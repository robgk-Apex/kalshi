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
        # Refresh Kalshi in the background so every /api/markets request returns
        # instantly from cache — the browser's 1s polling never waits on (or
        # piles up behind) the multi-second crawl. Critical on small hosts.
        self._thread = threading.Thread(target=self._refresh_loop, daemon=True)
        self._thread.start()

    def _refresh_loop(self):
        while True:
            try:
                try:
                    self.ledger.settle(self.client)
                except Exception:
                    pass
                snap = self._fetch()
                with self._lock:
                    self._cache = snap
                    self._cache_at = time.time()
            except Exception:
                pass
            time.sleep(max(1.0, self.min_interval))

    def snapshot(self):
        with self._lock:
            if self._cache:
                return self._cache
        # first background fetch hasn't landed yet — say so without erroring
        return {"mode": "LIVE", "error": "warming up — fetching live markets…",
                "balance": None, "rows": [], "ledger": None,
                "updated": datetime.now(timezone.utc).isoformat()}

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
        # crypto history is per-coin, so fetch it once per coin (not per row) —
        # cuts the price-feed calls from ~dozens to ~5 and keeps the crawl quick.
        pcache = {}
        for r in rows:
            coin = r["coin"]
            if coin not in pcache:
                pcache[coin] = self._prices_strike(r["ticker"])[0]
            apply_rec(r, pcache[coin], r.get("strike", 0))
            ph = pcache[coin]
            if ph:
                r["spot"] = ph[-1]   # current coin price, so strikes read in context
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
            # Prefer the strike-bearing subtitle ("$64,000 or above" / "Target
            # Price: $X") over the full market question so a price is always
            # present as a fallback for the client.
            "title": (m.get("subtitle") or m.get("yes_sub_title")
                      or m.get("title") or ticker),
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
            if not r.get("strike"):
                r["strike"] = strike
            if prices:
                r["spot"] = prices[-1]
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
<title>Kalshi Crypto Up/Down — Live Board</title>
<style>
  :root{
    --bg:#0d131e; --panel:#131c2a; --panel2:#1a2536; --line:#243248;
    --ink:#e9eef6; --muted:#8a97ab; --faint:#5f6f86;
    --accent:#4c8dff; --accent-ink:#0d131e;
    --yes:#2fbf71; --no:#f0616d; --hold:#93a1b6; --up:#2fbf71; --down:#f0616d;
    --radius:12px; --shadow:0 1px 0 rgba(255,255,255,.03), 0 8px 24px rgba(0,0,0,.35);
    --mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,monospace;
    --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  }
  @media (prefers-color-scheme: light){
    :root{--bg:#eef1f6;--panel:#fff;--panel2:#f4f7fb;--line:#dbe2ec;--ink:#16202e;
      --muted:#5b6b80;--faint:#8695ab;--accent:#2f6fe0;--accent-ink:#fff;
      --yes:#188a53;--no:#d33843;--hold:#6b7a90;
      --shadow:0 1px 2px rgba(20,32,50,.06), 0 10px 24px rgba(20,32,50,.08);}
  }
  :root[data-theme="dark"]{--bg:#0d131e;--panel:#131c2a;--panel2:#1a2536;--line:#243248;
    --ink:#e9eef6;--muted:#8a97ab;--faint:#5f6f86;--accent:#4c8dff;--accent-ink:#0d131e;
    --yes:#2fbf71;--no:#f0616d;--hold:#93a1b6;--shadow:0 1px 0 rgba(255,255,255,.03),0 8px 24px rgba(0,0,0,.35);}
  :root[data-theme="light"]{--bg:#eef1f6;--panel:#fff;--panel2:#f4f7fb;--line:#dbe2ec;--ink:#16202e;
    --muted:#5b6b80;--faint:#8695ab;--accent:#2f6fe0;--accent-ink:#fff;--yes:#188a53;--no:#d33843;--hold:#6b7a90;
    --shadow:0 1px 2px rgba(20,32,50,.06),0 10px 24px rgba(20,32,50,.08);}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:15px;line-height:1.45;-webkit-font-smoothing:antialiased}
  .wrap{max-width:1180px;margin:0 auto;padding:0 20px 64px}
  header{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
  .head{max-width:1180px;margin:0 auto;padding:14px 20px;display:flex;align-items:center;gap:16px;flex-wrap:wrap}
  .brand{display:flex;align-items:baseline;gap:10px}
  .brand h1{font-size:18px;margin:0;letter-spacing:-.01em;font-weight:680}
  .brand .tag{font-size:11px;text-transform:uppercase;letter-spacing:.14em;color:var(--muted)}
  .live{display:flex;align-items:center;gap:7px;font:600 12px/1 var(--mono);color:var(--muted)}
  .dot{width:8px;height:8px;border-radius:50%;background:var(--faint)}
  .dot.live{background:var(--up);box-shadow:0 0 0 0 color-mix(in srgb,var(--up) 60%,transparent);animation:pulse 2.4s infinite}
  .dot.demo{background:#f5a623} .dot.err{background:var(--no)}
  @keyframes pulse{0%{box-shadow:0 0 0 0 color-mix(in srgb,var(--up) 55%,transparent)}70%{box-shadow:0 0 0 7px transparent}100%{box-shadow:0 0 0 0 transparent}}
  .spacer{flex:1}
  .clock{font:600 13px/1 var(--mono);color:var(--ink)}
  .themebtn{background:var(--panel2);color:var(--muted);border:1px solid var(--line);border-radius:8px;padding:6px 10px;font-size:12px;cursor:pointer}
  .themebtn:hover{color:var(--ink)}
  .summary{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:20px 0}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:14px 16px;box-shadow:var(--shadow)}
  .card .k{font-size:11px;text-transform:uppercase;letter-spacing:.12em;color:var(--muted)}
  .card .v{font:660 24px/1.1 var(--mono);margin-top:8px;font-variant-numeric:tabular-nums}
  .card .s{font-size:12px;color:var(--faint);margin-top:5px}
  .pos{color:var(--up)} .neg{color:var(--down)}
  .controls{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:6px 0 14px}
  .seg{display:inline-flex;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:3px;gap:2px}
  .seg button{border:0;background:transparent;color:var(--muted);padding:7px 13px;border-radius:7px;font:600 13px var(--sans);cursor:pointer;white-space:nowrap}
  .seg button.on{background:var(--accent);color:var(--accent-ink)}
  .seg button:not(.on):hover{color:var(--ink);background:var(--panel2)}
  .count{font:600 12px var(--mono);color:var(--muted);margin-left:auto}
  .note{font-size:12px;color:var(--faint);margin:0 0 16px}
  .note b{color:var(--muted);font-weight:600}
  .tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:var(--radius);background:var(--panel);box-shadow:var(--shadow)}
  table{width:100%;border-collapse:collapse;min-width:920px}
  thead th{position:sticky;top:0;font-size:10.5px;text-transform:uppercase;letter-spacing:.11em;color:var(--muted);text-align:right;padding:11px 12px;background:var(--panel2);border-bottom:1px solid var(--line);font-weight:600;white-space:nowrap}
  thead th.l{text-align:left}
  tbody td{padding:11px 12px;border-bottom:1px solid var(--line);text-align:right;font-variant-numeric:tabular-nums;vertical-align:middle}
  tbody tr:last-child td{border-bottom:0}
  tbody tr:hover{background:color-mix(in srgb,var(--accent) 6%,transparent)}
  .mkt{text-align:left}
  .mkt .coin{display:inline-flex;align-items:center;gap:8px}
  .badge{font:700 11px/1 var(--mono);padding:4px 7px;border-radius:6px;background:var(--panel2);border:1px solid var(--line);color:var(--ink);min-width:44px;display:inline-block;text-align:center}
  .mkt .thresh{font-weight:640;font-variant-numeric:tabular-nums}
  .mkt .sub{color:var(--muted);font-size:12.5px;margin-top:3px}
  .cad{font:600 10.5px/1 var(--mono);text-transform:uppercase;letter-spacing:.06em;padding:4px 8px;border-radius:20px;border:1px solid var(--line);color:var(--muted);white-space:nowrap}
  .cad.c15{color:#c58bff;border-color:color-mix(in srgb,#c58bff 40%,var(--line))}
  .cadhourly{color:#4c8dff;border-color:color-mix(in srgb,#4c8dff 40%,var(--line))}
  .caddaily{color:#35c6a6;border-color:color-mix(in srgb,#35c6a6 40%,var(--line))}
  .cadweekly{color:#f5a623;border-color:color-mix(in srgb,#f5a623 40%,var(--line))}
  .px{font:600 14px var(--mono)}
  .px .ask{color:var(--ink)} .px .bidask{color:var(--faint);font-size:11.5px}
  .cd{font:600 13px var(--mono);color:var(--ink)} .cd.soon{color:var(--no)} .cd.done{color:var(--faint);font-size:11px;letter-spacing:.05em}
  .rec{display:inline-flex;flex-direction:column;align-items:flex-end;gap:5px}
  .pill{font:700 11.5px/1 var(--mono);letter-spacing:.03em;padding:5px 9px;border-radius:7px;white-space:nowrap}
  .pill.buyyes{color:var(--yes);background:color-mix(in srgb,var(--yes) 14%,transparent);border:1px solid color-mix(in srgb,var(--yes) 40%,transparent)}
  .pill.buyno{color:var(--no);background:color-mix(in srgb,var(--no) 14%,transparent);border:1px solid color-mix(in srgb,var(--no) 40%,transparent)}
  .pill.hold{color:var(--hold);background:color-mix(in srgb,var(--hold) 12%,transparent);border:1px solid color-mix(in srgb,var(--hold) 32%,transparent)}
  .conf{display:inline-flex;align-items:center;gap:6px}
  .confbar{width:52px;height:4px;border-radius:3px;background:var(--panel2);overflow:hidden}
  .confbar i{display:block;height:100%;background:var(--accent)}
  .confbar.buyyes i{background:var(--yes)} .confbar.buyno i{background:var(--no)}
  .confn{font:600 11px var(--mono);color:var(--muted)}
  .why{text-align:left;font-size:12px;color:var(--muted);max-width:300px;line-height:1.4}
  .why b{color:var(--ink);font-weight:600}
  .take{display:inline-flex;gap:6px;justify-content:flex-end}
  .take button{border:1px solid var(--line);background:var(--panel2);color:var(--ink);font:700 12px var(--mono);padding:7px 10px;border-radius:8px;cursor:pointer;transition:.12s}
  .take .y:hover{background:color-mix(in srgb,var(--yes) 22%,transparent);border-color:var(--yes);color:var(--yes)}
  .take .n:hover{background:color-mix(in srgb,var(--no) 22%,transparent);border-color:var(--no);color:var(--no)}
  .take button:active{transform:translateY(1px)}
  .posarea{margin-top:26px}
  .posarea h2{font-size:14px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);margin:0 0 12px;font-weight:600}
  .hcount{font:700 12px var(--mono);color:var(--faint);background:var(--panel2);border:1px solid var(--line);border-radius:20px;padding:2px 9px;margin-left:4px}
  .empty{color:var(--faint);font-size:13.5px;padding:18px;text-align:center;border:1px dashed var(--line);border-radius:var(--radius)}
  .postbl td .side{font:700 11px var(--mono);padding:3px 7px;border-radius:5px}
  .side.yes{color:var(--yes);background:color-mix(in srgb,var(--yes) 14%,transparent)}
  .side.no{color:var(--no);background:color-mix(in srgb,var(--no) 14%,transparent)}
  .res{font:700 11px var(--mono);padding:3px 7px;border-radius:5px}
  .res.win{color:var(--yes);background:color-mix(in srgb,var(--yes) 13%,transparent)}
  .res.loss{color:var(--no);background:color-mix(in srgb,var(--no) 13%,transparent)}
  .closebtn{border:1px solid var(--line);background:transparent;color:var(--muted);border-radius:7px;padding:5px 9px;font:600 11px var(--mono);cursor:pointer}
  .closebtn:hover{color:var(--no);border-color:var(--no)}
  .foot{margin-top:30px;font-size:12px;color:var(--faint);line-height:1.6}
  .foot code{font-family:var(--mono);background:var(--panel2);padding:1px 5px;border-radius:4px}
  .foot .err{color:var(--no)}
  body.viewonly .take,body.viewonly .posarea{display:none}
  @media (max-width:820px){.summary{grid-template-columns:repeat(2,1fr)}.head .clock{display:none}}
</style>
</head><body>
<header>
  <div class="head">
    <div class="brand"><h1>Crypto Up / Down</h1><span class="tag">Kalshi · live board</span></div>
    <span class="live"><span class="dot" id="dot"></span><span id="mode">connecting…</span></span>
    <div class="spacer"></div>
    <span class="clock" id="clock">--:--:--</span>
    <button class="themebtn" id="theme">◐ Theme</button>
  </div>
</header>
<div class="wrap">
  <section class="summary">
    <div class="card"><div class="k">Open positions</div><div class="v" id="nopen">0</div><div class="s" id="staked">$0 at risk</div></div>
    <div class="card"><div class="k">Unrealized P&amp;L</div><div class="v" id="upnl">$0.00</div><div class="s">mark-to-market vs mid</div></div>
    <div class="card"><div class="k">Realized P&amp;L</div><div class="v" id="rpnl">$0.00</div><div class="s">from settled &amp; closed</div></div>
    <div class="card"><div class="k">Total P&amp;L</div><div class="v" id="tpnl">$0.00</div><div class="s">unrealized + realized</div></div>
  </section>
  <div class="controls">
    <div class="seg" id="filter">
      <button data-c="all" class="on">All</button>
      <button data-c="15m">15-min</button>
      <button data-c="hourly">Hourly</button>
      <button data-c="daily">Daily</button>
      <button data-c="weekly">Weekly</button>
    </div>
    <span class="count" id="rowcount"></span>
  </div>
  <p class="note">Each row is one <b>price threshold</b> — will the coin be <b>at or above</b> that price
    at settlement? Hourly / daily / weekly list a whole <b>ladder of strikes</b> per coin (pick the price
    you want); 15-min is the single at-the-money target. Live Kalshi books, refreshed every second. <b id="src"></b>
    Suggestions are an educated read — <b>not advice</b>. Take a side to track <b>your own</b> P&amp;L
    (kept in your browser); it settles into realized P&amp;L at close.</p>
  <div class="tablewrap">
    <table>
      <thead><tr>
        <th class="l">Market</th><th class="l">Window</th><th>YES</th><th>NO</th>
        <th>Settles</th><th>Suggestion</th><th class="l">Why</th><th>Trade</th>
      </tr></thead>
      <tbody id="rows"><tr><td class="l" colspan="8" style="color:var(--faint);padding:18px">Loading live markets…</td></tr></tbody>
    </table>
  </div>
  <section class="posarea"><h2>Your positions</h2>
    <div id="posbox"><div class="empty">No positions yet — hit <b>YES</b> or <b>NO</b> on a market above.</div></div>
  </section>
  <section class="posarea" id="histbox"></section>
  <p class="foot" id="foot">
    Contracts settle at $1 (win) or $0 (loss). Entry uses the side's <b>ask</b>; unrealized P&amp;L =
    contracts × (mid − entry). Your positions and P&amp;L live in <b>this browser only</b> — each
    viewer has their own. Educational only; hourly/15-min crypto is close to a coin flip.
    <span style="opacity:.55">· board build: <b>ladder-2</b></span>
  </p>
</div>
<script>
const REFRESH=parseInt("__REFRESH__");
const VIEW_ONLY=__VIEWONLY__;
const LS="kalshi_pnl_v1";
let filter="all", closeTimes={}, rowsById={}, lastBook={}, seen=new Set(), order2=[];
let positions=[], settledHist=[], realized=0;
try{const s=JSON.parse(localStorage.getItem(LS)||"{}");
  positions=s.positions||[]; settledHist=s.settled||[]; realized=s.realized||0;}catch(e){}
function persist(){try{localStorage.setItem(LS,JSON.stringify({positions:positions,settled:settledHist,realized:realized}));}catch(e){}}

function money(n){return (n<0?"-":"")+"$"+Math.abs(n).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});}
function signedMoney(n){return (n>0?"+":n<0?"-":"")+"$"+Math.abs(n).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});}
const cadence=r=>/15M/.test(r.ticker)?"15m":(r.hours_left<=1.5?"hourly":r.hours_left<=48?"daily":"weekly");
const CAD_LABEL={"15m":"15-MIN",hourly:"HOURLY",daily:"DAILY",weekly:"WEEKLY"};
const CAD_CLASS={"15m":"c15",hourly:"cadhourly",daily:"caddaily",weekly:"cadweekly"};
const CAD_ORD={"15m":0,hourly:1,daily:2,weekly:3};
function is15(tk){return /15M/.test(tk);}
function fmtStrike(coin,v){v=+v||0;
  if(coin==="XRP"||coin==="DOGE") return "$"+v.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:5});
  return "$"+v.toLocaleString(undefined,{maximumFractionDigits:0});}
// Headline is the PRICE THRESHOLD (coin shown separately in the badge). Hourly/
// daily/weekly list a whole ladder of these strikes; 15-min is the one target.
function priceFromTitle(t){const m=String(t||"").match(/\$?\s*([0-9][0-9,]*\.?[0-9]*)/);
  return m?parseFloat(m[1].replace(/,/g,"")):0;}
function strikeOf(r){let s=+r.strike||0; if(s<=0) s=priceFromTitle(r.title); return s;}
function marketMain(r){const s=strikeOf(r);
  return s>0?("≥ "+fmtStrike(r.coin,s)):(((r.title||"").replace(/ or above.*/,""))||"up/down");}
function marketSub(r){
  if(!r.spot){return is15(r.ticker)?"target at close":"resolves at close";}
  const s=strikeOf(r), itm=(s>0&&r.spot>=s);
  return "spot "+fmtStrike(r.coin,r.spot)+(s>0?' <span class="'+(itm?"pos":"neg")+'">'+(itm?"(YES in the money)":"(NO in the money)")+"</span>":"");}
function bookMid(book,side){return side==="yes"?(book.yes_bid+book.yes_ask)/2:(book.no_bid+book.no_ask)/2;}
function curBook(tk){return rowsById[tk]||lastBook[tk]||null;}
function recClass(a){return a==="BUY YES"?"buyyes":a==="BUY NO"?"buyno":"hold";}

// ---- settlement: a held market that has left the live feed AND is past close
//      resolves at the market-implied outcome (last yes-mid >= 0.50 -> YES wins).
function settleClosed(feedSet){
  const now=Date.now(); let changed=false;
  for(let i=positions.length-1;i>=0;i--){
    const p=positions[i], ct=closeTimes[p.ticker];
    if(feedSet.has(p.ticker)) continue;          // still trading
    if(!ct || ct>now) continue;                  // not actually closed yet
    const b=curBook(p.ticker); const yesMid=b?bookMid(b,"yes"):0.5;
    const won=yesMid>=0.5?"yes":"no";
    const payout=(p.side===won)?p.contracts:0;
    realized+=payout-p.stake;
    settledHist.unshift({coin:p.coin,label:p.label,side:p.side,won:won,stake:p.stake,payout:payout,pnl:payout-p.stake});
    positions.splice(i,1); changed=true;
  }
  if(changed){persist(); renderPositions();}
}

let failCount=0;
async function poll(){
  let d;
  try{
    const ctl=new AbortController(); const to=setTimeout(function(){ctl.abort();},9000);
    const res=await fetch("/api/markets",{signal:ctl.signal}); clearTimeout(to);
    d=await res.json();
  }catch(e){
    failCount++; if(failCount>=3) setStatus("err","reconnecting…");
    return;   // keep showing the last good board; don't blank on one slow tick
  }
  failCount=0;
  setStatus(d.mode==="LIVE"?"live":(d.mode==="DEMO"?"demo":"err"),
            d.mode+(d.mode==="DEMO"?" (synthetic)":"")+" · "+new Date(d.updated).toLocaleTimeString());
  document.getElementById("src").textContent=d.error?("note: "+d.error):"";
  const rows=(d.rows||[]); const feed=new Set();
  rows.forEach(function(r){
    r._cad=cadence(r); feed.add(r.ticker);
    rowsById[r.ticker]=r; lastBook[r.ticker]=r;
    closeTimes[r.ticker]=new Date(r.close_time).getTime();
    if(!seen.has(r.ticker)){seen.add(r.ticker); order2.push(r.ticker);}
  });
  if(rows.length) settleClosed(feed);   // never settle off an empty warmup/error tick
  // group into a clean price ladder: cadence, then coin, then strike ascending
  // (so BTC's ≥$63,800 / ≥$63,900 / ≥$64,000 … read in order). Stable, no popping.
  const live=rows.slice().sort(function(a,b){
    if(CAD_ORD[a._cad]!==CAD_ORD[b._cad]) return CAD_ORD[a._cad]-CAD_ORD[b._cad];
    if(a.coin!==b.coin) return a.coin<b.coin?-1:1;
    const sa=strikeOf(a), sb=strikeOf(b); if(sa!==sb) return sa-sb;
    return a.ticker<b.ticker?-1:(a.ticker>b.ticker?1:0);
  });
  if(rows.length || !d.error) renderTable(live);  // don't wipe a good table while warming up
  renderPositions(); renderPnl();
}

function setStatus(cls,txt){document.getElementById("dot").className="dot "+cls;
  document.getElementById("mode").textContent=txt;}

function renderTable(live){
  const shownAll=live.length;
  const vis=live.filter(function(r){return filter==="all"||r._cad===filter;});
  document.getElementById("rowcount").textContent=vis.length+" of "+shownAll+" markets";
  const tb=document.getElementById("rows");
  if(!vis.length){tb.innerHTML='<tr><td class="l" colspan="8" style="color:var(--faint);padding:18px">No open '+(filter==="all"?"":filter+" ")+'markets right now.</td></tr>';return;}
  tb.innerHTML=vis.map(function(r){
    const rc=r.rec||{action:"HOLD",side:"",conf:0,reasons:[]};
    const cls=recClass(rc.action), conf=Math.max(0,Math.min(100,rc.conf||0));
    const why1=(rc.reasons&&rc.reasons[0])||"", whyRest=(rc.reasons||[]).slice(1,3).join(" · ");
    const wtag=is15(r.ticker)?'':'';
    const trade=VIEW_ONLY?'':'<div class="take">'
      +'<button class="y" onclick="take(\''+r.ticker+'\',\'yes\','+r.yes_ask+')">YES '+r.yes_ask.toFixed(2)+'</button>'
      +'<button class="n" onclick="take(\''+r.ticker+'\',\'no\','+r.no_ask+')">NO '+r.no_ask.toFixed(2)+'</button></div>';
    return '<tr data-t="'+r.ticker+'">'
      +'<td class="mkt"><span class="coin"><span class="badge">'+r.coin+'</span><span class="thresh">'+marketMain(r)+'</span></span>'
        +'<div class="sub">'+marketSub(r)+'</div></td>'
      +'<td class="mkt"><span class="cad '+CAD_CLASS[r._cad]+'">'+CAD_LABEL[r._cad]+'</span></td>'
      +'<td class="px"><span class="ask">'+r.yes_ask.toFixed(2)+'</span><div class="bidask">'+r.yes_bid.toFixed(2)+' / '+r.yes_ask.toFixed(2)+'</div></td>'
      +'<td class="px"><span class="ask">'+r.no_ask.toFixed(2)+'</span><div class="bidask">'+r.no_bid.toFixed(2)+' / '+r.no_ask.toFixed(2)+'</div></td>'
      +'<td><span class="cd cdcell">--</span></td>'
      +'<td><div class="rec"><span class="pill '+cls+'">'+rc.action+'</span>'
        +'<span class="conf"><span class="confbar '+cls+'"><i style="width:'+conf+'%"></i></span><span class="confn">'+conf+'</span></span></div></td>'
      +'<td class="why"><b>'+esc(why1)+'</b>'+(whyRest?'<br>'+esc(whyRest):'')+'</td>'
      +'<td>'+trade+'</td></tr>';
  }).join("");
  tickCountdowns();
}
function esc(s){return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");}

function tickCountdowns(){
  const now=Date.now();
  document.querySelectorAll("tr[data-t]").forEach(function(tr){
    const tk=tr.getAttribute("data-t"), cd=tr.querySelector(".cdcell"); if(!cd)return;
    const ms=(closeTimes[tk]||0)-now;
    if(ms<=0){cd.textContent="settling"; cd.className="cd cdcell done"; return;}
    const s=Math.floor(ms/1000),h=Math.floor(s/3600),m=Math.floor((s%3600)/60),ss=s%60;
    cd.textContent=h>0?(h+"h "+String(m).padStart(2,"0")+"m"):(m+":"+String(ss).padStart(2,"0"));
    cd.className="cd cdcell"+(ms<5*60000?" soon":"");
  });
}
function clockTick(){document.getElementById("clock").textContent=new Date().toLocaleTimeString(); tickCountdowns();}

// ---- trades (per-viewer, browser-local) ----
function take(tk,side,ask){
  if(VIEW_ONLY)return;
  const r=rowsById[tk]; if(!r){alert("Market no longer open.");return;}
  if(!(ask>0)){alert("No "+side.toUpperCase()+" ask on this market.");return;}
  const def=localStorage.getItem("kalshi_amt")||"25";
  const raw=prompt("How much to put on "+side.toUpperCase()+" — "+r.coin+" "+marketMain(r)+" at close?\nEntry $"+ask.toFixed(2)+" per contract. Enter stake in $:",def);
  if(raw===null)return; const stake=parseFloat(raw);
  if(!(stake>0)){alert("Enter a positive dollar amount.");return;}
  localStorage.setItem("kalshi_amt",Math.round(stake));
  positions.push({ticker:tk,coin:r.coin,label:marketMain(r),cad:r._cad,side:side,entry:ask,stake:stake,contracts:stake/ask});
  persist(); renderPositions(); renderPnl();
}
window.take=take;
function closePos(i){
  const p=positions[i]; if(!p)return;
  const b=curBook(p.ticker); const m=b?bookMid(b,p.side):p.entry, proceeds=p.contracts*m;
  realized+=proceeds-p.stake;
  settledHist.unshift({coin:p.coin,label:p.label,side:p.side,won:"closed",stake:p.stake,payout:proceeds,pnl:proceeds-p.stake});
  positions.splice(i,1); persist(); renderPositions(); renderPnl();
}
window.closePos=closePos;

function renderPositions(){
  const box=document.getElementById("posbox");
  if(!positions.length){box.innerHTML='<div class="empty">No positions yet — hit <b>YES</b> or <b>NO</b> on a market above.</div>'; renderHistory(); return;}
  let h='<div class="tablewrap"><table class="postbl"><thead><tr>'
    +'<th class="l">Market</th><th class="l">Side</th><th>Stake</th><th>Entry</th><th>Mid now</th><th>Value</th><th>P&amp;L</th><th></th></tr></thead><tbody>';
  positions.forEach(function(p,i){
    const b=curBook(p.ticker); const m=b?bookMid(b,p.side):p.entry, val=p.contracts*m, pnl=val-p.stake;
    const stale=rowsById[p.ticker]?"":' <span class="hcount">closing</span>';
    h+='<tr><td class="mkt"><span class="badge">'+p.coin+'</span> '+esc(p.label)+stale+'</td>'
      +'<td class="l"><span class="side '+p.side+'">'+p.side.toUpperCase()+'</span></td>'
      +'<td>'+money(p.stake)+'</td><td>'+p.entry.toFixed(2)+'</td><td>'+m.toFixed(2)+'</td><td>'+money(val)+'</td>'
      +'<td class="'+(pnl>=0?"pos":"neg")+'">'+signedMoney(pnl)+'</td>'
      +'<td><button class="closebtn" onclick="closePos('+i+')">Close</button></td></tr>';
  });
  h+='</tbody></table></div>'; box.innerHTML=h; renderHistory();
}
function renderHistory(){
  const box=document.getElementById("histbox");
  if(!settledHist.length){box.innerHTML=""; return;}
  let h='<h2>Settled <span class="hcount">'+settledHist.length+'</span></h2>'
    +'<div class="tablewrap"><table class="postbl"><thead><tr>'
    +'<th class="l">Market</th><th class="l">Side</th><th class="l">Result</th><th>Stake</th><th>Payout</th><th>P&amp;L</th></tr></thead><tbody>';
  settledHist.slice(0,40).forEach(function(s){
    const res=s.won==="closed"?"Closed early":(s.side===s.won?"Won":"Lost");
    h+='<tr><td class="mkt"><span class="badge">'+s.coin+'</span> '+esc(s.label)+'</td>'
      +'<td class="l"><span class="side '+s.side+'">'+s.side.toUpperCase()+'</span></td>'
      +'<td class="l"><span class="res '+(s.pnl>=0?"win":"loss")+'">'+res+'</span></td>'
      +'<td>'+money(s.stake)+'</td><td>'+money(s.payout)+'</td>'
      +'<td class="'+(s.pnl>=0?"pos":"neg")+'">'+signedMoney(s.pnl)+'</td></tr>';
  });
  h+='</tbody></table></div>'; box.innerHTML=h;
}
function setPnl(id,v){const e=document.getElementById(id);e.textContent=signedMoney(v);e.className="v "+(v>0?"pos":v<0?"neg":"");}
function renderPnl(){
  let staked=0,val=0;
  positions.forEach(function(p){const b=curBook(p.ticker);const m=b?bookMid(b,p.side):p.entry;staked+=p.stake;val+=p.contracts*m;});
  const upnl=val-staked, total=upnl+realized;
  document.getElementById("nopen").textContent=positions.length;
  document.getElementById("staked").textContent=money(staked)+" at risk";
  setPnl("upnl",upnl); setPnl("rpnl",realized); setPnl("tpnl",total);
}

document.getElementById("filter").addEventListener("click",function(e){
  const b=e.target.closest("button"); if(!b)return; filter=b.dataset.c;
  this.querySelectorAll("button").forEach(function(x){x.classList.toggle("on",x===b);});
  poll();
});
document.getElementById("theme").addEventListener("click",function(){
  const cur=document.documentElement.getAttribute("data-theme");
  const next=cur==="dark"?"light":(cur==="light"?"dark":(matchMedia("(prefers-color-scheme: dark)").matches?"light":"dark"));
  document.documentElement.setAttribute("data-theme",next);
});
if(VIEW_ONLY) document.body.classList.add("viewonly");
// self-scheduling loop: never start a new poll until the last one finishes,
// so slow ticks can't pile up and knock the connection over.
async function pollLoop(){ try{await poll();}catch(e){} setTimeout(pollLoop, REFRESH); }
renderPositions(); renderPnl(); clockTick(); pollLoop();
setInterval(clockTick,1000);
</script>
</body></html>"""


if __name__ == "__main__":
    main()
