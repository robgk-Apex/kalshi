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

from . import db
from .scrapers.browser import BrowserScraper

SOURCES = json.load(open(os.path.join(os.path.dirname(__file__), "sources.json")))
SOURCES.pop("_note", None)
SOURCES.pop("demo", None)


def main():
    ap = argparse.ArgumentParser(description="Scrape foreclosure / REO listings into the local DB")
    ap.add_argument("--source", default="hud", help=f"one of {', '.join(SOURCES)} or 'all'")
    ap.add_argument("--state", action="append", default=[], help="2-letter state (repeatable)")
    ap.add_argument("--url", action="append", default=[], help="explicit search-results URL")
    ap.add_argument("--max-pages", type=int, default=20)
    ap.add_argument("--max-details", type=int, default=200)
    ap.add_argument("--no-details", action="store_true", help="skip detail pages (fewer photos)")
    ap.add_argument("--delay", type=float, default=1.5, help="seconds between requests")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    db.init()
    names = list(SOURCES) if a.source == "all" else [a.source]
    for name in names:
        if a.url:
            urls = a.url
        else:
            states = [s.upper() for s in a.state] or ["GA"]
            urls = [u.format(state=s) for u in SOURCES[name]["search_urls"] for s in states]
        s = BrowserScraper(name, delay=a.delay, max_pages=a.max_pages,
                           details=not a.no_details, max_details=a.max_details)
        listings = asyncio.run(s.run(urls))
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
