"""
Topaz Configuration Module

Інтегрує auto-detection Topaz з налаштуваннями проекту.
Використовуй цей модуль замість прямого доступу до settings для Topaz.

Використання:
    from app.modules.topaz_config import topaz_config

    if topaz_config.is_enabled:
        ffmpeg = topaz_config.ffmpeg_path
        # ... use Topaz
"""

from pathlib import Path
from typing import Optional
from loguru import logger

from app.modules.topaz_detector import topaz_detector


class TopazConfig:
    """
    Конфігурація Topaz Video AI з auto-detection.

    При ініціалізації:
    1. Перевіряє наявність Topaz через TopazDetector
    2. Якщо знайдено - використовує знайдені шляхи
    3. Якщо ні - вимикає Topaz функціонал

    Properties:
        is_enabled: Чи увімкнено Topaz (auto-detected)
        ffmpeg_path: Шлях до Topaz FFmpeg
        models_path: Шлях до моделей Topaz
    """

    def __init__(self):
        self._initialized = False
        self._is_enabled = False
        self._ffmpeg_path: Optional[Path] = None
        self._models_path: Optional[Path] = None

    def _ensure_initialized(self):
        """Lazy initialization"""
        if self._initialized:
            return

        installation = topaz_detector.detect()

        if installation.is_available:
            self._is_enabled = True
            self._ffmpeg_path = installation.ffmpeg_path
            self._models_path = installation.models_path

            logger.success("Topaz Video AI auto-detected:")
            logger.info(f"  FFmpeg: {self._ffmpeg_path}")
            logger.info(f"  Models: {self._models_path}")
            logger.info(f"  Version: {installation.version_hint}")
        else:
            self._is_enabled = False
            logger.warning("Topaz Video AI not found - enhancement disabled")
            if installation.error_message:
                logger.warning(f"  {installation.error_message}")

        self._initialized = True

    @property
    def is_enabled(self) -> bool:
        """Чи увімкнено Topaz (auto-detected)"""
        self._ensure_initialized()
        return self._is_enabled

    @property
    def ffmpeg_path(self) -> Optional[Path]:
        """Шлях до Topaz FFmpeg executable"""
        self._ensure_initialized()
        return self._ffmpeg_path

    @property
    def models_path(self) -> Optional[Path]:
        """Шлях до моделей Topaz"""
        self._ensure_initialized()
        return self._models_path

    def disable(self):
        """Примусово вимкнути Topaz"""
        self._ensure_initialized()
        self._is_enabled = False
        logger.info("Topaz Video AI manually disabled")

    def get_status(self) -> dict:
        """Повертає повний статус для діагностики"""
        self._ensure_initialized()
        return {
            "enabled": self._is_enabled,
            "ffmpeg_path": str(self._ffmpeg_path) if self._ffmpeg_path else None,
            "models_path": str(self._models_path) if self._models_path else None,
            "detector_status": topaz_detector.get_status(),
        }


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

topaz_config = TopazConfig()


# ============================================================================
# EXPORT
# ============================================================================

__all__ = ["TopazConfig", "topaz_config"]
