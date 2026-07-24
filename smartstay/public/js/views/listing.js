import { h, mount, $, img, usd, stars, fmtDate, timeAgo, lightbox, openModal, toast, empty, heartIcon, AMENITY_ICONS, todayISO, addDaysISO } from '../ui.js';
import { api, auth } from '../api.js';
import { navigate } from '../router.js';
import { favState } from '../components.js';

function gallery(photos) {
  const safe = photos.length ? photos : ['https://images.unsplash.com/photo-1568605114967-8130f3a36994?auto=format&fit=crop&w=1200&q=80'];
  const pics = [...safe, ...safe, ...safe].slice(0, 5);
  return h('div', { class: 'gallery' },
    ...pics.map((src, i) => img(src, { class: i === 0 ? 'main' : '', onClick: () => lightbox(safe, i % safe.length) })));
}

function reviewsBlock(listing) {
  if (!listing.reviews.length) {
    return h('div', { class: 'detail-sec' }, h('h3', {}, 'Reviews'), h('p', { class: 'muted' }, 'No reviews yet — be the first to stay here.'));
  }
  return h('div', { class: 'detail-sec' },
    h('div', { class: 'review-summary' }, '★', ` ${listing.rating.toFixed(2)}`, h('span', { class: 'dot' }), `${listing.reviewCount} review${listing.reviewCount > 1 ? 's' : ''}`),
    h('div', { class: 'reviews-grid' },
      ...listing.reviews.slice(0, 8).map((r) => h('div', { class: 'review' },
        h('div', { class: 'who' },
          img(r.author?.avatar, { class: 'avatar' }),
          h('div', {}, h('strong', {}, r.author?.name || 'Guest'), h('div', { class: 'muted', style: { fontSize: '13px' } }, timeAgo(r.createdAt)))),
        h('div', { class: 'stars' }, stars(r.rating)),
        h('p', { style: { margin: '6px 0 0' } }, r.comment)))));
}

function bookingWidget(listing) {
  const card = h('div', { class: 'booking-card' });
  const state = { checkIn: '', checkOut: '', guests: 1, quote: null };

  const inInput = h('input', { type: 'date', min: todayISO() });
  const outInput = h('input', { type: 'date', min: addDaysISO(todayISO(), 1) });
  const guestsSel = h('select', {},
    ...Array.from({ length: listing.maxGuests }, (_, i) => h('option', { value: i + 1 }, `${i + 1} guest${i ? 's' : ''}`)));

  const summary = h('div', { id: 'quote-summary' });
  const reserveBtn = h('button', { class: 'btn btn-primary btn-block btn-lg', disabled: true }, listing.instantBook ? '⚡ Reserve now' : 'Request to book');

  async function refresh() {
    state.checkIn = inInput.value; state.checkOut = outInput.value; state.guests = Number(guestsSel.value);
    if (state.checkIn) outInput.min = addDaysISO(state.checkIn, 1);
    if (!state.checkIn || !state.checkOut) {
      mount(summary, h('p', { class: 'muted center', style: { padding: '6px 0' } }, 'Add your dates for an exact total'));
      reserveBtn.disabled = true; state.quote = null; return;
    }
    mount(summary, h('div', { class: 'center muted', style: { padding: '10px' } }, 'Calculating…'));
    try {
      const q = await api.quote(listing.id, { checkIn: state.checkIn, checkOut: state.checkOut, guests: state.guests });
      state.quote = q;
      if (!q.available) {
        mount(summary, h('div', { class: 'badge status-cancelled', style: { display: 'block', textAlign: 'center', padding: '12px' } }, '🚫 Not available for these dates'));
        reserveBtn.disabled = true; return;
      }
      renderQuote(q);
      reserveBtn.disabled = false;
    } catch (err) {
      mount(summary, h('div', { class: 'badge status-cancelled', style: { display: 'block', textAlign: 'center', padding: '12px' } }, err.message));
      reserveBtn.disabled = true; state.quote = null;
    }
  }

  function line(label, value, cls = '') { return h('div', { class: `price-line ${cls}` }, h('span', {}, label), h('span', {}, value)); }
  function renderQuote(q) {
    mount(summary,
      line(h('span', { class: 'u' }, `${usd(q.avgPerNight)} avg × ${q.nights} night${q.nights > 1 ? 's' : ''}`), usd(q.base)),
      q.discount ? line(q.discountLabel + ` (−${q.discountPct}%)`, '−' + usd(q.discount), 'discount') : null,
      q.cleaningFee ? line(h('span', { class: 'u' }, 'Cleaning fee'), usd(q.cleaningFee)) : null,
      line(h('span', { class: 'u' }, 'Service fee'), usd(q.serviceFee)),
      line(h('span', { class: 'u' }, 'Taxes'), usd(q.taxes)),
      line('Total (USD)', usd(q.total), 'total'),
    );
  }

  [inInput, outInput, guestsSel].forEach((el) => el.addEventListener('change', refresh));

  reserveBtn.addEventListener('click', async () => {
    if (!auth.isLoggedIn) { toast('Please log in to book', 'err'); navigate('/login'); return; }
    reserveBtn.disabled = true; reserveBtn.textContent = 'Booking…';
    try {
      const { booking } = await api.book({ listingId: listing.id, checkIn: state.checkIn, checkOut: state.checkOut, guests: state.guests });
      confirmModal(listing, booking);
    } catch (err) {
      toast(err.message, 'err');
      reserveBtn.disabled = false; reserveBtn.textContent = listing.instantBook ? '⚡ Reserve now' : 'Request to book';
    }
  });

  const nightly = listing.pricing?.nightly;
  mount(card,
    h('div', { class: 'spread', style: { alignItems: 'baseline' } },
      h('div', { class: 'price-lead' }, usd(listing.fromNightly), h('span', { class: 'muted', style: { fontWeight: 400, fontSize: '15px' } }, ' night')),
      listing.rating ? h('span', { class: 'rating', style: { fontWeight: 600 } }, `★ ${listing.rating.toFixed(2)} · ${listing.reviewCount}`) : h('span', { class: 'chip' }, 'New')),
    h('div', { class: 'booking-fields' },
      h('div', { class: 'r2' },
        h('div', { class: 'bf' }, h('label', {}, 'Check-in'), inInput),
        h('div', { class: 'bf' }, h('label', {}, 'Check-out'), outInput)),
      h('div', { class: 'bf rowtop' }, h('label', {}, 'Guests'), guestsSel)),
    reserveBtn,
    h('p', { class: 'muted center', style: { fontSize: '13px', margin: '12px 0 0' } }, listing.instantBook ? 'You won’t be charged yet' : 'The host will confirm within 24h'),
    summary,
    listing.pricing?.weeklyDiscountPct || listing.pricing?.monthlyDiscountPct ?
      h('div', { class: 'demo-note', style: { marginTop: '14px' } },
        '💡 Long-stay savings: ',
        listing.pricing.weeklyDiscountPct ? `${listing.pricing.weeklyDiscountPct}% off weekly` : '',
        listing.pricing.weeklyDiscountPct && listing.pricing.monthlyDiscountPct ? ' · ' : '',
        listing.pricing.monthlyDiscountPct ? `${listing.pricing.monthlyDiscountPct}% off monthly` : '') : null,
  );
  mount(summary, h('p', { class: 'muted center', style: { padding: '6px 0' } }, 'Add your dates for an exact total'));
  return card;
}

function confirmModal(listing, booking) {
  const body = h('div', { class: 'center' },
    h('div', { style: { fontSize: '54px' } }, '🎉'),
    h('h2', { style: { fontSize: '24px' } }, booking.status === 'confirmed' ? 'You’re booked!' : 'Request sent!'),
    h('p', { class: 'muted' }, booking.status === 'confirmed'
      ? `Your stay at ${listing.title} is confirmed.`
      : `Your request for ${listing.title} was sent to the host.`),
    h('div', { style: { textAlign: 'left', border: '1px solid var(--line)', borderRadius: '14px', padding: '16px', margin: '18px 0' } },
      h('div', { class: 'spread' }, h('span', { class: 'muted' }, 'Dates'), h('strong', {}, `${fmtDate(booking.checkIn)} – ${fmtDate(booking.checkOut)}`)),
      h('div', { class: 'spread', style: { marginTop: '8px' } }, h('span', { class: 'muted' }, 'Guests'), h('strong', {}, String(booking.guests))),
      h('div', { class: 'spread', style: { marginTop: '8px' } }, h('span', { class: 'muted' }, 'Total'), h('strong', {}, usd(booking.total)))),
    h('button', { class: 'btn btn-primary btn-block', onClick: () => { document.getElementById('modal-root').innerHTML = ''; document.body.style.overflow = ''; navigate('/trips'); } }, 'View my trips'),
  );
  openModal(' ', body);
}

export async function listingView({ params }) {
  const app = $('#app');
  mount(app, h('div', { class: 'container' }, h('div', { class: 'spinner' })));
  let data;
  try { data = await api.listing(params.id); }
  catch (err) { mount(app, h('div', { class: 'container' }, empty('😕', 'Listing not found', err.message, h('a', { class: 'btn btn-primary', href: '#/search' }, 'Browse homes')))); return; }
  const l = data.listing;

  const isFav = favState.ids.has(l.id);
  const favBtn = h('button', { class: 'btn btn-ghost', html: `<span style="display:flex;gap:6px;align-items:center"><span style="width:18px;display:inline-block">${heartIcon()}</span>${isFav ? 'Saved' : 'Save'}</span>`,
    onClick: async () => {
      if (!auth.isLoggedIn) return navigate('/login');
      try { const { favorited } = await api.toggleFav(l.id); favorited ? favState.ids.add(l.id) : favState.ids.delete(l.id); toast(favorited ? 'Saved to wishlist' : 'Removed', 'ok'); listingView({ params }); }
      catch (e) { toast(e.message, 'err'); }
    } });

  mount(app,
    h('div', { class: 'container detail-head' },
      h('div', { class: 'breadcrumb' }, h('a', { href: '#/search' }, 'Homes'), ' / ', h('a', { href: `#/search?city=${encodeURIComponent(l.state)}` }, `${l.city}, ${l.state}`), ' / ', l.type),
      h('div', { class: 'spread wrap' },
        h('h1', { class: 'detail-title' }, l.title),
        h('div', { class: 'row' },
          h('button', { class: 'btn btn-ghost', onClick: () => { navigator.clipboard?.writeText(location.href); toast('Link copied', 'ok'); } }, '🔗 Share'),
          favBtn)),
      h('div', { class: 'row wrap muted', style: { gap: '4px', marginTop: '2px' } },
        l.rating ? h('strong', { style: { color: 'var(--ink)' } }, `★ ${l.rating.toFixed(2)}`) : h('span', { class: 'chip' }, 'New'),
        l.reviewCount ? h('span', {}, ` · ${l.reviewCount} reviews · `) : h('span', {}, ' · '),
        h('strong', { style: { color: 'var(--ink)' } }, `${l.city}, ${l.state}`)),
      gallery(l.photos),
    ),
    h('div', { class: 'container' },
      h('div', { class: 'detail-grid' },
        h('div', {},
          h('div', { class: 'detail-sec spread' },
            h('div', {},
              h('h2', { style: { fontSize: '22px' } }, `${l.type} hosted by ${l.host?.name || 'a SmartStay host'}`),
              h('div', { class: 'muted' }, `${l.maxGuests} guests · ${l.bedrooms} bedrooms · ${l.beds} beds · ${l.bathrooms} baths`)),
            img(l.host?.avatar, { class: 'avatar', style: { width: '56px', height: '56px' } })),
          h('div', { class: 'detail-sec' }, h('p', { style: { fontSize: '16px', color: 'var(--ink-2)' } }, l.description)),
          h('div', { class: 'detail-sec' },
            h('h3', {}, 'What this place offers'),
            h('div', { class: 'amenity-grid' },
              ...l.amenities.map((a) => h('div', { class: 'amenity' }, h('span', { class: 'ico' }, AMENITY_ICONS[a] || '✓'), a)))),
          mapBlock(l),
          reviewsBlock(l),
        ),
        h('div', {}, bookingWidget(l)),
      )),
  );
}

function mapBlock(l) {
  return h('div', { class: 'detail-sec' },
    h('h3', {}, 'Where you’ll be'),
    h('p', { class: 'muted', style: { marginTop: '-4px' } }, `${l.city}, ${l.state}`),
    h('div', { class: 'map-box', style: { backgroundImage: 'linear-gradient(120deg,#dbe7f0,#eef3f7)' } },
      h('div', { style: { position: 'absolute', inset: 0, opacity: .5, backgroundImage: 'url(https://images.unsplash.com/photo-1524661135-423995f22d0b?auto=format&fit=crop&w=1200&q=60)', backgroundSize: 'cover', backgroundPosition: 'center' } }),
      h('div', { class: 'map-pin' }, `📍 ${l.city}`)));
}
