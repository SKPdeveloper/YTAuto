"""
A/B Rotation Daemon — Checkpoint-Aligned Monitor

Runs ABMonitor.run_cycle() on a smart schedule: sleeps until the next
checkpoint instead of polling at a fixed interval. This reduces API calls
by ~90% while improving checkpoint timing precision from ~30min to ~5min.

Graceful shutdown on SIGINT/SIGTERM.

Usage:
    python -m src.publisher.ab_daemon
"""

import signal
import sys
import time
from pathlib import Path

from loguru import logger

from .ab_config import MAX_INTERVAL_MINUTES, MIN_INTERVAL_MINUTES
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
    """Start the A/B rotation monitoring daemon with checkpoint-aligned sleep."""
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

    logger.info(
        f"A/B Monitor daemon starting "
        f"(checkpoint-aligned, min={MIN_INTERVAL_MINUTES}min, max={MAX_INTERVAL_MINUTES}min)"
    )

    # Run once immediately on start
    logger.info("Running initial cycle...")
    try:
        results = monitor.run_cycle()
        logger.info(f"Initial cycle results: {results}")
    except Exception as e:
        logger.error(f"Initial cycle error: {e}")

    # Main loop — sleep until next checkpoint
    while running:
        try:
            sleep_sec = monitor.compute_next_wake_seconds()
        except Exception as e:
            logger.error(f"Error computing next wake: {e}")
            sleep_sec = MIN_INTERVAL_MINUTES * 60

        hours = sleep_sec // 3600
        mins = (sleep_sec % 3600) // 60
        logger.info(f"Sleeping {hours}h{mins:02d}m until next checkpoint...")

        # Sleep in 1-second increments so shutdown signal is responsive
        for _ in range(sleep_sec):
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
