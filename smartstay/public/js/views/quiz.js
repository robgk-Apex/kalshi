import { h, mount, $, loading, fmtDate, addDaysISO, todayISO } from '../ui.js';
import { api } from '../api.js';
import { navigate } from '../router.js';
import { listingCard } from '../components.js';

const SEEN_KEY = 'smartstay_quiz_seen';
export const shouldAutoQuiz = () => !localStorage.getItem(SEEN_KEY);
const markSeen = () => localStorage.setItem(SEEN_KEY, '1');

// Each option carries the fields used both to score listings and to build a search query.
const QUESTIONS = [
  {
    key: 'vibe', q: 'What kind of getaway are you dreaming of?',
    options: [
      { label: 'Beach & ocean', ico: '🏖️', amenities: ['Beach access', 'Ocean view'] },
      { label: 'Mountains & snow', ico: '⛰️', amenities: ['Mountain view', 'Ski-in/ski-out'] },
      { label: 'City & culture', ico: '🌆', types: ['Apartment', 'Loft', 'Condo'] },
      { label: 'Desert & sun', ico: '🏜️', amenities: ['Pool', 'Hot tub'] },
      { label: 'Lakes & nature', ico: '🌲', amenities: ['Lake access', 'Fireplace'] },
      { label: 'Surprise me', ico: '🎲' },
    ],
  },
  {
    key: 'group', q: 'Who’s coming along?',
    options: [
      { label: 'Just me', ico: '🧍', guests: 1 },
      { label: 'Two of us', ico: '💑', guests: 2 },
      { label: 'Family', ico: '👨‍👩‍👧', guests: 5 },
      { label: 'Big group', ico: '🥳', guests: 8 },
    ],
  },
  {
    key: 'length', q: 'How long will you stay?',
    options: [
      { label: 'A weekend', ico: '🗓️', sub: '2–3 nights', nights: 2 },
      { label: 'A week', ico: '📅', sub: 'weekly discounts kick in', nights: 7 },
      { label: 'A month or more', ico: '🧳', sub: 'biggest long-stay savings', nights: 30 },
    ],
  },
  {
    key: 'budget', q: 'What’s your nightly budget?',
    options: [
      { label: 'Under $250', ico: '💵', max: 250 },
      { label: '$250 – $500', ico: '💸', min: 250, max: 500 },
      { label: '$500 – $1,000', ico: '💰', min: 500, max: 1000 },
      { label: 'Sky’s the limit', ico: '🤑' },
    ],
  },
  {
    key: 'must', q: 'Pick your one must-have',
    options: [
      { label: 'A pool', ico: '🏊', amenity: 'Pool' },
      { label: 'A hot tub', ico: '♨️', amenity: 'Hot tub' },
      { label: 'Pet-friendly', ico: '🐾', amenity: 'Pets allowed' },
      { label: 'A workspace', ico: '💻', amenity: 'Workspace' },
      { label: 'Instant Book', ico: '⚡', instantBook: true },
      { label: 'No dealbreakers', ico: '✨' },
    ],
  },
  { key: 'when', q: 'When are you going?', dynamic: 'months' },
];

// Upcoming months + a flexible option (built fresh so it's always current).
function monthOptions() {
  const out = [];
  const now = new Date();
  for (let i = 0; i < 5; i++) {
    const d = new Date(now.getFullYear(), now.getMonth() + i, 1);
    out.push({ label: d.toLocaleDateString('en-US', { month: 'long', year: 'numeric' }), ico: '📅', year: d.getFullYear(), month: d.getMonth() + 1 });
  }
  out.push({ label: 'I’m flexible', ico: '🤷', flexible: true });
  return out;
}

// Query carried into a listing so its booking widget pre-fills the stay.
function listingQuery(a) {
  const q = new URLSearchParams();
  const dates = computeDates(a);
  if (dates) { q.set('checkIn', dates.ci); q.set('checkOut', dates.co); }
  if (a.group?.guests) q.set('guests', a.group.guests);
  return q.toString();
}

// Turn the month + trip length into a concrete stay window we can check availability for.
function computeDates(a) {
  const w = a.when;
  if (!w || w.flexible) return null;
  const nights = Math.min(a.length?.nights || 3, 27);
  const now = new Date();
  const ci = (w.year === now.getFullYear() && w.month === now.getMonth() + 1)
    ? addDaysISO(todayISO(), 7)                                   // this month → a week out
    : `${w.year}-${String(w.month).padStart(2, '0')}-08`;         // future month → the 8th
  return { ci, co: addDaysISO(ci, nights) };
}

function scoreListing(l, a) {
  let s = 0;
  if (a.vibe) {
    if (a.vibe.amenities && a.vibe.amenities.some((x) => l.amenities.includes(x))) s += 3;
    if (a.vibe.types && a.vibe.types.includes(l.type)) s += 3;
  }
  if (a.group?.guests) { s += l.maxGuests >= a.group.guests ? 2 : -3; }
  if (a.budget) {
    const p = l.fromNightly, min = a.budget.min || 0, max = a.budget.max || Infinity;
    s += (p >= min && p <= max) ? 2 : (p > max ? -2 : 0);
  }
  if (a.must) {
    if (a.must.amenity && l.amenities.includes(a.must.amenity)) s += 3;
    if (a.must.instantBook && l.instantBook) s += 3;
  }
  // Trip-length fit (proxy for bookability — the quiz doesn't collect exact dates):
  if (a.length?.nights) {
    const n = a.length.nights;
    if ((l.minNights || 1) > n) s -= 2.5;                 // can't book a stay that short
    if (n >= 28 && l.monthlyDiscountPct) s += 1.5;         // best value for long stays
    else if (n >= 7 && l.weeklyDiscountPct) s += 1;
  }
  if (l.instantBook) s += 0.5;                             // instantly bookable
  s += (l.rating ? l.rating : 4.0) * 0.4;                 // reward well-reviewed homes (tiebreaker)
  return s;
}

// Short, human reasons this home matched — shown on each result card.
function matchReasons(l, a) {
  const r = [];
  if (a.vibe?.amenities) { const m = a.vibe.amenities.find((x) => l.amenities.includes(x)); if (m) r.push(m); }
  else if (a.vibe?.types?.includes(l.type)) r.push(`${l.type} in the heart of the city`);
  if (a.group?.guests && l.maxGuests >= a.group.guests) r.push(`Sleeps ${l.maxGuests}`);
  if (a.must?.amenity && l.amenities.includes(a.must.amenity)) r.push(a.must.amenity);
  if (a.must?.instantBook && l.instantBook) r.push('⚡ Instant Book');
  if (a.length?.nights >= 28 && l.monthlyDiscountPct) r.push(`${l.monthlyDiscountPct}% off monthly`);
  else if (a.length?.nights >= 7 && l.weeklyDiscountPct) r.push(`${l.weeklyDiscountPct}% off weekly`);
  if (l.rating && l.rating >= 4.7) r.push(`★ ${l.rating.toFixed(2)} top-rated`);
  if (a.budget && l.fromNightly <= (a.budget.max || Infinity)) r.push(`$${l.fromNightly.toLocaleString()}/night`);
  return r.slice(0, 4);
}

function toSearchQuery(a) {
  const q = new URLSearchParams();
  if (a.group?.guests) q.set('guests', a.group.guests);
  if (a.budget?.min) q.set('minPrice', a.budget.min);
  if (a.budget?.max) q.set('maxPrice', a.budget.max);
  if (a.must?.amenity) q.set('amenities', a.must.amenity);
  if (a.must?.instantBook) q.set('instantBook', 'true');
  const dates = computeDates(a);
  if (dates) { q.set('checkIn', dates.ci); q.set('checkOut', dates.co); }
  return q.toString();
}

export function openQuiz() {
  const root = $('#modal-root');
  const answers = {};
  let step = 0;

  const overlay = h('div', { class: 'quiz-overlay' });
  document.body.style.overflow = 'hidden';
  mount(root, overlay);

  const close = () => { markSeen(); root.innerHTML = ''; document.body.style.overflow = ''; };

  function frame(children) {
    const pct = Math.round((step / QUESTIONS.length) * 100);
    return mount(overlay, h('div', { class: 'quiz-inner' },
      h('div', { class: 'quiz-top' },
        h('div', { class: 'logo', style: { fontSize: '18px' } }, h('span', {}, '🏡'), h('b', {}, 'SmartStay'), h('span', { style: { color: 'var(--ink)', fontWeight: 700 } }, ' Trip Matcher')),
        h('button', { class: 'iconbtn', title: 'Skip', onClick: close }, '✕')),
      h('div', { class: 'quiz-bar' }, h('span', { style: { width: pct + '%' } })),
      children));
  }

  function isSelected(Q, opt) {
    if (answers[Q.key] === opt) return true;
    if (Q.key === 'when' && answers.when) {
      return (opt.flexible && answers.when.flexible) || (answers.when.year === opt.year && answers.when.month === opt.month);
    }
    return false;
  }

  function renderQuestion() {
    const Q = QUESTIONS[step];
    const opts = Q.dynamic === 'months' ? monthOptions() : Q.options;
    frame(h('div', {},
      h('div', { class: 'muted', style: { fontWeight: 700, fontSize: '13px', letterSpacing: '.05em' } }, `QUESTION ${step + 1} OF ${QUESTIONS.length}`),
      h('h2', { class: 'quiz-q' }, Q.q),
      h('div', { class: 'quiz-opts' },
        ...opts.map((opt) => h('button', {
          class: 'quiz-opt' + (isSelected(Q, opt) ? ' on' : ''),
          onClick: () => { answers[Q.key] = opt; step < QUESTIONS.length - 1 ? (step++, renderQuestion()) : finish(); },
        }, h('span', { class: 'ico' }, opt.ico), h('span', {}, opt.label, opt.sub ? h('small', {}, opt.sub) : null))),
      ),
      h('div', { class: 'row', style: { marginTop: '26px', justifyContent: 'space-between' } },
        step > 0 ? h('button', { class: 'btn btn-ghost', onClick: () => { step--; renderQuestion(); } }, '← Back') : h('span', {}),
        h('button', { class: 'btn btn-ghost muted', onClick: close }, 'Skip the quiz'))));
  }

  async function finish() {
    frame(h('div', { class: 'center', style: { paddingTop: '40px' } },
      h('h2', { class: 'quiz-q' }, 'Finding your perfect stays…'), loading()));
    const dates = computeDates(answers);
    // When dates are chosen, the server filters out anything already booked/blocked.
    const q = dates ? `?checkIn=${dates.ci}&checkOut=${dates.co}` : '';
    let listings = [];
    try { ({ listings } = await api.listings(q)); } catch { /* ignore */ }
    const ranked = listings
      .map((l) => ({ l, s: scoreListing(l, answers) }))
      .sort((a, b) => b.s - a.s)
      .slice(0, 6)
      .map((x) => x.l);
    renderResults(ranked, dates);
  }

  function renderResults(matches, dates) {
    const lq = listingQuery(answers);
    const grid = h('div', { class: 'grid', style: { marginTop: '22px' } }, ...matches.map((l) => {
      const card = listingCard(l, { query: lq });
      card.addEventListener('click', close); // navigate (with dates) + dismiss the quiz
      const reasons = matchReasons(l, answers);
      return h('div', { class: 'quiz-match' }, card,
        reasons.length ? h('div', { class: 'quiz-why' }, '✓ ', reasons.join(' · ')) : null);
    }));
    frame(h('div', {},
      h('div', { class: 'center' },
        h('div', { style: { fontSize: '44px' } }, '✨'),
        h('h2', { class: 'quiz-q' }, 'Your perfect matches'),
        h('p', { class: 'muted' }, dates
          ? `Available ${fmtDate(dates.ci)} – ${fmtDate(dates.co)} · hand-picked from your answers, booking-fee free.`
          : 'Hand-picked from your answers — and every one is booking-fee free.')),
      matches.length
        ? grid
        : h('p', { class: 'muted center', style: { padding: '20px' } }, dates
          ? 'No homes are free for those exact dates. Try “I’m flexible” or a different month.'
          : 'Browse all our homes to find your fit.'),
      h('div', { class: 'row', style: { justifyContent: 'center', marginTop: '26px', flexWrap: 'wrap' } },
        h('button', { class: 'btn btn-primary btn-lg', onClick: () => { close(); navigate('/search?' + toSearchQuery(answers)); } }, 'Browse all matches'),
        h('button', { class: 'btn btn-outline', onClick: () => { step = 0; for (const k in answers) delete answers[k]; renderQuestion(); } }, '↻ Retake quiz'))));
  }

  renderQuestion();
}
