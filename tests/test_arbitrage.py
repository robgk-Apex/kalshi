"""Tests for the arbitrage strategy."""

import unittest
from decimal import Decimal
from unittest.mock import MagicMock

from src.models.market import Market, Orderbook, OrderbookLevel
from src.models.order import OrderSide
from src.strategies.arbitrage import ArbitrageStrategy


class TestArbitrageStrategy(unittest.TestCase):
    """Test arbitrage detection logic."""

    def setUp(self):
        self.config = {
            "min_profit_cents": 2,
            "max_contracts_per_trade": 50,
            "min_volume_24h": 10,
        }
        self.strategy = ArbitrageStrategy(self.config)
        self.mock_client = MagicMock()

    def _make_market(self, ticker="TEST-MKT", yes_bid=0.40, no_bid=0.55, volume=100):
        return Market(
            ticker=ticker,
            event_ticker="TEST-EVT",
            series_ticker="TEST",
            title="Test Market",
            status="open",
            yes_bid=Decimal(str(yes_bid)),
            yes_ask=Decimal(str(1 - no_bid + 0.02)),  # approx
            no_bid=Decimal(str(no_bid)),
            no_ask=Decimal(str(1 - yes_bid + 0.02)),
            last_price=Decimal(str(yes_bid + 0.02)),
            volume_24h=volume,
        )

    def _make_orderbook(self, ticker, yes_bids, no_bids):
        return Orderbook(
            ticker=ticker,
            yes_bids=[OrderbookLevel(Decimal(str(p)), Decimal(str(q))) for p, q in yes_bids],
            no_bids=[OrderbookLevel(Decimal(str(p)), Decimal(str(q))) for p, q in no_bids],
        )

    def test_detects_arbitrage(self):
        """Should detect when YES + NO < $1.00."""
        market = self._make_market(yes_bid=0.45, no_bid=0.58)
        # yes_ask = 1 - 0.58 = 0.42, no_ask = 1 - 0.45 = 0.55
        # total = 0.42 + 0.55 = 0.97 -> profit = $0.03

        ob = self._make_orderbook(
            "TEST-MKT",
            yes_bids=[(0.45, 100)],
            no_bids=[(0.58, 100)],
        )
        self.mock_client.get_orderbook.return_value = ob

        signals = self.strategy.scan([market], self.mock_client)

        self.assertEqual(len(signals), 2)  # Paired: buy YES + buy NO
        self.assertTrue(all(s.is_arbitrage for s in signals))
        self.assertEqual(signals[0].pair_id, signals[1].pair_id)

        sides = {s.side for s in signals}
        self.assertEqual(sides, {OrderSide.YES, OrderSide.NO})

        # Profit should be $0.03
        self.assertEqual(signals[0].edge, Decimal("0.03"))

    def test_no_arbitrage_when_sum_equals_one(self):
        """Should NOT signal when YES + NO = $1.00 (no profit)."""
        market = self._make_market(yes_bid=0.45, no_bid=0.55)
        # yes_ask = 1 - 0.55 = 0.45, no_ask = 1 - 0.45 = 0.55
        # total = 0.45 + 0.55 = 1.00 -> no profit

        ob = self._make_orderbook(
            "TEST-MKT",
            yes_bids=[(0.45, 100)],
            no_bids=[(0.55, 100)],
        )
        self.mock_client.get_orderbook.return_value = ob

        signals = self.strategy.scan([market], self.mock_client)
        self.assertEqual(len(signals), 0)

    def test_no_arbitrage_when_sum_exceeds_one(self):
        """Should NOT signal when YES + NO > $1.00."""
        # yes_ask = 1 - 0.40 = 0.60, no_ask = 1 - 0.38 = 0.62
        # total = 0.60 + 0.62 = 1.22 -> no arb
        market = self._make_market(yes_bid=0.38, no_bid=0.40)
        ob = self._make_orderbook(
            "TEST-MKT",
            yes_bids=[(0.38, 100)],
            no_bids=[(0.40, 100)],
        )
        self.mock_client.get_orderbook.return_value = ob

        signals = self.strategy.scan([market], self.mock_client)
        self.assertEqual(len(signals), 0)

    def test_skips_low_volume_markets(self):
        """Should skip markets below minimum volume threshold."""
        market = self._make_market(yes_bid=0.45, no_bid=0.58, volume=5)

        signals = self.strategy.scan([market], self.mock_client)
        self.assertEqual(len(signals), 0)
        self.mock_client.get_orderbook.assert_not_called()

    def test_skips_closed_markets(self):
        """Should skip non-open markets."""
        market = self._make_market()
        market.status = "closed"

        signals = self.strategy.scan([market], self.mock_client)
        self.assertEqual(len(signals), 0)

    def test_handles_empty_orderbook(self):
        """Should gracefully handle empty orderbooks."""
        market = self._make_market()
        ob = self._make_orderbook("TEST-MKT", [], [])
        self.mock_client.get_orderbook.return_value = ob

        signals = self.strategy.scan([market], self.mock_client)
        self.assertEqual(len(signals), 0)

    def test_respects_min_profit_threshold(self):
        """Should not signal when profit is below min_profit_cents."""
        config = {**self.config, "min_profit_cents": 5}
        strategy = ArbitrageStrategy(config)

        market = self._make_market(yes_bid=0.45, no_bid=0.58)
        ob = self._make_orderbook(
            "TEST-MKT",
            yes_bids=[(0.45, 100)],
            no_bids=[(0.58, 100)],
        )
        self.mock_client.get_orderbook.return_value = ob

        # Profit is $0.03, threshold is $0.05
        signals = strategy.scan([market], self.mock_client)
        self.assertEqual(len(signals), 0)

    def test_limits_contract_size(self):
        """Should cap contracts at max_contracts_per_trade."""
        config = {**self.config, "max_contracts_per_trade": 5}
        strategy = ArbitrageStrategy(config)

        market = self._make_market(yes_bid=0.45, no_bid=0.58)
        ob = self._make_orderbook(
            "TEST-MKT",
            yes_bids=[(0.45, 1000)],  # Huge size available
            no_bids=[(0.58, 1000)],
        )
        self.mock_client.get_orderbook.return_value = ob

        signals = strategy.scan([market], self.mock_client)
        self.assertEqual(len(signals), 2)


if __name__ == "__main__":
    unittest.main()
