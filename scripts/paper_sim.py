"""Offline paper-trade simulation for the short-term up/down crypto strategy.

Why this exists
---------------
Paper-trading against REAL Kalshi data requires network access to Kalshi plus
API keys, and it settles over real time (hours). This script instead drives the
*actual* bot components — MarketScanner, RiskManager, TradeExecutor (dry-run),
PaperTrader — over synthetic-but-realistic directional-crypto markets, with a
built-in settlement model, so you can watch the whole pipeline behave and see a
P&L result in seconds, with no network and no keys.

    python scripts/paper_sim.py --scenario mixed --cycles 200

What the bot actually trades on
-------------------------------
For crypto this scanner has no external fair-value model — its "edge" comes from
the market's own prices, chiefly when the LAST trade price diverges from the
current bid/ask. So the bot's profitability hinges entirely on whether that
divergence carries information. The scenarios make that explicit:

  efficient : tight books, last == mid. No divergence -> the bot mostly sits
              out. Expect ~0 trades and ~0 P&L.
  informed  : the last-price divergence points toward the TRUE settle odds
              (a real, if idealized, signal). Expect the bot to profit.
  noise     : the last-price divergence is pure noise, unrelated to the
              outcome. Expect the bot to lose (it pays the spread to chase
              meaningless prints) — an important warning about this heuristic.
  mixed     : half informed, half noise (the realistic, uncertain case).

IMPORTANT: synthetic markets are a controlled model, NOT a prediction of live
Kalshi behavior. The "edge" scenario only makes money because we injected a real
mispricing; a live market may or may not offer one. To paper-trade the REAL
markets, run the bot itself against Kalshi (needs your keys + network):

    python -m src --dry-run

Note: the sim disables the CryptoAnalyzer/probability gates (they need live
price feeds). Those gates only ever *block* trades, so the live bot trades a
subset of what the sim would.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import src.paper_trader as paper_trader_module
from src.scanner import MarketScanner
from src.risk_manager import RiskManager
from src.executor import TradeExecutor
from src.paper_trader import PaperTrader

# Coins we simulate, mapped to their Kalshi directional (up/down) series.
COINS = [
    ("BTC", "KXBTCD"),
    ("ETH", "KXETHD"),
    ("SOL", "KXSOLD"),
]


def _clamp(x, lo=0.02, hi=0.98):
    return max(lo, min(hi, x))


class SimClient:
    """Stand-in for KalshiClient that serves generated markets by series and
    settles them with a pre-drawn outcome."""

    def __init__(self):
        self._by_series: dict[str, list] = {}
        self._outcomes: dict[str, str] = {}  # ticker -> "yes"/"no"

    def set_cycle_markets(self, markets_by_series, outcomes):
        self._by_series = markets_by_series
        self._outcomes.update(outcomes)

    def get_events(self, **kwargs):
        series = kwargs.get("series_ticker")
        markets = self._by_series.get(series, []) if series else []
        return {"events": [{"markets": markets}], "cursor": ""}

    def get_markets(self, **kwargs):
        return {"markets": [], "cursor": ""}

    def get_balance(self):
        return {"balance": 0}

    def get_market(self, ticker):
        # Called by PaperTrader.check_settlements: report every known ticker as
        # settled with its drawn result.
        if ticker in self._outcomes:
            return {"market": {"status": "settled", "result": self._outcomes[ticker]}}
        return {"market": {"status": "active"}}


def make_market(rng, coin, series, cycle, idx, kind):
    """Generate one up/down crypto market and its (hidden) settle outcome.

    A tight, coherent order book is centered on a market-implied probability
    ``m``. The LAST trade price may diverge from the book by ``delta`` — that
    divergence is the only thing this scanner can trade on for crypto. ``kind``
    decides whether the divergence is informative:

      "efficient" : delta = 0            -> no signal, bot sits out
      "informed"  : last points at truth -> profitable signal
      "noise"     : last is random       -> money-losing signal

    Returns (market_dict, outcome) where outcome is "yes" or "no".
    """
    m = rng.uniform(0.35, 0.65)  # market-implied probability of YES

    if kind == "efficient":
        delta = 0.0
        p_true = _clamp(m + rng.gauss(0, 0.03))
    elif kind == "informed":
        delta = rng.choice([-0.15, 0.15])
        # True odds move the SAME way the last-price diverges (a real signal).
        p_true = _clamp(m + delta + rng.gauss(0, 0.03))
    else:  # noise
        delta = rng.choice([-0.15, 0.15])
        # Last price wanders but the outcome ignores it.
        p_true = _clamp(m + rng.gauss(0, 0.03))

    outcome = "yes" if rng.random() < p_true else "no"

    # Tight 2-cent books with a small overround so YES_ask + NO_ask > 1
    # (i.e. never a locked arbitrage — this is a realistic book).
    yes_bid = _clamp(m - 0.01)
    yes_ask = _clamp(m + 0.01)
    no_mid = (1.0 - m) + 0.02
    no_bid = _clamp(no_mid - 0.01)
    no_ask = _clamp(no_mid + 0.01)
    last = _clamp(m + delta)

    ticker = f"{series}-C{cycle:03d}-{coin}{idx}"
    close = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    market = {
        "ticker": ticker,
        "event_ticker": f"{series}-C{cycle:03d}",
        "title": f"{coin} up/down cycle {cycle}",
        "status": "active",
        "yes_bid_dollars": round(yes_bid, 2),
        "yes_ask_dollars": round(yes_ask, 2),
        "no_bid_dollars": round(no_bid, 2),
        "no_ask_dollars": round(no_ask, 2),
        "last_price_dollars": round(last, 2),
        "volume": rng.randint(150, 3000),
        "close_time": close,
    }
    return market, outcome


def build_scanner(client, config):
    scanner = MarketScanner(client, config)
    # The analyzer gates need live price feeds; disable them for the offline sim.
    scanner.crypto_analyzer = None
    scanner.weather_analyzer = None
    scanner.probability_checker = None
    return scanner


def run(scenario, cycles, seed, bankroll, verbose=True):
    rng = random.Random(seed)

    config = {
        "strategy": {
            "mode": "crypto_short",
            "min_edge": 0.05,
            "scan_interval": 30,
            "min_volume": 100,
            "max_hours_to_expiry": 2,
            "max_entry_price": 0.60,
        },
        "risk": {
            "bankroll": bankroll,
            "max_bet_pct": 0.05,
            "max_contracts": 20,
            "max_positions": 10,
            "stop_loss_pct": 0.20,
            "daily_loss_limit": bankroll,  # don't halt the sim on the daily limit
        },
    }

    client = SimClient()
    scanner = build_scanner(client, config)
    risk = RiskManager(config)
    risk.bankroll = bankroll
    risk.starting_bankroll = bankroll
    executor = TradeExecutor(client, risk, dry_run=True)

    # Keep the sim's paper state in a throwaway file so it never touches
    # logs/paper_trades.json.
    tmp = os.path.join(tempfile.gettempdir(), f"kalshi_paper_sim_{seed}.json")
    if os.path.exists(tmp):
        os.remove(tmp)
    paper_trader_module.PAPER_FILE = tmp
    paper = PaperTrader(starting_balance=bankroll)

    edges = []
    for cycle in range(1, cycles + 1):
        markets_by_series = {}
        outcomes = {}
        for coin, series in COINS:
            if scenario == "mixed":
                kind = rng.choice(["informed", "noise"])
            else:
                kind = scenario
            market, outcome = make_market(rng, coin, series, cycle, 0, kind)
            markets_by_series[series] = [market]
            outcomes[market["ticker"]] = outcome
        client.set_cycle_markets(markets_by_series, outcomes)

        # Scan -> size -> (paper) execute, exactly like the live loop's paper path.
        for opp in scanner.scan():
            result = executor.execute(opp)
            if result and result.get("status") == "dry_run":
                edges.append(opp.edge)
                paper.record_entry(opp.ticker, opp.side, result["contracts"], opp.market_price)

        # Settle everything drawn this cycle (holding to expiry) and free the
        # position slots so the sim can keep trading.
        before = set(paper.positions.keys())
        paper.check_settlements(client)
        for _ in before - set(paper.positions.keys()):
            risk.record_close()

    s = paper.summary()
    avg_edge = sum(edges) / len(edges) if edges else 0.0
    if os.path.exists(tmp):
        os.remove(tmp)
    if not verbose:
        return s
    print("=" * 60)
    print(f"  PAPER SIM — scenario={scenario}  cycles={cycles}  seed={seed}")
    print("=" * 60)
    print(f"  Starting balance : ${s['starting_balance']:.2f}")
    print(f"  Ending balance   : ${s['current_balance']:.2f}")
    print(f"  Total P&L        : ${s['total_pnl']:+.2f} "
          f"({s['total_pnl'] / s['starting_balance'] * 100:+.1f}%)")
    print(f"  Trades taken     : {s['total_trades']}")
    print(f"  Settled W/L      : {s['wins']}/{s['losses']}  (win rate {s['win_rate']})")
    print(f"  Open at end      : {s['open_positions']}")
    print(f"  Avg entry edge   : {avg_edge:.3f}")
    print("=" * 60)
    if os.path.exists(tmp):
        os.remove(tmp)
    return s


def main():
    parser = argparse.ArgumentParser(description="Offline paper-trade simulation")
    parser.add_argument("--scenario",
                        choices=["efficient", "informed", "noise", "mixed"],
                        default="mixed")
    parser.add_argument("--cycles", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--bankroll", type=float, default=1000.0)
    args = parser.parse_args()
    run(args.scenario, args.cycles, args.seed, args.bankroll)


if __name__ == "__main__":
    main()
