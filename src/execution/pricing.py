"""Smart limit price calculation for order execution."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from ..models.order import OrderAction, OrderSide
from ..strategies.base import Signal

if TYPE_CHECKING:
    from ..models.market import Orderbook


class PriceCalculator:
    """Determines optimal limit prices for signals.

    For arbitrage: use the ask price directly (need guaranteed fill)
    For edge trades: offset slightly from market (try to get better fill)
    """

    def __init__(self, config: dict):
        self._offset = Decimal(str(config.get("limit_offset_cents", 1))) / 100

    def calculate_limit_price(
        self,
        signal: Signal,
        orderbook: "Orderbook",
    ) -> Decimal:
        """Calculate the optimal limit price for a signal.

        Args:
            signal: The trading signal
            orderbook: Current orderbook data

        Returns:
            Limit price in dollars (Decimal)
        """
        # For arbitrage, use exact target price (we need the fill)
        if signal.is_arbitrage:
            return self._clamp(signal.target_price)

        # For edge trades, try to get a better price
        if signal.action == OrderAction.BUY:
            if signal.side == OrderSide.YES:
                # Buying YES: place bid slightly below the ask
                ask = orderbook.best_yes_ask
                if ask is not None:
                    spread = orderbook.spread
                    if spread is not None and spread <= Decimal("0.02"):
                        # Tight spread: use the ask (cross it)
                        return self._clamp(ask)
                    else:
                        # Wide spread: bid inside the spread
                        return self._clamp(ask - self._offset)
            else:
                # Buying NO: place bid slightly below the no ask
                no_ask = orderbook.best_no_ask
                if no_ask is not None:
                    return self._clamp(no_ask - self._offset)

        elif signal.action == OrderAction.SELL:
            if signal.side == OrderSide.YES:
                bid = orderbook.best_yes_bid
                if bid is not None:
                    return self._clamp(bid + self._offset)
            else:
                no_bid = orderbook.best_no_bid
                if no_bid is not None:
                    return self._clamp(no_bid + self._offset)

        # Fallback: use signal's target price
        return self._clamp(signal.target_price)

    @staticmethod
    def _clamp(price: Decimal) -> Decimal:
        """Clamp price to valid Kalshi range ($0.01 - $0.99)."""
        return max(Decimal("0.01"), min(Decimal("0.99"), price))
