"""HUD Home Store (hudhomestore.gov) scraper.

HUD renders each search page on the server and embeds the full result set as JSON in a
hidden <input id="available_prop">, and each property page embeds its details in
<input id="prop_details">. So plain HTTP requests are enough; no browser needed.
"""
import html
import json
import logging
import re
import time

import httpx

from ..normalize import detect_amenities

log = logging.getLogger("scraper.hud")

BASE = "https://www.hudhomestore.gov"
PHOTO = "https://res.cloudinary.com/yardi/image/upload/q_auto,f_auto,c_limit,w_1600/hhs/{}"
STATES = ("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE "
          "NV NH NJ NM NY NC ND OH OK OR PA PR RI SC SD TN TX UT VT VA WA WV WI WY").split()
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
EXTERIOR = re.compile(r"front|back|rear|side|street|exterior|ext\b|yard|aerial|garage|pool|"
                      r"porch|deck|patio|roof|shed|fence|driveway|elevation|view|^e\d+$", re.I)
INTERIOR = re.compile(r"interior|int\b|kitchen|bath|bed|living|dining|family|den\b|laundry|"
                      r"basement|room|hall|stair|closet|office|master|primary|sunroom|foyer|"
                      r"utility|pantry|loft|attic|fireplace|^i\d+$", re.I)


def _hidden_json(page: str, input_id: str):
    m = re.search(r'id="%s"\s+value=(["\'])(.*?)\1' % re.escape(input_id), page, re.S)
    if not m:
        return None
    try:
        return json.loads(html.unescape(m.group(2)))
    except json.JSONDecodeError:
        return None


def _num(v):
    try:
        return float(str(v).replace(",", "").replace("$", "")) if v not in (None, "") else None
    except ValueError:
        return None


def photo_label(name: str) -> str:
    """'Primarybedroom_585140.png' -> 'Primarybedroom'; 'i1_73985124.png' -> 'i1'."""
    base = re.sub(r"\.\w+$", "", name)
    base = re.sub(r"[_ -]+\d{5,}$", "", base)  # trailing upload id
    return base.replace("_", " ").strip()


def photo_kind(name: str, index: int) -> str:
    label = photo_label(name)
    if INTERIOR.search(label):
        return "interior"
    if EXTERIOR.search(label):
        return "exterior"
    return "exterior" if index == 0 else "unknown"


def _photos(gallery: str | None, thumb: str | None) -> list[dict]:
    names = re.findall(r'"?([^",]+\.(?:png|jpe?g|gif|webp))"?', gallery or "", re.I)
    if not names and thumb and "NoImage" not in thumb:
        names = [thumb.rsplit("/", 1)[-1]]
    out = []
    for i, n in enumerate(dict.fromkeys(names)):
        label = photo_label(n)
        if re.fullmatch(r"[ie]\d+", label, re.I):
            label = "Interior" if label[0].lower() == "i" else "Exterior"
        elif re.fullmatch(r"[\d ()]+|img \d+|mls \d+|dsc\w*|photo ?\d*", label, re.I):
            label = None  # just a number: no useful caption
        else:
            label = label.title()
        out.append({"url": PHOTO.format(n), "kind": photo_kind(n, i), "caption": label})
    return out


def _amenities(r: dict, d: dict | None) -> list[str]:
    parts = [r.get("inAmenities"), r.get("outAmenities"), r.get("parkingType"),
             r.get("amenities"), r.get("propertyType")]
    found = set(detect_amenities(" ".join(p for p in parts if p)))
    fha = (r.get("fhaFinancing") or "").upper()
    if fha.startswith(("IN", "IE")):
        found.add("FHA Insurable")
    if d and str(d.get("Eligible203K", "")).lower() == "yes" or "IE" in fha:
        found.add("203k Eligible")
    if "owner occupant" in (r.get("eligibleBidders") or "").lower():
        found.add("Owner-Occupant Only")
    if (r.get("parkingType") or "").lower().startswith(("garage", "carport")):
        found.add("Garage")
    if r.get("numberOfStories") and _num(r["numberOfStories"]) == 1:
        found.add("Single Story")
    if d and (_num(d.get("LotSize")) or 0) >= 21780 and d.get("SqftAcreage") == "S":
        found.add("Large Lot")
    return sorted(found)


def _describe(r: dict, d: dict | None) -> str:
    """HUD has no free-text remarks, so build a readable summary from the structured fields."""
    lines = []
    if r.get("propertyType"):
        lines.append(f"{r['propertyType']} in {r.get('propertyCounty') or ''} County.".replace(" in  County", ""))
    for label, val in (("Indoor amenities", r.get("inAmenities")), ("Outdoor amenities", r.get("outAmenities")),
                       ("Parking", r.get("parkingType"))):
        if val:
            lines.append(f"{label}: {val.strip(', ').replace(',', ', ')}")
    lines.append(f"FHA financing: {r.get('fhaFinancing') or 'n/a'}")
    if d:
        if d.get("HOAFees"):
            lines.append(f"HOA fees: ${d['HOAFees']:,.0f} {(d.get('HOAFeePeriod') or '').lower()}")
        for k, lbl in (("FEMAFloodZone", "FEMA flood zone"), ("OpportunityZone", "Opportunity zone"),
                       ("RevitalizationArea", "Revitalization area")):
            if str(d.get(k)).lower() == "yes":
                lines.append(f"{lbl}: yes")
    lines.append(f"Eligible bidders: {r.get('eligibleBidders') or 'n/a'}. "
                 f"Listing period: {r.get('listingPeriod') or 'n/a'}.")
    if r.get("bidOpenDate"):
        lines.append(f"Bids open {r['bidOpenDate']}; period deadline {r.get('periodDeadlineDate') or 'n/a'}.")
    if r.get("SpecialProgram100Down") == "Yes":
        lines.append("Eligible for the FHA $100-down incentive.")
    return "\n".join(lines)


def to_property(r: dict, d: dict | None = None) -> dict:
    case = r["propertyCaseNumber"]
    p = {
        "source": "hud", "source_id": case,
        "address": r.get("propertyAddress"), "city": r.get("propertyCity"),
        "state": r.get("propertyState"), "zip": (r.get("propertyZip") or "")[:5] or None,
        "lat": _num(r.get("latitude")), "lng": _num(r.get("longitude")),
        "price": _num(r.get("listPrice")),
        "beds": _num(r.get("bedrooms")),
        "baths": r.get("bathroomsdecimal") or _num(r.get("bathrooms")),
        "sqft": _num(r.get("squareFootage")) or None,
        "year_built": int(_num(r.get("yearBuilt")) or 0) or None,
        "property_type": r.get("propertyType"),
        "status": r.get("propertyStatusDesc") or r.get("propertyStatus"),
        "listing_url": f"{BASE}/propertydetails?caseNumber={case}",
        "photos": _photos(r.get("galleryImages"), r.get("propertyThumb")),
        "raw": {"search": r, "detail": d},
    }
    if d:
        lot = _num(d.get("LotSize"))
        if lot:
            p["lot_sqft"] = lot * 43560 if d.get("SqftAcreage") == "A" else lot
    p["amenities"] = _amenities(r, d)
    p["description"] = _describe(r, d)
    return p


def scrape(states=None, details=True, delay=1.0, max_details=None) -> list[dict]:
    states = [s.upper() for s in (states or STATES)]
    out = []
    with httpx.Client(headers=HEADERS, timeout=45, follow_redirects=True) as c:
        for st in states:
            try:
                page = c.get(f"{BASE}/searchresult", params={"citystate": st}).text
            except httpx.HTTPError as e:
                log.error("[hud] %s search failed: %s", st, e)
                continue
            rows = [r for r in (_hidden_json(page, "available_prop") or [])
                    if r.get("propertyState", "").upper() == st]
            log.info("[hud] %s: %d listings", st, len(rows))
            for i, r in enumerate(rows):
                d = None
                if details and (max_details is None or i < max_details):
                    try:
                        dp = c.get(f"{BASE}/propertydetails",
                                   params={"caseNumber": r["propertyCaseNumber"]}).text
                        d = _hidden_json(dp, "prop_details")
                    except httpx.HTTPError as e:
                        log.debug("detail %s failed: %s", r["propertyCaseNumber"], e)
                    time.sleep(delay)
                out.append(to_property(r, d))
            time.sleep(delay)
    return out
