"""Discover Kalshi crypto series and their cadence (15-min / hourly / daily /
weekly). Runs in CI where Kalshi is reachable. Public, no keys.

Prints each crypto series ticker + title + frequency, plus the soonest open
market and its minutes-to-close so we can confirm the cadence.
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.api_client import KalshiClient

BASE = os.environ.get("KALSHI_BASE_URL", "https://api.elections.kalshi.com/trade-api/v2")
CRYPTO_HINTS = ("BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "HYPE", "CRYPTO", "BITCOIN", "ETHER")


def mins_to_soonest(client, series):
    try:
        resp = client.get_events(series_ticker=series, limit=100,
                                 with_nested_markets=True, status="open")
    except Exception as e:
        return f"(events error: {e})"
    soonest = None
    for ev in resp.get("events", []):
        for m in ev.get("markets", []):
            ts = m.get("expected_expiration_time") or m.get("close_time")
            if not ts:
                continue
            try:
                t = ts[:-1] + "+00:00" if ts.endswith("Z") else ts
                mins = (datetime.fromisoformat(t) - datetime.now(timezone.utc)).total_seconds() / 60
                if mins > 0 and (soonest is None or mins < soonest):
                    soonest = mins
            except Exception:
                pass
    return f"{soonest:.0f} min to soonest" if soonest else "(no open markets)"


def main():
    client = KalshiClient(BASE)
    series_list = []
    for cat in ("Crypto", "crypto", "Financials", "Financial"):
        try:
            resp = client._request("GET", "/series", params={"category": cat})
        except Exception as e:
            print(f"/series?category={cat}: {e}")
            continue
        got = resp.get("series", []) or []
        if got:
            print(f"/series?category={cat}: {len(got)} series")
            series_list = got
            break

    if not series_list:
        print("Could not list series by category; trying known crypto tickers.")
        series_list = [{"ticker": t} for t in
                       ("KXBTC", "KXBTCD", "KXETH", "KXETHD", "KXSOL", "KXSOLD",
                        "KXBTC15", "KXBTCMIN", "KXBTCW", "KXBTCWEEK")]

    print("\nCRYPTO SERIES (ticker | frequency | title | soonest market):")
    for s in series_list:
        tk = s.get("ticker", "")
        title = (s.get("title", "") or "")
        freq = s.get("frequency", "") or s.get("settlement_frequency", "")
        blob = (tk + " " + title).upper()
        if not any(h in blob for h in CRYPTO_HINTS):
            continue
        print(f"  {tk} | freq={freq!r} | {title[:48]} | {mins_to_soonest(client, tk)}")


if __name__ == "__main__":
    main()
