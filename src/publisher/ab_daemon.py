"""
A/B Rotation Daemon — Scheduled Monitor Entry Point

Runs ABMonitor.run_cycle() every MONITOR_INTERVAL_MINUTES in a simple loop.
Graceful shutdown on SIGINT/SIGTERM.

Usage:
    python -m src.publisher.ab_daemon
"""

import signal
import sys
import time
from pathlib import Path

from loguru import logger

from .ab_config import MONITOR_INTERVAL_MINUTES
from .ab_monitor import ABMonitor


def _setup_file_logging() -> None:
    """Add file sink so logs persist when running as detached process."""
    log_path = Path(__file__).parent.parent.parent / "logs" / "ab_daemon.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger.add(
        str(log_path),
        rotation="5 MB",
        retention="7 days",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
    )


def run_daemon() -> None:
    """Start the A/B rotation monitoring daemon."""
    _setup_file_logging()
    monitor = ABMonitor()
    running = True

    # Graceful shutdown
    def shutdown(signum, frame):
        nonlocal running
        logger.info("Shutdown signal received, stopping daemon...")
        running = False

    signal.signal(signal.SIGINT, shutdown)
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, shutdown)

    interval_sec = MONITOR_INTERVAL_MINUTES * 60

    logger.info(f"A/B Monitor daemon starting (interval: {MONITOR_INTERVAL_MINUTES}min)")

    # Run once immediately on start
    logger.info("Running initial cycle...")
    try:
        results = monitor.run_cycle()
        logger.info(f"Initial cycle results: {results}")
    except Exception as e:
        logger.error(f"Initial cycle error: {e}")

    # Main loop
    logger.info("Starting monitor loop...")
    while running:
        # Sleep in small increments so shutdown signal is responsive
        for _ in range(interval_sec):
            if not running:
                break
            time.sleep(1)

        if not running:
            break

        try:
            results = monitor.run_cycle()
            if results:
                logger.info(f"Cycle results: {results}")
        except Exception as e:
            logger.error(f"Cycle error: {e}")

    logger.info("A/B Monitor daemon stopped.")


if __name__ == "__main__":
    run_daemon()
