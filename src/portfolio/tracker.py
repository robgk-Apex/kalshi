"""Portfolio tracker: P&L monitoring, position sync, and reporting."""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from ..models.order import Fill, OrderSide
from ..models.portfolio import Balance, DailyPnL, Position

if TYPE_CHECKING:
    from ..client.rest import KalshiRestClient

logger = logging.getLogger("kalshi_bot.portfolio")


class PortfolioTracker:
    """Tracks portfolio state, P&L, and fill history.

    Periodically syncs with Kalshi API and maintains local
    records for analysis and CSV export.
    """

    def __init__(self, client: "KalshiRestClient"):
        self._client = client
        self._balance: Optional[Balance] = None
        self._positions: list[Position] = []
        self._fill_history: list[Fill] = []
        self._last_sync: Optional[datetime] = None

    @property
    def balance(self) -> Optional[Balance]:
        return self._balance

    @property
    def positions(self) -> list[Position]:
        return self._positions

    @property
    def total_exposure(self) -> Decimal:
        """Sum of all position market values."""
        return sum(p.market_value for p in self._positions)

    @property
    def total_unrealized_pnl(self) -> Decimal:
        """Sum of unrealized P&L across all positions."""
        return sum(p.unrealized_pnl for p in self._positions)

    def sync(self):
        """Sync portfolio state from Kalshi API."""
        try:
            self._balance = self._client.get_balance()
            self._positions = self._client.get_positions()
            self._last_sync = datetime.utcnow()

            logger.info(
                f"Portfolio sync: balance=${self._balance.total_dollars:.2f} "
                f"available=${self._balance.available_dollars:.2f} "
                f"positions={len(self._positions)} "
                f"exposure=${self.total_exposure:.2f}"
            )

        except Exception as e:
            logger.error(f"Portfolio sync failed: {e}")

    def record_fill(self, fill: Fill):
        """Record a fill in local history."""
        self._fill_history.append(fill)
        logger.info(
            f"Fill recorded: {fill.action.value} {fill.count}x "
            f"{fill.side.value} {fill.ticker} @ ${fill.price_dollars} "
            f"(total=${fill.total_dollars:.2f})"
        )

    def get_position(self, ticker: str) -> Optional[Position]:
        """Get current position in a specific market."""
        for p in self._positions:
            if p.ticker == ticker:
                return p
        return None

    def get_daily_summary(self) -> dict:
        """Generate a summary of today's trading activity."""
        if not self._balance:
            self.sync()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "balance": float(self._balance.total_dollars) if self._balance else 0,
            "available": float(self._balance.available_dollars) if self._balance else 0,
            "num_positions": len(self._positions),
            "total_exposure": float(self.total_exposure),
            "unrealized_pnl": float(self.total_unrealized_pnl),
            "fills_today": len(self._fill_history),
            "positions": [
                {
                    "ticker": p.ticker,
                    "side": p.side.value,
                    "count": p.count,
                    "avg_price": float(p.avg_entry_price),
                    "market_value": float(p.market_value),
                    "pnl": float(p.unrealized_pnl),
                }
                for p in self._positions
            ],
        }

    def export_fills_csv(self, path: str = "./logs/fills.csv"):
        """Export fill history to CSV for analysis."""
        if not self._fill_history:
            logger.info("No fills to export")
            return

        filepath = Path(path)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp", "ticker", "side", "action",
                "price", "count", "total", "order_id", "trade_id",
            ])
            for fill in self._fill_history:
                writer.writerow([
                    fill.timestamp.isoformat(),
                    fill.ticker,
                    fill.side.value,
                    fill.action.value,
                    float(fill.price_dollars),
                    fill.count,
                    float(fill.total_dollars),
                    fill.order_id,
                    fill.trade_id,
                ])

        logger.info(f"Exported {len(self._fill_history)} fills to {filepath}")

    def print_status(self):
        """Print a formatted portfolio status to the console."""
        if not self._balance:
            print("Portfolio not synced yet. Call sync() first.")
            return

        print("\n" + "=" * 60)
        print("PORTFOLIO STATUS")
        print("=" * 60)
        print(f"  Balance:    ${self._balance.total_dollars:.2f}")
        print(f"  Available:  ${self._balance.available_dollars:.2f}")
        print(f"  Positions:  {len(self._positions)}")
        print(f"  Exposure:   ${self.total_exposure:.2f}")
        print(f"  Unreal P&L: ${self.total_unrealized_pnl:.2f}")

        if self._positions:
            print("\n  Open Positions:")
            print(f"  {'Ticker':<25} {'Side':<5} {'Qty':<5} {'Entry':<8} {'Value':<10} {'P&L':<10}")
            print("  " + "-" * 63)
            for p in self._positions:
                print(
                    f"  {p.ticker:<25} {p.side.value:<5} {p.count:<5} "
                    f"${p.avg_entry_price:<7.2f} ${p.market_value:<9.2f} "
                    f"${p.unrealized_pnl:<9.2f}"
                )

        print(f"\n  Fills this session: {len(self._fill_history)}")
        print(f"  Last sync: {self._last_sync}")
        print("=" * 60 + "\n")
