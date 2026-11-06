"""FastAPI app: JSON API + the static single-page site.

    uvicorn app.server:app --reload --port 8000
"""
import json
import os

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .comps import get_comps, haversine_mi

STATIC = os.path.join(os.path.dirname(__file__), "..", "static")
SOURCES = json.load(open(os.path.join(os.path.dirname(__file__), "sources.json")))
SOURCES.pop("_note", None)

app = FastAPI(title="Foreclosure Finder")
db.init()

SORTS = {
    "price_asc": "price ASC", "price_desc": "price DESC", "newest": "first_seen DESC",
    "sqft_desc": "sqft DESC", "ppsf_asc": "(price / NULLIF(sqft, 0)) ASC",
}


def _cover_photos(c, ids):
    if not ids:
        return {}
    q = ",".join("?" * len(ids))
    out = {}
    for r in c.execute(
        f"SELECT property_id, url, kind FROM photos WHERE property_id IN ({q}) "
        f"ORDER BY property_id, (kind='exterior') DESC, position", ids):
        out.setdefault(r["property_id"], {"cover": r["url"], "count": 0})
        out[r["property_id"]]["count"] += 1
    return out


@app.get("/api/properties")
def list_properties(
    q: str | None = None, state: str | None = None, city: str | None = None,
    zip: str | None = None, source: str | None = None,
    min_price: float | None = None, max_price: float | None = None,
    min_beds: float | None = None, min_baths: float | None = None,
    min_sqft: float | None = None, max_sqft: float | None = None,
    amenities: list[str] = Query(default=[]),
    lat: float | None = None, lng: float | None = None, radius_mi: float | None = None,
    sort: str = "price_asc", page: int = 1, per_page: int = Query(default=24, le=200),
):
    where, args = ["1=1"], []
    if q:
        where.append("(address LIKE ? OR city LIKE ? OR zip LIKE ? OR description LIKE ?)")
        args += [f"%{q}%"] * 4
    for col, val in (("state", state and state.upper()), ("zip", zip), ("source", source)):
        if val:
            where.append(f"{col} = ?")
            args.append(val)
    if city:
        where.append("city LIKE ?")
        args.append(city)
    for col, op, val in (("price", ">=", min_price), ("price", "<=", max_price),
                         ("beds", ">=", min_beds), ("baths", ">=", min_baths),
                         ("sqft", ">=", min_sqft), ("sqft", "<=", max_sqft)):
        if val is not None:
            where.append(f"{col} {op} ?")
            args.append(val)
    for a in amenities:
        where.append("amenities LIKE ?")
        args.append(f'%"{a}"%')
    order = SORTS.get(sort, SORTS["price_asc"])
    with db.connect() as c:
        rows = [db.row_to_dict(r) for r in c.execute(
            f"SELECT * FROM properties WHERE {' AND '.join(where)} ORDER BY {order} NULLS LAST",
            args)]
        if lat is not None and lng is not None and radius_mi:
            rows = [r for r in rows if r["lat"] and r["lng"]
                    and haversine_mi(lat, lng, r["lat"], r["lng"]) <= radius_mi]
        total = len(rows)
        page_rows = rows[(page - 1) * per_page: page * per_page]
        covers = _cover_photos(c, [r["id"] for r in page_rows])
        for r in page_rows:
            r["cover_photo"] = covers.get(r["id"], {}).get("cover")
            r["photo_count"] = covers.get(r["id"], {}).get("count", 0)
            r.pop("description", None)
        # Lightweight map pins for every match, not just this page.
        pins = [{"id": r["id"], "lat": r["lat"], "lng": r["lng"], "price": r["price"]}
                for r in rows if r["lat"] and r["lng"]][:2000]
    return {"total": total, "page": page, "per_page": per_page, "results": page_rows,
            "pins": pins}


@app.get("/api/facets")
def facets():
    with db.connect() as c:
        states = [dict(r) for r in c.execute(
            "SELECT state, COUNT(*) n FROM properties WHERE state IS NOT NULL "
            "GROUP BY state ORDER BY state")]
        cities = [dict(r) for r in c.execute(
            "SELECT state, city, COUNT(*) n FROM properties WHERE city IS NOT NULL "
            "GROUP BY state, city ORDER BY n DESC LIMIT 500")]
        sources = [dict(r) for r in c.execute(
            "SELECT source, COUNT(*) n FROM properties GROUP BY source")]
        am = {}
        for (a,) in c.execute("SELECT amenities FROM properties"):
            for x in json.loads(a or "[]"):
                am[x] = am.get(x, 0) + 1
        pr = c.execute("SELECT MIN(price) lo, MAX(price) hi, COUNT(*) n FROM properties").fetchone()
    for s in sources:
        s["name"] = SOURCES.get(s["source"], {}).get("name", s["source"])
    return {"states": states, "cities": cities, "sources": sources,
            "amenities": sorted(({"name": k, "n": v} for k, v in am.items()),
                                key=lambda x: -x["n"]),
            "price": dict(pr)}


def _get(pid: int) -> dict:
    with db.connect() as c:
        r = c.execute("SELECT * FROM properties WHERE id=?", (pid,)).fetchone()
        if not r:
            raise HTTPException(404, "Property not found")
        p = db.row_to_dict(r)
        p["photos"] = [dict(x) for x in c.execute(
            "SELECT url, kind, caption FROM photos WHERE property_id=? ORDER BY position", (pid,))]
    return p


@app.get("/api/properties/{pid}")
def property_detail(pid: int):
    p = _get(pid)
    p["source_name"] = SOURCES.get(p["source"], {}).get("name", p["source"])
    p["price_per_sqft"] = round(p["price"] / p["sqft"], 2) if p.get("price") and p.get("sqft") else None
    return p


@app.get("/api/properties/{pid}/comps")
def property_comps(pid: int, refresh: bool = False):
    return get_comps(_get(pid), refresh=refresh)


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
@app.get("/property/{pid}")
def index(pid: int | None = None):
    return FileResponse(os.path.join(STATIC, "index.html"))
