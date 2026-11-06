# Foreclosure Finder

Pulls foreclosure / bank-owned (REO) listings from HUD, Fannie Mae and Freddie Mac into one
searchable site. You get photos (sorted into exterior and interior), prices, filters for
location, price, size and amenities, and comps for each property.

## Easiest: put it online (Render, free)

1. Sign in at https://render.com with GitHub (the same way as the Kalshi board).
2. **New > Blueprint**, pick `robgk-Apex/kalshi`, branch `claude/relaxed-goodall-tj31fi`,
   and set **Blueprint Path** to `foreclosure-finder/render.yaml`. Click **Apply**.
3. When it says **Live**, open the URL. It starts with the bundled listings snapshot and
   re-pulls every source once a day. To get real sold comps, paste your RentCast key into
   the `RENTCAST_API_KEY` field Render asks for.

## On your Windows PC

Double-click `START-FORECLOSURE-FINDER.bat` (it opens http://localhost:8000).
Double-click `REFRESH-LISTINGS.bat` to pull fresh listings (takes about an hour).

## From a terminal

```bash
cd foreclosure-finder
pip install -r requirements.txt
uvicorn app.server:app --port 8000      # open http://localhost:8000
```

## Scraping

```bash
python -m app.scrape --source hud                 # whole country
python -m app.scrape --source homepath --state GA # one state
python -m app.scrape --source homesteps --state TX --state FL
```

| key | site | how |
|---|---|---|
| `hud` | HUD Home Store | listing JSON embedded in the search and property pages |
| `homepath` | Fannie Mae HomePath | the site's JSON API, Fannie Mae-owned homes only |
| `homesteps` | Freddie Mac HomeSteps | schema.org listing data + facts on each property page |
| `usda`, `va`, any `--url` | other sites | generic headless-browser scraper (needs `playwright install chromium`) |

A run without `--state` covers the whole country and removes listings that are no longer
for sale. Photos: HUD labels every photo (Front, Kitchen, Bath…), so they sort into
Exterior/Interior. HomePath and HomeSteps photos aren't labeled; their first photo is the
front of the house and the rest appear under "Other photos". `data/snapshot.db` is the
bundled copy of the listings; refresh it with `python -c "from app import db; db.write_snapshot()"`.

## Comps

Set a [RentCast](https://app.rentcast.io) API key (the free tier has 50 lookups a month)
to get real recent sales and listings near each property, plus an estimated value and
the discount vs. list price:

```bash
export RENTCAST_API_KEY=your_key
```

Comps are cached for 7 days per property. Without a key, the detail page shows the other
foreclosure listings in your database within 5 miles and of similar size, labeled clearly
as listings, not closed sales.

## API

- `GET /api/properties?state=GA&city=Atlanta&zip=30310&min_price=&max_price=&min_beds=3&min_baths=2&min_sqft=&max_sqft=&amenities=Garage&amenities=Pool&source=hud&q=&sort=price_asc|price_desc|ppsf_asc|sqft_desc|newest&page=1`
- `GET /api/properties/{id}`: full details with every photo
- `GET /api/properties/{id}/comps`
- `GET /api/facets`: states, cities, sources and amenity counts for the filters

## Tests

```bash
python -m pytest tests -q
```

The scraper test runs headless Chromium against a local mock REO site (XHR JSON API,
pagination, detail-page gallery). If Playwright's browser version doesn't match, point it
at any Chrome with `CHROMIUM_PATH=/path/to/chrome`.
