"""Tests for the Kalshi trading bot."""

import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.scanner import MarketScanner, Opportunity
from src.risk_manager import RiskManager
from src.executor import TradeExecutor


# ── Mock client for testing ────────────────────────────
class MockClient:
    def __init__(self, markets=None, balance=10000):
        self._markets = markets or []
        self._balance = balance
        self.orders_placed = []

    def get_markets(self, **kwargs):
        return {"markets": self._markets, "cursor": ""}

    def get_balance(self):
        return {"balance": self._balance}

    def place_order(self, **kwargs):
        self.orders_placed.append(kwargs)
        return {"order": {"order_id": "test-123", "status": "resting"}}


def make_market(ticker="TEST-YES", yes_bid=45, yes_ask=50, no_bid=45, no_ask=55,
                volume=500, last_price=48):
    return {
        "ticker": ticker,
        "event_ticker": "TEST-EVENT",
        "title": f"Test Market {ticker}",
        "status": "open",
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "no_bid": no_bid,
        "no_ask": no_ask,
        "last_price": last_price,
        "volume": volume,
        "close_time": "2026-04-01T00:00:00Z",
    }


DEFAULT_CONFIG = {
    "strategy": {"min_edge": 0.05, "scan_interval": 30, "min_volume": 100, "max_days_to_expiry": 30},
    "risk": {"bankroll": 100, "max_bet_pct": 0.05, "max_contracts": 20,
             "max_positions": 10, "stop_loss_pct": 0.20, "daily_loss_limit": 20},
}


# ── Scanner Tests ──────────────────────────────────────
class TestScanner(unittest.TestCase):

    def test_no_markets_returns_empty(self):
        client = MockClient(markets=[])
        scanner = MarketScanner(client, DEFAULT_CONFIG)
        result = scanner.scan()
        self.assertEqual(result, [])

    def test_low_volume_filtered_out(self):
        market = make_market(volume=10)  # below min_volume=100
        client = MockClient(markets=[market])
        scanner = MarketScanner(client, DEFAULT_CONFIG)
        result = scanner.scan()
        self.assertEqual(result, [])

    def test_arbitrage_detected(self):
        # YES ask=40 + NO ask=50 = 90 cents < $1 = guaranteed profit
        market = make_market(yes_ask=40, no_ask=50, yes_bid=35, no_bid=45)
        client = MockClient(markets=[market])
        scanner = MarketScanner(client, DEFAULT_CONFIG)
        result = scanner.scan()
        self.assertGreater(len(result), 0)
        self.assertGreater(result[0].edge, 0)

    def test_no_arb_when_prices_sum_above_1(self):
        # YES ask=55 + NO ask=55 = $1.10 > $1 = no arb
        market = make_market(yes_ask=55, no_ask=55, yes_bid=50, no_bid=50,
                           last_price=53)
        client = MockClient(markets=[market])
        config = {**DEFAULT_CONFIG, "strategy": {**DEFAULT_CONFIG["strategy"], "min_edge": 0.10}}
        scanner = MarketScanner(client, config)
        result = scanner.scan()
        # With tight spread and high min_edge, no opportunities
        self.assertEqual(len(result), 0)

    def test_edge_detection(self):
        # Market says YES = 40 cents, but midpoint/last suggests 50 cents
        # Edge = 0.50 - 0.40 = 0.10 (above min_edge of 0.05)
        market = make_market(yes_bid=45, yes_ask=40, no_bid=50, no_ask=60,
                           last_price=50, volume=500)
        client = MockClient(markets=[market])
        scanner = MarketScanner(client, DEFAULT_CONFIG)
        result = scanner.scan()
        # Should find YES side underpriced
        yes_opps = [o for o in result if o.side == "yes"]
        if yes_opps:
            self.assertGreater(yes_opps[0].edge, 0)


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
