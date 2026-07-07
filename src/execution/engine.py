"""Order execution engine: placement, fill tracking, and order management."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING

from .pricing import PriceCalculator
from ..models.order import Fill, Order, OrderAction, OrderSide, OrderStatus, OrderType
from ..strategies.base import Signal

if TYPE_CHECKING:
    from ..client.rest import KalshiRestClient

logger = logging.getLogger("kalshi_bot.execution")


class ExecutionEngine:
    """Manages the full order lifecycle.

    - Submits signals as limit orders with smart pricing
    - Tracks open orders
    - Polls for fills
    - Cancels stale unfilled orders
    """

    def __init__(self, client: "KalshiRestClient", config: dict):
        self._client = client
        self._pricer = PriceCalculator(config)
        self._order_timeout = config.get("order_timeout_seconds", 60)
        self._max_open_orders = config.get("max_open_orders", 10)

        # Track open orders: client_order_id -> Order
        self._open_orders: dict[str, Order] = {}
        # Track last known fills to avoid duplicates
        self._known_fill_ids: set[str] = set()

    @property
    def open_order_count(self) -> int:
        return len(self._open_orders)

    def submit_signal(self, signal: Signal, size: int) -> Order | None:
        """Convert a signal to a limit order and submit it.

        Args:
            signal: Trading signal with direction and target price
            size: Number of contracts (from risk manager)

        Returns:
            Order object if submitted, None if failed
        """
        if self.open_order_count >= self._max_open_orders:
            logger.warning(
                f"Max open orders ({self._max_open_orders}) reached. "
                f"Skipping {signal.ticker}"
            )
            return None

        try:
            # Fetch current orderbook for smart pricing
            ob = self._client.get_orderbook(signal.ticker, depth=5)
            limit_price = self._pricer.calculate_limit_price(signal, ob)

            # Create order object
            order = Order(
                ticker=signal.ticker,
                action=signal.action,
                side=signal.side,
                order_type=OrderType.LIMIT,
                price_dollars=limit_price,
                count=size,
                strategy_name=signal.strategy_name,
                reason=signal.reason,
            )

            # Submit to Kalshi
            response = self._client.place_order(order)
            order_data = response.get("order", {})
            order.kalshi_order_id = order_data.get("order_id", "")
            order.status = OrderStatus.RESTING

            # Track it
            self._open_orders[order.client_order_id] = order

            logger.info(
                f"ORDER SUBMITTED: {order.action.value} {order.count}x "
                f"{order.side.value} {order.ticker} @ ${order.price_dollars} "
                f"(kalshi_id={order.kalshi_order_id})"
            )
            return order

        except Exception as e:
            logger.error(f"Failed to submit order for {signal.ticker}: {e}")
            return None

    def check_fills(self) -> list[Fill]:
        """Poll for new fills on open orders.

        Returns:
            List of new Fill objects since last check
        """
        new_fills = []

        try:
            # Fetch recent fills
            fills = self._client.get_fills(limit=50)

            for fill in fills:
                fill_id = fill.trade_id or f"{fill.order_id}_{fill.timestamp}"
                if fill_id in self._known_fill_ids:
                    continue

                self._known_fill_ids.add(fill_id)
                new_fills.append(fill)

                logger.info(
                    f"FILL: {fill.action.value} {fill.count}x "
                    f"{fill.side.value} {fill.ticker} @ ${fill.price_dollars}"
                )

            # Update open order statuses
            self._sync_order_statuses()

        except Exception as e:
            logger.error(f"Error checking fills: {e}")

        return new_fills

    def cancel_stale_orders(self) -> int:
        """Cancel orders that have been open longer than the timeout.

        Returns:
            Number of orders cancelled
        """
        cancelled = 0
        now = datetime.utcnow()
        stale_ids = []

        for coid, order in self._open_orders.items():
            if not order.is_open:
                continue
            age_seconds = (now - order.created_at).total_seconds()
            if age_seconds > self._order_timeout:
                stale_ids.append(coid)

        for coid in stale_ids:
            order = self._open_orders[coid]
            try:
                if order.kalshi_order_id:
                    self._client.cancel_order(order.kalshi_order_id)
                order.status = OrderStatus.CANCELLED
                cancelled += 1
                logger.info(
                    f"CANCELLED stale order: {order.ticker} "
                    f"(age={int((now - order.created_at).total_seconds())}s)"
                )
            except Exception as e:
                logger.warning(f"Failed to cancel order {order.kalshi_order_id}: {e}")

        # Clean up completed orders from tracking
        self._cleanup_completed()

        if cancelled:
            logger.info(f"Cancelled {cancelled} stale orders")
        return cancelled

    def cancel_all(self) -> int:
        """Cancel all open orders. Used on shutdown or emergency halt.

        Returns:
            Number of orders cancelled
        """
        cancelled = 0
        for coid, order in list(self._open_orders.items()):
            if order.is_open and order.kalshi_order_id:
                try:
                    self._client.cancel_order(order.kalshi_order_id)
                    order.status = OrderStatus.CANCELLED
                    cancelled += 1
                except Exception as e:
                    logger.warning(f"Failed to cancel {order.kalshi_order_id}: {e}")

        self._open_orders.clear()
        logger.info(f"Emergency cancel: cancelled {cancelled} orders")
        return cancelled

    def _sync_order_statuses(self):
        """Update statuses of tracked open orders from the API."""
        for coid, order in list(self._open_orders.items()):
            if not order.is_open or not order.kalshi_order_id:
                continue
            try:
                data = self._client.get_order(order.kalshi_order_id)
                order_data = data.get("order", data)
                status_str = order_data.get("status", "")

                if status_str:
                    try:
                        order.status = OrderStatus(status_str)
                    except ValueError:
                        pass

                filled = int(order_data.get("total_matched", 0) or 0)
                order.filled_count = filled

            except Exception as e:
                logger.debug(f"Could not sync order {order.kalshi_order_id}: {e}")

    def _cleanup_completed(self):
        """Remove completed orders from the tracking dict."""
        completed = [
            coid for coid, order in self._open_orders.items()
            if order.is_complete
        ]
        for coid in completed:
            del self._open_orders[coid]
