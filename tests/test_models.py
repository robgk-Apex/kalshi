"""Tests for data models (Market, Orderbook, Order, etc.)."""

import unittest
from decimal import Decimal
from datetime import datetime


class TestOrderbookModel(unittest.TestCase):
    """Test Orderbook data model and derived prices."""

    def _make_orderbook(self, yes_bids=None, no_bids=None):
        from src.models.market import Orderbook, OrderbookLevel
        return Orderbook(
            ticker="TEST-MARKET",
            yes_bids=[OrderbookLevel(Decimal(str(p)), Decimal(str(q))) for p, q in (yes_bids or [])],
            no_bids=[OrderbookLevel(Decimal(str(p)), Decimal(str(q))) for p, q in (no_bids or [])],
        )

    def test_best_yes_bid(self):
        ob = self._make_orderbook(yes_bids=[(0.45, 10), (0.43, 20)])
        self.assertEqual(ob.best_yes_bid, Decimal("0.45"))

    def test_best_no_bid(self):
        ob = self._make_orderbook(no_bids=[(0.55, 10), (0.53, 5)])
        self.assertEqual(ob.best_no_bid, Decimal("0.55"))

    def test_best_yes_ask_derived(self):
        """YES ask = 1 - best NO bid."""
        ob = self._make_orderbook(no_bids=[(0.55, 10)])
        self.assertEqual(ob.best_yes_ask, Decimal("0.45"))

    def test_best_no_ask_derived(self):
        """NO ask = 1 - best YES bid."""
        ob = self._make_orderbook(yes_bids=[(0.40, 10)])
        self.assertEqual(ob.best_no_ask, Decimal("0.60"))

    def test_spread(self):
        ob = self._make_orderbook(
            yes_bids=[(0.40, 10)],
            no_bids=[(0.55, 10)],
        )
        # yes_ask = 1 - 0.55 = 0.45, spread = 0.45 - 0.40 = 0.05
        self.assertEqual(ob.spread, Decimal("0.05"))

    def test_midpoint(self):
        ob = self._make_orderbook(
            yes_bids=[(0.40, 10)],
            no_bids=[(0.55, 10)],
        )
        # yes_bid=0.40, yes_ask=0.45, mid=0.425
        self.assertEqual(ob.midpoint, Decimal("0.425"))

    def test_empty_orderbook(self):
        ob = self._make_orderbook()
        self.assertIsNone(ob.best_yes_bid)
        self.assertIsNone(ob.best_no_bid)
        self.assertIsNone(ob.best_yes_ask)
        self.assertIsNone(ob.best_no_ask)
        self.assertIsNone(ob.spread)
        self.assertIsNone(ob.midpoint)

    def test_from_api_response(self):
        from src.models.market import Orderbook
        data = {
            "orderbook": {
                "yes": [[0.45, 100], [0.43, 200]],
                "no": [[0.58, 50], [0.55, 150]],
            }
        }
        ob = Orderbook.from_api_response("TEST", data)
        self.assertEqual(ob.ticker, "TEST")
        self.assertEqual(len(ob.yes_bids), 2)
        self.assertEqual(len(ob.no_bids), 2)
        self.assertEqual(ob.best_yes_bid, Decimal("0.45"))
        self.assertEqual(ob.best_no_bid, Decimal("0.58"))


class TestMarketModel(unittest.TestCase):
    """Test Market data model."""

    def test_from_api_response(self):
        from src.models.market import Market
        data = {
            "ticker": "HIGHNY-26MAR25-T55",
            "event_ticker": "HIGHNY-26MAR25",
            "series_ticker": "KXHIGHNY",
            "title": "Will NYC high exceed 55F?",
            "status": "open",
            "yes_bid": 0.42,
            "yes_ask": 0.48,
            "no_bid": 0.54,
            "no_ask": 0.60,
            "last_price": 0.45,
            "previous_price": 0.40,
            "volume_24h": 500,
            "open_interest": 1000,
        }
        m = Market.from_api_response(data)
        self.assertEqual(m.ticker, "HIGHNY-26MAR25-T55")
        self.assertEqual(m.status, "open")
        self.assertEqual(m.yes_bid, Decimal("0.42"))
        self.assertEqual(m.volume_24h, 500)

    def test_implied_yes_prob(self):
        from src.models.market import Market
        m = Market(
            ticker="T", event_ticker="E", series_ticker="S",
            title="Test", status="open",
            yes_bid=Decimal("0.40"), yes_ask=Decimal("0.50"),
        )
        self.assertEqual(m.implied_yes_prob, Decimal("0.45"))

    def test_spread_pct(self):
        from src.models.market import Market
        m = Market(
            ticker="T", event_ticker="E", series_ticker="S",
            title="Test", status="open",
            yes_bid=Decimal("0.40"), yes_ask=Decimal("0.50"),
        )
        # spread_pct = (0.50 - 0.40) / 0.50 = 0.20
        self.assertEqual(m.spread_pct, Decimal("0.2"))


class TestOrderModel(unittest.TestCase):
    """Test Order data model."""

    def test_order_to_api_body(self):
        from src.models.order import Order, OrderAction, OrderSide, OrderType
        order = Order(
            ticker="TEST-MKT",
            action=OrderAction.BUY,
            side=OrderSide.YES,
            order_type=OrderType.LIMIT,
            price_dollars=Decimal("0.45"),
            count=10,
        )
        body = order.to_api_body()
        self.assertEqual(body["ticker"], "TEST-MKT")
        self.assertEqual(body["action"], "buy")
        self.assertEqual(body["side"], "yes")
        self.assertEqual(body["type"], "limit")
        self.assertEqual(body["yes_price"], 45)  # cents
        self.assertEqual(body["count"], 10)
        self.assertIn("client_order_id", body)

    def test_order_no_side_price(self):
        from src.models.order import Order, OrderAction, OrderSide, OrderType
        order = Order(
            ticker="TEST",
            action=OrderAction.BUY,
            side=OrderSide.NO,
            order_type=OrderType.LIMIT,
            price_dollars=Decimal("0.60"),
            count=5,
        )
        body = order.to_api_body()
        self.assertIn("no_price", body)
        self.assertNotIn("yes_price", body)
        self.assertEqual(body["no_price"], 60)

    def test_order_is_open(self):
        from src.models.order import Order, OrderAction, OrderSide, OrderType, OrderStatus
        order = Order(
            ticker="T", action=OrderAction.BUY, side=OrderSide.YES,
            order_type=OrderType.LIMIT, price_dollars=Decimal("0.5"), count=1,
        )
        order.status = OrderStatus.RESTING
        self.assertTrue(order.is_open)
        self.assertFalse(order.is_complete)

        order.status = OrderStatus.FILLED
        self.assertFalse(order.is_open)
        self.assertTrue(order.is_complete)

    def test_remaining_count(self):
        from src.models.order import Order, OrderAction, OrderSide, OrderType
        order = Order(
            ticker="T", action=OrderAction.BUY, side=OrderSide.YES,
            order_type=OrderType.LIMIT, price_dollars=Decimal("0.5"), count=10,
        )
        order.filled_count = 3
        self.assertEqual(order.remaining_count, 7)


class TestBalanceModel(unittest.TestCase):
    """Test Balance data model."""

    def test_from_api_response_cents(self):
        from src.models.portfolio import Balance
        # Kalshi returns balance in cents
        data = {
            "available_balance": 500000,  # $5000.00
            "balance": 520000,            # $5200.00
            "payout": 20000,              # $200.00
        }
        b = Balance.from_api_response(data)
        self.assertEqual(b.available_dollars, Decimal("5000"))
        self.assertEqual(b.total_dollars, Decimal("5200"))


if __name__ == "__main__":
    unittest.main()
