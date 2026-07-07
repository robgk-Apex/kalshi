"""Live visual dashboard for the short-term up/down crypto markets.

A zero-dependency (stdlib only) web dashboard that shows the directional crypto
markets the bot watches, auto-refreshing in the browser. Each row shows the
YES/NO book, last trade, volume, a live countdown to settlement, and the bot's
detected edge/signal (computed with the SAME scanner logic the bot trades on).

    # LIVE — real Kalshi data (needs your API keys + network to Kalshi)
    python scripts/dashboard.py --config config/config.yaml

    # DEMO — synthetic data, no network or keys (for previewing the screen)
    python scripts/dashboard.py --demo

Then open http://localhost:8787 in your browser.

Note on environments: if you run this where Kalshi is unreachable (e.g. a
locked-down CI/cloud box), use --demo. "Live data matching the current Kalshi
market" requires a network that can reach api.elections.kalshi.com.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.scanner import MarketScanner

COINS = [
    ("BTC", "KXBTCD", 68000.0),
    ("ETH", "KXETHD", 3500.0),
    ("SOL", "KXSOLD", 180.0),
    ("XRP", "KXXRPD", 0.62),
    ("DOGE", "KXDOGED", 0.16),
]

SCAN_CONFIG = {
    "strategy": {
        "mode": "crypto_short", "min_edge": 0.05, "scan_interval": 5,
        "min_volume": 100, "max_hours_to_expiry": 4, "max_entry_price": 0.90,
    },
    "risk": {"bankroll": 1000, "max_bet_pct": 0.05, "max_contracts": 20,
             "max_positions": 10, "stop_loss_pct": 0.20, "daily_loss_limit": 100},
}


def _gate_free_scanner(client):
    """A scanner with the network-bound analyzer gates disabled, used only to
    compute price-based edge for display."""
    s = MarketScanner(client, SCAN_CONFIG)
    s.crypto_analyzer = None
    s.weather_analyzer = None
    s.probability_checker = None
    return s


# ──────────────────────────────────────────────────────────────────────────
# Data providers
# ──────────────────────────────────────────────────────────────────────────
class LiveProvider:
    """Pulls real directional-crypto markets from Kalshi and flags the bot's
    signals. Results are cached for `min_interval` seconds so rapid browser
    polling doesn't hammer the API."""

    def __init__(self, config_path, min_interval=4.0):
        import yaml
        from src.api_client import KalshiClient

        with open(config_path) as f:
            config = yaml.safe_load(f)
        api = config["api"]
        self.client = KalshiClient(api["base_url"], api["key_id"],
                                   api["private_key_path"])
        self.scanner = _gate_free_scanner(self.client)
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._cache = None
        self._cache_at = 0.0

    def snapshot(self):
        with self._lock:
            if self._cache and (time.time() - self._cache_at) < self.min_interval:
                return self._cache
            snap = self._fetch()
            self._cache = snap
            self._cache_at = time.time()
            return snap

    def _fetch(self):
        rows, error, balance = [], None, None
        try:
            bal = self.client.get_balance()
            balance = bal.get("balance", 0) / 100
        except Exception as e:
            error = f"balance: {e}"

        seen = set()
        for series in self.scanner.crypto_series:
            try:
                resp = self.client.get_events(series_ticker=series, limit=200,
                                              with_nested_markets=True)
            except Exception as e:
                error = str(e)
                continue
            for event in resp.get("events", []):
                for m in event.get("markets", []):
                    t = m.get("ticker", "")
                    if not t or t in seen:
                        continue
                    seen.add(t)
                    rows.append(self._row(m))
        rows = [r for r in rows if r]
        rows.sort(key=lambda r: (r["hours_left"], -abs(r["edge"])))
        return {"mode": "LIVE", "error": error, "balance": balance,
                "updated": datetime.now(timezone.utc).isoformat(), "rows": rows}

    def _row(self, m):
        sc = self.scanner
        ticker = m.get("ticker", "")
        yb = sc._to_float(m.get("yes_bid_dollars", 0) or m.get("yes_bid", 0))
        ya = sc._to_float(m.get("yes_ask_dollars", 0) or m.get("yes_ask", 0))
        nb = sc._to_float(m.get("no_bid_dollars", 0) or m.get("no_bid", 0))
        na = sc._to_float(m.get("no_ask_dollars", 0) or m.get("no_ask", 0))
        last = sc._to_float(m.get("last_price_dollars", 0) or m.get("last_price", 0))
        vol = sc._to_float(m.get("volume_fp", 0) or m.get("volume", 0))
        ct = (m.get("expected_expiration_time") or m.get("close_time")
              or m.get("expiration_time", ""))
        hours = sc._hours_until(ct) if ct else 9999
        try:
            opp = sc._evaluate_market(m)
        except Exception:
            opp = None
        return {
            "ticker": ticker, "coin": _coin_of(ticker),
            "title": m.get("title", ticker),
            "yes_bid": yb, "yes_ask": ya, "no_bid": nb, "no_ask": na,
            "last": last, "volume": vol, "hours_left": hours, "close_time": ct,
            "edge": round(opp.edge, 4) if opp else 0.0,
            "side": opp.side if opp else "",
        }


class DemoProvider:
    """Generates synthetic-but-plausible up/down crypto markets whose prices
    drift over time, so the screen looks alive without any network."""

    def __init__(self):
        self.rng = random.Random(1)
        self.client = _DemoClient(self.rng)
        self.scanner = _gate_free_scanner(self.client)
        self._t0 = time.time()

    def snapshot(self):
        self.client.regenerate(time.time() - self._t0)
        rows = []
        for series in self.scanner.crypto_series:
            resp = self.client.get_events(series_ticker=series)
            for event in resp.get("events", []):
                for m in event.get("markets", []):
                    rows.append(LiveProvider._row(self, m))
        rows = [r for r in rows if r]
        rows.sort(key=lambda r: (r["hours_left"], -abs(r["edge"])))
        return {"mode": "DEMO", "error": None, "balance": 1000.0,
                "updated": datetime.now(timezone.utc).isoformat(), "rows": rows}


class _DemoClient:
    def __init__(self, rng):
        self.rng = rng
        self._markets = {}

    def get_balance(self):
        return {"balance": 100000}

    def regenerate(self, elapsed):
        self._markets = {}
        for coin, series, spot in COINS:
            ms = []
            for i in range(3):
                # A market implied prob that oscillates over time per coin+bucket.
                phase = hash((coin, i)) % 100 / 100.0
                m = 0.5 + 0.18 * math.sin(elapsed / 20.0 + phase * 6.28)
                m = max(0.1, min(0.9, m))
                # Occasionally the "last" print diverges from the book (a signal).
                delta = 0.0
                if (int(elapsed / 5) + i) % 3 == 0:
                    delta = self.rng.choice([-0.19, 0.19])
                yb, ya = round(m - 0.01, 2), round(m + 0.01, 2)
                no_mid = 1 - m + 0.02
                nb, na = round(no_mid - 0.01, 2), round(no_mid + 0.01, 2)
                last = round(max(0.02, min(0.98, m + delta)), 2)
                mins = 15 + i * 20 - int(elapsed) % 15
                close = (datetime.now(timezone.utc)
                         + timedelta(minutes=max(1, mins))).isoformat()
                strike = int(spot * (1 + (i - 1) * 0.002))
                ms.append({
                    "ticker": f"{series}-{strike}-{i}", "event_ticker": series,
                    "title": f"{coin} above ${strike:,} at :{(i*20)%60:02d}",
                    "status": "active",
                    "yes_bid_dollars": yb, "yes_ask_dollars": ya,
                    "no_bid_dollars": nb, "no_ask_dollars": na,
                    "last_price_dollars": last,
                    "volume": 200 + self.rng.randint(0, 5000),
                    "close_time": close,
                })
            self._markets[series] = ms

    def get_events(self, series_ticker=None, **kw):
        return {"events": [{"markets": self._markets.get(series_ticker, [])}],
                "cursor": ""}

    def get_markets(self, **kw):
        return {"markets": [], "cursor": ""}


def _coin_of(ticker):
    for coin, series, _ in COINS:
        if ticker.startswith(series):
            return coin
    return ticker.split("-")[0]


# ──────────────────────────────────────────────────────────────────────────
# Web server
# ──────────────────────────────────────────────────────────────────────────
def make_handler(provider, refresh):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass  # quiet

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.startswith("/api/markets"):
                try:
                    data = provider.snapshot()
                except Exception as e:
                    data = {"mode": "ERROR", "error": str(e), "rows": [],
                            "balance": None,
                            "updated": datetime.now(timezone.utc).isoformat()}
                self._send(200, json.dumps(data).encode(), "application/json")
            else:
                html = PAGE.replace("__REFRESH__", str(int(refresh * 1000)))
                self._send(200, html.encode(), "text/html; charset=utf-8")

    return Handler


def main():
    parser = argparse.ArgumentParser(description="Live crypto up/down dashboard")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--demo", action="store_true",
                        help="Use synthetic data (no network/keys)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--refresh", type=float, default=5.0,
                        help="Browser refresh interval (seconds)")
    args = parser.parse_args()

    if args.demo:
        provider = DemoProvider()
        print("[dashboard] DEMO mode — synthetic data, no Kalshi connection")
    else:
        if not os.path.exists(args.config):
            print(f"Config not found: {args.config}. Use --demo to preview "
                  f"without keys, or copy config/config.example.yaml.")
            sys.exit(1)
        provider = LiveProvider(args.config)
        print("[dashboard] LIVE mode — pulling real Kalshi markets")

    server = ThreadingHTTPServer((args.host, args.port),
                                 make_handler(provider, args.refresh))
    print(f"[dashboard] open http://{args.host}:{args.port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[dashboard] stopped")


# ──────────────────────────────────────────────────────────────────────────
# Front-end (single self-contained page)
# ──────────────────────────────────────────────────────────────────────────
PAGE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kalshi Live — Up/Down Crypto</title>
<style>
  :root{
    --bg:#0b0e14; --panel:#131822; --panel2:#0f141d; --line:#222c3a;
    --txt:#e6edf3; --dim:#7d8aa0; --grn:#2ec36b; --red:#ff5c6c;
    --amber:#f5b942; --accent:#4aa8ff;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--txt);
    font:13px/1.4 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
  header{display:flex;align-items:center;gap:16px;padding:14px 20px;
    border-bottom:1px solid var(--line);background:var(--panel);position:sticky;top:0;z-index:5}
  h1{font-size:15px;margin:0;letter-spacing:.5px;font-weight:600}
  h1 .k{color:var(--accent)}
  .pill{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:999px;
    font-size:11px;border:1px solid var(--line);background:var(--panel2)}
  .dot{width:8px;height:8px;border-radius:50%;background:var(--grn)}
  .dot.live{animation:pulse 1.6s infinite}
  .dot.demo{background:var(--amber)}
  .dot.err{background:var(--red)}
  @keyframes pulse{0%{opacity:1;box-shadow:0 0 0 0 rgba(46,195,107,.5)}
    70%{opacity:.6;box-shadow:0 0 0 7px rgba(46,195,107,0)}100%{opacity:1}}
  .spacer{flex:1}
  .stats{display:flex;gap:10px;flex-wrap:wrap;padding:12px 20px}
  .stat{background:var(--panel);border:1px solid var(--line);border-radius:10px;
    padding:10px 14px;min-width:120px}
  .stat .lbl{color:var(--dim);font-size:10px;text-transform:uppercase;letter-spacing:.8px}
  .stat .val{font-size:20px;font-weight:600;margin-top:3px}
  .wrap{padding:0 20px 40px;overflow-x:auto}
  table{width:100%;border-collapse:collapse;min-width:860px}
  th,td{padding:8px 10px;text-align:right;white-space:nowrap}
  th{color:var(--dim);font-weight:500;font-size:10px;text-transform:uppercase;
    letter-spacing:.6px;border-bottom:1px solid var(--line);background:var(--bg)}
  td.l,th.l{text-align:left}
  tbody tr{border-bottom:1px solid #171e28}
  tbody tr.sig{background:linear-gradient(90deg,rgba(46,195,107,.10),transparent)}
  tbody tr.flash{animation:flash .8s}
  @keyframes flash{0%{background:rgba(74,168,255,.18)}100%{}}
  .coin{display:inline-block;min-width:42px;padding:2px 7px;border-radius:6px;
    background:var(--panel);border:1px solid var(--line);color:var(--accent);font-weight:600;text-align:center}
  .yes{color:var(--grn)} .no{color:var(--red)} .mut{color:var(--dim)}
  .badge{padding:2px 8px;border-radius:6px;font-weight:600;font-size:11px}
  .badge.buy-yes{background:rgba(46,195,107,.16);color:var(--grn)}
  .badge.buy-no{background:rgba(255,92,108,.16);color:var(--red)}
  .badge.none{color:var(--dim)}
  .cd{font-variant-numeric:tabular-nums}
  .cd.soon{color:var(--amber)} .cd.urgent{color:var(--red)}
  .bar{height:5px;border-radius:3px;background:#1b2431;margin-top:5px;overflow:hidden}
  .bar>i{display:block;height:100%;background:var(--accent)}
  footer{color:var(--dim);padding:10px 20px;font-size:11px;border-top:1px solid var(--line)}
  .err{color:var(--red)}
</style></head>
<body>
<header>
  <h1><span class="k">◆ KALSHI</span> LIVE · up/down crypto</h1>
  <span class="pill"><span id="dot" class="dot live"></span><b id="mode">connecting…</b></span>
  <span class="pill">refresh <b id="rf"></b></span>
  <div class="spacer"></div>
  <span class="pill">updated <b id="upd">—</b></span>
</header>
<div class="stats">
  <div class="stat"><div class="lbl">Markets tracked</div><div class="val" id="s-count">—</div></div>
  <div class="stat"><div class="lbl">Bot signals</div><div class="val yes" id="s-sig">—</div></div>
  <div class="stat"><div class="lbl">Best edge</div><div class="val" id="s-edge">—</div></div>
  <div class="stat"><div class="lbl">Total volume</div><div class="val" id="s-vol">—</div></div>
  <div class="stat"><div class="lbl">Balance</div><div class="val" id="s-bal">—</div></div>
</div>
<div class="wrap">
<table>
  <thead><tr>
    <th class="l">Market</th><th>Coin</th>
    <th>YES bid/ask</th><th>NO bid/ask</th><th>Last</th><th>Vol</th>
    <th>Closes in</th><th>Edge</th><th class="l">Signal</th>
  </tr></thead>
  <tbody id="rows"><tr><td class="l mut" colspan="9">Loading…</td></tr></tbody>
</table>
</div>
<footer id="foot">Waiting for data…</footer>
<script>
const REFRESH=parseInt("__REFRESH__");
document.getElementById('rf').textContent=(REFRESH/1000)+'s';
let closeTimes={}; // ticker -> epoch ms
let prevSig={};

function fmtC(v){return v>0?('$'+v.toFixed(2)):'—';}
function fmtVol(v){v=v||0;return v>=1000?(v/1000).toFixed(1)+'k':String(Math.round(v));}
function pct(v){return (v>=0?'+':'')+(v*100).toFixed(1)+'%';}

function countdown(ms){
  let d=ms-Date.now();
  if(d<0) d=0;
  const m=Math.floor(d/60000), s=Math.floor((d%60000)/1000);
  let cls=d<60000?'urgent':(d<300000?'soon':'');
  return '<span class="cd '+cls+'">'+m+'m '+(s<10?'0':'')+s+'s</span>';
}
function tick(){
  document.querySelectorAll('tr[data-t]').forEach(tr=>{
    const t=tr.getAttribute('data-t');
    if(closeTimes[t]) tr.querySelector('.cdcell').innerHTML=countdown(closeTimes[t]);
  });
}
setInterval(tick,1000);

async function load(){
  let data;
  try{ data=await (await fetch('/api/markets')).json(); }
  catch(e){ document.getElementById('mode').textContent='disconnected';
    document.getElementById('dot').className='dot err'; return; }

  const dot=document.getElementById('dot');
  dot.className='dot '+(data.mode==='LIVE'?'live':(data.mode==='DEMO'?'demo':'err'));
  document.getElementById('mode').textContent=data.mode+(data.mode==='DEMO'?' (synthetic)':'');
  document.getElementById('upd').textContent=new Date(data.updated).toLocaleTimeString();

  const rows=data.rows||[];
  const sigs=rows.filter(r=>r.side);
  const best=rows.reduce((a,r)=>Math.max(a,r.edge||0),0);
  const vol=rows.reduce((a,r)=>a+(r.volume||0),0);
  document.getElementById('s-count').textContent=rows.length;
  document.getElementById('s-sig').textContent=sigs.length;
  document.getElementById('s-edge').textContent=best>0?pct(best):'—';
  document.getElementById('s-vol').textContent=fmtVol(vol);
  document.getElementById('s-bal').textContent=data.balance!=null?('$'+data.balance.toFixed(2)):'—';

  const tb=document.getElementById('rows');
  closeTimes={};
  tb.innerHTML = rows.length? rows.map(r=>{
    closeTimes[r.ticker]=new Date(r.close_time).getTime();
    const sig=r.side?('<span class="badge buy-'+r.side+'">BUY '+r.side.toUpperCase()+'</span>')
                     :'<span class="badge none">—</span>';
    const edge=r.edge>0?('<span class="yes">'+pct(r.edge)+'</span>'):'<span class="mut">—</span>';
    const flash=(r.side && !prevSig[r.ticker])?' flash':'';
    return '<tr data-t="'+r.ticker+'" class="'+(r.side?'sig':'')+flash+'">'
      +'<td class="l">'+r.title+'</td>'
      +'<td><span class="coin">'+r.coin+'</span></td>'
      +'<td><span class="mut">'+fmtC(r.yes_bid)+'</span> / '+fmtC(r.yes_ask)+'</td>'
      +'<td><span class="mut">'+fmtC(r.no_bid)+'</span> / '+fmtC(r.no_ask)+'</td>'
      +'<td>'+fmtC(r.last)+'</td>'
      +'<td class="mut">'+fmtVol(r.volume)+'</td>'
      +'<td class="cdcell">'+countdown(closeTimes[r.ticker])+'</td>'
      +'<td>'+edge+'</td>'
      +'<td class="l">'+sig+'</td></tr>';
  }).join(''):'<tr><td class="l mut" colspan="9">No open up/down crypto markets right now.</td></tr>';

  prevSig={}; sigs.forEach(r=>prevSig[r.ticker]=true);
  const f=document.getElementById('foot');
  f.innerHTML = data.error? ('<span class="err">API note: '+data.error+'</span>')
    : (rows.length+' markets · '+sigs.length+' signal(s) · edge = bot fair value − ask (price-divergence heuristic, not a guarantee)');
}
load(); setInterval(load,REFRESH);
</script>
</body></html>"""


if __name__ == "__main__":
    main()
