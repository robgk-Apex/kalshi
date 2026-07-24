import { route, setNotFound, startRouter, resolve } from './router.js';
import { renderHeader, renderFooter } from './chrome.js';
import { auth, api } from './api.js';
import { loadFavorites } from './components.js';
import { h, mount, $, empty } from './ui.js';

import { homeView } from './views/home.js';
import { searchView } from './views/search.js';
import { listingView } from './views/listing.js';
import { loginView, signupView } from './views/auth.js';
import { tripsView, favoritesView, inboxView, profileView } from './views/account.js';
import { hostView, hostEditView } from './views/host.js';
import { aboutView } from './views/about.js';
import { openQuiz } from './views/quiz.js';

// ---- routes ----
route('/', homeView);
route('/search', searchView);
route('/listing/:id', listingView);
route('/login', loginView);
route('/signup', signupView);
route('/trips', tripsView);
route('/favorites', favoritesView);
route('/inbox', inboxView);
route('/profile', profileView);
route('/about', aboutView);
route('/quiz', () => { homeView(); openQuiz(); });
route('/host', hostView);
route('/host/new', hostEditView);
route('/host/edit/:id', hostEditView);

setNotFound(() => {
  mount($('#app'), h('div', { class: 'container' },
    empty('🧭', 'Page not found', 'The page you’re looking for doesn’t exist.', h('a', { class: 'btn btn-primary', href: '#/' }, 'Go home'))));
});

// Re-render header when auth changes (login/logout).
window.addEventListener('auth-change', renderHeader);

async function boot() {
  renderHeader();
  renderFooter();
  // Validate stored token; hydrate favorites.
  if (auth.isLoggedIn) {
    try {
      const { user } = await api.me();
      if (user) auth.update(user);
    } catch { /* token invalid -> cleared by api layer */ }
    await loadFavorites();
  }
  startRouter();
}

boot();
