"""Tests for the dashboard ledger (Take trade + active win/loss P&L)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import dashboard

LEDGER_FILE = os.path.join("logs", "dashboard_ledger.json")


class FakeSettleClient:
    """get_market returns a settled result for tickers we name, else active."""

    def __init__(self, results):
        self.results = results  # ticker -> "yes"/"no"

    def get_market(self, ticker):
        r = self.results.get(ticker)
        if r:
            return {"market": {"status": "settled", "result": r}}
        return {"market": {"status": "active"}}


class TestLedger(unittest.TestCase):

    def setUp(self):
        self.L = dashboard.Ledger()
        self.L.clear()

    def tearDown(self):
        try:
            os.remove(LEDGER_FILE)
        except OSError:
            pass

    def test_open_position_is_not_a_loss(self):
        # Deploying cash into an open bet must NOT show as realized loss.
        self.L.take("KXBTCD-1-A", "yes", 0.40, 10)
        v = self.L.view({"KXBTCD-1-A": {"yes": 0.44, "no": 0.56}})
        self.assertEqual(v["open_count"], 1)
        self.assertEqual(v["realized"], 0)
        self.assertAlmostEqual(v["unreal"], 0.4, places=2)  # (0.44-0.40)*10

    def test_no_double_take_same_market(self):
        self.L.take("KXBTCD-1-A", "yes", 0.40, 10)
        self.L.take("KXBTCD-1-A", "yes", 0.40, 10)
        self.assertEqual(self.L.view({})["open_count"], 1)

    def test_settlement_books_win_and_loss(self):
        self.L.take("KXBTCD-1-A", "yes", 0.40, 10)   # settles yes -> win
        self.L.take("KXETHD-1-B", "no", 0.55, 10)    # settles yes -> loss
        self.L.settle(FakeSettleClient({"KXBTCD-1-A": "yes", "KXETHD-1-B": "yes"}))
        v = self.L.view({})
        self.assertEqual(v["open_count"], 0)
        # win: (1-0.40)*10 = +6.0 ; loss: -0.55*10 = -5.5 ; realized = +0.5
        self.assertAlmostEqual(v["realized"], 0.5, places=2)
        self.assertEqual((v["wins"], v["losses"]), (1, 1))
        self.assertEqual(v["win_rate"], "50%")

    def test_clear_empties_ledger(self):
        self.L.take("KXBTCD-1-A", "yes", 0.4, 10)
        self.L.clear()
        self.assertEqual(self.L.view({})["open_count"], 0)


class TestDemoProvider(unittest.TestCase):

    def tearDown(self):
        try:
            os.remove(LEDGER_FILE)
        except OSError:
            pass

    def test_snapshot_shape_and_crypto_only(self):
        p = dashboard.DemoProvider()
        p.ledger.clear()
        s = p.snapshot()
        self.assertEqual(s["mode"], "DEMO")
        self.assertGreater(len(s["rows"]), 0)
        for key in ("realized", "unreal", "net", "open", "closed", "win_rate"):
            self.assertIn(key, s["ledger"])
        # only directional crypto markets are surfaced
        self.assertTrue(all(r["ticker"].startswith("KX") for r in s["rows"]))


if __name__ == "__main__":
    unittest.main()
