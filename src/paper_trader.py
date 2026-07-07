"""Paper trading - tracks simulated P&L without real money."""

import json
import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger("kalshi-bot.paper")

PAPER_FILE = "logs/paper_trades.json"


class PaperTrader:
    """Tracks what would have happened if we traded for real."""

    def __init__(self, starting_balance: float = 1000.0):
        self.starting_balance = starting_balance
        self.balance = starting_balance
        self.positions = {}  # ticker -> {side, contracts, entry_price, cost}
        self.closed_trades = []
        self.trade_count = 0
        self._load()

    def record_entry(self, ticker: str, side: str, contracts: int, price: float):
        """Record a simulated buy."""
        cost = contracts * price
        self.balance -= cost
        self.trade_count += 1

        self.positions[ticker] = {
            "side": side,
            "contracts": contracts,
            "entry_price": price,
            "cost": cost,
            "time": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(
            f"[PAPER] BUY {contracts}x {side} {ticker} @ ${price:.2f} "
            f"(cost=${cost:.2f}) | Balance: ${self.balance:.2f}"
        )
        self._save()

    def check_settlements(self, client):
        """Check if any positions have settled and calculate P&L."""
        to_remove = []
        for ticker, pos in self.positions.items():
            try:
                market = client.get_market(ticker).get("market", {})
                status = market.get("status", "")

                if status == "settled":
                    result = market.get("result", "")
                    won = (result == pos["side"])

                    if won:
                        payout = pos["contracts"] * 1.0  # $1 per contract
                        pnl = payout - pos["cost"]
                        self.balance += payout
                    else:
                        pnl = -pos["cost"]

                    self.closed_trades.append({
                        "ticker": ticker,
                        "side": pos["side"],
                        "contracts": pos["contracts"],
                        "entry_price": pos["entry_price"],
                        "result": result,
                        "won": won,
                        "pnl": pnl,
                        "closed_time": datetime.now(timezone.utc).isoformat(),
                    })

                    emoji = "WIN" if won else "LOSS"
                    logger.info(
                        f"[PAPER] {emoji}: {ticker} settled={result} "
                        f"PnL=${pnl:+.2f} | Balance: ${self.balance:.2f}"
                    )
                    to_remove.append(ticker)

            except Exception as e:
                logger.debug(f"Could not check {ticker}: {e}")

        for t in to_remove:
            del self.positions[t]

        if to_remove:
            self._save()

    def summary(self) -> dict:
        total_pnl = self.balance - self.starting_balance
        wins = sum(1 for t in self.closed_trades if t["won"])
        losses = sum(1 for t in self.closed_trades if not t["won"])
        win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0

        return {
            "starting_balance": self.starting_balance,
            "current_balance": round(self.balance, 2),
            "total_pnl": round(total_pnl, 2),
            "open_positions": len(self.positions),
            "closed_trades": len(self.closed_trades),
            "wins": wins,
            "losses": losses,
            "win_rate": f"{win_rate:.1f}%",
            "total_trades": self.trade_count,
        }

    def _save(self):
        data = {
            "starting_balance": self.starting_balance,
            "balance": self.balance,
            "trade_count": self.trade_count,
            "positions": self.positions,
            "closed_trades": self.closed_trades,
        }
        os.makedirs(os.path.dirname(PAPER_FILE), exist_ok=True)
        with open(PAPER_FILE, "w") as f:
            json.dump(data, f, indent=2)

    def _load(self):
        if os.path.exists(PAPER_FILE):
            try:
                with open(PAPER_FILE, "r") as f:
                    data = json.load(f)
                self.balance = data.get("balance", self.starting_balance)
                self.starting_balance = data.get("starting_balance", self.starting_balance)
                self.trade_count = data.get("trade_count", 0)
                self.positions = data.get("positions", {})
                self.closed_trades = data.get("closed_trades", [])
                logger.info(f"[PAPER] Loaded state: ${self.balance:.2f} balance, "
                           f"{len(self.positions)} open positions")
            except Exception:
                pass
