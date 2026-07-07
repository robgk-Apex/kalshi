"""Risk management - position sizing, loss limits, exposure tracking."""

import logging
from typing import Optional

logger = logging.getLogger("kalshi-bot.risk")


class RiskManager:
    """Controls position sizing and enforces risk limits."""

    def __init__(self, config: dict):
        risk = config["risk"]
        self.bankroll = risk["bankroll"]
        self.max_bet_pct = risk["max_bet_pct"]
        self.max_contracts = risk["max_contracts"]
        self.max_positions = risk["max_positions"]
        self.stop_loss_pct = risk["stop_loss_pct"]
        self.daily_loss_limit = risk["daily_loss_limit"]

        self.starting_bankroll = self.bankroll
        self._starting_bankroll_synced = False
        self.daily_pnl = 0.0
        self.open_positions = 0
        self.halted = False

    def update_bankroll(self, balance_cents: int):
        """Update bankroll from the actual account balance.

        The FIRST sync (at startup) also anchors ``starting_bankroll`` to the
        real balance. Without this the stop-loss threshold stays pinned to the
        config placeholder (e.g. $100) instead of the real account size, so a
        "20% stop-loss" on a $1,000 account would not halt until a ~92% loss.
        """
        self.bankroll = balance_cents / 100
        if not self._starting_bankroll_synced:
            self.starting_bankroll = self.bankroll
            self._starting_bankroll_synced = True

    def check_halt(self) -> bool:
        """Check if we should stop trading."""
        if self.halted:
            return True

        # Stop-loss: bankroll dropped too much
        if self.bankroll < self.starting_bankroll * (1 - self.stop_loss_pct):
            logger.warning(
                f"HALT: Stop-loss triggered. Bankroll ${self.bankroll:.2f} "
                f"< ${self.starting_bankroll * (1 - self.stop_loss_pct):.2f}"
            )
            self.halted = True
            return True

        # Daily loss limit
        if self.daily_pnl < -self.daily_loss_limit:
            logger.warning(
                f"HALT: Daily loss limit hit. PnL=${self.daily_pnl:.2f} "
                f"< -${self.daily_loss_limit:.2f}"
            )
            self.halted = True
            return True

        return False

    def size_position(self, edge: float, price: float) -> Optional[int]:
        """
        Calculate how many contracts to buy using Kelly Criterion (fractional).

        Returns number of contracts, or None if we shouldn't trade.
        """
        if self.check_halt():
            return None

        if self.open_positions >= self.max_positions:
            logger.info(f"Max positions ({self.max_positions}) reached, skipping")
            return None

        if price <= 0 or price >= 1:
            return None

        # Kelly fraction: edge / odds
        # For binary markets: f = (p * b - q) / b
        # where p = fair probability, b = payout odds, q = 1-p
        win_prob = price + edge
        win_prob = max(0.01, min(0.99, win_prob))
        lose_prob = 1 - win_prob

        payout = (1.0 / price) - 1  # payout ratio
        if payout <= 0:
            return None

        kelly = (win_prob * payout - lose_prob) / payout

        # Use fractional Kelly (25%) for safety
        kelly *= 0.25

        if kelly <= 0:
            return None

        # Scale bet size with confidence (edge size)
        # Bigger edge = higher confidence = bigger bet
        # SAFETY: All tiers are capped at max_bet_pct from config
        if edge >= 0.30:
            tier = "MAX"
            tier_pct = 0.06  # 6% of bankroll ($300)
            max_cts = self.max_contracts * 3  # 300 contracts
        elif edge >= 0.15:
            tier = "LARGE"
            tier_pct = 0.05  # 5% ($250)
            max_cts = self.max_contracts * 2  # 200 contracts
        elif edge >= 0.05:
            tier = "MEDIUM"
            tier_pct = 0.03  # 3% ($150)
            max_cts = self.max_contracts  # 100 contracts
        else:
            tier = "SMALL"
            tier_pct = 0.015  # 1.5% ($75)
            max_cts = int(self.max_contracts * 0.5)  # 50 contracts

        # HARD CAP: never exceed max_bet_pct from config regardless of tier
        max_pct = min(tier_pct, self.max_bet_pct)

        # Convert to dollar amount, cap at tier max
        bet_dollars = min(kelly * self.bankroll, max_pct * self.bankroll)

        # HARD CAP: absolute max $200 per trade
        bet_dollars = min(bet_dollars, 200.0)

        # Convert to contracts
        contracts = int(bet_dollars / price)
        contracts = max(1, min(contracts, max_cts))

        logger.info(f"Sizing: edge={edge:.4f} kelly={kelly:.4f} tier={tier} "
                     f"bet=${bet_dollars:.2f} contracts={contracts}")

        return contracts

    def record_trade(self, pnl: float = 0):
        self.daily_pnl += pnl

    def record_open(self):
        self.open_positions += 1

    def record_close(self):
        self.open_positions = max(0, self.open_positions - 1)

    def reset_daily(self):
        """Call at start of each trading day."""
        self.daily_pnl = 0.0
        self.halted = False
        logger.info("Daily risk counters reset")

    def status(self) -> dict:
        return {
            "bankroll": self.bankroll,
            "daily_pnl": self.daily_pnl,
            "open_positions": self.open_positions,
            "halted": self.halted,
        }
