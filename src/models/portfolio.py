"""Portfolio, Balance, and P&L data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from .order import OrderSide


@dataclass
class Balance:
    """Account balance."""
    available_dollars: Decimal
    total_dollars: Decimal
    pending_dollars: Decimal = Decimal("0")

    @classmethod
    def from_api_response(cls, data: dict) -> Balance:
        # Kalshi returns balance in cents
        return cls(
            available_dollars=Decimal(str(data.get("available_balance", 0))) / 100,
            total_dollars=Decimal(str(data.get("balance", 0))) / 100,
            pending_dollars=Decimal(str(data.get("payout", 0))) / 100,
        )


@dataclass
class Position:
    """An open position in a market."""
    ticker: str
    side: OrderSide
    count: int
    avg_entry_price: Decimal
    current_price: Optional[Decimal] = None

    @property
    def market_value(self) -> Decimal:
        """Current market value of the position."""
        price = self.current_price or self.avg_entry_price
        return price * self.count

    @property
    def cost_basis(self) -> Decimal:
        """Total cost to enter this position."""
        return self.avg_entry_price * self.count

    @property
    def unrealized_pnl(self) -> Decimal:
        """Unrealized P&L."""
        if self.current_price is None:
            return Decimal("0")
        return (self.current_price - self.avg_entry_price) * self.count

    @classmethod
    def from_api_response(cls, data: dict) -> Position:
        """Parse from Kalshi portfolio positions response."""
        # Determine side from the count signs
        yes_count = int(data.get("total_traded", 0) or 0)
        resting_yes = int(data.get("resting_orders_count", 0) or 0)

        # market_exposure gives a sense of the position
        market_exposure = data.get("market_exposure", 0)

        # Kalshi positions response varies; handle flexibly
        position_count = int(data.get("position", 0) or 0)
        if position_count >= 0:
            side = OrderSide.YES
        else:
            side = OrderSide.NO
            position_count = abs(position_count)

        avg_price = Decimal("0.50")  # default if not available
        if data.get("total_cost"):
            total_cost = Decimal(str(data["total_cost"])) / 100
            if position_count > 0:
                avg_price = total_cost / position_count

        return cls(
            ticker=data.get("ticker", data.get("market_ticker", "")),
            side=side,
            count=position_count,
            avg_entry_price=avg_price,
        )


@dataclass
class DailyPnL:
    """Daily profit and loss tracker."""
    date: date
    starting_balance: Decimal
    current_balance: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    trade_count: int = 0
    fills: list = field(default_factory=list)

    @property
    def total_pnl(self) -> Decimal:
        return self.current_balance - self.starting_balance

    @property
    def total_pnl_pct(self) -> Decimal:
        if self.starting_balance == 0:
            return Decimal("0")
        return self.total_pnl / self.starting_balance

    @property
    def is_loss_limit_hit(self) -> bool:
        """Check if we've lost more than a threshold (checked externally)."""
        return self.total_pnl < 0
