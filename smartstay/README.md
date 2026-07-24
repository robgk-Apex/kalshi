# 🏡 SmartStay USA

**A full-stack short, medium & long-term rental marketplace — "Airbnb 2.0" for the United States.**

Owners list their homes and set their own rates by the **night, weekend, week, or month**.
Guests search, compare, and book beautiful stays across the country — with real availability,
dynamic pricing, reviews, wishlists, and messaging.

Built top-to-bottom: a Node/Express REST API, JWT auth, a file-persisted data store, and a
polished, responsive single-page frontend (no build step required).

---

## ✨ Features

### For guests
- **Smart search** by destination, dates, guests, home type, price, amenities, and Instant Book
- **Rich listing pages** — photo gallery + lightbox, amenities, host profile, an interactive map, and reviews
- **Interactive maps** (Leaflet + OpenStreetMap) — a split list/map view on search with price pins, popups, and card↔pin hover highlighting, plus an approximate-location map on every listing
- **Real availability** — booked dates are blocked; overlapping stays are rejected
- **Dynamic pricing quotes** — nightly + weekend rates, automatic **weekly / monthly discounts**,
  cleaning fee, service fee, and taxes, all itemized before you book
- **Instant Book or request-to-book** flows with live confirmation
- **Trips dashboard** — upcoming & past stays, cancellations, and post-stay reviews
- **Wishlists** — save homes with one tap
- **Messages** — start a conversation with any host

### For hosts
- **List a home in minutes** — pick photos, amenities, and set your own pricing
- **Set flexible rates** — base nightly, weekend premium, weekly %, monthly %, cleaning fee,
  minimum nights, and Instant Book
- **Host dashboard** — listings, earnings, booking counts, and pending requests
- **Approve / decline** requests, edit or delete listings

### Under the hood
- **JWT authentication** with bcrypt-hashed passwords
- **Availability engine** with date-range overlap detection
- **Pricing engine** — weekend-aware nightly totals + length-of-stay discounts + fees & tax
- **Zero native dependencies** — runs anywhere Node 18+ runs
- **Seeded** with 12 real US destinations, hosts, reviews, and demo bookings on first launch

---

## 🚀 Getting started

```bash
cd smartstay
npm install
npm start
```

Then open **http://localhost:3000**.

The database seeds itself on first run (stored at `server/data/db.json`, git-ignored).
To reseed from scratch:

```bash
npm run seed          # force re-seed
# or just delete server/data/db.json and restart
```

### Demo accounts (password: `password123`)

| Role  | Email                  | What to try                              |
|-------|------------------------|------------------------------------------|
| Guest | `guest@smartstay.us`   | Pre-loaded trips, wishlists, book a stay  |
| Host  | `sofia@smartstay.us`   | Manages Malibu, Miami, Scottsdale, Brooklyn |
| Host  | `marcus@smartstay.us`  | Aspen, Tahoe, Savannah, Sedona           |
| Host  | `priya@smartstay.us`   | Austin, Nashville, Big Bear, Outer Banks |

Or **sign up** fresh and, on signup, check *"I want to host"* to list your own place.

---

## 🧱 Architecture

```
smartstay/
├── server/
│   ├── index.js      # Express app + all REST endpoints
│   ├── store.js      # JSON-backed persistence layer
│   ├── auth.js       # JWT + bcrypt + auth middleware
│   ├── pricing.js    # quote + availability engine (shared logic)
│   └── seed.js       # sample listings, hosts, reviews, bookings
└── public/
    ├── index.html
    ├── styles.css    # full design system
    └── js/
        ├── app.js        # routes + boot
        ├── api.js        # fetch wrapper + auth store
        ├── router.js     # hash router with :params
        ├── ui.js         # DOM/format helpers, modals, toasts, lightbox
        ├── chrome.js     # header + footer
        ├── components.js # listing card + search widget
        └── views/        # home, search, listing, auth, account, host
```

### Key API endpoints

| Method | Path                              | Purpose                        |
|--------|-----------------------------------|--------------------------------|
| POST   | `/api/auth/signup` · `/login`     | Register / log in (JWT)        |
| GET    | `/api/listings`                   | Search + filter + sort         |
| GET    | `/api/listings/:id`               | Listing detail + reviews       |
| POST   | `/api/listings/:id/quote`         | Price a specific stay          |
| POST   | `/api/bookings`                   | Create a booking               |
| GET    | `/api/bookings`                   | My trips                       |
| GET/POST/PUT/DELETE | `/api/host/listings…`| Manage listings                |
| GET    | `/api/host/bookings`              | Reservations for my homes      |
| POST   | `/api/listings/:id/reviews`       | Leave a review                 |
| GET/POST | `/api/favorites…`               | Wishlists                      |
| GET/POST | `/api/messages` · `/listings/:id/messages` | Messaging          |

---

## 💸 How pricing works

For a given stay, the engine:

1. Sums each night at the **nightly rate**, using the **weekend rate** for Friday & Saturday nights.
2. Applies a **length-of-stay discount** — monthly (28+ nights) takes priority over weekly (7+ nights).
3. Adds the **cleaning fee**, a **12% service fee**, and an **8% lodging tax**.

Everything is itemized in the booking widget so guests always see exactly what they pay.

---

## 📝 Notes

- Payments are simulated (no real charges) — this is a complete, runnable demo marketplace.
- Photos load from Unsplash and avatars from DiceBear; both fail gracefully if offline.
- Maps use a locally-vendored Leaflet (`public/vendor/leaflet/`) with CARTO/OpenStreetMap tiles — no CDN or API key required.
- Data persists to a local JSON file — swap `store.js` for Postgres/Mongo to go to production.
