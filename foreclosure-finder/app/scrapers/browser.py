"""Headless-browser scraper that works on any listing site.

Rather than parse HTML (which breaks on every redesign), it loads the real search page
in Chromium, records every JSON response the page's own JavaScript fetches, and pulls
listings out of those responses with app.normalize. It then pages through results and,
optionally, opens each listing's detail page to collect the full photo gallery.
"""
import asyncio
import json
import logging
import os
import re
from urllib.parse import urlparse

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from ..normalize import extract_listings, classify_photo

log = logging.getLogger("scraper")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
SKIP_IMG = re.compile(r"logo|icon|sprite|avatar|badge|banner|map|tile|marker|pixel|placeholder|"
                      r"\.svg|equal-housing|seal|flag", re.I)
NEXT_SELECTORS = [
    "button[aria-label*='next' i]:not([disabled])",
    "a[aria-label*='next' i]",
    "li.next:not(.disabled) a",
    "a:has-text('Next')",
    "button:has-text('Next'):not([disabled])",
    ".pagination-next:not(.disabled)",
    "a[rel='next']",
]


def _launch_kwargs():
    # Set CHROMIUM_PATH to use a specific Chrome/Chromium binary instead of Playwright's own.
    exe = os.environ.get("CHROMIUM_PATH")
    return {"headless": True, **({"executable_path": exe} if exe else {})}


class BrowserScraper:
    def __init__(self, source: str, delay: float = 1.5, max_pages: int = 20, details: bool = True,
                 max_details: int = 200):
        self.source = source
        self.delay = delay
        self.max_pages = max_pages
        self.details = details
        self.max_details = max_details
        self.found: dict[str, dict] = {}

    def _absorb(self, data, base_url):
        n = 0
        for p in extract_listings(data, self.source, base_url):
            key = p["source_id"]
            if key in self.found:
                old = self.found[key]
                for k, v in p.items():
                    if v and not old.get(k):
                        old[k] = v
                urls = {ph["url"] for ph in old["photos"]}
                old["photos"] += [ph for ph in p["photos"] if ph["url"] not in urls]
            else:
                self.found[key] = p
                n += 1
        return n

    async def _attach_json_listener(self, page, sink: list):
        async def on_response(resp):
            ct = resp.headers.get("content-type", "")
            if "json" not in ct and not resp.url.split("?")[0].endswith(".json"):
                return
            try:
                sink.append((resp.url, await resp.json()))
            except Exception:
                pass
        page.on("response", lambda r: asyncio.ensure_future(on_response(r)))

    async def _embedded_json(self, page):
        """Many sites ship initial results inside the HTML (__NEXT_DATA__, ld+json, window state)."""
        blobs = await page.evaluate("""() => {
            const out = [];
            document.querySelectorAll('script[type="application/json"], script[type="application/ld+json"], script#__NEXT_DATA__')
              .forEach(s => { try { out.push(JSON.parse(s.textContent)); } catch (e) {} });
            for (const k of ['__INITIAL_STATE__', '__PRELOADED_STATE__', '__NUXT__', '__APOLLO_STATE__']) {
              try { if (window[k]) out.push(JSON.parse(JSON.stringify(window[k]))); } catch (e) {}
            }
            return out;
        }""")
        return blobs

    async def scrape_search(self, ctx, url: str):
        page = await ctx.new_page()
        captured: list = []
        await self._attach_json_listener(page, captured)
        log.info("[%s] loading %s", self.source, url)
        try:
            await page.goto(url, wait_until="networkidle", timeout=60_000)
        except PWTimeout:
            log.warning("[%s] page slow to settle, continuing", self.source)
        for pg in range(self.max_pages):
            # Scroll to trigger lazy loading / infinite scroll.
            for _ in range(6):
                await page.mouse.wheel(0, 4000)
                await page.wait_for_timeout(400)
            await page.wait_for_timeout(int(self.delay * 1000))
            for blob in await self._embedded_json(page):
                self._absorb(blob, page.url)
            new = 0
            while captured:
                rurl, data = captured.pop(0)
                new += self._absorb(data, rurl)
            log.info("[%s] page %d: +%d listings (total %d)", self.source, pg + 1, new,
                     len(self.found))
            clicked = False
            for sel in NEXT_SELECTORS:
                loc = page.locator(sel).first
                try:
                    if await loc.count() and await loc.is_visible():
                        await loc.click(timeout=5000)
                        await page.wait_for_load_state("networkidle", timeout=30_000)
                        clicked = True
                        break
                except Exception:
                    continue
            if not clicked:
                break
        await page.close()

    async def scrape_detail(self, ctx, p: dict):
        page = await ctx.new_page()
        captured: list = []
        await self._attach_json_listener(page, captured)
        try:
            await page.goto(p["listing_url"], wait_until="networkidle", timeout=45_000)
        except PWTimeout:
            pass
        except Exception as e:
            log.debug("detail failed %s: %s", p["listing_url"], e)
            await page.close()
            return
        await page.wait_for_timeout(int(self.delay * 1000))
        # Merge any richer JSON for this listing (descriptions, full photo arrays, lat/lng).
        for blob in await self._embedded_json(page) + [d for _, d in captured]:
            for q in extract_listings(blob, self.source, page.url):
                if q["source_id"] == p["source_id"] or q["address"] == p["address"]:
                    for k, v in q.items():
                        if v and not p.get(k):
                            p[k] = v
                    have = {ph["url"] for ph in p["photos"]}
                    p["photos"] += [ph for ph in q["photos"] if ph["url"] not in have]
                    p["amenities"] = sorted(set(p.get("amenities", [])) | set(q.get("amenities", [])))
        # Fallback: grab the large <img> tags in the gallery.
        imgs = await page.evaluate("""() => Array.from(document.images)
            .filter(i => Math.max(i.naturalWidth, i.width) >= 300 || i.dataset.src || i.dataset.lazy)
            .map(i => ({url: i.dataset.src || i.dataset.lazy || i.currentSrc || i.src,
                        caption: i.alt || i.title || null}))
            .map(o => ({...o, url: new URL(o.url, location.href).href}))""")
        have = {ph["url"] for ph in p["photos"]}
        host = urlparse(p["listing_url"]).netloc
        for im in imgs:
            u = im["url"]
            if not u or not u.startswith("http") or u in have or SKIP_IMG.search(u):
                continue
            have.add(u)
            p["photos"].append({"url": u, "caption": im["caption"]})
        for i, ph in enumerate(p["photos"]):
            if not ph.get("kind") or ph["kind"] == "unknown":
                ph["kind"] = classify_photo(ph["url"], ph.get("caption"), i)
        if not p.get("description"):
            txt = await page.evaluate("() => document.body.innerText.slice(0, 20000)")
            from ..normalize import detect_amenities
            p["amenities"] = sorted(set(p.get("amenities", [])) | set(detect_amenities(txt)))
        log.debug("detail %s (%s): %d photos", p["address"], host, len(p["photos"]))
        await page.close()

    async def run(self, urls: list[str]) -> list[dict]:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(**_launch_kwargs())
            ctx = await browser.new_context(user_agent=UA, viewport={"width": 1400, "height": 1000})
            for u in urls:
                try:
                    await self.scrape_search(ctx, u)
                except Exception as e:
                    log.error("[%s] search failed for %s: %s", self.source, u, e)
            if self.details:
                todo = [p for p in self.found.values() if p.get("listing_url")][: self.max_details]
                log.info("[%s] fetching %d detail pages for photos", self.source, len(todo))
                for i, p in enumerate(todo, 1):
                    await self.scrape_detail(ctx, p)
                    await asyncio.sleep(self.delay)  # be polite to the source site
                    if i % 20 == 0:
                        log.info("[%s] details %d/%d", self.source, i, len(todo))
            await browser.close()
        return list(self.found.values())
