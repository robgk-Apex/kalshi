import { h, mount, $, img, usd, fmtDate, fmtRange, timeAgo, empty, openModal, toast, stars } from '../ui.js';
import { api, auth } from '../api.js';
import { navigate } from '../router.js';
import { listingCard } from '../components.js';

function requireAuth() {
  if (!auth.isLoggedIn) { navigate('/login'); return false; }
  return true;
}

function statusBadge(s) { return h('span', { class: `badge status-${s}` }, s[0].toUpperCase() + s.slice(1)); }

function reviewModal(booking, onDone) {
  let rating = 5;
  const starRow = h('div', { style: { fontSize: '34px', cursor: 'pointer', color: 'var(--gold)', letterSpacing: '4px' } });
  const draw = () => mount(starRow, ...[1, 2, 3, 4, 5].map((n) => h('span', { onClick: () => { rating = n; draw(); } }, n <= rating ? '★' : '☆')));
  draw();
  const comment = h('textarea', { placeholder: 'Tell other guests about your stay…' });
  const body = h('div', { class: 'form' },
    h('div', { class: 'center' }, starRow),
    comment,
    h('button', { class: 'btn btn-primary btn-block', onClick: async () => {
      try {
        await api.post(`/listings/${booking.listingId}/reviews`, { rating, comment: comment.value, bookingId: booking.id });
        toast('Thanks for your review! ⭐', 'ok');
        document.getElementById('modal-root').innerHTML = ''; document.body.style.overflow = '';
        onDone && onDone();
      } catch (e) { toast(e.message, 'err'); }
    } }, 'Submit review'));
  openModal(`Review · ${booking.listing?.title || 'your stay'}`, body);
}

function tripRow(b, reload) {
  const l = b.listing;
  return h('div', { class: 'list-row' },
    l ? img(l.photo, { class: 'thumb', onClick: () => navigate(`/listing/${l.id}`) }) : null,
    h('div', { class: 'grow' },
      h('div', { class: 'spread' }, h('strong', {}, l?.title || 'Listing removed'), statusBadge(b.status)),
      h('div', { class: 'muted' }, l ? `${l.city}, ${l.state}` : '', ' · ', `${b.nights} nights · ${b.guests} guests`),
      h('div', { class: 'muted' }, `📅 ${fmtRange(b.checkIn, b.checkOut)}`),
      h('div', { style: { marginTop: '6px' } }, h('strong', {}, usd(b.total)), h('span', { class: 'muted' }, ' total')),
    ),
    h('div', { class: 'stack', style: { gap: '8px' } },
      b.isPast && !b.reviewed && l ? h('button', { class: 'btn btn-outline', onClick: () => reviewModal(b, reload) }, '⭐ Review') : null,
      b.reviewed ? h('span', { class: 'chip' }, '✓ Reviewed') : null,
      !b.isPast && b.status !== 'cancelled' ? h('button', { class: 'btn btn-ghost', onClick: async () => {
        if (!confirm('Cancel this booking?')) return;
        try { await api.post(`/bookings/${b.id}/cancel`); toast('Booking cancelled', 'ok'); reload(); } catch (e) { toast(e.message, 'err'); }
      } }, 'Cancel') : null,
    ),
  );
}

export async function tripsView() {
  if (!requireAuth()) return;
  const app = $('#app');
  mount(app, h('div', { class: 'container', style: { paddingTop: '30px' } }, h('h1', { style: { fontSize: '30px' } }, 'Your trips'), h('div', { class: 'spinner' })));
  const reload = () => tripsView();
  try {
    const { bookings } = await api.myBookings();
    const upcoming = bookings.filter((b) => !b.isPast && b.status !== 'cancelled');
    const past = bookings.filter((b) => b.isPast || b.status === 'cancelled');
    mount(app, h('div', { class: 'container', style: { paddingTop: '30px', paddingBottom: '40px' } },
      h('h1', { style: { fontSize: '30px' } }, 'Your trips'),
      bookings.length === 0
        ? empty('🧳', 'No trips yet', 'Time to dust off your bags and start planning your next adventure.', h('a', { class: 'btn btn-primary', href: '#/search' }, 'Start exploring'))
        : h('div', {},
          upcoming.length ? h('div', {}, h('h3', { style: { marginTop: '20px' } }, 'Upcoming'), h('div', { class: 'stack', style: { gap: '14px' } }, ...upcoming.map((b) => tripRow(b, reload)))) : null,
          past.length ? h('div', {}, h('h3', { style: { marginTop: '28px' } }, 'Where you’ve been'), h('div', { class: 'stack', style: { gap: '14px' } }, ...past.map((b) => tripRow(b, reload)))) : null,
        )));
  } catch (err) { mount(app, h('div', { class: 'container' }, h('p', { class: 'muted' }, err.message))); }
}

export async function favoritesView() {
  if (!requireAuth()) return;
  const app = $('#app');
  mount(app, h('div', { class: 'container', style: { paddingTop: '30px' } }, h('h1', { style: { fontSize: '30px' } }, 'Wishlists'), h('div', { class: 'spinner' })));
  try {
    const { listings } = await api.favorites();
    mount(app, h('div', { class: 'container', style: { paddingTop: '30px', paddingBottom: '40px' } },
      h('h1', { style: { fontSize: '30px' } }, 'Wishlists'),
      listings.length
        ? h('div', { class: 'grid', style: { marginTop: '20px' } }, ...listings.map(listingCard))
        : empty('❤️', 'No saved homes yet', 'Tap the heart on any home to save it here.', h('a', { class: 'btn btn-primary', href: '#/search' }, 'Find homes'))));
  } catch (err) { mount(app, h('div', { class: 'container' }, h('p', { class: 'muted' }, err.message))); }
}

export async function inboxView() {
  if (!requireAuth()) return;
  const app = $('#app');
  mount(app, h('div', { class: 'container', style: { paddingTop: '30px' } }, h('h1', { style: { fontSize: '30px' } }, 'Messages'), h('div', { class: 'spinner' })));
  try {
    const { threads } = await api.get('/messages');
    mount(app, h('div', { class: 'container', style: { paddingTop: '30px', paddingBottom: '40px' } },
      h('h1', { style: { fontSize: '30px' } }, 'Messages'),
      threads.length
        ? h('div', { class: 'stack', style: { gap: '14px', marginTop: '18px' } },
          ...threads.map((t) => h('div', { class: 'list-row', onClick: () => t.listing && navigate(`/listing/${t.listing.id}`) },
            t.listing ? img(t.listing.photo, { class: 'thumb' }) : null,
            h('div', { class: 'grow' },
              h('strong', {}, t.listing?.title || 'Conversation'),
              h('p', { class: 'muted', style: { margin: '4px 0 0' } }, t.messages[t.messages.length - 1]?.body || ''),
              h('span', { class: 'muted', style: { fontSize: '13px' } }, timeAgo(t.lastAt))))))
        : empty('✉️', 'No messages yet', 'Message a host from any listing to start a conversation.', h('a', { class: 'btn btn-primary', href: '#/search' }, 'Browse homes'))));
  } catch (err) { mount(app, h('div', { class: 'container' }, h('p', { class: 'muted' }, err.message))); }
}

export function profileView() {
  if (!requireAuth()) return;
  const app = $('#app');
  const u = auth.user;
  const name = h('input', { class: 'input', value: u.name });
  const bio = h('textarea', { class: 'input', placeholder: 'Tell guests a little about yourself…' }, u.bio || '');
  bio.value = u.bio || '';
  const isHost = h('input', { type: 'checkbox', checked: u.isHost });
  mount(app, h('div', { class: 'container', style: { paddingTop: '30px', paddingBottom: '40px', maxWidth: '620px' } },
    h('h1', { style: { fontSize: '30px' } }, 'Account'),
    h('div', { class: 'row', style: { margin: '18px 0' } }, img(u.avatar, { class: 'avatar', style: { width: '76px', height: '76px' } }),
      h('div', {}, h('strong', { style: { fontSize: '18px' } }, u.name), h('div', { class: 'muted' }, u.email))),
    h('div', { class: 'form' },
      h('div', { class: 'field-group' }, h('label', {}, 'Name'), name),
      h('div', { class: 'field-group' }, h('label', {}, 'About'), bio),
      h('label', { class: 'check' }, isHost, '🏡 Enable hosting'),
      h('button', { class: 'btn btn-primary', style: { alignSelf: 'flex-start' }, onClick: async () => {
        try { const { user } = await api.patch('/auth/me', { name: name.value, bio: bio.value, isHost: isHost.checked }); auth.update(user); toast('Profile saved', 'ok'); }
        catch (e) { toast(e.message, 'err'); }
      } }, 'Save changes'),
      h('div', { class: 'menu-sep' }),
      h('button', { class: 'btn btn-outline', style: { alignSelf: 'flex-start' }, onClick: () => { auth.clear(); navigate('/'); } }, 'Log out'),
    )));
}
