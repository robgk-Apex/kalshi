"""Tests for the outcome-prediction engine (src/signals.py)."""

import unittest

from src.signals import (indicators_from_series, recommend, strike_from_market,
                         DECISION_THRESHOLD)


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

    def test_bullish_predicts_yes(self):
        r = recommend(indicators_from_series(rising(), 103), 0.55, 0.47, 1.0)
        self.assertEqual(r.action, "YES")
        self.assertEqual(r.side, "yes")
        self.assertGreater(r.confidence, 50)
        self.assertTrue(r.reasons)

    def test_bearish_predicts_no(self):
        r = recommend(indicators_from_series(falling(), 105), 0.45, 0.55, 1.0)
        self.assertEqual(r.action, "NO")
        self.assertEqual(r.side, "no")
        self.assertGreater(r.confidence, 40)

    def test_rich_ask_still_predicts_yes(self):
        # A likely YES is called YES regardless of price — this is a prediction,
        # not a value/arbitrage judgment, so a $0.90 ask does NOT force a pass.
        r = recommend(indicators_from_series(rising(), 103), 0.90, 0.12, 1.0)
        self.assertEqual(r.action, "YES")
        self.assertFalse(any("too rich" in s for s in r.reasons))

    def test_flat_market_is_tossup(self):
        flat = [100 + (0.05 if i % 2 else -0.05) for i in range(30)]
        r = recommend(indicators_from_series(flat, 100), 0.5, 0.5, 1.0)
        self.assertEqual(r.action, "TOSS-UP")

    def test_no_data_is_tossup(self):
        r = recommend(None, 0.5, 0.5, 1.0)
        self.assertEqual(r.action, "TOSS-UP")
        self.assertEqual(r.confidence, 0)

    def test_price_does_not_change_the_call(self):
        # Same indicators, wildly different asks -> identical prediction & score.
        ind = indicators_from_series(rising(), 103)
        cheap = recommend(ind, 0.10, 0.92, 1.0)
        rich = recommend(ind, 0.92, 0.10, 1.0)
        self.assertEqual(cheap.action, rich.action)
        self.assertEqual(cheap.score, rich.score)

    def test_threshold_gates_tossup(self):
        # A weak lean (just under the decision threshold) stays TOSS-UP.
        ind = indicators_from_series(rising(), 103)
        r = recommend(ind, 0.5, 0.5, 1.0)
        if abs(r.score) < DECISION_THRESHOLD:
            self.assertEqual(r.action, "TOSS-UP")
        else:
            self.assertIn(r.action, ("YES", "NO"))


if __name__ == "__main__":
    unittest.main()
