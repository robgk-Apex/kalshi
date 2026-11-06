"""SQLite storage for scraped foreclosure listings, their photos and cached comps."""
import json
import os
import sqlite3
import time
from contextlib import contextmanager

DB_PATH = os.environ.get(
    "FF_DB", os.path.join(os.path.dirname(__file__), "..", "data", "listings.db")
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS properties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    address TEXT, city TEXT, state TEXT, zip TEXT,
    lat REAL, lng REAL,
    price REAL,
    beds REAL, baths REAL, sqft REAL, lot_sqft REAL, year_built INTEGER,
    property_type TEXT, status TEXT,
    listing_url TEXT, description TEXT,
    amenities TEXT DEFAULT '[]',
    raw TEXT,
    first_seen REAL, updated_at REAL,
    UNIQUE(source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_prop_loc ON properties(state, city, zip);
CREATE INDEX IF NOT EXISTS idx_prop_price ON properties(price);
CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    property_id INTEGER NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    kind TEXT DEFAULT 'unknown',   -- exterior | interior | unknown
    caption TEXT,
    position INTEGER DEFAULT 0,
    UNIQUE(property_id, url)
);
CREATE TABLE IF NOT EXISTS comps_cache (
    property_id INTEGER PRIMARY KEY,
    payload TEXT NOT NULL,
    fetched_at REAL NOT NULL
);
"""

FIELDS = [
    "address", "city", "state", "zip", "lat", "lng", "price", "beds", "baths",
    "sqft", "lot_sqft", "year_built", "property_type", "status", "listing_url",
    "description",
]


@contextmanager
def connect():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init():
    with connect() as c:
        c.executescript(SCHEMA)


def upsert_property(c, p: dict) -> int:
    """Insert or update one normalized listing; returns its row id. Photos are merged."""
    now = time.time()
    vals = {k: p.get(k) for k in FIELDS}
    vals["amenities"] = json.dumps(sorted(set(p.get("amenities") or [])))
    vals["raw"] = json.dumps(p.get("raw"), default=str)[:200_000] if p.get("raw") else None
    cols = list(vals.keys())
    row = c.execute(
        "SELECT id FROM properties WHERE source=? AND source_id=?",
        (p["source"], str(p["source_id"])),
    ).fetchone()
    if row:
        pid = row["id"]
        # Only overwrite with non-null values so a sparse re-scrape doesn't wipe details.
        sets = ", ".join(f"{k}=COALESCE(?, {k})" for k in cols)
        c.execute(
            f"UPDATE properties SET {sets}, updated_at=? WHERE id=?",
            [vals[k] for k in cols] + [now, pid],
        )
    else:
        c.execute(
            f"INSERT INTO properties (source, source_id, {', '.join(cols)}, first_seen, updated_at) "
            f"VALUES (?, ?, {', '.join('?' for _ in cols)}, ?, ?)",
            [p["source"], str(p["source_id"])] + [vals[k] for k in cols] + [now, now],
        )
        pid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    for i, ph in enumerate(p.get("photos") or []):
        c.execute(
            "INSERT INTO photos (property_id, url, kind, caption, position) VALUES (?,?,?,?,?) "
            "ON CONFLICT(property_id, url) DO UPDATE SET kind=excluded.kind, "
            "caption=COALESCE(excluded.caption, photos.caption)",
            (pid, ph["url"], ph.get("kind", "unknown"), ph.get("caption"), i),
        )
    return pid


def row_to_dict(r) -> dict:
    d = dict(r)
    d["amenities"] = json.loads(d.get("amenities") or "[]")
    d.pop("raw", None)
    return d
