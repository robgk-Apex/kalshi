"""Load sample listings so you can try the site without scraping.

    python -m app.seed_demo          # add demo listings
    python -m app.seed_demo --clear  # remove them again

Demo rows use source='demo' and illustrated placeholder photos; they are not real houses.
"""
import random
import sys

from . import db
from .normalize import detect_amenities

CITIES = [  # city, state, zip, lat, lng, base $/sqft
    ("Atlanta", "GA", "30310", 33.727, -84.423, 165), ("Decatur", "GA", "30032", 33.746, -84.270, 150),
    ("Marietta", "GA", "30060", 33.937, -84.536, 175), ("Jacksonville", "FL", "32208", 30.391, -81.680, 140),
    ("Orlando", "FL", "32808", 28.571, -81.437, 190), ("Tampa", "FL", "33610", 27.996, -82.402, 205),
    ("Houston", "TX", "77016", 29.858, -95.300, 125), ("San Antonio", "TX", "78211", 29.355, -98.555, 120),
    ("Phoenix", "AZ", "85009", 33.454, -112.130, 215), ("Detroit", "MI", "48205", 42.431, -82.979, 70),
    ("Cleveland", "OH", "44105", 41.450, -81.630, 75), ("Memphis", "TN", "38109", 35.030, -90.070, 85),
]
STREETS = ["Oak", "Maple", "Pine", "Cedar", "Elm", "Willow", "Hickory", "Magnolia", "Lakeview",
           "Ridge", "Sunset", "Meadow", "Highland", "Park", "Church", "Mill"]
SUFFIX = ["St", "Ave", "Dr", "Ln", "Ct", "Way", "Rd", "Cir"]
FEATURES = ["attached 2-car garage", "in-ground pool", "full unfinished basement", "wood-burning fireplace",
            "central air", "fenced back yard", "covered back patio", "hardwood floors throughout",
            "updated kitchen with granite counters", "new roof in 2021", "large lot (0.6 acre)",
            "single-story ranch layout", "lakefront views", "wood deck off the kitchen"]
STATUS = ["Available", "Available", "Available", "Price Reduced", "Bid Open", "Under Contract"]


def build(n=72, seed=7):
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        city, st, z, lat, lng, ppsf = CITIES[i % len(CITIES)]
        beds = rnd.choice([2, 3, 3, 3, 4, 4, 5])
        baths = rnd.choice([1, 1.5, 2, 2, 2.5, 3])
        sqft = int(rnd.gauss(800 + beds * 380, 220))
        price = round(sqft * ppsf * rnd.uniform(0.55, 0.95), -2)
        feats = rnd.sample(FEATURES, rnd.randint(2, 5))
        source = rnd.choice(["hud", "hud", "homepath", "homesteps"])
        desc = (f"{beds} bed / {baths} bath {'HUD' if source == 'hud' else 'bank-owned'} home "
                f"with " + ", ".join(feats) + ". Sold as-is. "
                + ("FHA insurable with escrow (IE). " if rnd.random() < .4 else "")
                + ("Eligible for 203(k) rehab financing. " if rnd.random() < .3 else "")
                + ("Owner-occupant bidding period in effect." if source == "hud" else ""))
        ext = rnd.sample(range(1, 5), 2)
        ints = rnd.sample(range(1, 5), rnd.randint(2, 4))
        photos = [{"url": f"/static/demo/exterior{e}.svg", "kind": "exterior", "caption": "Front"
                   if j == 0 else "Rear"} for j, e in enumerate(ext)]
        names = ["Kitchen", "Living room", "Bedroom", "Bathroom"]
        photos += [{"url": f"/static/demo/interior{k}.svg", "kind": "interior",
                    "caption": names[k - 1]} for k in ints]
        out.append({
            "source": "demo", "source_id": f"DEMO-{source.upper()}-{i:04d}",
            "address": f"{rnd.randint(100, 9899)} {rnd.choice(STREETS)} {rnd.choice(SUFFIX)}",
            "city": city, "state": st, "zip": z,
            "lat": lat + rnd.uniform(-.05, .05), "lng": lng + rnd.uniform(-.06, .06),
            "price": price, "beds": beds, "baths": baths, "sqft": sqft,
            "lot_sqft": rnd.choice([5200, 6500, 7800, 9100, 12000, 26000]),
            "year_built": rnd.randint(1948, 2012), "property_type": "Single Family",
            "status": rnd.choice(STATUS), "listing_url": None, "description": desc,
            "amenities": detect_amenities(desc), "photos": photos,
        })
    return out


if __name__ == "__main__":
    db.init()
    with db.connect() as c:
        if "--clear" in sys.argv:
            c.execute("DELETE FROM properties WHERE source='demo'")
            print("Removed demo listings.")
        else:
            for p in build():
                db.upsert_property(c, p)
            print("Loaded 72 demo listings.")
