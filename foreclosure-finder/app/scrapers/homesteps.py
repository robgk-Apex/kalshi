"""Freddie Mac HomeSteps scraper (homesteps.com).

Search pages list 25 homes each as schema.org RealEstateListing JSON-LD. Each detail
page adds coordinates, the full description, every photo, and a "Label: value" fact list
(sq ft, year built, lot size, garage, HOA, taxes...).
"""
import html
import json
import logging
import re
import time

import httpx

from ..normalize import classify_photo, detect_amenities
from .hud import STATES

log = logging.getLogger("scraper.homesteps")
BASE = "https://www.homesteps.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


def _ld_listings(page: str) -> list[dict]:
    out = []
    for blob in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
        try:
            d = json.loads(blob)
        except json.JSONDecodeError:
            continue
        types = d.get("@type") if isinstance(d, dict) else None
        if types and "RealEstateListing" in (types if isinstance(types, list) else [types]):
            out.append(d)
    return out


def _num(v):
    m = re.search(r"-?\d[\d,]*\.?\d*", str(v or ""))
    return float(m.group(0).replace(",", "")) if m else None


def _facts(page: str) -> dict:
    text = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)
    text = html.unescape(re.sub(r"<[^>]+>", "\n", text))
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    facts = {}
    for a, b in zip(lines, lines[1:]):
        if a.endswith(":") and len(a) < 40 and not b.endswith(":"):
            facts.setdefault(a[:-1].strip(), b)
    m = re.search(r"([\d,]+)\s*sq\.?\s*ft", text)
    if m:
        facts.setdefault("_sqft", m.group(1))
    return facts


def to_property(card: dict, detail: dict | None, facts: dict) -> dict:
    d = detail or card
    loc = d.get("@location") or card.get("@location") or {}
    addr = loc.get("address") or {}
    geo = loc.get("geo") or {}
    offer = card.get("offers") or d.get("offers") or {}
    item = offer.get("itemOffered") or {}
    status = next((p.get("value") for p in card.get("additionalProperty") or []
                   if p.get("name") == "Status"), None)
    imgs = d.get("image") or []
    imgs = [i.get("url") if isinstance(i, dict) else i for i in (imgs if isinstance(imgs, list) else [imgs])]
    imgs = [u for u in dict.fromkeys(imgs) if u]
    # Sort by the photo number at the end of the file name (…-Circle-3.jpg).
    imgs.sort(key=lambda u: int(m.group(1)) if (m := re.search(r"-(\d+)\.\w+$", u)) else 0)
    photos = [{"url": u, "kind": classify_photo(u, None, i) if i == 0 else "unknown",
               "caption": "Front" if i == 0 else None} for i, u in enumerate(imgs)]
    desc = d.get("description") or ""
    lot = facts.get("Lot Size") or facts.get("Lot Size (Acres)") or facts.get("Acres")
    lot_sqft = None
    if lot:
        n = _num(lot)
        if n:
            lot_sqft = n * 43560 if ("acre" in lot.lower() or n < 100) else n
    am = set(detect_amenities(" ".join([desc] + [v for k, v in facts.items() if k != "_sqft"])))
    am.discard("Large Lot")
    if lot_sqft and lot_sqft >= 21780:  # half an acre or more
        am.add("Large Lot")
    if (_num(facts.get("Garage Spaces")) or 0) > 0 or "garage" in (facts.get("Parking") or "").lower():
        am.add("Garage")
    extra = []
    for k in ("Year Built", "HOA Fees", "HOA Frequency", "Property Tax", "Tax Year", "County",
              "Subdivision", "Elementary School", "Middle School", "High School"):
        if facts.get(k):
            extra.append(f"{k}: {facts[k]}")
    yb = _num(facts.get("Year Built"))
    return {
        "source": "homesteps", "source_id": card["url"].rstrip("/").rsplit("/", 1)[-1],
        "address": addr.get("streetAddress"), "city": addr.get("addressLocality"),
        "state": addr.get("addressRegion"), "zip": (addr.get("postalCode") or "")[:5] or None,
        "lat": _num(geo.get("latitude")), "lng": _num(geo.get("longitude")),
        "price": _num(offer.get("price")),
        "beds": _num(item.get("numberOfBedrooms")), "baths": _num(item.get("numberOfBathroomsTotal")),
        "sqft": _num(facts.get("Square Feet") or facts.get("_sqft")), "lot_sqft": lot_sqft,
        "year_built": int(yb) if yb and 1700 < yb < 2100 else None,
        "property_type": facts.get("Property Type") or item.get("accommodationCategory"),
        "status": status, "listing_url": card["url"],
        "description": (desc + ("\n\n" + "\n".join(extra) if extra else "")).strip() or None,
        "amenities": sorted(am), "photos": photos,
        "raw": {"card": card, "detail": detail, "facts": facts},
    }


def scrape(states=None, details=True, delay=1.0) -> list[dict]:
    states = [s.upper() for s in (states or STATES)]
    out, seen = [], set()
    with httpx.Client(headers=HEADERS, timeout=45, follow_redirects=True) as c:
        for st in states:
            cards = []
            for pg in range(0, 40):
                try:
                    page = c.get(f"{BASE}/listing/search", params={"search": st, "page": pg}).text
                except httpx.HTTPError as e:
                    log.error("[homesteps] %s page %d failed: %s", st, pg, e)
                    break
                got = [x for x in _ld_listings(page)
                       if ((x.get("@location") or {}).get("address") or {}).get("addressRegion") == st
                       and x.get("url") not in seen]
                time.sleep(delay)
                if not got:
                    break
                for x in got:
                    seen.add(x["url"])
                cards += got
            log.info("[homesteps] %s: %d listings", st, len(cards))
            for card in cards:
                detail, facts = None, {}
                if details:
                    try:
                        dp = c.get(card["url"]).text
                        found = _ld_listings(dp)
                        detail = found[0] if found else None
                        facts = _facts(dp)
                    except httpx.HTTPError as e:
                        log.debug("detail %s failed: %s", card["url"], e)
                    time.sleep(delay)
                out.append(to_property(card, detail, facts))
    return out
