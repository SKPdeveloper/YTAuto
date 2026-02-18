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
from selenium.common.exceptions import StaleElementReferenceException

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
        self._model_configured: bool = False  # True after first successful model/settings setup

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

            # 1. Navigate to fresh video page (always — clears previous generation state)
            # Model/audio/duration settings persist in localStorage across navigations,
            # so _ensure_kling_model() only runs once (first scene).
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
        Navigate to a clean HiggsField video page ready for image upload.

        Preserves localStorage (model/audio/duration settings persist).
        If a cached image from a previous scene is shown, clears it via
        scoped DOM traversal (same approach as image generator).

        Scene 1: about:blank → higgsfield → model setup (full)
        Scene 2+: about:blank → higgsfield → cached image cleared → skip model setup
        """
        if not await self._check_browser_alive():
            raise Exception("Browser window was closed externally")

        try:
            current_url = await asyncio.to_thread(lambda: self.driver.current_url)
        except Exception as e:
            raise Exception(f"Failed to get current URL: {e}")

        if force_refresh or "higgsfield.ai/create/video" not in current_url:
            # Step 1: Navigate through about:blank to reset React state
            # (localStorage is per-origin — preserved across about:blank navigation)
            logger.debug("Resetting React state via about:blank...")
            await asyncio.to_thread(self.driver.get, "about:blank")
            await asyncio.sleep(1)

            logger.debug(f"Loading {HIGGSFIELD_VIDEO_URL}")
            await asyncio.to_thread(self.driver.get, HIGGSFIELD_VIDEO_URL)
            await asyncio.sleep(4)

            # Step 2: Wait for page ready — file input OR cached image preview
            file_input_found = False
            for attempt in range(15):
                file_inputs = await asyncio.to_thread(
                    self.driver.find_elements,
                    By.CSS_SELECTOR,
                    'input[type="file"]'
                )
                if file_inputs:
                    file_input_found = True
                    logger.debug("Video page ready — file input found (clean page)")
                    break
                # Also check if page loaded but with cached image (no file input)
                has_img = await asyncio.to_thread(
                    self.driver.execute_script,
                    "return document.querySelectorAll('img').length > 2;"
                )
                if has_img and attempt >= 3:
                    logger.debug("Page loaded with cached image — will clear")
                    break
                await asyncio.sleep(1)

            # Step 3: If no file input, clear cached image via scoped X button
            if not file_input_found:
                logger.info("Cached image detected — clearing via X button...")
                cleared = await self._clear_cached_image_scoped()
                if cleared:
                    logger.info("Cached image cleared — waiting for file input...")
                    for i in range(10):
                        file_inputs = await asyncio.to_thread(
                            self.driver.find_elements,
                            By.CSS_SELECTOR,
                            'input[type="file"]'
                        )
                        if file_inputs:
                            logger.debug(f"File input appeared after clearing ({i}s)")
                            break
                        await asyncio.sleep(1)
                    else:
                        logger.warning("File input not found after clearing — fallback to nuclear clear")
                        await self._nuclear_clear_and_reload()

                else:
                    logger.warning("Scoped clearing failed — fallback to nuclear clear")
                    await self._nuclear_clear_and_reload()

            # Step 4: Ensure model/audio/duration (skips if already configured)
            await self._ensure_kling_model()

            # Step 5: Wait for page to stabilize after any model setup
            if not self._model_configured:
                # This shouldn't happen — _ensure_kling_model sets it
                logger.warning("Model not configured after _ensure_kling_model")
            else:
                # Quick stability check — verify file input isn't stale
                await asyncio.sleep(2)
                for attempt in range(5):
                    inputs_1 = await asyncio.to_thread(
                        self.driver.find_elements,
                        By.CSS_SELECTOR,
                        'input[type="file"]'
                    )
                    if not inputs_1:
                        await asyncio.sleep(1)
                        continue
                    try:
                        _ = await asyncio.to_thread(inputs_1[0].get_attribute, 'type')
                        logger.debug("Page stable — file input confirmed")
                        break
                    except StaleElementReferenceException:
                        logger.debug("File input stale — waiting for re-render...")
                        await asyncio.sleep(2)

    async def _clear_cached_image_scoped(self) -> bool:
        """
        Clear a cached image using scoped DOM traversal.
        Same approach as image generator: find the image preview,
        traverse UP the DOM tree, find X button (small button with SVG).

        Returns True if X button was found and clicked.
        """
        try:
            result = await asyncio.to_thread(
                self.driver.execute_script,
                """
                // Strategy 1: Find image preview and traverse up to find X button
                var imgs = document.querySelectorAll('img');
                for (var img of imgs) {
                    var src = img.src || '';
                    var rect = img.getBoundingClientRect();

                    // Skip logos, icons, tiny images
                    if (rect.width < 30 || rect.height < 30) continue;
                    // Skip images outside the left panel area (roughly x < 500)
                    if (rect.x > 500) continue;
                    // Must look like an uploaded preview (blob:, data:, cdn, or sizeable)
                    var isPreview = src.startsWith('blob:') || src.startsWith('data:') ||
                                   src.includes('cdn') || src.includes('upload') ||
                                   (rect.width > 80 && rect.height > 80);
                    if (!isPreview) continue;

                    // Traverse UP to find container with X button
                    var container = img;
                    for (var i = 0; i < 8; i++) {
                        container = container.parentElement;
                        if (!container) break;

                        var btns = container.querySelectorAll('button');
                        for (var btn of btns) {
                            if (btn.offsetWidth < 5 || btn.offsetWidth > 50) continue;
                            if (btn.offsetHeight < 5 || btn.offsetHeight > 50) continue;
                            // X button = small button with SVG icon
                            var svg = btn.querySelector('svg');
                            if (svg) {
                                btn.click();
                                return 'cleared:img_traversal';
                            }
                            // Or text-based X
                            var text = btn.textContent.trim();
                            if (text === '×' || text === 'x' || text === 'X' || text === '✕') {
                                btn.click();
                                return 'cleared:text_x';
                            }
                        }
                    }
                }

                // Strategy 2: Find file input (even hidden) and traverse up
                var fileInput = document.querySelector('input[type="file"]');
                if (fileInput) {
                    var container = fileInput;
                    for (var i = 0; i < 8; i++) {
                        container = container.parentElement;
                        if (!container) break;
                        var btns = container.querySelectorAll('button');
                        for (var btn of btns) {
                            if (btn.offsetWidth < 5 || btn.offsetWidth > 50) continue;
                            if (btn.offsetHeight < 5 || btn.offsetHeight > 50) continue;
                            var svg = btn.querySelector('svg');
                            if (svg) {
                                btn.click();
                                return 'cleared:input_traversal';
                            }
                        }
                    }
                }

                // Strategy 3: Find by aria-label (close, remove, delete, clear)
                var ariaButtons = document.querySelectorAll(
                    '[aria-label*="close" i], [aria-label*="remove" i], ' +
                    '[aria-label*="delete" i], [aria-label*="clear" i]'
                );
                for (var btn of ariaButtons) {
                    if (btn.offsetParent === null) continue;
                    if (btn.offsetWidth > 50) continue;
                    btn.click();
                    return 'cleared:aria_label';
                }

                return 'not_found';
                """
            )
            logger.info(f"Scoped image clear: {result}")
            if result.startswith('cleared'):
                await asyncio.sleep(2)
                return True
            return False

        except Exception as e:
            logger.warning(f"Scoped image clear failed: {e}")
            return False

    async def _nuclear_clear_and_reload(self) -> None:
        """
        Last resort: clear all browser storage and reload.
        This removes cached images but also model/audio/duration settings.
        """
        logger.warning("Nuclear clear: wiping all storage and reloading...")
        await asyncio.to_thread(
            self.driver.execute_script,
            """
            try { localStorage.clear(); } catch(e) {}
            try { sessionStorage.clear(); } catch(e) {}
            try {
                indexedDB.databases().then(function(dbs) {
                    dbs.forEach(function(db) { indexedDB.deleteDatabase(db.name); });
                });
            } catch(e) {}
            """
        )
        self._model_configured = False

        await asyncio.to_thread(self.driver.get, "about:blank")
        await asyncio.sleep(1)
        await asyncio.to_thread(self.driver.get, HIGGSFIELD_VIDEO_URL)
        await asyncio.sleep(4)

        for attempt in range(15):
            file_inputs = await asyncio.to_thread(
                self.driver.find_elements,
                By.CSS_SELECTOR,
                'input[type="file"]'
            )
            if file_inputs:
                logger.debug("File input found after nuclear clear")
                break
            await asyncio.sleep(1)

    async def _ensure_kling_model(self) -> None:
        """
        Ensure Kling 2.6 is the active model with correct settings.

        Uses textarea presence as evidence: Kling 2.6 shows a textarea,
        Kling 3.0 does not. This is a non-destructive check that never
        opens popups or clicks buttons unnecessarily.

        _model_configured flag tracks if settings were already configured.
        Scene 1: flag=False → full setup (model + audio + duration)
        Scene 2+: flag=True + textarea present → skip (localStorage preserved)
        After nuclear clear: flag=False → full setup again
        """
        try:
            # Evidence-based check: does textarea exist?
            textareas = await asyncio.to_thread(
                self.driver.find_elements, By.CSS_SELECTOR, 'textarea'
            )

            if textareas:
                # Kling 2.6 is already active (persisted from localStorage)
                logger.debug("Textarea present — Kling 2.6 is active")
                if not self._model_configured:
                    # First scene: also configure audio and duration
                    await self._ensure_audio_off()
                    await self._ensure_duration_10s()
                    self._model_configured = True
                    logger.info("Kling 2.6 confirmed + audio/duration configured")
                return

            # No textarea — Kling 3.0 (or other model) is active, need to switch
            logger.warning("No textarea — Kling 2.6 not active. Selecting model...")

            # Step 1: Click model selector button (below prompt area)
            clicked = await asyncio.to_thread(
                self.driver.execute_script,
                """
                // Find a clickable element containing a model name keyword
                var modelKeywords = ['kling', 'seedance', 'minimax', 'wan'];
                var candidates = document.querySelectorAll(
                    'button, [role="button"], div[class*="model"], div[class*="select"]'
                );
                for (var el of candidates) {
                    var text = (el.textContent || '').toLowerCase();
                    if (el.offsetParent === null) continue;
                    for (var kw of modelKeywords) {
                        if (text.includes(kw) && text.length < 100) {
                            if (text.includes('generate') || text.includes('upload')) continue;
                            el.click();
                            return 'clicked:' + (el.textContent || '').trim().substring(0, 50);
                        }
                    }
                }
                return 'not_found';
                """
            )
            logger.info(f"Model selector click: {clicked}")

            if clicked == 'not_found':
                logger.error("Model selector button not found on page!")
                return

            await asyncio.sleep(2)

            # Step 2: Click "Kling 2.6" in the popup
            kling_result = await asyncio.to_thread(
                self.driver.execute_script,
                """
                var els = document.querySelectorAll('button, div, li, a, span, label, h3, h4, p');
                var bestMatch = null;
                var bestLen = 9999;
                for (var el of els) {
                    if (el.offsetParent === null) continue;
                    var text = (el.textContent || '').trim();
                    if (text.includes('Kling 2.6') && !text.includes('Kling 2.1')) {
                        if (text.length < bestLen) {
                            bestMatch = el;
                            bestLen = text.length;
                        }
                    }
                }
                if (bestMatch) {
                    var clickTarget = bestMatch.closest('button, [role="button"], a, li')
                                     || bestMatch;
                    clickTarget.click();
                    return 'clicked: ' + bestMatch.textContent.trim().substring(0, 60);
                }
                return 'not_found';
                """
            )
            logger.info(f"Kling 2.6 click: {kling_result}")

            if 'not_found' in str(kling_result):
                logger.error("Kling 2.6 not found in popup!")
                await asyncio.to_thread(
                    self.driver.execute_script,
                    "document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}));"
                )
                return

            await asyncio.sleep(3)

            # Step 3: Verify textarea appeared (Kling 2.6 indicator)
            textarea_found = False
            for attempt in range(5):
                ta = await asyncio.to_thread(
                    self.driver.find_elements, By.CSS_SELECTOR, 'textarea'
                )
                if ta:
                    textarea_found = True
                    logger.info(f"Kling 2.6 verified — textarea found after {attempt}s")
                    break
                await asyncio.sleep(1)

            if not textarea_found:
                # Fallback: click "General" preset to finalize selection
                logger.warning("Textarea not found — clicking General preset as fallback...")
                await asyncio.to_thread(
                    self.driver.execute_script,
                    """
                    var els = document.querySelectorAll('button, div, h4, span, li');
                    for (var el of els) {
                        var text = (el.textContent || '').trim().toLowerCase();
                        if (text === 'general' && el.offsetParent !== null) {
                            var clickable = el.closest('button, [role="button"], li') || el;
                            clickable.click();
                            return;
                        }
                    }
                    """
                )
                await asyncio.sleep(3)
                ta2 = await asyncio.to_thread(
                    self.driver.find_elements, By.CSS_SELECTOR, 'textarea'
                )
                if not ta2:
                    logger.error("CRITICAL: Textarea still not found after model selection!")
                    return

            # Configure audio and duration
            await self._ensure_audio_off()
            await self._ensure_duration_10s()
            self._model_configured = True
            logger.info("Model setup complete — Kling 2.6 + audio/duration configured")

        except Exception as e:
            logger.warning(f"Error in model/settings setup: {e}", exc_info=True)

    async def _ensure_audio_off(self) -> None:
        """Ensure the Audio toggle is OFF."""
        try:
            # Check if audio is currently ON and turn it OFF
            toggled = await asyncio.to_thread(
                self.driver.execute_script,
                """
                // Find Audio toggle — look for label "Audio" near a toggle/switch
                var labels = document.querySelectorAll('span, label, p, div');
                for (var lbl of labels) {
                    if (lbl.textContent.trim().toLowerCase() === 'audio') {
                        // Find nearby toggle button or switch
                        var parent = lbl.closest('div') || lbl.parentElement;
                        if (!parent) continue;
                        // Look for toggle/switch in parent and its siblings
                        var container = parent.parentElement || parent;
                        var toggles = container.querySelectorAll(
                            'button[role="switch"], input[type="checkbox"], [class*="toggle"], [class*="switch"]'
                        );
                        for (var t of toggles) {
                            var isOn = t.getAttribute('aria-checked') === 'true'
                                    || t.checked === true
                                    || t.classList.contains('active')
                                    || t.getAttribute('data-state') === 'checked';
                            if (isOn) {
                                t.click();
                                return 'turned_off';
                            }
                            return 'already_off';
                        }
                    }
                }
                return 'not_found';
                """
            )
            if toggled == 'turned_off':
                logger.info("Audio toggle turned OFF")
            elif toggled == 'already_off':
                logger.debug("Audio already OFF")
            else:
                logger.debug("Audio toggle not found (may not exist for this model)")
        except Exception as e:
            logger.debug(f"Audio toggle check failed: {e}")

    async def _ensure_duration_10s(self) -> None:
        """
        Ensure video duration is set to 10s.

        HiggsField uses a DROPDOWN for duration:
        1. Click button[aria-label="Duration"] to open dropdown
        2. Select [role="option"][data-key="10"] or option with "10s" text
        """
        try:
            # Step 1: Click the Duration dropdown button
            clicked = await asyncio.to_thread(
                self.driver.execute_script,
                """
                // Try aria-label selector first (most reliable)
                var btn = document.querySelector('button[aria-label="Duration"]');
                if (btn) { btn.click(); return 'aria_label'; }

                // Fallback: find button containing "5s" or "10s" text (current duration shown)
                var candidates = document.querySelectorAll('button');
                for (var el of candidates) {
                    if (el.offsetParent === null) continue;
                    var text = (el.textContent || '').trim();
                    if (/^\\d+s$/.test(text)) {
                        el.click();
                        return 'text:' + text;
                    }
                }
                return 'not_found';
                """
            )
            logger.debug(f"Duration button click: {clicked}")

            if clicked == 'not_found':
                logger.warning("Duration button not found on page")
                return

            await asyncio.sleep(0.5)

            # Step 2: Select "10" from dropdown options
            selected = await asyncio.to_thread(
                self.driver.execute_script,
                """
                // Try data-key selector (most reliable)
                var option = document.querySelector('[role="option"][data-key="10"]');
                if (option) { option.click(); return 'data_key'; }

                // Fallback: find option containing "10s" or "10" text
                var options = document.querySelectorAll('[role="option"], [role="menuitem"], li');
                for (var opt of options) {
                    if (opt.offsetParent === null) continue;
                    var text = (opt.textContent || '').trim();
                    if (text === '10s' || text === '10') {
                        opt.click();
                        return 'text:' + text;
                    }
                }

                // Diagnostic: log what options are available
                var available = [];
                document.querySelectorAll('[role="option"]').forEach(function(o) {
                    available.push(o.textContent.trim());
                });
                return 'not_found:' + available.join(',');
                """
            )

            if 'not_found' in str(selected):
                logger.warning(f"Duration 10s option: {selected}")
            else:
                logger.info(f"Duration set to 10s ({selected})")

        except Exception as e:
            logger.warning(f"Duration setup failed: {e}")

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
        """
        Upload image to Higgsfield.

        Page is guaranteed to be clean after _ensure_video_page() which
        clears all browser storage. File input should always be present.

        Uses send_keys + React internal onChange handler to ensure
        the file is actually processed by React's synthetic event system.

        Retries on StaleElementReferenceException (page may re-render
        after model selection).
        """
        logger.debug(f"Uploading: {image_path}")
        abs_path = str(image_path.absolute())

        # Retry loop — handles stale element references from delayed re-renders
        for retry in range(3):
            try:
                # Step 1: Find file input (fresh search each retry)
                file_inputs = await asyncio.to_thread(
                    self.driver.find_elements,
                    By.CSS_SELECTOR,
                    'input[type="file"]'
                )

                if not file_inputs:
                    logger.warning("File input not found — waiting...")
                    for i in range(10):
                        await asyncio.sleep(1)
                        file_inputs = await asyncio.to_thread(
                            self.driver.find_elements,
                            By.CSS_SELECTOR,
                            'input[type="file"]'
                        )
                        if file_inputs:
                            break

                if not file_inputs:
                    raise Exception("File input not found on page — cannot upload image")

                # Step 2: Send file path via Selenium
                logger.debug(f"Sending file to input: {image_path.name}")
                await asyncio.to_thread(file_inputs[0].send_keys, abs_path)

                # Step 3: Trigger React's onChange handler
                # React 17+ uses event delegation and may not catch native DOM events.
                await asyncio.to_thread(
                    self.driver.execute_script,
                    """
                    var input = arguments[0];

                    // Approach 1: React internal onChange (most reliable for React 17+)
                    var reactPropsKey = Object.keys(input).find(function(key) {
                        return key.startsWith('__reactProps$') ||
                               key.startsWith('__reactEventHandlers$');
                    });
                    if (reactPropsKey) {
                        var props = input[reactPropsKey];
                        if (props && props.onChange) {
                            props.onChange({ target: input, currentTarget: input });
                            return 'react_onChange';
                        }
                    }

                    // Approach 2: Native change event (bubbles up for React event delegation)
                    var changeEvent = new Event('change', { bubbles: true });
                    input.dispatchEvent(changeEvent);

                    // Approach 3: InputEvent
                    var inputEvent = new Event('input', { bubbles: true });
                    input.dispatchEvent(inputEvent);

                    return 'native_events';
                    """,
                    file_inputs[0]
                )

                # If we got here without StaleElementReferenceException, break retry loop
                break

            except StaleElementReferenceException:
                if retry < 2:
                    logger.warning(f"Stale element on upload attempt {retry + 1} — page re-rendered, retrying...")
                    await asyncio.sleep(2)
                else:
                    raise Exception("File input keeps going stale — page unstable")

        # Step 4: Wait for upload processing
        logger.debug("Waiting for upload processing...")
        for i in range(60):
            body_text = await asyncio.to_thread(
                lambda: self.driver.find_element(By.TAG_NAME, 'body').text.lower()
            )
            if 'uploading' not in body_text:
                logger.debug(f"Upload processing done ({i}s)")
                break
            await asyncio.sleep(1)

        # Step 5: Verify — wait for file input to disappear (replaced by preview)
        for i in range(20):
            remaining = await asyncio.to_thread(
                self.driver.find_elements,
                By.CSS_SELECTOR,
                'input[type="file"]'
            )
            if not remaining:
                logger.info(f"Image upload VERIFIED — file input removed after {i}s")
                return
            # Also check if hidden (some UIs hide rather than remove)
            try:
                is_hidden = await asyncio.to_thread(
                    self.driver.execute_script,
                    "var el = arguments[0]; return el.offsetParent === null && el.offsetWidth === 0;",
                    remaining[0]
                )
                if is_hidden:
                    logger.info(f"Image upload VERIFIED — file input hidden after {i}s")
                    return
            except StaleElementReferenceException:
                # Element went stale during check — likely removed, which means success
                logger.info(f"Image upload VERIFIED — file input went stale (removed) after {i}s")
                return
            await asyncio.sleep(1)

        logger.warning("Image upload verification inconclusive — continuing anyway")

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
        """Нажать Generate (JavaScript click to bypass overlay elements)"""
        gen_btn = await asyncio.to_thread(
            self.driver.find_element,
            By.XPATH,
            "//button[contains(., 'Generate')]"
        )
        # Scroll button into view and use JS click — the prompt label
        # overlaps the button in the current Higgsfield UI, causing
        # ElementClickInterceptedException with native Selenium click
        await asyncio.to_thread(
            self.driver.execute_script,
            "arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();",
            gen_btn
        )
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
        """
        Get the URL of the generated video.

        Strategy (in order):
        1. Look for <video> elements directly on the page (inline player after generation)
        2. Search all DOM attributes for video URLs via JS (covers lazy-loaded/data-* attrs)
        3. Click History panel items to open modal with video
        """

        for attempt in range(max_attempts):
            try:
                # --- Strategy 1: Direct <video> elements on page ---
                video_url = await asyncio.to_thread(
                    self.driver.execute_script,
                    """
                    var validUrl = function(url) {
                        if (!url || !url.startsWith('http')) return false;
                        // Accept .mp4, cloudfront CDN, higgsfield CDN
                        return url.includes('.mp4') ||
                               url.includes('cloudfront') ||
                               url.includes('cdn.higgsfield');
                    };

                    // Check all <video> elements — src and <source> children
                    var videos = document.querySelectorAll('video');
                    for (var v of videos) {
                        if (validUrl(v.src)) return v.src;
                        if (validUrl(v.currentSrc)) return v.currentSrc;
                        var sources = v.querySelectorAll('source');
                        for (var s of sources) {
                            if (validUrl(s.src)) return s.src;
                        }
                    }

                    // Check <a> download links
                    var links = document.querySelectorAll('a[download], a[href*=".mp4"]');
                    for (var a of links) {
                        var href = a.getAttribute('href');
                        if (validUrl(href)) return href;
                    }

                    // Check data-* attributes
                    var dataEls = document.querySelectorAll(
                        '[data-url], [data-video-url], [data-src], [data-video]'
                    );
                    for (var el of dataEls) {
                        var attrs = ['data-url', 'data-video-url', 'data-src', 'data-video'];
                        for (var attr of attrs) {
                            var val = el.getAttribute(attr);
                            if (validUrl(val)) return val;
                        }
                    }

                    // Scan ALL attributes for video URLs (covers edge cases)
                    var allEls = document.querySelectorAll('*');
                    for (var el of allEls) {
                        for (var attr of el.attributes) {
                            if (attr.value && attr.value.startsWith('http') &&
                                (attr.value.includes('.mp4') || attr.value.includes('kling_motion'))) {
                                return attr.value;
                            }
                        }
                    }

                    return null;
                    """
                )

                if video_url:
                    logger.info(f"Found video URL (strategy 1, attempt {attempt + 1}): {video_url[:80]}...")
                    return video_url

                # --- Strategy 2: Click History panel → open modal → find video ---
                if attempt >= 2:  # Give inline video 2 attempts before trying History
                    url_from_history = await self._get_video_url_from_history()
                    if url_from_history:
                        logger.info(f"Found video URL (history, attempt {attempt + 1}): {url_from_history[:80]}...")
                        return url_from_history

            except Exception as e:
                logger.debug(f"Attempt {attempt + 1} error: {e}")

            logger.debug(f"Video not found yet, attempt {attempt + 1}/{max_attempts}")
            await asyncio.sleep(5)

        return None

    async def _get_video_url_from_history(self) -> Optional[str]:
        """
        Fallback: open History panel, click the newest card, extract video URL from modal.
        """
        try:
            # Click History button/tab
            clicked_history = await asyncio.to_thread(
                self.driver.execute_script,
                """
                var candidates = document.querySelectorAll('button, [role="tab"], a');
                for (var el of candidates) {
                    var text = (el.textContent || '').trim().toLowerCase();
                    if (text === 'history' || text.includes('history')) {
                        if (el.offsetParent === null) continue;
                        el.click();
                        return true;
                    }
                }
                return false;
                """
            )
            if not clicked_history:
                logger.debug("History button not found")
                return None

            await asyncio.sleep(2)

            # Click the first video card/thumbnail in history
            clicked_card = await asyncio.to_thread(
                self.driver.execute_script,
                """
                // Look for clickable cards with video thumbnails
                var selectors = [
                    '[data-asset-id]',
                    'button.absolute.inset-0',
                    'button[class*="cursor-pointer"]',
                    'div[class*="card"] button',
                    'div[class*="history"] button',
                    'div[class*="grid"] > div'
                ];
                for (var sel of selectors) {
                    var items = document.querySelectorAll(sel);
                    if (items.length > 0) {
                        items[0].click();
                        return sel + ':' + items.length;
                    }
                }
                return null;
                """
            )
            if not clicked_card:
                logger.debug("No history cards found")
                return None

            logger.debug(f"Clicked history card: {clicked_card}")
            await asyncio.sleep(3)

            # Extract video URL from modal
            video_url = await asyncio.to_thread(
                self.driver.execute_script,
                """
                var validUrl = function(url) {
                    if (!url || !url.startsWith('http')) return false;
                    return url.includes('.mp4') ||
                           url.includes('cloudfront') ||
                           url.includes('cdn.higgsfield');
                };
                // Check modal video elements
                var modalSelectors = [
                    'div[role="dialog"] video',
                    '[class*="modal"] video',
                    '[class*="Modal"] video',
                    '[class*="preview"] video',
                    'video'
                ];
                for (var sel of modalSelectors) {
                    var videos = document.querySelectorAll(sel);
                    for (var v of videos) {
                        if (validUrl(v.src)) return v.src;
                        if (validUrl(v.currentSrc)) return v.currentSrc;
                        var sources = v.querySelectorAll('source');
                        for (var s of sources) {
                            if (validUrl(s.src)) return s.src;
                        }
                    }
                }
                return null;
                """
            )

            # Close modal
            await asyncio.to_thread(
                self.driver.execute_script,
                "document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));"
            )
            await asyncio.sleep(1)

            return video_url

        except Exception as e:
            logger.debug(f"History fallback error: {e}")
            # Try to close any open modal
            try:
                await asyncio.to_thread(
                    self.driver.execute_script,
                    "document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));"
                )
            except Exception:
                pass
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
