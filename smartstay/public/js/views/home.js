import { h, mount, $, CATEGORY_ICONS } from '../ui.js';
import { api, auth } from '../api.js';
import { navigate } from '../router.js';
import { listingCard, cardGridSkeleton, searchWidget } from '../components.js';
import { openQuiz, shouldAutoQuiz } from './quiz.js';

const HERO_BG = 'https://images.unsplash.com/photo-1600585154340-be6161a56a0c?auto=format&fit=crop&w=2000&q=80';

const CATEGORIES = [
  { label: 'Villa', q: 'type=Villa' },
  { label: 'Cabin', q: 'type=Cabin' },
  { label: 'House', q: 'type=House' },
  { label: 'Apartment', q: 'type=Apartment' },
  { label: 'Ocean view', q: 'amenities=Ocean view' },
  { label: 'Pool', q: 'amenities=Pool' },
  { label: 'Mountain view', q: 'amenities=Mountain view' },
  { label: 'Ski-in/ski-out', q: 'amenities=Ski-in/ski-out' },
  { label: 'Beach access', q: 'amenities=Beach access' },
  { label: 'Hot tub', q: 'amenities=Hot tub' },
];

function valueProps() {
  const prop = (icon, title, text) => h('div', { class: 'stack', style: { gap: '6px' } },
    h('div', { style: { fontSize: '32px' } }, icon),
    h('strong', {}, title),
    h('span', { class: 'muted', style: { fontSize: '14.5px' } }, text));
  return h('section', { class: 'block' },
    h('div', { class: 'container' },
      h('div', { class: 'section-head' }, h('div', {}, h('div', { class: 'eyebrow' }, 'Why SmartStay'), h('h2', {}, 'Stay your way — a night, a week, or a season'))),
      h('div', { class: 'stat-row' },
        prop('💸', 'No booking fees', 'Guests never pay a service fee — so your total is lower than Airbnb, every time.'),
        prop('📅', 'Flexible lengths', 'Book by the weekend, week, or month with automatic long-stay discounts.'),
        prop('⚡', 'Instant Book', 'Reserve top homes in seconds — no waiting on approvals.'),
        prop('🛡️', 'Verified hosts', 'Every stay is backed by ratings, reviews, and secure checkout.'),
      ),
    ));
}

export async function homeView() {
  const app = $('#app');
  mount(app,
    h('section', { class: 'hero' },
      h('div', { class: 'hero-bg', style: { backgroundImage: `url(${HERO_BG})` } }),
      h('div', { class: 'hero-inner container' },
        h('div', { class: 'hero-badge' }, '✓ No guest booking fees — always cheaper than Airbnb'),
        h('h1', {}, 'Find your next stay in America'),
        h('p', {}, 'From cliffside villas to mountain cabins — book unforgettable homes for a weekend, a week, or a whole season. And you’ll never pay a booking fee.'),
        searchWidget({}, (q) => navigate('/search?' + q.toString())),
        h('button', { class: 'quiz-hero-btn', onClick: openQuiz }, '✨ Not sure where to go? Take the 60-second quiz →'),
      )),
    h('div', { class: 'container' },
      h('div', { class: 'catrow' },
        h('button', { class: 'cat active', onClick: () => navigate('/search') }, h('span', { class: 'ico' }, '🏠'), 'All homes'),
        ...CATEGORIES.map((c) => h('button', { class: 'cat', onClick: () => navigate('/search?' + c.q) },
          h('span', { class: 'ico' }, CATEGORY_ICONS[c.label] || '🏠'), c.label)),
      )),
    h('section', { class: 'block' },
      h('div', { class: 'container' },
        h('div', { class: 'section-head' },
          h('div', {}, h('div', { class: 'eyebrow' }, 'Featured'), h('h2', {}, 'Top-rated homes across the USA')),
          h('a', { class: 'btn btn-outline', href: '#/search' }, 'View all')),
        h('div', { id: 'home-grid' }, cardGridSkeleton(8)),
      )),
    valueProps(),
    hostCta(),
  );

  // First-time visitors get the Trip Matcher quiz automatically (once).
  if (shouldAutoQuiz()) setTimeout(openQuiz, 600);

  try {
    const { listings } = await api.listings('?sort=rating');
    mount($('#home-grid'), h('div', { class: 'grid' }, ...listings.slice(0, 8).map(listingCard)));
  } catch (err) {
    mount($('#home-grid'), h('p', { class: 'muted' }, 'Could not load listings. Is the server running?'));
  }
}

function hostCta() {
  return h('section', { class: 'block' },
    h('div', { class: 'container' },
      h('div', { style: { borderRadius: 'var(--radius-lg)', overflow: 'hidden', position: 'relative', minHeight: '320px', display: 'flex', alignItems: 'center', background: 'linear-gradient(120deg,#1a1a1a,#3a1520)' } },
        h('div', { style: { position: 'absolute', inset: 0, backgroundImage: 'url(https://images.unsplash.com/photo-1512917774080-9991f1c4c750?auto=format&fit=crop&w=1600&q=80)', backgroundSize: 'cover', backgroundPosition: 'center', opacity: .45 } }),
        h('div', { style: { position: 'relative', padding: '48px', color: '#fff', maxWidth: '560px' } },
          h('h2', { style: { color: '#fff', fontSize: '34px' } }, 'Your home could be your next big earner'),
          h('p', { style: { fontSize: '17px', opacity: .95 } }, 'List in minutes, set your own weekend, weekly, and monthly rates, and welcome guests from across the country.'),
          h('button', { class: 'btn btn-primary btn-lg', onClick: () => navigate(auth.isLoggedIn ? '/host/new' : '/signup?role=host') }, 'Start hosting →')),
      )));
}
