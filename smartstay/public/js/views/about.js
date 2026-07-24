import { h, mount, $ } from '../ui.js';
import { api } from '../api.js';
import { navigate } from '../router.js';

const HERO = 'https://images.unsplash.com/photo-1512917774080-9991f1c4c750?auto=format&fit=crop&w=2000&q=80';

export async function aboutView() {
  const app = $('#app');

  const stat = (id, label) => h('div', { class: 'stat' }, h('div', { class: 'n', id }, '—'), h('div', { class: 'l' }, label));
  const value = (icon, title, text) => h('div', { class: 'stack', style: { gap: '6px' } },
    h('div', { style: { fontSize: '30px' } }, icon), h('strong', {}, title),
    h('span', { class: 'muted', style: { fontSize: '14.5px' } }, text));

  mount(app,
    h('section', { class: 'hero', style: { minHeight: '380px' } },
      h('div', { class: 'hero-bg', style: { backgroundImage: `url(${HERO})` } }),
      h('div', { class: 'hero-inner container' },
        h('div', { class: 'eyebrow', style: { color: '#fff', opacity: .9 } }, 'About us'),
        h('h1', { style: { maxWidth: '760px' } }, 'Stays that feel like they were made for you'))),

    h('section', { class: 'block' },
      h('div', { class: 'container', style: { maxWidth: '760px' } },
        h('p', { style: { fontSize: '20px', lineHeight: '1.7', color: 'var(--ink-2)' } },
          'SmartStay USA was born from a simple belief: finding a place to stay should feel as good as the trip itself. ' +
          'We connect travelers with a hand-picked collection of homes across the country — cliffside villas, mountain cabins, ' +
          'downtown lofts, and beach cottages — and let you book them your way, whether that’s a spontaneous weekend, a working ' +
          'week, or a whole season. Every host sets their own nightly, weekly, and monthly rates, so longer stays come with real ' +
          'savings, and every home is backed by verified reviews and secure checkout. And unlike the other guys, we never charge ' +
          'guests a booking fee — no hidden math, no surprises, just a lower total than you’d pay on Airbnb, plus an interactive ' +
          'map and a place that feels like yours the moment you walk in. For hosts, SmartStay ' +
          'is the simplest way to turn a home into income, with full control over pricing, availability, and who stays. We’re ' +
          'building the most trusted, human, and genuinely beautiful way to travel across America — one great stay at a time.'),
        h('div', { class: 'stat-row', style: { marginTop: '34px' } },
          stat('about-homes', 'Homes to book'),
          stat('about-cities', 'US destinations'),
          stat('about-flex', 'Ways to stay')),
      )),

    h('section', { class: 'block', style: { background: 'var(--bg-2)' } },
      h('div', { class: 'container' },
        h('div', { class: 'section-head' }, h('div', {}, h('div', { class: 'eyebrow' }, 'What we stand for'), h('h2', {}, 'The SmartStay promise'))),
        h('div', { class: 'stat-row' },
          value('💸', 'No booking fees', 'Guests never pay a service fee — your total is lower than Airbnb, every single time.'),
          value('📅', 'Book your way', 'Weekend, week, or month — with automatic long-stay discounts baked in.'),
          value('🛡️', 'Trust built in', 'Verified hosts, real guest reviews, and secure checkout on every stay.'),
          value('🗺️', 'Truly local', 'Interactive maps and honest descriptions so you always know where you’ll be.')),
      )),

    h('section', { class: 'block' },
      h('div', { class: 'container center', style: { maxWidth: '640px' } },
        h('h2', { style: { fontSize: '30px' } }, 'Your next stay is waiting'),
        h('p', { class: 'muted', style: { fontSize: '17px' } }, 'Explore beautiful homes across the USA, or list your own and start earning.'),
        h('div', { class: 'row', style: { justifyContent: 'center', marginTop: '18px' } },
          h('button', { class: 'btn btn-primary btn-lg', onClick: () => navigate('/search') }, 'Explore stays'),
          h('button', { class: 'btn btn-outline btn-lg', onClick: () => navigate('/host/new') }, 'Become a host')))),
  );

  try {
    const [{ count }, { cities }] = await Promise.all([api.listings(), api.meta()]);
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    set('about-homes', String(count));
    set('about-cities', String((cities || []).length));
    set('about-flex', '3');
  } catch { /* stats are decorative */ }
}
