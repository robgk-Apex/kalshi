"""Arbitrage strategy: find markets where YES + NO < $1.00."""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from .base import Signal, Strategy
from ..models.order import OrderAction, OrderSide

if TYPE_CHECKING:
    from ..client.rest import KalshiRestClient
    from ..models.market import Market

logger = logging.getLogger("kalshi_bot.strategies.arbitrage")


class ArbitrageStrategy(Strategy):
    """Scans for risk-free arbitrage opportunities.

    Arbitrage exists when buying both YES and NO contracts costs less than $1.00.
    Since one side always settles at $1.00, the difference is guaranteed profit.

    In Kalshi's orderbook:
    - YES ask = 1 - best NO bid (buying YES from someone selling NO)
    - NO ask = 1 - best YES bid (buying NO from someone selling YES)

    If YES_ask + NO_ask < $1.00, there's an arb.
    """

    def __init__(self, config: dict):
        self._min_profit = Decimal(str(config.get("min_profit_cents", 2))) / 100
        self._max_contracts = config.get("max_contracts_per_trade", 50)
        self._min_volume = config.get("min_volume_24h", 10)

    @property
    def name(self) -> str:
        return "arbitrage"

    def scan(
        self,
        markets: list[Market],
        client: KalshiRestClient,
    ) -> list[Signal]:
        """Scan all open markets for arbitrage opportunities.

        Pre-filters using market listing data (yes_bid, yes_ask) before
        fetching full orderbooks to minimize API calls.
        """
        signals = []
        candidates = self._pre_filter(markets)
        logger.info(
            f"Arbitrage scan: {len(markets)} markets, "
            f"{len(candidates)} candidates after pre-filter"
        )

        for market in candidates:
            try:
                arb_signals = self._check_market(market, client)
                if arb_signals:
                    signals.extend(arb_signals)
                    logger.info(
                        f"ARB FOUND: {market.ticker} - "
                        f"profit=${arb_signals[0].edge:.4f}/contract"
                    )
            except Exception as e:
                logger.warning(f"Error checking {market.ticker}: {e}")

        return signals

    def _pre_filter(self, markets: list[Market]) -> list[Market]:
        """Quick filter using market listing data before fetching orderbooks."""
        candidates = []
        for m in markets:
            # Skip non-open or dead markets
            if m.status != "open":
                continue
            if m.volume_24h < self._min_volume:
                continue

            # Quick check from listing data: if yes_ask + no_ask appears cheap
            if m.yes_bid is not None and m.no_bid is not None:
                # yes_ask ≈ 1 - no_bid, no_ask ≈ 1 - yes_bid
                approx_yes_ask = Decimal("1.00") - (m.no_bid if m.no_bid else Decimal("0.99"))
                approx_no_ask = Decimal("1.00") - (m.yes_bid if m.yes_bid else Decimal("0.99"))
                approx_total = approx_yes_ask + approx_no_ask

                # Include if total cost is near or below $1.00 (with some buffer)
                if approx_total <= Decimal("1.02"):
                    candidates.append(m)
            else:
                # No bid data available, include for full check
                candidates.append(m)

        return candidates

    def _check_market(
        self,
        market: Market,
        client: KalshiRestClient,
    ) -> list[Signal]:
        """Check a single market's orderbook for arbitrage.

        Returns:
            List of 0 or 2 signals (always paired: buy YES + buy NO)
        """
        ob = client.get_orderbook(market.ticker, depth=5)

        # Need both sides to have liquidity
        if ob.best_yes_bid is None or ob.best_no_bid is None:
            return []

        # Calculate actual ask prices
        yes_ask = ob.best_yes_ask  # = 1 - best_no_bid
        no_ask = ob.best_no_ask    # = 1 - best_yes_bid

        if yes_ask is None or no_ask is None:
            return []

        total_cost = yes_ask + no_ask
        profit = Decimal("1.00") - total_cost

        logger.debug(
            f"{market.ticker}: yes_ask=${yes_ask} + no_ask=${no_ask} = "
            f"${total_cost} -> profit=${profit}"
        )

        if profit < self._min_profit:
            return []

        # Determine available size (minimum of both sides)
        yes_size = sum(
            lvl.count_fp for lvl in ob.no_bids
            if lvl.price_dollars >= ob.best_no_bid
        )
        no_size = sum(
            lvl.count_fp for lvl in ob.yes_bids
            if lvl.price_dollars >= ob.best_yes_bid
        )
        available_size = min(int(yes_size), int(no_size), self._max_contracts)

        if available_size < 1:
            return []

        # Create paired signals
        pair_id = str(uuid.uuid4())[:8]

        return [
            Signal(
                ticker=market.ticker,
                side=OrderSide.YES,
                action=OrderAction.BUY,
                target_price=yes_ask,
                edge=profit,
                confidence=0.95,  # High confidence for pure arb
                strategy_name=self.name,
                reason=f"Arb: YES@${yes_ask}+NO@${no_ask}=${total_cost} profit=${profit}",
                is_arbitrage=True,
                pair_id=pair_id,
            ),
            Signal(
                ticker=market.ticker,
                side=OrderSide.NO,
                action=OrderAction.BUY,
                target_price=no_ask,
                edge=profit,
                confidence=0.95,
                strategy_name=self.name,
                reason=f"Arb: YES@${yes_ask}+NO@${no_ask}=${total_cost} profit=${profit}",
                is_arbitrage=True,
                pair_id=pair_id,
            ),
        ]
