/* Foreclosure Finder front end: list + filters, map, and property detail with comps. */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const money = v => v == null ? "—" : "$" + Math.round(v).toLocaleString();
const ppsf = v => v < 1 ? "$" + v.toFixed(2) : money(v);
const num = v => v == null ? "—" : Number(v).toLocaleString();
const api = (path, params) => {
  const u = new URL(path, location.origin);
  if (params) for (const [k, v] of Object.entries(params))
    (Array.isArray(v) ? v : [v]).forEach(x => x !== "" && x != null && u.searchParams.append(k, x));
  return fetch(u).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); });
};

let facets = null, listMap = null, listLayer = null, view = "grid", page = 1, lastPins = [];
const TEXT_FILTERS = ["q", "state", "city", "zip", "min_price", "max_price", "min_sqft", "max_sqft", "source", "property_type", "sort"];

/* ---------- filter state <-> URL ---------- */
function readFilters() {
  const f = {};
  TEXT_FILTERS.forEach(id => { const v = $("#" + id).value.trim().replace(/[$,]/g, ""); if (v) f[id] = v; });
  $$(".chips").forEach(c => { const on = $("button.on", c); if (on && on.dataset.v) f[c.dataset.name] = on.dataset.v; });
  const am = $$("#amenities input:checked").map(i => i.value);
  if (am.length) f.amenities = am;
  return f;
}
function writeUrl(f) {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(f)) (Array.isArray(v) ? v : [v]).forEach(x => u.append(k, x));
  if (page > 1) u.set("page", page);
  if (view === "map") u.set("view", "map");
  history.replaceState(null, "", "/" + (u.toString() ? "?" + u : ""));
}
function applyUrl() {
  const u = new URLSearchParams(location.search);
  TEXT_FILTERS.forEach(id => { if (id !== "city") $("#" + id).value = u.get(id) || (id === "sort" ? "price_asc" : ""); });
  fillCities(); $("#city").value = u.get("city") || "";
  $$(".chips").forEach(c => $$("button", c).forEach(b => b.classList.toggle("on", (b.dataset.v || "") === (u.get(c.dataset.name) || ""))));
  const am = u.getAll("amenities");
  $$("#amenities input").forEach(i => i.checked = am.includes(i.value));
  page = +u.get("page") || 1;
  setView(u.get("view") === "map" ? "map" : "grid", false);
}

/* ---------- filter UI ---------- */
function buildChips(id, values) {
  $("#" + id).innerHTML = [["", "Any"], ...values.map(v => [v, v + "+"])]
    .map(([v, l]) => `<button type="button" data-v="${v}" class="${v ? "" : "on"}">${l}</button>`).join("");
}
function fillCities() {
  const st = $("#state").value;
  const cities = (facets?.cities || []).filter(c => !st || c.state === st)
    .sort((a, b) => a.city.localeCompare(b.city));
  $("#city").innerHTML = `<option value="">All cities</option>` +
    cities.map(c => `<option value="${esc(c.city)}">${esc(c.city)}${st ? "" : ", " + c.state} (${c.n})</option>`).join("");
}
async function loadFacets() {
  facets = await api("/api/facets");
  $("#state").innerHTML = `<option value="">All states</option>` +
    facets.states.map(s => `<option value="${s.state}">${s.state} (${s.n})</option>`).join("");
  $("#source").innerHTML = `<option value="">All sources</option>` +
    facets.sources.map(s => `<option value="${s.source}">${esc(s.name)} (${s.n})</option>`).join("");
  $("#property_type").innerHTML = `<option value="">All types</option>` +
    facets.types.map(t => `<option value="${esc(t.property_type)}">${esc(t.property_type)} (${t.n})</option>`).join("");
  $("#amenities").innerHTML = facets.amenities.length ? facets.amenities.map(a =>
    `<label><input type="checkbox" value="${esc(a.name)}"> ${esc(a.name)} <span class="n">${a.n}</span></label>`).join("")
    : `<p class="note">No amenity data yet.</p>`;
  buildChips("beds", [1, 2, 3, 4, 5]);
  buildChips("baths", [1, 2, 3]);
}

/* ---------- results ---------- */
function card(p) {
  const st = p.status && !/^(avail|active|listed|for sale)/i.test(p.status) ? `<span class="badge warn">${esc(p.status)}</span>` : "";
  const img = p.cover_photo ? `<img src="${esc(p.cover_photo)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.outerHTML='<div class=noimg>No photo</div>'">` : `<div class="noimg">No photo</div>`;
  const srcName = facets?.sources.find(s => s.source === p.source)?.name || p.source;
  return `<a class="card" href="/property/${p.id}" data-link>
    <div class="ph">${img}${st}${p.photo_count ? `<span class="pc">${p.photo_count} photos</span>` : ""}</div>
    <div class="body">
      <div class="price">${money(p.price)}</div>
      <div class="facts">${num(p.beds)} bd · ${num(p.baths)} ba · ${num(p.sqft)} sq ft</div>
      <div class="addr">${esc(p.address)}, ${esc(p.city || "")}, ${esc(p.state || "")} ${esc(p.zip || "")}</div>
      <div class="src">${esc(srcName)}${p.price && p.sqft ? ` · ${ppsf(p.price / p.sqft)}/sq ft` : ""}</div>
    </div></a>`;
}
let reqId = 0;
async function search() {
  const f = readFilters(); writeUrl(f);
  const my = ++reqId;
  $("#count").textContent = "Searching…";
  const d = await api("/api/properties", {...f, page, per_page: 24});
  if (my !== reqId) return;
  $("#count").textContent = `${d.total.toLocaleString()} ${d.total === 1 ? "home" : "homes"}`;
  $("#grid").innerHTML = d.results.length ? d.results.map(card).join("")
    : `<div class="empty"><b>No homes match these filters.</b><br>Try widening the price range or removing an amenity.${facets?.price?.n ? "" : "<br><br>The database is empty. Run a scrape (see README) or load demo data with <code>python -m app.seed_demo</code>."}</div>`;
  const pages = Math.ceil(d.total / d.per_page);
  $("#pager").innerHTML = pages > 1 ? pagerHtml(pages) : "";
  lastPins = d.pins;
  if (view === "map") drawPins();
}
function pagerHtml(pages) {
  const set = new Set([1, pages, page - 1, page, page + 1].filter(x => x >= 1 && x <= pages));
  let out = page > 1 ? `<button data-p="${page - 1}">‹</button>` : "", prev = 0;
  [...set].sort((a, b) => a - b).forEach(p => { if (p - prev > 1) out += `<span>…</span>`; out += `<button data-p="${p}" class="${p === page ? "on" : ""}">${p}</button>`; prev = p; });
  return out + (page < pages ? `<button data-p="${page + 1}">›</button>` : "");
}
const tiles = () => L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {maxZoom: 19, attribution: "© OpenStreetMap"});
const pinIcon = (label, cls = "") => L.divIcon({className: "", html: `<span class="pin ${cls}">${label}</span>`, iconSize: [0, 0]});
const shortMoney = v => v >= 1e6 ? "$" + (v / 1e6).toFixed(1) + "M" : "$" + Math.round(v / 1e3) + "K";
function drawPins() {
  if (!window.L) return;
  if (!listMap) { listMap = L.map("map").setView([37.5, -95], 4); tiles().addTo(listMap); listLayer = L.layerGroup().addTo(listMap); }
  listLayer.clearLayers();
  lastPins.forEach(p => L.marker([p.lat, p.lng], {icon: pinIcon(shortMoney(p.price))})
    .on("click", () => navigate("/property/" + p.id)).addTo(listLayer));
  setTimeout(() => { listMap.invalidateSize(); if (lastPins.length) listMap.fitBounds(lastPins.map(p => [p.lat, p.lng]), {padding: [30, 30], maxZoom: 13}); }, 50);
}
function setView(v, run = true) {
  view = v;
  $$(".seg button").forEach(b => b.classList.toggle("on", b.dataset.view === v));
  $("#map").hidden = v !== "map";
  if (run) { writeUrl(readFilters()); if (v === "map") drawPins(); }
}

/* ---------- detail ---------- */
async function showDetail(id) {
  const el = $("#detailView");
  el.innerHTML = `<div class="skeleton" style="height:420px"></div>`;
  let p;
  try { p = await api(`/api/properties/${id}`); }
  catch { el.innerHTML = `<a class="back" href="/" data-link>← Back to results</a><div class="empty">Property not found.</div>`; return; }
  document.title = `${p.address} · Foreclosure Finder`;
  const facts = [
    ["Bedrooms", num(p.beds)], ["Bathrooms", num(p.baths)], ["Living area", p.sqft ? num(p.sqft) + " sq ft" : "—"],
    ["Lot size", p.lot_sqft ? num(p.lot_sqft) + " sq ft" : "—"], ["Year built", p.year_built || "—"],
    ["Price / sq ft", p.price_per_sqft ? money(p.price_per_sqft) : "—"], ["Type", p.property_type || "—"],
    ["Status", p.status || "—"], ["Source", p.source_name], ["Listing ID", p.source_id],
  ];
  el.innerHTML = `
    <a class="back" href="/${sessionStorage.ffBack || ""}" data-link>← Back to results</a>
    <div class="d-head">
      <div><h1>${esc(p.address)}</h1><div class="sub">${esc(p.city || "")}, ${esc(p.state || "")} ${esc(p.zip || "")}</div></div>
      <div class="d-price">${money(p.price)}<small>${num(p.beds)} bd · ${num(p.baths)} ba · ${num(p.sqft)} sq ft</small></div>
    </div>
    <section class="gallery" id="gallery"></section>
    <div class="cols">
      <div>
        <section class="panel"><h2>Property details</h2>
          <div class="kv">${facts.map(([k, v]) => `<div><span>${k}</span><b>${esc(v)}</b></div>`).join("")}</div></section>
        ${p.amenities.length ? `<section class="panel"><h2>Amenities &amp; features</h2><div class="tags">${p.amenities.map(a => `<span class="tag">${esc(a)}</span>`).join("")}</div></section>` : ""}
        ${p.description ? `<section class="panel"><h2>Description</h2><p class="desc">${esc(p.description)}</p></section>` : ""}
        <section class="panel" id="comps"><h2>Comparable sales</h2><div class="skeleton" style="height:160px"></div></section>
      </div>
      <aside>
        <section class="panel"><h2>Location</h2><div id="dmap" class="dmap"></div></section>
        <section class="panel"><h2>On the source site</h2>
          ${p.listing_url ? `<p class="note">Bids, offers and disclosures are handled on the original listing.</p><a class="btn" href="${esc(p.listing_url)}" target="_blank" rel="noopener">View on ${esc(p.source_name)}</a>` : `<p class="note">${p.source === "demo" ? "This is a demo listing, not a real property." : "No source link was captured."}</p>`}
        </section>
      </aside>
    </div>`;
  renderGallery(p.photos);
  let dmap = null;
  if (window.L && p.lat && p.lng) {
    dmap = L.map("dmap").setView([p.lat, p.lng], 14); tiles().addTo(dmap);
    L.marker([p.lat, p.lng], {icon: pinIcon("This home", "subject")}).addTo(dmap);
  } else $("#dmap").outerHTML = `<p class="note">${p.lat ? "Map couldn't load (no connection to the map library)." : "No coordinates for this listing."}</p>`;
  loadComps(p, dmap);
}

let gPhotos = [], gIdx = 0;
function renderGallery(all) {
  const g = $("#gallery");
  if (!all.length) { g.innerHTML = `<div class="g-main"><div class="noimg" style="display:grid;place-items:center;height:100%;color:var(--muted)">No photos available</div></div>`; return; }
  const kindOf = p => (p.kind === "exterior" || p.kind === "interior") ? p.kind : "unknown";
  const counts = {all: all.length};
  all.forEach(p => counts[kindOf(p)] = (counts[kindOf(p)] || 0) + 1);
  const LABEL = {all: "All", exterior: "Exterior", interior: "Interior", unknown: "Other photos"};
  const draw = (tab) => {
    gPhotos = tab === "all" ? all : all.filter(p => kindOf(p) === tab); gIdx = 0;
    g.innerHTML = `
      <div class="g-tabs">${["all", "exterior", "interior", "unknown"].filter(t => t === "all" || counts[t]).map(t =>
        `<button type="button" data-tab="${t}" class="${t === tab ? "on" : ""}">${LABEL[t]} (${counts[t]})</button>`).join("")}</div>
      <div class="g-main"><img alt="" referrerpolicy="no-referrer"><span class="kind"></span></div>
      <div class="thumbs">${gPhotos.map((p, i) => `<img src="${esc(p.url)}" data-i="${i}" alt="${esc(p.caption || p.kind)}" loading="lazy" referrerpolicy="no-referrer">`).join("")}</div>`;
    show(0);
    $$(".g-tabs button", g).forEach(b => b.onclick = () => draw(b.dataset.tab));
    $$(".thumbs img", g).forEach(t => t.onclick = () => show(+t.dataset.i));
    $(".g-main", g).onclick = () => openLb();
  };
  const show = i => {
    gIdx = (i + gPhotos.length) % gPhotos.length; const ph = gPhotos[gIdx];
    $(".g-main img", g).src = ph.url;
    $(".g-main .kind", g).textContent = ph.caption || (ph.kind === "unknown" ? `Photo ${gIdx + 1}` : ph.kind);
    $$(".thumbs img", g).forEach((t, j) => t.classList.toggle("on", j === gIdx));
  };
  g.show = show;
  draw("all");
}
function openLb() {
  const lb = $("#lightbox"); lb.hidden = false;
  const upd = () => { const p = gPhotos[gIdx]; $("img", lb).src = p.url; $(".lb-cap", lb).textContent = `${gIdx + 1} / ${gPhotos.length}` + (p.caption ? ` · ${p.caption}` : ""); };
  const step = d => { gIdx = (gIdx + d + gPhotos.length) % gPhotos.length; upd(); $("#gallery").show?.(gIdx); };
  $(".lb-prev", lb).onclick = () => step(-1); $(".lb-next", lb).onclick = () => step(1);
  $(".lb-close", lb).onclick = () => lb.hidden = true;
  lb.onclick = e => { if (e.target === lb) lb.hidden = true; };
  document.onkeydown = e => { if (lb.hidden) return; if (e.key === "Escape") lb.hidden = true; if (e.key === "ArrowLeft") step(-1); if (e.key === "ArrowRight") step(1); };
  upd();
}

async function loadComps(p, dmap) {
  const box = $("#comps");
  let d;
  try { d = await api(`/api/properties/${p.id}/comps`); }
  catch { box.innerHTML = `<h2>Comparable sales</h2><p class="note">Couldn't load comps.</p>`; return; }
  const s = d.summary, real = d.provider === "rentcast";
  const disc = s.discount_pct;
  const stats = [
    real && s.estimated_value ? ["Estimated market value", money(s.estimated_value), s.value_low ? `${money(s.value_low)} – ${money(s.value_high)}` : ""] : null,
    ["Median comp price", money(s.median_price)],
    ["Median comp $/sq ft", s.median_ppsf ? money(s.median_ppsf) : "—"],
    s.implied_value ? ["Value at median $/sq ft", money(s.implied_value)] : null,
    disc != null ? ["List price vs. value", (disc >= 0 ? disc + "% below" : -disc + "% above"), "", disc >= 0 ? "good" : "bad"] : null,
  ].filter(Boolean);
  box.innerHTML = `<h2>${real ? "Comparable sales" : "Nearby comparable listings"}</h2>
    <p class="note ${real ? "" : "warn"}">${esc(d.error || "")} ${real ? `${s.count} comps from RentCast: recent sales and listings near this home.` : `Other foreclosure listings within ${d.radius_mi || 5} miles, not closed sales.${d.error ? "" : " Set <code>RENTCAST_API_KEY</code> to pull real sold comps."}`}</p>
    <div class="stats">${stats.map(([k, v, sub, cls]) => `<div class="stat"><span>${k}</span><b class="${cls || ""}">${v}</b>${sub ? `<span>${sub}</span>` : ""}</div>`).join("")}</div>
    ${d.comps.length ? `<div class="tbl-wrap"><table><thead><tr><th>Address</th><th class="num">Price</th><th class="num">Bd</th><th class="num">Ba</th><th class="num">Sq ft</th><th class="num">$/sq ft</th><th class="num">Dist.</th><th>${real ? "Date" : "Status"}</th></tr></thead><tbody>
      <tr class="subj"><td>This home</td><td class="num">${money(p.price)}</td><td class="num">${num(p.beds)}</td><td class="num">${num(p.baths)}</td><td class="num">${num(p.sqft)}</td><td class="num">${p.price_per_sqft ? money(p.price_per_sqft) : "—"}</td><td class="num">—</td><td></td></tr>
      ${d.comps.map(c => `<tr><td>${c.id ? `<a href="/property/${c.id}" data-link>${esc(c.address)}</a>` : esc(c.address)}</td><td class="num">${money(c.price)}</td><td class="num">${num(c.beds)}</td><td class="num">${num(c.baths)}</td><td class="num">${num(c.sqft)}</td><td class="num">${c.price && c.sqft ? money(c.price / c.sqft) : "—"}</td><td class="num">${c.distance_mi != null ? c.distance_mi + " mi" : "—"}</td><td>${esc(real ? (c.date || "").slice(0, 10) : c.status || "")}</td></tr>`).join("")}
    </tbody></table></div>` : `<p class="note">No comparable properties found nearby.</p>`}`;
  if (dmap) {
    const pts = [[p.lat, p.lng]];
    d.comps.filter(c => c.lat && c.lng).forEach(c => { pts.push([c.lat, c.lng]); L.marker([c.lat, c.lng], {icon: pinIcon(shortMoney(c.price), "comp")}).bindTooltip(c.address).addTo(dmap); });
    if (pts.length > 1) dmap.fitBounds(pts, {padding: [25, 25], maxZoom: 15});
  }
}

/* ---------- routing ---------- */
function navigate(path) { history.pushState(null, "", path); route(); }
function route() {
  const m = location.pathname.match(/^\/property\/(\d+)/);
  $("#listView").hidden = !!m; $("#detailView").hidden = !m;
  $("#filterToggle").hidden = !!m;
  window.scrollTo(0, 0);
  if (m) showDetail(m[1]);
  else { document.title = "Foreclosure Finder"; applyUrl(); search(); }
}
document.addEventListener("click", e => {
  const a = e.target.closest("a[data-link]");
  if (!a || e.metaKey || e.ctrlKey || e.shiftKey) return;
  e.preventDefault();
  if (!$("#listView").hidden) sessionStorage.ffBack = location.search;
  navigate(a.getAttribute("href"));
});
window.addEventListener("popstate", route);

/* ---------- wire up ---------- */
let t;
const debounced = () => { clearTimeout(t); t = setTimeout(() => { page = 1; search(); }, 300); };
(async () => {
  await loadFacets();
  ["q", "zip", "min_price", "max_price", "min_sqft", "max_sqft"].forEach(id => $("#" + id).addEventListener("input", debounced));
  ["city", "source", "property_type", "sort"].forEach(id => $("#" + id).addEventListener("change", () => { page = 1; search(); }));
  $("#state").addEventListener("change", () => { fillCities(); page = 1; search(); });
  $("#amenities").addEventListener("change", () => { page = 1; search(); });
  $$(".chips").forEach(c => c.addEventListener("click", e => { const b = e.target.closest("button"); if (!b) return; $$("button", c).forEach(x => x.classList.toggle("on", x === b)); page = 1; search(); }));
  $("#pager").addEventListener("click", e => { const b = e.target.closest("button[data-p]"); if (!b) return; page = +b.dataset.p; search(); window.scrollTo(0, 0); });
  $$(".seg button").forEach(b => b.onclick = () => setView(b.dataset.view));
  $("#searchForm").onsubmit = e => { e.preventDefault(); if ($("#listView").hidden) navigate("/?q=" + encodeURIComponent($("#q").value)); else { page = 1; search(); } };
  $("#reset").onclick = () => { history.replaceState(null, "", "/"); applyUrl(); search(); };
  $("#filterToggle").onclick = () => $("#filters").classList.toggle("open");
  route();
})();
