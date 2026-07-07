"""Risk management: position sizing, exposure limits, daily loss protection."""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal, ROUND_DOWN
from typing import TYPE_CHECKING

from ..models.order import Fill
from ..models.portfolio import DailyPnL
from ..strategies.base import Signal

if TYPE_CHECKING:
    from ..client.rest import KalshiRestClient

logger = logging.getLogger("kalshi_bot.risk")


class RiskManager:
    """Central risk gatekeeper.

    Every trading signal passes through check_signal() before execution.
    Enforces:
    - Daily loss limit (halts trading for the day)
    - Maximum concurrent positions
    - Maximum total portfolio exposure
    - Per-market position size limit
    - Kelly criterion position sizing (quarter-Kelly default)
    """

    def __init__(self, config: dict, client: "KalshiRestClient"):
        self._client = client
        self._bankroll = Decimal(str(config.get("bankroll_dollars", 5000)))
        self._max_position_pct = Decimal(str(config.get("max_position_pct", 0.05)))
        self._max_exposure_pct = Decimal(str(config.get("max_total_exposure_pct", 0.40)))
        self._daily_loss_pct = Decimal(str(config.get("daily_loss_limit_pct", 0.05)))
        self._max_positions = config.get("max_concurrent_positions", 20)
        self._kelly_fraction = Decimal(str(config.get("kelly_fraction", 0.25)))

        self._trading_halted = False
        self._daily_pnl: DailyPnL | None = None
        self._position_cache: dict[str, int] = {}  # ticker -> count
        self._cache_time = 0.0

    # -------------------------------------------------------------------------
    # Daily tracking
    # -------------------------------------------------------------------------

    def start_of_day_reset(self):
        """Record starting balance for daily P&L tracking. Call on startup."""
        try:
            balance = self._client.get_balance()
            self._daily_pnl = DailyPnL(
                date=date.today(),
                starting_balance=balance.total_dollars,
                current_balance=balance.total_dollars,
            )
            self._trading_halted = False
            self._bankroll = balance.total_dollars  # Update bankroll to actual balance
            logger.info(
                f"Day reset: bankroll=${self._bankroll}, "
                f"daily loss limit=${self._bankroll * self._daily_loss_pct}"
            )
        except Exception as e:
            logger.error(f"Failed to reset daily tracking: {e}")

    def is_trading_halted(self) -> bool:
        """Check if trading is halted due to daily loss limit."""
        return self._trading_halted

    def record_fill(self, fill: Fill):
        """Record a fill for daily P&L tracking."""
        if self._daily_pnl:
            self._daily_pnl.trade_count += 1
            self._daily_pnl.fills.append(fill)

    # -------------------------------------------------------------------------
    # Signal evaluation
    # -------------------------------------------------------------------------

    def check_signal(self, signal: Signal) -> tuple[bool, int, str]:
        """Evaluate whether a signal should be executed and determine size.

        Args:
            signal: The trading signal to evaluate

        Returns:
            Tuple of (approved, position_size, reason)
            - approved: True if the trade should be placed
            - position_size: Number of contracts to trade
            - reason: Human-readable explanation
        """
        # 1. Check if trading is halted
        if self._check_daily_loss():
            return False, 0, "Trading halted: daily loss limit reached"

        # 2. Check concurrent positions
        positions = self._get_positions()
        if len(positions) >= self._max_positions:
            return False, 0, f"Max positions reached ({self._max_positions})"

        # 3. Check total exposure
        total_exposure = self._get_total_exposure(positions)
        max_exposure = self._bankroll * self._max_exposure_pct
        if total_exposure >= max_exposure:
            return (
                False, 0,
                f"Max exposure reached: ${total_exposure:.2f} >= ${max_exposure:.2f}"
            )

        # 4. Check per-market position
        existing = self._position_cache.get(signal.ticker, 0)
        max_per_market = self._bankroll * self._max_position_pct
        existing_value = Decimal(str(existing)) * signal.target_price
        if existing_value >= max_per_market:
            return (
                False, 0,
                f"Max position in {signal.ticker}: ${existing_value:.2f} >= ${max_per_market:.2f}"
            )

        # 5. Calculate position size using Kelly criterion
        size = self._kelly_size(signal)

        # 6. Clamp to remaining room in per-market limit
        remaining_room = max_per_market - existing_value
        max_contracts_by_limit = int(remaining_room / signal.target_price) if signal.target_price > 0 else 0
        size = min(size, max_contracts_by_limit)

        # 7. Clamp to remaining room in total exposure
        exposure_room = max_exposure - total_exposure
        max_contracts_by_exposure = int(exposure_room / signal.target_price) if signal.target_price > 0 else 0
        size = min(size, max_contracts_by_exposure)

        if size < 1:
            return False, 0, "Position size too small after risk limits"

        return True, size, "approved"

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _check_daily_loss(self) -> bool:
        """Check if daily loss limit has been breached."""
        if self._trading_halted:
            return True

        try:
            balance = self._client.get_balance()
            if self._daily_pnl:
                self._daily_pnl.current_balance = balance.total_dollars
                loss = self._daily_pnl.starting_balance - balance.total_dollars
                loss_pct = loss / self._daily_pnl.starting_balance if self._daily_pnl.starting_balance > 0 else Decimal("0")

                if loss > 0 and loss_pct >= self._daily_loss_pct:
                    self._trading_halted = True
                    logger.warning(
                        f"DAILY LOSS LIMIT HIT: lost ${loss:.2f} "
                        f"({loss_pct:.1%}) - HALTING TRADING"
                    )
                    return True
        except Exception as e:
            logger.error(f"Error checking daily loss: {e}")

        return False

    def _get_positions(self) -> list:
        """Fetch current positions and update cache."""
        try:
            positions = self._client.get_positions()
            self._position_cache = {}
            for p in positions:
                self._position_cache[p.ticker] = p.count
            return positions
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return []

    def _get_total_exposure(self, positions: list) -> Decimal:
        """Calculate total portfolio exposure (sum of position market values)."""
        total = Decimal("0")
        for p in positions:
            total += p.market_value
        return total

    def _kelly_size(self, signal: Signal) -> int:
        """Calculate position size using fractional Kelly criterion.

        Kelly formula: f* = (bp - q) / b
        Where:
            b = net odds (payout - 1 = (1/price) - 1)
            p = probability of winning (price + edge)
            q = probability of losing (1 - p)

        We use quarter-Kelly (kelly_fraction = 0.25) for safety.
        """
        price = float(signal.target_price)
        edge = float(signal.edge)

        if price <= 0 or price >= 1:
            return 1

        # Estimated probability of winning
        p = min(0.95, price + edge)
        q = 1 - p

        # Net odds: how much you win per dollar risked
        b = (1.0 / price) - 1.0

        if b <= 0:
            return 1

        # Kelly fraction
        kelly_f = (b * p - q) / b

        if kelly_f <= 0:
            # Negative Kelly = don't bet
            return 0

        # Apply fraction (quarter-Kelly)
        adjusted_f = kelly_f * float(self._kelly_fraction)

        # Convert to dollar amount and then to contracts
        kelly_dollars = float(self._bankroll) * adjusted_f
        contracts = int(kelly_dollars / price)

        # Minimum 1 contract if Kelly says to bet at all
        return max(1, contracts)
