"""Export a REAL Kalshi snapshot (near-term up/down crypto) as one JSON line.

Runs in CI (which can reach Kalshi + Coin- price feeds). Prints the snapshot
between markers so it can be lifted out of the job log and rendered into a
viewable board. Public — no keys.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.api_client import KalshiClient
from src.signals import indicators_from_series, recommend, strike_from_market

BASE = os.environ.get("KALSHI_BASE_URL", "https://api.elections.kalshi.com/trade-api/v2")
SERIES = [
    # 15-minute up/down (frequency=fifteen_min)
    ("BTC", "KXBTC15M"), ("ETH", "KXETH15M"), ("SOL", "KXSOL15M"),
    ("XRP", "KXXRP15M"), ("DOGE", "KXDOGE15M"),
    # hourly up/down (also lists near-term daily/weekly windows)
    ("BTC", "KXBTCD"), ("ETH", "KXETHD"), ("SOL", "KXSOLD"),
    ("XRP", "KXXRPD"), ("DOGE", "KXDOGED"),
]
MAX_ROWS = 60


def f(m, *names):
    for n in names:
        v = m.get(n)
        if v not in (None, ""):
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return 0.0


def hours_until(ts):
    if not ts:
        return 9999.0
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return max(0.0, (datetime.fromisoformat(ts) - datetime.now(timezone.utc)).total_seconds() / 3600)
    except Exception:
        return 9999.0


def main():
    client = KalshiClient(BASE)  # public
    try:
        from src.crypto_analyzer import CryptoAnalyzer
        analyzer = CryptoAnalyzer()
    except Exception:
        analyzer = None

    hist_cache = {}

    def prices_strike(coin, market):
        # Strike works across BOTH formats: hourly -T<price> ticker suffix AND
        # the 15-min floor_strike field / "Target Price: $X" title.
        strike = strike_from_market(market)
        if not analyzer or strike <= 0:
            return None, strike
        if coin not in hist_cache:
            ticker = market.get("ticker", "")
            cid, _ = analyzer._get_coin(ticker)
            hist = analyzer._get_history(cid) or [] if cid else []
            price = analyzer._get_price(cid) if cid else None
            series = [p for _t, p in hist]
            if price:
                series = series + [price]
            hist_cache[coin] = series
        return hist_cache[coin], strike

    # Pick near-the-money, actually-tradeable markets across ALL coins (not the
    # deep in/out-of-the-money strikes that sit at $0.00 / $1.00).
    per_coin = max(4, MAX_ROWS // len(SERIES))
    selected = []
    for i, (coin, series) in enumerate(SERIES):
        if i:
            time.sleep(0.4)  # throttle: Kalshi's public API rate-limits bursts
        try:
            resp = client.get_events(series_ticker=series, limit=200,
                                     with_nested_markets=True, status="open")
        except Exception as e:
            print(f"  {series}: ERROR {e}")
            continue
        cand = []
        n_markets = 0
        sample = None
        for ev in resp.get("events", []):
            for m in ev.get("markets", []):
                t = m.get("ticker", "")
                if not t:
                    continue
                n_markets += 1
                if sample is None:
                    sample = m
                ya = f(m, "yes_ask_dollars", "yes_ask")
                if not (0.08 <= ya <= 0.92):  # skip near-certain strikes
                    continue
                hrs = hours_until(m.get("expected_expiration_time") or m.get("close_time"))
                cand.append((hrs, abs(ya - 0.5), coin, series, m))
        # soonest to settle, then closest to a coin-flip (most interesting)
        cand.sort(key=lambda x: (x[0], x[1]))
        # Diagnostics — especially to confirm the 15-min (KX*15M) markets and
        # that a strike parses out of them.
        strk = strike_from_market(sample) if sample else 0.0
        print(f"  {series}: {len(resp.get('events', []))} events, "
              f"{n_markets} markets, {len(cand)} in-band; "
              f"sample strike={strk} ({(sample or {}).get('ticker','-')})")
        selected.extend(cand[:per_coin])
    selected.sort(key=lambda x: x[0])

    rows = []
    for hrs, _mid, coin, series, m in selected[:MAX_ROWS]:
        ya = f(m, "yes_ask_dollars", "yes_ask")
        yb = f(m, "yes_bid_dollars", "yes_bid")
        na = f(m, "no_ask_dollars", "no_ask")
        nb = f(m, "no_bid_dollars", "no_bid")
        last = f(m, "last_price_dollars", "last_price")
        vol = f(m, "volume_fp", "volume")
        prices, strike = prices_strike(coin, m)
        try:
            rec = recommend(indicators_from_series(prices, strike), ya, na, hrs)
            rec = {"action": rec.action, "side": rec.side, "conf": rec.confidence,
                   "reasons": rec.reasons}
        except Exception:
            rec = {"action": "HOLD", "side": "", "conf": 0, "reasons": ["no price data"]}
        bucket = 15 if hrs <= 0.3 else (30 if hrs <= 0.6 else 60)
        rows.append({
            "ticker": m["ticker"], "coin": coin,
            "title": m.get("subtitle") or m.get("yes_sub_title") or m.get("title", coin),
            "yes_bid": round(yb, 2), "yes_ask": round(ya, 2),
            "no_bid": round(nb, 2), "no_ask": round(na, 2),
            "last": round(last, 2), "volume": round(vol),
            "hours_left": round(hrs, 4), "bucket": bucket, "rec": rec,
        })

    payload = {"generated_at": datetime.now(timezone.utc).isoformat(),
               "source": BASE, "count": len(rows), "rows": rows}
    print(f"\nSnapshot: {len(rows)} near-term real markets")
    print("SNAPSHOT_JSON " + json.dumps(payload, separators=(",", ":")))


if __name__ == "__main__":
    main()
