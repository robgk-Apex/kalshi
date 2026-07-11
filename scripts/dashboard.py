"""Live visual dashboard for the short-term up/down crypto markets.

A zero-dependency (stdlib only) web dashboard that shows the directional crypto
markets the bot watches, auto-refreshing in the browser. Each row shows the
YES/NO book, last trade, volume, a live countdown to settlement, and the bot's
detected edge/signal (computed with the SAME scanner logic the bot trades on).

You can also click "Take" on a market to log a trade you made — the dashboard
then tracks it and shows an active P&L that updates as your positions settle to
wins ($1/contract) or losses ($0). Your ledger is kept server-side in
logs/dashboard_ledger.json.

    # LIVE (public) — REAL Kalshi market data, no account or keys needed
    python scripts/dashboard.py --live

    # LIVE (authenticated) — also shows your account balance
    python scripts/dashboard.py --config config/config.yaml

    # DEMO — synthetic data, no network (a preview of the screen)
    python scripts/dashboard.py --demo

Then open http://localhost:8787 in your browser.

Note: settlement (win/loss P&L) requires Kalshi to tell us the market result, so
realized P&L only advances in LIVE mode. In DEMO mode taken trades show as open
with mark-to-market unrealized P&L. To fully explore the take/settle loop with
no keys, use the interactive Artifact preview instead.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import src.paper_trader as paper_trader_module
from src.scanner import MarketScanner
from src.signals import indicators_from_series, recommend, strike_from_market


def build_rec(prices, strike, yes_ask, no_ask, hours, edge):
    """Educated recommendation for one market, safe against any bad input."""
    try:
        r = recommend(indicators_from_series(prices, strike),
                      yes_ask, no_ask, hours, edge)
        return {"action": r.action, "side": r.side, "conf": r.confidence,
                "reasons": r.reasons}
    except Exception:
        return {"action": "HOLD", "side": "", "conf": 0,
                "reasons": ["no price data"]}


def apply_rec(row, prices, strike):
    """Attach an educated recommendation to a row; when it's actionable, it also
    becomes what the Take button pre-selects."""
    rec = build_rec(prices, strike, row["yes_ask"], row["no_ask"],
                    row["hours_left"], row["edge"])
    row["rec"] = rec
    if rec["action"] != "HOLD" and rec["side"]:
        row["lean_side"] = rec["side"]
        row["lean_ask"] = round(row["yes_ask"] if rec["side"] == "yes"
                                else row["no_ask"], 2)
    return row

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


def _new_paper(starting=1000.0):
    """A PaperTrader that keeps the dashboard ledger in its own file."""
    paper_trader_module.PAPER_FILE = os.path.join("logs", "dashboard_ledger.json")
    from src.paper_trader import PaperTrader
    return PaperTrader(starting_balance=starting)


def _coin_of(ticker):
    for coin, series, _ in COINS:
        if ticker.startswith(series):
            return coin
    return ticker.split("-")[0]


# ──────────────────────────────────────────────────────────────────────────
# Ledger — shared take/settle/P&L logic on top of PaperTrader
# ──────────────────────────────────────────────────────────────────────────
class Ledger:
    def __init__(self):
        self.paper = _new_paper()
        self._lock = threading.Lock()

    def take(self, ticker, side, price, count):
        with self._lock:
            if ticker in self.paper.positions:
                return  # already holding
            self.paper.record_entry(ticker, side, int(count), float(price))

    def settle(self, client):
        with self._lock:
            try:
                self.paper.check_settlements(client)
            except Exception:
                pass

    def view(self, mid_by_ticker):
        """Return a JSON-safe ledger snapshot.

        Realized P&L is the sum of SETTLED trade P&L only (a win pays
        $1/contract, a loss pays $0) — open positions do NOT count as losses
        just because cash was deployed. Unrealized P&L marks open positions to
        the current mid.
        """
        with self._lock:
            open_pos = []
            unreal = 0.0
            for ticker, p in self.paper.positions.items():
                mid = mid_by_ticker.get(ticker)
                cur = mid.get(p["side"]) if mid else None
                u = (cur - p["entry_price"]) * p["contracts"] if cur is not None else 0.0
                unreal += u
                open_pos.append({
                    "ticker": ticker, "coin": _coin_of(ticker), "side": p["side"],
                    "entry": p["entry_price"], "qty": p["contracts"],
                    "now": cur, "unreal": round(u, 2),
                })
            realized = sum(c["pnl"] for c in self.paper.closed_trades)
            wins = sum(1 for c in self.paper.closed_trades if c["won"])
            losses = sum(1 for c in self.paper.closed_trades if not c["won"])
            wr = f"{wins / (wins + losses) * 100:.0f}%" if (wins + losses) else "—"
            closed = [{
                "ticker": c["ticker"], "coin": _coin_of(c["ticker"]),
                "side": c["side"], "entry": c["entry_price"], "qty": c["contracts"],
                "result": c["result"], "won": c["won"], "pnl": round(c["pnl"], 2),
            } for c in self.paper.closed_trades[-15:]][::-1]
            return {
                "realized": round(realized, 2), "unreal": round(unreal, 2),
                "net": round(realized + unreal, 2),
                "wins": wins, "losses": losses, "win_rate": wr,
                "open_count": len(self.paper.positions),
                "staked": round(sum(p["cost"] for p in self.paper.positions.values()), 2),
                "open": open_pos, "closed": closed,
            }

    def clear(self):
        with self._lock:
            self.paper.positions = {}
            self.paper.closed_trades = []
            self.paper.balance = self.paper.starting_balance
            self.paper.trade_count = 0
            self.paper._save()


# ──────────────────────────────────────────────────────────────────────────
# Data providers
# ──────────────────────────────────────────────────────────────────────────
class LiveProvider:
    """Pulls real directional-crypto markets from Kalshi and flags the bot's
    signals. Results are cached for `min_interval` seconds so rapid browser
    polling doesn't hammer the API."""

    def __init__(self, client, min_interval=1.0):
        self.client = client
        self.scanner = _gate_free_scanner(self.client)
        self.ledger = Ledger()
        try:
            from src.crypto_analyzer import CryptoAnalyzer
            self.analyzer = CryptoAnalyzer()
        except Exception:
            self.analyzer = None
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._cache = None
        self._cache_at = 0.0
        self._logged = False

    def snapshot(self):
        with self._lock:
            if self._cache and (time.time() - self._cache_at) < self.min_interval:
                return self._cache
            self.ledger.settle(self.client)
            snap = self._fetch()
            self._cache = snap
            self._cache_at = time.time()
            return snap

    def _fetch(self):
        rows, error, balance = [], None, None
        if getattr(self.client, "authed", False):
            try:
                bal = self.client.get_balance()
                balance = bal.get("balance", 0) / 100
            except Exception as e:
                error = f"balance: {e}"

        seen = set()
        for si, series in enumerate(self.scanner.crypto_series):
            if si:
                time.sleep(0.25)  # throttle: Kalshi's public API rate-limits bursts
            cursor = None
            for _page in range(6):  # page through all open strikes for the series
                try:
                    params = {"series_ticker": series, "limit": 200,
                              "with_nested_markets": True, "status": "open"}
                    if cursor:
                        params["cursor"] = cursor
                    resp = self.client.get_events(**params)
                except Exception as e:
                    error = str(e)
                    break
                for event in resp.get("events", []):
                    for m in event.get("markets", []):
                        t = m.get("ticker", "")
                        if not t or t in seen:
                            continue
                        seen.add(t)
                        rows.append(self._row(m))
                cursor = resp.get("cursor", "")
                if not cursor:
                    break
        rows = [r for r in rows if r]
        for r in rows:
            prices, _ = self._prices_strike(r["ticker"])
            apply_rec(r, prices, r.get("strike", 0))
        rows.sort(key=lambda r: (r["hours_left"], -abs(r["edge"])))
        if not self._logged:
            self._logged = True
            if rows:
                print(f"[dashboard] LIVE: pulled {len(rows)} real Kalshi markets "
                      f"(e.g. {rows[0]['ticker']} yes_ask=${rows[0]['yes_ask']:.2f})")
            elif error:
                print(f"[dashboard] LIVE: no markets — {error}. Check API key / "
                      f"base_url in config, and that markets are open.")
            else:
                print("[dashboard] LIVE: no open up/down crypto markets right now.")
        mids = {r["ticker"]: {"yes": (r["yes_bid"] + r["yes_ask"]) / 2,
                              "no": (r["no_bid"] + r["no_ask"]) / 2} for r in rows}
        return {"mode": "LIVE", "error": error, "balance": balance,
                "updated": datetime.now(timezone.utc).isoformat(), "rows": rows,
                "ledger": self.ledger.view(mids)}

    def _prices_strike(self, ticker):
        """Real price history + strike for a ticker, via the CryptoAnalyzer
        (fetches live crypto prices, cached). Returns (prices, strike)."""
        a = self.analyzer
        if not a:
            return None, 0
        try:
            cid, _sym = a._get_coin(ticker)
            if not cid:
                return None, 0
            price = a._get_price(cid)
            hist = a._get_history(cid) or []
            prices = [p for _ts, p in hist]
            if price:
                prices = prices + [price]
            return prices, (a._parse_strike(ticker) or 0)
        except Exception:
            return None, 0

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
        # side the bot leans (for the Take button even without a full signal)
        lean_side = opp.side if opp else ("yes" if ya <= na else "no")
        lean_ask = ya if lean_side == "yes" else na
        return {
            "ticker": ticker, "coin": _coin_of(ticker),
            "title": m.get("title", ticker),
            "yes_bid": yb, "yes_ask": ya, "no_bid": nb, "no_ask": na,
            "last": last, "volume": vol, "hours_left": hours, "close_time": ct,
            "edge": round(opp.edge, 4) if opp else 0.0,
            "side": opp.side if opp else "",
            "lean_side": lean_side, "lean_ask": round(lean_ask, 2),
            # Strike across both formats: hourly -T<price> suffix AND the
            # 15-min floor_strike field / "Target Price: $X" title.
            "strike": strike_from_market(m),
        }


class DemoProvider:
    """Generates synthetic up/down crypto markets whose prices drift over time."""

    def __init__(self):
        self.rng = random.Random(1)
        self.client = _DemoClient(self.rng)
        self.scanner = _gate_free_scanner(self.client)
        self.ledger = Ledger()
        self._t0 = time.time()

    def snapshot(self):
        self.client.regenerate(time.time() - self._t0)
        self.ledger.settle(self.client)  # demo tickers are stable, so no-op mostly
        rows = []
        for series in self.scanner.crypto_series:
            resp = self.client.get_events(series_ticker=series)
            for event in resp.get("events", []):
                for m in event.get("markets", []):
                    rows.append(LiveProvider._row(self, m))
        rows = [r for r in rows if r]
        for r in rows:
            prices, strike = self.client.ta(r["ticker"])
            apply_rec(r, prices, strike)
        rows.sort(key=lambda r: (r["hours_left"], -abs(r["edge"])))
        mids = {r["ticker"]: {"yes": (r["yes_bid"] + r["yes_ask"]) / 2,
                              "no": (r["no_bid"] + r["no_ask"]) / 2} for r in rows}
        return {"mode": "DEMO", "error": None, "balance": 1000.0,
                "updated": datetime.now(timezone.utc).isoformat(), "rows": rows,
                "ledger": self.ledger.view(mids)}


class _DemoClient:
    """Synthetic market data with a real per-coin spot random walk, so the
    recommendation engine runs on genuine price indicators (trend/momentum/etc).
    Tickers are stable (SERIES-slot) so held positions persist."""

    def __init__(self, rng):
        self.rng = rng
        self.coins = {}
        for coin, series, spot in COINS:
            self.coins[series] = {
                "sym": coin, "spot": spot, "hist": [spot] * 30,
                "vol": 0.0025 + rng.random() * 0.0035,
                "strikes": [round(spot * (1 + off), 6)
                            for off in (-0.004, 0.0, 0.004)],
            }
        self._markets = {}

    def get_balance(self):
        return {"balance": 100000}

    def _fmt_strike(self, s):
        return f"{s:,.0f}" if s >= 1000 else f"{s:.4f}".rstrip("0").rstrip(".")

    def regenerate(self, elapsed):
        for series, c in self.coins.items():
            c["spot"] = max(1e-6, c["spot"] * (1 + self.rng.gauss(0, c["vol"])))
            c["hist"].append(c["spot"])
            if len(c["hist"]) > 40:
                c["hist"].pop(0)
        self._markets = {}
        for series, c in self.coins.items():
            spot, ms = c["spot"], []
            for i, strike in enumerate(c["strikes"]):
                # book-implied prob of YES (finish above strike) tracks spot
                m = max(0.1, min(0.9, 0.5 + 6.0 * (spot - strike) / strike))
                delta = 0.0
                if (int(elapsed / 5) + i) % 3 == 0:
                    delta = self.rng.choice([-0.16, 0.16])
                yb, ya = round(m - 0.01, 2), round(m + 0.01, 2)
                no_mid = 1 - m + 0.02
                nb, na = round(no_mid - 0.01, 2), round(no_mid + 0.01, 2)
                last = round(max(0.02, min(0.98, m + delta)), 2)
                mins = 15 + i * 20 - int(elapsed) % 15
                close = (datetime.now(timezone.utc)
                         + timedelta(minutes=max(1, mins))).isoformat()
                ms.append({
                    "ticker": f"{series}-{i}", "event_ticker": series,
                    "title": f"{c['sym']} above ${self._fmt_strike(strike)} (up/down)",
                    "status": "active",
                    "yes_bid_dollars": yb, "yes_ask_dollars": ya,
                    "no_bid_dollars": nb, "no_ask_dollars": na,
                    "last_price_dollars": last,
                    "volume": 200 + self.rng.randint(0, 5000),
                    "close_time": close,
                })
            self._markets[series] = ms

    def ta(self, ticker):
        """Price history + strike for a demo ticker (for the recommendation)."""
        series, _, idx = ticker.rpartition("-")
        c = self.coins.get(series)
        if not c:
            return None, 0
        try:
            strike = c["strikes"][int(idx)]
        except (ValueError, IndexError):
            strike = c["spot"]
        return list(c["hist"]), strike

    def get_events(self, series_ticker=None, **kw):
        return {"events": [{"markets": self._markets.get(series_ticker, [])}],
                "cursor": ""}

    def get_markets(self, **kw):
        return {"markets": [], "cursor": ""}

    def get_market(self, ticker):
        # Demo markets never settle (stable tickers); positions stay open.
        return {"market": {"status": "active"}}


# ──────────────────────────────────────────────────────────────────────────
# Web server
# ──────────────────────────────────────────────────────────────────────────
def make_handler(provider, refresh, public=False):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if public:  # view-only board: no shared-portfolio writes
                self._send(403, b'{"ok":false,"error":"view-only"}',
                           "application/json")
                return
            if self.path.startswith("/api/take"):
                n = int(self.headers.get("Content-Length", 0))
                try:
                    body = json.loads(self.rfile.read(n) or b"{}")
                    provider.ledger.take(body["ticker"], body["side"],
                                         body["price"], body.get("count", 10))
                    ok = True
                except Exception as e:
                    ok = False
                self._send(200, json.dumps({"ok": ok}).encode(), "application/json")
            elif self.path.startswith("/api/clear"):
                provider.ledger.clear()
                self._send(200, b'{"ok":true}', "application/json")
            else:
                self._send(404, b"not found", "text/plain")

        def do_GET(self):
            if self.path.startswith("/api/markets"):
                try:
                    data = provider.snapshot()
                except Exception as e:
                    data = {"mode": "ERROR", "error": str(e), "rows": [],
                            "balance": None, "ledger": None,
                            "updated": datetime.now(timezone.utc).isoformat()}
                self._send(200, json.dumps(data).encode(), "application/json")
            else:
                html = (PAGE.replace("__REFRESH__", str(int(refresh * 1000)))
                            .replace("__VIEWONLY__", "true" if public else "false"))
                self._send(200, html.encode(), "text/html; charset=utf-8")

    return Handler


PROD_BASE = "https://api.elections.kalshi.com/trade-api/v2"


def build_live_provider(args):
    """Build a LiveProvider that pulls REAL Kalshi data.

    Priority: --config file, else env vars, else public (no-auth) live mode.
    Public mode needs no account/keys — it reads Kalshi's public market data,
    which is all the read-only board requires. Auth (config/env keys) adds the
    account balance tile.
    """
    from src.api_client import KalshiClient
    base = args.base_url or os.environ.get("KALSHI_BASE_URL") or PROD_BASE

    if args.config and os.path.exists(args.config):
        import yaml
        with open(args.config) as f:
            api = yaml.safe_load(f)["api"]
        client = KalshiClient(api["base_url"], api.get("key_id"),
                              api.get("private_key_path"))
        print(f"[dashboard] LIVE (authenticated via {args.config}) — real Kalshi data")
        return LiveProvider(client, min_interval=args.refresh)

    key_id = os.environ.get("KALSHI_KEY_ID")
    key_path = os.environ.get("KALSHI_PRIVATE_KEY_PATH")
    if os.environ.get("KALSHI_PRIVATE_KEY") and not key_path:
        key_path = os.path.join("logs", "_kalshi_env.pem")
        with open(key_path, "w") as f:
            f.write(os.environ["KALSHI_PRIVATE_KEY"])
    if key_id and key_path:
        client = KalshiClient(base, key_id, key_path)
        print("[dashboard] LIVE (authenticated via env) — real Kalshi data")
    else:
        client = KalshiClient(base)  # public, no auth
        print(f"[dashboard] LIVE (public, no keys) — real Kalshi data from {base}")
    return LiveProvider(client, min_interval=args.refresh)


def main():
    parser = argparse.ArgumentParser(description="Live crypto up/down dashboard")
    parser.add_argument("--live", action="store_true",
                        help="Pull REAL Kalshi public data (no keys needed)")
    parser.add_argument("--config", default=None,
                        help="Authenticated live mode from a config.yaml")
    parser.add_argument("--demo", action="store_true",
                        help="Synthetic data (no network/keys) — a preview")
    parser.add_argument("--base-url", default=None,
                        help=f"Kalshi API base (default {PROD_BASE})")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8787)))
    parser.add_argument("--refresh", type=float, default=1.0,
                        help="Browser refresh interval in seconds (default 1)")
    parser.add_argument("--public", action="store_true",
                        help="View-only: share the live board with others; hide "
                             "the Take/Clear/P&L trading UI (no shared portfolio)")
    args = parser.parse_args()

    os.makedirs("logs", exist_ok=True)
    if args.demo:
        provider = DemoProvider()
        print("[dashboard] DEMO mode — synthetic data, no Kalshi connection")
    elif args.live or args.config or args.base_url or os.environ.get("KALSHI_KEY_ID"):
        provider = build_live_provider(args)
    else:
        print("Pick a data source:")
        print("  --live                     real Kalshi public data (no keys)")
        print("  --config config/config.yaml  authenticated (adds your balance)")
        print("  --demo                     synthetic preview")
        sys.exit(1)

    server = ThreadingHTTPServer((args.host, args.port),
                                 make_handler(provider, args.refresh, args.public))
    shown = "localhost" if args.host in ("127.0.0.1", "0.0.0.0") else args.host
    if args.public:
        print("[dashboard] PUBLIC view-only — trading UI disabled, safe to share")
    print(f"[dashboard] open http://{shown}:{args.port}  (Ctrl+C to stop)")
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
  :root{--bg:#0b0e14;--panel:#131822;--panel2:#0f141d;--line:#222c3a;--txt:#e6edf3;
    --dim:#7d8aa0;--dim2:#556074;--accent:#4aa8ff;--grn:#2ec36b;--red:#ff5c6c;--amber:#f5b942;
    --grn-w:rgba(46,195,107,.14);--red-w:rgba(255,92,108,.14)}
  *{box-sizing:border-box} html,body{margin:0}
  body{background:radial-gradient(1200px 500px at 80% -10%,rgba(74,168,255,.06),transparent 60%),var(--bg);
    color:var(--txt);font:13px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;-webkit-font-smoothing:antialiased}
  .term{max-width:1180px;margin:0 auto;padding:0 18px 48px}
  header{display:flex;align-items:center;gap:14px;flex-wrap:wrap;padding:16px 4px 14px;
    border-bottom:1px solid var(--line);position:sticky;top:0;background:linear-gradient(var(--bg),rgba(11,14,20,.86));backdrop-filter:blur(6px);z-index:10}
  .brand{font-family:system-ui,-apple-system,Segoe UI,sans-serif;font-size:16px;font-weight:700;margin:0;display:flex;align-items:center;gap:9px}
  .brand .mark{color:var(--accent)} .brand .sub{color:var(--dim);font-weight:500;font-size:12px}
  .pill{display:inline-flex;align-items:center;gap:7px;padding:4px 11px;border-radius:999px;font-size:11px;
    border:1px solid var(--line);background:var(--panel2);color:var(--dim);font-variant-numeric:tabular-nums}
  .pill b{color:var(--txt);font-weight:600}
  .dot{width:8px;height:8px;border-radius:50%;background:var(--grn)} .live .dot{animation:pulse 1.7s infinite}
  .dot.demo{background:var(--amber)} .dot.err{background:var(--red)}
  @keyframes pulse{0%{box-shadow:0 0 0 0 rgba(46,195,107,.5)}70%{box-shadow:0 0 0 7px rgba(46,195,107,0)}100%{}}
  .grow{flex:1} select{background:var(--panel2);color:var(--txt);border:1px solid var(--line);border-radius:7px;padding:3px 6px;font:inherit;font-size:11px}
  .pnlbar{display:flex;gap:14px;flex-wrap:wrap;background:linear-gradient(180deg,var(--panel),var(--panel2));
    border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:16px 0 14px}
  .pnlbar .big{display:flex;flex-direction:column;justify-content:center;min-width:170px}
  .pnlbar .big .lbl{color:var(--dim);font-size:10px;letter-spacing:.9px;text-transform:uppercase}
  .pnlbar .big .num{font-size:30px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.1;margin-top:2px}
  .pnlbar .cells{display:grid;grid-template-columns:repeat(4,minmax(84px,1fr));gap:12px;flex:1}
  .cell .lbl{color:var(--dim);font-size:10px;letter-spacing:.7px;text-transform:uppercase}
  .cell .v{font-size:16px;font-weight:600;margin-top:3px;font-variant-numeric:tabular-nums}
  .ghost{background:transparent;color:var(--dim);border:1px solid var(--line);border-radius:8px;padding:7px 12px;font:inherit;font-size:11px;cursor:pointer}
  .ghost:hover{color:var(--txt);border-color:var(--dim2)}
  .stats{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:14px 0}
  .stat{background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--line);border-radius:12px;padding:12px 14px}
  .stat .lbl{color:var(--dim);font-size:10px;letter-spacing:.9px;text-transform:uppercase}
  .stat .val{font-size:22px;font-weight:650;margin-top:5px;font-variant-numeric:tabular-nums}
  .stat .foot{font-size:10.5px;color:var(--dim2);margin-top:2px}
  .section-h{display:flex;align-items:center;gap:10px;margin:22px 2px 10px}
  .section-h h2{font-size:12px;letter-spacing:.9px;text-transform:uppercase;color:var(--dim);margin:0;font-weight:600}
  .section-h .rule{flex:1;height:1px;background:var(--line)}
  .toolbar{display:flex;align-items:center;gap:12px;margin:2px 2px 12px}
  .tlabel{color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:.7px}
  .seg{display:inline-flex;border:1px solid var(--line);border-radius:9px;overflow:hidden;background:var(--panel2)}
  .seg button{background:transparent;color:var(--dim);border:none;border-right:1px solid var(--line);padding:6px 13px;font:inherit;font-size:11px;font-weight:600;cursor:pointer}
  .seg button:last-child{border-right:none} .seg button:hover{color:var(--txt)}
  .seg button.on{background:rgba(74,168,255,.16);color:var(--accent)}
  .tablewrap{border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--panel2)}
  .scroll{overflow-x:auto} table{width:100%;border-collapse:collapse;min-width:940px}
  thead th{color:var(--dim);font-weight:500;font-size:10px;letter-spacing:.7px;text-transform:uppercase;text-align:right;padding:11px 12px;background:var(--panel);border-bottom:1px solid var(--line)}
  thead th.l,tbody td.l{text-align:left}
  tbody td{padding:9px 12px;text-align:right;border-bottom:1px solid #161d27;font-variant-numeric:tabular-nums;white-space:nowrap}
  tbody tr:last-child td{border-bottom:none}
  tbody tr.sig{background:linear-gradient(90deg,var(--grn-w),transparent 55%)}
  tbody tr.sig.no{background:linear-gradient(90deg,var(--red-w),transparent 55%)}
  .coin{display:inline-flex;justify-content:center;min-width:46px;padding:3px 8px;border-radius:7px;background:#0e1420;border:1px solid var(--line);color:var(--accent);font-weight:700;font-size:11px}
  .up{color:var(--grn)} .down{color:var(--red)} .mut{color:var(--dim)} .book span{color:var(--dim2)}
  .chip{padding:3px 9px;border-radius:7px;font-weight:700;font-size:11px}
  .chip.yes{background:var(--grn-w);color:var(--grn)} .chip.no{background:var(--red-w);color:var(--red)} .chip.flat{color:var(--dim2);font-weight:500}
  .edge.pos{color:var(--grn);font-weight:600}
  .cd.soon{color:var(--amber)} .cd.urgent{color:var(--red);font-weight:600}
  .take{border:1px solid var(--accent);color:var(--accent);background:rgba(74,168,255,.10);border-radius:7px;padding:5px 10px;font:inherit;font-size:11px;font-weight:600;cursor:pointer}
  .take:hover{background:rgba(74,168,255,.22)} .take.held{border-color:var(--grn);color:var(--grn);background:var(--grn-w);cursor:default}
  .badge{padding:2px 8px;border-radius:6px;font-weight:700;font-size:10.5px}
  .badge.won{background:var(--grn-w);color:var(--grn)} .badge.lost{background:var(--red-w);color:var(--red)} .badge.open{background:rgba(74,168,255,.12);color:var(--accent)}
  .empty{padding:16px 14px;color:var(--dim2);font-size:12px}
  footer{color:var(--dim2);font-size:11px;margin-top:16px;line-height:1.6} footer .warn{color:var(--amber)} .err{color:var(--red)}
  @media (max-width:860px){.stats{grid-template-columns:repeat(2,1fr)}.pnlbar .cells{grid-template-columns:repeat(2,1fr)}}
</style></head>
<body>
<div class="term">
<header id="hdr" class="live">
  <h1 class="brand"><span class="mark">◆</span> KALSHI&nbsp;<span class="sub">up/down crypto terminal</span></h1>
  <span class="pill"><span id="dot" class="dot"></span><b id="mode">connecting…</b></span>
  <div class="grow"></div>
  <span class="pill">updated <b id="upd">—</b></span>
</header>

<section class="pnlbar" id="pnlbar" style="display:none">
  <div class="big"><div class="lbl">Active P&amp;L</div><div class="num" id="p-net">$0.00</div></div>
  <div class="cells">
    <div class="cell"><div class="lbl">Realized</div><div class="v" id="p-real">$0.00</div></div>
    <div class="cell"><div class="lbl">Unrealized</div><div class="v" id="p-unreal">$0.00</div></div>
    <div class="cell"><div class="lbl">Record W–L</div><div class="v" id="p-wl">0–0</div></div>
    <div class="cell"><div class="lbl">Win rate</div><div class="v" id="p-wr">—</div></div>
  </div>
  <div style="display:flex;align-items:center"><button class="ghost" id="clear">Clear ledger</button></div>
</section>

<section class="stats">
  <div class="stat"><div class="lbl">Markets</div><div class="val" id="s-count">—</div><div class="foot">up/down contracts</div></div>
  <div class="stat"><div class="lbl">Suggestions</div><div class="val up" id="s-sig">—</div><div class="foot">BUY YES / BUY NO</div></div>
  <div class="stat"><div class="lbl">Best edge</div><div class="val" id="s-edge">—</div><div class="foot">fair − ask</div></div>
  <div class="stat" id="opentrades"><div class="lbl">Open trades</div><div class="val" id="s-open">0</div><div class="foot">you're holding</div></div>
  <div class="stat"><div class="lbl">Balance</div><div class="val" id="s-bal">—</div><div class="foot">Kalshi account</div></div>
</section>

<div class="toolbar">
  <span class="tlabel">Window</span>
  <div class="seg" id="filter">
    <button data-cad="15m">15 min</button>
    <button data-cad="hourly">Hourly</button>
    <button data-cad="daily">Daily</button>
    <button data-cad="weekly">Weekly</button>
    <button data-cad="all" class="on">All</button>
  </div>
</div>

<div class="tablewrap"><div class="scroll"><table>
  <thead><tr><th class="l">Market</th><th>Coin</th><th>YES bid/ask</th><th>NO bid/ask</th>
    <th>Last</th><th>Vol</th><th>Closes in</th><th>Edge</th><th>Suggestion</th><th class="l tradecol">Trade</th></tr></thead>
  <tbody id="rows"><tr><td class="l mut" colspan="10">Loading…</td></tr></tbody>
</table></div></div>

<div class="section-h mytrades"><h2>My trades</h2><span class="rule"></span></div>
<div class="tablewrap mytrades"><div class="scroll"><table>
  <thead><tr><th class="l">Market</th><th>Side</th><th>Entry</th><th>Invested</th><th>Qty</th><th>Now / Result</th><th>P&amp;L</th><th class="l">Status</th></tr></thead>
  <tbody id="ledger"><tr><td class="empty l" colspan="8">No trades yet — click <b>Take</b> on a market above.</td></tr></tbody>
</table></div></div>

<footer id="foot">Waiting for data…</footer>
</div>
<script>
const REFRESH=parseInt("__REFRESH__");
const VIEW_ONLY=__VIEWONLY__;   // shared board: live data only, no trading UI
let closeTimes={};
function fmtC(v){return v>0?('$'+v.toFixed(2)):'—';}
function fmtVol(v){v=v||0;return v>=1000?(v/1000).toFixed(1)+'k':String(Math.round(v));}
function pct(v){return (v>=0?'+':'')+(v*100).toFixed(1)+'%';}
function signed(v){return (v>=0?'+$':'-$')+Math.abs(v).toFixed(2);}
function countdown(ms){let d=Math.max(0,ms-Date.now());const m=Math.floor(d/60000),s=Math.floor(d%60000/1000);
  let c=d<60000?'urgent':(d<300000?'soon':'');return '<span class="cd '+c+'">'+m+'m '+(s<10?'0':'')+s+'s</span>';}
function tick(){document.querySelectorAll('tr[data-t]').forEach(tr=>{const t=tr.getAttribute('data-t');
  if(closeTimes[t]) tr.querySelector('.cdcell').innerHTML=countdown(closeTimes[t]);});}
setInterval(tick,1000);

let CAD="all";  // Kalshi crypto up/down cadences: 15m / hourly / daily / weekly
// 15-min markets come from the *15M series; the hourly (*D) series lists this
// hour's window plus future ones, so split those by time.
const cadence=r=>/15M/.test(r.ticker)?"15m":(r.hours_left<=1.5?"hourly":r.hours_left<=48?"daily":"weekly");
async function take(ticker,side,price){
  const def=localStorage.getItem('kalshi_amt')||'25';
  const inp=prompt('How much did you put in on '+side.toUpperCase()+' @ $'+price.toFixed(2)+' per contract?  ($)', def);
  if(inp===null) return;
  const amt=parseFloat(inp); if(!amt||amt<=0) return;
  localStorage.setItem('kalshi_amt', Math.round(amt));
  const count=Math.max(1, Math.round(amt/price));
  await fetch('/api/take',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({ticker,side,price,count})});
  load();
}
if(VIEW_ONLY){
  // Shared board — strip the trading surface so viewers can't collide on one
  // portfolio. Live market data, suggestions and countdowns stay.
  document.body.classList.add('viewonly');
  const hide=el=>{if(el)el.style.display='none';};
  hide(document.getElementById('pnlbar'));
  hide(document.getElementById('clear'));
  hide(document.getElementById('opentrades'));
  document.querySelectorAll('.tradecol').forEach(el=>el.style.display='none');
  document.querySelectorAll('.mytrades').forEach(el=>el.style.display='none');
}else{
  document.getElementById('clear').onclick=async()=>{if(confirm('Clear all tracked trades?')){await fetch('/api/clear',{method:'POST'});load();}};
}
document.querySelectorAll('#filter button').forEach(btn=>btn.onclick=()=>{
  CAD=btn.dataset.cad;
  document.querySelectorAll('#filter button').forEach(b=>b.classList.toggle('on',b===btn));
  load();
});

async function load(){
  let d; try{ d=await (await fetch('/api/markets')).json(); }
  catch(e){ document.getElementById('mode').textContent='disconnected'; document.getElementById('dot').className='dot err'; return; }
  const dot=document.getElementById('dot');
  dot.className='dot '+(d.mode==='LIVE'?'live':(d.mode==='DEMO'?'demo':'err'));
  document.getElementById('mode').textContent=d.mode+(d.mode==='DEMO'?' (synthetic)':'');
  document.getElementById('upd').textContent=new Date(d.updated).toLocaleTimeString();

  const L=d.ledger;
  // Stable order by ticker so rows keep their position and only the numbers /
  // prediction update — they don't jump around as countdowns/edges change.
  const rows=(d.rows||[]).filter(r=>CAD==="all"||cadence(r)===CAD)
    .sort((a,b)=>a.ticker<b.ticker?-1:(a.ticker>b.ticker?1:0));
  const held=new Set((L&&L.open||[]).map(p=>p.ticker));
  const sigs=rows.filter(r=>r.rec&&r.rec.action!=='HOLD');
  document.getElementById('s-count').textContent=rows.length;
  document.getElementById('s-sig').textContent=sigs.length;
  const best=rows.reduce((a,r)=>Math.max(a,r.edge||0),0);
  document.getElementById('s-edge').textContent=best>0?pct(best):'—';
  document.getElementById('s-bal').textContent=d.balance!=null?('$'+d.balance.toFixed(2)):'—';
  document.getElementById('s-open').textContent=L?L.open_count:0;

  const tb=document.getElementById('rows'); closeTimes={};
  tb.innerHTML=rows.length?rows.map(r=>{
    closeTimes[r.ticker]=new Date(r.close_time).getTime();
    const rc=r.rec||{action:'HOLD',side:'',conf:0,reasons:[]};
    const why=(rc.reasons||[]).join(' · ').replace(/"/g,'&quot;');
    const rec=rc.action==='HOLD'
      ? '<span class="chip flat" title="'+why+'">HOLD</span>'
      : '<span class="chip '+rc.side+'" title="'+why+'">'+rc.action+' <b>'+rc.conf+'%</b></span>';
    const edge=r.edge>0?('<span class="edge pos">'+pct(r.edge)+'</span>'):'<span class="mut">—</span>';
    const btn=VIEW_ONLY?''
      :(held.has(r.ticker)?'<button class="take held" disabled>✓ holding</button>'
      :'<button class="take" onclick="take(\''+r.ticker+'\',\''+r.lean_side+'\','+r.lean_ask+')">Take '+r.lean_side.toUpperCase()+' $'+r.lean_ask.toFixed(2)+'</button>');
    return '<tr data-t="'+r.ticker+'" class="'+(rc.side?'sig '+rc.side:'')+'">'
      +'<td class="l">'+r.title+'</td><td><span class="coin">'+r.coin+'</span></td>'
      +'<td class="book"><span>'+fmtC(r.yes_bid)+'</span> / '+fmtC(r.yes_ask)+'</td>'
      +'<td class="book"><span>'+fmtC(r.no_bid)+'</span> / '+fmtC(r.no_ask)+'</td>'
      +'<td>'+fmtC(r.last)+'</td><td class="mut">'+fmtVol(r.volume)+'</td>'
      +'<td class="cdcell">'+countdown(closeTimes[r.ticker])+'</td><td>'+edge+'</td>'
      +'<td>'+rec+'</td><td class="l tradecol">'+btn+'</td></tr>';
  }).join(''):'<tr><td class="l mut" colspan="10">No open up/down crypto markets right now.</td></tr>';

  // ledger
  if(L && !VIEW_ONLY){
    document.getElementById('pnlbar').style.display=(L.open.length||L.closed.length)?'flex':'none';
    const set=(id,v)=>{const e=document.getElementById(id);e.textContent=signed(v);e.className=(id==='p-net'?'num ':'v ')+(v>=0?'up':'down');};
    set('p-net',L.net);set('p-real',L.realized);set('p-unreal',L.unreal);
    document.getElementById('p-wl').textContent=L.wins+'–'+L.losses;
    document.getElementById('p-wr').textContent=L.win_rate;
    const lb=document.getElementById('ledger');
    const items=L.open.map(p=>({...p,st:'open'})).concat(L.closed.map(p=>({...p,st:p.won?'won':'lost'})));
    lb.innerHTML=items.length?items.map(p=>{
      const now=p.st==='open'?fmtC(p.now):(p.result?p.result.toUpperCase():'—');
      const pnl=p.st==='open'?signed(p.unreal):signed(p.pnl);
      const cls=p.st==='won'?'up':(p.st==='lost'?'down':(pnl[0]==='+'?'up':'down'));
      const badge='<span class="badge '+p.st+'">'+(p.st==='won'?'WON':p.st==='lost'?'LOST':'OPEN')+'</span>';
      return '<tr><td class="l">'+p.coin+' '+p.side.toUpperCase()+' · '+p.ticker+'</td>'
        +'<td><span class="chip '+p.side+'">'+p.side.toUpperCase()+'</span></td>'
        +'<td>'+fmtC(p.entry)+'</td><td>$'+(p.entry*p.qty).toFixed(2)+'</td><td>'+p.qty+'</td><td>'+now+'</td>'
        +'<td class="'+cls+'">'+pnl+'</td><td class="l">'+badge+'</td></tr>';
    }).join(''):'<tr><td class="empty l" colspan="8">No trades yet — click <b>Take</b> on a market above.</td></tr>';
  }
  const f=document.getElementById('foot');
  f.innerHTML=d.error?('<span class="err">API note: '+d.error+'</span>')
    :(rows.length+' markets · '+sigs.length+' suggestion(s) · <b>Suggestion</b> = trend + momentum + distance-to-strike + volatility + time (hover for the reasons). A heuristic read of price action, <b>not</b> a guarantee.'
      +(d.mode==='DEMO'?' · <span class="warn">demo trades don\'t settle — use LIVE for win/loss P&L</span>':''));
}
load(); setInterval(load,REFRESH);
</script>
</body></html>"""


if __name__ == "__main__":
    main()
