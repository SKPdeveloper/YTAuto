"""
Universal Higgsfield Video Generator - Kling 2.6

Универсальный генератор видео для любого проекта.
Алгоритм: загрузить картинку -> ввести prompt -> генерировать -> скачать в папку сцены
"""

import asyncio
import time
import json
import httpx
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable, Awaitable
from dataclasses import dataclass
from datetime import datetime

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from loguru import logger

from app.clients.adspower_client import AdsPowerClient


HIGGSFIELD_VIDEO_URL = "https://higgsfield.ai/create/video"

# Type alias для progress callback
ProgressCallback = Callable[[int, int, str], Awaitable[None]]  # (current, total, message)


@dataclass
class VideoResult:
    """Результат генерации видео"""
    scene_num: int
    video_path: Optional[Path] = None
    video_url: Optional[str] = None
    success: bool = False
    error: Optional[str] = None
    duration_sec: float = 0.0  # Время генерации в секундах


class SimpleVideoGenerator:
    """
    Универсальный генератор видео через Higgsfield Kling 2.6.

    Usage:
        from app.clients.adspower_client import AdsPowerClient, AdsPowerConfig
        from app.clients.higgsfield_video_simple import SimpleVideoGenerator

        browser = AdsPowerClient(config)
        await browser.start_browser()

        gen = SimpleVideoGenerator(browser)

        # Для одной сцены
        result = await gen.generate_and_download(image_path, prompt, output_dir, scene_num)

        # Для всего проекта
        results = await gen.generate_project("proj_xxx")
    """

    def __init__(
        self,
        browser: AdsPowerClient,
        projects_dir: Path = None,
        progress_callback: Optional[ProgressCallback] = None,
    ):
        self.browser = browser
        self.projects_dir = projects_dir or Path("D:/YTAuto/YTAuto/projects")
        self._http_client: Optional[httpx.AsyncClient] = None
        self._progress_callback = progress_callback

    async def close(self) -> None:
        """Close HTTP client to release resources."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    @property
    def driver(self):
        return self.browser.driver

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    async def generate_and_download(
        self,
        image_path: Path,
        prompt: str,
        output_dir: Path,
        scene_num: int = 1,
        project_id: str = ""
    ) -> VideoResult:
        """
        Сгенерировать и скачать видео для одной сцены.

        Args:
            image_path: Путь к изображению
            prompt: Video prompt для генерации
            output_dir: Папка для сохранения видео
            scene_num: Номер сцены
            project_id: ID проекта (для логирования)

        Returns:
            VideoResult с результатом
        """
        result = VideoResult(scene_num=scene_num)
        prefix = f"[{project_id}]" if project_id else ""
        start_time = time.time()

        try:
            logger.info(f"{prefix}[Scene {scene_num}] Starting video generation")
            logger.info(f"{prefix}[Scene {scene_num}] Image: {image_path.name}")
            logger.info(f"{prefix}[Scene {scene_num}] Prompt: {prompt[:60]}...")

            # DEBUG: Скриншот перед началом
            await self.take_screenshot(f"scene{scene_num}_01_before_start.png")

            # 1. Перейти на чистую страницу видео (force refresh для каждой сцены)
            await self._ensure_video_page(force_refresh=True)
            await self.take_screenshot(f"scene{scene_num}_02_video_page.png")

            # 2. Загрузить изображение
            await self._upload_image(image_path)
            await self.take_screenshot(f"scene{scene_num}_03_image_uploaded.png")

            # 3. Ввести prompt
            await self._enter_prompt(prompt)
            await self.take_screenshot(f"scene{scene_num}_04_prompt_entered.png")

            # 4. Нажать Generate
            await self._click_generate()
            await self.take_screenshot(f"scene{scene_num}_05_generate_clicked.png")

            # 5. Дождаться завершения генерации (2-5 минут)
            logger.info(f"{prefix}[Scene {scene_num}] Waiting for generation (2-5 min)...")
            await self._wait_for_generation_complete(timeout=420)
            await self.take_screenshot(f"scene{scene_num}_06_generation_complete.png")

            # 6. Дать странице обновиться
            logger.debug(f"{prefix}[Scene {scene_num}] Waiting for video to appear...")
            await asyncio.sleep(8)

            # 7. Скачать видео (увеличенный таймаут для поиска)
            video_url = await self._get_latest_video_url(max_attempts=20)
            if video_url:
                video_path = output_dir / "video.mp4"
                await self._download_video(video_url, video_path)

                result.video_url = video_url
                result.video_path = video_path
                result.success = True
                result.duration_sec = time.time() - start_time

                # 9. Сохранить метаданные
                await self._save_video_metadata(
                    output_dir=output_dir,
                    scene_num=scene_num,
                    project_id=project_id,
                    prompt=prompt,
                    video_url=video_url,
                    image_path=image_path,
                    duration_sec=result.duration_sec
                )

                logger.success(f"{prefix}[Scene {scene_num}] Video saved: {video_path} ({result.duration_sec:.1f}s)")
            else:
                result.error = "Video URL not found after generation"
                result.duration_sec = time.time() - start_time
                logger.error(f"{prefix}[Scene {scene_num}] {result.error}")

        except Exception as e:
            result.error = str(e)
            result.duration_sec = time.time() - start_time
            logger.error(f"{prefix}[Scene {scene_num}] Error: {e}")

            # Скриншот при ошибке
            await self.take_screenshot(f"scene{scene_num}_ERROR.png")

        return result

    async def _save_video_metadata(
        self,
        output_dir: Path,
        scene_num: int,
        project_id: str,
        prompt: str,
        video_url: str,
        image_path: Path,
        duration_sec: float
    ) -> None:
        """Сохранить метаданные видео в JSON файл."""
        metadata = {
            "scene_number": scene_num,
            "project_id": project_id,
            "motion_prompt": prompt,
            "video_url": video_url,
            "source_image": str(image_path),
            "model": "Kling 2.6",
            "duration": 10,
            "aspect_ratio": "9:16",
            "source": "higgsfield_web_simple",
            "generation_time_sec": round(duration_sec, 1),
            "generated_at": datetime.now().isoformat()
        }

        metadata_path = output_dir / "video_metadata.json"
        try:
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            logger.debug(f"Saved metadata: {metadata_path}")
        except Exception as e:
            logger.warning(f"Failed to save metadata: {e}")

    async def generate_project(self, project_id: str) -> List[VideoResult]:
        """
        Сгенерировать видео для всех сцен проекта.

        Args:
            project_id: ID проекта (например "proj_0f379e1a24ff")

        Returns:
            Список VideoResult для каждой сцены
        """
        project_dir = self.projects_dir / project_id
        brief_path = project_dir / "project_brief.json"

        if not brief_path.exists():
            raise FileNotFoundError(f"Project brief not found: {brief_path}")

        with open(brief_path, 'r', encoding='utf-8') as f:
            brief = json.load(f)

        title = brief.get('youtube', {}).get('title', 'Unknown')
        logger.info(f"Project: {project_id}")
        logger.info(f"Title: {title}")

        results = []
        scenes_to_generate = []

        # Собрать сцены для генерации
        for scene_data in brief.get("scenes", []):
            scene_num = scene_data["scene_number"]
            video_prompt = scene_data.get("video_prompt", "")

            scene_dir = project_dir / f"scene_{scene_num}"
            image_path = scene_dir / "image.png"
            video_path = scene_dir / "video.mp4"

            if video_path.exists():
                logger.info(f"[Scene {scene_num}] Video exists, skipping")
                results.append(VideoResult(scene_num=scene_num, video_path=video_path, success=True))
                continue

            if not image_path.exists():
                logger.warning(f"[Scene {scene_num}] No image, skipping")
                results.append(VideoResult(scene_num=scene_num, error="No image"))
                continue

            if not video_prompt:
                logger.warning(f"[Scene {scene_num}] No prompt, skipping")
                results.append(VideoResult(scene_num=scene_num, error="No prompt"))
                continue

            scenes_to_generate.append({
                "scene_num": scene_num,
                "image_path": image_path,
                "prompt": video_prompt,
                "output_dir": scene_dir
            })

        logger.info(f"Scenes to generate: {len(scenes_to_generate)}")

        # Генерировать каждую сцену
        for scene in scenes_to_generate:
            result = await self.generate_and_download(
                image_path=scene["image_path"],
                prompt=scene["prompt"],
                output_dir=scene["output_dir"],
                scene_num=scene["scene_num"],
                project_id=project_id
            )
            results.append(result)

            # Пауза между сценами
            if result.success:
                await asyncio.sleep(3)

        # Отчет
        success_count = sum(1 for r in results if r.success)
        logger.info(f"Generation complete: {success_count}/{len(results)} successful")

        return results

    # =========================================================================
    # PRIVATE METHODS
    # =========================================================================

    async def _check_browser_alive(self) -> bool:
        """Проверить что браузер ещё открыт"""
        try:
            # Попытка получить title проверяет что браузер жив
            _ = await asyncio.to_thread(lambda: self.driver.title)
            return True
        except Exception as e:
            logger.error(f"Browser check failed: {e}")
            return False

    async def take_screenshot(self, filename: str = "debug_screenshot.png") -> Optional[Path]:
        """Сделать скриншот браузера для отладки"""
        try:
            screenshot_dir = self.projects_dir / "screenshots"
            screenshot_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%H%M%S")
            screenshot_path = screenshot_dir / f"{timestamp}_{filename}"

            await asyncio.to_thread(self.driver.save_screenshot, str(screenshot_path))
            logger.debug(f"Screenshot saved: {screenshot_path}")
            return screenshot_path
        except Exception as e:
            logger.warning(f"Failed to take screenshot: {e}")
            return None

    async def _ensure_video_page(self, force_refresh: bool = False) -> None:
        """
        Убедиться что мы на чистой странице видео.

        Args:
            force_refresh: Принудительно обновить страницу
        """
        # Проверка что браузер жив
        if not await self._check_browser_alive():
            raise Exception("Browser window was closed externally")

        try:
            current_url = await asyncio.to_thread(lambda: self.driver.current_url)
        except Exception as e:
            raise Exception(f"Failed to get current URL: {e}")

        if force_refresh or "higgsfield.ai/create/video" not in current_url:
            # Navigate away first to clear cached React state (image/prompt from previous generation)
            logger.debug("Clearing page state (about:blank)...")
            await asyncio.to_thread(self.driver.get, "about:blank")
            await asyncio.sleep(1)

            logger.debug(f"Navigating to {HIGGSFIELD_VIDEO_URL}")
            await asyncio.to_thread(self.driver.get, HIGGSFIELD_VIDEO_URL)
            await asyncio.sleep(4)

            # Wait for page to be ready
            for attempt in range(10):
                file_inputs = await asyncio.to_thread(
                    self.driver.find_elements,
                    By.CSS_SELECTOR,
                    'input[type="file"]'
                )
                if file_inputs:
                    logger.debug(f"Video page ready (file input found)")
                    return
                await asyncio.sleep(1)

            logger.warning("Video page loaded but file input not found")

    async def _click_change_button(self) -> bool:
        """Кликнуть кнопку Change чтобы заменить изображение"""
        try:
            change_btn = await asyncio.to_thread(
                self.driver.execute_script,
                """
                var btns = document.querySelectorAll('button');
                for (var btn of btns) {
                    if (btn.textContent.toLowerCase().includes('change')) {
                        return btn;
                    }
                }
                return null;
                """
            )
            if change_btn:
                logger.debug("Found Change button, clicking...")
                await asyncio.to_thread(
                    self.driver.execute_script,
                    "arguments[0].click();",
                    change_btn
                )
                await asyncio.sleep(2)
                return True
            return False
        except Exception as e:
            logger.debug(f"Failed to click Change button: {e}")
            return False

    async def _remove_current_image(self) -> None:
        """Удалить текущее изображение (кликнуть X)"""
        try:
            x_btn = await asyncio.to_thread(
                self.driver.execute_script,
                """
                var btns = document.querySelectorAll('button');
                for (var btn of btns) {
                    var rect = btn.getBoundingClientRect();
                    // X button is small, positioned in upper-left area of the image preview
                    if (rect.width < 35 && rect.height < 35 && rect.y > 180 && rect.y < 400 && rect.x < 250 && rect.x > 100) {
                        return btn;
                    }
                }
                return null;
                """
            )
            if x_btn:
                await asyncio.to_thread(x_btn.click)
                await asyncio.sleep(2)
                logger.debug("Removed current image")
        except Exception:
            pass

    async def _clear_image_via_js(self) -> bool:
        """
        Clear existing image using JavaScript DOM traversal.

        More robust than pixel-based detection — searches for close/remove buttons
        by their SVG content (X icon) or aria attributes, regardless of position.
        """
        try:
            result = await asyncio.to_thread(
                self.driver.execute_script,
                """
                // Strategy 1: Find button with SVG close icon (X pattern) in the left panel
                // The left panel is typically within the first 300px of the page
                var allBtns = document.querySelectorAll('button');
                for (var btn of allBtns) {
                    var rect = btn.getBoundingClientRect();
                    // Must be in left panel area (x < 300) and small (likely a close button)
                    if (rect.width > 50 || rect.height > 50 || rect.x > 300) continue;
                    if (rect.width < 8 || rect.height < 8) continue;

                    // Check for SVG with close/X icon (path data with diagonal lines)
                    var svg = btn.querySelector('svg');
                    if (svg) {
                        var paths = svg.querySelectorAll('path, line');
                        if (paths.length >= 1 && paths.length <= 4) {
                            // Small button with simple SVG = likely close/remove button
                            btn.click();
                            return 'clicked_svg_btn';
                        }
                    }

                    // Check text content for X or ×
                    var text = btn.textContent.trim();
                    if (text === '×' || text === 'x' || text === 'X' || text === '✕') {
                        btn.click();
                        return 'clicked_text_btn';
                    }
                }

                // Strategy 2: Find by aria-label
                var closeBtns = document.querySelectorAll('[aria-label*="close"], [aria-label*="remove"], [aria-label*="delete"], [aria-label*="clear"]');
                for (var btn of closeBtns) {
                    var rect = btn.getBoundingClientRect();
                    if (rect.x < 300 && rect.width < 50) {
                        btn.click();
                        return 'clicked_aria_btn';
                    }
                }

                // Strategy 3: Find any small absolute-positioned button overlaying an image
                var imgs = document.querySelectorAll('img');
                for (var img of imgs) {
                    var imgRect = img.getBoundingClientRect();
                    if (imgRect.x > 300 || imgRect.width > 200) continue;  // Not in left panel
                    // Find buttons near this image's top-right corner
                    for (var btn of allBtns) {
                        var btnRect = btn.getBoundingClientRect();
                        if (btnRect.width < 40 && btnRect.height < 40 &&
                            Math.abs(btnRect.x - (imgRect.x + imgRect.width)) < 30 &&
                            Math.abs(btnRect.y - imgRect.y) < 30) {
                            btn.click();
                            return 'clicked_overlay_btn';
                        }
                    }
                }

                return null;
                """
            )
            if result:
                logger.info(f"Cleared image via JS: {result}")
                return True
            logger.debug("JS image clearing: no suitable button found")
            return False
        except Exception as e:
            logger.warning(f"JS image clearing failed: {e}")
            return False

    async def _clear_preset_image(self) -> bool:
        """
        Удалить текущее preset/existing изображение кликом на X кнопку.

        В новом UI Higgsfield по умолчанию показывается preset стиль или
        остаётся предыдущее загруженное изображение.
        Нужно кликнуть X чтобы очистить и получить возможность загрузить своё изображение.

        Returns:
            True если изображение было очищено, False если не найдено
        """
        try:
            # Метод 1: Найти маленькую кнопку X на превью по позиции
            x_btn = await asyncio.to_thread(
                self.driver.execute_script,
                """
                var btns = document.querySelectorAll('button');
                for (var btn of btns) {
                    var rect = btn.getBoundingClientRect();
                    // X кнопка: маленькая (15-35px), в левой части экрана (x < 250), в области превью (y 150-450)
                    if (rect.width > 12 && rect.width < 40 &&
                        rect.height > 12 && rect.height < 40 &&
                        rect.x < 250 && rect.x > 50 &&
                        rect.y > 150 && rect.y < 450) {
                        // Дополнительная проверка - кнопка должна содержать SVG или быть круглой
                        var svg = btn.querySelector('svg');
                        var hasRoundClass = btn.className.includes('rounded');
                        if (svg || hasRoundClass || rect.width === rect.height) {
                            return btn;
                        }
                    }
                }
                return null;
                """
            )

            if x_btn:
                logger.debug(f"Found X button via position, clicking via JavaScript...")
                # Use JavaScript click - more reliable than Selenium click
                await asyncio.to_thread(
                    self.driver.execute_script,
                    "arguments[0].click();",
                    x_btn
                )
                await asyncio.sleep(2)
                return True

            # Метод 2: Найти кнопку по SVG с path для X
            x_btn = await asyncio.to_thread(
                self.driver.execute_script,
                """
                // Ищем SVG иконки закрытия (X)
                var svgs = document.querySelectorAll('svg');
                for (var svg of svgs) {
                    var paths = svg.querySelectorAll('path');
                    for (var path of paths) {
                        var d = path.getAttribute('d') || '';
                        // Типичные паттерны для X иконки
                        if (d.includes('M6') && d.includes('18') ||
                            d.toLowerCase().includes('close') ||
                            d.includes('L12') && d.includes('L6')) {
                            var btn = svg.closest('button');
                            if (btn) {
                                var rect = btn.getBoundingClientRect();
                                // Кнопка должна быть в левой части экрана
                                if (rect.x < 250 && rect.y < 450) {
                                    return btn;
                                }
                            }
                        }
                    }
                }
                return null;
                """
            )

            if x_btn:
                logger.debug(f"Found X button via SVG, clicking via JavaScript...")
                await asyncio.to_thread(
                    self.driver.execute_script,
                    "arguments[0].click();",
                    x_btn
                )
                await asyncio.sleep(2)
                return True

            # Метод 3: Найти любую кнопку с X-подобной иконкой в области превью
            x_btn = await asyncio.to_thread(
                self.driver.execute_script,
                """
                // Ищем кнопки с X в области превью (более агрессивный поиск)
                var btns = document.querySelectorAll('button');
                for (var btn of btns) {
                    var rect = btn.getBoundingClientRect();
                    // Любая маленькая кнопка в области превью
                    if (rect.width < 50 && rect.height < 50 &&
                        rect.x > 80 && rect.x < 200 &&
                        rect.y > 100 && rect.y < 350) {
                        // Проверяем что это кнопка удаления (имеет SVG или текст X)
                        var hasX = btn.textContent.includes('×') ||
                                   btn.textContent.includes('x') ||
                                   btn.querySelector('svg') !== null;
                        if (hasX) {
                            return btn;
                        }
                    }
                }
                return null;
                """
            )

            if x_btn:
                logger.debug(f"Found X button via aggressive search, clicking...")
                await asyncio.to_thread(
                    self.driver.execute_script,
                    "arguments[0].click();",
                    x_btn
                )
                await asyncio.sleep(2)
                return True

            logger.debug("No X button found to clear image")
            return False

        except Exception as e:
            logger.warning(f"Failed to clear preset: {e}")
            return False

    async def _upload_image(self, image_path: Path) -> None:
        """Загрузить изображение (с поддержкой нового Higgsfield UI)"""
        logger.debug(f"Uploading: {image_path}")

        # 1. Check if file input already exists (clean page after about:blank navigation)
        file_inputs = await asyncio.to_thread(
            self.driver.find_elements,
            By.CSS_SELECTOR,
            'input[type="file"]'
        )

        if file_inputs:
            logger.info("File input found immediately - clean page")
        else:
            # 2. Page has cached image — need to clear it
            logger.info("No file input - page has cached image, clearing...")

            # Method A: Try pixel-based X button (legacy)
            for attempt in range(3):
                cleared = await self._clear_preset_image()
                if cleared:
                    logger.info(f"Cleared existing image (attempt {attempt + 1})")
                    await asyncio.sleep(2)
                    file_inputs = await asyncio.to_thread(
                        self.driver.find_elements,
                        By.CSS_SELECTOR,
                        'input[type="file"]'
                    )
                    if file_inputs:
                        logger.info("File input appeared after clearing!")
                        break
                else:
                    break

            # Method B: Try JavaScript to find and click ANY close/remove button near image preview
            if not file_inputs:
                logger.info("Trying JS-based image removal...")
                cleared_js = await self._clear_image_via_js()
                if cleared_js:
                    await asyncio.sleep(2)
                    file_inputs = await asyncio.to_thread(
                        self.driver.find_elements,
                        By.CSS_SELECTOR,
                        'input[type="file"]'
                    )

            # Method C: Try "Change" button
            if not file_inputs:
                change_btns = await asyncio.to_thread(
                    self.driver.find_elements,
                    By.XPATH,
                    "//button[contains(., 'Change')]"
                )
                if change_btns:
                    logger.debug("Clicking 'Change' button...")
                    await asyncio.to_thread(
                        self.driver.execute_script,
                        "arguments[0].click();",
                        change_btns[0]
                    )
                    await asyncio.sleep(2)
                    file_inputs = await asyncio.to_thread(
                        self.driver.find_elements,
                        By.CSS_SELECTOR,
                        'input[type="file"]'
                    )

            # Method D: Wait for file input (maybe clearing is async)
            if not file_inputs:
                logger.debug("Waiting for file input to appear...")
                for attempt in range(10):
                    file_inputs = await asyncio.to_thread(
                        self.driver.find_elements,
                        By.CSS_SELECTOR,
                        'input[type="file"]'
                    )
                    if file_inputs:
                        logger.debug(f"File input appeared after {attempt}s")
                        break
                    await asyncio.sleep(1)

            # Method E (last resort): Force page reload via JS and try again
            if not file_inputs:
                logger.warning("All clearing methods failed — force reloading page...")
                await asyncio.to_thread(
                    self.driver.execute_script,
                    "window.localStorage.clear(); window.sessionStorage.clear();"
                )
                await asyncio.to_thread(self.driver.get, "about:blank")
                await asyncio.sleep(1)
                await asyncio.to_thread(self.driver.get, HIGGSFIELD_VIDEO_URL)
                await asyncio.sleep(5)
                for attempt in range(15):
                    file_inputs = await asyncio.to_thread(
                        self.driver.find_elements,
                        By.CSS_SELECTOR,
                        'input[type="file"]'
                    )
                    if file_inputs:
                        logger.info(f"File input found after localStorage clear + reload")
                        break
                    await asyncio.sleep(1)

        # Final check
        if not file_inputs:
            raise Exception("File input not found after all attempts (5 methods tried)")

        # 5. Загрузить файл
        logger.debug(f"Sending file to input...")
        await asyncio.to_thread(file_inputs[0].send_keys, str(image_path.absolute()))

        # 6. Ждать завершения загрузки
        logger.debug("Waiting for upload...")
        for i in range(120):
            body_text = await asyncio.to_thread(
                lambda: self.driver.find_element(By.TAG_NAME, 'body').text.lower()
            )
            if 'uploading' not in body_text:
                logger.debug(f"Upload complete ({i}s)")
                break
            await asyncio.sleep(1)

        await asyncio.sleep(3)

    async def _enter_prompt(self, prompt: str) -> None:
        """Ввести prompt"""
        textarea = await asyncio.to_thread(
            self.driver.find_element,
            By.CSS_SELECTOR,
            'textarea'
        )
        await asyncio.to_thread(textarea.clear)
        await asyncio.to_thread(textarea.send_keys, prompt)
        await asyncio.sleep(1)

    async def _click_generate(self) -> None:
        """Нажать Generate"""
        gen_btn = await asyncio.to_thread(
            self.driver.find_element,
            By.XPATH,
            "//button[contains(., 'Generate')]"
        )
        await asyncio.to_thread(gen_btn.click)
        await asyncio.sleep(3)

        # Проверить что генерация началась
        body_text = await asyncio.to_thread(
            lambda: self.driver.find_element(By.TAG_NAME, 'body').text.lower()
        )
        if 'in progress' in body_text or 'in queue' in body_text:
            logger.debug("Generation started")
        else:
            logger.warning("Generation status unclear")

    async def _wait_for_generation_complete(self, timeout: int = 420) -> None:
        """
        Дождаться завершения генерации.

        Проверяет статусы: "in progress", "in queue", "generating".
        Также проверяет появление видео в history.
        """
        detected_start = False

        for i in range(timeout // 5):
            try:
                body_text = await asyncio.to_thread(
                    lambda: self.driver.find_element(By.TAG_NAME, 'body').text.lower()
                )
            except Exception:
                await asyncio.sleep(5)
                continue

            in_progress = 'in progress' in body_text
            in_queue = 'in queue' in body_text
            generating = 'generating' in body_text

            if in_progress or in_queue or generating:
                detected_start = True
                if i % 6 == 0:  # Log every 30s
                    status = "in progress" if in_progress else ("in queue" if in_queue else "generating")
                    logger.debug(f"Generation {status}... ({i*5}s)")
                await asyncio.sleep(5)
            else:
                if detected_start:
                    # Было в процессе, теперь готово
                    logger.info(f"Generation complete ({i*5}s)")
                    return
                else:
                    # Ждем пока генерация начнется
                    if i > 12:  # После 60 секунд (was 30s — too short)
                        logger.warning(f"No generation status detected after {i*5}s — generation may not have started")
                        return
                    await asyncio.sleep(5)

        logger.warning(f"Generation timeout after {timeout}s")

    async def _get_latest_video_url(self, max_attempts: int = 10) -> Optional[str]:
        """Получить URL последнего видео через History panel"""

        for attempt in range(max_attempts):
            try:
                # 1. Click History button to ensure panel is open
                history_btns = await asyncio.to_thread(
                    self.driver.find_elements,
                    By.XPATH,
                    "//button[contains(., 'History')]"
                )
                if history_btns:
                    await asyncio.to_thread(history_btns[0].click)
                    await asyncio.sleep(2)

                # 2. Click on first history item (most recent video)
                overlay_btns = await asyncio.to_thread(
                    self.driver.find_elements,
                    By.CSS_SELECTOR,
                    'button.absolute.inset-0.cursor-pointer'
                )
                if overlay_btns:
                    logger.debug(f"Clicking first history item...")
                    await asyncio.to_thread(overlay_btns[0].click)
                    await asyncio.sleep(3)

                    # 3. Get cloudfront video URL from modal
                    videos = await asyncio.to_thread(
                        self.driver.find_elements,
                        By.TAG_NAME,
                        'video'
                    )
                    for v in videos:
                        src = await asyncio.to_thread(v.get_attribute, 'src')
                        if src and 'cloudfront' in src:
                            logger.debug(f"Found cloudfront video URL")
                            # Close modal by pressing ESC
                            await asyncio.to_thread(
                                self.driver.find_element,
                                By.TAG_NAME, 'body'
                            )
                            body = await asyncio.to_thread(
                                self.driver.find_element,
                                By.TAG_NAME, 'body'
                            )
                            await asyncio.to_thread(body.send_keys, Keys.ESCAPE)
                            await asyncio.sleep(1)
                            return src

                    # Close modal if no cloudfront found
                    body = await asyncio.to_thread(
                        self.driver.find_element,
                        By.TAG_NAME, 'body'
                    )
                    await asyncio.to_thread(body.send_keys, Keys.ESCAPE)
                    await asyncio.sleep(1)

            except Exception as e:
                logger.debug(f"Attempt {attempt + 1} error: {e}")

            logger.debug(f"Video not found yet, attempt {attempt + 1}/{max_attempts}")
            await asyncio.sleep(3)

        return None

    async def _download_video(self, url: str, output_path: Path) -> None:
        """Скачать видео"""
        logger.debug(f"Downloading to {output_path}")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        if not self._http_client:
            self._http_client = httpx.AsyncClient(timeout=120)

        response = await self._http_client.get(url)
        response.raise_for_status()

        with open(output_path, 'wb') as f:
            f.write(response.content)

        size_mb = output_path.stat().st_size / 1024 / 1024
        logger.debug(f"Downloaded: {size_mb:.1f} MB")


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

async def generate_videos_for_project(
    browser: AdsPowerClient,
    project_id: str,
    projects_dir: Path = None
) -> List[VideoResult]:
    """
    Удобная функция для генерации видео всего проекта.

    Args:
        browser: Подключенный AdsPowerClient
        project_id: ID проекта
        projects_dir: Папка с проектами (опционально)

    Returns:
        Список результатов
    """
    generator = SimpleVideoGenerator(browser, projects_dir)
    return await generator.generate_project(project_id)


def get_pending_scenes(project_id: str, projects_dir: Path = None) -> List[dict]:
    """
    Получить список сцен без видео.

    Args:
        project_id: ID проекта
        projects_dir: Папка с проектами

    Returns:
        Список сцен [{scene_num, image_path, prompt}, ...]
    """
    projects_dir = projects_dir or Path("D:/YTAuto/YTAuto/projects")
    project_dir = projects_dir / project_id
    brief_path = project_dir / "project_brief.json"

    if not brief_path.exists():
        return []

    with open(brief_path, 'r', encoding='utf-8') as f:
        brief = json.load(f)

    pending = []
    for scene_data in brief.get("scenes", []):
        scene_num = scene_data["scene_number"]
        video_prompt = scene_data.get("video_prompt", "")

        if not video_prompt:
            continue

        scene_dir = project_dir / f"scene_{scene_num}"
        image_path = scene_dir / "image.png"
        video_path = scene_dir / "video.mp4"

        if image_path.exists() and not video_path.exists():
            pending.append({
                "scene_num": scene_num,
                "image_path": str(image_path),
                "prompt": video_prompt
            })

    return pending
