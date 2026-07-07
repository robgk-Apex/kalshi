"""Edge detection strategy: model-based probability estimation vs market prices."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from .base import Signal, Strategy
from ..models.order import OrderAction, OrderSide

if TYPE_CHECKING:
    from ..client.rest import KalshiRestClient
    from ..models.market import Market

logger = logging.getLogger("kalshi_bot.strategies.edge")


# =============================================================================
# Pluggable probability models
# =============================================================================

class ProbabilityModel(ABC):
    """Abstract interface for probability estimation models.

    Implement this to add your own model (e.g., using news APIs,
    polling data, ML predictions, etc.).
    """

    @abstractmethod
    def estimate(
        self,
        market: "Market",
        related_markets: list["Market"],
        client: "KalshiRestClient",
    ) -> Optional[tuple[float, float]]:
        """Estimate the true probability for a market.

        Args:
            market: The market to estimate
            related_markets: Other markets in the same event
            client: API client for additional data

        Returns:
            Tuple of (probability, confidence) or None if no estimate.
            probability: 0.0 to 1.0 (true YES probability)
            confidence: 0.0 to 1.0 (how confident the model is)
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        pass


class MeanReversionModel(ProbabilityModel):
    """Bet against sharp recent price moves.

    Theory: In illiquid prediction markets, sharp moves often overshoot
    and revert to the mean. If price has moved significantly from the
    previous price, estimate fair value closer to the previous level.
    """

    @property
    def name(self) -> str:
        return "mean_reversion"

    def estimate(
        self,
        market: "Market",
        related_markets: list["Market"],
        client: "KalshiRestClient",
    ) -> Optional[tuple[float, float]]:
        if market.last_price is None or market.previous_price is None:
            return None

        last = float(market.last_price)
        prev = float(market.previous_price)

        if prev == 0 or last == 0:
            return None

        # Calculate the move
        move = last - prev
        move_pct = abs(move) / prev

        # Only signal on significant moves (>10% relative move)
        if move_pct < 0.10:
            return None

        # Estimate fair value as partial reversion (60% of the way back)
        reversion_factor = 0.60
        fair_value = last - (move * reversion_factor)

        # Clamp to valid range
        fair_value = max(0.05, min(0.95, fair_value))

        # Confidence based on move magnitude (bigger move = more likely to revert)
        confidence = min(0.8, move_pct * 2)

        return (fair_value, confidence)


class AggregateModel(ProbabilityModel):
    """Check that probabilities within an event sum to ~1.0.

    Theory: For mutually exclusive outcomes (e.g., "Who wins?"), the
    YES prices of all markets in the event should sum to approximately 1.0.
    If they don't, some markets are mispriced.
    """

    @property
    def name(self) -> str:
        return "aggregate"

    def estimate(
        self,
        market: "Market",
        related_markets: list["Market"],
        client: "KalshiRestClient",
    ) -> Optional[tuple[float, float]]:
        if not related_markets or len(related_markets) < 2:
            return None

        # Sum all YES implied probabilities in the event
        total_prob = Decimal("0")
        market_prob = None
        valid_count = 0

        for m in related_markets:
            prob = m.implied_yes_prob
            if prob is not None and prob > 0:
                total_prob += prob
                valid_count += 1
                if m.ticker == market.ticker:
                    market_prob = prob

        if market_prob is None or valid_count < 2:
            return None

        # If probabilities sum to > 1.0, all markets are overpriced
        # If they sum to < 1.0, all markets are underpriced
        # Adjust this market's fair value proportionally

        if total_prob == 0:
            return None

        # Fair value: normalize so the event sums to 1.0
        fair_value = float(market_prob / total_prob)

        # Calculate how mispriced this specific market is
        current_price = float(market_prob)
        price_diff = abs(fair_value - current_price)

        # Only signal if meaningful mispricing
        if price_diff < 0.03:
            return None

        # Confidence based on how many markets we're averaging over
        confidence = min(0.7, 0.3 + (valid_count * 0.05))

        return (fair_value, confidence)


class StaleBookModel(ProbabilityModel):
    """Detect stale/abandoned markets with outdated prices.

    Theory: Low-volume markets may have stale limit orders sitting on
    the book at prices that no longer reflect reality. If the market
    has wide spreads and minimal recent activity, the last trade price
    may better represent fair value than the current bid/ask.
    """

    @property
    def name(self) -> str:
        return "stale_book"

    def estimate(
        self,
        market: "Market",
        related_markets: list["Market"],
        client: "KalshiRestClient",
    ) -> Optional[tuple[float, float]]:
        if market.last_price is None:
            return None

        # Check for wide spread (indicating stale book)
        spread = market.spread_pct
        if spread is None or spread < Decimal("0.08"):
            return None  # Spread is tight enough, book isn't stale

        # Check for low volume
        if market.volume_24h > 100:
            return None  # Active market, not stale

        # Use last trade price as fair value estimate
        # (more recent info than the stale book)
        fair_value = float(market.last_price)
        fair_value = max(0.05, min(0.95, fair_value))

        # Low confidence — stale book trades are uncertain
        confidence = 0.4

        return (fair_value, confidence)


# =============================================================================
# Model registry
# =============================================================================

MODEL_REGISTRY: dict[str, type[ProbabilityModel]] = {
    "mean_reversion": MeanReversionModel,
    "aggregate": AggregateModel,
    "stale_book": StaleBookModel,
}


# =============================================================================
# Edge detection strategy
# =============================================================================

class EdgeDetectionStrategy(Strategy):
    """Compares market prices against a probability model and bets on edges.

    Uses pluggable ProbabilityModel implementations to estimate fair values,
    then generates signals when the market price diverges significantly.
    """

    def __init__(self, config: dict):
        self._min_edge = Decimal(str(config.get("min_edge_pct", 0.05)))
        self._min_volume = config.get("min_volume_24h", 50)
        self._max_spread = Decimal(str(config.get("max_spread_pct", 0.15)))

        model_type = config.get("model_type", "mean_reversion")
        if model_type not in MODEL_REGISTRY:
            raise ValueError(
                f"Unknown model type: {model_type}. "
                f"Available: {list(MODEL_REGISTRY.keys())}"
            )
        self._model = MODEL_REGISTRY[model_type]()
        logger.info(f"Edge detection using model: {self._model.name}")

    @property
    def name(self) -> str:
        return f"edge_{self._model.name}"

    def scan(
        self,
        markets: list[Market],
        client: KalshiRestClient,
    ) -> list[Signal]:
        signals = []

        # Group markets by event for the aggregate model
        event_markets: dict[str, list[Market]] = {}
        for m in markets:
            if m.status == "open":
                event_markets.setdefault(m.event_ticker, []).append(m)

        candidates = self._pre_filter(markets)
        logger.info(
            f"Edge scan ({self._model.name}): {len(markets)} markets, "
            f"{len(candidates)} candidates"
        )

        for market in candidates:
            try:
                related = event_markets.get(market.event_ticker, [])
                result = self._model.estimate(market, related, client)

                if result is None:
                    continue

                fair_value, confidence = result
                signal = self._evaluate_edge(market, fair_value, confidence)
                if signal:
                    signals.append(signal)
                    logger.info(f"EDGE FOUND: {signal}")

            except Exception as e:
                logger.warning(f"Error analyzing {market.ticker}: {e}")

        return signals

    def _pre_filter(self, markets: list[Market]) -> list[Market]:
        """Filter markets suitable for edge detection."""
        candidates = []
        for m in markets:
            if m.status != "open":
                continue
            if m.volume_24h < self._min_volume:
                continue
            # Skip markets with extremely wide spreads (no liquidity)
            if m.spread_pct is not None and m.spread_pct > self._max_spread:
                # Exception: stale book model specifically looks for wide spreads
                if self._model.name != "stale_book":
                    continue
            candidates.append(m)
        return candidates

    def _evaluate_edge(
        self,
        market: Market,
        fair_value: float,
        confidence: float,
    ) -> Optional[Signal]:
        """Compare model's fair value against market price and generate signal."""
        market_price = market.implied_yes_prob
        if market_price is None:
            return None

        market_price_f = float(market_price)
        edge = fair_value - market_price_f

        # Check if edge exceeds threshold
        if abs(edge) < float(self._min_edge):
            return None

        if edge > 0:
            # Model says YES is underpriced -> BUY YES
            side = OrderSide.YES
            action = OrderAction.BUY
            # Target price slightly above current market
            target_price = Decimal(str(min(fair_value, market_price_f + abs(edge) * 0.5)))
        else:
            # Model says YES is overpriced -> BUY NO (equivalent to selling YES)
            side = OrderSide.NO
            action = OrderAction.BUY
            # NO price = 1 - YES price; target the NO side
            no_fair = 1.0 - fair_value
            no_market = 1.0 - market_price_f
            target_price = Decimal(str(min(no_fair, no_market + abs(edge) * 0.5)))

        # Clamp price to valid range
        target_price = max(Decimal("0.01"), min(Decimal("0.99"), target_price))

        return Signal(
            ticker=market.ticker,
            side=side,
            action=action,
            target_price=target_price,
            edge=Decimal(str(abs(edge))),
            confidence=confidence,
            strategy_name=self.name,
            reason=(
                f"Model={self._model.name}: fair={fair_value:.3f} "
                f"vs market={market_price_f:.3f} edge={edge:+.3f}"
            ),
        )
