"""Main entry point: python -m src [--dry-run]"""

import argparse
import logging
import os
import signal
import sys
import time
import yaml

from .api_client import KalshiClient
from .scanner import MarketScanner
from .risk_manager import RiskManager
from .executor import TradeExecutor
from .paper_trader import PaperTrader
from .external_odds import ExternalOddsProvider


def load_config(path: str) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


def setup_logging(config: dict):
    log_cfg = config.get("logging", {})
    level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
    log_file = log_cfg.get("file", "logs/bot.log")

    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file),
        ],
    )


def main():
    parser = argparse.ArgumentParser(description="Kalshi Trading Bot")
    parser.add_argument("--dry-run", action="store_true", help="Scan only, no real trades")
    parser.add_argument("--config", default="config/config.yaml", help="Config file path")
    parser.add_argument("--once", action="store_true", help="Run one scan then exit")
    parser.add_argument("--live-confirm", action="store_true",
                        help="Required to run in live mode (safety flag)")
    args = parser.parse_args()

    # Safety: require --live-confirm to trade real money
    if not args.dry_run and not args.live_confirm:
        print("="*60)
        print("  WARNING: You are about to trade REAL MONEY!")
        print("  Add --live-confirm to confirm you want to go live.")
        print("  Use --dry-run for paper trading.")
        print("="*60)
        sys.exit(1)

    # Load config
    if not os.path.exists(args.config):
        print(f"Config not found: {args.config}")
        print("Copy config/config.example.yaml to config/config.yaml and add your API key.")
        sys.exit(1)

    config = load_config(args.config)
    setup_logging(config)
    logger = logging.getLogger("kalshi-bot")

    mode = "DRY RUN" if args.dry_run else "LIVE"
    logger.info(f"{'='*50}")
    logger.info(f"  Kalshi Trading Bot - {mode} MODE")
    logger.info(f"{'='*50}")

    # Init API client
    api_cfg = config["api"]
    client = KalshiClient(
        base_url=api_cfg["base_url"],
        key_id=api_cfg["key_id"],
        private_key_path=api_cfg["private_key_path"],
    )

    # Check connection
    try:
        balance = client.get_balance()
        bal_dollars = balance.get("balance", 0) / 100
        logger.info(f"Connected! Balance: ${bal_dollars:.2f}")
    except Exception as e:
        logger.error(f"Failed to connect: {e}")
        sys.exit(1)

    # Init components
    paper = None
    if args.dry_run:
        paper_balance = config["risk"].get("paper_balance", 1000)
        paper = PaperTrader(starting_balance=paper_balance)
        risk = RiskManager(config)
        risk.bankroll = paper.balance
        risk.starting_bankroll = paper.starting_balance
        logger.info(f"[PAPER] Paper trading with ${paper.balance:.2f} fake money")
    else:
        risk = RiskManager(config)
        risk.update_bankroll(balance.get("balance", 0))

    # Init external odds provider
    ext_odds = None
    ext_cfg = config.get("external_odds", {})
    if ext_cfg.get("enabled") and ext_cfg.get("odds_api_key"):
        ext_odds = ExternalOddsProvider(ext_cfg["odds_api_key"])
        logger.info("[ODDS] External odds enabled (The Odds API)")
    else:
        logger.info("[ODDS] No external odds API key - using bid/ask analysis only")
        logger.info("[ODDS] Get a free key at https://the-odds-api.com/ for better edge detection")

    scanner = MarketScanner(client, config, external_odds=ext_odds)
    executor = TradeExecutor(client, risk, dry_run=args.dry_run)

    scan_interval = config["strategy"]["scan_interval"]
    logger.info(f"Scanning every {scan_interval}s | Min edge: {config['strategy']['min_edge']}")
    logger.info(f"Risk: max {config['risk']['max_bet_pct']*100:.0f}% per trade, "
                f"max {config['risk']['max_positions']} positions")

    # Stop file: create this file to gracefully stop the bot
    stop_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "STOP")
    if os.path.exists(stop_file):
        os.remove(stop_file)

    # Ignore Ctrl+C in all modes (user uses copy/paste frequently)
    signal.signal(signal.SIGINT, lambda *_: logger.info(
        "Ctrl+C ignored. To stop: echo. > C:\\Users\\robgk\\kalshi-bot\\STOP"
    ))
    logger.info(f"Ctrl+C is DISABLED. To stop the bot:")
    logger.info(f"  echo. > C:\\Users\\robgk\\kalshi-bot\\STOP")

    # Track all open positions (both paper and live) to prevent duplicates
    held_tickers = set()
    if paper:
        held_tickers = set(paper.positions.keys())

    # Main loop
    scan_count = 0
    while True:
        # Check for stop file
        if os.path.exists(stop_file):
            logger.info("STOP file detected. Shutting down gracefully...")
            os.remove(stop_file)
            break

        scan_count += 1
        logger.info(f"\n--- Scan #{scan_count} ---")

        # Check risk halt
        if risk.check_halt():
            logger.warning("Risk halt active. Waiting...")
            time.sleep(scan_interval)
            continue

        # In live mode, refresh real balance every scan
        if not args.dry_run:
            try:
                live_balance = client.get_balance()
                live_bal_dollars = live_balance.get("balance", 0) / 100
                risk.bankroll = live_bal_dollars
                logger.info(f"[LIVE] Balance: ${live_bal_dollars:.2f}")
            except Exception as e:
                logger.error(f"Balance check failed: {e} - skipping this scan")
                time.sleep(scan_interval)
                continue

        # Scan markets
        opportunities = scanner.scan()

        if not opportunities:
            logger.info("No opportunities found this scan.")
        else:
            logger.info(f"Found {len(opportunities)} opportunities:")
            for opp in opportunities[:5]:  # Show top 5
                logger.info(f"  {opp}")

            # Execute top opportunities (skip tickers we already hold)
            for opp in opportunities:
                if opp.ticker in held_tickers:
                    continue  # Already holding this market (paper or live)

                result = executor.execute(opp)
                if result and result.get("status") != "error":
                    held_tickers.add(opp.ticker)  # Prevent re-buying

                    # Record in paper trader
                    if paper and result.get("status") == "dry_run":
                        paper.record_entry(
                            opp.ticker, opp.side,
                            result["contracts"], opp.market_price,
                        )
                    if not args.dry_run:
                        time.sleep(0.5)  # Rate limit

        # Check paper settlements and remove settled tickers from held set
        if paper:
            before_positions = set(paper.positions.keys())
            paper.check_settlements(client)
            after_positions = set(paper.positions.keys())
            settled = before_positions - after_positions
            for t in settled:
                held_tickers.discard(t)
            ps = paper.summary()
            logger.info(
                f"[PAPER] Balance: ${ps['current_balance']:.2f} | "
                f"PnL: ${ps['total_pnl']:+.2f} | "
                f"Open: {ps['open_positions']} | "
                f"W/L: {ps['wins']}/{ps['losses']} ({ps['win_rate']})"
            )

        # Print summary
        summary = executor.get_summary()
        risk_status = risk.status()
        logger.info(
            f"Session: {summary['total_signals']} signals, "
            f"{summary['executed']} executed, "
            f"${summary['total_cost']:.2f} deployed | "
            f"Bankroll: ${risk_status['bankroll']:.2f} | "
            f"Daily PnL: ${risk_status['daily_pnl']:.2f}"
        )

        if args.once:
            break

        logger.info(f"Sleeping {scan_interval}s...")
        time.sleep(scan_interval)

    # Clean exit
    summary = executor.get_summary()
    logger.info(f"Bot stopped. Final summary: {summary}")


if __name__ == "__main__":
    main()
