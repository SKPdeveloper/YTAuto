"""
Kling Video Generator - Генерація відео через Kling 2.6 модель.

WORKFLOW: Kling Video Generation
1. Navigate to video page
2. Set model to Kling 2.6
3. Clear old image
4. Upload start frame
5. Enter motion prompt
6. Set duration (10s)
7. Generate
8. Wait and download
"""

import asyncio
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Dict

import httpx
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException

from loguru import logger

from app.core.errors import (
    HiggsFieldWebGenerationError,
    HiggsFieldWebElementNotFoundError,
    HiggsFieldWebDownloadError,
    HiggsFieldWebTimeoutError,
)
from app.clients.adspower_client import AdsPowerClient
from app.clients.higgsfield_selectors import (
    HIGGSFIELD_VIDEO_URL,
    VIDEO_SELECTORS,
    JS_SCRIPTS,
    TIMEOUTS,
)


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class KlingSettings:
    """Налаштування для Kling 2.6"""
    model: str = "Kling 2.6"
    duration: int = 10
    aspect_ratio: str = "9:16"


# ============================================================================
# KLING VIDEO GENERATOR
# ============================================================================

class KlingVideoGenerator:
    """
    Генератор відео через Kling 2.6.

    Потребує AdsPowerClient для управління браузером.

    Usage:
        browser = AdsPowerClient(config)
        await browser.start_browser()

        generator = KlingVideoGenerator(browser, download_dir)
        video = await generator.generate_video(image_path, prompt)
    """

    def __init__(
        self,
        browser: AdsPowerClient,
        download_dir: Path,
        settings: Optional[KlingSettings] = None,
        http_client: Optional[httpx.AsyncClient] = None
    ):
        self.browser = browser
        self.download_dir = download_dir
        self.settings = settings or KlingSettings()
        self._http_client = http_client

        # Кешований URL останнього відео
        self._last_generated_video_url: Optional[str] = None

        # Очередь на скачивание (scene_num -> initial_urls)
        self._pending_downloads: List[dict] = []

        # Ensure download dir exists
        self.download_dir.mkdir(parents=True, exist_ok=True)

    # ========================================================================
    # NAVIGATION
    # ========================================================================

    async def _navigate_to_video(self) -> None:
        """Перейти на сторінку генерації відео"""
        logger.debug(f"Navigating to: {HIGGSFIELD_VIDEO_URL}")

        await self.browser.navigate(HIGGSFIELD_VIDEO_URL)

        # Перевірити чи не розлогінило
        await self.browser.check_and_handle_logout()

        # Очікування повного завантаження UI
        logger.info(f"Waiting {TIMEOUTS.PAGE_LOAD}s for UI to fully load...")
        await asyncio.sleep(TIMEOUTS.PAGE_LOAD)
        logger.debug("Video page loaded")

    # ========================================================================
    # MODEL SELECTION (Kling workflow)
    # ========================================================================

    async def _select_kling_model(self) -> None:
        """
        Вибрати модель Kling через UI.

        Workflow:
        1. Клік на "Change" (іконка олівця)
        2. Клік на таб "Kling"
        3. Клік на пресет "General"
        """
        logger.info("Selecting Kling model...")
        await asyncio.to_thread(self._sync_select_kling_model)

    def _sync_select_kling_model(self) -> None:
        """Sync вибір моделі Kling"""
        driver = self.browser.driver

        # Step 1: Click "Change" button (pencil icon)
        logger.debug("Step 1: Looking for Change button (pencil icon)...")
        change_btn = driver.execute_script("""
            var buttons = document.querySelectorAll('button');
            for (var i = 0; i < buttons.length; i++) {
                var svg = buttons[i].querySelector('svg path');
                if (svg) {
                    var d = svg.getAttribute('d') || '';
                    if (d.startsWith('M13.5479')) {
                        return buttons[i];
                    }
                }
            }
            return null;
        """)

        if change_btn:
            driver.execute_script("arguments[0].click();", change_btn)
            logger.debug("Clicked Change button")
            time.sleep(1)
        else:
            logger.warning("Change button not found - model may already be selected")
            return

        # Step 2: Click "Kling" tab
        logger.debug("Step 2: Looking for Kling tab...")
        time.sleep(0.5)

        kling_tab = driver.execute_script("""
            var buttons = document.querySelectorAll('button');
            for (var i = 0; i < buttons.length; i++) {
                var text = buttons[i].textContent || '';
                if (text.toLowerCase().includes('kling') &&
                    !text.toLowerCase().includes('seedance')) {
                    return buttons[i];
                }
            }
            return null;
        """)

        if kling_tab:
            driver.execute_script("arguments[0].click();", kling_tab)
            logger.debug("Clicked Kling tab")
            time.sleep(1)
        else:
            logger.warning("Kling tab not found")
            return

        # Step 3: Click "General" preset
        logger.debug("Step 3: Looking for General preset...")
        time.sleep(0.5)

        general_btn = driver.execute_script("""
            var buttons = document.querySelectorAll('button');
            for (var i = 0; i < buttons.length; i++) {
                var text = buttons[i].textContent || '';
                if (text.toLowerCase().trim() === 'general') {
                    return buttons[i];
                }
            }
            // Fallback: look for h4 with "General" text
            var h4s = document.querySelectorAll('h4');
            for (var i = 0; i < h4s.length; i++) {
                if (h4s[i].textContent.toLowerCase().trim() === 'general') {
                    var btn = h4s[i].closest('button');
                    if (btn) return btn;
                }
            }
            return null;
        """)

        if general_btn:
            driver.execute_script("arguments[0].click();", general_btn)
            logger.info("Selected Kling model with General preset")
            time.sleep(1)
        else:
            logger.warning("General preset not found")

    # ========================================================================
    # SETTINGS
    # ========================================================================

    async def _set_video_duration(self, duration: int) -> None:
        """Встановити тривалість відео (5 або 10 секунд)"""
        logger.debug(f"Setting video duration: {duration}s")
        await asyncio.to_thread(self._sync_set_video_duration, duration)

    def _sync_set_video_duration(self, duration: int) -> None:
        """Sync встановлення тривалості відео"""
        driver = self.browser.driver

        try:
            # Click Duration button
            duration_btn = driver.find_element(
                By.CSS_SELECTOR,
                VIDEO_SELECTORS.DURATION_BUTTON
            )
            driver.execute_script("arguments[0].click();", duration_btn)
            time.sleep(0.5)

            # Select duration option
            data_key = str(duration)
            option_selector = f'[role="option"][data-key="{data_key}"]'

            options = driver.find_elements(By.CSS_SELECTOR, option_selector)
            if options:
                driver.execute_script("arguments[0].click();", options[0])
                logger.info(f"Duration set to {duration}s")
            else:
                # Fallback: look by text
                all_options = driver.find_elements(By.CSS_SELECTOR, '[role="option"]')
                for opt in all_options:
                    if f"{duration}s" in opt.text:
                        driver.execute_script("arguments[0].click();", opt)
                        logger.info(f"Duration set to {duration}s (by text)")
                        return
                logger.warning(f"Duration option {duration}s not found")

        except Exception as e:
            logger.warning(f"Failed to set duration: {e}")

    async def _ensure_audio_off(self) -> None:
        """Переконатися що аудіо вимкнено"""
        logger.debug("Checking audio toggle...")
        await asyncio.to_thread(self._sync_ensure_audio_off)

    def _sync_ensure_audio_off(self) -> None:
        """Sync перевірка що аудіо OFF"""
        driver = self.browser.driver

        try:
            audio_toggle = driver.find_element(
                By.CSS_SELECTOR,
                VIDEO_SELECTORS.AUDIO_TOGGLE
            )

            state = audio_toggle.get_attribute("data-state")
            aria_checked = audio_toggle.get_attribute("aria-checked")

            is_on = (state == "on" or state == "checked" or aria_checked == "true")

            if is_on:
                driver.execute_script("arguments[0].click();", audio_toggle)
                logger.info("Audio toggled OFF")
                time.sleep(0.3)
            else:
                logger.debug("Audio already OFF")

        except Exception as e:
            logger.debug(f"Audio toggle not found or error: {e}")

    # ========================================================================
    # ASPECT RATIO SETTING (9:16 for vertical video - YouTube Shorts)
    # ========================================================================

    async def _set_aspect_ratio_9_16(self) -> None:
        """
        Автоматично встановити aspect ratio 9:16 (вертикальне відео).

        ВАЖЛИВО: Це обов'язково для YouTube Shorts/TikTok формату.
        Викликається автоматично після переходу на сторінку генерації відео.
        """
        logger.info("Setting aspect ratio to 9:16 (vertical video)...")
        await asyncio.to_thread(self._sync_set_aspect_ratio_9_16)

    def _sync_set_aspect_ratio_9_16(self) -> None:
        """
        Sync встановлення aspect ratio 9:16.
        Перевіряє чи вже 9:16 - якщо так, не змінює.
        """
        driver = self.browser.driver

        try:
            # Шукаємо кнопку aspect ratio
            aspect_btn = None
            current_ratio = None

            # Спосіб 1: aria-label
            try:
                aspect_btn = driver.find_element(
                    By.CSS_SELECTOR,
                    VIDEO_SELECTORS.ASPECT_RATIO_BUTTON
                )
                current_ratio = aspect_btn.text.strip()
                logger.debug(f"Found Aspect Ratio button, current: '{current_ratio}'")
            except NoSuchElementException:
                pass

            # Спосіб 2: Шукаємо кнопку з текстом що містить ":"
            if not aspect_btn:
                buttons = driver.find_elements(By.TAG_NAME, "button")
                for btn in buttons:
                    try:
                        text = btn.text.strip()
                        if ":" in text and any(r in text for r in ["16:9", "9:16", "1:1"]):
                            aspect_btn = btn
                            current_ratio = text
                            logger.debug(f"Found button with ratio: '{text}'")
                            break
                    except:
                        continue

            # Перевіряємо чи вже 9:16
            if current_ratio and "9:16" in current_ratio:
                logger.success("Aspect ratio already 9:16, skipping")
                return

            if not aspect_btn:
                logger.warning("Aspect Ratio button not found!")
                return

            if aspect_btn:
                # Клікаємо на кнопку щоб відкрити dropdown
                driver.execute_script("arguments[0].click();", aspect_btn)
                logger.debug("Clicked Aspect Ratio button, waiting for dropdown...")
                time.sleep(0.5)

                # Шукаємо 9:16 опцію
                option_9_16 = None

                # Спосіб 1: По data-key
                try:
                    option_9_16 = driver.find_element(
                        By.CSS_SELECTOR,
                        VIDEO_SELECTORS.ASPECT_RATIO_OPTION_9_16
                    )
                    logger.debug("Found 9:16 option by data-key")
                except NoSuchElementException:
                    pass

                # Спосіб 2: По тексту в role="option"
                if not option_9_16:
                    options = driver.find_elements(By.CSS_SELECTOR, '[role="option"]')
                    for opt in options:
                        opt_text = opt.text.strip()
                        if "9:16" in opt_text:
                            option_9_16 = opt
                            logger.debug(f"Found 9:16 option by text: '{opt_text}'")
                            break

                if option_9_16:
                    driver.execute_script("arguments[0].click();", option_9_16)
                    logger.success("✓ Aspect ratio set to 9:16 (vertical video)")
                    time.sleep(0.3)
                else:
                    logger.warning("9:16 option not found in dropdown")
            else:
                logger.error("Could not find Aspect Ratio button at all")

        except Exception as e:
            logger.error(f"Failed to set aspect ratio: {e}")

    # ========================================================================
    # START FRAME HANDLING
    # ========================================================================

    async def _upload_start_frame(self, image_path: Path) -> None:
        """Завантажити зображення як start frame"""
        logger.debug(f"Uploading start frame: {image_path}")

        if not image_path.exists():
            raise HiggsFieldWebGenerationError(f"Start frame not found: {image_path}")

        await asyncio.to_thread(self._sync_upload_start_frame, str(image_path.absolute()))

    def _sync_upload_start_frame(self, image_path: str) -> None:
        """Sync upload start frame через file input"""
        driver = self.browser.driver

        try:
            file_inputs = driver.find_elements(
                By.CSS_SELECTOR,
                VIDEO_SELECTORS.START_FRAME_INPUT
            )

            if not file_inputs:
                raise HiggsFieldWebElementNotFoundError("No file input found for start frame")

            # Перший input - start frame
            start_frame_input = file_inputs[0]
            start_frame_input.send_keys(image_path)

            logger.debug("Start frame uploaded")
            logger.info(f"Waiting {TIMEOUTS.VIDEO_UPLOAD}s for start frame to upload...")
            time.sleep(TIMEOUTS.VIDEO_UPLOAD)

            if self._verify_start_frame_uploaded():
                logger.success("Start frame upload VERIFIED - delete button found")
            else:
                logger.warning("Start frame upload verification FAILED - no delete button found")
                logger.info(f"Waiting additional {TIMEOUTS.IMAGE_UPLOAD_EXTRA}s...")
                time.sleep(TIMEOUTS.IMAGE_UPLOAD_EXTRA)
                if self._verify_start_frame_uploaded():
                    logger.success("Start frame upload VERIFIED on second check")
                else:
                    raise HiggsFieldWebGenerationError("Start frame upload failed - cannot proceed")

        except NoSuchElementException:
            raise HiggsFieldWebElementNotFoundError("Start frame file input not found")
        except Exception as e:
            logger.warning(f"Failed to upload start frame: {e}")

    def _verify_start_frame_uploaded(self) -> bool:
        """Перевірити чи start frame завантажено успішно"""
        try:
            driver = self.browser.driver
            
            # КРИТИЧНО: Спочатку перевірити що немає 'Uploading' тексту
            uploading_check = driver.execute_script("""
                var body = document.body.innerText.toLowerCase();
                return body.includes('uploading');
            """)
            if uploading_check:
                logger.debug("Upload still in progress - 'Uploading' text found")
                return False
            
            # Тепер перевіряємо наявність картинки
            result = self.browser.execute_script(JS_SCRIPTS.verify_start_frame_uploaded())
            return result
        except Exception as e:
            logger.debug(f"Error verifying start frame upload: {e}")
            return False

    def _refresh_page(self) -> None:
        """Оновити сторінку для чистого стану - перейти на video URL"""
        driver = self.browser.driver
        try:
            # Переходимо напряму на URL замість refresh
            driver.get(HIGGSFIELD_VIDEO_URL)
            logger.info(f"Navigated to {HIGGSFIELD_VIDEO_URL}")
            time.sleep(5)  # Дати сторінці завантажитись
        except Exception as e:
            logger.warning(f"Could not navigate: {e}")

    def _sync_clear_video_image(self) -> None:
        """Видалити старе зображення з поля для відео"""
        driver = self.browser.driver

        try:
            # Очистить file input напрямую
            driver.execute_script("""
                var inputs = document.querySelectorAll('input[type="file"]');
                for (var i = 0; i < inputs.length; i++) {
                    inputs[i].value = '';
                }
            """)

            # Клик X кнопку
            result = driver.execute_script("""
                var cleared = 0;
                var buttons = document.querySelectorAll('button');

                for (var i = 0; i < buttons.length; i++) {
                    var btn = buttons[i];
                    var svg = btn.querySelector('svg');
                    if (!svg) continue;

                    if (btn.offsetWidth > 0 && btn.offsetWidth < 50 && btn.offsetHeight < 50) {
                        var paths = svg.querySelectorAll('path');
                        for (var p = 0; p < paths.length; p++) {
                            var d = paths[p].getAttribute('d') || '';
                            if (d.startsWith('M3.81344') ||
                                d.includes('M6 18L18 6') ||
                                d.includes('M6 6l12 12') ||
                                d.includes('m1 1 6 6')) {
                                btn.click();
                                cleared++;
                            }
                        }
                    }
                }
                return cleared;
            """)

            if result and result > 0:
                logger.info(f"Cleared {result} start frame(s)")
            time.sleep(0.5)

        except Exception as e:
            logger.debug(f"Could not clear video image: {e}")

    # ========================================================================
    # PROMPT HANDLING
    # ========================================================================

    def _sync_enter_video_prompt(self, prompt: str) -> None:
        """Очистити старий промпт і ввести новий"""
        driver = self.browser.driver

        try:
            textarea = driver.find_element(By.ID, "prompt")
            logger.debug("Found video prompt textarea")

            # Scroll до textarea
            driver.execute_script("""
                var textarea = arguments[0];
                textarea.scrollIntoView({block: 'center'});
            """, textarea)
            time.sleep(0.2)

            # Перевірити чи є старий промпт і очистити
            old_value = textarea.get_attribute('value') or ''
            if old_value.strip():
                logger.info(f"Clearing old prompt ({len(old_value)} chars)...")
                self._sync_clear_video_prompt()
                time.sleep(0.3)

            # Ввести новий промпт через React-сумісний спосіб
            driver.execute_script("""
                var textarea = arguments[0];
                var prompt = arguments[1];

                textarea.focus();

                // Native setter для React
                var nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLTextAreaElement.prototype, 'value'
                ).set;
                nativeInputValueSetter.call(textarea, prompt);

                // Dispatch events
                textarea.dispatchEvent(new Event('input', { bubbles: true }));
                textarea.dispatchEvent(new Event('change', { bubbles: true }));
            """, textarea, prompt)

            time.sleep(0.3)

            # Верифікація
            new_value = textarea.get_attribute('value') or ''
            if len(new_value) > 20:
                logger.info(f"Video prompt entered via JS ({len(new_value)} chars)")
            else:
                logger.warning("JS prompt entry may have failed, trying send_keys...")
                textarea.clear()
                textarea.send_keys(prompt)

        except NoSuchElementException:
            logger.warning("textarea#prompt not found, trying fallback...")
            textarea = driver.find_element(By.CSS_SELECTOR, 'textarea[name="prompt"]')
            textarea.clear()
            textarea.send_keys(prompt)

    def _sync_clear_video_prompt(self) -> None:
        """Очистити промпт відео"""
        driver = self.browser.driver

        try:
            textarea = driver.find_element(By.CSS_SELECTOR, VIDEO_SELECTORS.PROMPT_TEXTAREA)
            driver.execute_script("""
                var textarea = arguments[0];
                var nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLTextAreaElement.prototype, 'value'
                ).set;
                nativeInputValueSetter.call(textarea, '');
                var inputEvent = new Event('input', { bubbles: true });
                textarea.dispatchEvent(inputEvent);
            """, textarea)
            logger.debug("Video prompt cleared")
        except Exception as e:
            logger.debug(f"Could not clear video prompt: {e}")

    def _sync_clear_all_fields(self) -> None:
        """
        АГРЕСИВНА очистка всіх полів: промпт + картинка.
        Викликається перед кожною новою сценою.
        """
        driver = self.browser.driver
        logger.info("Clearing ALL fields (prompt + frame)...")

        # 1. Очистити промпт
        try:
            driver.execute_script("""
                var textarea = document.querySelector('textarea#prompt') ||
                               document.querySelector('textarea');
                if (textarea) {
                    var nativeSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLTextAreaElement.prototype, 'value'
                    ).set;
                    nativeSetter.call(textarea, '');
                    textarea.dispatchEvent(new Event('input', { bubbles: true }));
                    textarea.dispatchEvent(new Event('change', { bubbles: true }));
                    console.log('Prompt cleared');
                }
            """)
            logger.info("  Prompt: CLEARED")
        except Exception as e:
            logger.warning(f"  Prompt clear failed: {e}")

        time.sleep(0.3)

        # 2. Очистити картинку (клік на X кнопку)
        try:
            cleared = driver.execute_script("""
                var buttons = document.querySelectorAll('button');
                for (var btn of buttons) {
                    var svg = btn.querySelector('svg path');
                    if (svg) {
                        var d = svg.getAttribute('d') || '';
                        // X icon: M3.81344 or M18 6L6 18
                        if (d.startsWith('M3.81344') || d.includes('M18 6L6 18') || d.includes('6 18M6 6')) {
                            btn.click();
                            return 'clicked';
                        }
                    }
                }
                return 'no_x_button';
            """)
            if cleared == 'clicked':
                logger.info("  Frame: CLEARED (X clicked)")
            else:
                logger.info("  Frame: already empty")
        except Exception as e:
            logger.warning(f"  Frame clear failed: {e}")

        time.sleep(0.3)
        logger.info("All fields cleared!")

    def _sync_close_modal_if_exists(self) -> None:
        """Закрити модальне вікно якщо воно відкрите."""
        driver = self.browser.driver
        try:
            # Шукаємо кнопку закриття модального вікна
            close_buttons = driver.execute_script("""
                var modals = document.querySelectorAll('[role="dialog"], .modal, [class*="modal"]');
                for (var m of modals) {
                    var closeBtn = m.querySelector('button[aria-label="Close"], button[class*="close"], svg[class*="close"]');
                    if (closeBtn) {
                        closeBtn.click();
                        return 'closed';
                    }
                }
                // Also try ESC key
                document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', code: 'Escape'}));
                return 'esc_sent';
            """)
            if close_buttons:
                logger.info(f"Modal handling: {close_buttons}")
                time.sleep(0.5)
        except Exception as e:
            logger.debug(f"Modal check: {e}")

    def _sync_verify_image_loaded(self) -> bool:
        """
        Перевірити що зображення дійсно завантажено на сторінці.
        Шукаємо preview картинки у формі генерації відео.
        """
        driver = self.browser.driver

        try:
            # Закриваємо модальне вікно якщо є
            self._sync_close_modal_if_exists()

            # Шукаємо специфічний контейнер для start frame на HiggsField
            # Зазвичай це img всередині контейнера з розміром > 100px
            has_start_frame = driver.execute_script("""
                // Look for images in the video creation form
                var imgs = document.querySelectorAll('img');
                for (var i = 0; i < imgs.length; i++) {
                    var img = imgs[i];
                    var src = img.src || '';

                    // Skip small images (icons, avatars)
                    if (img.naturalWidth < 100 || img.naturalHeight < 100) continue;

                    // Look for blob: or data: URLs (uploaded images)
                    if (src.startsWith('blob:') || src.startsWith('data:')) {
                        // Check if visible on page
                        var rect = img.getBoundingClientRect();
                        if (rect.width > 50 && rect.height > 50) {
                            console.log('Found start frame:', src.substring(0, 50));
                            return {found: true, src: src.substring(0, 80), width: rect.width, height: rect.height};
                        }
                    }
                }
                return {found: false};
            """)

            if has_start_frame and has_start_frame.get('found'):
                logger.info(f"Start frame loaded: {has_start_frame.get('width')}x{has_start_frame.get('height')}")
                logger.debug(f"  src: {has_start_frame.get('src')}...")
                return True

            logger.warning("No start frame image found on page!")
            return False
        except Exception as e:
            logger.warning(f"Error checking image: {e}")
            return False

    def _sync_get_credits_count(self) -> int:
        """Отримати поточну кількість кредитів з кнопки Generate."""
        driver = self.browser.driver
        try:
            result = driver.execute_script("""
                // Method 1: Find button.bg-primary (main Generate button)
                var primaryBtn = document.querySelector('button.bg-primary');
                if (primaryBtn) {
                    var text = primaryBtn.innerText || primaryBtn.textContent || '';
                    console.log('Primary button text:', text);
                    var match = text.match(/(\\d+)/);
                    if (match) {
                        return parseInt(match[1]);
                    }
                }

                // Method 2: Search all buttons for Generate text
                var btns = document.querySelectorAll('button');
                for (var btn of btns) {
                    var text = btn.innerText || btn.textContent || '';
                    if (text.toLowerCase().includes('generate')) {
                        var match = text.match(/(\\d+)/);
                        if (match) {
                            return parseInt(match[1]);
                        }
                    }
                }

                // Method 3: Look for span/div with credits number near Generate
                var generateElements = document.querySelectorAll('*');
                for (var el of generateElements) {
                    if (el.textContent && el.textContent.toLowerCase().includes('generate')) {
                        var nums = el.textContent.match(/(\\d+)/g);
                        if (nums && nums.length > 0) {
                            return parseInt(nums[0]);
                        }
                    }
                }

                return -1;
            """)
            logger.debug(f"Credits detection result: {result}")
            return result if result else -1
        except Exception as e:
            logger.debug(f"Credits detection error: {e}")
            return -1

    def _sync_verify_generation_started(self, credits_before: int = -1) -> bool:
        """
        Перевірити що генерація відео дійсно почалась.
        Перевіряємо зменшення кредитів (найнадійніший спосіб).
        """
        driver = self.browser.driver

        try:
            # Метод 1: Перевірити зменшення кредитів
            if credits_before > 0:
                credits_now = self._sync_get_credits_count()
                if credits_now >= 0 and credits_now < credits_before:
                    logger.success(f"Credits decreased: {credits_before} -> {credits_now}")
                    return True
                logger.info(f"Credits unchanged: {credits_before} -> {credits_now}")

            # Метод 2: Перевірити чи кнопка стала disabled
            result = driver.execute_script("""
                var btns = document.querySelectorAll('button');
                for (var btn of btns) {
                    if (btn.innerText && btn.innerText.toLowerCase().includes('generate')) {
                        if (btn.disabled) {
                            return {started: true, reason: 'button disabled'};
                        }
                    }
                }
                return {started: false};
            """)

            if result and result.get('started'):
                logger.success(f"Generation started: {result.get('reason')}")
                return True

            logger.warning("Generation does NOT appear to have started (credits unchanged, button enabled)")
            return False
        except Exception as e:
            logger.warning(f"Error checking generation status: {e}")
            return False

    def _sync_click_generate_fast(self) -> bool:
        """
        Надійний клік на Generate кнопку з 5 fallback методами.
        Після кожної спроби перевіряємо чи генерація запустилась.

        ВАЖЛИВО: Рахуємо кількість queue indicators ДО кліку,
        щоб не плутати з попередніми генераціями.

        Returns:
            bool: True якщо генерація запустилась, False якщо ні
        """
        driver = self.browser.driver

        try:
            # Знайти кнопку
            btn = self._find_generate_button()
            if not btn:
                logger.error("Generate button not found")
                return False

            btn_text = btn.text.strip()
            logger.info(f"Generate button found: '{btn_text[:40]}'")

            # Перевірка що кнопка активна
            is_disabled = driver.execute_script("""
                var btn = arguments[0];
                return btn.disabled || btn.hasAttribute('disabled') ||
                       btn.classList.contains('disabled') || btn.classList.contains('opacity-50');
            """, btn)

            if is_disabled:
                logger.error("Generate button is DISABLED! Start frame not loaded?")
                return False

            # ВАЖЛИВО: Підрахувати кількість queue indicators ДО кліку
            initial_queue_count = self._count_queue_indicators()
            logger.info(f"Queue indicators before click: {initial_queue_count}")

            # Scroll до кнопки
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
            time.sleep(0.5)

            # ========================================================
            # 5 МЕТОДІВ КЛІКУ З ПЕРЕВІРКОЮ ПІСЛЯ КОЖНОГО
            # ========================================================

            click_methods = [
                ("JS click()", self._click_method_js_click),
                ("JS dispatchEvent", self._click_method_js_dispatch),
                ("Selenium click()", self._click_method_selenium),
                ("ActionChains click", self._click_method_action_chains),
                ("PyAutoGUI click", self._click_method_pyautogui),
            ]

            for method_name, method_func in click_methods:
                logger.info(f"Trying: {method_name}...")
                try:
                    # Оновити посилання на кнопку перед кожною спробою
                    btn = self._find_generate_button()
                    if not btn:
                        logger.warning("Button disappeared, re-finding...")
                        continue

                    method_func(btn)
                    time.sleep(2)

                    # Перевірка чи спрацювало (з урахуванням початкової кількості)
                    if self._verify_generation_started(btn_text, initial_queue_count):
                        logger.success(f"[OK] Generation started via {method_name}")
                        return True
                    else:
                        logger.warning(f"  {method_name} - no effect, trying next...")

                except Exception as e:
                    logger.warning(f"  {method_name} failed: {e}")

            logger.error("ALL 5 click methods FAILED!")
            return False

        except NoSuchElementException:
            logger.error("Generate button not found (NoSuchElement)")
            return False

    def _count_queue_indicators(self) -> int:
        """Підрахувати кількість видимих queue indicators на сторінці."""
        driver = self.browser.driver
        count = 0

        queue_selectors = [
            '[class*="queue"]',
            '[class*="generating"]',
            '[class*="progress"]',
            '[class*="loading"]',
            'div[class*="spinner"]',
            '.animate-spin',
            '[data-state="generating"]',
        ]

        for selector in queue_selectors:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                for el in elements:
                    try:
                        if el.is_displayed():
                            count += 1
                    except:
                        pass
            except:
                continue

        return count

    def _find_generate_button(self):
        """Знайти Generate кнопку різними способами."""
        driver = self.browser.driver

        # Спосіб 1: button.bg-primary
        try:
            btn = driver.find_element(By.CSS_SELECTOR, 'button.bg-primary')
            if btn and btn.is_displayed():
                return btn
        except NoSuchElementException:
            pass

        # Спосіб 2: кнопка з текстом "Generate"
        try:
            buttons = driver.find_elements(By.TAG_NAME, "button")
            for b in buttons:
                try:
                    text = b.text.strip().lower()
                    if "generate" in text and b.is_displayed():
                        return b
                except:
                    continue
        except:
            pass

        # Спосіб 3: CSS селектор з aria-label
        try:
            btn = driver.find_element(By.CSS_SELECTOR, 'button[aria-label*="Generate"]')
            if btn and btn.is_displayed():
                return btn
        except NoSuchElementException:
            pass

        # Спосіб 4: XPath з текстом
        try:
            btn = driver.find_element(By.XPATH, "//button[contains(text(), 'Generate')]")
            if btn and btn.is_displayed():
                return btn
        except NoSuchElementException:
            pass

        return None

    def _click_method_js_click(self, btn) -> None:
        """Метод 1: JavaScript click()"""
        self.browser.driver.execute_script("arguments[0].click();", btn)
        logger.debug("  JS click() executed")

    def _click_method_js_dispatch(self, btn) -> None:
        """Метод 2: JavaScript dispatchEvent з MouseEvent"""
        self.browser.driver.execute_script("""
            var event = new MouseEvent('click', {
                view: window,
                bubbles: true,
                cancelable: true,
                clientX: arguments[0].getBoundingClientRect().x + 10,
                clientY: arguments[0].getBoundingClientRect().y + 10
            });
            arguments[0].dispatchEvent(event);
        """, btn)
        logger.debug("  JS dispatchEvent executed")

    def _click_method_selenium(self, btn) -> None:
        """Метод 3: Selenium native click()"""
        btn.click()
        logger.debug("  Selenium click() executed")

    def _click_method_action_chains(self, btn) -> None:
        """Метод 4: ActionChains click"""
        from selenium.webdriver.common.action_chains import ActionChains
        actions = ActionChains(self.browser.driver)
        actions.move_to_element(btn).click().perform()
        logger.debug("  ActionChains click executed")

    def _click_method_pyautogui(self, btn) -> None:
        """Метод 5: PyAutoGUI click по координатах з підтримкою multi-monitor та DPI scaling"""
        import pyautogui
        import ctypes

        # Вимкнути failsafe для роботи на інших моніторах
        pyautogui.FAILSAFE = False

        driver = self.browser.driver

        # Активувати вікно браузера перед кліком (Windows)
        try:
            import win32gui
            import win32con

            # Отримати handle вікна браузера через title
            window_title = driver.title

            def find_window_callback(hwnd, windows):
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd)
                    if window_title and window_title in title:
                        windows.append(hwnd)
                return True

            windows = []
            win32gui.EnumWindows(find_window_callback, windows)

            if windows:
                hwnd = windows[0]
                # Активувати вікно
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(hwnd)
                time.sleep(0.3)  # Дати час на активацію
                logger.debug(f"  Browser window activated: hwnd={hwnd}")
        except ImportError:
            logger.debug("  win32gui not available, skipping window activation")
        except Exception as e:
            logger.debug(f"  Window activation failed: {e}")

        # Встановити DPI awareness для коректних координат на multi-monitor
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

        # Отримати точні координати кнопки через JavaScript
        # getBoundingClientRect() дає координати відносно viewport
        rect = driver.execute_script("""
            var rect = arguments[0].getBoundingClientRect();
            return {
                x: rect.left + rect.width / 2,
                y: rect.top + rect.height / 2
            };
        """, btn)

        # Позиція вікна браузера
        window_rect = driver.get_window_rect()

        # Динамічно обчислити висоту toolbar (різниця між зовнішньою і внутрішньою висотою)
        toolbar_height = driver.execute_script(
            "return window.outerHeight - window.innerHeight;"
        )

        # Координати на екрані = позиція вікна + координати у viewport + toolbar
        x = int(window_rect['x'] + rect['x'])
        y = int(window_rect['y'] + rect['y'] + toolbar_height)

        logger.debug(f"  PyAutoGUI clicking at ({x}, {y}), window_rect={window_rect}, toolbar_height={toolbar_height}")
        pyautogui.click(x, y)
        logger.debug("  PyAutoGUI click executed")

    def _verify_generation_started(self, original_btn_text: str, initial_queue_count: int = 0) -> bool:
        """
        Перевірити чи генерація запустилась.

        ВАЖЛИВО: Порівнюємо з initial_queue_count щоб не плутати
        з попередніми генераціями!

        Ознаки успіху:
        1. Кнопка змінила текст (напр. на "Generating..." або "In Queue")
        2. КІЛЬКІСТЬ queue indicators ЗБІЛЬШИЛАСЬ
        3. Кнопка стала disabled
        4. З'явився toast про старт генерації
        """
        driver = self.browser.driver

        # Перевірка 1: Текст кнопки змінився
        try:
            btn = self._find_generate_button()
            if btn:
                new_text = btn.text.strip()
                if new_text != original_btn_text:
                    logger.info(f"  Button text changed: '{original_btn_text[:20]}' -> '{new_text[:20]}'")
                    return True

                # Перевірка disabled
                is_disabled = driver.execute_script("""
                    var btn = arguments[0];
                    return btn.disabled || btn.classList.contains('disabled') ||
                           btn.classList.contains('opacity-50') || btn.classList.contains('cursor-not-allowed');
                """, btn)
                if is_disabled:
                    logger.info("  Button became disabled")
                    return True
        except:
            pass

        # Перевірка 2: КІЛЬКІСТЬ queue indicators ЗБІЛЬШИЛАСЬ
        current_queue_count = self._count_queue_indicators()
        if current_queue_count > initial_queue_count:
            logger.info(f"  Queue indicators increased: {initial_queue_count} -> {current_queue_count}")
            return True

        # Перевірка 3: Toast / notification
        try:
            toasts = driver.find_elements(By.CSS_SELECTOR, '[role="alert"], .toast, [class*="notification"]')
            for toast in toasts:
                if toast.is_displayed():
                    toast_text = toast.text.strip().lower()
                    if any(w in toast_text for w in ["queue", "generat", "start", "process"]):
                        logger.info(f"  Found toast: '{toast_text[:30]}'")
                        return True
        except:
            pass

        # Якщо нічого не змінилось - генерація НЕ почалась
        logger.debug(f"  No change detected (queue: {initial_queue_count} -> {current_queue_count})")
        return False

    # ========================================================================
    # GENERATION WAITING
    # ========================================================================

    async def _wait_for_video_generation(
        self,
        timeout: int = TIMEOUTS.VIDEO_GENERATION
    ) -> None:
        """
        Коротка пауза після кліку Generate.
        """
        logger.info("Waiting 5s after Generate click...")
        await asyncio.sleep(5)
        logger.info("Proceeding to wait for video...")

    def _check_video_download_ready(self) -> bool:
        """Перевірити чи є кнопка завантаження"""
        driver = self.browser.driver

        try:
            download_btns = driver.find_elements(
                By.XPATH,
                VIDEO_SELECTORS.DOWNLOAD_BUTTON
            )
            return len(download_btns) > 0
        except Exception:
            return False

    def _get_current_video_urls_sync(self) -> List[str]:
        """
        Отримати ВСІ URLs відео на сторінці HiggsField.

        Стратегія:
        1. Шукаємо video elements (якщо відео вже програється)
        2. Шукаємо a[href*.mp4] посилання
        3. Шукаємо download кнопки і отримуємо їх href
        4. Шукаємо будь-які атрибути з .mp4 або kling_motion
        """
        driver = self.browser.driver
        urls = []

        try:
            # Комплексний пошук всіх можливих URL відео
            js_urls = driver.execute_script("""
                var urls = [];

                // 1. Всі video elements (якщо відео програється)
                document.querySelectorAll('video').forEach(v => {
                    if (v.src && v.src.includes('.mp4')) urls.push(v.src);
                    if (v.currentSrc && v.currentSrc.includes('.mp4')) urls.push(v.currentSrc);
                    v.querySelectorAll('source').forEach(s => {
                        if (s.src && s.src.includes('.mp4')) urls.push(s.src);
                    });
                });

                // 2. Всі посилання на mp4
                document.querySelectorAll('a[href*=".mp4"]').forEach(a => {
                    urls.push(a.href);
                });

                // 3. Всі посилання на kling_motion (CDN відео HiggsField)
                document.querySelectorAll('a[href*="kling_motion"]').forEach(a => {
                    urls.push(a.href);
                });

                // 4. Download кнопки (a[download])
                document.querySelectorAll('a[download]').forEach(a => {
                    var href = a.getAttribute('href');
                    if (href && (href.includes('.mp4') || href.includes('kling_motion'))) {
                        urls.push(href);
                    }
                });

                // 5. Будь-які атрибути з mp4 або kling_motion
                document.querySelectorAll('*').forEach(el => {
                    for (var attr of el.attributes) {
                        if (attr.value && attr.value.startsWith('http')) {
                            if (attr.value.includes('.mp4') || attr.value.includes('kling_motion')) {
                                urls.push(attr.value);
                            }
                        }
                    }
                });

                // 6. Перевірити data-* атрибути
                document.querySelectorAll('[data-url], [data-video-url], [data-src], [data-video]').forEach(el => {
                    ['data-url', 'data-video-url', 'data-src', 'data-video'].forEach(attr => {
                        var val = el.getAttribute(attr);
                        if (val && (val.includes('.mp4') || val.includes('kling_motion'))) {
                            urls.push(val);
                        }
                    });
                });

                // 7. Шукаємо в style background-image
                document.querySelectorAll('[style*="kling_motion"]').forEach(el => {
                    var style = el.getAttribute('style');
                    var match = style.match(/url\\(['"]?(https?:[^'"\\)]+)['"]?\\)/);
                    if (match && match[1]) urls.push(match[1]);
                });

                return [...new Set(urls)];
            """)

            for url in (js_urls or []):
                if url and url.startswith('http') and url not in urls:
                    # Only include .mp4 video files (not .webp thumbnails)
                    if '.mp4' in url:
                        urls.append(url)

            logger.info(f"Found {len(urls)} video URLs on page")
            for url in urls[:5]:
                logger.info(f"  URL: {url[:80]}...")

        except Exception as e:
            logger.warning(f"Error getting video URLs: {e}")

        return urls

    def _click_newest_video_in_history(self) -> bool:
        """
        Клікнути на найновіше відео в History panel щоб завантажити його URL.

        Стратегія:
        1. Знайти History panel (праворуч)
        2. Клікнути на перший відео-елемент (найновіше)
        3. Чекати завантаження video player

        Returns:
            True якщо вдалося клікнути
        """
        driver = self.browser.driver

        try:
            # Спробуємо клікнути на перше відео в History
            clicked = driver.execute_script("""
                // Шукаємо відео items в History панелі
                // Зазвичай це елементи з video thumbnail + play button

                // Метод 1: Шукаємо елементи з іконкою play (SVG або button)
                var videoItems = document.querySelectorAll('[class*="video"], [class*="history"] video, [class*="gallery"] video');
                if (videoItems.length > 0) {
                    videoItems[0].click();
                    return 'video_element';
                }

                // Метод 2: Шукаємо thumbnail з play overlay
                var playButtons = document.querySelectorAll('[class*="play"], svg[class*="play"]');
                for (var i = 0; i < playButtons.length; i++) {
                    var parent = playButtons[i].closest('div[class*="item"], div[class*="card"], div[class*="video"]');
                    if (parent) {
                        parent.click();
                        return 'play_button';
                    }
                }

                // Метод 3: Шукаємо items в правій панелі (History)
                var historyPanel = document.querySelector('[class*="history"], [class*="sidebar"], [class*="right"]');
                if (historyPanel) {
                    var items = historyPanel.querySelectorAll('div[class*="item"], div[class*="card"]');
                    if (items.length > 0) {
                        items[0].click();
                        return 'history_item';
                    }
                }

                // Метод 4: Клікаємо на перший елемент з video всередині
                var videoContainers = document.querySelectorAll('div:has(video)');
                if (videoContainers.length > 0) {
                    videoContainers[0].click();
                    return 'video_container';
                }

                // Метод 5: Шукаємо download кнопку і клікаємо на її батьківський елемент
                var downloadBtns = document.querySelectorAll('[aria-label*="ownload"], [title*="ownload"], a[download]');
                for (var i = 0; i < downloadBtns.length; i++) {
                    var item = downloadBtns[i].closest('div[class*="item"], div[class*="card"]');
                    if (item) {
                        // Клікаємо на сам item щоб завантажити відео
                        item.click();
                        return 'download_parent';
                    }
                }

                return null;
            """)

            if clicked:
                logger.debug(f"Clicked on video item via: {clicked}")
                return True
            else:
                logger.debug("No video items found to click")
                return False

        except Exception as e:
            logger.warning(f"Error clicking video in history: {e}")
            return False

    async def _wait_for_new_video(
        self,
        initial_urls: List[str],
        timeout: int = 600,  # 10 хвилин max
        poll_interval: int = 30
    ) -> Optional[str]:
        """
        Чекати поки з'явиться НОВЕ відео (URL якого не було в initial_urls).

        Args:
            initial_urls: URLs які були ДО натискання Generate
            timeout: Максимальний час очікування
            poll_interval: Інтервал перевірки

        Returns:
            str: URL нового відео або None якщо timeout
        """
        logger.info(f"Waiting for NEW video (timeout={timeout}s)...")
        logger.info(f"  Initial URLs count: {len(initial_urls)}")
        initial_set = set(initial_urls)

        start_time = asyncio.get_event_loop().time()

        while True:
            elapsed = asyncio.get_event_loop().time() - start_time

            if elapsed > timeout:
                logger.error(f"Timeout waiting for new video after {timeout}s")
                return None

            # Refresh сторінки для оновлення списку відео
            logger.info(f"Checking for new video... ({elapsed:.0f}s elapsed)")
            await asyncio.to_thread(self.browser.driver.refresh)
            await asyncio.sleep(5)

            # Отримати поточні URLs
            current_urls = await asyncio.to_thread(self._get_current_video_urls_sync)
            logger.debug(f"  Current URLs count: {len(current_urls)}")

            # Знайти НОВІ URLs
            new_urls = [url for url in current_urls if url not in initial_set]

            if new_urls:
                # Беремо перший новий URL (найсвіжіший)
                new_url = new_urls[0]
                logger.success(f"Found NEW video URL!")
                logger.info(f"  URL: {new_url[:80]}...")
                return new_url

            await asyncio.sleep(poll_interval)

        return None

    async def _download_video_by_url(self, video_url: str, scene_num: int = 0) -> Path:
        """
        Завантажити конкретне відео за URL.

        Args:
            video_url: URL відео для завантаження
            scene_num: Номер сцени для імені файлу

        Returns:
            Path: Шлях до завантаженого файлу
        """
        output_path = self.download_dir / f"scene_{scene_num}_{int(time.time())}.mp4"

        logger.info(f"Downloading video from: {video_url[:80]}...")

        try:
            if self._http_client:
                response = await self._http_client.get(video_url, timeout=120)
            else:
                async with httpx.AsyncClient() as client:
                    response = await client.get(video_url, timeout=120)

            response.raise_for_status()

            content_length = len(response.content)
            size_mb = content_length / 1024 / 1024
            logger.info(f"  Video size: {size_mb:.2f} MB")

            if content_length < 10000:
                raise HiggsFieldWebDownloadError(f"Video file too small ({content_length} bytes)")

            output_path.write_bytes(response.content)
            logger.success(f"  Saved: {output_path}")

            return output_path

        except Exception as e:
            raise HiggsFieldWebDownloadError(
                f"Failed to download video from {video_url[:50]}...",
                cause=e
            )

    def _get_all_video_urls(self) -> List[str]:
        """Отримати всі URLs відео на сторінці (CloudFront URLs)"""
        driver = self.browser.driver
        urls = []

        try:
            # Метод 1: Знайти всі video елементи
            videos = driver.find_elements(By.TAG_NAME, "video")
            logger.info(f"Found {len(videos)} <video> elements")

            for video in videos:
                src = video.get_attribute("src")
                if src and src not in urls:
                    # Фільтруємо тільки CloudFront URLs (реальні відео)
                    if "cloudfront.net" in src or ".mp4" in src:
                        urls.append(src)
                        logger.debug(f"  Video src: {src[:80]}...")
                    continue

                sources = video.find_elements(By.TAG_NAME, "source")
                for source in sources:
                    src = source.get_attribute("src")
                    if src and src not in urls:
                        if "cloudfront.net" in src or ".mp4" in src:
                            urls.append(src)

            # Метод 2: data-* атрибути
            video_data_elements = driver.find_elements(
                By.CSS_SELECTOR,
                '[data-video-url], [data-src*="mp4"], [data-src*="cloudfront"]'
            )
            for el in video_data_elements:
                url = el.get_attribute("data-video-url") or el.get_attribute("data-src")
                if url and url not in urls and ("cloudfront" in url or ".mp4" in url):
                    urls.append(url)

            # Метод 3: JS для пошуку всіх video src
            js_urls = driver.execute_script("""
                var urls = [];
                document.querySelectorAll('video').forEach(v => {
                    if (v.src && v.src.includes('cloudfront')) urls.push(v.src);
                    v.querySelectorAll('source').forEach(s => {
                        if (s.src && s.src.includes('cloudfront')) urls.push(s.src);
                    });
                });
                return [...new Set(urls)];
            """)
            for url in (js_urls or []):
                if url not in urls:
                    urls.append(url)

            logger.info(f"CloudFront video URLs found: {len(urls)}")

            # Метод 4: CLICK на картки щоб відкрити модал і отримати реальний URL
            # HiggsField використовує lazy-loading для відео - клік відкриває модал з реальним URL
            if len(urls) <= 1:
                logger.info("Few URLs (lazy-loading) - clicking cards to extract real video URLs...")
                try:
                    from selenium.webdriver.common.action_chains import ActionChains
                    from selenium.webdriver.common.keys import Keys

                    # Отримати картки з data-asset-id (video thumbnails)
                    cards = driver.find_elements(By.CSS_SELECTOR, '[data-asset-id]')[:16]
                    logger.info(f"Found {len(cards)} video cards to click")

                    for i, card in enumerate(cards[:10]):  # Перевірити перші 10
                        try:
                            # Scroll до картки
                            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", card)
                            time.sleep(0.4)

                            # CLICK на картку щоб відкрити модал
                            card.click()
                            time.sleep(2.0)  # Почекати поки модал відкриється і відео завантажиться

                            # Знайти video в модалі (різні селектори)
                            modal_selectors = [
                                'div[role="dialog"] video',
                                '.modal video',
                                '[class*="modal"] video',
                                '[class*="Modal"] video',
                                'video[class*="player"]',
                                '[class*="preview"] video',
                                '[class*="Preview"] video'
                            ]

                            modal_videos = []
                            for selector in modal_selectors:
                                found = driver.find_elements(By.CSS_SELECTOR, selector)
                                modal_videos.extend(found)

                            # Якщо не знайшли в модалі, шукати будь-яке video з src
                            if not modal_videos:
                                modal_videos = driver.find_elements(By.TAG_NAME, "video")

                            for mv in modal_videos:
                                src = mv.get_attribute("src")
                                if src and src not in urls:
                                    if "cloudfront" in src or "cdn.higgsfield" in src or ".mp4" in src:
                                        urls.append(src)
                                        logger.debug(f"  Card {i+1} modal video: {src[:60]}...")
                                # Також перевірити source elements
                                sources = mv.find_elements(By.TAG_NAME, "source")
                                for source in sources:
                                    s_src = source.get_attribute("src")
                                    if s_src and s_src not in urls:
                                        if "cloudfront" in s_src or "cdn.higgsfield" in s_src or ".mp4" in s_src:
                                            urls.append(s_src)

                            # Закрити модал клавішею ESC
                            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                            time.sleep(0.5)

                        except Exception as card_err:
                            logger.debug(f"Card {i+1} click failed: {card_err}")
                            # Спробувати закрити модал якщо відкритий
                            try:
                                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                                time.sleep(0.3)
                            except:
                                pass

                    logger.info(f"After card clicks: {len(urls)} URLs")
                except Exception as click_err:
                    logger.warning(f"Card click approach failed: {click_err}")

        except Exception as e:
            logger.error(f"Error getting video URLs: {e}")

        return urls

    # ========================================================================
    # DOWNLOAD
    # ========================================================================

    async def _download_generated_video(
        self,
        exclude_urls: Optional[List[str]] = None
    ) -> Path:
        """
        Завантажити згенероване відео.

        Args:
            exclude_urls: URLs які потрібно ВИКЛЮЧИТИ (старі відео)
        """
        logger.info("Waiting for video generation and downloading...")
        exclude_urls = exclude_urls or []

        # ВАЖЛИВО: Перейти на сторінку галереї відео!
        logger.info("Navigating to video gallery...")
        await asyncio.to_thread(
            self.browser.driver.get, "https://higgsfield.ai/create/video"
        )
        await asyncio.sleep(5)

        max_retries = 12
        retry_delay = 30  # 30 сек між спробами, max 6 min wait
        video_url = None

        for attempt in range(1, max_retries + 1):
            # Scroll сторінку щоб завантажити lazy-load відео
            await asyncio.to_thread(
                self.browser.driver.execute_script,
                "window.scrollTo(0, document.body.scrollHeight);"
            )
            await asyncio.sleep(2)
            await asyncio.to_thread(
                self.browser.driver.execute_script,
                "window.scrollTo(0, 0);"
            )
            await asyncio.sleep(1)

            # Отримати всі URL відео на сторінці
            all_urls = await asyncio.to_thread(self._get_current_video_urls_sync)

            # Відфільтрувати старі відео
            new_urls = [url for url in all_urls if url not in exclude_urls]

            logger.info(f"[Attempt {attempt}/{max_retries}] Total: {len(all_urls)}, New: {len(new_urls)}, Excluded: {len(exclude_urls)}")

            if new_urls:
                video_url = new_urls[0]  # Перше НОВЕ відео
                logger.success(f"Found NEW video: {video_url[:60]}...")
                break

            if attempt < max_retries:
                logger.info(f"No NEW video yet, waiting {retry_delay}s...")
                await asyncio.sleep(retry_delay)
                # Refresh сторінки галереї
                await asyncio.to_thread(self.browser.driver.refresh)
                await asyncio.sleep(3)

        if not video_url:
            # FALLBACK: If no "new" video found, just download the first (newest) video
            all_urls = await asyncio.to_thread(self._get_current_video_urls_sync)
            if all_urls:
                video_url = all_urls[0]
                logger.warning(f"No NEW video found, using FALLBACK - downloading first video: {video_url[:60]}...")
            else:
                raise HiggsFieldWebDownloadError("No video found on page at all")

        output_path = self.download_dir / f"video_{int(time.time())}.mp4"

        try:
            logger.info(f"Downloading video from: {video_url[:80]}...")

            if self._http_client:
                response = await self._http_client.get(video_url, timeout=120)
            else:
                async with httpx.AsyncClient() as client:
                    response = await client.get(video_url, timeout=120)

            response.raise_for_status()

            content_length = len(response.content)
            logger.debug(f"Video size: {content_length / 1024 / 1024:.2f} MB")

            if content_length < 10000:
                logger.warning(f"Video file too small ({content_length} bytes), might be invalid")

            output_path.write_bytes(response.content)
            logger.info(f"Video saved to: {output_path}")

            self._last_generated_video_url = None
            return output_path

        except Exception as e:
            raise HiggsFieldWebDownloadError(
                f"Failed to download video from {video_url[:50]}...",
                cause=e
            )

    async def download_pending_videos(self, scene_dirs: Dict[int, Path]) -> Dict[int, Path]:
        """
        Скачать ВСЕ видео из очереди.

        Вызывать ПОСЛЕ того как все сцены поставлены в очередь генерации.

        Args:
            scene_dirs: Dict[scene_num -> output_dir] куда сохранять видео

        Returns:
            Dict[scene_num -> video_path] скачанные видео
        """
        if not self._pending_downloads:
            logger.warning("No pending downloads in queue")
            return {}

        logger.info("=" * 60)
        logger.info(f"DOWNLOADING {len(self._pending_downloads)} PENDING VIDEOS")
        logger.info("=" * 60)

        # Собрать ВСЕ initial_urls из всех сцен
        all_initial_urls = set()
        for item in self._pending_downloads:
            all_initial_urls.update(item['initial_urls'])

        logger.info(f"Total URLs to exclude: {len(all_initial_urls)}")

        # Перейти на страницу видео и обновить
        await self._navigate_to_video()
        await asyncio.sleep(5)

        downloaded: Dict[int, Path] = {}
        max_wait = 600  # 10 минут максимум на все видео
        poll_interval = 30
        start_time = asyncio.get_event_loop().time()

        while len(downloaded) < len(self._pending_downloads):
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > max_wait:
                logger.error(f"Timeout waiting for videos after {max_wait}s")
                break

            # Получить текущие URL
            current_urls = await asyncio.to_thread(self._get_current_video_urls_sync)
            new_urls = [url for url in current_urls if url not in all_initial_urls]

            logger.info(f"[{elapsed:.0f}s] Found {len(new_urls)} NEW videos (need {len(self._pending_downloads) - len(downloaded)} more)")

            # Скачать новые видео
            for url in new_urls:
                # Найти какой сцене принадлежит это видео (по порядку)
                for item in self._pending_downloads:
                    scene_num = item['scene_num']
                    if scene_num in downloaded:
                        continue  # Уже скачано

                    # Скачиваем в папку сцены
                    output_dir = scene_dirs.get(scene_num, self.download_dir)
                    output_path = output_dir / "video.mp4"

                    try:
                        logger.info(f"[Scene {scene_num}] Downloading: {url[:60]}...")

                        if self._http_client:
                            response = await self._http_client.get(url, timeout=120)
                        else:
                            async with httpx.AsyncClient() as client:
                                response = await client.get(url, timeout=120)

                        response.raise_for_status()
                        content = response.content

                        if len(content) < 10000:
                            logger.warning(f"[Scene {scene_num}] Video too small, skipping")
                            continue

                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        output_path.write_bytes(content)

                        downloaded[scene_num] = output_path
                        all_initial_urls.add(url)  # Добавить в exclude чтобы не скачать снова

                        logger.success(f"[Scene {scene_num}] Saved: {output_path}")
                        break

                    except Exception as e:
                        logger.error(f"[Scene {scene_num}] Download failed: {e}")

            if len(downloaded) < len(self._pending_downloads):
                logger.info(f"Waiting {poll_interval}s for more videos...")
                await asyncio.sleep(poll_interval)
                await self.browser.refresh()
                await asyncio.sleep(3)

        # Очистить очередь
        self._pending_downloads.clear()

        logger.info("=" * 60)
        logger.info(f"DOWNLOADED {len(downloaded)}/{len(self._pending_downloads)} VIDEOS")
        logger.info("=" * 60)

        return downloaded

    def _get_video_url(self) -> Optional[str]:
        """Отримати URL відео з DOM"""
        driver = self.browser.driver

        try:
            all_urls = []

            videos = driver.find_elements(By.TAG_NAME, "video")
            logger.debug(f"Found {len(videos)} video elements")

            for i, video in enumerate(videos):
                src = video.get_attribute("src")
                if src:
                    logger.debug(f"  Video {i} src: {src[:80]}...")
                    all_urls.append(src)
                    continue

                sources = video.find_elements(By.TAG_NAME, "source")
                for source in sources:
                    src = source.get_attribute("src")
                    if src:
                        logger.debug(f"  Video {i} source: {src[:80]}...")
                        all_urls.append(src)

            video_elements = driver.find_elements(
                By.CSS_SELECTOR,
                '[data-video-url], [data-src*="mp4"], [data-src*="video"]'
            )
            for el in video_elements:
                url = el.get_attribute("data-video-url") or el.get_attribute("data-src")
                if url and url not in all_urls:
                    logger.debug(f"  Data attr video: {url[:80]}...")
                    all_urls.append(url)

            if not all_urls:
                logger.warning("No video URLs found in DOM")
                return None

            # Пріоритет cloudfront/higgsfield
            for url in all_urls:
                if "cloudfront" in url or "higgsfield" in url:
                    logger.debug(f"Selected cloudfront/higgsfield video: {url[:80]}...")
                    return url

            for url in all_urls:
                if "mp4" in url.lower() or "video" in url.lower():
                    logger.debug(f"Selected first video URL: {url[:80]}...")
                    return url

            logger.debug(f"Using fallback video URL: {all_urls[0][:80]}...")
            return all_urls[0]

        except Exception as e:
            logger.warning(f"Failed to get video URL: {e}")
            return None

    # ========================================================================
    # MAIN GENERATION WORKFLOW
    # ========================================================================

    async def generate_video(
        self,
        image_path: Path,
        motion_prompt: str,
        duration: int = 10
    ) -> Path:
        """
        WORKFLOW: Генерація відео через Kling.

        Args:
            image_path: Шлях до початкового зображення (start frame)
            motion_prompt: Опис руху
            duration: Тривалість в секундах (5 або 10)

        Returns:
            Path: Шлях до завантаженого відео
        """
        logger.info("=" * 60)
        logger.info("GENERATING VIDEO - KLING 2.6")
        logger.info("=" * 60)
        logger.info(f"  Image: {image_path.name}")
        logger.info(f"  Duration: {duration}s")
        logger.info(f"  Aspect Ratio: {self.settings.aspect_ratio} (vertical video)")
        logger.info(f"  Prompt: {motion_prompt[:60]}...")
        logger.info("=" * 60)

        # Step 0: Navigate to video generation page FIRST!
        logger.info("Step 0/7: Navigating to video page...")
        await self._navigate_to_video()

        # Step 1: Очистити старий start frame
        logger.info("Step 1/7: Clearing old start frame...")
        await asyncio.to_thread(self._sync_clear_video_image)

        # Step 2: Завантажити картинку
        logger.info("Step 2/7: Uploading start frame...")
        await self._upload_start_frame(image_path)

        # Step 3: ★ Встановити aspect ratio 9:16 (ПІСЛЯ завантаження картинки!)
        logger.info("Step 3/7: ★ Setting aspect ratio to 9:16...")
        await self._set_aspect_ratio_9_16()

        # Step 4: Ввести промпт
        logger.info("Step 4/7: Entering motion prompt...")
        await asyncio.to_thread(self._sync_enter_video_prompt, motion_prompt)

        # Step 5: Wait for spinners to disappear before clicking Generate
        # Upload to Higgsfield server can take up to 90 seconds
        logger.info("Step 5/7: Waiting for upload spinners to disappear (max 90s)...")
        await self._wait_for_all_spinners_gone(timeout=90)

        # Step 5.5: Click Generate with retry (same as queue_single_video)
        logger.info("Step 5.5/7: Clicking Generate...")
        initial_urls = await asyncio.to_thread(self._get_current_video_urls_sync)

        max_retries = 3
        success = False

        for attempt in range(1, max_retries + 1):
            result = await asyncio.to_thread(self._sync_click_generate_space)
            if result:
                success = True
                break
            else:
                logger.warning(f"Generate click attempt {attempt}/{max_retries} FAILED")
                if attempt < max_retries:
                    logger.info("Retrying: clearing and re-entering data...")
                    await asyncio.sleep(2)
                    await asyncio.to_thread(self._sync_clear_video_image)
                    await asyncio.sleep(1)
                    await self._upload_start_frame(image_path)
                    await asyncio.to_thread(self._sync_enter_video_prompt, motion_prompt)
                    await asyncio.sleep(1)
                    await self._wait_for_all_spinners_gone(timeout=90)

        if not success:
            raise HiggsFieldWebGenerationError("Failed to start video generation after 3 attempts")

        await self._wait_for_video_generation()

        # Step 6: Завантажити відео
        logger.info("Step 6/7: Downloading video...")
        video_path = await self._download_generated_video(exclude_urls=initial_urls)

        logger.info("=" * 60)
        logger.success(f"✓ KLING VIDEO COMPLETE: {video_path}")
        logger.info(f"  Format: {self.settings.aspect_ratio} vertical video")
        logger.info("=" * 60)
        return video_path

    async def queue_single_video(
        self,
        image_path: Path,
        motion_prompt: str,
        scene_num: int,
        is_last: bool = False
    ) -> None:
        """
        Поставити одне відео в чергу.

        ОПТИМІЗОВАНИЙ WORKFLOW:
        1. Очистити поля (швидко)
        2. Завантажити картинку
        3. Ввести промпт
        4. Натиснути Generate
        5. Коротка пауза і далі (БЕЗ refresh!)
        """
        logger.info(f"")
        logger.info(f"[Scene {scene_num}] {'='*50}")
        logger.info(f"[Scene {scene_num}] QUEUEING VIDEO")
        logger.info(f"[Scene {scene_num}]   Image: {image_path.name}")
        logger.info(f"[Scene {scene_num}]   Prompt: {motion_prompt[:60]}...")

        # Step 1: Очистка полів (швидка)
        logger.info(f"[Scene {scene_num}] [1/4] Clearing fields...")
        await asyncio.to_thread(self._sync_clear_all_fields)
        await asyncio.sleep(1)

        # Step 2: Завантажити картинку
        logger.info(f"[Scene {scene_num}] [2/4] Uploading image...")
        await asyncio.to_thread(self._sync_start_upload, str(image_path.absolute()))

        # Step 3: Чекаємо upload (оптимізовано - 45 сек замість 90)
        logger.info(f"[Scene {scene_num}] [2/4] Waiting for upload (max 60s)...")
        await self._wait_for_upload_fast()

        # Step 3.5: Коротка пауза для UI (раніше 60с - занадто!)
        if scene_num > 1:
            logger.info(f"[Scene {scene_num}] [2.5/4] Short UI pause (5s)...")
            await asyncio.sleep(5)

        # Step 4: Ввести промпт
        logger.info(f"[Scene {scene_num}] [3/4] Entering prompt...")
        await asyncio.to_thread(self._sync_enter_video_prompt, motion_prompt)
        await asyncio.sleep(1)

        # Step 5: ЖДАТИ поки ВСІ спіннери зникнуть (upload spinner!)
        logger.info(f"[Scene {scene_num}] [4/4] Waiting for spinners to disappear...")
        await self._wait_for_all_spinners_gone(timeout=30)

        # Step 6: Натиснути Generate з retry
        logger.info(f"[Scene {scene_num}] [5/5] Clicking Generate (SPACE key)...")

        max_retries = 3
        success = False

        for attempt in range(1, max_retries + 1):
            result = await asyncio.to_thread(self._sync_click_generate_space)
            if result:
                success = True
                break
            else:
                logger.warning(f"[Scene {scene_num}] Generate click attempt {attempt}/{max_retries} FAILED")
                if attempt < max_retries:
                    # Спробувати перезавантажити форму
                    logger.info(f"[Scene {scene_num}] Retrying: clearing and re-entering data...")
                    await asyncio.sleep(2)
                    await asyncio.to_thread(self._sync_clear_all_fields)
                    await asyncio.sleep(1)
                    await asyncio.to_thread(self._sync_start_upload, str(image_path.absolute()))
                    await self._wait_for_upload_fast()
                    await asyncio.to_thread(self._sync_enter_video_prompt, motion_prompt)
                    await asyncio.sleep(1)
                    # КРИТИЧНО: Чекати поки спіннери зникнуть!
                    await self._wait_for_all_spinners_gone(timeout=30)

        if not success:
            logger.error(f"[Scene {scene_num}] FAILED TO START GENERATION after {max_retries} attempts!")
            logger.info(f"[Scene {scene_num}] {'='*50}")
            return  # Skip this scene

        # Step 6: Пауза для підтвердження (збільшено з 5 до 10 сек)
        logger.info(f"[Scene {scene_num}] Waiting 10s for queue confirmation...")
        await asyncio.sleep(10)

        # НЕ РОБИМО REFRESH! Просто очищаємо поля для наступної сцени
        if not is_last:
            logger.info(f"[Scene {scene_num}] Clearing for next scene (NO refresh)...")
            await asyncio.to_thread(self._sync_clear_all_fields)
            await asyncio.sleep(3)  # Збільшено з 2 до 3 сек

        logger.info(f"[Scene {scene_num}] QUEUED OK!")
        logger.info(f"[Scene {scene_num}] {'='*50}")

    def _sync_start_upload(self, image_path: str) -> None:
        """
        Почати upload без очікування (send_keys).

        ВАЖЛИВО: Обробляємо stale element reference через retry.
        """
        driver = self.browser.driver
        max_retries = 3

        # Check if file exists
        import os
        if not os.path.exists(image_path):
            logger.error(f"IMAGE FILE NOT FOUND: {image_path}")
            raise HiggsFieldWebElementNotFoundError(f"Image file not found: {image_path}")

        logger.info(f"Uploading image: {image_path}")
        logger.info(f"Image file exists, size: {os.path.getsize(image_path)} bytes")

        for attempt in range(1, max_retries + 1):
            try:
                # ЗАВЖДИ перешукуємо елементи (fresh reference)
                file_inputs = driver.find_elements(
                    By.CSS_SELECTOR,
                    VIDEO_SELECTORS.START_FRAME_INPUT
                )

                logger.info(f"Found {len(file_inputs)} file input(s) (attempt {attempt})")

                if not file_inputs:
                    if attempt < max_retries:
                        logger.warning(f"No file input found, retrying in 2s...")
                        time.sleep(2)
                        continue
                    raise HiggsFieldWebElementNotFoundError("No file input found after retries")

                file_input = file_inputs[0]

                # Clear the file input value first to ensure fresh upload
                try:
                    driver.execute_script("arguments[0].value = '';", file_input)
                    logger.debug("Cleared file input value")
                except Exception as e:
                    logger.debug(f"Could not clear file input: {e}")

                # Send the file path
                file_input.send_keys(image_path)
                logger.info(f"Upload started (send_keys sent to file input)")
                return  # Success!

            except StaleElementReferenceException as e:
                logger.warning(f"Stale element on attempt {attempt}/{max_retries}, retrying...")
                if attempt < max_retries:
                    time.sleep(2)  # Just wait and retry, NO refresh
                    continue
                else:
                    logger.error(f"Failed after {max_retries} attempts due to stale element")
                    raise

            except Exception as e:
                logger.error(f"Failed to start upload: {e}")
                raise

    async def _wait_for_upload_fast(self, timeout: int = 120) -> None:
        """
        ОПТИМІЗОВАНИЙ: Чекати поки upload завершиться.
        Без зайвих затримок - перевіряємо кожні 3 секунди.

        Args:
            timeout: Максимальний час очікування (60s)
        """
        start_time = asyncio.get_event_loop().time()
        check_interval = 3  # Перевіряємо кожні 3 секунди

        # Мінімальна пауза для початку upload
        await asyncio.sleep(5)

        while True:
            elapsed = asyncio.get_event_loop().time() - start_time

            if elapsed > timeout:
                logger.warning(f"Upload timeout after {timeout}s - proceeding anyway")
                return  # НЕ кидаємо помилку - продовжуємо

            # Перевіряємо чи картинка завантажена
            is_uploaded = await asyncio.to_thread(self._verify_start_frame_uploaded)

            if is_uploaded:
                logger.success(f"Upload OK in {elapsed:.1f}s")
                await asyncio.sleep(1)  # Коротка пауза
                return

            logger.debug(f"Upload in progress... ({elapsed:.0f}s)")
            await asyncio.sleep(check_interval)

    async def _wait_for_all_spinners_gone(self, timeout: int = 30) -> None:
        """
        Чекати поки ВСІ спіннери на сторінці зникнуть.
        КРИТИЧНО: Не можна натискати Generate поки спіннер крутиться!
        """
        logger.info(f"Waiting for all spinners to disappear (max {timeout}s)...")
        start_time = asyncio.get_event_loop().time()

        while True:
            elapsed = asyncio.get_event_loop().time() - start_time

            if elapsed > timeout:
                logger.warning(f"Spinner wait timeout after {timeout}s - proceeding anyway")
                return

            # Перевіряємо наявність спіннерів
            spinner_count = await asyncio.to_thread(self._count_visible_spinners)

            if spinner_count == 0:
                logger.success(f"All spinners gone in {elapsed:.1f}s")
                await asyncio.sleep(0.5)  # Коротка пауза
                return

            logger.debug(f"Still {spinner_count} spinner(s) visible... ({elapsed:.0f}s)")
            await asyncio.sleep(1)

    def _count_visible_spinners(self) -> int:
        """Підрахувати видимі спіннери (upload/loading indicators)."""
        driver = self.browser.driver
        count = 0

        spinner_selectors = [
            '.animate-spin',
            '[class*="loading"]',
            '[class*="spinner"]',
            'svg.animate-spin',
        ]

        for selector in spinner_selectors:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                for el in elements:
                    try:
                        if el.is_displayed():
                            count += 1
                    except:
                        pass
            except:
                continue

        # Also check .preload elements (start frame upload spinner)
        # If opacity > 0, spinner is active
        try:
            preload_count = driver.execute_script("""
                var count = 0;
                document.querySelectorAll('.preload').forEach(function(el) {
                    var style = window.getComputedStyle(el);
                    var opacity = parseFloat(style.opacity);
                    if (opacity > 0.1) {
                        count++;
                    }
                });
                return count;
            """)
            count += preload_count or 0
        except:
            pass

        # Check for "Uploading" text (start frame upload in progress)
        try:
            uploading_count = driver.execute_script("""
                var count = 0;
                var elements = document.querySelectorAll('*');
                for (var i = 0; i < elements.length; i++) {
                    var text = elements[i].textContent || '';
                    if (text.toLowerCase().includes('uploading') && elements[i].offsetWidth > 0) {
                        // Check it's a small element (not the whole page)
                        if (elements[i].textContent.length < 50) {
                            count++;
                            break;
                        }
                    }
                }
                return count;
            """)
            count += uploading_count or 0
        except:
            pass

        return count

    def _sync_click_generate_space(self) -> bool:
        """
        Натиснути Generate кнопку через ПРОБЕЛ (SPACE key).
        ВАЖЛИВО: Мишка не працює - тільки клавіатура!
        КРИТИЧНО: Спочатку закриваємо модал duration якщо він відкритий!
        """
        from selenium.webdriver.common.keys import Keys
        driver = self.browser.driver

        try:
            # КРИТИЧНО: Закрити модал duration якщо відкритий
            logger.debug("Closing any open modals before Generate...")
            self._sync_close_modal_if_exists()
            time.sleep(0.3)

            # Натиснути ESC для закриття будь-яких dropdown/модалів
            from selenium.webdriver.common.action_chains import ActionChains
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
            time.sleep(0.3)

            # Знайти кнопку
            btn = self._find_generate_button()
            if not btn:
                logger.error("Generate button not found")
                return False

            btn_text = btn.text.strip()
            logger.info(f"Generate button found: '{btn_text[:30]}'")

            # Перевірка що кнопка активна
            is_disabled = driver.execute_script("""
                var btn = arguments[0];
                return btn.disabled || btn.hasAttribute('disabled') ||
                       btn.classList.contains('disabled') || btn.classList.contains('opacity-50');
            """, btn)

            if is_disabled:
                logger.error("Generate button is DISABLED!")
                return False

            # Scroll до кнопки
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
            time.sleep(0.5)

            # КРИТИЧНО: Закрыть любые открытые dropdown (Duration, etc.)
            from selenium.webdriver.common.action_chains import ActionChains
            try:
                # Кликнуть в пустое место чтобы закрыть dropdown
                driver.execute_script("document.body.click();")
                time.sleep(0.3)
                # ESC для закрытия модалов
                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                time.sleep(0.3)
            except:
                pass

            # ПРОСТОЙ КЛИК - проверено что работает!
            logger.info("Clicking Generate: simple click()...")

            # Просто кликаем кнопку
            btn.click()
            time.sleep(0.5)

            # JS click для надёжности
            try:
                driver.execute_script("arguments[0].click();", btn)
            except:
                pass

            logger.info("Generate button clicked!")
            time.sleep(4)

            # Проверка 1: Popup 'Generation started' (самый надежный)
            try:
                body_text = driver.find_element(By.TAG_NAME, 'body').text.lower()
                if 'generation started' in body_text:
                    logger.success("Generation started! Found popup")
                    return True
            except:
                pass

            # Проверка 2: Кнопка disabled?
            try:
                new_btn = self._find_generate_button()
                if new_btn:
                    is_disabled = driver.execute_script("return arguments[0].disabled;", new_btn)
                    if is_disabled:
                        logger.success("Generation started! Button disabled")
                        return True
            except:
                pass

            # Проверка 3: Еще один JS клик + ждем popup
            logger.info("Extra JS click...")
            try:
                btn = self._find_generate_button()
                if btn:
                    driver.execute_script("arguments[0].click();", btn)
                    time.sleep(4)
                    body_text = driver.find_element(By.TAG_NAME, 'body').text.lower()
                    if 'generation started' in body_text:
                        logger.success("Generation started after extra click!")
                        return True
            except:
                pass

            logger.warning("No confirmation of generation start - retrying...")
            return False

        except Exception as e:
            logger.error(f"SPACE click failed: {e}")
            return False

    async def _wait_for_upload_verified(self, timeout: int = 180, min_wait: int = 90) -> None:
        """
        LEGACY: Чекати поки upload завершиться (старий метод).
        Використовуй _wait_for_upload_fast() замість цього.

        Args:
            timeout: Максимальний час очікування (180s = 3 min)
            min_wait: Мінімальний час очікування (60s для надійного upload)
        """
        start_time = asyncio.get_event_loop().time()
        check_interval = 10  # Перевіряємо кожні 10 секунд

        # ВАЖЛИВО: Мінімальний час очікування для upload
        logger.info(f"Waiting minimum {min_wait}s for full image upload...")
        await asyncio.sleep(min_wait)

        # Тепер перевіряємо чи картинка реально завантажилась (не просто X кнопка)
        while True:
            elapsed = asyncio.get_event_loop().time() - start_time

            if elapsed > timeout:
                logger.error(f"Upload verification TIMEOUT after {timeout}s - image not loaded!")
                raise HiggsFieldWebGenerationError("Start frame upload timed out - cannot proceed")

            # Перевіряємо чи картинка реально завантажена (naturalWidth > 100)
            is_uploaded = await asyncio.to_thread(self._verify_start_frame_uploaded)

            if is_uploaded:
                logger.success(f"Upload VERIFIED - image loaded in {elapsed:.1f}s")
                # Додаткова пауза після верифікації щоб UI встиг оновитись
                await asyncio.sleep(3)
                return

            logger.info(f"Image not fully loaded yet, waiting... ({elapsed:.0f}s elapsed)")
            await asyncio.sleep(check_interval)

        # Цей код не повинен виконатись
        logger.error("Upload verification failed - should not reach here")

    async def queue_all_scenes(
        self,
        scenes: list,  # List of (image_path, motion_prompt) or (image_path, motion_prompt, image_url) tuples
        on_scene_queued: callable = None
    ) -> None:
        """
        Поставити всі сцени в чергу генерації.

        Args:
            scenes: Список кортежів:
                - (image_path, motion_prompt) - звичайний режим з upload
                - (image_path, motion_prompt, image_url) - FAST режим через URL
            on_scene_queued: Callback після кожної сцени (optional)
        """
        total_scenes = len(scenes)
        logger.info("=" * 60)
        logger.info(f"QUEUEING {total_scenes} SCENES FOR VIDEO GENERATION")
        logger.info("=" * 60)

        # Перевіряємо чи є URL в сценах (FAST mode)
        has_urls = len(scenes) > 0 and len(scenes[0]) >= 3 and scenes[0][2]

        if has_urls:
            logger.info("FAST MODE: Using image URLs (no upload!)")
            # Для FAST mode потрібно бути на сторінці з галереєю
            await self.browser.navigate("https://higgsfield.ai/generate")
            await asyncio.sleep(5)
        else:
            # CRITICAL: Navigate to video page FIRST!
            logger.info("Step 0: Navigating to video page...")
            await self._navigate_to_video()
            logger.info("Step 0b: Using default model (no selection)")

            # ОЧИСТКА перед початком - промпт і картинка
            logger.info("Step 0c: Initial cleanup (prompt + frame)...")
            await asyncio.to_thread(self._sync_clear_all_fields)
            await asyncio.sleep(1)

        for i, scene_data in enumerate(scenes):
            scene_num = i + 1
            is_last = (scene_num == total_scenes)

            # Розпаковуємо дані сцени
            if len(scene_data) >= 3:
                image_path, motion_prompt, image_url = scene_data[0], scene_data[1], scene_data[2]
            else:
                image_path, motion_prompt = scene_data[0], scene_data[1]
                image_url = None

            # Використовуємо FAST mode якщо є URL, з fallback на upload
            if image_url:
                success = await self.queue_video_from_url(
                    image_url=image_url,
                    motion_prompt=motion_prompt,
                    scene_num=scene_num,
                    is_last=is_last
                )
                # Fallback to upload if FAST mode failed
                if not success and image_path:
                    logger.warning(f"[Scene {scene_num}] FAST mode failed, falling back to upload...")
                    # Navigate to video page for upload mode
                    await self._navigate_to_video()
                    await asyncio.to_thread(self._sync_clear_all_fields)
                    await asyncio.sleep(1)
                    await self.queue_single_video(
                        image_path=image_path,
                        motion_prompt=motion_prompt,
                        scene_num=scene_num,
                        is_last=is_last
                    )
            else:
                await self.queue_single_video(
                    image_path=image_path,
                    motion_prompt=motion_prompt,
                    scene_num=scene_num,
                    is_last=is_last
                )

            if on_scene_queued:
                on_scene_queued(scene_num, total_scenes)

        # ФИНАЛЬНАЯ очистка после всех сцен
        logger.info("Final cleanup after all scenes...")
        await asyncio.to_thread(self._sync_clear_all_fields)

        logger.info("=" * 60)
        logger.info(f"ALL {total_scenes} SCENES QUEUED!")
        logger.info("=" * 60)

    async def wait_for_all_videos(
        self,
        expected_count: int,
        timeout: int = 900,  # 15 хвилин max
        initial_wait: int = 240,  # 4 хвилини (оптимізовано з 5)
        allow_single_refresh: bool = True  # Один refresh наприкінці
    ) -> List[str]:
        """
        ОПТИМІЗОВАНО: Чекати поки всі відео згенеруються.
        БЕЗ refresh під час polling! Тільки один refresh в кінці якщо потрібно.

        Args:
            expected_count: Очікувана кількість нових відео
            timeout: Максимальний час очікування
            initial_wait: Час очікування перед першою перевіркою (4 хв)
            allow_single_refresh: Дозволити один refresh наприкінці

        Returns:
            List[str]: URLs згенерованих відео (в порядку сцен)
        """
        logger.info("")
        logger.info("=" * 60)
        logger.info(f"WAITING FOR {expected_count} VIDEOS")
        logger.info(f"Initial wait: {initial_wait}s ({initial_wait//60} min)")
        logger.info("=" * 60)

        start_time = asyncio.get_event_loop().time()
        poll_interval = 45  # Перевіряємо кожні 45 секунд (замість 30)

        # Перейти на сторінку з результатами
        logger.info("Navigating to video gallery...")
        await asyncio.to_thread(
            self.browser.driver.get, "https://higgsfield.ai/create/video"
        )
        await asyncio.sleep(5)

        # Запам'ятати початкові відео
        initial_urls = await asyncio.to_thread(self._get_all_video_urls)
        initial_set = set(initial_urls)
        logger.info(f"Initial videos on page: {len(initial_urls)}")

        # Очікування перед першою перевіркою
        logger.info(f"Waiting {initial_wait}s before first check...")
        await asyncio.sleep(initial_wait)

        cycle = 0
        refresh_used = False

        while True:
            cycle += 1
            elapsed = asyncio.get_event_loop().time() - start_time

            if elapsed > timeout:
                logger.warning(f"Timeout after {timeout}s")
                break

            # БЕЗ REFRESH! Тільки scroll для lazy-load
            logger.info(f"[Cycle {cycle}] Checking ({elapsed:.0f}s elapsed)...")
            await asyncio.to_thread(
                self.browser.driver.execute_script,
                "window.scrollTo(0, document.body.scrollHeight);"
            )
            await asyncio.sleep(2)
            await asyncio.to_thread(
                self.browser.driver.execute_script,
                "window.scrollTo(0, 0);"
            )
            await asyncio.sleep(1)

            # Читаємо DOM
            current_urls = await asyncio.to_thread(self._get_all_video_urls)
            new_urls = [url for url in current_urls if url not in initial_set]
            logger.info(f"[Cycle {cycle}] Found {len(new_urls)}/{expected_count} new videos")

            if len(new_urls) >= expected_count:
                logger.success(f"All {expected_count} videos generated!")
                result = list(reversed(new_urls[:expected_count]))
                return result

            # Один refresh в кінці якщо потрібно (після 6 хв)
            if allow_single_refresh and not refresh_used and elapsed > 360:
                logger.info("Single refresh to find missing videos...")
                await asyncio.to_thread(self.browser.driver.refresh)
                await asyncio.sleep(5)
                refresh_used = True

                current_urls = await asyncio.to_thread(self._get_all_video_urls)
                new_urls = [url for url in current_urls if url not in initial_set]
                logger.info(f"After refresh: found {len(new_urls)} new videos")

                if len(new_urls) >= expected_count:
                    logger.success(f"All {expected_count} videos found!")
                    return list(reversed(new_urls[:expected_count]))

            await asyncio.sleep(poll_interval)

        # Повернути що є
        final_urls = await asyncio.to_thread(self._get_all_video_urls)
        new_urls = [url for url in final_urls if url not in initial_set]
        logger.warning(f"Returning {len(new_urls)} videos (expected {expected_count})")
        return list(reversed(new_urls))

    async def get_video_asset_ids(self, count: int = 6) -> List[str]:
        """
        Отримати asset IDs відео з поточної сторінки.

        Args:
            count: Кількість asset IDs для повернення

        Returns:
            List[str]: Asset IDs в порядку DOM (newest first)
        """
        driver = self.browser.driver

        asset_ids = await asyncio.to_thread(lambda: driver.execute_script("""
            var ids = [];
            var cards = document.querySelectorAll('[data-asset-id]');
            for (var card of cards) {
                var id = card.getAttribute('data-asset-id');
                if (id && id.length > 10) ids.push(id);
            }
            return [...new Set(ids)];
        """))

        logger.info(f"Found {len(asset_ids)} asset IDs on page")
        return asset_ids[:count]

    async def download_videos_via_button(
        self,
        asset_ids: List[str],
        download_folder: Path,
        prefix: str = "scene"
    ) -> List[Path]:
        """
        Завантажити відео через кнопку Download на сторінці.

        Workflow:
        1. Для кожного asset_id: клікнути на картку → відкриється відео
        2. Клікнути кнопку Download
        3. Почекати завантаження
        4. Перемістити файл в папку проекту

        Args:
            asset_ids: Список asset IDs відео
            download_folder: Папка для збереження
            prefix: Префікс для імен файлів

        Returns:
            List[Path]: Шляхи до завантажених файлів
        """
        logger.info("=" * 60)
        logger.info(f"DOWNLOADING {len(asset_ids)} VIDEOS VIA BROWSER")
        logger.info("=" * 60)

        driver = self.browser.driver
        downloaded = []

        # Визначаємо папку завантажень браузера
        import os
        browser_download_dir = Path(os.environ.get('USERPROFILE', '')) / 'Downloads'

        for i, asset_id in enumerate(asset_ids):
            scene_num = i + 1
            logger.info(f"[Scene {scene_num}] Downloading asset: {asset_id[:12]}...")

            try:
                # Клікнути на картку відео
                clicked = await asyncio.to_thread(lambda aid=asset_id: driver.execute_script("""
                    var card = document.querySelector('[data-asset-id="' + arguments[0] + '"]');
                    if (card) {
                        var btn = card.querySelector('button');
                        if (btn) { btn.click(); return 'button'; }
                        card.click();
                        return 'card';
                    }
                    return null;
                """, aid))

                if not clicked:
                    logger.warning(f"[Scene {scene_num}] Card not found")
                    continue

                await asyncio.sleep(2)

                # Знайти URL відео для метаданих
                video_url = await asyncio.to_thread(lambda: driver.execute_script("""
                    var video = document.querySelector('video[src*="cloudfront"]');
                    return video ? video.src : '';
                """))

                # Клікнути кнопку Download
                download_clicked = await asyncio.to_thread(lambda: driver.execute_script("""
                    var buttons = document.querySelectorAll('button');
                    for (var btn of buttons) {
                        var svg = btn.querySelector('svg path[d*="M20.25 14.75"]');
                        if (svg) {
                            btn.click();
                            return true;
                        }
                    }
                    return false;
                """))

                if download_clicked:
                    logger.success(f"[Scene {scene_num}] Download button clicked!")
                else:
                    logger.error(f"[Scene {scene_num}] Download button not found")
                    continue

                # Почекати завантаження (15-25 секунд для 20-50MB)
                await asyncio.sleep(20)

                # Знайти новий файл в папці завантажень
                mp4_files = sorted(
                    browser_download_dir.glob('*.mp4'),
                    key=lambda x: x.stat().st_mtime,
                    reverse=True
                )

                if mp4_files:
                    newest_file = mp4_files[0]
                    # Перевіряємо що файл новий (менше 60 секунд)
                    if (time.time() - newest_file.stat().st_mtime) < 60:
                        output_path = download_folder / f"{prefix}_{scene_num}.mp4"
                        download_folder.mkdir(parents=True, exist_ok=True)

                        import shutil
                        shutil.move(str(newest_file), str(output_path))

                        size_mb = output_path.stat().st_size / 1024 / 1024
                        logger.success(f"[Scene {scene_num}] Saved: {output_path} ({size_mb:.1f} MB)")
                        downloaded.append(output_path)
                    else:
                        logger.warning(f"[Scene {scene_num}] No new download found")
                else:
                    logger.warning(f"[Scene {scene_num}] No MP4 in Downloads folder")

                # Закрити відео/повернутися
                await asyncio.to_thread(lambda: driver.execute_script("""
                    document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}));
                """))
                await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"[Scene {scene_num}] Failed: {e}")

        logger.info("=" * 60)
        logger.info(f"DOWNLOADED {len(downloaded)}/{len(asset_ids)} VIDEOS")
        logger.info("=" * 60)

        return downloaded

    async def download_videos(
        self,
        video_urls: List[str],
        prefix: str = "scene"
    ) -> List[Path]:
        """
        Завантажити список відео через HTTP.

        Args:
            video_urls: Список URLs відео
            prefix: Префікс для імен файлів

        Returns:
            List[Path]: Шляхи до завантажених файлів
        """
        logger.info("=" * 60)
        logger.info(f"DOWNLOADING {len(video_urls)} VIDEOS")
        logger.info("=" * 60)

        downloaded = []

        for i, url in enumerate(video_urls):
            scene_num = i + 1
            output_path = self.download_dir / f"{prefix}_{scene_num}_{int(time.time())}.mp4"

            try:
                logger.info(f"Downloading video {scene_num}/{len(video_urls)}...")

                if self._http_client:
                    response = await self._http_client.get(url, timeout=120)
                else:
                    async with httpx.AsyncClient() as client:
                        response = await client.get(url, timeout=120)

                response.raise_for_status()
                output_path.write_bytes(response.content)

                size_mb = len(response.content) / 1024 / 1024
                logger.info(f"  Saved: {output_path.name} ({size_mb:.2f} MB)")
                downloaded.append(output_path)

            except Exception as e:
                logger.error(f"Failed to download video {scene_num}: {e}")

        logger.info("=" * 60)
        logger.info(f"DOWNLOADED {len(downloaded)}/{len(video_urls)} VIDEOS")
        logger.info("=" * 60)

        return downloaded

    # =========================================================================
    # DOWNLOAD FROM GALLERY - Click each video card to get URL
    # =========================================================================

    async def download_from_gallery(
        self,
        count: int = 6,
        download_folder: Optional[Path] = None,
        prefix: str = "scene"
    ) -> List[Path]:
        """
        Скачати відео безпосередньо з галереї.
        Кліки на кожну картку, отримує URL з modal, скачує через HTTP.

        Args:
            count: Кількість відео для скачування (перші N = найновіші)
            download_folder: Папка для збереження
            prefix: Префікс для імен файлів

        Returns:
            List[Path]: Шляхи до завантажених файлів
        """
        logger.info("=" * 60)
        logger.info(f"DOWNLOAD FROM GALLERY: {count} videos")
        logger.info("=" * 60)

        driver = self.browser.driver
        output_folder = download_folder or self.download_dir
        output_folder.mkdir(parents=True, exist_ok=True)
        downloaded = []

        # Навігація на сторінку галереї
        logger.info("Navigating to video gallery...")
        driver.get("https://higgsfield.ai/create/video")
        await asyncio.sleep(5)

        # Клікаємо на вкладку History
        driver.execute_script("""
            var tabs = document.querySelectorAll('[role="tab"]');
            for (var t of tabs) {
                if (t.textContent.includes('History')) { t.click(); break; }
            }
        """)
        await asyncio.sleep(5)

        # Скрол для завантаження карток
        driver.execute_script("window.scrollTo(0, 500);")
        await asyncio.sleep(2)
        driver.execute_script("window.scrollTo(0, 0);")
        await asyncio.sleep(2)

        # Чекаємо поки з'являться картки (до 30 секунд)
        for attempt in range(15):
            card_count = driver.execute_script(
                "return document.querySelectorAll('[data-asset-id]').length;"
            )
            logger.info(f"Waiting for cards... attempt {attempt+1}, found {card_count}")
            if card_count >= count:
                break
            await asyncio.sleep(3)

        # Отримуємо всі картки з data-asset-id (відео)
        cards = driver.execute_script("""
            var cards = document.querySelectorAll('[data-asset-id]');
            var result = [];
            for (var i = 0; i < Math.min(cards.length, arguments[0]); i++) {
                result.push({
                    id: cards[i].getAttribute('data-asset-id'),
                    index: i
                });
            }
            return result;
        """, count)

        logger.info(f"Found {len(cards)} video cards to download")

        # Запам'ятовуємо файли в Downloads до початку
        import os
        downloads_dir = Path(os.environ.get('USERPROFILE', '')) / 'Downloads'
        before_files = set(downloads_dir.glob('*.mp4'))

        # Gallery shows newest first, so card 0 = last scene, card N-1 = scene 1
        for i, card in enumerate(cards):
            scene_num = count - i  # Reverse: card 0 = scene count, card count-1 = scene 1
            asset_id = card['id']
            logger.info(f"[Scene {scene_num}] Processing asset: {asset_id[:16]}...")

            try:
                # 1. Навести мишку на картку щоб з'явились кнопки (hover)
                from selenium.webdriver.common.action_chains import ActionChains
                card_el = driver.find_element(By.CSS_SELECTOR, f'[data-asset-id="{asset_id}"]')
                ActionChains(driver).move_to_element(card_el).perform()
                await asyncio.sleep(1)

                # 2. Знайти і клікнути кнопку Download (SVG path M20.25 14.75)
                download_clicked = driver.execute_script("""
                    var card = document.querySelector('[data-asset-id="' + arguments[0] + '"]');
                    if (!card) return 'card_not_found';

                    // Шукаємо кнопку Download всередині картки
                    var btns = card.querySelectorAll('button');
                    for (var btn of btns) {
                        var svg = btn.querySelector('svg');
                        if (svg) {
                            var paths = svg.querySelectorAll('path');
                            for (var p of paths) {
                                var d = p.getAttribute('d') || '';
                                // Download іконка має path M20.25 14.75...
                                if (d.includes('M20.25 14.75') || d.includes('M12 15V3.75')) {
                                    btn.click();
                                    return 'clicked_download';
                                }
                            }
                        }
                    }
                    return 'download_not_found';
                """, asset_id)

                if download_clicked:
                    logger.info(f"[Scene {scene_num}] Download button clicked: {download_clicked}")
                    await asyncio.sleep(15)  # Чекаємо завантаження

                    # Перевіряємо нові файли
                    after_files = set(downloads_dir.glob('*.mp4'))
                    new_files = after_files - before_files

                    if new_files:
                        # Беремо найновіший файл
                        newest = max(new_files, key=lambda f: f.stat().st_mtime)
                        output_path = output_folder / f"{prefix}_{scene_num}.mp4"

                        import shutil
                        shutil.move(str(newest), str(output_path))

                        size_mb = output_path.stat().st_size / 1024 / 1024
                        logger.success(f"[Scene {scene_num}] Saved: {output_path.name} ({size_mb:.1f} MB)")
                        downloaded.append(output_path)
                        before_files = set(downloads_dir.glob('*.mp4'))  # Оновлюємо список
                    else:
                        logger.warning(f"[Scene {scene_num}] No new file in Downloads")
                else:
                    logger.warning(f"[Scene {scene_num}] Download button not found")

                # Зняти виділення (клік в інше місце)
                driver.execute_script("document.body.click();")
                await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"[Scene {scene_num}] Failed: {e}")
                await asyncio.sleep(1)

        logger.info("=" * 60)
        logger.info(f"DOWNLOADED {len(downloaded)}/{count} VIDEOS FROM GALLERY")
        logger.info("=" * 60)

        return downloaded

    # =========================================================================
    # PARALLEL TABS - All scenes in separate tabs
    # =========================================================================

    async def queue_all_parallel(
        self,
        scenes: list,  # List of (image_path, motion_prompt) tuples
    ) -> None:
        """
        Запустити всі сцени ПАРАЛЕЛЬНО в окремих вкладках.

        Workflow:
        1. Відкрити N вкладок з video page (по одній на сцену)
        2. В кожній вкладці: завантажити картинку + ввести промпт
        3. Натиснути Generate в КОЖНІЙ вкладці
        4. Чекати генерації
        """
        total = len(scenes)
        logger.info("=" * 60)
        logger.info(f"PARALLEL MODE: {total} TABS")
        logger.info("=" * 60)

        driver = self.browser.driver
        video_url = "https://higgsfield.ai/create/video"

        # Зберігаємо handles вкладок
        tab_handles = []

        # Step 1: Відкрити всі вкладки
        # Note: By already imported at top of file
        from selenium.webdriver.common.keys import Keys

        logger.info(f"Step 1: Opening {total} tabs...")

        # Перша вкладка - головна
        driver.get(video_url)
        await asyncio.sleep(10)  # Чекаємо завантаження
        tab_handles.append(driver.current_window_handle)
        logger.info(f"  Tab 1 opened (main) - handle: {driver.current_window_handle[:20]}...")

        # Відкриваємо решту вкладок через ActionChains Ctrl+T
        body = driver.find_element(By.TAG_NAME, "body")

        for i in range(2, total + 1):
            initial_handles = set(driver.window_handles)

            # Ctrl+T для нової вкладки
            body.send_keys(Keys.CONTROL + 't')
            await asyncio.sleep(2)

            # Чекаємо появи нової вкладки
            for _ in range(10):
                current_handles = set(driver.window_handles)
                new_handles = current_handles - initial_handles
                if new_handles:
                    new_handle = list(new_handles)[0]
                    tab_handles.append(new_handle)
                    driver.switch_to.window(new_handle)
                    driver.get(video_url)
                    await asyncio.sleep(5)
                    logger.info(f"  Tab {i} opened - handle: {new_handle[:20]}...")
                    break
                await asyncio.sleep(0.5)
            else:
                logger.warning(f"  Tab {i} failed to open!")

        logger.info(f"  Total tabs opened: {len(tab_handles)}")

        # Чекаємо завантаження всіх вкладок
        logger.info("Step 1b: Waiting for all tabs to load (30s)...")
        await asyncio.sleep(30)

        # Step 2: В кожній вкладці завантажити картинку і ввести промпт
        logger.info(f"Step 2: Uploading images and prompts in each tab...")

        for i, (image_path, motion_prompt) in enumerate(scenes):
            scene_num = i + 1
            handle = tab_handles[i]

            logger.info(f"  Tab {scene_num}: switching...")
            driver.switch_to.window(handle)
            await asyncio.sleep(1)

            # Очистити старий кадр
            try:
                self._sync_clear_video_image()
            except Exception:
                pass
            await asyncio.sleep(1)

            # Чекаємо появи file input (сторінка завантажилась)
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            try:
                WebDriverWait(driver, 30).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="file"]'))
                )
            except Exception:
                logger.warning(f"  Tab {scene_num}: No file input found, page may not be loaded")
                continue

            # Завантажити картинку
            logger.info(f"  Tab {scene_num}: uploading {image_path.name}...")
            try:
                self._sync_start_upload(str(image_path.absolute()))
            except Exception as e:
                logger.error(f"  Tab {scene_num}: upload failed - {e}")
                continue

            # Ввести промпт
            logger.info(f"  Tab {scene_num}: entering prompt...")
            self._sync_enter_video_prompt(motion_prompt)

            await asyncio.sleep(2)
            logger.info(f"  Tab {scene_num}: ready!")

        # Step 3: Чекаємо повну загрузку всіх картинок (60s)
        logger.info("Step 3: Waiting 60s for all images to fully upload...")
        await asyncio.sleep(60)

        # Step 4: Натиснути Generate в КОЖНІЙ вкладці
        logger.info(f"Step 4: Clicking Generate in all {total} tabs...")

        for i in range(total):
            scene_num = i + 1
            handle = tab_handles[i]

            driver.switch_to.window(handle)
            await asyncio.sleep(0.5)

            logger.info(f"  Tab {scene_num}: clicking Generate...")
            try:
                self._sync_click_generate()
                logger.success(f"  Tab {scene_num}: Generate CLICKED!")
            except Exception as e:
                logger.error(f"  Tab {scene_num}: Generate FAILED - {e}")

            await asyncio.sleep(2)

        logger.info("=" * 60)
        logger.info(f"ALL {total} SCENES QUEUED IN PARALLEL!")
        logger.info("=" * 60)
        logger.info("Now wait for videos to generate on HiggsField...")

        # Повернутись на першу вкладку
        driver.switch_to.window(tab_handles[0])

    # ========================================================================
    # FAST VIDEO FROM URL (no upload!)
    # ========================================================================

    async def queue_video_from_url(
        self,
        image_url: str,
        motion_prompt: str,
        scene_num: int,
        is_last: bool = False
    ) -> bool:
        """
        FAST video gen - image already on HiggsField!
        1. Click image in gallery (by data-asset-preview)
        2. Enter prompt
        3. Click Generate

        Returns:
            True if successful, False if image not found (caller should fallback to upload)
        """
        logger.info(f"[Scene {scene_num}] FAST: from URL")
        logger.info(f"[Scene {scene_num}]   URL: {image_url[:70]}...")

        clicked = await asyncio.to_thread(self._click_image_by_url, image_url)
        if not clicked:
            logger.error(f"[Scene {scene_num}] Image not found in gallery!")
            return False
        await asyncio.sleep(3)

        await asyncio.to_thread(self._sync_enter_video_prompt, motion_prompt)
        await asyncio.sleep(2)

        await asyncio.to_thread(self._sync_click_generate)
        await asyncio.sleep(30)

        # NO REFRESH - прерывает загрузку!
        logger.info(f"[Scene {scene_num}] FAST done!")
        return True

    def _click_image_by_url(self, image_url: str) -> bool:
        """Find and click image by URL or asset-id"""
        driver = self.browser.driver
        import re
        match = re.search(r'/([a-f0-9-]{36})(?:_min)?\.', image_url)
        asset_id = match.group(1) if match else None

        if asset_id:
            try:
                imgs = driver.find_elements(
                    By.CSS_SELECTOR,
                    f'img[data-asset-preview="{asset_id}"]'
                )
                if imgs:
                    logger.info(f"Found image by asset-id: {asset_id}")
                    imgs[0].click()
                    return True
            except Exception:
                pass

        try:
            imgs = driver.find_elements(By.CSS_SELECTOR, 'img[data-asset-preview]')
            for img in imgs:
                src = img.get_attribute('src') or ''
                srcset = img.get_attribute('srcset') or ''
                if image_url in src or image_url in srcset:
                    logger.info("Found image by URL match")
                    img.click()
                    return True
        except Exception:
            pass

        logger.warning(f"Image not found for URL: {image_url[:60]}...")
        return False
