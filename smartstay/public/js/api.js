// Thin fetch wrapper with token handling + a tiny auth store.

const TOKEN_KEY = 'smartstay_token';
const USER_KEY = 'smartstay_user';

export const auth = {
  token: localStorage.getItem(TOKEN_KEY) || null,
  user: JSON.parse(localStorage.getItem(USER_KEY) || 'null'),
  set(token, user) {
    this.token = token; this.user = user;
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
    window.dispatchEvent(new Event('auth-change'));
  },
  update(user) {
    this.user = user;
    localStorage.setItem(USER_KEY, JSON.stringify(user));
    window.dispatchEvent(new Event('auth-change'));
  },
  clear() {
    this.token = null; this.user = null;
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    window.dispatchEvent(new Event('auth-change'));
  },
  get isLoggedIn() { return !!this.token; },
};

async function req(method, path, body) {
  const headers = { 'Content-Type': 'application/json' };
  if (auth.token) headers.Authorization = `Bearer ${auth.token}`;
  const res = await fetch(`/api${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch { /* no body */ }
  if (!res.ok) {
    if (res.status === 401) auth.clear();
    throw new Error(data?.error || `Request failed (${res.status})`);
  }
  return data;
}

export const api = {
  get: (p) => req('GET', p),
  post: (p, b) => req('POST', p, b),
  put: (p, b) => req('PUT', p, b),
  patch: (p, b) => req('PATCH', p, b),
  del: (p) => req('DELETE', p),

  // convenience wrappers
  signup: (b) => req('POST', '/auth/signup', b),
  login: (b) => req('POST', '/auth/login', b),
  me: () => req('GET', '/auth/me'),
  listings: (query = '') => req('GET', `/listings${query}`),
  listing: (id) => req('GET', `/listings/${id}`),
  quote: (id, b) => req('POST', `/listings/${id}/quote`, b),
  book: (b) => req('POST', '/bookings', b),
  myBookings: () => req('GET', '/bookings'),
  hostBookings: () => req('GET', '/host/bookings'),
  hostListings: () => req('GET', '/host/listings'),
  favorites: () => req('GET', '/favorites'),
  toggleFav: (id) => req('POST', `/favorites/${id}`),
  meta: () => req('GET', '/meta'),
};
