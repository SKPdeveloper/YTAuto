"""
Edible House Automator - Web UI Entry Point
Запуск FastAPI сервера для Web UI
"""

import asyncio
import sys
from pathlib import Path

# Додаємо app до PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent))

import uvicorn
from app.core.config import settings
from app.utils.logger import logger


# ============================================================================
# BANNER
# ============================================================================

BANNER = """
========================================================================

     EDIBLE HOUSE AUTOMATOR - Web UI Dashboard

     Version: 1.0.0

========================================================================
"""


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Start the Web UI server."""
    print(BANNER)

    logger.info("Starting Web UI server...")
    logger.info(f"Host: {settings.WEB_HOST}")
    logger.info(f"Port: {settings.WEB_PORT}")
    logger.info(f"URL: http://{settings.WEB_HOST}:{settings.WEB_PORT}")
    logger.info("")
    logger.info("Press Ctrl+C to stop the server")
    logger.info("")

    try:
        uvicorn.run(
            "app.api.routes:app",
            host=settings.WEB_HOST,
            port=settings.WEB_PORT,
            reload=False,
            log_level="info",
        )
    except KeyboardInterrupt:
        logger.info("Shutting down Web UI server...")


if __name__ == "__main__":
    main()
