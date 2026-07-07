"""Trade executor - decides whether to actually place orders."""

import logging
import uuid
from typing import Optional

logger = logging.getLogger("kalshi-bot.executor")


class TradeExecutor:
    """Executes trades or logs them in dry-run mode."""

    def __init__(self, client, risk_manager, dry_run: bool = False):
        self.client = client
        self.risk = risk_manager
        self.dry_run = dry_run
        self.trade_log = []

    def execute(self, opportunity) -> Optional[dict]:
        """Attempt to execute a trade on an opportunity."""

        # Size the position
        contracts = self.risk.size_position(opportunity.edge, opportunity.market_price)
        if contracts is None:
            logger.debug(f"Risk manager rejected: {opportunity.ticker}")
            return None

        cost = contracts * opportunity.market_price
        trade_info = {
            "ticker": opportunity.ticker,
            "title": opportunity.title,
            "side": opportunity.side,
            "action": "buy",
            "contracts": contracts,
            "price": opportunity.market_price,
            "cost": cost,
            "edge": opportunity.edge,
            "fair_price": opportunity.fair_price,
        }

        if self.dry_run:
            logger.info(
                f"[DRY RUN] WOULD TRADE: buy {contracts}x {opportunity.side} "
                f"{opportunity.ticker} @ ${opportunity.market_price:.2f} "
                f"(edge={opportunity.edge:+.4f}, cost=${cost:.2f})"
            )
            trade_info["status"] = "dry_run"
            self.trade_log.append(trade_info)
            self.risk.record_open()  # Track position count in paper mode too
            return trade_info

        # Live execution
        try:
            price_kwarg = {}
            if opportunity.side == "yes":
                price_kwarg["yes_price"] = opportunity.market_price
            else:
                price_kwarg["no_price"] = opportunity.market_price

            result = self.client.place_order(
                ticker=opportunity.ticker,
                side=opportunity.side,
                action="buy",
                count=contracts,
                client_order_id=str(uuid.uuid4()),
                **price_kwarg,
            )

            order = result.get("order", {})
            order_id = order.get("order_id", "unknown")
            status = order.get("status", "unknown")

            logger.info(
                f"ORDER PLACED: {order_id} buy {contracts}x {opportunity.side} "
                f"{opportunity.ticker} @ ${opportunity.market_price:.2f} "
                f"status={status} edge={opportunity.edge:+.4f}"
            )

            self.risk.record_open()
            trade_info["status"] = status
            trade_info["order_id"] = order_id
            self.trade_log.append(trade_info)
            return trade_info

        except Exception as e:
            logger.error(f"Order failed for {opportunity.ticker}: {e}")
            trade_info["status"] = "error"
            trade_info["error"] = str(e)
            self.trade_log.append(trade_info)
            return None

    def get_summary(self) -> dict:
        total = len(self.trade_log)
        executed = sum(1 for t in self.trade_log if t["status"] not in ("error", "dry_run"))
        dry = sum(1 for t in self.trade_log if t["status"] == "dry_run")
        errors = sum(1 for t in self.trade_log if t["status"] == "error")
        total_cost = sum(t["cost"] for t in self.trade_log if t["status"] != "error")
        return {
            "total_signals": total,
            "executed": executed,
            "dry_run": dry,
            "errors": errors,
            "total_cost": total_cost,
        }
