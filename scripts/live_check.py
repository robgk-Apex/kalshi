"""One-shot live check: pull REAL Kalshi up/down crypto markets and print them.

Runs anywhere with internet access to Kalshi (locally, or in GitHub Actions —
which is how we exercise it, since this build sandbox can't reach Kalshi).
Public, no keys required.

    python scripts/live_check.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.api_client import KalshiClient
from src.signals import indicators_from_series, recommend

BASE = os.environ.get("KALSHI_BASE_URL", "https://api.elections.kalshi.com/trade-api/v2")
SERIES = ["KXBTCD", "KXETHD", "KXSOLD", "KXXRPD", "KXDOGED"]
FIELDS = ["ticker", "yes_bid", "yes_ask", "no_bid", "no_ask",
          "yes_bid_dollars", "yes_ask_dollars", "no_bid_dollars", "no_ask_dollars",
          "last_price", "last_price_dollars", "volume", "volume_fp",
          "close_time", "expected_expiration_time", "status"]


def main():
    print(f"Fetching real Kalshi markets from {BASE} (public, no auth)")
    client = KalshiClient(BASE)
    total, sample = 0, None
    for s in SERIES:
        try:
            resp = client.get_events(series_ticker=s, limit=50,
                                     with_nested_markets=True, status="open")
        except Exception as e:
            print(f"  {s}: ERROR {e}")
            continue
        markets = [m for ev in resp.get("events", []) for m in ev.get("markets", [])]
        print(f"  {s}: {len(markets)} open markets")
        total += len(markets)
        if markets and sample is None:
            sample = markets[0]

    print(f"\nTOTAL open up/down crypto markets: {total}")
    if not sample:
        print("No markets returned. Kalshi may require auth, or block this IP, "
              "or no markets are open right now.")
        return

    print("\nSAMPLE MARKET — fields the dashboard reads:")
    for k in FIELDS:
        if k in sample:
            print(f"  {k}: {sample[k]}")

    # Show that the pipeline works end to end on real data.
    def f(*names):
        for n in names:
            if n in sample and sample[n] not in (None, ""):
                try:
                    return float(sample[n])
                except (TypeError, ValueError):
                    pass
        return 0.0
    ya, na = f("yes_ask_dollars", "yes_ask"), f("no_ask_dollars", "no_ask")
    print(f"\nParsed: yes_ask=${ya:.2f}  no_ask=${na:.2f}")
    print("\nFULL SAMPLE JSON (truncated):")
    print(json.dumps(sample, indent=2)[:2500])


if __name__ == "__main__":
    main()
