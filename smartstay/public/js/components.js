import { h, img, usd, heartIcon, toast } from './ui.js';
import { auth, api } from './api.js';
import { navigate } from './router.js';

// In-memory set of favorited listing ids (hydrated on load if logged in).
export const favState = { ids: new Set(), loaded: false };

export async function loadFavorites() {
  if (!auth.isLoggedIn) { favState.ids = new Set(); favState.loaded = true; return; }
  try {
    const { ids } = await api.favorites();
    favState.ids = new Set(ids);
  } catch { /* ignore */ }
  favState.loaded = true;
}

export function listingCard(l, opts = {}) {
  const isFav = favState.ids.has(l.id);
  const fav = h('button', { class: `fav ${isFav ? 'on' : ''}`, title: 'Save', html: heartIcon(),
    onClick: async (e) => {
      e.stopPropagation();
      if (!auth.isLoggedIn) { navigate('/login'); return; }
      try {
        const { favorited } = await api.toggleFav(l.id);
        fav.classList.toggle('on', favorited);
        if (favorited) favState.ids.add(l.id); else favState.ids.delete(l.id);
        toast(favorited ? 'Saved to wishlist' : 'Removed', 'ok');
      } catch (err) { toast(err.message, 'err'); }
    } });

  const ratingEl = l.rating
    ? h('span', { class: 'rating' }, '★ ', l.rating.toFixed(2))
    : h('span', { class: 'rating' }, h('span', { class: 'chip' }, 'New'));

  return h('article', { class: 'card', onClick: () => navigate(`/listing/${l.id}${opts.query ? '?' + opts.query : ''}`) },
    h('div', { class: 'media' },
      img(l.photo, { alt: l.title }),
      fav,
      l.instantBook ? h('span', { class: 'tag' }, '⚡ Instant Book') : null,
    ),
    h('div', { class: 'body' },
      h('h3', { class: 'title' }, h('span', {}, `${l.city}, ${l.state}`), ratingEl),
      h('div', { class: 'sub' }, l.title),
      h('div', { class: 'sub muted' }, `${l.type} · ${l.bedrooms} bd · ${l.beds} beds · Up to ${l.maxGuests} guests`),
      h('div', { class: 'price' }, h('b', {}, usd(l.fromNightly)), ' ', h('span', { class: 'muted' }, 'night')),
    ),
  );
}

export function cardGridSkeleton(n = 8) {
  return h('div', { class: 'grid' },
    ...Array.from({ length: n }, () => h('div', {},
      h('div', { class: 'skel', style: { aspectRatio: '20/19' } }),
      h('div', { class: 'skel', style: { height: '14px', width: '70%', marginTop: '12px' } }),
      h('div', { class: 'skel', style: { height: '12px', width: '50%', marginTop: '8px' } }))));
}

// Compact search widget used on the home hero and search page.
export function searchWidget(initial = {}, onSubmit) {
  const state = {
    where: initial.city || initial.q || '',
    checkIn: initial.checkIn || '',
    checkOut: initial.checkOut || '',
    guests: initial.guests || '',
  };
  const whereInput = h('input', { placeholder: 'Search destinations', value: state.where });
  const inInput = h('input', { type: 'date', value: state.checkIn, min: new Date().toISOString().slice(0, 10) });
  const outInput = h('input', { type: 'date', value: state.checkOut, min: new Date().toISOString().slice(0, 10) });
  const guestsInput = h('input', { type: 'number', min: '1', max: '16', placeholder: 'Add guests', value: state.guests });

  const submit = () => {
    const q = new URLSearchParams();
    if (whereInput.value.trim()) q.set('city', whereInput.value.trim());
    if (inInput.value) q.set('checkIn', inInput.value);
    if (outInput.value) q.set('checkOut', outInput.value);
    if (guestsInput.value) q.set('guests', guestsInput.value);
    onSubmit ? onSubmit(q) : navigate('/search?' + q.toString());
  };
  inInput.addEventListener('change', () => { if (inInput.value) outInput.min = inInput.value; });
  [whereInput, guestsInput].forEach((el) => el.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); }));

  const field = (label, node) => h('div', { class: 'field' }, h('label', {}, label), node);
  return h('div', { class: 'searchbox' },
    field('Where', whereInput),
    h('div', { class: 'vsep' }),
    field('Check in', inInput),
    h('div', { class: 'vsep' }),
    field('Check out', outInput),
    h('div', { class: 'vsep' }),
    field('Who', guestsInput),
    h('div', { class: 'submit' }, h('button', { class: 'btn btn-primary', onClick: submit }, '🔍 Search')),
  );
}
