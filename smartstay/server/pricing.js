// Shared pricing & availability logic.
// Rates: nightly base, optional weekend override (Fri/Sat nights),
// plus weekly / monthly length-of-stay discounts. Guest-side fees on top.

const SERVICE_FEE_PCT = 0;    // NO guest booking fee — cheaper than Airbnb
const TAX_PCT = 0.08;         // occupancy / lodging tax estimate (unavoidable, goes to the state)
const AIRBNB_GUEST_FEE_PCT = 0.14; // typical Airbnb guest service fee, for savings comparison
export const PLATFORM_COMMISSION = 0.20; // SmartStay's cut of host gross revenue (how we make money instead)

// Host economics for a completed/active booking: gross (accommodation +
// cleaning), SmartStay's 20% commission, and the host's net payout (80%).
export function hostEconomics(booking) {
  const gross = round2((booking.subtotal || 0) + (booking.cleaningFee || 0));
  const platformFee = round2(gross * PLATFORM_COMMISSION);
  const payout = round2(gross - platformFee);
  return { gross, platformFee, payout };
}

export function toUTCDate(str) {
  // Accepts 'YYYY-MM-DD' and returns a UTC midnight Date.
  const [y, m, d] = String(str).split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

export function ymd(date) {
  return date.toISOString().slice(0, 10);
}

export function nightsBetween(checkIn, checkOut) {
  const a = toUTCDate(checkIn);
  const b = toUTCDate(checkOut);
  return Math.round((b - a) / 86400000);
}

// Every night (check-in inclusive, check-out exclusive).
export function eachNight(checkIn, checkOut) {
  const out = [];
  const a = toUTCDate(checkIn);
  const b = toUTCDate(checkOut);
  for (let d = new Date(a); d < b; d.setUTCDate(d.getUTCDate() + 1)) {
    out.push(new Date(d));
  }
  return out;
}

function round2(n) {
  return Math.round(n * 100) / 100;
}

// Build a full price quote for a stay. Returns null-ish error info if invalid.
export function quote(listing, checkIn, checkOut, guests = 1) {
  const p = listing.pricing || {};
  const nights = nightsBetween(checkIn, checkOut);

  if (!checkIn || !checkOut || Number.isNaN(nights) || nights <= 0) {
    return { ok: false, error: 'Select valid check-in and check-out dates.' };
  }
  if ((listing.minNights || 1) > nights) {
    return { ok: false, error: `This home has a ${listing.minNights}-night minimum.` };
  }
  if (guests > (listing.maxGuests || 1)) {
    return { ok: false, error: `This home hosts up to ${listing.maxGuests} guests.` };
  }

  let base = 0;
  for (const night of eachNight(checkIn, checkOut)) {
    const dow = night.getUTCDay(); // 0 Sun .. 6 Sat
    const isWeekend = dow === 5 || dow === 6; // Fri & Sat nights
    const rate = isWeekend && p.weekendNightly ? p.weekendNightly : p.nightly;
    base += rate;
  }

  // Length-of-stay discount: monthly wins over weekly.
  let discountPct = 0;
  let discountLabel = '';
  if (nights >= 28 && p.monthlyDiscountPct) {
    discountPct = p.monthlyDiscountPct;
    discountLabel = 'Monthly discount';
  } else if (nights >= 7 && p.weeklyDiscountPct) {
    discountPct = p.weeklyDiscountPct;
    discountLabel = 'Weekly discount';
  }

  const discount = round2(base * (discountPct / 100));
  const subtotal = round2(base - discount);
  const cleaningFee = round2(p.cleaningFee || 0);
  const serviceFee = round2(subtotal * SERVICE_FEE_PCT); // 0 — we don't charge guests
  const taxes = round2((subtotal + cleaningFee) * TAX_PCT);
  const total = round2(subtotal + cleaningFee + serviceFee + taxes);
  // What the same stay would cost on Airbnb (their guest fee), for a savings callout.
  const airbnbFee = round2(subtotal * AIRBNB_GUEST_FEE_PCT);

  return {
    ok: true,
    nights,
    base: round2(base),
    avgPerNight: round2(base / nights),
    discountPct,
    discountLabel,
    discount,
    subtotal,
    cleaningFee,
    serviceFee,
    taxes,
    total,
    airbnbFee,
    savingsVsAirbnb: airbnbFee, // guests save the entire fee they'd have paid elsewhere
  };
}

// "From" price for cards — cheapest plausible night.
export function fromNightly(listing) {
  const p = listing.pricing || {};
  return Math.min(p.nightly || Infinity, p.weekendNightly || Infinity);
}

export function rangesOverlap(aIn, aOut, bIn, bOut) {
  return toUTCDate(aIn) < toUTCDate(bOut) && toUTCDate(bIn) < toUTCDate(aOut);
}

// Blocked date ranges for a listing (active bookings + host blocks).
export function blockedRanges(listing, bookings) {
  const active = bookings
    .filter((b) => b.listingId === listing.id && ['pending', 'confirmed'].includes(b.status))
    .map((b) => ({ checkIn: b.checkIn, checkOut: b.checkOut }));
  const hostBlocks = (listing.blockedDates || []).map((r) => ({ checkIn: r.checkIn, checkOut: r.checkOut }));
  return [...active, ...hostBlocks];
}

export function isAvailable(listing, bookings, checkIn, checkOut) {
  return !blockedRanges(listing, bookings).some((r) => rangesOverlap(checkIn, checkOut, r.checkIn, r.checkOut));
}
