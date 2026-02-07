"""
Visual Engine Web - HiggsFieldWebClient Adapter

Адаптер що надає той самий інтерфейс що й HiggsFieldClient (API),
але використовує HiggsFieldWebClient (браузерну автоматизацію).

Це дозволяє використовувати Ultimate підписку замість pay-per-use API.
"""

import asyncio
import shutil
from pathlib import Path
from typing import Optional, List

from app.core.config import settings
from app.utils.logger import logger
from app.utils import file_manager

from app.clients.higgsfield_web import (
    HiggsFieldWebClient,
    AdsPowerConfig,
    ImageSettings,
    VideoSettings,
    VideoModel,
)
from app.clients.higgsfield_image import GeneratedImage
from app.clients.higgsfield_video_simple import SimpleVideoGenerator


class HiggsFieldWebAdapter:
    """
    Адаптер для HiggsFieldWebClient з інтерфейсом сумісним з HiggsFieldClient.

    Використовує браузерну автоматизацію через AdsPower замість API.

    Lifecycle:
    1. Клієнт створюється при ініціалізації orchestrator
    2. Browser запускається при першому виклику методу генерації
    3. Browser залишається відкритим до виклику shutdown()
    4. shutdown() викликається після апрува всіх анімацій в Telegram

    Usage:
        # В orchestrator:
        if settings.HIGGSFIELD_WEB_ENABLED:
            self.visual_engine = HiggsFieldWebAdapter()
        else:
            self.visual_engine = HiggsFieldClient()

        # ... генерація ...

        # Після апрува анімацій:
        await self.visual_engine.shutdown()
    """

    def __init__(self):
        """Ініціалізація адаптера (браузер НЕ запускається тут)"""

        # AdsPower конфігурація
        self._adspower_config = AdsPowerConfig(
            api_key=settings.ADSPOWER_API_KEY,
            profile_id=settings.ADSPOWER_PROFILE_ID,
            base_url=settings.ADSPOWER_BASE_URL,
        )

        # Image settings
        self._image_settings = ImageSettings(
            aspect_ratio=settings.HIGGSFIELD_WEB_ASPECT_RATIO,
            resolution=settings.HIGGSFIELD_WEB_IMAGE_RESOLUTION,
            unlimited=False,  # За замовчуванням OFF для кращої якості
        )

        # Video settings
        self._video_settings = VideoSettings(
            model=settings.HIGGSFIELD_WEB_VIDEO_MODEL,
            duration=settings.HIGGSFIELD_WEB_VIDEO_DURATION,
            aspect_ratio=settings.HIGGSFIELD_WEB_ASPECT_RATIO,
        )

        # Web client (створюється лінево)
        self._client: Optional[HiggsFieldWebClient] = None
        self._browser_started = False

        # Reference image tracking (для сумісності з API клієнтом)
        self._reference_images: dict = {}  # {(project_id, scene_number): image_path}

        # Download directory
        self._download_dir = settings.PROJECTS_DIR / "downloads"
        self._download_dir.mkdir(parents=True, exist_ok=True)

        logger.info("HiggsFieldWebAdapter initialized:")
        logger.info(f"  AdsPower Profile: {settings.ADSPOWER_PROFILE_ID}")
        logger.info(f"  Aspect Ratio: {settings.HIGGSFIELD_WEB_ASPECT_RATIO}")
        logger.info(f"  Image Resolution: {settings.HIGGSFIELD_WEB_IMAGE_RESOLUTION}")
        logger.info(f"  Video Model: {settings.HIGGSFIELD_WEB_VIDEO_MODEL}")
        logger.info(f"  Video Duration: {settings.HIGGSFIELD_WEB_VIDEO_DURATION}s")

    # ========================================================================
    # BROWSER LIFECYCLE
    # ========================================================================

    async def _ensure_browser_started(self) -> None:
        """
        Запускає браузер якщо ще не запущено.
        Якщо браузер був запущений, але вікно закрите - перепідключається.
        """
        # Check if we need to start fresh
        if not self._browser_started or not self._client:
            logger.info("Starting HiggsFieldWebClient browser...")

            # Determine video model from settings
            video_model = VideoModel.KLING if "kling" in settings.HIGGSFIELD_WEB_VIDEO_MODEL.lower() else VideoModel.SEEDANCE
            logger.info(f"Using video model: {video_model.value}")

            self._client = HiggsFieldWebClient(
                adspower_config=self._adspower_config,
                image_settings=self._image_settings,
                video_settings=self._video_settings,
                video_model=video_model,
                download_dir=settings.PROJECTS_DIR / "downloads",
            )

            await self._client.start_browser()
            self._browser_started = True

            # NOTE: НЕ очищаємо тут! Очистка тільки в orchestrator

            logger.success("Browser started and ready")
            return

        # Browser was started before - check if it's still alive
        if self._client and not self._client.is_browser_alive():
            logger.warning("Browser window was closed, reconnecting...")

            # Try to reconnect
            reconnected = await self._client.ensure_alive_or_reconnect(max_retries=3)

            if not reconnected:
                # Full restart needed
                logger.warning("Reconnection failed, performing full restart...")
                self._browser_started = False
                self._client = None

                # Recursive call to start fresh
                await self._ensure_browser_started()
            else:
                logger.success("Browser reconnected successfully")

    def approve_shutdown(self) -> None:
        """
        Позначає що браузер можна закривати.
        Викликати після апрува анімацій в Telegram.
        """
        if self._client:
            self._client.approve_for_shutdown()

    async def shutdown(self) -> None:
        """
        Закриває браузер. Викликати тільки після апрува анімацій!
        """
        if self._client and self._browser_started:
            logger.info("Shutting down HiggsFieldWebAdapter...")
            # Clear all forms before shutdown
            await self._client.clear_all_forms()
            self._client.approve_for_shutdown()
            await self._client.shutdown()
            self._browser_started = False
            logger.success("Browser closed")

    async def force_shutdown(self) -> None:
        """Примусове закриття (для error handling)"""
        if self._client:
            await self._client.force_shutdown()
            self._browser_started = False

    @property
    def is_browser_open(self) -> bool:
        """Чи браузер відкритий"""
        return self._browser_started and self._client is not None

    @property
    def client(self) -> Optional[HiggsFieldWebClient]:
        """Публічний доступ до web client"""
        return self._client

    @property
    def download_dir(self) -> Path:
        """Директорія для завантажень"""
        return self._download_dir

    # ========================================================================
    # IMAGE GENERATION (сумісність з HiggsFieldClient)
    # ========================================================================

    async def generate_image(
        self,
        prompt: str,
        scene_number: int,
        project_id: str = "test_project",
    ) -> Path:
        """
        Генерує одне зображення (Unlimited=ON для швидкості).

        Args:
            prompt: Промпт для генерації
            scene_number: Номер сцени
            project_id: ID проекту

        Returns:
            Path до збереженого зображення
        """
        await self._ensure_browser_started()

        logger.info(f"[Scene {scene_number}] Generating image (Unlimited=ON)...")

        # Для звичайних сцен використовуємо Unlimited=ON (швидше, 1 зображення)
        self._client.image_settings.unlimited = True

        try:
            # Генеруємо зображення (повертає GeneratedImage з .path та .url)
            gen_img = await self._client.generate_scene_image(
                prompt=prompt,
                reference_image=None,
            )

            # Копіюємо в правильну директорію проекту
            scene_dir = settings.get_scene_dir(project_id, scene_number)
            scene_dir.mkdir(parents=True, exist_ok=True)

            final_path = scene_dir / "image.png"
            shutil.copy(gen_img.path, final_path)

            # Зберігаємо metadata
            metadata = {
                "prompt": prompt,
                "scene_number": scene_number,
                "project_id": project_id,
                "generation_mode": "web_unlimited",
                "source": "higgsfield_web",
            }
            await file_manager.save_json(metadata, scene_dir / "metadata.json")

            # Зберігаємо для reference
            self._reference_images[(project_id, scene_number)] = final_path

            logger.success(f"[Scene {scene_number}] Image saved: {final_path}")
            return final_path

        except Exception as e:
            logger.error(f"[Scene {scene_number}] Image generation failed: {e}")
            raise

    async def generate_image_with_reference(
        self,
        prompt: str,
        reference_image_url: Optional[str],
        scene_number: int,
        project_id: str = "test_project",
    ) -> Path:
        """
        Генерує зображення з референсом (для REQUIRES_REF сцен).

        Args:
            prompt: Промпт для генерації
            reference_image_url: URL або шлях до reference зображення
            scene_number: Номер сцени
            project_id: ID проекту

        Returns:
            Path до збереженого зображення
        """
        await self._ensure_browser_started()

        logger.info(f"[Scene {scene_number}] Generating image with reference...")

        # Для сцен з референсом - Unlimited=ON
        self._client.image_settings.unlimited = True

        # Визначаємо reference image path
        reference_path = None
        if reference_image_url:
            # Якщо це URL - конвертуємо в локальний шлях
            if reference_image_url.startswith("http"):
                # Шукаємо локальний файл за project/scene
                for (pid, snum), path in self._reference_images.items():
                    if pid == project_id and path.exists():
                        reference_path = path
                        break
            else:
                # Це вже локальний шлях
                reference_path = Path(reference_image_url)
                if not reference_path.exists():
                    reference_path = None

        try:
            gen_img = await self._client.generate_scene_image(
                prompt=prompt,
                reference_image=reference_path,
            )

            # Копіюємо в директорію проекту
            scene_dir = settings.get_scene_dir(project_id, scene_number)
            scene_dir.mkdir(parents=True, exist_ok=True)

            final_path = scene_dir / "image.png"
            shutil.copy(gen_img.path, final_path)

            # Metadata
            metadata = {
                "prompt": prompt,
                "scene_number": scene_number,
                "project_id": project_id,
                "generation_mode": "web_with_reference",
                "reference_used": str(reference_path) if reference_path else None,
                "source": "higgsfield_web",
            }
            await file_manager.save_json(metadata, scene_dir / "metadata.json")

            self._reference_images[(project_id, scene_number)] = final_path

            logger.success(f"[Scene {scene_number}] Image with reference saved: {final_path}")
            return final_path

        except Exception as e:
            logger.error(f"[Scene {scene_number}] Image generation with reference failed: {e}")
            raise

    async def generate_scene_image(
        self,
        prompt: str,
        scene_number: int,
        project_id: str = "test_project",
        reference_image: Optional[Path] = None,
        reference_type: str = "REQUIRES_REF",
    ) -> Path:
        """
        Генерує зображення для сцени.

        Args:
            prompt: Промпт для генерації
            scene_number: Номер сцени
            project_id: ID проекту
            reference_image: Шлях до reference зображення (опціонально)
            reference_type: INDEPENDENT, REQUIRES_REF, or LOOP_CLOSE

        Returns:
            Path до збереженого зображення
        """
        await self._ensure_browser_started()

        logger.info(f"[Scene {scene_number}] Generating image...")
        logger.info(f"  Reference type: {reference_type}")
        logger.info(f"  Reference image: {reference_image.name if reference_image else 'None'}")

        # Для всіх сцен крім PRIMARY - Unlimited=ON
        self._client.image_settings.unlimited = True

        # Determine reference path
        ref_path = None
        if reference_image and reference_image.exists():
            ref_path = reference_image

        try:
            # Call client's generate_scene_image with reference_type
            # Повертає GeneratedImage з path та url
            gen_img = await self._client.generate_scene_image(
                prompt=prompt,
                reference_image=ref_path,
                reference_type=reference_type
            )

            # Copy to project directory
            scene_dir = settings.get_scene_dir(project_id, scene_number)
            scene_dir.mkdir(parents=True, exist_ok=True)

            final_path = scene_dir / "image.png"
            shutil.copy(gen_img.path, final_path)

            # Metadata з URL для відео генерації
            metadata = {
                "prompt": prompt,
                "scene_number": scene_number,
                "project_id": project_id,
                "reference_type": reference_type,
                "reference_used": str(ref_path) if ref_path else None,
                "source": "higgsfield_web",
                "image_url": gen_img.url,  # URL на HiggsField
            }
            await file_manager.save_json(metadata, scene_dir / "metadata.json")

            self._reference_images[(project_id, scene_number)] = final_path

            logger.success(f"[Scene {scene_number}] Image saved: {final_path}")
            logger.debug(f"  URL saved: {gen_img.url[:60]}...")
            return final_path

        except Exception as e:
            logger.error(f"[Scene {scene_number}] Image generation failed: {e}")
            raise

    async def generate_primary_scene_candidates(
        self,
        prompt: str,
        scene_number: int,
        project_id: str = "test_project",
        num_candidates: int = 4,
        max_retries: int = 2,
    ) -> List[Path]:
        """
        Генерує кандидатів для PRIMARY сцени (Unlimited=OFF для якості).

        Args:
            prompt: Промпт для генерації
            scene_number: Номер сцени (зазвичай 1)
            project_id: ID проекту
            num_candidates: Кількість кандидатів (4)
            max_retries: Максимум повторних спроб при помилці браузера

        Returns:
            List[Path] до збережених зображень
        """
        last_error = None

        for attempt in range(1, max_retries + 2):  # +2 for initial + retries
            try:
                await self._ensure_browser_started()

                logger.info(f"[Scene {scene_number}] Generating {num_candidates} PRIMARY candidates (Unlimited=OFF)...")
                if attempt > 1:
                    logger.info(f"[Scene {scene_number}] Attempt {attempt}/{max_retries + 1}")

                # Для PRIMARY сцени - Unlimited=OFF для найкращої якості
                self._client.image_settings.unlimited = False

                # Генеруємо кандидатів (повертає List[GeneratedImage] з path та url)
                generated_images = await self._client.generate_primary_candidates(
                    prompt=prompt,
                    num_candidates=num_candidates,
                )

                # Копіюємо в директорію проекту
                scene_dir = settings.get_scene_dir(project_id, scene_number)
                scene_dir.mkdir(parents=True, exist_ok=True)

                final_paths = []
                for i, gen_img in enumerate(generated_images, 1):
                    dst_path = scene_dir / f"candidate_{i}.png"
                    shutil.copy(gen_img.path, dst_path)
                    final_paths.append(dst_path)

                    # Metadata для кожного кандидата (включаючи URL для валідних)
                    candidate_meta = {
                        "prompt": prompt,
                        "scene_number": scene_number,
                        "project_id": project_id,
                        "candidate_index": i,
                        "generation_mode": "web_primary",
                        "source": "higgsfield_web",
                        "image_url": gen_img.url,  # URL на HiggsField для відео генерації
                    }
                    await file_manager.save_json(
                        candidate_meta,
                        scene_dir / f"candidate_{i}_metadata.json"
                    )
                    logger.debug(f"  Candidate {i}: saved with URL {gen_img.url[:60]}...")

                logger.success(f"[Scene {scene_number}] Generated {len(final_paths)} PRIMARY candidates with URLs")
                return final_paths

            except Exception as e:
                last_error = e
                error_msg = str(e).lower()

                # Check if this is a browser window closed error
                if "no such window" in error_msg or "target window already closed" in error_msg:
                    logger.warning(f"[Scene {scene_number}] Browser window closed during generation")

                    if attempt <= max_retries:
                        logger.info(f"[Scene {scene_number}] Attempting browser reconnection...")
                        # Force browser restart on next _ensure_browser_started call
                        self._browser_started = False
                        if self._client:
                            try:
                                await self._client.force_shutdown()
                            except Exception:
                                pass
                        self._client = None
                        await asyncio.sleep(2)  # Brief pause before retry
                        continue

                # Non-recoverable error or max retries reached
                logger.error(f"[Scene {scene_number}] PRIMARY candidates generation failed: {e}")
                raise

        # Should not reach here, but just in case
        if last_error:
            raise last_error

    # ========================================================================
    # VIDEO GENERATION (сумісність з HiggsFieldClient)
    # ========================================================================

    async def generate_video(
        self,
        image_path: Path,
        prompt: str,
        scene_number: int,
        project_id: str = "test_project",
    ) -> Path:
        """
        Генерує відео з зображення.

        Args:
            image_path: Шлях до вихідного зображення
            prompt: Motion prompt для відео
            scene_number: Номер сцени
            project_id: ID проекту

        Returns:
            Path до збереженого відео
        """
        await self._ensure_browser_started()

        logger.info(f"[Scene {scene_number}] Generating video...")

        try:
            video_path = await self._client.generate_video(
                image_path=image_path,
                motion_prompt=prompt,
                duration=self._video_settings.duration,
            )

            # Копіюємо в директорію проекту
            scene_dir = settings.get_scene_dir(project_id, scene_number)
            scene_dir.mkdir(parents=True, exist_ok=True)

            final_path = scene_dir / "video.mp4"
            shutil.copy(video_path, final_path)

            # Metadata
            metadata = {
                "motion_prompt": prompt,
                "scene_number": scene_number,
                "project_id": project_id,
                "source_image": str(image_path),
                "duration": self._video_settings.duration,
                "model": self._video_settings.model,
                "source": "higgsfield_web",
            }
            await file_manager.save_json(metadata, scene_dir / "video_metadata.json")

            logger.success(f"[Scene {scene_number}] Video saved: {final_path}")
            return final_path

        except Exception as e:
            logger.error(f"[Scene {scene_number}] Video generation failed: {e}")
            raise

    async def generate_all_videos_parallel(
        self,
        scenes: list,
        project_id: str = "test_project",
    ) -> List[Path]:
        """
        Генерує відео для всіх сцен.

        Використовує SimpleVideoGenerator (послідовна генерація) якщо
        USE_SIMPLE_VIDEO_GENERATOR=True, інакше стару паралельну логіку.

        Args:
            scenes: Список сцен з полями:
                - scene_number: int
                - image_path: str (шлях до зображення)
                - video_prompt: str (motion prompt)
            project_id: ID проекту

        Returns:
            List[Path] шляхів до відео файлів
        """
        await self._ensure_browser_started()

        # Нова парадигма: SimpleVideoGenerator (послідовна, надійна)
        if settings.USE_SIMPLE_VIDEO_GENERATOR:
            return await self._generate_videos_simple(scenes, project_id)

        # Стара логіка: паралельна черга через KlingVideoGenerator
        return await self._generate_videos_parallel_legacy(scenes, project_id)

    async def _generate_videos_simple(
        self,
        scenes: list,
        project_id: str,
        max_retries_per_scene: int = 2,
    ) -> List[Path]:
        """
        Нова парадигма: послідовна генерація через SimpleVideoGenerator.

        Workflow для кожної сцени:
        1. Перейти на сторінку відео
        2. Видалити старе зображення
        3. Завантажити нове зображення
        4. Ввести motion prompt
        5. Натиснути Generate
        6. Дочекатися завершення
        7. Отримати URL з History panel
        8. Завантажити відео через HTTP

        Args:
            scenes: Список сцен
            project_id: ID проекту
            max_retries_per_scene: Максимум повторів на сцену при помилці браузера

        Returns:
            List[Path] шляхів до відео файлів
        """
        logger.info("")
        logger.info("=" * 60)
        logger.info(f"[SimpleVideoGenerator] GENERATING {len(scenes)} VIDEOS")
        logger.info("=" * 60)

        # Використовуємо браузер з _client
        generator = SimpleVideoGenerator(
            browser=self._client._browser,
            projects_dir=settings.PROJECTS_DIR
        )

        final_paths = []

        for scene in scenes:
            scene_num = scene['scene_number']
            image_path = Path(scene['image_path'])
            video_prompt = scene.get('video_prompt', '')

            # DEBUG: Log which image is used for each scene
            logger.info(f"[Scene {scene_num}] Using image: {image_path}")
            if not image_path.exists():
                logger.error(f"[Scene {scene_num}] IMAGE NOT FOUND: {image_path}")

            scene_dir = settings.get_scene_dir(project_id, scene_num)
            scene_dir.mkdir(parents=True, exist_ok=True)

            # Retry loop for browser reconnection
            scene_success = False
            for attempt in range(1, max_retries_per_scene + 2):
                try:
                    # Check browser is alive before each scene
                    if not self._client.is_browser_alive():
                        logger.warning(f"[Scene {scene_num}] Browser not alive, reconnecting...")
                        await self._ensure_browser_started()
                        # Reinitialize generator with new browser
                        generator = SimpleVideoGenerator(
                            browser=self._client._browser,
                            projects_dir=settings.PROJECTS_DIR
                        )

                    if attempt > 1:
                        logger.info(f"[Scene {scene_num}] Retry attempt {attempt}/{max_retries_per_scene + 1}")

                    result = await generator.generate_and_download(
                        image_path=image_path,
                        prompt=video_prompt,
                        output_dir=scene_dir,
                        scene_num=scene_num,
                        project_id=project_id
                    )

                    if result.success and result.video_path:
                        final_paths.append(result.video_path)
                        logger.success(f"[Scene {scene_num}] Video saved: {result.video_path}")
                        scene_success = True
                        break
                    else:
                        error_msg = str(result.error or "").lower()
                        # Check if browser-related error
                        if "no such window" in error_msg or "target window already closed" in error_msg:
                            logger.warning(f"[Scene {scene_num}] Browser window closed during generation")
                            if attempt <= max_retries_per_scene:
                                # Force browser restart
                                self._browser_started = False
                                if self._client:
                                    try:
                                        await self._client.force_shutdown()
                                    except Exception:
                                        pass
                                self._client = None
                                await asyncio.sleep(2)
                                await self._ensure_browser_started()
                                generator = SimpleVideoGenerator(
                                    browser=self._client._browser,
                                    projects_dir=settings.PROJECTS_DIR
                                )
                                continue

                        logger.error(f"[Scene {scene_num}] Video generation failed: {result.error}")
                        break

                except Exception as e:
                    error_msg = str(e).lower()
                    # Check if browser-related error
                    if "no such window" in error_msg or "target window already closed" in error_msg:
                        logger.warning(f"[Scene {scene_num}] Browser window closed: {e}")
                        if attempt <= max_retries_per_scene:
                            # Close old generator HTTP client before replacing
                            try:
                                await generator.close()
                            except Exception:
                                pass
                            # Force browser restart
                            self._browser_started = False
                            if self._client:
                                try:
                                    await self._client.force_shutdown()
                                except Exception:
                                    pass
                            self._client = None
                            await asyncio.sleep(2)
                            await self._ensure_browser_started()
                            generator = SimpleVideoGenerator(
                                browser=self._client._browser,
                                projects_dir=settings.PROJECTS_DIR
                            )
                            continue

                    logger.error(f"[Scene {scene_num}] Exception: {e}")
                    break

            if not scene_success:
                final_paths.append(None)

        # Close generator HTTP client
        await generator.close()

        success_count = sum(1 for p in final_paths if p is not None)
        logger.info("")
        logger.info("=" * 60)
        logger.info(f"[SimpleVideoGenerator] COMPLETE: {success_count}/{len(scenes)} videos")
        logger.info("=" * 60)

        # Повертаємо список з None для невдалих сцен, щоб зберегти порядок індексів
        return final_paths

    async def _generate_videos_parallel_legacy(
        self,
        scenes: list,
        project_id: str,
    ) -> List[Path]:
        """
        Стара логіка: паралельна генерація через KlingVideoGenerator.

        Використовується коли USE_SIMPLE_VIDEO_GENERATOR=False.

        Args:
            scenes: Список сцен
            project_id: ID проекту

        Returns:
            List[Path] шляхів до відео файлів
        """
        logger.info(f"[Legacy] Generating {len(scenes)} videos in parallel...")

        try:
            # Call client's parallel generation method
            video_paths = await self._client.generate_all_videos_parallel(
                scenes=scenes,
                download_dir=self._download_dir
            )

            # Copy videos to project directories
            final_paths = []
            for i, video_path in enumerate(video_paths):
                if i < len(scenes):
                    scene_num = scenes[i]['scene_number']
                    scene_dir = settings.get_scene_dir(project_id, scene_num)
                    scene_dir.mkdir(parents=True, exist_ok=True)

                    final_path = scene_dir / "video.mp4"
                    shutil.copy(video_path, final_path)
                    final_paths.append(final_path)

                    logger.success(f"[Scene {scene_num}] Video saved: {final_path}")

            return final_paths

        except Exception as e:
            logger.error(f"Parallel video generation failed: {e}")
            raise

    async def generate_all_images_parallel(
        self,
        scenes: list,
        project_id: str = "test_project",
        reference_image: Optional[Path] = None,
        reference_url: Optional[str] = None,
    ) -> List[Path]:
        """
        Генерує зображення для всіх сцен паралельно.

        ВАЖЛИВО: Сцени мають бути вже відсортовані!
        - Спочатку INDEPENDENT (без референсу)
        - Потім REQUIRES_REF/LOOP_CLOSE (з референсом)

        Workflow:
        1. Всі зображення ставляться в чергу послідовно (15 сек між ними)
        2. Higgsfield генерує їх паралельно
        3. Чекаємо поки всі готові
        4. Завантажуємо результати

        Args:
            scenes: Список сцен з полями:
            reference_url: URL референсної картинки на HiggsField (для поиска по asset_id)
                - scene_number: int
                - image_prompt: str
                - reference_image: Optional[str] (шлях до референсу)
            project_id: ID проекту
            reference_image: Спільний референс для REQUIRES_REF сцен

        Returns:
            List[Path] шляхів до зображень
        """
        await self._ensure_browser_started()

        logger.info("=" * 60)
        logger.info(f"[VISUAL_ENGINE] PARALLEL IMAGE GENERATION: {len(scenes)} scenes")
        logger.info(f"[VISUAL_ENGINE] reference_image parameter: {reference_image}")
        if reference_image:
            logger.info(f"[VISUAL_ENGINE] reference_image exists: {reference_image.exists()}")
        logger.info("=" * 60)

        # Prepare scenes data with reference paths
        prepared_scenes = []
        for scene in scenes:
            ref_from_scene = scene.get('reference_image')
            ref_to_use = ref_from_scene or (str(reference_image) if reference_image else None)

            scene_data = {
                'scene_number': scene.get('scene_number'),
                'image_prompt': scene.get('image_prompt', ''),
                'reference_type': scene.get('reference_type', 'REQUIRES_REF'),
                'reference_image': ref_to_use
            }
            prepared_scenes.append(scene_data)
            logger.info(f"[VISUAL_ENGINE] Scene {scene.get('scene_number')}: ref_type={scene.get('reference_type')}, ref_image={ref_to_use}")

        try:
            # Call client's parallel generation method
            # Returns List[GeneratedImage] with path and url
            generated_images = await self._client.generate_all_images_parallel(
                scenes=prepared_scenes,
                download_dir=self._download_dir,
                reference_url=reference_url
            )

            # Log how many images were returned vs expected
            logger.info(f"[VISUAL_ENGINE] Generated {len(generated_images)}/{len(scenes)} images")

            if len(generated_images) < len(scenes):
                logger.error(f"[VISUAL_ENGINE] MISSING IMAGES! Expected {len(scenes)}, got {len(generated_images)}")
                logger.error(f"[VISUAL_ENGINE] {len(scenes) - len(generated_images)} scene(s) may be missing! This will cause incomplete final video.")

            # NOTE: Order is already correct after reverse in higgsfield_image.py
            # Scenes are queued: 2,3,4,5,6 -> History shows: 6,5,4,3,2 -> Reversed: 2,3,4,5,6

            # Copy images to project directories and save URLs to metadata
            final_paths = []
            for i, gen_img in enumerate(generated_images):
                if i < len(scenes):
                    scene_num = scenes[i]['scene_number']
                    scene_dir = settings.get_scene_dir(project_id, scene_num)
                    scene_dir.mkdir(parents=True, exist_ok=True)

                    final_path = scene_dir / "image.png"
                    # Use .path attribute from GeneratedImage
                    shutil.copy(gen_img.path, final_path)
                    final_paths.append(final_path)

                    # Save image_url to metadata for FAST video generation
                    metadata_path = scene_dir / "metadata.json"
                    metadata = {}
                    if metadata_path.exists():
                        try:
                            import json
                            with open(metadata_path, "r", encoding="utf-8") as f:
                                metadata = json.load(f)
                        except Exception:
                            pass

                    metadata["image_url"] = gen_img.url
                    with open(metadata_path, "w", encoding="utf-8") as f:
                        import json
                        json.dump(metadata, f, indent=2, ensure_ascii=False)

                    logger.success(f"[Scene {scene_num}] Image saved: {final_path}")
                    logger.info(f"[Scene {scene_num}] URL saved: {gen_img.url[:60]}...")

            return final_paths

        except Exception as e:
            logger.error(f"Parallel image generation failed: {e}")
            raise

    # ========================================================================
    # REFERENCE IMAGE HELPERS (сумісність з HiggsFieldClient)
    # ========================================================================

    def get_reference_image_url(
        self,
        project_id: str,
        scene_number: int,
    ) -> Optional[str]:
        """
        Отримує URL/шлях до reference зображення.

        Для web adapter повертає локальний шлях замість URL.

        Args:
            project_id: ID проекту
            scene_number: Номер сцени

        Returns:
            Шлях до зображення або None
        """
        key = (project_id, scene_number)
        if key in self._reference_images:
            path = self._reference_images[key]
            if path.exists():
                return str(path)

        # Спробувати знайти на диску
        scene_dir = settings.get_scene_dir(project_id, scene_number)
        image_path = scene_dir / "image.png"

        if image_path.exists():
            self._reference_images[key] = image_path
            return str(image_path)

        return None

    # ========================================================================
    # API STATUS CHECK (для сумісності)
    # ========================================================================

    async def check_api_status(self) -> dict:
        """
        Перевіряє статус (для web adapter - перевіряє AdsPower).

        Returns:
            Dict з інформацією про статус
        """
        try:
            # Перевіряємо чи AdsPower доступний
            import httpx

            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{settings.ADSPOWER_BASE_URL}/api/v1/browser/active",
                    params={"serial_number": settings.ADSPOWER_PROFILE_ID}
                )

                if response.status_code == 200:
                    return {
                        "status": "ok",
                        "message": "✅ AdsPower connected, ready to use",
                        "has_credits": True,  # Unlimited subscription
                        "details": "Using HiggsFieldWebClient (Ultimate)"
                    }
                else:
                    return {
                        "status": "error",
                        "message": "⚠️ AdsPower browser not active",
                        "has_credits": True,
                        "details": "Start AdsPower and browser profile first"
                    }

        except Exception as e:
            return {
                "status": "error",
                "message": "❌ AdsPower connection error",
                "has_credits": False,
                "details": str(e)
            }


# ============================================================================
# FACTORY FUNCTION
# ============================================================================

def create_visual_engine():
    """
    Створює visual engine залежно від конфігурації.

    Returns:
        HiggsFieldWebAdapter якщо HIGGSFIELD_WEB_ENABLED=true,
        інакше HiggsFieldClient (API)
    """
    if settings.HIGGSFIELD_WEB_ENABLED:
        logger.info("Using HiggsFieldWebAdapter (browser automation)")
        return HiggsFieldWebAdapter()
    else:
        from app.services.visual_engine import HiggsFieldClient
        logger.info("Using HiggsFieldClient (API)")
        return HiggsFieldClient()


# ============================================================================
# EXPORT
# ============================================================================

__all__ = ["HiggsFieldWebAdapter", "create_visual_engine"]
