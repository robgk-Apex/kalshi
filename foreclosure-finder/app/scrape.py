"""Command-line entry point.

    python -m app.scrape --source hud --state GA --state FL
    python -m app.scrape --source all --state TX --no-details
    python -m app.scrape --source hud --url "https://www.hudhomestore.gov/searchresult?citystate=Atlanta,GA"
"""
import argparse
import asyncio
import json
import logging
import os
import time

from . import db
from .scrapers import hud, homepath, homesteps

SOURCES = json.load(open(os.path.join(os.path.dirname(__file__), "sources.json")))
SOURCES.pop("_note", None)
SOURCES.pop("demo", None)
DEDICATED = {"hud": hud, "homepath": homepath, "homesteps": homesteps}


def main():
    ap = argparse.ArgumentParser(description="Scrape foreclosure / REO listings into the local DB")
    ap.add_argument("--source", default="hud", help=f"one of {', '.join(SOURCES)} or 'all'")
    ap.add_argument("--state", action="append", default=[], help="2-letter state (repeatable)")
    ap.add_argument("--url", action="append", default=[], help="explicit search-results URL")
    ap.add_argument("--max-pages", type=int, default=20)
    ap.add_argument("--max-details", type=int, default=200)
    ap.add_argument("--no-details", action="store_true", help="skip detail pages (fewer photos)")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    db.init()
    names = list(SOURCES) if a.source == "all" else [a.source]
    for name in names:
        if name in DEDICATED and not a.url:
            # Dedicated scrapers use each site's own data feed. No --state = whole country.
            started = time.time()
            listings = DEDICATED[name].scrape(a.state or None, details=not a.no_details,
                                              delay=a.delay)
            _save(name, listings)
            if listings and not a.state:
                # Full nationwide run: anything not seen this time has sold or been pulled.
                with db.connect() as c:
                    n = c.execute("DELETE FROM properties WHERE source=? AND updated_at < ?",
                                  (name, started)).rowcount
                logging.info("[%s] removed %d listings no longer for sale", name, n)
            continue
        if a.url:
            urls = a.url
        else:
            states = [s.upper() for s in a.state] or ["GA"]
            urls = [u.format(state=s) for u in SOURCES[name]["search_urls"] for s in states]
        from .scrapers.browser import BrowserScraper  # needs Playwright; only for generic sources
        s = BrowserScraper(name, delay=a.delay, max_pages=a.max_pages,
                           details=not a.no_details, max_details=a.max_details)
        listings = asyncio.run(s.run(urls))
        _save(name, listings)


def _save(name, listings):
    with db.connect() as c:
        for p in listings:
            db.upsert_property(c, p)
    photos = sum(len(p["photos"]) for p in listings)
    logging.info("[%s] saved %d listings, %d photos", name, len(listings), photos)
    if not listings:
        logging.warning("[%s] no listings found. The site may have changed its URL or "
                        "blocked automated access; see app/sources.json.", name)


if __name__ == "__main__":
    main()
