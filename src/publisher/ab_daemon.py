"""
A/B Rotation Daemon — Scheduled Monitor Entry Point

Runs ABMonitor.run_cycle() every MONITOR_INTERVAL_MINUTES using APScheduler.
Graceful shutdown on SIGINT/SIGTERM.

Usage:
    python -m src.publisher.ab_daemon
"""

import signal
import sys

from loguru import logger

from .ab_config import MONITOR_INTERVAL_MINUTES
from .ab_monitor import ABMonitor


def run_daemon() -> None:
    """Start the A/B rotation monitoring daemon."""
    from apscheduler.schedulers.blocking import BlockingScheduler

    monitor = ABMonitor()
    scheduler = BlockingScheduler()

    # Run every N minutes, with grace time for missed runs
    scheduler.add_job(
        monitor.run_cycle,
        trigger="interval",
        minutes=MONITOR_INTERVAL_MINUTES,
        id="ab_monitor_cycle",
        misfire_grace_time=300,
        coalesce=True,
    )

    # Graceful shutdown
    def shutdown(signum, frame):
        logger.info("Shutdown signal received, stopping daemon...")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    # SIGTERM is not supported on Windows
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, shutdown)

    logger.info(f"A/B Monitor daemon starting (interval: {MONITOR_INTERVAL_MINUTES}min)")

    # Run once immediately on start
    logger.info("Running initial cycle...")
    try:
        results = monitor.run_cycle()
        logger.info(f"Initial cycle results: {results}")
    except Exception as e:
        logger.error(f"Initial cycle error: {e}")

    logger.info("Starting scheduler loop...")
    scheduler.start()


if __name__ == "__main__":
    run_daemon()
