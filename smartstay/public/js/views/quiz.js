import { h, mount, $, loading } from '../ui.js';
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
      { label: 'A weekend', ico: '🗓️', sub: '2–3 nights' },
      { label: 'A week', ico: '📅', sub: 'weekly discounts kick in' },
      { label: 'A month or more', ico: '🧳', sub: 'biggest long-stay savings' },
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
];

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
  return s;
}

function toSearchQuery(a) {
  const q = new URLSearchParams();
  if (a.group?.guests) q.set('guests', a.group.guests);
  if (a.budget?.min) q.set('minPrice', a.budget.min);
  if (a.budget?.max) q.set('maxPrice', a.budget.max);
  if (a.must?.amenity) q.set('amenities', a.must.amenity);
  if (a.must?.instantBook) q.set('instantBook', 'true');
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

  function renderQuestion() {
    const Q = QUESTIONS[step];
    frame(h('div', {},
      h('div', { class: 'muted', style: { fontWeight: 700, fontSize: '13px', letterSpacing: '.05em' } }, `QUESTION ${step + 1} OF ${QUESTIONS.length}`),
      h('h2', { class: 'quiz-q' }, Q.q),
      h('div', { class: 'quiz-opts' },
        ...Q.options.map((opt) => h('button', {
          class: 'quiz-opt' + (answers[Q.key] === opt ? ' on' : ''),
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
    let listings = [];
    try { ({ listings } = await api.listings()); } catch { /* ignore */ }
    const ranked = listings
      .map((l) => ({ l, s: scoreListing(l, answers) }))
      .sort((a, b) => b.s - a.s)
      .slice(0, 6)
      .map((x) => x.l);
    renderResults(ranked);
  }

  function renderResults(matches) {
    const grid = h('div', { class: 'grid', style: { marginTop: '22px' } }, ...matches.map((l) => {
      const card = listingCard(l);
      card.addEventListener('click', close); // navigate + dismiss the quiz
      return card;
    }));
    frame(h('div', {},
      h('div', { class: 'center' },
        h('div', { style: { fontSize: '44px' } }, '✨'),
        h('h2', { class: 'quiz-q' }, 'Your perfect matches'),
        h('p', { class: 'muted' }, 'Hand-picked from your answers — and every one is booking-fee free.')),
      matches.length ? grid : h('p', { class: 'muted center' }, 'Browse all our homes to find your fit.'),
      h('div', { class: 'row', style: { justifyContent: 'center', marginTop: '26px', flexWrap: 'wrap' } },
        h('button', { class: 'btn btn-primary btn-lg', onClick: () => { close(); navigate('/search?' + toSearchQuery(answers)); } }, 'Browse all matches'),
        h('button', { class: 'btn btn-outline', onClick: () => { step = 0; for (const k in answers) delete answers[k]; renderQuestion(); } }, '↻ Retake quiz'))));
  }

  renderQuestion();
}
