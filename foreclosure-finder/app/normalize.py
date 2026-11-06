"""Turn arbitrary listing JSON (from any foreclosure site's API) into one common shape.

Sites change their field names often, so instead of hard-coding one schema we match
keys case-insensitively against alias lists, and find listing arrays anywhere in a
JSON response by looking for lists of objects that have both a price and an address.
"""
import re
from urllib.parse import urljoin


def _k(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


ALIASES = {
    "source_id": ["caseNumber", "propertyCaseNumber", "fhaCaseNumber", "propertyId", "listingId",
                  "reoId", "assetId", "loanNumber", "mlsNumber", "id", "propertyNumber"],
    "price": ["listPrice", "listingPrice", "askingPrice", "currentPrice", "price", "salePrice",
              "currentListPrice", "listprice", "amount", "listAmount"],
    "address": ["streetAddress", "address1", "addressLine1", "propertyAddress", "address",
                "street", "fullStreetAddress", "addressLine"],
    "city": ["city", "cityName", "propertyCity"],
    "state": ["state", "stateCode", "stateAbbreviation", "propertyState", "st"],
    "zip": ["zip", "zipCode", "postalCode", "zip5", "propertyZip", "zipcode"],
    "lat": ["latitude", "lat", "geoLatitude"],
    "lng": ["longitude", "lng", "lon", "long", "geoLongitude"],
    "beds": ["bedrooms", "beds", "bedroomCount", "numBedrooms", "totalBedrooms", "bedroom"],
    "baths": ["bathrooms", "baths", "bathroomCount", "numBathrooms", "totalBathrooms",
              "bathroomsTotal", "bathroom"],
    "half_baths": ["halfBaths", "halfBathrooms", "bathroomsHalf"],
    "full_baths": ["fullBaths", "fullBathrooms", "bathroomsFull"],
    "sqft": ["squareFeet", "sqft", "livingArea", "squareFootage", "livingSqFt", "livingAreaSqFt",
             "buildingSize", "grossLivingArea", "totalSqFt", "sqFt"],
    "lot_sqft": ["lotSize", "lotSqFt", "lotSizeSqFt", "lotSquareFeet", "lotArea"],
    "year_built": ["yearBuilt", "builtYear", "yearConstructed"],
    "property_type": ["propertyType", "type", "homeType", "propertyTypeDescription", "style"],
    "status": ["status", "listingStatus", "propertyStatus", "saleStatus"],
    "listing_url": ["url", "detailUrl", "listingUrl", "propertyUrl", "link", "href"],
    "description": ["description", "remarks", "publicRemarks", "propertyDescription", "comments",
                    "marketingRemarks"],
    "photos": ["photos", "images", "imageUrls", "pictures", "media", "photoUrls", "propertyImages",
               "gallery", "imageList", "photoList"],
    "photo": ["photoUrl", "imageUrl", "thumbnailUrl", "mainPhoto", "primaryPhoto", "thumbnail",
              "image", "picture", "photo"],
}
_ALIAS_K = {f: [_k(a) for a in al] for f, al in ALIASES.items()}

AMENITY_PATTERNS = {
    "Pool": r"\bpool\b",
    "Garage": r"\bgarage\b|\bcarport\b",
    "Basement": r"\bbasement\b",
    "Fireplace": r"\bfireplace",
    "Central Air": r"central (air|a/?c)|\bhvac\b|\bc/a\b",
    "Waterfront": r"waterfront|lake ?front|ocean ?front|river ?front|water view",
    "Fenced Yard": r"fenced",
    "Deck / Patio": r"\bdeck\b|\bpatio\b|\bporch\b",
    "Hardwood Floors": r"hardwood",
    "Updated Kitchen": r"(updated|remodeled|renovated|new) kitchen|granite|quartz",
    "New Roof": r"new roof",
    "Large Lot": r"large lot|acre",
    "Single Story": r"single[- ]story|one[- ]story|ranch",
    "FHA Insurable": r"fha[- ]insur|insurable|insured with escrow|\bIE\b status",
    "203k Eligible": r"203\s*\(?k\)?",
    "Owner-Occupant Only": r"owner[- ]occupant",
}

INTERIOR_WORDS = r"kitchen|bed(room)?|bath|living|dining|interior|inside|family|den|laundry|" \
                 r"closet|hall|stair|basement|bonus|office|room|ceiling|floor"
EXTERIOR_WORDS = r"front|exterior|outside|street|yard|back ?yard|elevation|aerial|garage|" \
                 r"porch|driveway|roof|side|rear|curb|lot|pool|deck|patio"


def _lookup(obj: dict, field: str):
    """Find a value for `field` in a dict by alias, case/punctuation-insensitively, one level deep."""
    kmap = {_k(k): v for k, v in obj.items()}
    for a in _ALIAS_K[field]:
        if a in kmap and kmap[a] not in (None, "", [], {}):
            return kmap[a]
    # One level of nesting (e.g. {"address": {"city": ..}} or {"details": {...}})
    for v in obj.values():
        if isinstance(v, dict):
            sub = {_k(k): vv for k, vv in v.items()}
            for a in _ALIAS_K[field]:
                if a in sub and sub[a] not in (None, "", [], {}):
                    return sub[a]
    return None


def _num(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict):
        return None
    m = re.search(r"-?\d[\d,]*\.?\d*", str(v))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _str(v):
    if v is None:
        return None
    if isinstance(v, dict):
        return None
    s = str(v).strip()
    return s or None


def classify_photo(url: str, caption: str | None, index: int) -> str:
    text = f"{caption or ''} {url.rsplit('/', 1)[-1]}".lower()
    if re.search(INTERIOR_WORDS, text):
        return "interior"
    if re.search(EXTERIOR_WORDS, text):
        return "exterior"
    # Foreclosure sites almost always lead with the front of the house.
    return "exterior" if index == 0 else "unknown"


def extract_photos(obj: dict, base_url: str | None = None) -> list[dict]:
    items = []
    raw = _lookup(obj, "photos")
    if isinstance(raw, str):
        raw = [u for u in re.split(r"[|,;\s]+", raw) if u]
    if isinstance(raw, list):
        for it in raw:
            if isinstance(it, str):
                items.append((it, None))
            elif isinstance(it, dict):
                url = None
                for key in ("url", "src", "href", "uri", "imageUrl", "photoUrl", "large", "fullSize",
                            "original", "path", "fileUrl", "mediaUrl"):
                    for k, v in it.items():
                        if _k(k) == _k(key) and isinstance(v, str):
                            url = v
                            break
                    if url:
                        break
                cap = next((v for k, v in it.items()
                            if _k(k) in ("caption", "description", "title", "label", "roomtype",
                                         "category", "tag", "alt") and isinstance(v, str)), None)
                if url:
                    items.append((url, cap))
    single = _lookup(obj, "photo")
    if isinstance(single, str):
        items.insert(0, (single, None))
    out, seen = [], set()
    for url, cap in items:
        if base_url:
            url = urljoin(base_url, url)
        if not url.startswith("http") or url in seen:
            continue
        seen.add(url)
        out.append({"url": url, "caption": cap})
    for i, ph in enumerate(out):
        ph["kind"] = classify_photo(ph["url"], ph["caption"], i)
    return out


def detect_amenities(text: str) -> list[str]:
    return [name for name, pat in AMENITY_PATTERNS.items()
            if re.search(pat, text or "", re.I)]


def normalize(obj: dict, source: str, base_url: str | None = None) -> dict | None:
    price = _num(_lookup(obj, "price"))
    address = _lookup(obj, "address")
    if isinstance(address, dict):  # address object -> flatten
        obj = {**obj, **address}
        address = _lookup(address, "address")
    address = _str(address)
    if not address or not price or price < 1000:
        return None
    baths = _num(_lookup(obj, "baths"))
    if baths is None:
        full, half = _num(_lookup(obj, "full_baths")), _num(_lookup(obj, "half_baths"))
        if full is not None:
            baths = full + 0.5 * (half or 0)
    sid = _str(_lookup(obj, "source_id")) or f"{address}|{_str(_lookup(obj, 'zip')) or ''}"
    url = _str(_lookup(obj, "listing_url"))
    if url and base_url:
        url = urljoin(base_url, url)
    desc = _str(_lookup(obj, "description"))
    state = _str(_lookup(obj, "state"))
    zip_ = _str(_lookup(obj, "zip"))
    yb = _num(_lookup(obj, "year_built"))
    p = {
        "source": source,
        "source_id": sid,
        "address": address,
        "city": (_str(_lookup(obj, "city")) or "").title() or None,
        "state": state.upper()[:2] if state else None,
        "zip": zip_[:5] if zip_ else None,
        "lat": _num(_lookup(obj, "lat")),
        "lng": _num(_lookup(obj, "lng")),
        "price": price,
        "beds": _num(_lookup(obj, "beds")),
        "baths": baths,
        "sqft": _num(_lookup(obj, "sqft")),
        "lot_sqft": _num(_lookup(obj, "lot_sqft")),
        "year_built": int(yb) if yb and 1700 < yb < 2100 else None,
        "property_type": _str(_lookup(obj, "property_type")),
        "status": _str(_lookup(obj, "status")),
        "listing_url": url,
        "description": desc,
        "photos": extract_photos(obj, base_url),
        "raw": obj,
    }
    # Amenities: scan description plus any boolean/text feature fields in the raw record.
    feature_text = " ".join(
        [desc or ""]
        + [k for k, v in obj.items() if v is True]
        + [str(v) for k, v in obj.items()
           if isinstance(v, str) and re.search(r"feature|amenit|garage|pool|heat|cool|basement|"
                                               r"fireplace|eligib|insur", k, re.I)]
    )
    p["amenities"] = detect_amenities(feature_text)
    return p


def find_listing_arrays(data, depth=0):
    """Yield every list in a JSON tree that looks like a list of property listings."""
    if depth > 8:
        return
    if isinstance(data, list):
        dicts = [x for x in data if isinstance(x, dict)]
        if dicts:
            hits = sum(1 for d in dicts[:25]
                       if _lookup(d, "price") is not None and _lookup(d, "address") is not None)
            if hits >= max(1, len(dicts[:25]) // 2):
                yield dicts
                return
        for x in data:
            yield from find_listing_arrays(x, depth + 1)
    elif isinstance(data, dict):
        for v in data.values():
            yield from find_listing_arrays(v, depth + 1)


def extract_listings(data, source: str, base_url: str | None = None) -> list[dict]:
    out = []
    for arr in find_listing_arrays(data):
        for obj in arr:
            p = normalize(obj, source, base_url)
            if p:
                out.append(p)
    return out
