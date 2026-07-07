"""Kalshi Trading Bot — Main entry point and orchestration loop.

Usage:
    python -m src.main                  # Run with default config
    python -m src.main --config path    # Run with custom config
    python -m src.main --dry-run        # Scan only, no trades
"""

from __future__ import annotations

import argparse
import signal as signal_module
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

from .client.rest import KalshiRestClient
from .execution.engine import ExecutionEngine
from .portfolio.tracker import PortfolioTracker
from .risk.manager import RiskManager
from .strategies.arbitrage import ArbitrageStrategy
from .strategies.base import Signal, Strategy
from .utils.logging import setup_logging

import logging

logger = logging.getLogger("kalshi_bot.main")


def load_config(path: str) -> dict:
    """Load YAML configuration file."""
    config_path = Path(path)
    if not config_path.exists():
        print(f"ERROR: Config file not found at {path}")
        print(f"Copy config/config.example.yaml to {path} and fill in your API keys.")
        sys.exit(1)

    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Validate required fields
    required = ["api", "risk", "arbitrage", "edge", "execution", "logging"]
    for key in required:
        if key not in config:
            print(f"ERROR: Missing '{key}' section in config")
            sys.exit(1)

    if config["api"].get("key_id", "").startswith("YOUR_"):
        print("ERROR: You need to set your API key_id in the config file.")
        print("Generate API keys at https://kalshi.com/account/api-keys")
        sys.exit(1)

    return config


def deduplicate_signals(signals: list[Signal]) -> list[Signal]:
    """Deduplicate and resolve conflicting signals.

    Rules:
    - Arbitrage pairs are kept together (linked by pair_id)
    - If multiple strategies signal the same ticker, keep highest edge
    - If signals conflict (BUY YES vs BUY NO) for same ticker from
      non-arb strategies, drop both
    """
    # Separate arb signals (always keep paired)
    arb_signals = [s for s in signals if s.is_arbitrage]
    edge_signals = [s for s in signals if not s.is_arbitrage]

    # Deduplicate edge signals by ticker
    best_by_ticker: dict[str, Signal] = {}
    conflicts: set[str] = set()

    for s in edge_signals:
        key = s.ticker
        if key in best_by_ticker:
            existing = best_by_ticker[key]
            # Check for conflict (different sides)
            if existing.side != s.side:
                conflicts.add(key)
                continue
            # Keep the one with higher edge
            if s.edge > existing.edge:
                best_by_ticker[key] = s
        else:
            best_by_ticker[key] = s

    # Remove conflicting tickers
    deduped_edge = [
        s for ticker, s in best_by_ticker.items()
        if ticker not in conflicts
    ]

    # Don't duplicate arb signals for tickers that also have edge signals
    edge_tickers = {s.ticker for s in deduped_edge}
    filtered_arb = [s for s in arb_signals if s.ticker not in edge_tickers]

    result = filtered_arb + deduped_edge
    if len(result) != len(signals):
        logger.info(
            f"Deduplication: {len(signals)} signals -> {len(result)} "
            f"({len(signals) - len(result)} removed)"
        )
    return result


def run_bot(config: dict, dry_run: bool = False):
    """Main bot loop."""

    # Setup logging
    root_logger = setup_logging(config["logging"])
    logger.info("=" * 60)
    logger.info("KALSHI TRADING BOT STARTING")
    logger.info("=" * 60)

    if dry_run:
        logger.info("*** DRY RUN MODE — no orders will be placed ***")

    # Initialize components
    logger.info("Initializing API client...")
    client = KalshiRestClient(config["api"])

    logger.info("Initializing risk manager...")
    risk_mgr = RiskManager(config["risk"], client)

    logger.info("Initializing execution engine...")
    execution = ExecutionEngine(client, config["execution"])

    logger.info("Initializing portfolio tracker...")
    tracker = PortfolioTracker(client)

    # Initialize strategies
    strategies: list[Strategy] = []

    if config["arbitrage"].get("enabled", True):
        strategies.append(ArbitrageStrategy(config["arbitrage"]))
        logger.info("Strategy enabled: Arbitrage")

    if config["edge"].get("enabled", True):
        from .strategies.edge import EdgeDetectionStrategy
        strategies.append(EdgeDetectionStrategy(config["edge"]))
        logger.info(f"Strategy enabled: Edge Detection ({config['edge'].get('model_type', 'mean_reversion')})")

    if not strategies:
        logger.error("No strategies enabled! Enable at least one in config.")
        sys.exit(1)

    # Validate connectivity
    try:
        balance = client.get_balance()
        logger.info(f"Connected! Balance: ${balance.total_dollars:.2f} (available: ${balance.available_dollars:.2f})")
    except Exception as e:
        logger.error(f"Failed to connect to Kalshi API: {e}")
        logger.error("Check your API keys and network connection.")
        sys.exit(1)

    # Record start-of-day
    risk_mgr.start_of_day_reset()
    tracker.sync()
    tracker.print_status()

    # Graceful shutdown handler
    shutdown_requested = False

    def handle_shutdown(signum, frame):
        nonlocal shutdown_requested
        if shutdown_requested:
            logger.warning("Force shutdown!")
            sys.exit(1)
        shutdown_requested = True
        logger.info("Shutdown requested. Finishing current cycle...")

    signal_module.signal(signal_module.SIGINT, handle_shutdown)
    signal_module.signal(signal_module.SIGTERM, handle_shutdown)

    # Main loop
    cycle = 0
    scan_interval = config["arbitrage"].get("scan_interval_seconds", 5)

    logger.info(f"Starting main loop (interval={scan_interval}s)")
    logger.info("-" * 60)

    while not shutdown_requested:
        cycle += 1
        cycle_start = time.time()

        try:
            # 1. Check if trading is halted
            if risk_mgr.is_trading_halted():
                logger.warning("Trading halted (daily loss limit). Sleeping 5 min...")
                for _ in range(300):
                    if shutdown_requested:
                        break
                    time.sleep(1)
                continue

            # 2. Sync portfolio state (every 10 cycles to save API calls)
            if cycle % 10 == 1:
                tracker.sync()

            # 3. Fetch all open markets
            markets = client.get_markets(status="open")
            logger.debug(f"Cycle {cycle}: {len(markets)} open markets")

            # 4. Run each strategy
            all_signals: list[Signal] = []
            for strategy in strategies:
                try:
                    signals = strategy.scan(markets, client)
                    all_signals.extend(signals)
                    if signals:
                        logger.info(f"  {strategy.name}: {len(signals)} signals")
                except Exception as e:
                    logger.error(f"Strategy {strategy.name} error: {e}", exc_info=True)

            # 5. Deduplicate signals
            if all_signals:
                signals = deduplicate_signals(all_signals)
                logger.info(f"Cycle {cycle}: {len(signals)} signals after dedup")
            else:
                signals = []

            # 6. Risk check and execute each signal
            for sig in signals:
                if shutdown_requested:
                    break

                approved, size, reason = risk_mgr.check_signal(sig)

                if approved:
                    if dry_run:
                        logger.info(
                            f"  [DRY RUN] WOULD TRADE: {sig.action.value} {size}x "
                            f"{sig.side.value} {sig.ticker} @ ${sig.target_price} "
                            f"(edge={sig.edge:.4f}) [{sig.strategy_name}]"
                        )
                    else:
                        order = execution.submit_signal(sig, size)
                        if order:
                            logger.info(f"  EXECUTED: {order.ticker} {order.count}x @ ${order.price_dollars}")
                else:
                    logger.debug(f"  REJECTED: {sig.ticker} - {reason}")

            # 7. Check fills (if not dry run)
            if not dry_run:
                fills = execution.check_fills()
                for fill in fills:
                    tracker.record_fill(fill)
                    risk_mgr.record_fill(fill)

                # 8. Cancel stale orders
                execution.cancel_stale_orders()

            # 9. Periodic status report (every 60 cycles ~ 5 min)
            if cycle % 60 == 0:
                tracker.sync()
                tracker.print_status()

            # 10. Sleep
            elapsed = time.time() - cycle_start
            sleep_time = max(0, scan_interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Main loop error (cycle {cycle}): {e}", exc_info=True)
            time.sleep(10)

    # Shutdown
    logger.info("=" * 60)
    logger.info("SHUTTING DOWN")

    if not dry_run:
        logger.info("Cancelling all open orders...")
        execution.cancel_all()

    # Final status
    tracker.sync()
    tracker.print_status()

    # Export fills
    tracker.export_fills_csv()

    logger.info("Bot stopped.")
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Kalshi Trading Bot")
    parser.add_argument(
        "--config", "-c",
        default="config/config.yaml",
        help="Path to config file (default: config/config.yaml)",
    )
    parser.add_argument(
        "--dry-run", "-d",
        action="store_true",
        help="Scan and log signals without placing trades",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    run_bot(config, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
