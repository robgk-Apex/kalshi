// Header + footer that react to auth state.
import { h, mount, $, img } from './ui.js';
import { auth } from './api.js';
import { navigate } from './router.js';

function userMenu() {
  const wrap = h('div', { style: { position: 'relative' } });
  let open = false;
  const pop = h('div', { class: 'menu-pop hide' });
  const rebuildPop = () => {
    const u = auth.user;
    mount(pop,
      u ? h('div', { style: { padding: '8px 12px 4px' } }, h('strong', {}, u.name), h('div', { class: 'muted', style: { fontSize: '13px' } }, u.email)) : null,
      u ? h('div', { class: 'menu-sep' }) : null,
      u ? h('a', { href: '#/trips' }, '🧳 My trips') : null,
      u ? h('a', { href: '#/favorites' }, '❤️ Wishlists') : null,
      u ? h('a', { href: '#/inbox' }, '✉️ Messages') : null,
      u ? h('a', { href: '#/host' }, '🏡 Hosting') : null,
      u ? h('a', { href: '#/profile' }, '⚙️ Account') : null,
      u ? h('div', { class: 'menu-sep' }) : null,
      !u ? h('a', { href: '#/signup' }, '🧳 Sign up to book') : null,
      !u ? h('a', { href: '#/signup?role=host' }, '🏡 Sign up as a host') : null,
      !u ? h('a', { href: '#/login' }, '➡️ Log in') : null,
      !u ? h('div', { class: 'menu-sep' }) : null,
      h('a', { href: u ? '#/host/new' : '#/signup?role=host' }, '➕ List your property'),
      u ? h('button', { onClick: () => { auth.clear(); navigate('/'); toggle(false); } }, '🚪 Log out') : null,
    );
  };
  const toggle = (v) => { open = v ?? !open; pop.classList.toggle('hide', !open); };
  const btn = h('button', { class: 'usermenu', onClick: (e) => { e.stopPropagation(); rebuildPop(); toggle(); } },
    h('span', { html: '<svg width="16" height="16" viewBox="0 0 16 16"><path d="M2 4h12M2 8h12M2 12h12" stroke="currentColor" stroke-width="1.6" fill="none"/></svg>' }));
  const avatar = auth.user
    ? img(auth.user.avatar, { class: 'avatar', style: { width: '30px', height: '30px' } })
    : h('span', { class: 'avatar', style: { width: '30px', height: '30px', display: 'grid', placeItems: 'center', background: '#717171', color: '#fff' }, html: '<svg width="18" height="18" viewBox="0 0 24 24" fill="#fff"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-6 8-6s8 2 8 6"/></svg>' });
  btn.append(avatar);
  wrap.append(btn, pop);
  document.addEventListener('click', () => toggle(false));
  return wrap;
}

export function renderHeader() {
  const header = $('#app-header');
  mount(header, h('div', { class: 'container nav' },
    h('a', { class: 'logo', href: '#/' }, h('span', { class: 'mark' }, '🏡'), h('b', {}, 'SmartStay'), h('span', { style: { color: 'var(--ink)', fontWeight: 700 } }, 'USA')),
    h('nav', { class: 'nav-links' },
      h('a', { class: 'nav-link', href: '#/search' }, 'Explore'),
      h('a', { class: 'nav-link', href: '#/quiz' }, '✨ Trip quiz'),
      h('a', { class: 'nav-link', href: auth.isLoggedIn ? '#/host' : '#/signup?role=host', style: { color: 'var(--brand)' } }, '🏡 List your property'),
    ),
    userMenu(),
  ));
}

export function renderFooter() {
  const footer = $('#app-footer');
  const col = (title, links) => h('div', {}, h('h4', {}, title), ...links.map(([t, href]) => h('a', { href: href || '#/search' }, t)));
  mount(footer,
    h('div', { class: 'container' },
      h('div', { class: 'footcols' },
        col('Explore', [['Beach houses', '#/search?amenities=Beach access'], ['Cabins', '#/search?type=Cabin'], ['Luxury villas', '#/search?type=Villa'], ['Pet-friendly', '#/search?amenities=Pets allowed']]),
        col('Hosting', [['List your home', '#/host/new'], ['Host dashboard', '#/host'], ['Responsible hosting', '#/host']]),
        col('Support', [['Help center'], ['Cancellation options'], ['Safety information']]),
        col('Company', [['About SmartStay', '#/about'], ['Newsroom'], ['Careers']]),
      ),
      h('div', { class: 'footbar spread wrap' },
        h('span', {}, `© ${new Date().getFullYear()} SmartStay USA · Built as a demo marketplace`),
        h('span', {}, '🇺🇸 United States · English (US) · $ USD'),
      ),
    ));
}
