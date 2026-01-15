"""
Custom Exceptions для Edible House Automator
Структуровані помилки для кращої діагностики та обробки
"""

from typing import Optional, Dict, Any


# ============================================================================
# BASE EXCEPTIONS
# ============================================================================

class EdibleHouseError(Exception):
    """Базовий клас для всіх помилок проекту"""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None
    ):
        self.message = message
        self.details = details or {}
        self.cause = cause
        super().__init__(self.message)

    def __str__(self) -> str:
        base = self.message
        if self.details:
            base += f" | Details: {self.details}"
        if self.cause:
            base += f" | Caused by: {self.cause}"
        return base


class ConfigurationError(EdibleHouseError):
    """Помилка конфігурації (відсутні ключі, невалідні значення)"""
    pass


class APIError(EdibleHouseError):
    """Базовий клас для API помилок"""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_body: Optional[str] = None,
        **kwargs
    ):
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(message, **kwargs)


# ============================================================================
# VIDEO PROCESSING EXCEPTIONS
# ============================================================================

class VideoProcessingError(EdibleHouseError):
    """Базовий клас для помилок обробки відео"""
    pass


class UpscalingError(VideoProcessingError):
    """Помилка при upscaling"""
    pass


class FrameInterpolationError(VideoProcessingError):
    """Помилка при frame interpolation (FPS boost)"""
    pass


class TopazError(VideoProcessingError):
    """Помилка Topaz Video AI"""
    pass


# ============================================================================
# HIGGSFIELD EXCEPTIONS
# ============================================================================

class HiggsFieldError(APIError):
    """Базовий клас для Higgsfield помилок"""
    pass


class HiggsFieldImageGenerationError(HiggsFieldError):
    """Помилка генерації зображення"""
    pass


class HiggsFieldVideoGenerationError(HiggsFieldError):
    """Помилка генерації відео"""
    pass


# ============================================================================
# ADSPOWER EXCEPTIONS
# ============================================================================

class AdsPowerError(EdibleHouseError):
    """Базовий клас для AdsPower помилок"""
    pass


class AdsPowerConnectionError(AdsPowerError):
    """Помилка підключення до AdsPower API"""
    pass


class AdsPowerBrowserError(AdsPowerError):
    """Помилка запуску/керування браузером"""
    pass


# ============================================================================
# HIGGSFIELD WEB EXCEPTIONS
# ============================================================================

class HiggsFieldWebError(EdibleHouseError):
    """Базовий клас для Higgsfield Web automation помилок"""
    pass


class HiggsFieldWebNavigationError(HiggsFieldWebError):
    """Помилка навігації по сайту"""
    pass


class HiggsFieldWebElementNotFoundError(HiggsFieldWebError):
    """Елемент не знайдено на сторінці"""
    pass


class HiggsFieldWebGenerationError(HiggsFieldWebError):
    """Помилка генерації через веб-інтерфейс"""
    pass


class HiggsFieldWebTimeoutError(HiggsFieldWebError):
    """Timeout очікування генерації"""
    pass


class HiggsFieldWebDownloadError(HiggsFieldWebError):
    """Помилка завантаження результату"""
    pass


# ============================================================================
# GEMINI/CLAUDE EXCEPTIONS
# ============================================================================

class AIProviderError(APIError):
    """Базовий клас для AI provider помилок"""
    pass


class GeminiError(AIProviderError):
    """Помилка Google Gemini API"""
    pass


class ClaudeError(AIProviderError):
    """Помилка Anthropic Claude API"""
    pass


class ContentGenerationError(AIProviderError):
    """Помилка генерації контенту (сценарій, промпти)"""
    pass


class ValidationError(AIProviderError):
    """Помилка валідації (зображення не відповідає промпту)"""
    pass


# ============================================================================
# ELEVENLABS EXCEPTIONS
# ============================================================================

class ElevenLabsError(APIError):
    """Базовий клас для ElevenLabs помилок"""
    pass


class TTSGenerationError(ElevenLabsError):
    """Помилка генерації TTS"""
    pass


# ============================================================================
# FILE/STORAGE EXCEPTIONS
# ============================================================================

class StorageError(EdibleHouseError):
    """Базовий клас для storage помилок"""
    pass


class FileNotFoundError(StorageError):
    """Файл не знайдено"""
    pass


class FileUploadError(StorageError):
    """Помилка завантаження файлу"""
    pass


class FileDownloadError(StorageError):
    """Помилка скачування файлу"""
    pass


# ============================================================================
# PIPELINE CONTROL ERRORS
# ============================================================================

class ScenarioRejectedError(EdibleHouseError):
    """
    Користувач відхилив сценарій.
    Pipeline має перезапуститись з генерації нового скрипта.
    """
    pass


# ============================================================================
# EXPORT
# ============================================================================

__all__ = [
    # Base
    "EdibleHouseError",
    "ConfigurationError",
    "APIError",

    # Video Processing
    "VideoProcessingError",
    "UpscalingError",
    "FrameInterpolationError",
    "TopazError",

    # Higgsfield
    "HiggsFieldError",
    "HiggsFieldImageGenerationError",
    "HiggsFieldVideoGenerationError",

    # AdsPower
    "AdsPowerError",
    "AdsPowerConnectionError",
    "AdsPowerBrowserError",

    # Higgsfield Web
    "HiggsFieldWebError",
    "HiggsFieldWebNavigationError",
    "HiggsFieldWebElementNotFoundError",
    "HiggsFieldWebGenerationError",
    "HiggsFieldWebTimeoutError",
    "HiggsFieldWebDownloadError",

    # AI Providers
    "AIProviderError",
    "GeminiError",
    "ClaudeError",
    "ContentGenerationError",
    "ValidationError",

    # ElevenLabs
    "ElevenLabsError",
    "TTSGenerationError",

    # Storage
    "StorageError",
    "FileNotFoundError",
    "FileUploadError",
    "FileDownloadError",

    # Pipeline Control
    "ScenarioRejectedError",
]
