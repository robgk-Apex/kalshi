"""Fannie Mae HomePath scraper (homepath.fanniemae.com).

HomePath's own JSON API returns at most 400 homes per map box, so we split the map
into quadrants until each box comes back under the cap. listingTypes=5 limits results
to Fannie Mae-owned foreclosures (the site otherwise mixes in ordinary MLS listings).
"""
import logging
import time

import httpx

from ..normalize import detect_amenities

log = logging.getLogger("scraper.homepath")

BASE = "https://homepath.fanniemae.com"
CAP = 400
REGIONS = {  # south, west, north, east
    "CONUS": (24.3, -125.0, 49.5, -66.8), "AK": (51.0, -179.9, 71.5, -129.9),
    "HI": (18.8, -160.3, 22.3, -154.7), "PR": (17.8, -67.4, 18.6, -65.2),
}
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
           "Accept": "application/json"}


def _yn(v):
    return v is True or str(v).strip().lower() in ("y", "yes", "true", "1")


def to_property(s: dict, d: dict | None) -> dict:
    d = d or {}
    r = {**s, **d}
    geo = r.get("geoPoint") or {}
    pics = sorted(d.get("propertyPics") or [], key=lambda x: x.get("sequence") or 0)
    urls = [x["imageUrl"] for x in pics if x.get("imageUrl")] or \
           ([s["primHiResImageUrl"]] if s.get("primHiResImageUrl") else [])
    # HomePath photos carry no captions. The primary (first) photo is the front of the house;
    # the rest can't be told apart from file names, so they're left as "unknown".
    photos = [{"url": u, "kind": "exterior" if i == 0 else "unknown",
               "caption": "Front" if i == 0 else None} for i, u in enumerate(dict.fromkeys(urls))]
    baths = r.get("bathrooms")
    if baths is not None and r.get("partialBathroomCount"):
        baths = baths + 0.5 * r["partialBathroomCount"]
    am = set(detect_amenities(" ".join(str(r.get(k) or "") for k in
                                       ("features", "interiorDesc", "propUtilityDesc"))))
    for flag, name in (("fireplaceYn", "Fireplace"), ("poolPrivateYn", "Pool"),
                       ("waterfrontYn", "Waterfront")):
        if _yn(r.get(flag)):
            am.add(name)
    garage = (r.get("propGarageDesc") or "").strip()
    if garage and garage.lower() not in ("none", "0", "no"):
        am.add("Garage")
    if r.get("storiesTotal") == 1:
        am.add("Single Story")
    if (r.get("propLotSize") or 0) >= 21780:
        am.add("Large Lot")
    if r.get("firstLookProgramIndicator") == 1:
        am.add("Owner-Occupant Only")  # First Look period: owner-occupants & nonprofits only
    lines = [f"{r.get('propertyType') or 'Home'} owned by Fannie Mae"
             + (f" in {r['county'].title()}" if r.get("county") else "") + "."]
    if r.get("features"):
        lines.append(f"Features: {r['features']}")
    if r.get("propSubdivisionName"):
        lines.append(f"Subdivision: {r['propSubdivisionName']}")
    if r.get("propRealEstateTaxPaidAmount"):
        lines.append(f"Property taxes: ${r['propRealEstateTaxPaidAmount']:,.0f}"
                     f" ({r.get('propRealEstateTaxPaidYear') or 'n/a'})")
    for k, lbl in (("propElemSchoolDistrictName", "Elementary school"),
                   ("propHighSchoolDistrictName", "High school")):
        if r.get(k):
            lines.append(f"{lbl}: {r[k]}")
    if r.get("firstLookProgramIndicator") == 1:
        lines.append("In the First Look period: offers from owner-occupants, public entities "
                     "and nonprofits only.")
    if r.get("onlineOfferOnly"):
        lines.append("Offers are submitted online through HomePath.")
    if r.get("tenantOccupied"):
        lines.append("Tenant occupied.")
    return {
        "source": "homepath", "source_id": r["propertyUuid"],
        "address": (r.get("addressLine1") or "").title(), "city": r.get("city"),
        "state": r.get("state"), "zip": (r.get("zipCode") or "")[:5] or None,
        "lat": geo.get("latitude"), "lng": geo.get("longitude"),
        "price": r.get("price"), "beds": r.get("bedrooms"), "baths": baths,
        "sqft": r.get("sqft") or None, "lot_sqft": r.get("propLotSize") or None,
        "year_built": r.get("yearBuilt") or None, "property_type": r.get("propertyType"),
        "status": r.get("retailStatus") or r.get("equatorStatusLabel"),
        "listing_url": f"{BASE}/property-detail/{r['propertyUuid']}",
        "description": "\n".join(lines), "amenities": sorted(am), "photos": photos,
        "raw": {"search": s, "detail": d or None},
    }


def scrape(states=None, details=True, delay=0.7) -> list[dict]:
    states = {s.upper() for s in states} if states else None
    found: dict[str, dict] = {}
    with httpx.Client(headers=HEADERS, timeout=45) as c:
        def search(box, depth=0):
            s, w, n, e = box
            try:
                r = c.get(f"{BASE}/cfl/property-inventory/search",
                          params={"bounds": f"{s},{w},{n},{e}", "listingTypes": "5"})
                ps = r.json().get("properties") or []
            except (httpx.HTTPError, ValueError) as ex:
                log.error("[homepath] search %s failed: %s", box, ex)
                return
            time.sleep(delay)
            for p in ps:
                found[p["propertyUuid"]] = p
            if len(ps) >= CAP and depth < 14:
                ms, mw = (s + n) / 2, (w + e) / 2
                for b in ((s, w, ms, mw), (s, mw, ms, e), (ms, w, n, mw), (ms, mw, n, e)):
                    search(b, depth + 1)

        for name, box in REGIONS.items():
            if box[1] > box[3]:  # crosses the antimeridian / spans territories: skip
                continue
            search(box)
            log.info("[homepath] after %s: %d listings", name, len(found))
        rows = [p for p in found.values() if not states or (p.get("state") or "").upper() in states]
        out = []
        for i, sr in enumerate(rows, 1):
            d = None
            if details:
                try:
                    d = c.get(f"{BASE}/cfl/property-inventory/property/{sr['propertyUuid']}").json()
                except (httpx.HTTPError, ValueError) as ex:
                    log.debug("detail %s failed: %s", sr["propertyUuid"], ex)
                time.sleep(delay)
                if i % 100 == 0:
                    log.info("[homepath] details %d/%d", i, len(rows))
            out.append(to_property(sr, d))
    return out
