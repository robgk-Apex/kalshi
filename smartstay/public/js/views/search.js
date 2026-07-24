import { h, mount, $, openModal, toast, CATEGORY_ICONS } from '../ui.js';
import { api } from '../api.js';
import { navigate, parseHash } from '../router.js';
import { listingCard, cardGridSkeleton, searchWidget } from '../components.js';

let META = null;

const CATS = ['Villa', 'Cabin', 'House', 'Apartment', 'Condo', 'Cottage', 'Loft', 'Townhouse'];

function buildQuery(q) {
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) if (v != null && v !== '') usp.set(k, v);
  return usp.toString();
}

function filterModal(current) {
  const state = { ...current };
  const amenities = new Set((current.amenities || '').split(',').filter(Boolean));

  const priceMin = h('input', { class: 'input', type: 'number', placeholder: 'Min', value: current.minPrice || '' });
  const priceMax = h('input', { class: 'input', type: 'number', placeholder: 'Max', value: current.maxPrice || '' });
  const instant = h('input', { type: 'checkbox', checked: current.instantBook === 'true' });

  const amenityChecks = (META?.amenities || []).map((a) => {
    const cb = h('input', { type: 'checkbox', checked: amenities.has(a) });
    const wrap = h('label', { class: `check ${amenities.has(a) ? 'on' : ''}` }, cb, a);
    cb.addEventListener('change', () => { cb.checked ? amenities.add(a) : amenities.delete(a); wrap.classList.toggle('on', cb.checked); });
    return wrap;
  });

  const body = h('div', { class: 'form' },
    h('div', {}, h('label', { style: { fontWeight: 700 } }, 'Price range (per night)'),
      h('div', { class: 'row', style: { marginTop: '8px' } }, priceMin, h('span', {}, '–'), priceMax)),
    h('label', { class: 'check', style: { marginTop: '6px' } }, instant, '⚡ Instant Book only'),
    h('div', {}, h('label', { style: { fontWeight: 700 } }, 'Amenities'),
      h('div', { class: 'check-grid', style: { marginTop: '10px' } }, ...amenityChecks)),
    h('div', { class: 'spread', style: { marginTop: '10px' } },
      h('button', { class: 'btn btn-ghost', onClick: () => { navigate('/search'); document.getElementById('modal-root').innerHTML = ''; document.body.style.overflow = ''; } }, 'Clear all'),
      h('button', { class: 'btn btn-primary', onClick: () => {
        const q = { ...state };
        q.minPrice = priceMin.value; q.maxPrice = priceMax.value;
        q.instantBook = instant.checked ? 'true' : '';
        q.amenities = [...amenities].join(',');
        navigate('/search?' + buildQuery(q));
        document.getElementById('modal-root').innerHTML = ''; document.body.style.overflow = '';
      } }, 'Show homes')),
  );
  openModal('Filters', body);
}

export async function searchView() {
  const { query } = parseHash();
  const app = $('#app');
  if (!META) { try { META = await api.meta(); } catch { META = { amenities: [] }; } }

  const activeType = query.type || '';
  const catrow = h('div', { class: 'catrow' },
    h('button', { class: `cat ${!activeType ? 'active' : ''}`, onClick: () => { const q = { ...query }; delete q.type; navigate('/search?' + buildQuery(q)); } },
      h('span', { class: 'ico' }, '🏠'), 'All'),
    ...CATS.map((c) => h('button', { class: `cat ${activeType === c ? 'active' : ''}`, onClick: () => navigate('/search?' + buildQuery({ ...query, type: c })) },
      h('span', { class: 'ico' }, CATEGORY_ICONS[c] || '🏠'), c)),
  );

  const sortSel = h('select', { class: 'input', style: { width: 'auto' }, onChange: (e) => navigate('/search?' + buildQuery({ ...query, sort: e.target.value })) },
    ...[['rating', 'Top rated'], ['price_asc', 'Price: low to high'], ['price_desc', 'Price: high to low']]
      .map(([v, l]) => h('option', { value: v, selected: (query.sort || 'rating') === v }, l)));

  const activeFilterCount = ['minPrice', 'maxPrice', 'instantBook'].filter((k) => query[k]).length + (query.amenities ? query.amenities.split(',').filter(Boolean).length : 0);

  mount(app,
    h('div', { class: 'container', style: { paddingTop: '18px' } },
      searchWidget(query, (q) => navigate('/search?' + q.toString())),
      catrow,
      h('div', { class: 'spread wrap', style: { margin: '10px 0 20px' } },
        h('div', { id: 'result-count', class: 'muted' }, 'Searching…'),
        h('div', { class: 'row' },
          h('button', { class: 'pill', onClick: () => filterModal(query) }, '⚙️ Filters', activeFilterCount ? h('span', { class: 'chip', style: { padding: '1px 8px' } }, String(activeFilterCount)) : null),
          sortSel,
        )),
      h('div', { id: 'search-grid' }, cardGridSkeleton(8)),
    ));

  try {
    const usp = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) if (v) usp.set(k, v);
    const { listings, count } = await api.listings('?' + usp.toString());
    const label = [
      count === 1 ? '1 home' : `${count} homes`,
      query.city ? `in ${query.city}` : 'across the USA',
      query.checkIn && query.checkOut ? '· dates available' : '',
    ].join(' ');
    mount($('#result-count'), h('strong', {}, label));
    if (!listings.length) {
      mount($('#search-grid'), h('div', { class: 'empty' },
        h('div', { class: 'big' }, '🔍'),
        h('h3', {}, 'No homes match your search'),
        h('p', { class: 'muted' }, 'Try widening your dates, price, or filters.'),
        h('button', { class: 'btn btn-outline', onClick: () => navigate('/search') }, 'Clear filters')));
    } else {
      mount($('#search-grid'), h('div', { class: 'grid' }, ...listings.map(listingCard)));
    }
  } catch (err) {
    mount($('#search-grid'), h('p', { class: 'muted' }, 'Could not load results: ' + err.message));
  }
}
