"""Tests for the pricing calculator."""

import unittest
from decimal import Decimal

from src.models.market import Orderbook, OrderbookLevel
from src.models.order import OrderAction, OrderSide
from src.execution.pricing import PriceCalculator
from src.strategies.base import Signal


class TestPriceCalculator(unittest.TestCase):
    """Test smart limit price calculation."""

    def setUp(self):
        self.pricer = PriceCalculator({"limit_offset_cents": 1})

    def _make_signal(self, side=OrderSide.YES, action=OrderAction.BUY, price=0.50, is_arb=False):
        return Signal(
            ticker="TEST", side=side, action=action,
            target_price=Decimal(str(price)), edge=Decimal("0.05"),
            confidence=0.7, strategy_name="test", reason="test",
            is_arbitrage=is_arb,
        )

    def _make_orderbook(self, yes_bids, no_bids):
        return Orderbook(
            ticker="TEST",
            yes_bids=[OrderbookLevel(Decimal(str(p)), Decimal(str(q))) for p, q in yes_bids],
            no_bids=[OrderbookLevel(Decimal(str(p)), Decimal(str(q))) for p, q in no_bids],
        )

    def test_arb_uses_exact_price(self):
        """Arbitrage signals should use the exact target price."""
        signal = self._make_signal(price=0.42, is_arb=True)
        ob = self._make_orderbook([(0.40, 10)], [(0.55, 10)])
        price = self.pricer.calculate_limit_price(signal, ob)
        self.assertEqual(price, Decimal("0.42"))

    def test_buy_yes_wide_spread_offsets(self):
        """BUY YES with wide spread should bid below the ask."""
        signal = self._make_signal(side=OrderSide.YES, action=OrderAction.BUY, price=0.50)
        ob = self._make_orderbook(
            yes_bids=[(0.40, 10)],
            no_bids=[(0.55, 10)],  # yes_ask = 0.45
        )
        price = self.pricer.calculate_limit_price(signal, ob)
        # Should be yes_ask - offset = 0.45 - 0.01 = 0.44
        self.assertEqual(price, Decimal("0.44"))

    def test_buy_yes_tight_spread_crosses(self):
        """BUY YES with tight spread should cross at the ask."""
        signal = self._make_signal(side=OrderSide.YES, action=OrderAction.BUY, price=0.50)
        ob = self._make_orderbook(
            yes_bids=[(0.44, 10)],
            no_bids=[(0.55, 10)],  # yes_ask = 0.45, spread = 0.01
        )
        price = self.pricer.calculate_limit_price(signal, ob)
        # Spread is 0.01, should use the ask directly
        self.assertEqual(price, Decimal("0.45"))

    def test_clamps_to_valid_range(self):
        """Price should be clamped between $0.01 and $0.99."""
        signal = self._make_signal(price=0.005, is_arb=True)
        ob = self._make_orderbook([], [])
        price = self.pricer.calculate_limit_price(signal, ob)
        self.assertGreaterEqual(price, Decimal("0.01"))
        self.assertLessEqual(price, Decimal("0.99"))


if __name__ == "__main__":
    unittest.main()
