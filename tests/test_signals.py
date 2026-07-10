"""Tests for the educated buy/sell recommendation engine (src/signals.py)."""

import unittest

from src.signals import (indicators_from_series, recommend, strike_from_market,
                         MAX_ENTRY)


def rising(n=30, start=100.0, slope=0.25):
    return [start + i * slope for i in range(n)]


def falling(n=30, start=110.0, slope=0.3):
    return [start - i * slope for i in range(n)]


class TestIndicators(unittest.TestCase):

    def test_none_when_too_little_data(self):
        self.assertIsNone(indicators_from_series([1, 2, 3], 1))
        self.assertIsNone(indicators_from_series([], 1))

    def test_none_when_bad_strike(self):
        self.assertIsNone(indicators_from_series(rising(), 0))

    def test_distance_sign(self):
        ind = indicators_from_series(rising(), 103)  # ends ~107 above 103
        self.assertGreater(ind["distance"], 0)
        self.assertGreater(ind["trend_short"], 0)
        self.assertGreater(ind["momentum"], 0)


class TestStrikeFromMarket(unittest.TestCase):

    def test_hourly_ticker_suffix(self):
        # Hourly up/down markets encode the strike as a -T<price> suffix.
        m = {"ticker": "KXBTCD-25JUL0812-T48999.99"}
        self.assertAlmostEqual(strike_from_market(m), 48999.99)

    def test_fifteen_min_floor_strike_field(self):
        # 15-min markets carry it in floor_strike.
        m = {"ticker": "KXSOL15M-26JUL081900-00", "floor_strike": 77.3918,
             "title": "Target Price: $77.3918"}
        self.assertAlmostEqual(strike_from_market(m), 77.3918)

    def test_fifteen_min_title_fallback(self):
        # No structured field / T-suffix — parse the dollar amount in the title.
        m = {"ticker": "KXETH15M-26JUL081900-00",
             "title": "Ethereum above Target Price: $3,412.50 at 7:00pm?"}
        self.assertAlmostEqual(strike_from_market(m), 3412.50)

    def test_string_floor_strike(self):
        m = {"ticker": "X", "floor_strike": "1234.5"}
        self.assertAlmostEqual(strike_from_market(m), 1234.5)

    def test_no_strike_returns_zero(self):
        self.assertEqual(strike_from_market({"ticker": "KXBTC15M-FOO-00"}), 0.0)
        self.assertEqual(strike_from_market({}), 0.0)


class TestRecommend(unittest.TestCase):

    def test_bullish_recommends_buy_yes(self):
        r = recommend(indicators_from_series(rising(), 103), 0.55, 0.47, 1.0, edge=0.04)
        self.assertEqual(r.action, "BUY YES")
        self.assertEqual(r.side, "yes")
        self.assertGreater(r.confidence, 50)
        self.assertTrue(r.reasons)

    def test_bearish_recommends_buy_no(self):
        r = recommend(indicators_from_series(falling(), 105), 0.45, 0.55, 1.0)
        self.assertEqual(r.action, "BUY NO")
        self.assertEqual(r.side, "no")
        self.assertGreater(r.confidence, 40)

    def test_rich_ask_forces_hold(self):
        # Strong bullish read, but the YES contract is priced at $0.90 — no value.
        r = recommend(indicators_from_series(rising(), 103), 0.90, 0.12, 1.0)
        self.assertEqual(r.action, "HOLD")
        self.assertTrue(any("too rich" in s for s in r.reasons))

    def test_flat_market_holds(self):
        flat = [100 + (0.05 if i % 2 else -0.05) for i in range(30)]
        r = recommend(indicators_from_series(flat, 100), 0.5, 0.5, 1.0)
        self.assertEqual(r.action, "HOLD")

    def test_no_data_holds(self):
        r = recommend(None, 0.5, 0.5, 1.0)
        self.assertEqual(r.action, "HOLD")
        self.assertEqual(r.confidence, 0)

    def test_edge_boosts_confidence(self):
        ind = indicators_from_series(rising(), 103)
        base = recommend(ind, 0.55, 0.47, 1.0, edge=0.0).confidence
        boosted = recommend(ind, 0.55, 0.47, 1.0, edge=0.06).confidence
        self.assertGreaterEqual(boosted, base)

    def test_max_entry_boundary(self):
        # At exactly MAX_ENTRY a strong signal is still actionable.
        r = recommend(indicators_from_series(rising(), 103), MAX_ENTRY, 0.10, 1.0)
        self.assertEqual(r.action, "BUY YES")


if __name__ == "__main__":
    unittest.main()
