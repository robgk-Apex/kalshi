"""End-to-end test of the browser scraper against a local mock foreclosure site.

The mock mimics how real REO sites behave: results come from an XHR JSON API with
site-specific field names, there's a "Next" button, and photos live on detail pages.
Run:  python -m pytest tests/ -q
"""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.normalize import extract_listings, normalize
from app.scrapers.browser import BrowserScraper

LISTINGS = [
    {"propertyCaseNumber": f"105-{i:06d}", "PropertyAddress": {"Address1": f"{100+i} Main St",
     "City": "ATLANTA", "State": "ga", "ZipCode": "30310-1234"}, "ListPrice": f"${120000 + i*1000:,}",
     "Bedrooms": 3, "FullBaths": 1, "HalfBaths": 1, "SquareFootage": "1,450", "YearBuilt": 1978,
     "Latitude": 33.7, "Longitude": -84.4, "Status": "Available", "detailUrl": f"/property/{i}",
     "thumbnailUrl": f"/img/{i}/front.jpg", "Remarks": "Ranch with garage and fireplace."}
    for i in range(6)
]
PIXEL = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                      "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send(self, body, ct):
        self.send_response(200); self.send_header("content-type", ct); self.end_headers()
        self.wfile.write(body if isinstance(body, bytes) else body.encode())

    def do_GET(self):
        p = self.path
        if p.startswith("/api/search"):
            pg = int(p.split("page=")[1])
            self.send(json.dumps({"data": {"totalCount": 6, "items": LISTINGS[pg*3:(pg+1)*3]}}),
                      "application/json")
        elif p.startswith("/search"):
            self.send("""<html><body><div id=r></div><button id=nx aria-label="Next page">Next</button>
<script>let pg=0;function load(){fetch('/api/search?page='+pg).then(r=>r.json()).then(d=>{
document.getElementById('r').textContent=d.data.items.length; if(pg>=1)document.getElementById('nx').remove();});}
document.getElementById('nx').onclick=()=>{pg++;load();};load();</script></body></html>""", "text/html")
        elif p.startswith("/property/"):
            i = p.rsplit("/", 1)[1]
            imgs = "".join(f'<img src="/img/{i}/{n}.png" alt="{n}" width=640 height=480>'
                           for n in ["front", "kitchen", "bedroom-1", "backyard"])
            self.send(f"<html><body>{imgs}<img src='/img/logo.png' width=400></body></html>", "text/html")
        elif p.startswith("/img/"):
            self.send(PIXEL, "image/png")
        else:
            self.send_response(404); self.end_headers()


@pytest.fixture(scope="module")
def site():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_normalize_maps_site_specific_fields():
    p = normalize(LISTINGS[0], "hud", "https://x.test/")
    assert p["source_id"] == "105-000000"
    assert p["address"] == "100 Main St" and p["city"] == "Atlanta" and p["state"] == "GA"
    assert p["zip"] == "30310" and p["price"] == 120000 and p["baths"] == 1.5 and p["sqft"] == 1450
    assert p["listing_url"] == "https://x.test/property/0"
    assert {"Garage", "Fireplace", "Single Story"} <= set(p["amenities"])
    assert p["photos"][0]["kind"] == "exterior"


def test_extract_ignores_non_listing_json():
    assert extract_listings({"user": {"name": "a"}, "items": [{"x": 1}]}, "hud") == []


def test_browser_scraper_pages_and_collects_photos(site):
    s = BrowserScraper("hud", delay=0.2, max_pages=5, details=True)
    out = asyncio.run(s.run([f"{site}/search"]))
    assert len(out) == 6, "should follow the Next button to page 2"
    p = next(x for x in out if x["source_id"] == "105-000002")
    urls = [ph["url"] for ph in p["photos"]]
    assert not any("logo" in u for u in urls)
    kinds = {ph["url"].rsplit("/", 1)[1]: ph["kind"] for ph in p["photos"]}
    assert kinds["kitchen.png"] == "interior" and kinds["bedroom-1.png"] == "interior"
    assert kinds["backyard.png"] == "exterior"
