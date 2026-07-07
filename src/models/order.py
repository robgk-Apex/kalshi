"""Order and Fill data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional
import uuid


class OrderSide(Enum):
    YES = "yes"
    NO = "no"


class OrderAction(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    LIMIT = "limit"
    MARKET = "market"


class OrderStatus(Enum):
    PENDING = "pending"
    RESTING = "resting"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class Order:
    """A trading order."""
    ticker: str
    action: OrderAction
    side: OrderSide
    order_type: OrderType
    price_dollars: Decimal
    count: int
    client_order_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    kalshi_order_id: Optional[str] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_count: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    strategy_name: str = ""
    reason: str = ""

    @property
    def is_open(self) -> bool:
        return self.status in (
            OrderStatus.PENDING,
            OrderStatus.RESTING,
            OrderStatus.PARTIALLY_FILLED,
        )

    @property
    def is_complete(self) -> bool:
        return self.status in (
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
        )

    @property
    def remaining_count(self) -> int:
        return self.count - self.filled_count

    @property
    def cost_dollars(self) -> Decimal:
        """Total cost if fully filled."""
        return self.price_dollars * self.count

    def to_api_body(self) -> dict:
        """Convert to Kalshi API create-order request body."""
        body = {
            "ticker": self.ticker,
            "action": self.action.value,
            "side": self.side.value,
            "type": self.order_type.value,
            "count": self.count,
            "client_order_id": self.client_order_id,
        }
        # Use yes_price or no_price depending on side
        if self.side == OrderSide.YES:
            body["yes_price"] = int(self.price_dollars * 100)  # cents
        else:
            body["no_price"] = int(self.price_dollars * 100)
        return body

    @classmethod
    def from_api_response(cls, data: dict) -> Order:
        """Parse from Kalshi API response."""
        side = OrderSide(data.get("side", "yes"))
        price = data.get("yes_price", data.get("no_price", 0))
        return cls(
            ticker=data.get("ticker", ""),
            action=OrderAction(data.get("action", "buy")),
            side=side,
            order_type=OrderType(data.get("type", "limit")),
            price_dollars=Decimal(str(price)) / 100 if price else Decimal("0"),
            count=int(data.get("remaining_count", 0)) + int(data.get("queue_position", 0) or 0),
            client_order_id=data.get("client_order_id", ""),
            kalshi_order_id=data.get("order_id", ""),
            status=OrderStatus(data.get("status", "pending")),
            filled_count=int(data.get("total_matched", 0) or 0),
        )


@dataclass
class Fill:
    """A completed trade fill."""
    order_id: str
    ticker: str
    side: OrderSide
    action: OrderAction
    price_dollars: Decimal
    count: int
    timestamp: datetime = field(default_factory=datetime.utcnow)
    trade_id: str = ""

    @property
    def total_dollars(self) -> Decimal:
        return self.price_dollars * self.count

    @classmethod
    def from_api_response(cls, data: dict) -> Fill:
        price = data.get("yes_price", data.get("no_price", 0))
        ts = data.get("created_time", "")
        if isinstance(ts, str) and ts:
            ts = ts.replace("Z", "+00:00")
            try:
                timestamp = datetime.fromisoformat(ts)
            except Exception:
                timestamp = datetime.utcnow()
        else:
            timestamp = datetime.utcnow()

        return cls(
            order_id=data.get("order_id", ""),
            ticker=data.get("ticker", ""),
            side=OrderSide(data.get("side", "yes")),
            action=OrderAction(data.get("action", "buy")),
            price_dollars=Decimal(str(price)) / 100 if price else Decimal("0"),
            count=int(data.get("count", 0)),
            timestamp=timestamp,
            trade_id=data.get("trade_id", ""),
        )
