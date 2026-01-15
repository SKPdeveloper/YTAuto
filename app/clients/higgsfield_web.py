"""
HiggsField Web Client - Facade для автоматизації через AdsPower браузер.

Цей модуль об'єднує:
- adspower_client.py - browser management
- higgsfield_image.py - image generation
- higgsfield_video.py - video generation
- higgsfield_selectors.py - CSS/XPath селектори

ВАЖЛИВО: Браузер НЕ закривається автоматично!
Потрібно явно викликати shutdown() після апрува анімацій в Телеграмі.
"""

import asyncio
from pathlib import Path
from typing import Optional, List

import httpx
from loguru import logger

# Re-export data classes
from app.clients.adspower_client import (
    AdsPowerClient,
    AdsPowerConfig,
    create_adspower_client,
)
from app.clients.higgsfield_image import (
    HiggsFieldImageGenerator,
    ImageSettings,
    GeneratedImage,
)
from app.clients.higgsfield_video import (
    HiggsFieldVideoGenerator,
    VideoSettings,
    VideoModel,
    create_video_generator,
)
from app.clients.higgsfield_video_kling import (
    KlingVideoGenerator,
    KlingSettings,
)
from app.clients.higgsfield_selectors import (
    HIGGSFIELD_IMAGE_URL,
    HIGGSFIELD_VIDEO_URL,
    TIMEOUTS,
)


# ============================================================================
# FACADE CLIENT
# ============================================================================

class HiggsFieldWebClient:
    """
    Higgsfield через AdsPower браузер.
    Використовує Ultimate підписку замість API credits.

    ВАЖЛИВО: Браузер НЕ закривається автоматично!
    Потрібно явно викликати shutdown() після апрува анімацій в Телеграмі.

    Usage:
        client = HiggsFieldWebClient(config)
        await client.start_browser()

        # Image generation
        images = await client.generate_primary_candidates(prompt)
        image = await client.generate_scene_image(prompt, reference)

        # Video generation
        video = await client.generate_video(image_path, motion_prompt)

        # After Telegram approval
        client.approve_for_shutdown()
        await client.shutdown()
    """

    def __init__(
        self,
        adspower_config: AdsPowerConfig,
        image_settings: Optional[ImageSettings] = None,
        video_settings: Optional[VideoSettings] = None,
        video_model: VideoModel = VideoModel.SEEDANCE,
        download_dir: Optional[Path] = None,
    ):
        self.adspower = adspower_config
        self.image_settings = image_settings or ImageSettings()
        self.video_settings = video_settings or VideoSettings()
        self._video_model = video_model
        self.download_dir = download_dir or Path.cwd() / "downloads"

        # Internal components
        self._browser: Optional[AdsPowerClient] = None
        self._image_generator: Optional[HiggsFieldImageGenerator] = None
        self._video_generator: Optional[HiggsFieldVideoGenerator] = None
        self._kling_generator: Optional[KlingVideoGenerator] = None
        self._http_client: Optional[httpx.AsyncClient] = None

        # Ensure download dir exists
        self.download_dir.mkdir(parents=True, exist_ok=True)

    # ========================================================================
    # PROPERTIES (for backward compatibility)
    # ========================================================================

    @property
    def _driver(self):
        """Backward compatibility: access to Selenium driver"""
        if self._browser:
            return self._browser.driver
        return None

    @property
    def is_browser_open(self) -> bool:
        """Перевірити чи браузер відкритий"""
        return self._browser is not None and self._browser.is_browser_open

    @property
    def is_approved_for_shutdown(self) -> bool:
        """Перевірити чи є апрув на закриття"""
        if self._browser:
            return self._browser.is_approved_for_shutdown
        return False

    @property
    def video_model(self) -> VideoModel:
        """Поточна модель відео"""
        return self._video_model

    @property
    def video_model_name(self) -> str:
        """Назва поточної моделі відео"""
        if self._video_generator:
            return self._video_generator.model_name
        return self._video_model.value

    # ========================================================================
    # BROWSER LIFECYCLE
    # ========================================================================

    async def start_browser(self) -> None:
        """Запустити браузер та ініціалізувати генератори"""
        logger.info("Starting HiggsFieldWebClient...")

        # Create browser client
        self._browser = AdsPowerClient(self.adspower)
        await self._browser.start_browser()

        # Create HTTP client
        self._http_client = httpx.AsyncClient(timeout=60)

        # Create generators
        self._image_generator = HiggsFieldImageGenerator(
            browser=self._browser,
            download_dir=self.download_dir,
            settings=self.image_settings,
            http_client=self._http_client
        )

        self._video_generator = HiggsFieldVideoGenerator(
            browser=self._browser,
            download_dir=self.download_dir,
            model=self._video_model,
            settings=self.video_settings,
            http_client=self._http_client
        )

        # Kling generator for parallel video generation
        self._kling_generator = KlingVideoGenerator(
            browser=self._browser,
            download_dir=self.download_dir,
            settings=KlingSettings(),
            http_client=self._http_client
        )

        logger.info("HiggsFieldWebClient started successfully")
        logger.info(f"  Video generators: Seedance + Kling 2.6")

    async def close_browser(self) -> None:
        """Закрити браузер (внутрішній метод)"""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

        if self._browser:
            await self._browser._close_browser()
            self._browser = None

        self._image_generator = None
        self._video_generator = None
        self._kling_generator = None

    # ========================================================================
    # APPROVAL & SHUTDOWN
    # ========================================================================

    def approve_for_shutdown(self) -> None:
        """
        Позначити що анімації апрувнуті і браузер можна закривати.
        Викликати з Telegram handler після апрува користувачем.
        """
        if self._browser:
            self._browser.approve_for_shutdown()

    async def shutdown(self) -> None:
        """
        Закрити браузер. Викликати ТІЛЬКИ після апрува анімацій!
        """
        if self._browser:
            await self._browser.shutdown()

        await self.close_browser()

    async def force_shutdown(self) -> None:
        """
        Примусово закрити браузер (для error handling).
        """
        if self._browser:
            await self._browser.force_shutdown()

        await self.close_browser()


    # ========================================================================
    # CLEANUP
    # ========================================================================

    async def clear_all_forms(self) -> None:
        """Очистити всі форми для чистого старту."""
        logger.info("Clearing all HiggsField forms...")
        if self._image_generator:
            try:
                await self._image_generator.clear_all_forms()
            except Exception as e:
                logger.warning(f"Failed to clear image forms: {e}")
        if self._browser and self._browser.driver:
            try:
                self._browser.driver.execute_script("""
                    document.querySelectorAll('textarea').forEach(ta => {
                        ta.value = '';
                        ta.dispatchEvent(new Event('input', { bubbles: true }));
                    });
                """)
            except Exception as e:
                logger.warning(f"Failed to clear video forms: {e}")
        logger.info("All forms cleared")

    # ========================================================================
    # CONTEXT MANAGER
    # ========================================================================

    async def __aenter__(self) -> "HiggsFieldWebClient":
        await self.start_browser()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        # НЕ закриваємо браузер автоматично!
        if exc_type is not None:
            logger.warning(f"Context exit with error: {exc_type.__name__}: {exc_val}")
            logger.warning("Browser NOT closed - call shutdown() manually after approval")

    # ========================================================================
    # IMAGE GENERATION (delegate to generator)
    # ========================================================================

    async def generate_primary_candidates(
        self,
        prompt: str,
        num_candidates: int = 4
    ) -> List[Path]:
        """
        WORKFLOW 1: Генерація 4 candidates для PRIMARY сцени.
        """
        if not self._image_generator:
            raise RuntimeError("Browser not started. Call start_browser() first.")

        return await self._image_generator.generate_primary_candidates(prompt, num_candidates)

    async def generate_scene_image(
        self,
        prompt: str,
        reference_image: Optional[Path] = None,
        reference_type: str = "REQUIRES_REF"
    ) -> Path:
        """
        WORKFLOW 2/3: Генерація зображення для secondary сцени.

        Args:
            prompt: Промпт для генерації
            reference_image: Шлях до reference зображення
            reference_type: INDEPENDENT, REQUIRES_REF, or LOOP_CLOSE
        """
        if not self._image_generator:
            raise RuntimeError("Browser not started. Call start_browser() first.")

        return await self._image_generator.generate_scene_image(prompt, reference_image, reference_type)

    async def queue_single_image(
        self,
        prompt: str,
        scene_num: int,
        reference_image: Optional[Path] = None
    ) -> None:
        """Поставити одне зображення в чергу."""
        if not self._image_generator:
            raise RuntimeError("Browser not started. Call start_browser() first.")

        await self._image_generator.queue_single_image(prompt, scene_num, reference_image)

    # ========================================================================
    # VIDEO GENERATION (delegate to generator)
    # ========================================================================

    async def generate_video(
        self,
        image_path: Path,
        motion_prompt: str,
        duration: int = 10
    ) -> Path:
        """
        WORKFLOW 4: Генерація відео з зображення.
        """
        if not self._video_generator:
            raise RuntimeError("Browser not started. Call start_browser() first.")

        return await self._video_generator.generate_video(image_path, motion_prompt, duration)

    async def queue_single_video(
        self,
        image_path: Path,
        motion_prompt: str,
        scene_num: int,
        duration: int = 10
    ) -> None:
        """Поставити одне відео в чергу."""
        if not self._video_generator:
            raise RuntimeError("Browser not started. Call start_browser() first.")

        await self._video_generator.queue_single_video(
            image_path, motion_prompt, scene_num, duration
        )

    def switch_video_model(self, model: VideoModel) -> None:
        """
        Змінити модель відео.

        Args:
            model: VideoModel.KLING або VideoModel.SEEDANCE
        """
        self._video_model = model
        if self._video_generator:
            self._video_generator.switch_model(model)
        logger.info(f"Switched video model to: {model.value}")

    # ========================================================================
    # PARALLEL VIDEO GENERATION (Kling 2.6)
    # ========================================================================

    async def generate_all_videos_parallel(
        self,
        scenes: list,
        download_dir: Optional[Path] = None,
        timeout: int = 900,
        initial_wait: int = 240,  # Оптимізовано: 4 хв замість 5
    ) -> List[Path]:
        """
        ОПТИМІЗОВАНО: Генерує відео для всіх сцен паралельно через Kling 2.6.

        Workflow:
        1. Всі сцени ставляться в чергу послідовно (БЕЗ refresh!)
        2. Kling генерує їх паралельно
        3. Чекаємо поки всі готові (polling DOM)
        4. Завантажуємо результати

        Args:
            scenes: Список сцен з полями:
                - scene_number: int
                - image_path: str (шлях до зображення)
                - video_prompt: str (motion prompt)
            download_dir: Директорія для завантаження (опціонально)
            timeout: Максимальний час очікування генерації (default: 15 хв)
            initial_wait: Час очікування перед першою перевіркою (default: 4 хв)

        Returns:
            List[Path]: Шляхи до згенерованих відео (в порядку сцен)
        """
        if not self._kling_generator:
            raise RuntimeError("Browser not started. Call start_browser() first.")

        logger.info("")
        logger.info("=" * 60)
        logger.info(f"[Kling] PARALLEL VIDEO GENERATION: {len(scenes)} scenes")
        logger.info("=" * 60)

        # Prepare scenes data for Kling: list of (image_path, motion_prompt, image_url)
        # If image_url is present, FAST mode will be used (no upload!)
        kling_scenes = []
        for scene in scenes:
            image_path = Path(scene.get('image_path', ''))
            motion_prompt = scene.get('video_prompt', '')
            image_url = scene.get('image_url', '')  # FAST mode URL
            kling_scenes.append((image_path, motion_prompt, image_url))

        # Step 1: Queue all scenes
        await self._kling_generator.queue_all_scenes(kling_scenes)

        # Step 2: Wait for all videos to generate
        video_urls = await self._kling_generator.wait_for_all_videos(
            expected_count=len(scenes),
            timeout=timeout,
            initial_wait=initial_wait,
        )

        # Step 3: Download videos via browser button
        # Get asset IDs from the page (works even if video_urls detection failed)
        asset_ids = await self._kling_generator.get_video_asset_ids(count=len(scenes))

        if not video_urls and not asset_ids:
            logger.error("No videos generated - neither URLs nor asset IDs found!")
            return []

        if not video_urls:
            logger.warning("No video URLs detected, but found asset IDs - proceeding with download...")

        if asset_ids:
            # Use button-based download (more reliable, handles signed URLs)
            downloaded_paths = await self._kling_generator.download_videos_via_button(
                asset_ids=list(reversed(asset_ids)),  # Reverse: newest-first → scene order
                download_folder=self.download_dir,
                prefix="scene"
            )
        else:
            # Fallback to HTTP download (may fail if URLs require signing)
            logger.warning("No asset IDs found, trying HTTP download...")
            downloaded_paths = await self._kling_generator.download_videos(
                video_urls=video_urls,
                prefix="kling_scene"
            )

        logger.success(f"[Kling] Generated {len(downloaded_paths)} videos")
        return downloaded_paths

    async def generate_all_images_parallel(
        self,
        scenes: list,
        download_dir: Optional[Path] = None,
    ) -> List[GeneratedImage]:
        """
        Генерує зображення для всіх сцен ПАРАЛЕЛЬНО (batch).

        Workflow:
        1. Navigate ONCE
        2. Upload reference ONCE (if any scene has it)
        3. Set Unlimited ON, 2K, count=1 ONCE
        4. Queue all scenes: prompt → Generate → 15s delay
        5. Wait for all images
        6. Download all

        Args:
            scenes: Список сцен з полями:
                - scene_number: int
                - image_prompt: str
                - reference_image: Optional[str] (шлях до референсу)
            download_dir: Директорія для завантаження (не використовується)

        Returns:
            List[GeneratedImage]: Об'єкти з path та url для кожного зображення
        """
        if not self._image_generator:
            raise RuntimeError("Browser not started. Call start_browser() first.")

        if not scenes:
            return []

        # Find shared reference (first scene with reference_image)
        reference_path = None
        for scene in scenes:
            ref_str = scene.get('reference_image')
            if ref_str:
                reference_path = Path(ref_str)
                break

        logger.info(f"[BATCH] Generating {len(scenes)} images in parallel...")
        logger.info(f"[BATCH] Reference: {reference_path.name if reference_path else 'None'}")

        # Use batch generation method
        generated_paths = await self._image_generator.generate_batch_images(
            scenes=scenes,
            reference_image=reference_path
        )

        logger.success(f"[BATCH] Generated {len(generated_paths)}/{len(scenes)} images")
        return generated_paths

    # ========================================================================
    # NAVIGATION (for advanced use cases)
    # ========================================================================

    async def _navigate_to_image(self) -> None:
        """Перейти на сторінку генерації зображень"""
        if self._image_generator:
            await self._image_generator._navigate_to_image()

    async def _navigate_to_video(self) -> None:
        """Перейти на сторінку генерації відео"""
        if self._video_generator:
            await self._video_generator._navigate_to_video()

    # ========================================================================
    # SETTINGS (for advanced use cases)
    # ========================================================================

    async def _set_aspect_ratio(self, ratio: str) -> None:
        """Встановити aspect ratio для зображення"""
        if self._image_generator:
            await self._image_generator._set_aspect_ratio(ratio)

    async def _set_resolution(self, resolution: str) -> None:
        """Встановити роздільну здатність"""
        if self._image_generator:
            await self._image_generator._set_resolution(resolution)

    async def _set_unlimited(self, enabled: bool) -> None:
        """Встановити Unlimited toggle"""
        if self._image_generator:
            await self._image_generator._set_unlimited(enabled)

    async def _set_video_model(self, model: str) -> None:
        """Встановити модель для відео"""
        if self._video_generator:
            await self._video_generator._set_video_model(model)

    async def _set_video_duration(self, duration: int) -> None:
        """Встановити тривалість відео"""
        if self._video_generator:
            await self._video_generator._set_video_duration(duration)


# ============================================================================
# FACTORY
# ============================================================================

def create_higgsfield_web_client(
    api_key: str,
    profile_id: str,
    base_url: str = "http://local.adspower.net:50325",
    video_model: VideoModel = VideoModel.SEEDANCE,
    download_dir: Optional[Path] = None,
) -> HiggsFieldWebClient:
    """
    Factory для створення клієнта з простими параметрами.

    Args:
        api_key: AdsPower API key
        profile_id: AdsPower profile ID
        base_url: AdsPower API URL
        video_model: Модель відео (KLING або SEEDANCE, default: SEEDANCE)
        download_dir: Директорія для завантаження
    """
    config = AdsPowerConfig(
        api_key=api_key,
        profile_id=profile_id,
        base_url=base_url,
    )

    return HiggsFieldWebClient(
        adspower_config=config,
        video_model=video_model,
        download_dir=download_dir,
    )


# ============================================================================
# EXPORT
# ============================================================================

__all__ = [
    # Main client
    "HiggsFieldWebClient",
    "create_higgsfield_web_client",

    # Config
    "AdsPowerConfig",
    "ImageSettings",
    "VideoSettings",
    "VideoModel",
    "KlingSettings",

    # Sub-modules (for direct access if needed)
    "AdsPowerClient",
    "HiggsFieldImageGenerator",
    "HiggsFieldVideoGenerator",
    "KlingVideoGenerator",
]
