"""Tests for the risk management module."""

import unittest
from decimal import Decimal
from unittest.mock import MagicMock, PropertyMock

from src.models.order import OrderAction, OrderSide
from src.models.portfolio import Balance, Position
from src.strategies.base import Signal


class TestKellySizing(unittest.TestCase):
    """Test Kelly criterion position sizing."""

    def _make_risk_manager(self, **overrides):
        from src.risk.manager import RiskManager

        config = {
            "bankroll_dollars": 5000,
            "max_position_pct": 0.05,
            "max_total_exposure_pct": 0.40,
            "daily_loss_limit_pct": 0.05,
            "max_concurrent_positions": 20,
            "kelly_fraction": 0.25,
        }
        config.update(overrides)

        mock_client = MagicMock()
        mock_client.get_balance.return_value = Balance(
            available_dollars=Decimal("5000"),
            total_dollars=Decimal("5000"),
        )
        mock_client.get_positions.return_value = []

        rm = RiskManager(config, mock_client)
        rm.start_of_day_reset()
        return rm

    def _make_signal(self, price=0.50, edge=0.10, ticker="TEST"):
        return Signal(
            ticker=ticker,
            side=OrderSide.YES,
            action=OrderAction.BUY,
            target_price=Decimal(str(price)),
            edge=Decimal(str(edge)),
            confidence=0.7,
            strategy_name="test",
            reason="test signal",
        )

    def test_kelly_positive_edge(self):
        """Positive edge should produce a positive position size."""
        rm = self._make_risk_manager()
        signal = self._make_signal(price=0.50, edge=0.10)
        approved, size, reason = rm.check_signal(signal)
        self.assertTrue(approved)
        self.assertGreater(size, 0)

    def test_kelly_larger_edge_larger_size(self):
        """Larger edge should produce larger position."""
        rm = self._make_risk_manager()
        sig_small = self._make_signal(price=0.50, edge=0.05)
        sig_large = self._make_signal(price=0.50, edge=0.15)

        _, size_small, _ = rm.check_signal(sig_small)
        _, size_large, _ = rm.check_signal(sig_large)

        self.assertGreater(size_large, size_small)

    def test_quarter_kelly_smaller_than_full(self):
        """Quarter Kelly should size smaller than full Kelly would."""
        rm_quarter = self._make_risk_manager(kelly_fraction=0.25)
        rm_full = self._make_risk_manager(kelly_fraction=1.0)

        signal = self._make_signal(price=0.50, edge=0.10)

        _, size_quarter, _ = rm_quarter.check_signal(signal)
        _, size_full, _ = rm_full.check_signal(signal)

        self.assertLess(size_quarter, size_full)


class TestRiskLimits(unittest.TestCase):
    """Test risk limit enforcement."""

    def _make_risk_manager_with_positions(self, num_positions=0, total_exposure=0):
        from src.risk.manager import RiskManager

        config = {
            "bankroll_dollars": 5000,
            "max_position_pct": 0.05,
            "max_total_exposure_pct": 0.40,
            "daily_loss_limit_pct": 0.05,
            "max_concurrent_positions": 5,
            "kelly_fraction": 0.25,
        }

        mock_client = MagicMock()
        mock_client.get_balance.return_value = Balance(
            available_dollars=Decimal("5000"),
            total_dollars=Decimal("5000"),
        )

        # Create mock positions
        positions = []
        for i in range(num_positions):
            p = Position(
                ticker=f"MKT-{i}",
                side=OrderSide.YES,
                count=10,
                avg_entry_price=Decimal("0.50"),
                current_price=Decimal("0.50"),
            )
            positions.append(p)
        mock_client.get_positions.return_value = positions

        rm = RiskManager(config, mock_client)
        rm.start_of_day_reset()
        return rm

    def test_rejects_at_max_positions(self):
        """Should reject when max concurrent positions reached."""
        rm = self._make_risk_manager_with_positions(num_positions=5)

        signal = Signal(
            ticker="NEW-MKT", side=OrderSide.YES, action=OrderAction.BUY,
            target_price=Decimal("0.50"), edge=Decimal("0.10"),
            confidence=0.7, strategy_name="test", reason="test",
        )

        approved, size, reason = rm.check_signal(signal)
        self.assertFalse(approved)
        self.assertIn("Max positions", reason)

    def test_daily_loss_halts_trading(self):
        """Should halt trading when daily loss limit is hit."""
        from src.risk.manager import RiskManager

        config = {
            "bankroll_dollars": 5000,
            "max_position_pct": 0.05,
            "max_total_exposure_pct": 0.40,
            "daily_loss_limit_pct": 0.05,
            "max_concurrent_positions": 20,
            "kelly_fraction": 0.25,
        }

        mock_client = MagicMock()
        # Start with $5000
        mock_client.get_balance.return_value = Balance(
            available_dollars=Decimal("5000"),
            total_dollars=Decimal("5000"),
        )
        mock_client.get_positions.return_value = []

        rm = RiskManager(config, mock_client)
        rm.start_of_day_reset()

        # Now balance drops to $4700 (6% loss > 5% limit)
        mock_client.get_balance.return_value = Balance(
            available_dollars=Decimal("4700"),
            total_dollars=Decimal("4700"),
        )

        signal = Signal(
            ticker="TEST", side=OrderSide.YES, action=OrderAction.BUY,
            target_price=Decimal("0.50"), edge=Decimal("0.10"),
            confidence=0.7, strategy_name="test", reason="test",
        )

        approved, size, reason = rm.check_signal(signal)
        self.assertFalse(approved)
        self.assertIn("daily loss", reason.lower())
        self.assertTrue(rm.is_trading_halted())


class TestSignalDeduplication(unittest.TestCase):
    """Test the signal deduplication logic."""

    def _make_signal(self, ticker, side, edge, strategy="test", is_arb=False, pair_id=""):
        return Signal(
            ticker=ticker, side=side, action=OrderAction.BUY,
            target_price=Decimal("0.50"), edge=Decimal(str(edge)),
            confidence=0.7, strategy_name=strategy, reason="test",
            is_arbitrage=is_arb, pair_id=pair_id,
        )

    def test_keeps_highest_edge(self):
        """When multiple strategies signal same ticker, keep highest edge."""
        from src.main import deduplicate_signals

        signals = [
            self._make_signal("MKT-1", OrderSide.YES, 0.05, "strat_a"),
            self._make_signal("MKT-1", OrderSide.YES, 0.10, "strat_b"),
        ]
        result = deduplicate_signals(signals)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].edge, Decimal("0.10"))

    def test_drops_conflicting_signals(self):
        """When strategies disagree on side, drop both."""
        from src.main import deduplicate_signals

        signals = [
            self._make_signal("MKT-1", OrderSide.YES, 0.05),
            self._make_signal("MKT-1", OrderSide.NO, 0.10),
        ]
        result = deduplicate_signals(signals)
        self.assertEqual(len(result), 0)

    def test_preserves_arb_pairs(self):
        """Arbitrage paired signals should be preserved."""
        from src.main import deduplicate_signals

        signals = [
            self._make_signal("MKT-1", OrderSide.YES, 0.03, is_arb=True, pair_id="abc"),
            self._make_signal("MKT-1", OrderSide.NO, 0.03, is_arb=True, pair_id="abc"),
        ]
        result = deduplicate_signals(signals)
        self.assertEqual(len(result), 2)


if __name__ == "__main__":
    unittest.main()
