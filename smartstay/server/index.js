import express from 'express';
import path from 'path';
import { fileURLToPath } from 'url';
import { load, save, flush, getDb, id } from './store.js';
import { seedIfEmpty } from './seed.js';
import { hashPassword, verifyPassword, signToken, publicUser, authenticate } from './auth.js';
import { quote, fromNightly, isAvailable, blockedRanges, nightsBetween, hostEconomics, PLATFORM_COMMISSION } from './pricing.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const app = express();
const PORT = process.env.PORT || 3000;

load();
seedIfEmpty();
flush();

app.use(express.json({ limit: '4mb' }));

// ---------- helpers ----------
const db = () => getDb();

function ratingFor(listingId) {
  const rs = db().reviews.filter((r) => r.listingId === listingId);
  if (!rs.length) return { average: null, count: 0 };
  const average = rs.reduce((s, r) => s + r.rating, 0) / rs.length;
  return { average: Math.round(average * 100) / 100, count: rs.length };
}

function hostCard(hostId) {
  const u = db().users.find((x) => x.id === hostId);
  if (!u) return null;
  return { id: u.id, name: u.name, avatar: u.avatar, bio: u.bio, isHost: u.isHost, createdAt: u.createdAt };
}

function listingCard(l) {
  const { average, count } = ratingFor(l.id);
  return {
    id: l.id,
    title: l.title,
    type: l.type,
    city: l.city,
    state: l.state,
    lat: l.lat,
    lng: l.lng,
    bedrooms: l.bedrooms,
    beds: l.beds,
    bathrooms: l.bathrooms,
    maxGuests: l.maxGuests,
    amenities: l.amenities,
    photo: l.photos?.[0] || null,
    photos: l.photos,
    fromNightly: fromNightly(l),
    instantBook: l.instantBook,
    minNights: l.minNights,
    weeklyDiscountPct: l.pricing?.weeklyDiscountPct || 0,
    monthlyDiscountPct: l.pricing?.monthlyDiscountPct || 0,
    rating: average,
    reviewCount: count,
    hostId: l.hostId,
  };
}

function wrap(fn) {
  return (req, res) => {
    Promise.resolve(fn(req, res)).catch((err) => {
      console.error(err);
      res.status(500).json({ error: 'Something went wrong on our end.' });
    });
  };
}

// ---------- auth ----------
app.post('/api/auth/signup', wrap((req, res) => {
  const { name, email, password, isHost } = req.body || {};
  if (!name || !email || !password) return res.status(400).json({ error: 'Name, email and password are required.' });
  if (password.length < 6) return res.status(400).json({ error: 'Password must be at least 6 characters.' });
  const exists = db().users.find((u) => u.email === email.toLowerCase());
  if (exists) return res.status(409).json({ error: 'An account with this email already exists.' });
  const user = {
    id: id(),
    name: name.trim(),
    email: email.toLowerCase().trim(),
    passwordHash: hashPassword(password),
    isHost: !!isHost,
    avatar: `https://api.dicebear.com/7.x/avataaars/svg?seed=${encodeURIComponent(name)}`,
    bio: '',
    createdAt: new Date().toISOString(),
  };
  db().users.push(user);
  save();
  res.json({ token: signToken(user), user: publicUser(user) });
}));

app.post('/api/auth/login', wrap((req, res) => {
  const { email, password } = req.body || {};
  const user = db().users.find((u) => u.email === String(email || '').toLowerCase());
  if (!user || !verifyPassword(password || '', user.passwordHash)) {
    return res.status(401).json({ error: 'Incorrect email or password.' });
  }
  res.json({ token: signToken(user), user: publicUser(user) });
}));

app.get('/api/auth/me', authenticate(), wrap((req, res) => {
  res.json({ user: publicUser(req.user) });
}));

app.patch('/api/auth/me', authenticate(), wrap((req, res) => {
  const { name, bio, isHost, avatar } = req.body || {};
  if (name != null) req.user.name = String(name).trim();
  if (bio != null) req.user.bio = String(bio);
  if (avatar != null) req.user.avatar = String(avatar);
  if (isHost != null) req.user.isHost = !!isHost;
  save();
  res.json({ user: publicUser(req.user) });
}));

// ---------- listings: search & detail ----------
app.get('/api/listings', wrap((req, res) => {
  const { q, city, type, guests, minPrice, maxPrice, amenities, checkIn, checkOut, instantBook, sort } = req.query;
  let items = db().listings.slice();

  if (q) {
    const needle = String(q).toLowerCase();
    items = items.filter((l) =>
      [l.title, l.city, l.state, l.type, l.description].join(' ').toLowerCase().includes(needle));
  }
  if (city) {
    const needle = String(city).toLowerCase();
    items = items.filter((l) => `${l.city}, ${l.state}`.toLowerCase().includes(needle) || l.city.toLowerCase().includes(needle) || l.state.toLowerCase().includes(needle));
  }
  if (type) items = items.filter((l) => l.type.toLowerCase() === String(type).toLowerCase());
  if (guests) items = items.filter((l) => l.maxGuests >= Number(guests));
  if (minPrice) items = items.filter((l) => fromNightly(l) >= Number(minPrice));
  if (maxPrice) items = items.filter((l) => fromNightly(l) <= Number(maxPrice));
  if (instantBook === 'true') items = items.filter((l) => l.instantBook);
  if (amenities) {
    const wanted = String(amenities).split(',').map((a) => a.trim().toLowerCase()).filter(Boolean);
    items = items.filter((l) => wanted.every((w) => l.amenities.map((a) => a.toLowerCase()).includes(w)));
  }
  if (checkIn && checkOut && nightsBetween(checkIn, checkOut) > 0) {
    items = items.filter((l) => isAvailable(l, db().bookings, checkIn, checkOut));
  }

  let cards = items.map(listingCard);

  switch (sort) {
    case 'price_asc': cards.sort((a, b) => a.fromNightly - b.fromNightly); break;
    case 'price_desc': cards.sort((a, b) => b.fromNightly - a.fromNightly); break;
    case 'rating': cards.sort((a, b) => (b.rating || 0) - (a.rating || 0)); break;
    default: cards.sort((a, b) => (b.rating || 0) - (a.rating || 0));
  }

  res.json({ count: cards.length, listings: cards });
}));

app.get('/api/listings/:lid', wrap((req, res) => {
  const l = db().listings.find((x) => x.id === req.params.lid);
  if (!l) return res.status(404).json({ error: 'Listing not found.' });
  const { average, count } = ratingFor(l.id);
  const reviews = db().reviews
    .filter((r) => r.listingId === l.id)
    .sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt))
    .map((r) => ({ ...r, author: hostCard(r.guestId) }));

  res.json({
    listing: {
      ...l,
      rating: average,
      reviewCount: count,
      fromNightly: fromNightly(l),
      host: hostCard(l.hostId),
      blocked: blockedRanges(l, db().bookings),
      reviews,
    },
  });
}));

// Price quote for a specific stay.
app.post('/api/listings/:lid/quote', wrap((req, res) => {
  const l = db().listings.find((x) => x.id === req.params.lid);
  if (!l) return res.status(404).json({ error: 'Listing not found.' });
  const { checkIn, checkOut, guests } = req.body || {};
  const q = quote(l, checkIn, checkOut, Number(guests) || 1);
  if (!q.ok) return res.status(400).json(q);
  const available = isAvailable(l, db().bookings, checkIn, checkOut);
  res.json({ ...q, available });
}));

// ---------- host: manage listings ----------
const AMENITY_VOCAB = ['Wifi','Kitchen','Pool','Hot tub','Free parking','Air conditioning','Heating','Washer','Dryer','EV charger','Gym','Pets allowed','Fireplace','Beach access','Lake access','Mountain view','Ocean view','Workspace','BBQ grill','Patio','Ski-in/ski-out'];
const TYPE_VOCAB = ['House','Apartment','Cabin','Condo','Villa','Cottage','Loft','Townhouse'];

function sanitizeListingInput(body) {
  const p = body.pricing || {};
  return {
    title: String(body.title || '').trim(),
    description: String(body.description || '').trim(),
    type: TYPE_VOCAB.includes(body.type) ? body.type : 'House',
    city: String(body.city || '').trim(),
    state: String(body.state || '').trim().toUpperCase().slice(0, 2),
    lat: Number(body.lat) || 39.5,
    lng: Number(body.lng) || -98.35,
    bedrooms: Math.max(0, Number(body.bedrooms) || 1),
    beds: Math.max(1, Number(body.beds) || 1),
    bathrooms: Math.max(1, Number(body.bathrooms) || 1),
    maxGuests: Math.max(1, Number(body.maxGuests) || 2),
    amenities: Array.isArray(body.amenities) ? body.amenities.filter((a) => AMENITY_VOCAB.includes(a)) : [],
    photos: Array.isArray(body.photos) ? body.photos.filter((u) => typeof u === 'string' && u.startsWith('http')).slice(0, 12) : [],
    pricing: {
      nightly: Math.max(10, Number(p.nightly) || 100),
      weekendNightly: p.weekendNightly ? Math.max(10, Number(p.weekendNightly)) : 0,
      weeklyDiscountPct: Math.min(60, Math.max(0, Number(p.weeklyDiscountPct) || 0)),
      monthlyDiscountPct: Math.min(70, Math.max(0, Number(p.monthlyDiscountPct) || 0)),
      cleaningFee: Math.max(0, Number(p.cleaningFee) || 0),
    },
    minNights: Math.max(1, Number(body.minNights) || 1),
    instantBook: !!body.instantBook,
  };
}

app.get('/api/host/listings', authenticate(), wrap((req, res) => {
  const mine = db().listings.filter((l) => l.hostId === req.user.id);
  const cards = mine.map((l) => {
    const bookings = db().bookings.filter((b) => b.listingId === l.id && b.status !== 'cancelled');
    const econ = bookings.reduce((acc, b) => {
      const e = hostEconomics(b);
      acc.gross += e.gross; acc.platformFee += e.platformFee; acc.payout += e.payout;
      return acc;
    }, { gross: 0, platformFee: 0, payout: 0 });
    return {
      ...listingCard(l), bookingCount: bookings.length,
      gross: Math.round(econ.gross), platformFee: Math.round(econ.platformFee), payout: Math.round(econ.payout),
      revenue: Math.round(econ.payout), // net payout to the host
      description: l.description, pricing: l.pricing, minNights: l.minNights, blockedDates: l.blockedDates,
    };
  });
  res.json({ listings: cards, commissionPct: PLATFORM_COMMISSION * 100 });
}));

app.post('/api/host/listings', authenticate(), wrap((req, res) => {
  const clean = sanitizeListingInput(req.body || {});
  if (!clean.title || !clean.city || !clean.description) {
    return res.status(400).json({ error: 'Title, city and description are required.' });
  }
  if (!clean.photos.length) {
    return res.status(400).json({ error: 'Please add at least one photo of your place.' });
  }
  req.user.isHost = true;
  const listing = { id: id(), hostId: req.user.id, blockedDates: [], createdAt: new Date().toISOString(), ...clean };
  db().listings.push(listing);
  save();
  res.json({ listing });
}));

app.put('/api/host/listings/:lid', authenticate(), wrap((req, res) => {
  const l = db().listings.find((x) => x.id === req.params.lid);
  if (!l) return res.status(404).json({ error: 'Listing not found.' });
  if (l.hostId !== req.user.id) return res.status(403).json({ error: 'You can only edit your own listings.' });
  const clean = sanitizeListingInput({ ...l, ...req.body });
  if (!clean.photos.length) return res.status(400).json({ error: 'Please add at least one photo of your place.' });
  Object.assign(l, clean);
  save();
  res.json({ listing: l });
}));

app.delete('/api/host/listings/:lid', authenticate(), wrap((req, res) => {
  const l = db().listings.find((x) => x.id === req.params.lid);
  if (!l) return res.status(404).json({ error: 'Listing not found.' });
  if (l.hostId !== req.user.id) return res.status(403).json({ error: 'You can only delete your own listings.' });
  db().listings = db().listings.filter((x) => x.id !== l.id);
  save();
  res.json({ ok: true });
}));

// Host blocks dates manually.
app.post('/api/host/listings/:lid/block', authenticate(), wrap((req, res) => {
  const l = db().listings.find((x) => x.id === req.params.lid);
  if (!l || l.hostId !== req.user.id) return res.status(403).json({ error: 'Not allowed.' });
  const { checkIn, checkOut } = req.body || {};
  if (!checkIn || !checkOut || nightsBetween(checkIn, checkOut) <= 0) return res.status(400).json({ error: 'Invalid dates.' });
  l.blockedDates = l.blockedDates || [];
  l.blockedDates.push({ checkIn, checkOut });
  save();
  res.json({ listing: l });
}));

app.get('/api/host/bookings', authenticate(), wrap((req, res) => {
  const myListingIds = new Set(db().listings.filter((l) => l.hostId === req.user.id).map((l) => l.id));
  const items = db().bookings
    .filter((b) => myListingIds.has(b.listingId))
    .sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt))
    .map((b) => ({
      ...b,
      ...hostEconomics(b),
      listing: listingCard(db().listings.find((l) => l.id === b.listingId)),
      guest: hostCard(b.guestId),
    }));
  res.json({ bookings: items });
}));

// ---------- bookings ----------
app.post('/api/bookings', authenticate(), wrap((req, res) => {
  const { listingId, checkIn, checkOut, guests } = req.body || {};
  const l = db().listings.find((x) => x.id === listingId);
  if (!l) return res.status(404).json({ error: 'Listing not found.' });
  if (l.hostId === req.user.id) return res.status(400).json({ error: 'You cannot book your own listing.' });
  const q = quote(l, checkIn, checkOut, Number(guests) || 1);
  if (!q.ok) return res.status(400).json(q);
  if (!isAvailable(l, db().bookings, checkIn, checkOut)) {
    return res.status(409).json({ error: 'Those dates are no longer available.' });
  }
  const booking = {
    id: id(),
    listingId: l.id,
    guestId: req.user.id,
    checkIn, checkOut,
    guests: Number(guests) || 1,
    nights: q.nights,
    subtotal: q.subtotal,
    cleaningFee: q.cleaningFee,
    serviceFee: q.serviceFee,
    taxes: q.taxes,
    total: q.total,
    status: l.instantBook ? 'confirmed' : 'pending',
    createdAt: new Date().toISOString(),
  };
  db().bookings.push(booking);
  save();
  res.json({ booking: { ...booking, listing: listingCard(l) } });
}));

app.get('/api/bookings', authenticate(), wrap((req, res) => {
  const now = new Date();
  const items = db().bookings
    .filter((b) => b.guestId === req.user.id)
    .sort((a, b) => new Date(b.checkIn) - new Date(a.checkIn))
    .map((b) => {
      const l = db().listings.find((x) => x.id === b.listingId);
      const isPast = new Date(b.checkOut) < now;
      const reviewed = db().reviews.some((r) => r.listingId === b.listingId && r.guestId === req.user.id && r.bookingId === b.id);
      return { ...b, listing: l ? listingCard(l) : null, host: l ? hostCard(l.hostId) : null, isPast, reviewed };
    });
  res.json({ bookings: items });
}));

app.post('/api/bookings/:bid/cancel', authenticate(), wrap((req, res) => {
  const b = db().bookings.find((x) => x.id === req.params.bid);
  if (!b) return res.status(404).json({ error: 'Booking not found.' });
  const l = db().listings.find((x) => x.id === b.listingId);
  const isGuest = b.guestId === req.user.id;
  const isHost = l && l.hostId === req.user.id;
  if (!isGuest && !isHost) return res.status(403).json({ error: 'Not allowed.' });
  b.status = 'cancelled';
  save();
  res.json({ booking: b });
}));

// Host confirms a pending request.
app.post('/api/bookings/:bid/confirm', authenticate(), wrap((req, res) => {
  const b = db().bookings.find((x) => x.id === req.params.bid);
  if (!b) return res.status(404).json({ error: 'Booking not found.' });
  const l = db().listings.find((x) => x.id === b.listingId);
  if (!l || l.hostId !== req.user.id) return res.status(403).json({ error: 'Not allowed.' });
  b.status = 'confirmed';
  save();
  res.json({ booking: b });
}));

// ---------- reviews ----------
app.post('/api/listings/:lid/reviews', authenticate(), wrap((req, res) => {
  const l = db().listings.find((x) => x.id === req.params.lid);
  if (!l) return res.status(404).json({ error: 'Listing not found.' });
  const { rating, comment, bookingId } = req.body || {};
  const r = Number(rating);
  if (!(r >= 1 && r <= 5)) return res.status(400).json({ error: 'Rating must be 1–5.' });
  // Must have a booking on this listing.
  const hasStay = db().bookings.some((b) => b.listingId === l.id && b.guestId === req.user.id);
  if (!hasStay) return res.status(403).json({ error: 'You can review a home after you’ve booked it.' });
  const review = {
    id: id(),
    listingId: l.id,
    guestId: req.user.id,
    bookingId: bookingId || null,
    rating: r,
    comment: String(comment || '').trim(),
    createdAt: new Date().toISOString(),
  };
  db().reviews.push(review);
  save();
  res.json({ review });
}));

// ---------- favorites ----------
app.get('/api/favorites', authenticate(), wrap((req, res) => {
  const ids = new Set(db().favorites.filter((f) => f.userId === req.user.id).map((f) => f.listingId));
  const listings = db().listings.filter((l) => ids.has(l.id)).map(listingCard);
  res.json({ listings, ids: [...ids] });
}));

app.post('/api/favorites/:lid', authenticate(), wrap((req, res) => {
  const lid = req.params.lid;
  const existing = db().favorites.find((f) => f.userId === req.user.id && f.listingId === lid);
  let favorited;
  if (existing) {
    db().favorites = db().favorites.filter((f) => !(f.userId === req.user.id && f.listingId === lid));
    favorited = false;
  } else {
    db().favorites.push({ userId: req.user.id, listingId: lid });
    favorited = true;
  }
  save();
  res.json({ favorited });
}));

// ---------- messaging ----------
app.post('/api/listings/:lid/messages', authenticate(), wrap((req, res) => {
  const l = db().listings.find((x) => x.id === req.params.lid);
  if (!l) return res.status(404).json({ error: 'Listing not found.' });
  const body = String(req.body?.body || '').trim();
  if (!body) return res.status(400).json({ error: 'Message cannot be empty.' });
  const toId = l.hostId === req.user.id ? null : l.hostId;
  // Thread keyed by listing + the two participants (guest & host).
  const guestId = l.hostId === req.user.id ? req.body?.guestId : req.user.id;
  const threadId = `${l.id}:${guestId}`;
  const msg = {
    id: id(), listingId: l.id, threadId,
    fromId: req.user.id, toId: toId || req.body?.guestId, body,
    createdAt: new Date().toISOString(), read: false,
  };
  db().messages.push(msg);
  save();
  res.json({ message: msg });
}));

app.get('/api/messages', authenticate(), wrap((req, res) => {
  const mine = db().messages.filter((m) => m.fromId === req.user.id || m.toId === req.user.id);
  const threads = {};
  for (const m of mine.sort((a, b) => new Date(a.createdAt) - new Date(b.createdAt))) {
    if (!threads[m.threadId]) {
      const l = db().listings.find((x) => x.id === m.listingId);
      threads[m.threadId] = { threadId: m.threadId, listing: l ? listingCard(l) : null, messages: [], lastAt: m.createdAt };
    }
    threads[m.threadId].messages.push(m);
    threads[m.threadId].lastAt = m.createdAt;
  }
  const list = Object.values(threads).sort((a, b) => new Date(b.lastAt) - new Date(a.lastAt));
  res.json({ threads: list });
}));

// ---------- meta ----------
app.get('/api/meta', wrap((req, res) => {
  res.json({ amenities: AMENITY_VOCAB, types: TYPE_VOCAB,
    cities: [...new Set(db().listings.map((l) => `${l.city}, ${l.state}`))].sort() });
}));

app.get('/api/health', (req, res) => res.json({ ok: true, listings: db().listings.length }));

// ---------- static frontend ----------
app.use(express.static(path.join(__dirname, '..', 'public')));
// SPA fallback (hash routing, but catch deep links gracefully).
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, '..', 'public', 'index.html'));
});

const server = app.listen(PORT, () => {
  console.log(`\n  🏡  SmartStay USA running at http://localhost:${PORT}\n`);
});

function shutdown() {
  flush();
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 500);
}
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
