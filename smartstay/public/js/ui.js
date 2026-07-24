// DOM + formatting helpers shared across views.

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'html') el.innerHTML = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else el.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    el.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return el;
}

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function clear(el) { if (!el) return el; while (el.firstChild) el.removeChild(el.firstChild); return el; }
// Null-safe: an async render may target a node that navigation has already replaced.
export function mount(el, ...nodes) { if (!el) return el; clear(el); el.append(...nodes.flat().filter(Boolean)); return el; }

export const usd = (n, cents = false) =>
  '$' + Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: cents ? 2 : 0, maximumFractionDigits: cents ? 2 : 0 });

export function fmtDate(str, opts = { month: 'short', day: 'numeric' }) {
  if (!str) return '';
  const [y, m, d] = str.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-US', { ...opts, timeZone: 'UTC' });
}

export function fmtRange(a, b) {
  if (!a || !b) return 'Add dates';
  const sameMonth = a.slice(0, 7) === b.slice(0, 7);
  return sameMonth
    ? `${fmtDate(a)} – ${fmtDate(b, { day: 'numeric' })}`
    : `${fmtDate(a)} – ${fmtDate(b)}`;
}

export function timeAgo(iso) {
  const secs = (Date.now() - new Date(iso)) / 1000;
  const units = [['year', 31536000], ['month', 2592000], ['week', 604800], ['day', 86400], ['hour', 3600], ['minute', 60]];
  for (const [name, s] of units) {
    const v = Math.floor(secs / s);
    if (v >= 1) return `${v} ${name}${v > 1 ? 's' : ''} ago`;
  }
  return 'just now';
}

export const todayISO = () => new Date().toISOString().slice(0, 10);
export function addDaysISO(iso, days) {
  const [y, m, d] = iso.split('-').map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  dt.setUTCDate(dt.getUTCDate() + days);
  return dt.toISOString().slice(0, 10);
}

export function stars(rating) {
  const full = Math.round(rating || 0);
  return '★★★★★'.slice(0, full) + '☆☆☆☆☆'.slice(0, 5 - full);
}

export const CATEGORY_ICONS = {
  All: '🏠', Villa: '🏖️', Cabin: '🌲', House: '🏡', Apartment: '🏙️',
  Condo: '🏢', Cottage: '🌾', Loft: '🎨', Townhouse: '🏘️',
  Pool: '🏊', 'Ocean view': '🌊', 'Mountain view': '⛰️', 'Ski-in/ski-out': '🎿',
  'Beach access': '🏝️', 'Hot tub': '♨️', Pets: '🐾',
};

export const AMENITY_ICONS = {
  Wifi: '📶', Kitchen: '🍳', Pool: '🏊', 'Hot tub': '♨️', 'Free parking': '🅿️',
  'Air conditioning': '❄️', Heating: '🔥', Washer: '🧺', Dryer: '🌀', 'EV charger': '🔌',
  Gym: '🏋️', 'Pets allowed': '🐾', Fireplace: '🪵', 'Beach access': '🏝️', 'Lake access': '🛶',
  'Mountain view': '⛰️', 'Ocean view': '🌊', Workspace: '💻', 'BBQ grill': '🍖', Patio: '🌿',
  'Ski-in/ski-out': '🎿',
};

// Image with graceful fallback to a soft gradient if the URL fails.
export function img(src, attrs = {}) {
  const el = h('img', { src, loading: 'lazy', ...attrs });
  el.addEventListener('error', () => {
    el.style.background = 'linear-gradient(135deg,#ffd7df,#ffeef1)';
    el.removeAttribute('src');
  }, { once: true });
  return el;
}

let toastTimer;
export function toast(msg, kind = '') {
  const root = document.getElementById('toast-root');
  const t = h('div', { class: `toast ${kind}` }, msg);
  root.append(t);
  setTimeout(() => { t.style.opacity = '0'; t.style.transition = 'opacity .3s'; }, 2600);
  setTimeout(() => t.remove(), 2950);
}

export function openModal(title, bodyNode, opts = {}) {
  const root = document.getElementById('modal-root');
  const close = () => { root.innerHTML = ''; document.body.style.overflow = ''; };
  const backdrop = h('div', { class: 'modal-backdrop', onClick: (e) => { if (e.target === backdrop) close(); } },
    h('div', { class: 'modal', style: opts.width ? { maxWidth: opts.width } : {} },
      h('div', { class: 'modal-head' },
        h('strong', {}, title),
        h('button', { class: 'iconbtn', onClick: close }, '✕')),
      h('div', { class: 'modal-body' }, bodyNode)));
  document.body.style.overflow = 'hidden';
  mount(root, backdrop);
  return close;
}

export function lightbox(photos, start = 0) {
  const root = document.getElementById('modal-root');
  let i = start;
  const render = () => {
    mount(root, h('div', { class: 'lightbox', onClick: (e) => { if (e.target.classList.contains('lightbox')) close(); } },
      h('button', { class: 'lb-close', onClick: close }, '✕'),
      photos.length > 1 && h('button', { class: 'lb-nav prev', onClick: () => { i = (i - 1 + photos.length) % photos.length; render(); } }, '‹'),
      img(photos[i]),
      photos.length > 1 && h('button', { class: 'lb-nav next', onClick: () => { i = (i + 1) % photos.length; render(); } }, '›')));
  };
  const close = () => { root.innerHTML = ''; document.body.style.overflow = ''; document.removeEventListener('keydown', key); };
  const key = (e) => { if (e.key === 'Escape') close(); if (e.key === 'ArrowRight') { i = (i + 1) % photos.length; render(); } if (e.key === 'ArrowLeft') { i = (i - 1 + photos.length) % photos.length; render(); } };
  document.addEventListener('keydown', key);
  document.body.style.overflow = 'hidden';
  render();
}

export function heartIcon() {
  return `<svg viewBox="0 0 32 32" fill="rgba(0,0,0,.5)" stroke="#fff" stroke-width="2"><path d="M16 28c7-4.7 12-10 12-16A6 6 0 0 0 16 8 6 6 0 0 0 4 12c0 6 5 11.3 12 16z"/></svg>`;
}

export function loading() {
  return h('div', {}, h('div', { class: 'spinner' }));
}

export function empty(icon, title, sub, action) {
  return h('div', { class: 'empty' },
    h('div', { class: 'big' }, icon),
    h('h3', {}, title),
    sub && h('p', { class: 'muted' }, sub),
    action);
}
