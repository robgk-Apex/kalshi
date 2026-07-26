# SmartStay USA — web build

`smartstay.src.html` is the complete, self-contained SmartStay app: a vanilla-JS
single-page app with an in-browser mock backend (data persists in `localStorage`).
It is the source of truth for the GitHub Pages site.

## Build the deployed site

```bash
node smartstay-web/build-docs.js
```

This transforms the artifact into `docs/index.html` (served by GitHub Pages):

- wraps it in a full HTML document (doctype, head meta, favicon)
- injects real property photos (they load in a real browser)
- uses a distinct `localStorage` key so the Pages build seeds independently

## Features

- Two-sided marketplace: guests book, owners host
- Trip Matcher quiz with availability-aware recommendations
- No guest booking fee (cheaper than Airbnb); SmartStay keeps 20% of host gross
- Owner dashboard: revenue split, booking calendar with block-out dates,
  per-reservation earnings on hover
- Booking detail: guest contact (name, phone, email, card last-4), in-app chat,
  post-stay photo messages and damage invoices with pay flow
- Multi-photo listing upload (owners add their own real photos)
- Payout method: owners add bank account + routing number for their 80% payout
