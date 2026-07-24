// Minimal hash router with :params support.

const routes = [];
let notFound = () => {};

export function route(pattern, handler) {
  // '/listing/:id' -> regex
  const keys = [];
  const rx = new RegExp('^' + pattern.replace(/:[^/]+/g, (m) => { keys.push(m.slice(1)); return '([^/]+)'; }) + '$');
  routes.push({ rx, keys, handler });
}

export function setNotFound(fn) { notFound = fn; }

export function parseHash() {
  const raw = location.hash.slice(1) || '/';
  const [path, queryStr] = raw.split('?');
  const query = Object.fromEntries(new URLSearchParams(queryStr || ''));
  return { path, query };
}

export function navigate(path) {
  location.hash = path;
}

export function resolve() {
  const { path, query } = parseHash();
  for (const r of routes) {
    const m = path.match(r.rx);
    if (m) {
      const params = {};
      r.keys.forEach((k, i) => (params[k] = decodeURIComponent(m[i + 1])));
      window.scrollTo({ top: 0 });
      return r.handler({ params, query, path });
    }
  }
  window.scrollTo({ top: 0 });
  notFound();
}

export function startRouter() {
  window.addEventListener('hashchange', resolve);
  resolve();
}

export function linkTo(path) {
  return '#' + path;
}
