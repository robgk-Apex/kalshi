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
        # Chart bullish and the market agrees (priced ~68% YES) -> YES.
        r = recommend(indicators_from_series(rising(), 103), 0.68, 0.34, 1.0)
        self.assertIn(r.action, ("YES", "LEAN YES"))
        self.assertEqual(r.side, "yes")
        self.assertGreater(r.confidence, 40)
        self.assertTrue(r.reasons)

    def test_bearish_predicts_no(self):
        r = recommend(indicators_from_series(falling(), 105), 0.32, 0.68, 1.0)
        self.assertIn(r.action, ("NO", "LEAN NO"))
        self.assertEqual(r.side, "no")
        self.assertGreater(r.confidence, 40)

    def test_market_odds_anchor_the_call(self):
        # A flat chart but a market priced strongly YES -> predict YES; strongly
        # NO -> predict NO. The market's own odds are the base forecast.
        flat = [100 + (0.05 if i % 2 else -0.05) for i in range(30)]
        ind = indicators_from_series(flat, 100)
        yes_mkt = recommend(ind, 0.85, 0.17, 1.0)   # market ~84% YES
        self.assertEqual(yes_mkt.side, "yes")
        no_mkt = recommend(ind, 0.15, 0.87, 1.0)    # market ~14% YES
        self.assertEqual(no_mkt.side, "no")

    def test_ev_flags_overpriced(self):
        # A near-coin-flip bought at a rich ask is negative expected value.
        flat = [100 + (0.05 if i % 2 else -0.05) for i in range(30)]
        r = recommend(indicators_from_series(flat, 100), 0.85, 0.17, 1.0)
        self.assertLess(r.ev, 0.0)
        self.assertTrue(any("EV" in s for s in r.reasons))

    def test_flat_market_still_leans(self):
        # A near-coin-flip with data still commits to a side (never a toss-up).
        flat = [100 + (0.05 if i % 2 else -0.05) for i in range(30)]
        r = recommend(indicators_from_series(flat, 100), 0.5, 0.5, 1.0)
        self.assertIn(r.action, ("YES", "NO", "LEAN YES", "LEAN NO"))
        self.assertIn(r.side, ("yes", "no"))

    def test_only_missing_data_is_non_directional(self):
        r = recommend(None, 0.5, 0.5, 1.0)
        self.assertEqual(r.action, "NO DATA")
        self.assertEqual(r.side, "")
        self.assertEqual(r.confidence, 0)

    def test_chart_can_tilt_but_market_leads(self):
        # With no market prices, the chart alone drives the call...
        ind = indicators_from_series(rising(), 103)
        chart_only = recommend(ind)
        self.assertEqual(chart_only.side, "yes")
        # ...but a market priced hard the other way pulls the blend toward it.
        against = recommend(ind, 0.08, 0.94, 1.0)   # market ~7% YES
        self.assertLess(against.probability, chart_only.probability)

    def test_weak_conviction_is_labelled_lean(self):
        # Below the decision threshold we still pick a side, just label it LEAN.
        ind = indicators_from_series(rising(), 103)
        r = recommend(ind, 0.5, 0.5, 1.0)
        if r.confidence < DECISION_THRESHOLD:
            self.assertTrue(r.action.startswith("LEAN"))
        else:
            self.assertIn(r.action, ("YES", "NO"))
        self.assertIn(r.side, ("yes", "no"))

    def test_probability_matches_side(self):
        # Probability and side are consistent, and it always commits with data.
        up = recommend(indicators_from_series(rising(), 103))
        self.assertGreaterEqual(up.probability, 0.5)
        self.assertEqual(up.side, "yes")
        down = recommend(indicators_from_series(falling(), 105))
        self.assertLess(down.probability, 0.5)
        self.assertEqual(down.side, "no")


if __name__ == "__main__":
    unittest.main()
