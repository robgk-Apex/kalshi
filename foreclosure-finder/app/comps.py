"""Comparable sales for a property.

Primary: RentCast's valuation API (real recent sold/listed comps + an estimated value).
Set RENTCAST_API_KEY (free tier at https://app.rentcast.io). Results are cached in the DB
for 7 days so you don't burn API calls.

Fallback (no key): nearby listings already in our own database with similar size. These are
other distressed listings, not closed sales, and the UI labels them that way.
"""
import json
import math
import os
import statistics
import time

import httpx

from . import db

CACHE_TTL = 7 * 86400


def haversine_mi(a_lat, a_lng, b_lat, b_lng):
    r = 3958.8
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lng - a_lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _summary(subject, comps):
    ppsf = [c["price"] / c["sqft"] for c in comps if c.get("price") and c.get("sqft")]
    prices = [c["price"] for c in comps if c.get("price")]
    out = {
        "count": len(comps),
        "median_price": statistics.median(prices) if prices else None,
        "median_ppsf": statistics.median(ppsf) if ppsf else None,
    }
    if out["median_ppsf"] and subject.get("sqft"):
        out["implied_value"] = round(out["median_ppsf"] * subject["sqft"], -2)
        if subject.get("price"):
            out["discount_pct"] = round(100 * (1 - subject["price"] / out["implied_value"]), 1)
    return out


def rentcast_comps(p: dict, key: str) -> dict:
    addr = ", ".join(x for x in [p.get("address"), p.get("city"),
                                 f"{p.get('state') or ''} {p.get('zip') or ''}".strip()] if x)
    params = {"address": addr, "compCount": 15}
    for k, v in (("bedrooms", p.get("beds")), ("bathrooms", p.get("baths")),
                 ("squareFootage", p.get("sqft"))):
        if v:
            params[k] = v
    if p.get("property_type"):
        params["propertyType"] = "Single Family"
    r = httpx.get("https://api.rentcast.io/v1/avm/value", params=params,
                  headers={"X-Api-Key": key, "Accept": "application/json"}, timeout=30)
    r.raise_for_status()
    d = r.json()
    comps = [{
        "address": c.get("formattedAddress") or c.get("addressLine1"),
        "price": c.get("price"),
        "beds": c.get("bedrooms"),
        "baths": c.get("bathrooms"),
        "sqft": c.get("squareFootage"),
        "year_built": c.get("yearBuilt"),
        "distance_mi": round(c["distance"], 2) if c.get("distance") is not None else None,
        "date": c.get("removedDate") or c.get("lastSeenDate") or c.get("listedDate"),
        "status": c.get("status"),
        "days_on_market": c.get("daysOnMarket"),
        "correlation": c.get("correlation"),
        "lat": c.get("latitude"), "lng": c.get("longitude"),
    } for c in d.get("comparables", [])]
    s = _summary(p, comps)
    s.update({"estimated_value": d.get("price"), "value_low": d.get("priceRangeLow"),
              "value_high": d.get("priceRangeHigh")})
    if s.get("estimated_value") and p.get("price"):
        s["discount_pct"] = round(100 * (1 - p["price"] / s["estimated_value"]), 1)
    return {"provider": "rentcast", "kind": "market comps (sold / recently listed)",
            "summary": s, "comps": comps}


def local_comps(c, p: dict, limit=12) -> dict:
    # Start close and widen until there are a few comps to compare against.
    for radius in (3, 5, 10, 25):
        out = _local_comps(c, p, radius, limit)
        if len(out["comps"]) >= 4:
            break
    out["radius_mi"] = radius
    return out


def _local_comps(c, p: dict, radius_mi=5.0, limit=12) -> dict:
    rows = c.execute("SELECT * FROM properties WHERE id != ? AND price IS NOT NULL", (p["id"],))
    cands = []
    for r in rows:
        r = dict(r)
        if p.get("lat") and r.get("lat") and p.get("lng") and r.get("lng"):
            d = haversine_mi(p["lat"], p["lng"], r["lat"], r["lng"])
            if d > radius_mi:
                continue
        elif p.get("zip") and r.get("zip") == p["zip"]:
            d = None
        else:
            continue
        if p.get("sqft") and r.get("sqft") and not (0.6 <= r["sqft"] / p["sqft"] <= 1.4):
            continue
        cands.append({"address": f"{r['address']}, {r['city'] or ''}", "price": r["price"],
                      "beds": r["beds"], "baths": r["baths"], "sqft": r["sqft"],
                      "year_built": r["year_built"],
                      "distance_mi": round(d, 2) if d is not None else None,
                      "status": r["status"] or "Listed", "date": None, "id": r["id"],
                      "lat": r["lat"], "lng": r["lng"], "source": r["source"]})
    cands.sort(key=lambda x: (x["distance_mi"] if x["distance_mi"] is not None else 99))
    cands = cands[:limit]
    return {"provider": "local",
            "kind": "nearby foreclosure listings (not closed sales). Add RENTCAST_API_KEY for real sold comps",
            "summary": _summary(p, cands), "comps": cands}


def get_comps(p: dict, refresh=False) -> dict:
    key = os.environ.get("RENTCAST_API_KEY")
    with db.connect() as c:
        if key and not refresh:
            row = c.execute("SELECT payload, fetched_at FROM comps_cache WHERE property_id=?",
                            (p["id"],)).fetchone()
            if row and time.time() - row["fetched_at"] < CACHE_TTL:
                return json.loads(row["payload"])
        if key:
            try:
                out = rentcast_comps(p, key)
                c.execute("INSERT OR REPLACE INTO comps_cache VALUES (?,?,?)",
                          (p["id"], json.dumps(out), time.time()))
                return out
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                why = {401: "RentCast rejected the API key", 403: "RentCast refused the request",
                       404: "RentCast has no data for this address",
                       429: "the RentCast monthly lookup limit is used up"}.get(
                           code, f"RentCast returned an error ({code})")
            except Exception:
                why = "RentCast couldn't be reached"
            out = local_comps(c, p)
            out["error"] = f"No sold comps: {why}."
            return out
        return local_comps(c, p)
