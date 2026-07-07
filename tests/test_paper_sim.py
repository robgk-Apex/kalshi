"""Smoke + sanity tests for the offline paper-trade simulation.

These lock in the *shape* of the result (not exact P&L, which is random):
- an efficient market with no signal is not traded;
- an informative signal is profitable;
- a pure-noise signal does far worse than the informative one (on average it
  loses money — the point of the sim).
"""

import os
import statistics
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import paper_sim


class TestPaperSim(unittest.TestCase):

    def test_efficient_market_is_not_traded(self):
        s = paper_sim.run("efficient", cycles=30, seed=1, bankroll=1000, verbose=False)
        self.assertEqual(s["total_trades"], 0)
        self.assertEqual(s["current_balance"], 1000)

    def test_informed_signal_is_profitable(self):
        s = paper_sim.run("informed", cycles=250, seed=1, bankroll=1000, verbose=False)
        self.assertGreater(s["total_trades"], 0)
        self.assertGreater(s["total_pnl"], 0)

    def test_noise_underperforms_informed_on_average(self):
        seeds = range(16)
        informed = statistics.mean(
            paper_sim.run("informed", cycles=250, seed=s, bankroll=1000,
                          verbose=False)["total_pnl"]
            for s in seeds
        )
        noise = statistics.mean(
            paper_sim.run("noise", cycles=250, seed=s, bankroll=1000,
                          verbose=False)["total_pnl"]
            for s in seeds
        )
        self.assertGreater(informed, 0)
        # Chasing noise is not a real edge: it does far worse than a real signal.
        self.assertLess(noise, informed / 4)


if __name__ == "__main__":
    unittest.main()
