"""Tests for the Kalshi trading bot.

These target the ACTIVE implementation reachable from `python -m src`:
the event-based, dollar-denominated MarketScanner plus the RiskManager and
TradeExecutor.
"""

import unittest
import sys
import os
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.scanner import MarketScanner, Opportunity
from src.risk_manager import RiskManager
from src.executor import TradeExecutor


# ── Mock client for testing ────────────────────────────
class MockClient:
    """Minimal stand-in for KalshiClient.

    The scanner discovers markets via get_events() with nested markets, so we
    serve our fixture markets from the first get_events() call (which the
    scanner makes while sweeping its crypto series) and empty responses after.
    """

    def __init__(self, markets=None, balance=10000):
        self._markets = markets or []
        self._balance = balance
        self._events_served = False
        self.orders_placed = []

    def get_events(self, **kwargs):
        if self._events_served:
            return {"events": [], "cursor": ""}
        self._events_served = True
        return {
            "events": [{"event_ticker": "TEST-EVENT", "markets": self._markets}],
            "cursor": "",
        }

    def get_markets(self, **kwargs):
        return {"markets": self._markets, "cursor": ""}

    def get_market(self, ticker):
        for m in self._markets:
            if m.get("ticker") == ticker:
                return {"market": m}
        return {"market": {}}

    def get_balance(self):
        return {"balance": self._balance}

    def place_order(self, **kwargs):
        self.orders_placed.append(kwargs)
        return {"order": {"order_id": "test-123", "status": "resting"}}


def _future_close(hours=2):
    """A settlement time inside the scanner's expiry window (dynamic so the
    fixture never goes stale)."""
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def make_market(ticker="TEST-YES", yes_bid=0.45, yes_ask=0.50, no_bid=0.45,
                no_ask=0.55, volume=500, last_price=0.48, hours_to_close=2):
    """Build a market dict in the dollar-denominated shape the scanner reads.

    Prices are in DOLLARS (0.00-1.00), matching Kalshi API v2 *_dollars fields.
    """
    return {
        "ticker": ticker,
        "event_ticker": "TEST-EVENT",
        "title": f"Test Market {ticker}",
        "status": "open",
        "yes_bid_dollars": yes_bid,
        "yes_ask_dollars": yes_ask,
        "no_bid_dollars": no_bid,
        "no_ask_dollars": no_ask,
        "last_price_dollars": last_price,
        "volume": volume,
        "close_time": _future_close(hours_to_close),
    }


DEFAULT_CONFIG = {
    "strategy": {"min_edge": 0.05, "scan_interval": 30, "min_volume": 100, "max_days_to_expiry": 30},
    "risk": {"bankroll": 100, "max_bet_pct": 0.05, "max_contracts": 20,
             "max_positions": 10, "stop_loss_pct": 0.20, "daily_loss_limit": 20},
}


# ── Scanner Tests ──────────────────────────────────────
def _make_scanner(client, config=None, gates=False):
    """Build a scanner. By default the real-world gates (crypto/weather/
    probability checkers) are disabled so tests exercise the core
    mispricing-detection logic deterministically."""
    scanner = MarketScanner(client, config or DEFAULT_CONFIG)
    if not gates:
        scanner.crypto_analyzer = None
        scanner.weather_analyzer = None
        scanner.probability_checker = None
    return scanner


class TestScanner(unittest.TestCase):

    def test_no_markets_returns_empty(self):
        client = MockClient(markets=[])
        scanner = _make_scanner(client)
        result = scanner.scan()
        self.assertEqual(result, [])

    def test_low_volume_filtered_out(self):
        market = make_market(volume=10)  # below min_volume=100
        client = MockClient(markets=[market])
        scanner = _make_scanner(client)
        result = scanner.scan()
        self.assertEqual(result, [])

    def test_expired_market_filtered_out(self):
        # Settlement in the past -> scanner should skip it entirely.
        market = make_market(hours_to_close=-5, yes_ask=0.40, no_ask=0.50)
        client = MockClient(markets=[market])
        scanner = _make_scanner(client)
        result = scanner.scan()
        self.assertEqual(result, [])

    def test_arbitrage_detected(self):
        # YES ask $0.40 + NO ask $0.50 = $0.90 < $1 = guaranteed profit.
        # Arbitrage is detected regardless of the gates.
        market = make_market(yes_ask=0.40, no_ask=0.50, yes_bid=0.35, no_bid=0.45)
        client = MockClient(markets=[market])
        scanner = _make_scanner(client)
        result = scanner.scan()
        self.assertGreater(len(result), 0)
        self.assertGreater(result[0].edge, 0)
        # Cheaper side is bought; here YES ($0.40) <= NO ($0.50).
        self.assertEqual(result[0].side, "yes")

    def test_no_arb_when_prices_sum_above_1(self):
        # YES ask $0.55 + NO ask $0.55 = $1.10 > $1 = no arb, tight spread,
        # fair value near mid -> no edge above a 0.10 threshold either.
        market = make_market(yes_ask=0.55, no_ask=0.55, yes_bid=0.52, no_bid=0.52,
                             last_price=0.53)
        client = MockClient(markets=[market])
        config = {**DEFAULT_CONFIG,
                  "strategy": {**DEFAULT_CONFIG["strategy"], "min_edge": 0.10}}
        scanner = _make_scanner(client, config)
        result = scanner.scan()
        self.assertEqual(len(result), 0)

    def test_edge_detection(self):
        # YES ask is $0.40 but last trade / cross-implied fair value sits
        # around $0.47, an edge above the 0.05 threshold on the YES side.
        market = make_market(yes_bid=0.38, yes_ask=0.40, no_bid=0.55, no_ask=0.62,
                             last_price=0.55, volume=500)
        client = MockClient(markets=[market])
        scanner = _make_scanner(client)
        result = scanner.scan()
        yes_opps = [o for o in result if o.side == "yes"]
        self.assertTrue(yes_opps, "expected an underpriced YES opportunity")
        self.assertGreaterEqual(yes_opps[0].edge, DEFAULT_CONFIG["strategy"]["min_edge"])


# ── Risk Manager Tests ─────────────────────────────────
class TestRiskManager(unittest.TestCase):

    def test_initial_state(self):
        rm = RiskManager(DEFAULT_CONFIG)
        self.assertFalse(rm.halted)
        self.assertEqual(rm.bankroll, 100)
        self.assertEqual(rm.daily_pnl, 0)

    def test_stop_loss_triggers(self):
        rm = RiskManager(DEFAULT_CONFIG)
        rm.bankroll = 75  # dropped 25%, threshold is 20%
        self.assertTrue(rm.check_halt())
        self.assertTrue(rm.halted)

    def test_daily_loss_limit(self):
        rm = RiskManager(DEFAULT_CONFIG)
        rm.daily_pnl = -25  # limit is -20
        self.assertTrue(rm.check_halt())

    def test_position_sizing_basic(self):
        rm = RiskManager(DEFAULT_CONFIG)
        contracts = rm.size_position(edge=0.10, price=0.50)
        self.assertIsNotNone(contracts)
        self.assertGreater(contracts, 0)
        self.assertLessEqual(contracts, 20)  # max_contracts

    def test_no_trade_when_halted(self):
        rm = RiskManager(DEFAULT_CONFIG)
        rm.halted = True
        contracts = rm.size_position(edge=0.10, price=0.50)
        self.assertIsNone(contracts)

    def test_max_positions_respected(self):
        rm = RiskManager(DEFAULT_CONFIG)
        rm.open_positions = 10  # at max
        contracts = rm.size_position(edge=0.10, price=0.50)
        self.assertIsNone(contracts)

    def test_reset_daily(self):
        rm = RiskManager(DEFAULT_CONFIG)
        rm.daily_pnl = -15
        rm.halted = True
        rm.reset_daily()
        self.assertFalse(rm.halted)
        self.assertEqual(rm.daily_pnl, 0)

    def test_update_bankroll_anchors_starting_bankroll(self):
        # Config placeholder bankroll is 100, but the real account has $5,000.
        # The first balance sync must re-anchor starting_bankroll to $5,000 so
        # the stop-loss measures against the real account, not the placeholder.
        rm = RiskManager(DEFAULT_CONFIG)
        self.assertEqual(rm.starting_bankroll, 100)
        rm.update_bankroll(500_000)  # cents -> $5,000
        self.assertEqual(rm.bankroll, 5000)
        self.assertEqual(rm.starting_bankroll, 5000)

    def test_stop_loss_scales_with_real_balance(self):
        # With a $5,000 real starting balance and 20% stop, a drop to $3,900
        # (-22%) must halt; a drop to only $4,500 (-10%) must not.
        rm = RiskManager(DEFAULT_CONFIG)
        rm.update_bankroll(500_000)  # anchors starting_bankroll = $5,000
        rm.bankroll = 4500
        self.assertFalse(rm.check_halt())
        rm.bankroll = 3900
        self.assertTrue(rm.check_halt())

    def test_starting_bankroll_only_anchors_once(self):
        # Later balance syncs update bankroll but must NOT move the anchor.
        rm = RiskManager(DEFAULT_CONFIG)
        rm.update_bankroll(500_000)  # $5,000
        rm.update_bankroll(300_000)  # $3,000 later
        self.assertEqual(rm.bankroll, 3000)
        self.assertEqual(rm.starting_bankroll, 5000)


# ── Executor Tests ─────────────────────────────────────
class TestExecutor(unittest.TestCase):

    def _make_opp(self, edge=0.10, price=0.50):
        return Opportunity(
            ticker="TEST-YES", event_ticker="TEST", title="Test",
            side="yes", market_price=price, fair_price=price + edge,
            edge=edge, volume=500, yes_bid=0.48, yes_ask=price,
            no_bid=0.48, no_ask=0.52,
        )

    def test_dry_run_no_api_call(self):
        client = MockClient()
        rm = RiskManager(DEFAULT_CONFIG)
        executor = TradeExecutor(client, rm, dry_run=True)
        opp = self._make_opp()
        result = executor.execute(opp)
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(len(client.orders_placed), 0)

    def test_live_places_order(self):
        client = MockClient()
        rm = RiskManager(DEFAULT_CONFIG)
        executor = TradeExecutor(client, rm, dry_run=False)
        opp = self._make_opp()
        result = executor.execute(opp)
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "resting")
        self.assertEqual(len(client.orders_placed), 1)

    def test_summary_tracking(self):
        client = MockClient()
        rm = RiskManager(DEFAULT_CONFIG)
        executor = TradeExecutor(client, rm, dry_run=True)
        executor.execute(self._make_opp())
        executor.execute(self._make_opp())
        summary = executor.get_summary()
        self.assertEqual(summary["total_signals"], 2)
        self.assertEqual(summary["dry_run"], 2)


if __name__ == "__main__":
    unittest.main()
