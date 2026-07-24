import { h, mount, $, img, usd, fmtRange, empty, toast, openModal } from '../ui.js';
import { api, auth } from '../api.js';
import { navigate } from '../router.js';

let META = null;

const PRESET_PHOTOS = [
  '1568605114967-8130f3a36994', '1512917774080-9991f1c4c750', '1600585154340-be6161a56a0c',
  '1600596542815-ffad4c1539a9', '1600607687939-ce8a6c25118c', '1600566753086-00f18fb6b3ea',
  '1580587771525-78b9dba3b914', '1570129477492-45c003edd2be', '1613490493576-7fde63acd811',
  '1502672260266-1c1ef2d93688', '1560448204-e02f11c3d0e2', '1449844908441-8829872d2607',
  '1493809842364-78817add7ffb', '1518780664697-55e3ad937233', '1600585152220-90363fe7e115',
  '1600121848594-d8644e57abab',
].map((id) => `https://images.unsplash.com/photo-${id}?auto=format&fit=crop&w=1200&q=80`);

function requireAuth() { if (!auth.isLoggedIn) { navigate('/login'); return false; } return true; }

// ---------- Host dashboard ----------
export async function hostView() {
  if (!requireAuth()) return;
  const app = $('#app');
  mount(app, h('div', { class: 'container', style: { paddingTop: '30px' } }, h('h1', { style: { fontSize: '30px' } }, 'Hosting'), h('div', { class: 'spinner' })));
  let listings = [], bookings = [];
  try { ({ listings } = await api.hostListings()); ({ bookings } = await api.hostBookings()); }
  catch (err) { mount(app, h('div', { class: 'container' }, h('p', { class: 'muted' }, err.message))); return; }

  const grossTotal = listings.reduce((s, l) => s + (l.gross || 0), 0);
  const feeTotal = listings.reduce((s, l) => s + (l.platformFee || 0), 0);
  const payoutTotal = listings.reduce((s, l) => s + (l.payout || 0), 0);
  const totalBookings = bookings.filter((b) => b.status !== 'cancelled').length;
  const pending = bookings.filter((b) => b.status === 'pending');
  const reload = () => hostView();

  mount(app, h('div', { class: 'container', style: { paddingTop: '30px', paddingBottom: '50px' } },
    h('div', { class: 'spread wrap' },
      h('h1', { style: { fontSize: '30px' } }, `Welcome back, ${auth.user.name.split(' ')[0]}`),
      h('button', { class: 'btn btn-primary', onClick: () => navigate('/host/new') }, '➕ Add a home')),

    h('div', { class: 'stat-row' },
      h('div', { class: 'stat' }, h('div', { class: 'n' }, String(listings.length)), h('div', { class: 'l' }, 'Active listings')),
      h('div', { class: 'stat' }, h('div', { class: 'n' }, String(totalBookings)), h('div', { class: 'l' }, 'Total bookings')),
      h('div', { class: 'stat' }, h('div', { class: 'n', style: { color: 'var(--green)' } }, usd(payoutTotal)), h('div', { class: 'l' }, 'Your payout (80%)')),
      h('div', { class: 'stat' }, h('div', { class: 'n' }, String(pending.length)), h('div', { class: 'l' }, 'Pending requests')),
    ),

    h('div', { class: 'demo-note', style: { marginBottom: '24px', display: 'flex', gap: '16px', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center' } },
      h('span', {}, `💸 SmartStay keeps 20% of gross booking revenue — you keep 80%.`),
      h('span', { style: { fontWeight: 600 } }, `Gross ${usd(grossTotal)} · SmartStay fee ${usd(feeTotal)} · Your payout ${usd(payoutTotal)}`)),

    pending.length ? h('div', {},
      h('h3', {}, '⏳ Requests needing your review'),
      h('div', { class: 'stack', style: { gap: '12px', marginBottom: '28px' } }, ...pending.map((b) => bookingRow(b, reload, true)))) : null,

    h('h3', {}, 'Your listings'),
    listings.length
      ? h('div', { class: 'stack', style: { gap: '14px' } }, ...listings.map((l) => listingRow(l, reload)))
      : empty('🏡', 'No listings yet', 'List your first home and start earning.', h('button', { class: 'btn btn-primary', onClick: () => navigate('/host/new') }, 'Get started')),

    bookings.length ? h('div', {}, h('h3', { style: { marginTop: '34px' } }, 'All bookings'),
      h('div', { class: 'stack', style: { gap: '12px' } }, ...bookings.map((b) => bookingRow(b, reload, false)))) : null,
  ));
}

function listingRow(l, reload) {
  return h('div', { class: 'list-row' },
    img(l.photo, { class: 'thumb', onClick: () => navigate(`/listing/${l.id}`) }),
    h('div', { class: 'grow' },
      h('strong', {}, l.title),
      h('div', { class: 'muted' }, `${l.city}, ${l.state} · ${usd(l.fromNightly)}/night`),
      h('div', { class: 'muted', style: { fontSize: '13.5px' } }, `${l.bookingCount} bookings · ${usd(l.payout || 0)} payout · ${l.rating ? '★ ' + l.rating.toFixed(1) : 'No reviews'}`)),
    h('div', { class: 'row' },
      h('button', { class: 'btn btn-outline', onClick: () => navigate(`/host/edit/${l.id}`) }, 'Edit'),
      h('button', { class: 'btn btn-ghost', onClick: async () => {
        if (!confirm(`Delete "${l.title}"? This cannot be undone.`)) return;
        try { await api.del(`/host/listings/${l.id}`); toast('Listing deleted', 'ok'); reload(); } catch (e) { toast(e.message, 'err'); }
      } }, '🗑️')));
}

function bookingRow(b, reload, actionable) {
  return h('div', { class: 'list-row' },
    b.listing ? img(b.listing.photo, { class: 'thumb' }) : null,
    h('div', { class: 'grow' },
      h('div', { class: 'spread' }, h('strong', {}, b.listing?.title || 'Listing'), h('span', { class: `badge status-${b.status}` }, b.status)),
      h('div', { class: 'muted' }, `${b.guest?.name || 'Guest'} · ${b.guests} guests · ${fmtRange(b.checkIn, b.checkOut)}`),
      h('div', {}, h('strong', { style: { color: 'var(--green)' } }, usd(b.payout || 0)), h('span', { class: 'muted' }, ` payout · ${usd(b.total)} gross`))),
    actionable && b.status === 'pending' ? h('div', { class: 'row' },
      h('button', { class: 'btn btn-primary', onClick: async () => { try { await api.post(`/bookings/${b.id}/confirm`); toast('Booking confirmed', 'ok'); reload(); } catch (e) { toast(e.message, 'err'); } } }, 'Confirm'),
      h('button', { class: 'btn btn-ghost', onClick: async () => { try { await api.post(`/bookings/${b.id}/cancel`); toast('Declined', 'ok'); reload(); } catch (e) { toast(e.message, 'err'); } } }, 'Decline')) : null);
}

// ---------- Listing editor (create/edit) ----------
export async function hostEditView({ params }) {
  if (!requireAuth()) return;
  const app = $('#app');
  const editing = !!params?.id;
  if (!META) { try { META = await api.meta(); } catch { META = { amenities: [], types: [] }; } }

  let existing = null;
  if (editing) {
    mount(app, h('div', { class: 'container' }, h('div', { class: 'spinner' })));
    try { const { listings } = await api.hostListings(); existing = listings.find((l) => l.id === params.id); }
    catch (e) { toast(e.message, 'err'); }
    if (!existing) { mount(app, h('div', { class: 'container' }, empty('😕', 'Listing not found', '', h('a', { class: 'btn btn-primary', href: '#/host' }, 'Back to hosting')))); return; }
  }

  const D = existing || {};
  const P = D.pricing || {};
  const selectedPhotos = new Set(D.photos || []);
  const selectedAmenities = new Set(D.amenities || []);

  const f = {
    title: h('input', { class: 'input', placeholder: 'Charming beach cottage with ocean views', value: D.title || '' }),
    description: h('textarea', { class: 'input', placeholder: 'Describe what makes your place special…' }),
    type: h('select', { class: 'input' }, ...(META.types || ['House']).map((t) => h('option', { value: t, selected: D.type === t }, t))),
    city: h('input', { class: 'input', placeholder: 'Austin', value: D.city || '' }),
    state: h('input', { class: 'input', placeholder: 'TX', maxlength: '2', value: D.state || '' }),
    bedrooms: h('input', { class: 'input', type: 'number', min: '0', value: D.bedrooms ?? 1 }),
    beds: h('input', { class: 'input', type: 'number', min: '1', value: D.beds ?? 1 }),
    bathrooms: h('input', { class: 'input', type: 'number', min: '1', value: D.bathrooms ?? 1 }),
    maxGuests: h('input', { class: 'input', type: 'number', min: '1', value: D.maxGuests ?? 2 }),
    nightly: h('input', { class: 'input', type: 'number', min: '10', value: P.nightly ?? 150 }),
    weekendNightly: h('input', { class: 'input', type: 'number', min: '0', placeholder: 'Optional', value: P.weekendNightly || '' }),
    weeklyDiscountPct: h('input', { class: 'input', type: 'number', min: '0', max: '60', value: P.weeklyDiscountPct ?? 10 }),
    monthlyDiscountPct: h('input', { class: 'input', type: 'number', min: '0', max: '70', value: P.monthlyDiscountPct ?? 25 }),
    cleaningFee: h('input', { class: 'input', type: 'number', min: '0', value: P.cleaningFee ?? 75 }),
    minNights: h('input', { class: 'input', type: 'number', min: '1', value: D.minNights ?? 2 }),
    instantBook: h('input', { type: 'checkbox', checked: D.instantBook ?? true }),
  };
  f.description.value = D.description || '';

  const photoGrid = h('div', { class: 'check-grid', style: { gridTemplateColumns: 'repeat(auto-fill,minmax(110px,1fr))' } },
    ...PRESET_PHOTOS.map((url) => {
      const on = selectedPhotos.has(url);
      const tile = h('div', { style: { position: 'relative', cursor: 'pointer', borderRadius: '10px', overflow: 'hidden', aspectRatio: '4/3', outline: on ? '3px solid var(--brand)' : '1px solid var(--line-2)' } },
        img(url), h('span', { class: 'photo-check', style: { position: 'absolute', top: '6px', right: '6px', width: '22px', height: '22px', borderRadius: '50%', background: on ? 'var(--brand)' : 'rgba(255,255,255,.85)', color: '#fff', display: 'grid', placeItems: 'center', fontSize: '13px' } }, on ? '✓' : ''));
      tile.addEventListener('click', () => {
        if (selectedPhotos.has(url)) selectedPhotos.delete(url); else selectedPhotos.add(url);
        const now = selectedPhotos.has(url);
        tile.style.outline = now ? '3px solid var(--brand)' : '1px solid var(--line-2)';
        const chk = tile.querySelector('.photo-check'); chk.style.background = now ? 'var(--brand)' : 'rgba(255,255,255,.85)'; chk.textContent = now ? '✓' : '';
      });
      return tile;
    }));

  const amenityGrid = h('div', { class: 'check-grid' },
    ...(META.amenities || []).map((a) => {
      const cb = h('input', { type: 'checkbox', checked: selectedAmenities.has(a) });
      const wrap = h('label', { class: `check ${selectedAmenities.has(a) ? 'on' : ''}` }, cb, a);
      cb.addEventListener('change', () => { cb.checked ? selectedAmenities.add(a) : selectedAmenities.delete(a); wrap.classList.toggle('on', cb.checked); });
      return wrap;
    }));

  const fg = (label, node, hint) => h('div', { class: 'field-group' }, h('label', {}, label), node, hint ? h('small', { class: 'muted' }, hint) : null);

  const save = async () => {
    const payload = {
      title: f.title.value, description: f.description.value, type: f.type.value,
      city: f.city.value, state: f.state.value,
      bedrooms: +f.bedrooms.value, beds: +f.beds.value, bathrooms: +f.bathrooms.value, maxGuests: +f.maxGuests.value,
      amenities: [...selectedAmenities], photos: [...selectedPhotos],
      pricing: { nightly: +f.nightly.value, weekendNightly: +f.weekendNightly.value || 0, weeklyDiscountPct: +f.weeklyDiscountPct.value, monthlyDiscountPct: +f.monthlyDiscountPct.value, cleaningFee: +f.cleaningFee.value },
      minNights: +f.minNights.value, instantBook: f.instantBook.checked,
    };
    if (!payload.title || !payload.city || !payload.description) { toast('Title, city and description are required', 'err'); return; }
    if (!payload.photos.length) { toast('Add at least one photo of your place', 'err'); return; }
    try {
      if (editing) { await api.put(`/host/listings/${params.id}`, payload); toast('Listing updated', 'ok'); }
      else { const { listing } = await api.post('/host/listings', payload); auth.update({ ...auth.user, isHost: true }); toast('Your home is live! 🎉', 'ok'); navigate(`/listing/${listing.id}`); return; }
      navigate('/host');
    } catch (e) { toast(e.message, 'err'); }
  };

  const netHint = h('div', { class: 'demo-note', style: { marginTop: '10px' } });
  const updateNet = () => {
    const nightly = +f.nightly.value || 0;
    const weekend = +f.weekendNightly.value || nightly;
    mount(netHint, `💸 SmartStay keeps 20% of gross booking revenue — you keep 80%. That's about ${usd(Math.round(nightly * 0.8))}/night${weekend !== nightly ? ` (${usd(Math.round(weekend * 0.8))}/weekend night)` : ''} in your pocket, plus your cleaning fee.`);
  };
  f.nightly.addEventListener('input', updateNet);
  f.weekendNightly.addEventListener('input', updateNet);
  updateNet();

  mount(app, h('div', { class: 'container', style: { maxWidth: '820px', paddingTop: '30px', paddingBottom: '50px' } },
    h('div', { class: 'breadcrumb' }, h('a', { href: '#/host' }, 'Hosting'), ' / ', editing ? 'Edit listing' : 'New listing'),
    h('h1', { style: { fontSize: '30px' } }, editing ? 'Edit your listing' : 'List your home'),
    h('p', { class: 'muted' }, 'Set your own rates for weekends, weeks, and months — SmartStay handles the rest.'),

    h('div', { class: 'form', style: { marginTop: '20px' } },
      h('h3', {}, '① The basics'),
      fg('Listing title', f.title),
      fg('Description', f.description),
      h('div', { class: 'row', style: { gap: '14px' } }, h('div', { class: 'grow' }, fg('Home type', f.type)), h('div', { class: 'grow' }, fg('City', f.city)), h('div', { style: { width: '90px' } }, fg('State', f.state))),
      h('div', { class: 'row wrap', style: { gap: '14px' } },
        h('div', { class: 'grow' }, fg('Bedrooms', f.bedrooms)), h('div', { class: 'grow' }, fg('Beds', f.beds)),
        h('div', { class: 'grow' }, fg('Bathrooms', f.bathrooms)), h('div', { class: 'grow' }, fg('Max guests', f.maxGuests))),

      h('h3', { style: { marginTop: '16px' } }, '② Photos', h('span', { style: { color: 'var(--brand)', fontWeight: 700, fontSize: '15px' } }, ' *required'), h('span', { class: 'muted', style: { fontWeight: 400, fontSize: '15px' } }, ' — every home needs at least one photo')),
      photoGrid,

      h('h3', { style: { marginTop: '16px' } }, '③ Amenities'),
      amenityGrid,

      h('h3', { style: { marginTop: '16px' } }, '④ Pricing'),
      h('div', { class: 'row wrap', style: { gap: '14px' } },
        h('div', { class: 'grow' }, fg('Nightly rate ($)', f.nightly)),
        h('div', { class: 'grow' }, fg('Weekend rate ($)', f.weekendNightly, 'Fri & Sat nights'))),
      h('div', { class: 'row wrap', style: { gap: '14px' } },
        h('div', { class: 'grow' }, fg('Weekly discount (%)', f.weeklyDiscountPct, '7+ nights')),
        h('div', { class: 'grow' }, fg('Monthly discount (%)', f.monthlyDiscountPct, '28+ nights')),
        h('div', { class: 'grow' }, fg('Cleaning fee ($)', f.cleaningFee))),
      netHint,
      h('div', { class: 'row wrap', style: { gap: '14px', alignItems: 'end' } },
        h('div', { style: { width: '160px' } }, fg('Minimum nights', f.minNights)),
        h('label', { class: 'check', style: { marginBottom: '2px' } }, f.instantBook, '⚡ Enable Instant Book')),

      h('div', { class: 'row', style: { marginTop: '20px' } },
        h('button', { class: 'btn btn-primary btn-lg', onClick: save }, editing ? 'Save changes' : 'Publish listing'),
        h('button', { class: 'btn btn-ghost', onClick: () => navigate(editing ? '/host' : '/') }, 'Cancel')),
    )));
}
