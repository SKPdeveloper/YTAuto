"""
Higgsfield Video Generator - Facade з вибором моделі.

Підтримувані моделі:
- Kling 2.6 (платна, висока якість)
- Seedance 1.5 Pro (безкоштовна)

Usage:
    generator = create_video_generator(browser, download_dir, model="seedance")
    video = await generator.generate_video(image_path, prompt)
"""

from pathlib import Path
from typing import Optional, Literal, Union
from dataclasses import dataclass
from enum import Enum

import httpx
from loguru import logger

from app.clients.adspower_client import AdsPowerClient
from app.clients.higgsfield_video_kling import KlingVideoGenerator, KlingSettings
from app.clients.higgsfield_video_seedance import SeedanceVideoGenerator, SeedanceSettings


# ============================================================================
# ENUMS & TYPES
# ============================================================================

class VideoModel(str, Enum):
    """Доступні моделі для генерації відео"""
    KLING = "kling"
    SEEDANCE = "seedance"


# ============================================================================
# SETTINGS
# ============================================================================

@dataclass
class VideoSettings:
    """Загальні налаштування відео (для backward compatibility)"""
    model: str = "Kling 2.6"
    duration: int = 10
    aspect_ratio: str = "9:16"


# ============================================================================
# VIDEO GENERATOR FACADE
# ============================================================================

class HiggsFieldVideoGenerator:
    """
    Facade для генерації відео з вибором моделі.

    Делегує роботу до:
    - KlingVideoGenerator для Kling 2.6
    - SeedanceVideoGenerator для Seedance 1.5 Pro

    Usage:
        generator = HiggsFieldVideoGenerator(
            browser=browser,
            download_dir=download_dir,
            model="seedance"  # або "kling"
        )
        video = await generator.generate_video(image_path, prompt)
    """

    def __init__(
        self,
        browser: AdsPowerClient,
        download_dir: Path,
        model: Union[str, VideoModel] = VideoModel.SEEDANCE,
        settings: Optional[VideoSettings] = None,
        http_client: Optional[httpx.AsyncClient] = None
    ):
        self.browser = browser
        self.download_dir = download_dir
        self._http_client = http_client

        # Визначити модель
        if isinstance(model, str):
            model = model.lower()
            if model in ("kling", "kling 2.6", "kling2.6"):
                self._model = VideoModel.KLING
            elif model in ("seedance", "seedance 1.5", "seedance 1.5 pro"):
                self._model = VideoModel.SEEDANCE
            else:
                logger.warning(f"Unknown model '{model}', defaulting to Seedance")
                self._model = VideoModel.SEEDANCE
        else:
            self._model = model

        # Створити відповідний генератор
        self._generator = self._create_generator()

        logger.info(f"Video generator initialized with model: {self._model.value}")

    def _create_generator(self) -> Union[KlingVideoGenerator, SeedanceVideoGenerator]:
        """Створити генератор для вибраної моделі"""
        if self._model == VideoModel.KLING:
            return KlingVideoGenerator(
                browser=self.browser,
                download_dir=self.download_dir,
                http_client=self._http_client
            )
        else:
            return SeedanceVideoGenerator(
                browser=self.browser,
                download_dir=self.download_dir,
                http_client=self._http_client
            )

    @property
    def model(self) -> VideoModel:
        """Поточна модель"""
        return self._model

    @property
    def model_name(self) -> str:
        """Назва поточної моделі"""
        if self._model == VideoModel.KLING:
            return "Kling 2.6"
        else:
            return "Seedance 1.5 Pro"

    def switch_model(self, model: Union[str, VideoModel]) -> None:
        """
        Змінити модель генерації.

        Args:
            model: "kling" або "seedance"
        """
        if isinstance(model, str):
            model = model.lower()
            if model in ("kling", "kling 2.6"):
                self._model = VideoModel.KLING
            elif model in ("seedance", "seedance 1.5", "seedance 1.5 pro"):
                self._model = VideoModel.SEEDANCE
            else:
                raise ValueError(f"Unknown model: {model}")
        else:
            self._model = model

        self._generator = self._create_generator()
        logger.info(f"Switched to model: {self._model.value}")

    # ========================================================================
    # DELEGATED METHODS
    # ========================================================================

    async def generate_video(
        self,
        image_path: Path,
        motion_prompt: str,
        duration: int = None
    ) -> Path:
        """
        Генерувати відео.

        Args:
            image_path: Шлях до зображення (start frame)
            motion_prompt: Опис руху
            duration: Тривалість (auto: 10s для Kling, 12s для Seedance)

        Returns:
            Path: Шлях до завантаженого відео
        """
        # Default duration based on model
        if duration is None:
            duration = 10 if self._model == VideoModel.KLING else 12

        return await self._generator.generate_video(
            image_path=image_path,
            motion_prompt=motion_prompt,
            duration=duration
        )

    async def queue_single_video(
        self,
        image_path: Path,
        motion_prompt: str,
        scene_num: int,
        duration: int = None
    ) -> None:
        """Поставити відео в чергу"""
        if duration is None:
            duration = 10 if self._model == VideoModel.KLING else 12

        await self._generator.queue_single_video(
            image_path=image_path,
            motion_prompt=motion_prompt,
            scene_num=scene_num,
            duration=duration
        )

    # ========================================================================
    # NAVIGATION (for direct access if needed)
    # ========================================================================

    async def _navigate_to_video(self) -> None:
        """Перейти на сторінку відео"""
        await self._generator._navigate_to_video()


# ============================================================================
# FACTORY FUNCTIONS
# ============================================================================

def create_video_generator(
    browser: AdsPowerClient,
    download_dir: Path,
    model: str = "seedance",
    http_client: Optional[httpx.AsyncClient] = None
) -> HiggsFieldVideoGenerator:
    """
    Factory для створення генератора відео.

    Args:
        browser: AdsPowerClient instance
        download_dir: Директорія для завантаження
        model: "kling" або "seedance" (default: seedance)
        http_client: Optional HTTP client

    Returns:
        HiggsFieldVideoGenerator
    """
    return HiggsFieldVideoGenerator(
        browser=browser,
        download_dir=download_dir,
        model=model,
        http_client=http_client
    )


def create_kling_generator(
    browser: AdsPowerClient,
    download_dir: Path,
    http_client: Optional[httpx.AsyncClient] = None
) -> KlingVideoGenerator:
    """Factory для Kling генератора"""
    return KlingVideoGenerator(
        browser=browser,
        download_dir=download_dir,
        http_client=http_client
    )


def create_seedance_generator(
    browser: AdsPowerClient,
    download_dir: Path,
    http_client: Optional[httpx.AsyncClient] = None
) -> SeedanceVideoGenerator:
    """Factory для Seedance генератора"""
    return SeedanceVideoGenerator(
        browser=browser,
        download_dir=download_dir,
        http_client=http_client
    )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Main facade
    "HiggsFieldVideoGenerator",
    "VideoModel",
    "VideoSettings",

    # Specific generators
    "KlingVideoGenerator",
    "KlingSettings",
    "SeedanceVideoGenerator",
    "SeedanceSettings",

    # Factories
    "create_video_generator",
    "create_kling_generator",
    "create_seedance_generator",
]
