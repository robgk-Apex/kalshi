"""Structured logging setup with console and rotating file output."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(config: dict) -> logging.Logger:
    """Configure the logging system.

    Args:
        config: Logging config dict with keys:
            level, file, console, max_bytes, backup_count

    Returns:
        Root logger for the application
    """
    level = getattr(logging, config.get("level", "INFO").upper(), logging.INFO)
    log_file = config.get("file", "./logs/kalshi_bot.log")
    max_bytes = config.get("max_bytes", 10 * 1024 * 1024)  # 10 MB
    backup_count = config.get("backup_count", 5)
    enable_console = config.get("console", True)

    # Create log directory
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Configure root logger
    root_logger = logging.getLogger("kalshi_bot")
    root_logger.setLevel(level)

    # Clear existing handlers
    root_logger.handlers.clear()

    # Format
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler (rotating)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Console handler
    if enable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    root_logger.info("Logging initialized")
    return root_logger
