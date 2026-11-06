# Foreclosure Finder

Pulls foreclosure / bank-owned (REO) listings from government and GSE sites into one
searchable site. You get photos (sorted into exterior and interior), prices, filters for
location, price, size and amenities, and comps for each property.

## Quick start

```bash
cd foreclosure-finder
pip install -r requirements.txt
playwright install chromium

python -m app.seed_demo                 # optional: 72 sample listings to try the UI
uvicorn app.server:app --port 8000      # open http://localhost:8000
```

## Scraping real listings

```bash
python -m app.scrape --source hud --state GA --state FL
python -m app.scrape --source all --state TX            # every source in app/sources.json
python -m app.scrape --source hud --url "<a search-results URL you copied from the site>"
python -m app.seed_demo --clear                         # remove demo rows once you have real data
```

Sources (`app/sources.json`):

| key | site |
|---|---|
| `hud` | HUD Home Store (hudhomestore.gov) |
| `homepath` | Fannie Mae HomePath |
| `homesteps` | Freddie Mac HomeSteps |
| `usda` | USDA Rural Development REO |
| `va` | VA REO (Vendor Resource Management) |

**How it works:** the scraper opens the site's real search page in headless Chromium and
records the JSON its own JavaScript loads. It finds the listing arrays in that JSON
whatever the field names are (`app/normalize.py`), clicks "Next" through the result pages,
then opens each listing's detail page to collect the full photo gallery. Photos are tagged
exterior or interior from their captions and file names. Amenities (pool, garage, basement,
FHA insurable, 203k eligible, …) come from the description and feature fields.

Re-running a scrape updates existing rows by `(source, listing id)` and merges in new photos.
Run it on a schedule (cron) to keep listings fresh.

**If a source returns 0 listings:** these sites redesign often. Run a search on the site in
your browser, copy the results-page URL, and pass it with `--url` or put it in
`app/sources.json`. Use `-v` for debug logs. The default `--delay 1.5` keeps request rates
polite. Check each site's terms of use before scraping it. Commercial portals (Zillow,
Realtor.com, Auction.com, etc.) forbid scraping in their terms, so they aren't included.

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
