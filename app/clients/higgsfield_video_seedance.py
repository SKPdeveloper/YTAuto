"""
Seedance Video Generator - Генерація відео через Seedance 1.5 Pro модель.

WORKFLOW: Seedance Video Generation
1. Navigate to video page
2. Click "Change" button to open model selection
3. Select "Seedance 1.5 Pro" tab
4. Select "General" preset
5. Clear old start frame (X button if exists)
6. Set duration to 12s
7. Upload start frame
8. Enter motion prompt
9. Ensure Audio is OFF
10. Generate
11. Wait and download
"""

import asyncio
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List

import httpx
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

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
    SEEDANCE_SELECTORS,
    VIDEO_SELECTORS,
    TIMEOUTS,
)


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class SeedanceSettings:
    """Налаштування для Seedance 1.5 Pro"""
    model: str = "Seedance 1.5 Pro"
    preset: str = "General"
    duration: int = 12
    aspect_ratio: str = "9:16"
    audio: bool = False  # Audio має бути OFF


# ============================================================================
# SEEDANCE VIDEO GENERATOR
# ============================================================================

class SeedanceVideoGenerator:
    """
    Генератор відео через Seedance 1.5 Pro.

    Потребує AdsPowerClient для управління браузером.

    Usage:
        browser = AdsPowerClient(config)
        await browser.start_browser()

        generator = SeedanceVideoGenerator(browser, download_dir)
        video = await generator.generate_video(image_path, prompt)
    """

    def __init__(
        self,
        browser: AdsPowerClient,
        download_dir: Path,
        settings: Optional[SeedanceSettings] = None,
        http_client: Optional[httpx.AsyncClient] = None
    ):
        self.browser = browser
        self.download_dir = download_dir
        self.settings = settings or SeedanceSettings()
        self._http_client = http_client

        # Кешований URL останнього відео
        self._last_generated_video_url: Optional[str] = None

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
    # MODEL SELECTION (Seedance specific)
    # ========================================================================

    async def _select_seedance_model(self) -> None:
        """
        Вибрати модель Seedance 1.5 Pro.

        Steps:
        1. Click "Change" button
        2. Click "Seedance 1.5 Pro" tab
        3. Click "General" preset
        """
        logger.info("Selecting Seedance 1.5 Pro model...")
        await asyncio.to_thread(self._sync_select_seedance_model)

    def _sync_select_seedance_model(self) -> None:
        """Sync вибір моделі Seedance"""
        driver = self.browser.driver

        try:
            # Step 1: Click "Change" button
            logger.debug("Looking for 'Change' button...")
            change_btn = self._find_button_by_text("Change")

            if change_btn:
                driver.execute_script("arguments[0].click();", change_btn)
                logger.info("Clicked 'Change' button")
                time.sleep(1)  # Wait for model panel to open
            else:
                logger.warning("'Change' button not found, model may already be selected")

            # Step 2: Click "Seedance 1.5 Pro" tab
            logger.debug("Looking for 'Seedance 1.5 Pro' tab...")
            time.sleep(0.5)

            seedance_btn = self._find_button_by_text("Seedance 1.5 Pro")
            if not seedance_btn:
                seedance_btn = self._find_button_by_text("Seedance")

            if seedance_btn:
                driver.execute_script("arguments[0].click();", seedance_btn)
                logger.info("Selected Seedance 1.5 Pro")
                time.sleep(0.5)
            else:
                logger.warning("Seedance tab not found")

            # Step 3: Click "General" preset
            logger.debug("Looking for 'General' preset...")
            time.sleep(0.5)

            general_btn = self._find_button_by_text("General")
            if general_btn:
                driver.execute_script("arguments[0].click();", general_btn)
                logger.info("Selected 'General' preset")
                time.sleep(0.5)
            else:
                logger.warning("'General' preset not found")

        except Exception as e:
            logger.warning(f"Error selecting Seedance model: {e}")

    def _find_button_by_text(self, text: str):
        """Знайти кнопку за текстом"""
        driver = self.browser.driver
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for btn in buttons:
            try:
                btn_text = btn.text.strip()
                if text.lower() in btn_text.lower():
                    return btn
            except:
                continue
        return None

    # ========================================================================
    # START FRAME HANDLING
    # ========================================================================

    async def _clear_start_frame(self) -> None:
        """Видалити старий start frame якщо є"""
        logger.debug("Checking for existing start frame to clear...")
        await asyncio.to_thread(self._sync_clear_start_frame)

    def _sync_clear_start_frame(self) -> None:
        """Sync видалення start frame через X кнопку"""
        driver = self.browser.driver

        try:
            # Шукаємо X кнопку з специфічним path (4.11612)
            clear_btn = driver.execute_script("""
                // Шукаємо кнопку X біля start frame
                var buttons = document.querySelectorAll('button');
                for (var i = 0; i < buttons.length; i++) {
                    var btn = buttons[i];
                    var svg = btn.querySelector('svg');
                    if (svg) {
                        var path = svg.querySelector('path');
                        if (path) {
                            var d = path.getAttribute('d') || '';
                            // X icon має path з 4.11612
                            if (d.includes('4.11612')) {
                                return btn;
                            }
                        }
                    }
                }
                return null;
            """)

            if clear_btn:
                driver.execute_script("arguments[0].click();", clear_btn)
                logger.info("Cleared existing start frame")
                time.sleep(0.5)
            else:
                logger.debug("No start frame to clear (X button not found)")

        except Exception as e:
            logger.debug(f"Could not clear start frame: {e}")

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
                SEEDANCE_SELECTORS.START_FRAME_INPUT
            )

            if not file_inputs:
                raise HiggsFieldWebElementNotFoundError("No file input found for start frame")

            # Перший input - start frame
            start_frame_input = file_inputs[0]
            start_frame_input.send_keys(image_path)

            logger.debug("Start frame uploaded")
            logger.info(f"Waiting {TIMEOUTS.VIDEO_UPLOAD}s for start frame to upload...")
            time.sleep(TIMEOUTS.VIDEO_UPLOAD)

            # Верифікація
            if self._verify_start_frame_uploaded():
                logger.success("Start frame upload VERIFIED")
            else:
                logger.warning("Start frame upload verification uncertain")
                logger.info(f"Waiting additional {TIMEOUTS.IMAGE_UPLOAD_EXTRA}s...")
                time.sleep(TIMEOUTS.IMAGE_UPLOAD_EXTRA)

        except NoSuchElementException:
            raise HiggsFieldWebElementNotFoundError("Start frame file input not found")
        except Exception as e:
            logger.warning(f"Failed to upload start frame: {e}")

    def _verify_start_frame_uploaded(self) -> bool:
        """Перевірити чи start frame завантажено"""
        driver = self.browser.driver

        try:
            # Шукаємо X кнопку яка з'являється після завантаження
            result = driver.execute_script("""
                var buttons = document.querySelectorAll('button');
                for (var i = 0; i < buttons.length; i++) {
                    var btn = buttons[i];
                    var svg = btn.querySelector('svg path');
                    if (svg) {
                        var d = svg.getAttribute('d') || '';
                        if (d.includes('4.11612')) {
                            return true;
                        }
                    }
                }
                return false;
            """)
            return result
        except:
            return False

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

        Workflow:
        1. Знайти кнопку Aspect Ratio (може показувати поточне значення)
        2. Клікнути щоб відкрити dropdown
        3. Вибрати 9:16 опцію
        """
        driver = self.browser.driver

        try:
            # Спосіб 1: Шукаємо кнопку з aria-label="Aspect Ratio"
            logger.debug("Looking for Aspect Ratio button...")

            aspect_btn = None
            try:
                aspect_btn = driver.find_element(
                    By.CSS_SELECTOR,
                    SEEDANCE_SELECTORS.ASPECT_RATIO_BUTTON
                )
                logger.debug("Found Aspect Ratio button by aria-label")
            except NoSuchElementException:
                pass

            # Спосіб 2: Шукаємо по тексту що містить ":"
            if not aspect_btn:
                logger.debug("Trying to find button by text containing ':'...")
                aspect_btn = self._find_button_by_text(":")
                if aspect_btn:
                    logger.debug("Found Aspect Ratio button by ':' text")

            # Спосіб 3: Шукаємо кнопку з текстом 16:9 або 9:16 або 1:1
            if not aspect_btn:
                for ratio_text in ["16:9", "9:16", "1:1"]:
                    aspect_btn = self._find_button_by_text(ratio_text)
                    if aspect_btn:
                        logger.debug(f"Found button with ratio text: {ratio_text}")
                        break

            if not aspect_btn:
                logger.warning("Aspect Ratio button not found, trying JavaScript approach...")
                aspect_btn = driver.execute_script("""
                    var buttons = document.querySelectorAll('button');
                    for (var i = 0; i < buttons.length; i++) {
                        var text = buttons[i].textContent || '';
                        if (text.includes('16:9') || text.includes('9:16') || text.includes('1:1')) {
                            return buttons[i];
                        }
                    }
                    return null;
                """)

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
                        SEEDANCE_SELECTORS.ASPECT_RATIO_OPTION_9_16
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
    # DURATION SETTING
    # ========================================================================

    async def _set_duration_12s(self) -> None:
        """Встановити тривалість 12 секунд"""
        logger.debug("Setting duration to 12s...")
        await asyncio.to_thread(self._sync_set_duration_12s)

    def _sync_set_duration_12s(self) -> None:
        """Sync встановлення duration 12s"""
        driver = self.browser.driver

        try:
            # Знайти кнопку Duration
            duration_btn = driver.find_element(
                By.CSS_SELECTOR,
                SEEDANCE_SELECTORS.DURATION_BUTTON
            )

            if duration_btn:
                driver.execute_script("arguments[0].click();", duration_btn)
                time.sleep(0.5)

                # Знайти опцію 12s
                option_12s = driver.find_element(
                    By.CSS_SELECTOR,
                    SEEDANCE_SELECTORS.DURATION_OPTION_12S
                )

                if option_12s:
                    driver.execute_script("arguments[0].click();", option_12s)
                    logger.info("Duration set to 12s")
                else:
                    # Fallback: шукаємо по тексту
                    options = driver.find_elements(By.CSS_SELECTOR, '[role="option"]')
                    for opt in options:
                        if "12" in opt.text:
                            driver.execute_script("arguments[0].click();", opt)
                            logger.info("Duration set to 12s (via text)")
                            return
                    logger.warning("12s option not found")

        except NoSuchElementException:
            logger.warning("Duration button not found, trying by text...")
            btn = self._find_button_by_text("Duration")
            if btn:
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(0.5)
                options = driver.find_elements(By.CSS_SELECTOR, '[role="option"]')
                for opt in options:
                    if "12" in opt.text:
                        driver.execute_script("arguments[0].click();", opt)
                        logger.info("Duration set to 12s")
                        return
        except Exception as e:
            logger.warning(f"Failed to set duration: {e}")

    # ========================================================================
    # AUDIO TOGGLE
    # ========================================================================

    async def _ensure_audio_off(self) -> None:
        """Перевірити що Audio вимкнене"""
        logger.debug("Checking Audio toggle...")
        await asyncio.to_thread(self._sync_ensure_audio_off)

    def _sync_ensure_audio_off(self) -> None:
        """Sync перевірка що Audio OFF"""
        driver = self.browser.driver

        try:
            audio_toggle = driver.find_element(
                By.CSS_SELECTOR,
                SEEDANCE_SELECTORS.AUDIO_TOGGLE
            )

            if audio_toggle:
                state = audio_toggle.get_attribute("data-state")
                aria_checked = audio_toggle.get_attribute("aria-checked")

                is_on = state == "on" or state == "checked" or aria_checked == "true"

                if is_on:
                    # Вимкнути
                    driver.execute_script("arguments[0].click();", audio_toggle)
                    logger.info("Audio turned OFF")
                    time.sleep(0.3)
                else:
                    logger.debug("Audio already OFF")

        except NoSuchElementException:
            logger.debug("Audio toggle not found (may not be available)")
        except Exception as e:
            logger.debug(f"Could not check audio toggle: {e}")

    # ========================================================================
    # PROMPT HANDLING
    # ========================================================================

    def _sync_clear_prompt(self) -> None:
        """Очистити старий промпт з textarea"""
        driver = self.browser.driver

        try:
            textarea = driver.find_element(By.ID, "prompt")
            old_value = textarea.get_attribute('value') or ''

            if old_value.strip():
                logger.info(f"Found old prompt ({len(old_value)} chars), clearing...")

                # Очистити через React-сумісний спосіб
                driver.execute_script("""
                    var textarea = arguments[0];
                    textarea.focus();

                    // Native setter для React
                    var nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLTextAreaElement.prototype, 'value'
                    ).set;
                    nativeInputValueSetter.call(textarea, '');

                    // Dispatch events
                    textarea.dispatchEvent(new Event('input', { bubbles: true }));
                    textarea.dispatchEvent(new Event('change', { bubbles: true }));
                """, textarea)

                time.sleep(0.3)
                logger.info("Old prompt cleared")
            else:
                logger.debug("Prompt textarea is empty, nothing to clear")

        except NoSuchElementException:
            logger.debug("textarea#prompt not found for clearing")
        except Exception as e:
            logger.warning(f"Error clearing prompt: {e}")

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
                self._sync_clear_prompt()
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
            textarea = driver.find_element(By.CSS_SELECTOR, 'textarea')
            textarea.clear()
            textarea.send_keys(prompt)

    def _sync_click_generate(self) -> None:
        """
        Надійний клік на Generate кнопку з 5 fallback методами.
        Після кожної спроби перевіряємо чи генерація запустилась.
        """
        driver = self.browser.driver

        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.5)

            # Знайти кнопку
            btn = self._find_generate_button()
            if not btn:
                raise HiggsFieldWebElementNotFoundError("Generate button not found")

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
                return

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

                    # Перевірка чи спрацювало
                    if self._verify_generation_started(btn_text):
                        logger.success(f"✓ Generation started via {method_name}")
                        return
                    else:
                        logger.warning(f"  {method_name} - no effect, trying next...")

                except Exception as e:
                    logger.warning(f"  {method_name} failed: {e}")

            logger.error("ALL 5 click methods FAILED!")

        except NoSuchElementException:
            raise HiggsFieldWebElementNotFoundError("Generate button not found")

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

        # Спосіб 2: з селекторів
        try:
            buttons = driver.find_elements(By.CSS_SELECTOR, SEEDANCE_SELECTORS.GENERATE_BUTTON)
            if buttons and buttons[0].is_displayed():
                return buttons[0]
        except NoSuchElementException:
            pass

        # Спосіб 3: кнопка з текстом "Generate"
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
        """Метод 5: PyAutoGUI click по координатах"""
        import pyautogui

        # Отримати координати кнопки
        location = btn.location
        size = btn.size

        # Позиція вікна браузера
        window_rect = self.browser.driver.get_window_rect()

        # Координати центру кнопки на екрані
        x = window_rect['x'] + location['x'] + size['width'] // 2
        y = window_rect['y'] + location['y'] + size['height'] // 2 + 80  # +80 для toolbar

        logger.debug(f"  PyAutoGUI clicking at ({x}, {y})")
        pyautogui.click(x, y)
        logger.debug("  PyAutoGUI click executed")

    def _verify_generation_started(self, original_btn_text: str) -> bool:
        """
        Перевірити чи генерація запустилась.
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

        # Перевірка 2: З'явився елемент черги / генерації
        queue_indicators = [
            '[class*="queue"]',
            '[class*="generating"]',
            '[class*="progress"]',
            '[class*="loading"]',
            'div[class*="spinner"]',
            '.animate-spin',
            '[data-state="generating"]',
        ]

        for selector in queue_indicators:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                for el in elements:
                    if el.is_displayed():
                        logger.info(f"  Found queue indicator: {selector}")
                        return True
            except:
                continue

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

        return False

    # ========================================================================
    # GENERATION WAITING
    # ========================================================================

    async def _wait_for_video_generation(
        self,
        timeout: int = TIMEOUTS.VIDEO_GENERATION
    ) -> None:
        """Очікування завершення генерації відео"""
        logger.info(f"Waiting for video generation (timeout: {timeout}s)...")

        start_time = asyncio.get_event_loop().time()
        poll_interval = TIMEOUTS.POLL_INTERVAL
        min_wait = TIMEOUTS.MIN_VIDEO_WAIT

        # Запам'ятати початкові відео URLs
        initial_video_urls = await asyncio.to_thread(self._get_all_video_urls)
        logger.debug(f"Initial video URLs on page: {len(initial_video_urls)}")

        # Мінімальне очікування
        logger.debug(f"Waiting minimum {min_wait}s for video generation to start...")
        await asyncio.sleep(min_wait)

        max_cycles = 20

        for cycle in range(1, max_cycles + 1):
            elapsed = asyncio.get_event_loop().time() - start_time

            if elapsed > timeout:
                raise HiggsFieldWebTimeoutError(
                    f"Video generation timeout after {timeout}s",
                    details={"elapsed": elapsed}
                )

            logger.info(f"Video check cycle {cycle}/{max_cycles}, elapsed={elapsed:.1f}s...")

            await self.browser.refresh()
            await asyncio.sleep(5)
            await self.browser.wait_for_page_ready()

            current_video_urls = await asyncio.to_thread(self._get_all_video_urls)
            logger.debug(f"Current video URLs: {len(current_video_urls)}")

            new_videos = [url for url in current_video_urls if url not in initial_video_urls]

            if new_videos:
                logger.info(f"New video detected! Found {len(new_videos)} new video(s)")
                self._last_generated_video_url = new_videos[0]
                await asyncio.sleep(3)
                return

            await asyncio.sleep(poll_interval)

        logger.warning(f"Max cycles ({max_cycles}) reached. Final check...")
        await self.browser.refresh()
        await asyncio.sleep(5)
        await self.browser.wait_for_page_ready()

    def _get_all_video_urls(self) -> List[str]:
        """Отримати всі URLs відео на сторінці"""
        driver = self.browser.driver
        urls = []

        try:
            videos = driver.find_elements(By.TAG_NAME, "video")

            for video in videos:
                src = video.get_attribute("src")
                if src and src not in urls:
                    urls.append(src)
                    continue

                sources = video.find_elements(By.TAG_NAME, "source")
                for source in sources:
                    src = source.get_attribute("src")
                    if src and src not in urls:
                        urls.append(src)

        except Exception as e:
            logger.debug(f"Error getting video URLs: {e}")

        return urls

    # ========================================================================
    # DOWNLOAD
    # ========================================================================

    async def _download_generated_video(self) -> Path:
        """Завантажити згенероване відео"""
        logger.debug("Downloading generated video...")

        max_retries = 3
        retry_delay = 5
        video_url = None

        for attempt in range(1, max_retries + 1):
            if self._last_generated_video_url:
                video_url = self._last_generated_video_url
                logger.debug(f"Using cached video URL: {video_url[:80]}...")
                break

            video_url = await asyncio.to_thread(self._get_video_url)

            if video_url:
                logger.debug(f"Found video URL in DOM (attempt {attempt})")
                break

            if attempt < max_retries:
                logger.debug(f"No video URL found (attempt {attempt}/{max_retries}), retrying...")
                await asyncio.sleep(retry_delay)
                await self.browser.refresh()
                await asyncio.sleep(3)
                await self.browser.wait_for_page_ready()

        if not video_url:
            raise HiggsFieldWebDownloadError("Could not find video URL after all retries")

        output_path = self.download_dir / f"seedance_video_{int(time.time())}.mp4"

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

            output_path.write_bytes(response.content)
            logger.info(f"Video saved to: {output_path}")

            self._last_generated_video_url = None
            return output_path

        except Exception as e:
            raise HiggsFieldWebDownloadError(
                f"Failed to download video",
                cause=e
            )

    def _get_video_url(self) -> Optional[str]:
        """Отримати URL відео з DOM"""
        driver = self.browser.driver

        try:
            videos = driver.find_elements(By.TAG_NAME, "video")

            for video in videos:
                src = video.get_attribute("src")
                if src:
                    return src

                sources = video.find_elements(By.TAG_NAME, "source")
                for source in sources:
                    src = source.get_attribute("src")
                    if src:
                        return src

            return None

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
        duration: int = 12
    ) -> Path:
        """
        WORKFLOW: Seedance Video Generation

        Args:
            image_path: Шлях до початкового зображення (start frame)
            motion_prompt: Опис руху
            duration: Тривалість в секундах (default 12)

        Returns:
            Path: Шлях до завантаженого відео
        """
        logger.info("=" * 60)
        logger.info("GENERATING VIDEO (SEEDANCE 1.5 Pro)")
        logger.info("=" * 60)
        logger.info(f"  Image: {image_path.name}")
        logger.info(f"  Duration: {duration}s")
        logger.info(f"  Aspect Ratio: {self.settings.aspect_ratio} (vertical video)")
        logger.info(f"  Preset: {self.settings.preset}")
        logger.info(f"  Prompt: {motion_prompt[:60]}...")
        logger.info("=" * 60)

        # Step 1: Навігація
        logger.info("Step 1/11: Navigating to video page...")
        await self._navigate_to_video()

        # Step 2: Вибрати модель Seedance
        logger.info("Step 2/11: Selecting Seedance 1.5 Pro model...")
        await self._select_seedance_model()

        # Step 3: ★ АВТОМАТИЧНО встановити aspect ratio 9:16 (вертикальне відео)
        logger.info("Step 3/11: ★ Setting aspect ratio to 9:16 (vertical video for YouTube Shorts)...")
        await self._set_aspect_ratio_9_16()

        # Step 4: Очистити старий start frame (якщо є)
        logger.info("Step 4/11: Clearing old start frame (if exists)...")
        await self._clear_start_frame()

        # Step 5: Встановити duration 12s
        logger.info("Step 5/11: Setting duration to 12s...")
        await self._set_duration_12s()

        # Step 6: Завантажити start frame
        logger.info("Step 6/11: Uploading start frame...")
        await self._upload_start_frame(image_path)

        # Step 7: Ввести промпт
        logger.info("Step 7/11: Entering motion prompt...")
        await asyncio.to_thread(self._sync_enter_video_prompt, motion_prompt)

        # Step 8: Перевірити що Audio OFF
        logger.info("Step 8/11: Ensuring Audio is OFF...")
        await self._ensure_audio_off()

        # Step 9: Генерація
        logger.info("Step 9/11: Clicking Generate...")
        await asyncio.to_thread(self._sync_click_generate)

        # Step 10: Очікування
        logger.info("Step 10/11: Waiting for video generation...")
        await self._wait_for_video_generation()

        # Step 11: Завантаження
        logger.info("Step 11/11: Downloading video...")
        video_path = await self._download_generated_video()

        logger.info("=" * 60)
        logger.success(f"✓ SEEDANCE VIDEO COMPLETE: {video_path}")
        logger.info(f"  Format: {self.settings.aspect_ratio} vertical video")
        logger.info("=" * 60)
        return video_path

    async def queue_single_video(
        self,
        image_path: Path,
        motion_prompt: str,
        scene_num: int,
        duration: int = 12
    ) -> None:
        """Поставити одне відео в чергу (не чекає завершення)"""
        logger.info(f"[Scene {scene_num}] Queueing Seedance video...")
        logger.info(f"  Image: {image_path.name}")
        logger.info(f"  Prompt: {motion_prompt[:50]}...")

        # Clear old frame
        logger.info(f"[Scene {scene_num}] Clearing old start frame...")
        await self._clear_start_frame()

        # Upload new frame
        logger.info(f"[Scene {scene_num}] Uploading start frame...")
        await self._upload_start_frame(image_path)

        # Enter prompt
        logger.info(f"[Scene {scene_num}] Entering prompt...")
        await asyncio.to_thread(self._sync_enter_video_prompt, motion_prompt)

        # Ensure audio off
        await self._ensure_audio_off()

        # Click Generate
        logger.info(f"[Scene {scene_num}] Clicking Generate...")
        await asyncio.to_thread(self._sync_click_generate)

        # Wait briefly
        logger.info(f"[Scene {scene_num}] Waiting 15 seconds...")
        await asyncio.sleep(15)

        # Clear frame for next
        logger.info(f"[Scene {scene_num}] Clearing start frame...")
        await self._clear_start_frame()

        logger.info(f"[Scene {scene_num}] Seedance video queued!")
