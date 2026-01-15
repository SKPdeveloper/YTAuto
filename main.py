"""
Edible House Automator - Main Entry Point
AI Video Generation Pipeline для Windows
"""

import asyncio
import sys
from pathlib import Path

# Додаємо app до PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent))

from app.core.config import settings
from app.core.state_manager import state_manager
from app.utils.logger import logger


# ============================================================================
# BANNER
# ============================================================================

BANNER = """
========================================================================

     EDIBLE HOUSE AUTOMATOR - AI Video Generation Pipeline

   Version: 0.1.0 (ETAP 1: Core Infrastructure)

========================================================================
"""


# ============================================================================
# INITIALIZATION
# ============================================================================

async def initialize_system() -> bool:
    """
    Ініціалізує всі компоненти системи

    Returns:
        True якщо успішно, False якщо є критичні помилки
    """
    logger.info("Starting system initialization...")

    try:
        # 1. Перевірка конфігурації
        logger.info("Checking configuration...")
        logger.info(f"Base directory: {settings.BASE_DIR}")
        logger.info(f"Projects directory: {settings.PROJECTS_DIR}")
        logger.info(f"Logs directory: {settings.LOGS_DIR}")
        logger.info(f"Data directory: {settings.DATA_DIR}")

        # 2. Перевірка що всі директорії створені
        logger.info("Ensuring all directories exist...")
        settings.ensure_directories()
        logger.success("All directories ready")

        # 3. Ініціалізація бази даних
        logger.info("Initializing database...")
        await state_manager.initialize()
        logger.success("Database initialized")

        # 4. Перевірка API ключів
        logger.info("Checking API keys...")

        api_keys_status = {
            "Higgsfield": bool(settings.HIGGSFIELD_API_KEY and settings.HIGGSFIELD_API_SECRET),
            "Gemini": bool(settings.GOOGLE_GEMINI_API_KEY),
            "Telegram": bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID),
            "Claude (optional)": bool(settings.ANTHROPIC_API_KEY) if settings.CONTENTBRAIN_PROVIDER == "claude" else None
        }

        for service, has_key in api_keys_status.items():
            if has_key is None:
                logger.debug(f"  {service}: Not required")
            elif has_key:
                logger.success(f"  {service}: [OK] Configured")
            else:
                logger.warning(f"  {service}: [MISSING]")

        # Перевірка чи є хоча б базові ключі
        required_keys = ["Higgsfield", "Gemini", "Telegram"]
        missing_required = [k for k in required_keys if not api_keys_status[k]]

        if missing_required:
            logger.warning(
                f"Missing required API keys: {', '.join(missing_required)}\n"
                f"Please configure them in config/.env before running the pipeline"
            )

        # 5. Перевірка Topaz Video AI
        logger.info("Checking Topaz Video AI...")
        if settings.TOPAZ_FFMPEG_PATH.exists():
            logger.success(f"  Topaz FFmpeg found: {settings.TOPAZ_FFMPEG_PATH}")
        else:
            logger.warning(
                f"  Topaz FFmpeg not found at: {settings.TOPAZ_FFMPEG_PATH}\n"
                f"  Update TOPAZ_FFMPEG_PATH in .env if installed elsewhere"
            )

        # 6. Перевірка ContentBrain налаштувань
        logger.info(f"ContentBrain provider: {settings.CONTENTBRAIN_PROVIDER}")
        logger.info(f"ContentBrain model: {settings.CONTENTBRAIN_MODEL}")

        logger.success("System initialization completed!")
        return True

    except Exception as e:
        logger.error(f"System initialization failed: {e}")
        logger.exception(e)
        return False


# ============================================================================
# MAIN APPLICATION
# ============================================================================

async def main() -> None:
    """
    Головна функція додатку
    """

    print(BANNER)

    # Ініціалізація
    success = await initialize_system()

    if not success:
        logger.error("Initialization failed. Exiting...")
        return

    logger.info("")
    logger.info("=" * 75)
    logger.info("ЕТАП 1: CORE INFRASTRUCTURE - ЗАВЕРШЕНО [COMPLETE]")
    logger.info("=" * 75)
    logger.info("")
    logger.info("Наступні кроки:")
    logger.info("  1. Створи config/.env файл (скопіюй з config/.env.example)")
    logger.info("  2. Заповни API ключі в .env файлі")
    logger.info("  3. Перейди до ЕТАПУ 2: Higgsfield API Client")
    logger.info("")
    logger.info("Система готова! Перейди до наступного етапу розробки.")
    logger.info("")

    # TODO: В наступних етапах тут буде запуск:
    # - FastAPI server
    # - Telegram bot
    # - ProjectOrchestrator
    # - TopazQueue
    # Поки що просто виходимо після ініціалізації


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down gracefully...")
    except Exception as e:
        logger.critical(f"Critical error: {e}")
        logger.exception(e)
        sys.exit(1)
