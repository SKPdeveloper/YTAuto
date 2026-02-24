"""
Higgsfield Image Generator - Р"РµРЅРµСЂР°С†С–СЏ Р·РѕР±СЂР°Р¶РµРЅСЊ С‡РµСЂРµР· Р±СЂР°СѓР·РµСЂ.

Workflows:
- WORKFLOW 1 (PRIMARY): 4 РєР°РЅРґРёРґР°С‚Рё Р±РµР· СЂРµС„РµСЂРµРЅСЃСѓ
- WORKFLOW 2 (INDEPENDENT): 1 Р·РѕР±СЂР°Р¶РµРЅРЅСЏ Р±РµР· СЂРµС„РµСЂРµРЅСЃСѓ, Unlimited ON
- WORKFLOW 3 (REQUIRES_REF): 1 Р·РѕР±СЂР°Р¶РµРЅРЅСЏ Р· СЂРµС„РµСЂРµРЅСЃРѕРј
"""

import asyncio
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List

import httpx
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException

from loguru import logger

from app.core.errors import (
    HiggsFieldWebNavigationError,
    HiggsFieldWebElementNotFoundError,
    HiggsFieldWebGenerationError,
    HiggsFieldWebDownloadError,
)
from app.clients.adspower_client import AdsPowerClient
from app.clients.higgsfield_selectors import (
    HIGGSFIELD_IMAGE_URL,
    IMAGE_SELECTORS,
    JS_SCRIPTS,
    TIMEOUTS,
)


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class ImageSettings:
    """РќР°Р»Р°С€С‚СѓРІР°РЅРЅСЏ РґР»СЏ РіРµРЅРµСЂР°С†С–С— Р·РѕР±СЂР°Р¶РµРЅСЊ"""
    aspect_ratio: str = "9:16"
    resolution: str = "2K"
    unlimited: bool = False


@dataclass
class GeneratedImage:
    """Р РµР·СѓР»СЊС‚Р°С‚ РіРµРЅРµСЂР°С†С–С— Р·РѕР±СЂР°Р¶РµРЅРЅСЏ Р· URL С‚Р° Р»РѕРєР°Р»СЊРЅРёРј С€Р»СЏС…РѕРј"""
    path: Path          # Р›РѕРєР°Р»СЊРЅРёР№ С€Р»СЏС… РґРѕ СЃРєР°С‡Р°РЅРѕРіРѕ С„Р°Р№Р»Сѓ
    url: str            # URL РЅР° HiggsField (РґР»СЏ РІС–РґРµРѕ РіРµРЅРµСЂР°С†С–С—)
    index: int = 0      # Р†РЅРґРµРєСЃ РІ batch


# ============================================================================
# IMAGE GENERATOR
# ============================================================================

class HiggsFieldImageGenerator:
    """
    Р"РµРЅРµСЂР°С‚РѕСЂ Р·РѕР±СЂР°Р¶РµРЅСЊ С‡РµСЂРµР· Higgsfield Web UI.

    РџРѕС‚СЂРµР±СѓС" AdsPowerClient РґР»СЏ СѓРїСЂР°РІР»С–РЅРЅСЏ Р±СЂР°СѓР·РµСЂРѕРј.

    Usage:
        browser = AdsPowerClient(config)
        await browser.start_browser()

        generator = HiggsFieldImageGenerator(browser, download_dir)
        images = await generator.generate_primary_candidates(prompt)
    """

    def __init__(
        self,
        browser: AdsPowerClient,
        download_dir: Path,
        settings: Optional[ImageSettings] = None,
        http_client: Optional[httpx.AsyncClient] = None
    ):
        self.browser = browser
        self.download_dir = download_dir
        self.settings = settings or ImageSettings()
        self._http_client = http_client

        # URL референсной картинки (для поиска по asset_id в галерее)
        self._reference_url: Optional[str] = None

        # Ensure download dir exists
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def set_reference_url(self, url: str) -> None:
        """Установить URL референсной картинки для поиска в галерее"""
        self._reference_url = url
        logger.info(f"[REFERENCE] Set reference URL: {url[:80]}...")

    # ========================================================================
    # NAVIGATION
    # ========================================================================

    async def _navigate_to_image(self, force: bool = False) -> None:
        """
        РџРµСЂРµР№С‚Рё РЅР° СЃС‚РѕСЂС–РЅРєСѓ РіРµРЅРµСЂР°С†С–С— Р·РѕР±СЂР°Р¶РµРЅСЊ.

        Args:
            force: РЇРєС‰Рѕ True - Р·Р°РІР¶РґРё РїРµСЂРµС…РѕРґРёС‚Рё. РЇРєС‰Рѕ False - РїСЂРѕРїСѓСЃС‚РёС‚Рё СЏРєС‰Рѕ РІР¶Рµ РЅР° СЃС‚РѕСЂС–РЅС†С–.
        """
        # РџРµСЂРµРІС–СЂРёС‚Рё С‡Рё РІР¶Рµ РЅР° СЃС‚РѕСЂС–РЅС†С–
        if not force:
            current_url = await asyncio.to_thread(lambda: self.browser.driver.current_url)
            if current_url and HIGGSFIELD_IMAGE_URL in current_url:
                logger.debug("Already on image page, skipping navigation")
                return

        logger.debug(f"Navigating to: {HIGGSFIELD_IMAGE_URL}")

        await self.browser.navigate(HIGGSFIELD_IMAGE_URL)

        # РџРµСЂРµРІС–СЂРёС‚Рё С‡Рё РЅРµ СЂРѕР·Р»РѕРіС–РЅРёР»Рѕ
        await self.browser.check_and_handle_logout()

        # РџРѕС‡РµРєР°С‚Рё Р·Р°РІР°РЅС‚Р°Р¶РµРЅРЅСЏ СЃС‚РѕСЂС–РЅРєРё
        await self.browser.wait_for_element(
            By.TAG_NAME,
            "textarea",
            TIMEOUTS.DEFAULT_WAIT
        )

        # РћС‡С–РєСѓРІР°РЅРЅСЏ РїРѕРІРЅРѕРіРѕ Р·Р°РІР°РЅС‚Р°Р¶РµРЅРЅСЏ UI
        logger.info(f"Waiting {TIMEOUTS.PAGE_LOAD}s for UI to fully load...")
        await asyncio.sleep(TIMEOUTS.PAGE_LOAD)
        logger.debug("Image page loaded")

    # ========================================================================
    # CLEANUP
    # ========================================================================

    async def clear_all_forms(self) -> None:
        """
        Очистити всi форми - промпт та референс.
        Викликати на початку та в кiнцi роботи для чистого стану.
        """
        logger.info("Clearing all forms (prompt + reference)...")

        # Очистити промпт
        await asyncio.to_thread(self._sync_clear_prompt)

        # Очистити референс
        await self._clear_reference_image()

        logger.info("All forms cleared")

    # ========================================================================
    # SETTINGS
    # ========================================================================

    async def _set_aspect_ratio(self, ratio: str) -> None:
        """Р’СЃС‚Р°РЅРѕРІРёС‚Рё aspect ratio РґР»СЏ Р·РѕР±СЂР°Р¶РµРЅРЅСЏ"""
        logger.debug(f"Setting aspect ratio: {ratio}")
        await asyncio.to_thread(self._sync_set_aspect_ratio, ratio)

    def _sync_set_aspect_ratio(self, ratio: str) -> None:
        """
        Sync setting aspect ratio using proper selectors.

        Workflow:
        1. Find aspect ratio button (aria-label or text with :)
        2. Click to open dropdown
        3. Find and click the target option (9:16)
        """
        try:
            driver = self.browser.driver
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.5)

            # Method 1: Find button by aria-label
            btn = None
            try:
                btn = driver.find_element(By.CSS_SELECTOR, 'button[aria-label="Aspect Ratio"]')
                logger.debug("Found aspect ratio button by aria-label")
            except:
                pass

            # Method 2: Find button by data-key with ratio
            if not btn:
                try:
                    btns = driver.find_elements(By.CSS_SELECTOR, 'button[data-key]')
                    for b in btns:
                        key = b.get_attribute('data-key')
                        if key and ':' in key:
                            btn = b
                            logger.debug(f"Found aspect ratio button by data-key: {key}")
                            break
                except:
                    pass

            # Method 3: Find button with text containing ":"
            if not btn:
                btn = self.browser.find_button_by_text(":")
                if btn:
                    logger.debug("Found aspect ratio button by text ':'")

            if not btn:
                logger.warning("Aspect ratio button not found!")
                return

            # Click button to open dropdown
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(0.5)

            # Method 1: Find option by data-key
            option_selector = f'[role="option"][data-key="{ratio}"]'
            try:
                option = driver.find_element(By.CSS_SELECTOR, option_selector)
                driver.execute_script("arguments[0].click();", option)
                logger.success(f"Aspect ratio set to {ratio} (by data-key)")
                return
            except:
                pass

            # Method 2: Find option by text
            options = driver.find_elements(By.CSS_SELECTOR, '[role="option"]')
            for opt in options:
                opt_text = opt.text.strip()
                if ratio in opt_text:
                    driver.execute_script("arguments[0].click();", opt)
                    logger.success(f"Aspect ratio set to {ratio} (by text: '{opt_text}')")
                    return

            logger.warning(f"Aspect ratio option {ratio} not found in dropdown!")

        except Exception as e:
            logger.warning(f"Failed to set aspect ratio: {e}")

    async def _set_resolution(self, resolution: str) -> None:
        """Р’СЃС‚Р°РЅРѕРІРёС‚Рё СЂРѕР·РґС–Р»СЊРЅСѓ Р·РґР°С‚РЅС–СЃС‚СЊ"""
        logger.debug(f"Setting resolution: {resolution}")
        await asyncio.to_thread(self._sync_set_resolution, resolution)

    def _sync_set_resolution(self, resolution: str) -> None:
        """
        Р’СЃС‚Р°РЅРѕРІР»РµРЅРЅСЏ resolution С‡РµСЂРµР· dropdown.

        Workflow:
        1. Р—РЅР°Р№С‚Рё РєРЅРѕРїРєСѓ dropdown (РїРѕРєР°Р·СѓС" 1K Р°Р±Рѕ 2K)
        2. РљР»С–РєРЅСѓС‚Рё С‰РѕР± РІС–РґРєСЂРёС‚Рё
        3. РџРѕС‡РµРєР°С‚Рё РїРѕРєРё dropdown РІС–РґРєСЂРёС"С‚СЊСЃСЏ
        4. Р—РЅР°Р№С‚Рё С– РєР»С–РєРЅСѓС‚Рё РЅР° 2K РѕРїС†С–СЋ
        """
        driver = self.browser.driver

        try:
            logger.info(f"Setting resolution to: {resolution}")

            # Scroll down to see resolution controls
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.5)

            # Step 1: Find resolution dropdown button (contains "1K" or "2K" text)
            dropdown_btn = driver.execute_script("""
                // Find button with aria-haspopup="listbox" that contains resolution text
                var buttons = document.querySelectorAll('button[aria-haspopup="listbox"]');
                for (var i = 0; i < buttons.length; i++) {
                    var text = buttons[i].textContent || '';
                    if (text.includes('1K') || text.includes('2K') || text.includes('4K')) {
                        console.log('Found resolution dropdown:', text);
                        return buttons[i];
                    }
                }
                return null;
            """)

            if not dropdown_btn:
                logger.warning("Resolution dropdown button not found")
                return

            current_text = dropdown_btn.text
            logger.info(f"Current resolution dropdown text: '{current_text}'")

            # Check if already 2K
            if '2K' in current_text:
                logger.info("Resolution already set to 2K, skipping")
                return

            # Step 2: Click to open dropdown
            logger.info("Clicking resolution dropdown to open...")
            driver.execute_script("arguments[0].click();", dropdown_btn)
            time.sleep(1.0)  # Wait for dropdown animation

            # Step 3: Wait for dropdown to appear and find 2K option
            # Try multiple strategies to find the 2K option
            option_clicked = driver.execute_script("""
                // Strategy 1: Look for role="option" elements
                var options = document.querySelectorAll('[role="option"]');
                console.log('Found ' + options.length + ' role=option elements');

                for (var i = 0; i < options.length; i++) {
                    var text = options[i].textContent || '';
                    console.log('Option ' + i + ': ' + text);
                    if (text.includes('2K')) {
                        console.log('Clicking 2K option!');
                        options[i].click();
                        return 'option_clicked';
                    }
                }

                // Strategy 2: Look for listbox items
                var listbox = document.querySelector('[role="listbox"]');
                if (listbox) {
                    var items = listbox.querySelectorAll('div[role], div[class*="item"], div[class*="option"]');
                    console.log('Found ' + items.length + ' listbox items');

                    for (var i = 0; i < items.length; i++) {
                        var text = items[i].textContent || '';
                        if (text.includes('2K')) {
                            console.log('Clicking 2K listbox item!');
                            items[i].click();
                            return 'listbox_clicked';
                        }
                    }
                }

                // Strategy 3: Look for any clickable element with 2K text
                var allElements = document.querySelectorAll('div, button, span');
                for (var i = 0; i < allElements.length; i++) {
                    var el = allElements[i];
                    var text = el.textContent || '';
                    var style = window.getComputedStyle(el);

                    // Look for visible elements with 2K text that are likely dropdown options
                    if (text.includes('2K') && style.display !== 'none' && style.visibility !== 'hidden') {
                        var rect = el.getBoundingClientRect();
                        // Check if element is visible and reasonably sized (dropdown option)
                        if (rect.height > 20 && rect.height < 100 && rect.width > 50) {
                            // Check if it's within viewport (dropdown should be visible)
                            if (rect.top > 0 && rect.top < window.innerHeight) {
                                console.log('Clicking 2K element: ' + el.tagName + ' at ' + rect.top);
                                el.click();
                                return 'element_clicked';
                            }
                        }
                    }
                }

                return 'not_found';
            """)

            logger.info(f"2K selection result: {option_clicked}")

            if option_clicked and option_clicked != 'not_found':
                time.sleep(0.5)
                # Verify the change
                new_text = dropdown_btn.text if dropdown_btn else ""
                logger.info(f"Resolution dropdown after click: '{new_text}'")
                if '2K' in new_text:
                    logger.success(f"Resolution successfully set to 2K")
                else:
                    logger.warning(f"Resolution may not have changed (current: '{new_text}')")
            else:
                logger.warning("2K option not found in dropdown - trying direct click approach")

                # Fallback: try clicking by coordinates relative to dropdown
                time.sleep(0.3)
                dropdown_btn.click()  # Reopen if closed
                time.sleep(0.5)

                # Look for 2K text and click its parent
                driver.execute_script("""
                    var walker = document.createTreeWalker(
                        document.body,
                        NodeFilter.SHOW_TEXT,
                        null,
                        false
                    );

                    while (walker.nextNode()) {
                        if (walker.currentNode.textContent.includes('2K')) {
                            var parent = walker.currentNode.parentElement;
                            if (parent) {
                                var rect = parent.getBoundingClientRect();
                                if (rect.top > 0 && rect.height > 10) {
                                    parent.click();
                                    console.log('Clicked 2K text parent');
                                    break;
                                }
                            }
                        }
                    }
                """)
                time.sleep(0.3)

        except Exception as e:
            logger.warning(f"Failed to set resolution: {e}")

    async def _set_image_count(self, count: int) -> None:
        """Р’СЃС‚Р°РЅРѕРІРёС‚Рё РєС–Р»СЊРєС–СЃС‚СЊ Р·РѕР±СЂР°Р¶РµРЅСЊ РґР»СЏ РіРµРЅРµСЂР°С†С–С— (1-4)"""
        logger.info(f"Setting image count to: {count}")
        await asyncio.to_thread(self._sync_set_image_count, count)

    def _sync_set_image_count(self, count: int) -> None:
        """Sync встановлення кількості зображень через кнопки +/-"""
        driver = self.browser.driver

        if count < 1:
            count = 1
        if count > 4:
            count = 4

        logger.info(f"[IMAGE_COUNT] Setting image count to {count}...")

        def find_plus_minus_buttons():
            return driver.execute_script(JS_SCRIPTS.find_plus_minus_buttons())

        try:
            # Спочатку перевіримо чи кнопки взагалі є
            initial_buttons = find_plus_minus_buttons()
            if not initial_buttons or (not initial_buttons.get('plus') and not initial_buttons.get('minus')):
                logger.warning(f"[IMAGE_COUNT] ⚠️ +/- buttons NOT FOUND! UI may have changed.")
                logger.warning(f"[IMAGE_COUNT] Count will remain at previous value (likely 4)")
                return

            logger.info(f"[IMAGE_COUNT] Found buttons: plus={bool(initial_buttons.get('plus'))}, minus={bool(initial_buttons.get('minus'))}")

            # Крок 1: Скинути до мінімуму (1)
            minus_clicks = 0
            logger.info("[IMAGE_COUNT] Step 1: Resetting to minimum (1)...")
            for i in range(4):
                buttons = find_plus_minus_buttons()
                minus_btn = buttons.get('minus') if buttons else None

                if not minus_btn:
                    logger.info(f"[IMAGE_COUNT] Minus button gone after {i} clicks - reached minimum (1)")
                    break

                try:
                    driver.execute_script("arguments[0].click();", minus_btn)
                    minus_clicks += 1
                    time.sleep(0.2)
                except Exception:
                    break

            logger.info(f"[IMAGE_COUNT] Clicked minus {minus_clicks} times")
            time.sleep(0.3)

            # Крок 2: Збільшити до потрібної кількості
            clicks_needed = count - 1
            plus_clicks = 0
            if clicks_needed > 0:
                logger.info(f"[IMAGE_COUNT] Step 2: Increasing to {count} (need {clicks_needed} clicks)...")

                for i in range(clicks_needed):
                    buttons = find_plus_minus_buttons()
                    plus_btn = buttons.get('plus') if buttons else None

                    if not plus_btn:
                        logger.warning(f"[IMAGE_COUNT] Plus button gone after {i} clicks")
                        break

                    try:
                        driver.execute_script("arguments[0].click();", plus_btn)
                        plus_clicks += 1
                        time.sleep(0.2)
                    except Exception as e:
                        logger.warning(f"[IMAGE_COUNT] Failed to click +: {e}")
                        break

                logger.info(f"[IMAGE_COUNT] Clicked plus {plus_clicks} times")

            # Верифікація
            final_count = 1 + plus_clicks  # Починаємо з 1, додаємо кліки
            if final_count == count:
                logger.info(f"[IMAGE_COUNT] ✅ Image count set to {count}")
            else:
                logger.warning(f"[IMAGE_COUNT] ⚠️ Expected {count}, but set {final_count}")

        except Exception as e:
            logger.error(f"[IMAGE_COUNT] ❌ Failed to set image count: {e}")

    async def _set_unlimited(self, enabled: bool) -> None:
        """Р’СЃС‚Р°РЅРѕРІРёС‚Рё Unlimited toggle"""
        logger.debug(f"Setting Unlimited: {enabled}")
        await asyncio.to_thread(self._sync_set_unlimited, enabled)

    def _sync_set_unlimited(self, enabled: bool) -> None:
        """Sync РІСЃС‚Р°РЅРѕРІР»РµРЅРЅСЏ Unlimited toggle"""
        driver = self.browser.driver

        try:
            switches = driver.find_elements(
                By.CSS_SELECTOR,
                IMAGE_SELECTORS.UNLIMITED_SWITCH
            )

            if not switches:
                logger.warning("Unlimited switch not found")
                return

            switch = switches[0]
            logger.debug("Found Unlimited switch")

            current_state = switch.get_attribute("data-state")
            is_on = (current_state == "on" or current_state == "checked" or
                     switch.get_attribute("aria-checked") == "true")

            logger.debug(f"Current Unlimited state: {current_state} (is_on={is_on})")

            if is_on != enabled:
                driver.execute_script("arguments[0].click();", switch)
                time.sleep(0.3)

                new_state = switch.get_attribute("data-state")
                logger.info(f"Unlimited toggled: {current_state} -> {new_state}")
            else:
                logger.info(f"Unlimited already {'ON' if enabled else 'OFF'}")

        except Exception as e:
            logger.warning(f"Failed to set Unlimited: {e}")

    # ========================================================================
    # PROMPT HANDLING
    # ========================================================================

    def _sync_clear_prompt(self) -> None:
        """Очистити поле промпта - надійний метод з End+Backspace"""
        driver = self.browser.driver

        try:
            textarea = driver.find_element(By.CSS_SELECTOR, IMAGE_SELECTORS.PROMPT_TEXTAREA)
            logger.debug("Found prompt textarea for clearing")

            # Scroll to textarea and focus
            driver.execute_script("""
                var textarea = arguments[0];
                textarea.scrollIntoView({block: 'center'});
                textarea.focus();
            """, textarea)
            time.sleep(0.3)

            # Method 1: Try JS clear first
            driver.execute_script("""
                var textarea = arguments[0];
                var nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLTextAreaElement.prototype, 'value'
                ).set;
                nativeInputValueSetter.call(textarea, '');
                textarea.dispatchEvent(new Event('input', { bubbles: true }));
                textarea.dispatchEvent(new Event('change', { bubbles: true }));
            """, textarea)
            time.sleep(0.2)

            # Method 2: If JS didn't work, use End + multiple Backspace (reliable for React)
            current_value = textarea.get_attribute('value') or ''
            if current_value:
                textarea.click()
                time.sleep(0.1)
                textarea.send_keys(Keys.END)
                # Delete char by char (works with React state)
                for _ in range(len(current_value) + 10):
                    textarea.send_keys(Keys.BACKSPACE)
                time.sleep(0.1)

            # Verify
            current_value = textarea.get_attribute('value') or ''
            if current_value:
                logger.warning(f"Prompt not fully cleared, still has: {len(current_value)} chars")
            else:
                logger.info("Prompt cleared successfully")

        except NoSuchElementException:
            logger.warning("Prompt textarea not found for clearing")
        except Exception as e:
            logger.warning(f"Failed to clear prompt: {e}")

    def _sync_enter_prompt(self, prompt: str) -> None:
        """Sync РІРІС–Рґ prompt РІ textarea С‡РµСЂРµР· JavaScript РґР»СЏ React"""
        driver = self.browser.driver

        try:
            selectors = [
                IMAGE_SELECTORS.PROMPT_TEXTAREA,
                IMAGE_SELECTORS.PROMPT_TEXTAREA_ALT1,
                IMAGE_SELECTORS.PROMPT_TEXTAREA_ALT2,
                IMAGE_SELECTORS.PROMPT_TEXTAREA_ALT3,
                IMAGE_SELECTORS.PROMPT_TEXTAREA_FALLBACK,
            ]

            textarea = None
            for selector in selectors:
                try:
                    textarea = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                    )
                    logger.info(f"Found textarea with selector: {selector}")
                    break
                except:
                    logger.debug(f"Selector {selector} not found, trying next...")
                    continue

            if not textarea:
                raise NoSuchElementException("No textarea found with any selector")

            result = driver.execute_script(
                JS_SCRIPTS.set_react_textarea_value(),
                textarea,
                prompt
            )

            time.sleep(0.3)

            if result and result > 50:
                logger.info(f"Prompt entered via JS ({result} chars)")
            else:
                logger.warning(f"JS method returned {result} chars, trying ActionChains...")
                from selenium.webdriver.common.action_chains import ActionChains

                actions = ActionChains(driver)
                actions.move_to_element(textarea).click().perform()
                time.sleep(0.2)

                actions = ActionChains(driver)
                actions.key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).perform()
                time.sleep(0.1)
                actions = ActionChains(driver)
                actions.send_keys(Keys.DELETE).perform()
                time.sleep(0.1)

                actions = ActionChains(driver)
                actions.send_keys(prompt).perform()
                time.sleep(0.3)

        except NoSuchElementException:
            raise HiggsFieldWebElementNotFoundError("Prompt textarea not found")

    def _sync_click_generate(self) -> None:
        """Sync клік на Generate кнопку"""
        driver = self.browser.driver

        try:
            # Ждём появления кнопки (до 10 сек)
            logger.info("[GENERATE] Waiting for Generate button...")
            btn = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, IMAGE_SELECTORS.GENERATE_BUTTON))
            )

            btn_disabled = btn.get_attribute("disabled")
            btn_text = btn.text or btn.get_attribute("innerText") or ""
            logger.info(f"[GENERATE] Button found: disabled={btn_disabled}, text='{btn_text[:30]}'")

            # Если кнопка disabled - ждём до 5 сек пока станет активной
            if btn_disabled:
                logger.info("[GENERATE] Button is disabled, waiting for it to become enabled...")
                for _ in range(10):
                    time.sleep(0.5)
                    btn_disabled = btn.get_attribute("disabled")
                    if not btn_disabled:
                        logger.info("[GENERATE] Button is now enabled!")
                        break
                else:
                    logger.warning("[GENERATE] Button still disabled after 5s, clicking anyway...")

            # Скроллим к кнопке
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
            time.sleep(0.3)

            # Кликаем
            driver.execute_script("arguments[0].click();", btn)
            logger.success("[GENERATE] Generate button clicked!")

            # Ждём немного чтобы генерация началась
            time.sleep(1)

        except Exception as e:
            logger.error(f"[GENERATE] Failed to click Generate: {e}")
            raise HiggsFieldWebElementNotFoundError(f"Generate button error: {e}")

    # ========================================================================
    # REFERENCE IMAGE HANDLING
    # ========================================================================

    async def _upload_reference_image(
        self,
        image_path: Path,
        skip_if_exists: bool = False,
        reference_url: Optional[str] = None
    ) -> None:
        """
        Установить reference image для style consistency.

        Args:
            image_path: Локальный путь к картинке (для fallback)
            skip_if_exists: Пропустить если референс уже установлен
            reference_url: URL картинки на HiggsField (для поиска по asset_id)
        """
        logger.debug(f"Setting reference image: {image_path}")
        if reference_url:
            logger.debug(f"Reference URL: {reference_url[:80]}...")

        if not image_path.exists():
            raise HiggsFieldWebGenerationError(f"Reference image not found: {image_path}")

        if skip_if_exists:
            has_reference = await asyncio.to_thread(self._check_reference_exists)
            if has_reference:
                logger.info("Reference already uploaded, skipping...")
                return

        # Используем переданный URL или сохранённый в классе
        url_to_use = reference_url or self._reference_url
        if url_to_use:
            logger.info(f"[REFERENCE] Using URL for asset lookup: {url_to_use[:60]}...")

        await asyncio.to_thread(self._sync_upload_reference, str(image_path.absolute()), url_to_use)

    def _check_reference_exists(self) -> bool:
        """РџРµСЂРµРІС–СЂРёС‚Рё С‡Рё reference image РІР¶Рµ Р·Р°РІР°РЅС‚Р°Р¶РµРЅРѕ"""
        try:
            result = self.browser.execute_script(JS_SCRIPTS.check_reference_exists())
            if result:
                logger.debug("Reference image already exists on page")
            else:
                logger.debug("No reference image found on page")
            return result
        except Exception as e:
            logger.debug(f"Error checking reference: {e}")
            return False

    def _sync_upload_reference(self, image_path: str, reference_url: Optional[str] = None) -> None:
        """
        Установить референс через клик на кнопку Reference на картинке в галерее.

        Метод:
        1. Находим картинку в галерее по asset_id (из URL) или первую
        2. Наводим мышку чтобы появились кнопки
        3. Кликаем на кнопку Reference
        """
        driver = self.browser.driver

        # Извлекаем asset_id из URL если есть
        target_asset_id = None
        if reference_url:
            # URL формат: .../hf_20260126_063641_7878e367-0266-4539-8be3-412f72e6b854_min.webp
            # или содержит asset_id в пути
            import re
            # Ищем UUID паттерн в URL
            uuid_pattern = r'([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})'
            match = re.search(uuid_pattern, reference_url)
            if match:
                target_asset_id = match.group(1)
                logger.info(f"[REFERENCE] Extracted asset_id from URL: {target_asset_id}")

        logger.info(f"[REFERENCE] Setting reference from gallery image...")
        if target_asset_id:
            logger.info(f"[REFERENCE] Target asset_id: {target_asset_id}")

        try:
            # Step 1: Найти картинку в галерее
            logger.info("[REFERENCE] Step 1: Finding target image in gallery...")

            # Ищем картинку по asset_id или берём первую
            result = driver.execute_script("""
                var targetId = arguments[0];

                // Находим все картинки в галерее
                var assetDivs = document.querySelectorAll('[data-asset-id]');
                console.log('Found ' + assetDivs.length + ' asset divs');

                if (assetDivs.length === 0) {
                    return {success: false, error: 'no_assets'};
                }

                var targetAsset = null;

                // Если есть target asset_id - ищем по нему
                if (targetId) {
                    for (var i = 0; i < assetDivs.length; i++) {
                        var div = assetDivs[i];
                        var divId = div.getAttribute('data-asset-id');
                        if (divId === targetId) {
                            targetAsset = div;
                            console.log('Found target asset by ID at index ' + i);
                            break;
                        }
                    }
                }

                // Если не нашли по ID - берём первую
                if (!targetAsset) {
                    targetAsset = assetDivs[0];
                    console.log('Using first asset (target not found or not specified)');
                }

                var assetId = targetAsset.getAttribute('data-asset-id');

                // Скроллим к ней
                targetAsset.scrollIntoView({block: 'center'});

                return {success: true, assetId: assetId, count: assetDivs.length};
            """, target_asset_id)

            if not result or not result.get('success'):
                raise HiggsFieldWebGenerationError(f"No images found in gallery: {result}")

            logger.info(f"[REFERENCE] Found {result.get('count')} images, using: {result.get('assetId')}")

            time.sleep(0.5)

            # Step 2: Наводим мышку на картинку чтобы появилась кнопка Reference
            logger.info("[REFERENCE] Step 2: Hovering over image to show Reference button...")

            from selenium.webdriver.common.action_chains import ActionChains

            # Находим картинку по asset_id
            found_asset_id = result.get('assetId')
            target_asset = driver.find_element(By.CSS_SELECTOR, f'[data-asset-id="{found_asset_id}"]')

            # Реальный hover через ActionChains
            actions = ActionChains(driver)
            actions.move_to_element(target_asset).perform()

            # Ждём появления overlay с кнопкой
            time.sleep(1)

            # Теперь ищем кнопку Reference на этой картинке
            # Кнопка "Reference" - белый текст на overlay
            ref_button = driver.execute_script("""
                var targetId = arguments[0];
                var targetAsset = document.querySelector('[data-asset-id="' + targetId + '"]');
                if (!targetAsset) return null;

                // Ищем кнопку/элемент с текстом "Reference" внутри карточки
                var allElements = targetAsset.querySelectorAll('*');
                for (var i = 0; i < allElements.length; i++) {
                    var el = allElements[i];
                    var text = (el.textContent || '').trim();

                    // Точное совпадение "Reference"
                    if (text === 'Reference') {
                        console.log('Found Reference button (exact match):', el.tagName);
                        return el;
                    }
                }

                // Также проверяем весь документ - кнопка может быть в overlay поверх карточки
                var allDocs = document.querySelectorAll('*');
                for (var i = 0; i < allDocs.length; i++) {
                    var el = allDocs[i];
                    var text = (el.textContent || '').trim();
                    var style = window.getComputedStyle(el);

                    // Точное совпадение "Reference" и элемент видимый
                    if (text === 'Reference' && style.display !== 'none' && style.visibility !== 'hidden') {
                        var rect = el.getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0) {
                            console.log('Found Reference button in document:', el.tagName);
                            return el;
                        }
                    }
                }

                return null;
            """, found_asset_id)

            if ref_button:
                logger.info("[REFERENCE] Found Reference button, clicking...")
                driver.execute_script("arguments[0].click();", ref_button)
                time.sleep(1)
            else:
                # Если кнопки Reference нет при hover, кликаем на картинку
                # и ищем в открывшемся меню/модале
                logger.info("[REFERENCE] No Reference button on hover, clicking image...")

                driver.execute_script("""
                    var targetId = arguments[0];
                    var targetAsset = document.querySelector('[data-asset-id="' + targetId + '"]');
                    if (targetAsset) {
                        var img = targetAsset.querySelector('img');
                        if (img) {
                            img.click();
                        } else {
                            targetAsset.click();
                        }
                    }
                """, found_asset_id)
                time.sleep(1)

                # Ищем кнопку Reference в открывшемся модале/меню
                ref_button = driver.execute_script("""
                    // Ищем во всём документе кнопку Reference
                    var allButtons = document.querySelectorAll('button, [role="button"], [role="menuitem"]');
                    for (var i = 0; i < allButtons.length; i++) {
                        var btn = allButtons[i];
                        var text = (btn.textContent || '').toLowerCase();
                        var ariaLabel = (btn.getAttribute('aria-label') || '').toLowerCase();

                        if (text.includes('reference') || text.includes('use as ref') ||
                            ariaLabel.includes('reference') || ariaLabel.includes('use as ref')) {
                            console.log('Found Reference button in modal:', btn);
                            return btn;
                        }
                    }

                    // Также ищем в dropdown/popover
                    var popovers = document.querySelectorAll('[role="menu"], [role="listbox"], [class*="popover"], [class*="dropdown"]');
                    for (var i = 0; i < popovers.length; i++) {
                        var items = popovers[i].querySelectorAll('button, div, span, li');
                        for (var j = 0; j < items.length; j++) {
                            var item = items[j];
                            var text = (item.textContent || '').toLowerCase();
                            if (text.includes('reference') || text.includes('use as ref')) {
                                console.log('Found Reference in dropdown:', item);
                                return item;
                            }
                        }
                    }

                    return null;
                """)

                if ref_button:
                    logger.info("[REFERENCE] Found Reference button in modal/menu, clicking...")
                    driver.execute_script("arguments[0].click();", ref_button)
                    time.sleep(1)
                else:
                    logger.warning("[REFERENCE] Reference button not found, trying fallback...")
                    # Закрываем модал если открыт (нажимаем Escape)
                    from selenium.webdriver.common.action_chains import ActionChains
                    actions = ActionChains(driver)
                    actions.send_keys(Keys.ESCAPE).perform()
                    time.sleep(0.5)

                    # Пробуем fallback метод
                    raise Exception("Reference button not found on image")

            # Step 3: Проверяем что референс установлен
            logger.info("[REFERENCE] Step 3: Verifying reference is set...")
            time.sleep(2)

            for attempt in range(5):
                if self._verify_reference_uploaded():
                    logger.success(f"[REFERENCE] Reference set from gallery VERIFIED!")
                    return

                logger.debug(f"[REFERENCE] Verification attempt {attempt + 1}/5...")
                time.sleep(2)

            logger.warning("[REFERENCE] Could not verify reference, but continuing...")
            return

        except Exception as e:
            logger.warning(f"[REFERENCE] Gallery method failed: {e}")
            # Skip clipboard paste (unreliable) — go straight to file input methods
            logger.info("[REFERENCE] Trying direct file input method...")
            self._sync_upload_reference_direct_input(image_path)

    def _sync_upload_reference_fallback(self, image_path: str) -> None:
        """
        Fallback метод загрузки референса через clipboard paste.

        Копируем изображение в буфер обмена и вставляем через Ctrl+V в textarea.
        """
        driver = self.browser.driver

        logger.info(f"[REFERENCE FALLBACK] Uploading via clipboard paste: {image_path}")

        from pathlib import Path
        import io
        file_path = Path(image_path)

        try:
            # Step 1: Копируем изображение в буфер обмена Windows
            logger.info("[REFERENCE FALLBACK] Step 1: Copying image to clipboard...")

            from PIL import Image
            import win32clipboard

            # Открываем изображение
            img = Image.open(file_path)

            # Конвертируем в BMP для буфера обмена Windows
            output = io.BytesIO()
            # Конвертируем в RGB если нужно (для PNG с альфа-каналом)
            if img.mode == 'RGBA':
                img = img.convert('RGB')
            img.save(output, 'BMP')
            data = output.getvalue()[14:]  # Убираем BMP header
            output.close()

            # Копируем в буфер обмена
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
            win32clipboard.CloseClipboard()

            logger.info("[REFERENCE FALLBACK] Image copied to clipboard")

            # Step 2: Фокусируемся на textarea промпта
            logger.info("[REFERENCE FALLBACK] Step 2: Focusing on prompt textarea...")

            driver.execute_script("""
                var textarea = document.querySelector('textarea[name="prompt"]');
                if (textarea) {
                    textarea.focus();
                    textarea.click();
                    console.log('Textarea focused');
                }
            """)
            time.sleep(0.5)

            # Step 3: Вставляем через Ctrl+V
            logger.info("[REFERENCE FALLBACK] Step 3: Pasting with Ctrl+V...")

            from selenium.webdriver.common.action_chains import ActionChains
            actions = ActionChains(driver)
            actions.key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()

            logger.info("[REFERENCE FALLBACK] Ctrl+V sent")

            # Ждём обработки
            time.sleep(3)

            # Проверяем результат
            for attempt in range(5):
                if self._verify_reference_uploaded():
                    logger.success(f"[REFERENCE FALLBACK] Upload via paste VERIFIED!")
                    return

                logger.debug(f"[REFERENCE FALLBACK] Verification attempt {attempt + 1}/5...")
                time.sleep(2)

            # Если paste не сработал, пробуем через input напрямую
            logger.warning("[REFERENCE FALLBACK] Paste didn't work, trying direct input method...")
            self._sync_upload_reference_direct_input(image_path)

        except ImportError as e:
            logger.warning(f"[REFERENCE FALLBACK] Required module not available: {e}")
            logger.info("[REFERENCE FALLBACK] Trying direct input method...")
            self._sync_upload_reference_direct_input(image_path)

    def _sync_upload_reference_direct_input(self, image_path: str) -> None:
        """
        Direct method — find file input via Selenium find_element + send_keys.
        Falls back to proxy input (Strategy B) if direct approach fails.
        """
        driver = self.browser.driver

        logger.info(f"[REFERENCE DIRECT] Uploading: {image_path}")

        from pathlib import Path
        file_path = Path(image_path)
        absolute_path = str(file_path.absolute())

        # ================================================================
        # Strategy A: Selenium find_element + send_keys (most reliable)
        # For <input type="file">, send_keys works even on hidden elements
        # ================================================================
        logger.info("[REFERENCE DIRECT] Strategy A: Selenium find_element + send_keys...")

        ref_input = None

        # Try finding reference file input by ID first
        try:
            ref_input = driver.find_element(By.ID, 'image-form-reference')
            logger.info("[REFERENCE DIRECT] Found input by ID: image-form-reference")
        except NoSuchElementException:
            logger.debug("[REFERENCE DIRECT] No input with ID 'image-form-reference'")

        # Try CSS selector from selectors config
        if not ref_input:
            try:
                ref_input = driver.find_element(By.CSS_SELECTOR, 'input[type="file"][id*="ref"]')
                logger.info(f"[REFERENCE DIRECT] Found input by CSS: id={ref_input.get_attribute('id')}")
            except NoSuchElementException:
                logger.debug("[REFERENCE DIRECT] No input matching CSS selector")

        # Try any file input with 'reference' in attributes
        if not ref_input:
            file_inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="file"]')
            logger.info(f"[REFERENCE DIRECT] Found {len(file_inputs)} file inputs total")
            for inp in file_inputs:
                attrs = f"{inp.get_attribute('id')} {inp.get_attribute('name')} {inp.get_attribute('class')}".lower()
                if 'reference' in attrs or 'ref' in attrs:
                    ref_input = inp
                    logger.info(f"[REFERENCE DIRECT] Found reference input: id={inp.get_attribute('id')}, name={inp.get_attribute('name')}")
                    break

        if not ref_input:
            logger.warning("[REFERENCE DIRECT] No reference file input found on page")
            # Last resort: try proxy input method
            logger.info("[REFERENCE DIRECT] Falling back to Strategy B (proxy input)...")
            self._sync_upload_reference_proxy_input(image_path)
            return

        # Make input interactable (remove hidden/disabled attrs)
        driver.execute_script("""
            var inp = arguments[0];
            inp.style.cssText = 'position: fixed !important; top: 100px !important; left: 100px !important; ' +
                'z-index: 999999 !important; width: 400px !important; height: 50px !important; ' +
                'opacity: 1 !important; display: block !important; visibility: visible !important; ' +
                'pointer-events: auto !important;';
            inp.removeAttribute('hidden');
            inp.removeAttribute('aria-hidden');
            inp.disabled = false;
        """, ref_input)

        time.sleep(0.5)

        # Send file path via Selenium send_keys
        try:
            ref_input.send_keys(absolute_path)
            logger.info(f"[REFERENCE DIRECT] File sent to input: {file_path.name}")
        except Exception as e:
            logger.warning(f"[REFERENCE DIRECT] Strategy A send_keys failed: {e}")
            logger.info("[REFERENCE DIRECT] Falling back to Strategy B (proxy input)...")
            self._sync_upload_reference_proxy_input(image_path)
            return

        # Trigger React-compatible events
        driver.execute_script("""
            var inp = arguments[0];
            // Dispatch native events that React listens to
            ['input', 'change'].forEach(function(evtName) {
                var evt = new Event(evtName, {bubbles: true, cancelable: true});
                inp.dispatchEvent(evt);
            });
            // Restore hidden style after React processes the event
            setTimeout(function() { inp.style.cssText = ''; }, 2000);
        """, ref_input)

        time.sleep(3)

        # Verify upload
        for attempt in range(3):
            if self._verify_reference_uploaded():
                logger.success("[REFERENCE DIRECT] Upload VERIFIED!")
                return
            logger.debug(f"[REFERENCE DIRECT] Verification attempt {attempt + 1}/3...")
            time.sleep(2)

        # Check if file is at least in the input
        has_files = driver.execute_script("""
            var allInputs = document.querySelectorAll('input[type="file"]');
            for (var i = 0; i < allInputs.length; i++) {
                if (allInputs[i].files && allInputs[i].files.length > 0) {
                    return {hasFiles: true, name: allInputs[i].files[0].name, inputId: allInputs[i].id};
                }
            }
            return {hasFiles: false};
        """)

        if has_files and has_files.get('hasFiles'):
            logger.warning(f"[REFERENCE DIRECT] File is in input ({has_files.get('name')}) but UI not updated. Continuing.")
            return

        # ================================================================
        # Strategy A failed — fall through to Strategy B (proxy input)
        # ================================================================
        logger.warning("[REFERENCE DIRECT] Strategy A verification failed, trying Strategy B (proxy input)...")
        self._sync_upload_reference_proxy_input(image_path)

    def _sync_upload_reference_proxy_input(self, image_path: str) -> None:
        """
        Strategy B: create a temporary visible input, send_keys to it,
        then transfer file to original input via DataTransfer + React events.
        """
        driver = self.browser.driver

        from pathlib import Path
        file_path = Path(image_path)
        absolute_path = str(file_path.absolute())

        driver.execute_script("""
            var existing = document.getElementById('image-form-reference-visible');
            if (existing) existing.remove();

            var newInp = document.createElement('input');
            newInp.type = 'file';
            newInp.id = 'image-form-reference-visible';
            newInp.accept = 'image/jpeg,image/jpg,image/png,image/webp';
            newInp.style.cssText = 'position: fixed; top: 100px; left: 100px; z-index: 999999; width: 400px; height: 50px; opacity: 1; display: block;';
            document.body.appendChild(newInp);
        """)

        time.sleep(0.5)

        try:
            new_input = driver.find_element(By.ID, 'image-form-reference-visible')
            new_input.send_keys(absolute_path)
            logger.info(f"[REFERENCE PROXY] File sent to proxy input: {file_path.name}")
        except Exception as e:
            logger.error(f"[REFERENCE PROXY] Failed to send file to proxy input: {e}")
            driver.execute_script("var el = document.getElementById('image-form-reference-visible'); if (el) el.remove();")
            raise

        # Transfer file from proxy to original input + trigger React events
        time.sleep(1)
        driver.execute_script("""
            var proxyInp = document.getElementById('image-form-reference-visible');
            var origInp = document.getElementById('image-form-reference');
            if (!origInp) {
                var allInputs = document.querySelectorAll('input[type="file"]');
                for (var i = 0; i < allInputs.length; i++) {
                    var el = allInputs[i];
                    if (el.id === 'image-form-reference-visible') continue;
                    var attrs = (el.id + ' ' + el.name + ' ' + el.className).toLowerCase();
                    if (attrs.includes('reference') || attrs.includes('ref')) { origInp = el; break; }
                }
            }

            if (proxyInp && proxyInp.files && proxyInp.files.length > 0 && origInp) {
                var dt = new DataTransfer();
                dt.items.add(proxyInp.files[0]);
                origInp.files = dt.files;

                // Dispatch React-compatible events
                ['input', 'change'].forEach(function(evtName) {
                    var evt = new Event(evtName, {bubbles: true, cancelable: true});
                    origInp.dispatchEvent(evt);
                });
                console.log('File transferred to original input via proxy + React events');
            }

            // Cleanup
            if (proxyInp) proxyInp.remove();
        """)

        time.sleep(3)

        for attempt in range(5):
            if self._verify_reference_uploaded():
                logger.success("[REFERENCE PROXY] Upload VERIFIED!")
                return
            logger.debug(f"[REFERENCE PROXY] Verification attempt {attempt + 1}/5...")
            time.sleep(2)

        has_files = driver.execute_script("""
            var inp = document.getElementById('image-form-reference');
            if (inp && inp.files && inp.files.length > 0) {
                return {hasFiles: true, name: inp.files[0].name};
            }
            return {hasFiles: false};
        """)

        if has_files and has_files.get('hasFiles'):
            logger.warning(f"[REFERENCE PROXY] File is in input ({has_files.get('name')}) but UI not updated. Continuing.")
            return

        raise HiggsFieldWebGenerationError("Reference upload proxy method failed - file not in input")

    def _verify_reference_uploaded(self) -> bool:
        """
        Verify reference image is uploaded.

        Checks:
        1. input.files.length > 0 on reference input
        2. Preview image appears in reference area (blob: URL)
        3. Remove/X button appears near reference input
        """
        driver = self.browser.driver

        try:
            result = driver.execute_script("""
                // Check 1: File input has files
                var refInput = document.getElementById('image-form-reference');
                if (refInput && refInput.files && refInput.files.length > 0) {
                    console.log('Reference verified: input has files:', refInput.files[0].name);
                    return true;
                }

                // Check 2: Any file input has files (in case different input was used)
                var allInputs = document.querySelectorAll('input[type="file"]');
                for (var i = 0; i < allInputs.length; i++) {
                    if (allInputs[i].files && allInputs[i].files.length > 0) {
                        console.log('Reference verified: found input with files');
                        return true;
                    }
                }

                // Check 3: Look for blob: image in reference area
                // Reference area is typically near the prompt textarea, in a section with "reference" text
                var formArea = document.querySelector('form') || document.querySelector('main');
                if (formArea) {
                    var blobImages = formArea.querySelectorAll('img[src^="blob:"]');
                    if (blobImages.length > 0) {
                        console.log('Reference verified: found blob image in form');
                        return true;
                    }
                }

                // Check 4: Look for remove button with X icon near reference section
                // The reference section typically has a preview with X button
                var refSections = document.querySelectorAll('[class*="reference"], [aria-label*="reference"]');
                for (var i = 0; i < refSections.length; i++) {
                    var section = refSections[i];
                    var img = section.querySelector('img');
                    var btn = section.querySelector('button');
                    if (img && img.src && img.src.length > 20) {
                        console.log('Reference verified: found image in reference section');
                        return true;
                    }
                    if (btn) {
                        console.log('Reference verified: found button in reference section');
                        return true;
                    }
                }

                return false;
            """)
            return result
        except Exception as e:
            logger.debug(f"Error verifying reference upload: {e}")
            return False

    async def _clear_reference_image(self) -> None:
        """РћС‡РёСЃС‚РёС‚Рё reference image СЃРµРєС†С–СЋ"""
        logger.debug("Clearing reference image section...")
        await asyncio.to_thread(self._sync_clear_reference)

    def _sync_clear_reference(self) -> None:
        """Очистка reference image - ТОЛЬКО в зоне image-form-reference"""
        driver = self.browser.driver
        logger.info("Clearing reference image...")

        try:
            # Одна попытка - найти и кликнуть X только около референс-инпута
            result = driver.execute_script("""
                var refInput = document.getElementById('image-form-reference');
                if (!refInput) return 'no_input';

                // Ищем контейнер с референсом (5 уровней вверх)
                var container = refInput;
                for (var i = 0; i < 5; i++) {
                    container = container.parentElement;
                    if (!container) break;

                    // Ищем картинку в этом контейнере
                    var img = container.querySelector('img');
                    if (img && img.src && img.src.length > 50 && !img.src.includes('placeholder')) {
                        // Нашли превью - ищем X кнопку
                        var btns = container.querySelectorAll('button');
                        for (var j = 0; j < btns.length; j++) {
                            var btn = btns[j];
                            // X кнопка маленькая с SVG
                            if (btn.offsetWidth > 0 && btn.offsetWidth < 50) {
                                var svg = btn.querySelector('svg');
                                if (svg) {
                                    btn.click();
                                    return 'cleared';
                                }
                            }
                        }
                    }
                }
                return 'no_ref';
            """)

            logger.info(f"Reference clear result: {result}")

        except Exception as e:
            logger.warning(f"Failed to clear reference: {e}")

    # ========================================================================
    # GENERATION WAITING
    # ========================================================================

    async def _wait_for_generation(self, timeout: int = 300) -> None:
        """
        РћС‡С–РєСѓРІР°РЅРЅСЏ Р·Р°РІРµСЂС€РµРЅРЅСЏ РіРµРЅРµСЂР°С†С–С— Р·РѕР±СЂР°Р¶РµРЅСЊ.

        Р‘Р•Р— refresh РїС–Рґ С‡Р°СЃ РѕС‡С–РєСѓРІР°РЅРЅСЏ - С‚С–Р»СЊРєРё РїРµСЂРµРІС–СЂРєР° DOM.
        РџРµСЂРµРІС–СЂСЏС" СЃС‚Р°С‚СѓСЃ pending/queue - СЏРєС‰Рѕ РІ С‡РµСЂР·С–, РїСЂРѕРґРѕРІР¶СѓС" С‡РµРєР°С‚Рё.
        РўР°Р№РјР°СѓС‚: 5 С…РІРёР»РёРЅ (РґР»СЏ РїС–РєРѕРІРёС… РіРѕРґРёРЅ Higgsfield).
        """
        logger.info(f"Waiting for generation (timeout: {timeout}s, no refresh during wait)...")

        max_cycles = 30  # 30 * 20 = 600 секунд (10 хвилин)
        wait_per_cycle = 20

        initial_first_url = await asyncio.to_thread(self._get_first_image_url)
        logger.debug(f"Initial first image URL: {initial_first_url[:60] if initial_first_url else 'None'}...")

        for cycle in range(1, max_cycles + 1):
            logger.info(f"Cycle {cycle}/{max_cycles}: waiting {wait_per_cycle}s...")
            await asyncio.sleep(wait_per_cycle)

            # Check if generation is still in progress (pending/queue)
            is_pending = await asyncio.to_thread(self._check_generation_pending)
            if is_pending:
                logger.info(f"Generation still in progress (pending/queue), continuing to wait...")
                continue

            # РџРµСЂРµРІС–СЂСЏС"РјРѕ DOM Р‘Р•Р— refresh
            current_first_url = await asyncio.to_thread(self._get_first_image_url)
            logger.debug(f"Current first image URL: {current_first_url[:60] if current_first_url else 'None'}...")

            if current_first_url and current_first_url != initial_first_url:
                logger.info(f"Generation completed! New image detected on cycle {cycle}")
                return

            if current_first_url and not initial_first_url:
                logger.info(f"Generation completed! First image appeared on cycle {cycle}")
                return

            logger.debug(f"No new image yet (cycle {cycle}/{max_cycles})")

        # РўС–Р»СЊРєРё СЏРєС‰Рѕ РїС–СЃР»СЏ РІСЃС–С… С†РёРєР»С–РІ РЅРµРјР°С" СЂРµР·СѓР»СЊС‚Р°С‚Сѓ - РѕРґРёРЅ refresh
        logger.warning(f"Max cycles ({max_cycles}) reached. Single refresh to check...")
        await self.browser.refresh()
        await asyncio.sleep(5)
        await self.browser.wait_for_page_ready()

    def _get_first_image_url(self) -> Optional[str]:
        """РћС‚СЂРёРјР°С‚Рё URL РїРµСЂС€РѕРіРѕ Р·РѕР±СЂР°Р¶РµРЅРЅСЏ РЅР° СЃС‚РѕСЂС–РЅС†С–"""
        driver = self.browser.driver

        try:
            selectors = [
                'img[data-asset-preview]',
                'img[src*="cloudfront"]',
                'img[src*="higgsfield"]',
                'div[data-testid="image-result"] img',
                '.generated-image img',
            ]

            for selector in selectors:
                images = driver.find_elements(By.CSS_SELECTOR, selector)
                if images:
                    src = images[0].get_attribute("src")
                    if src and ("cloudfront" in src or "higgsfield" in src):
                        return src
            return None
        except Exception:
            return None

    def _check_generation_pending(self) -> bool:
        """
        РџРµСЂРµРІС–СЂРёС‚Рё С‡Рё РіРµРЅРµСЂР°С†С–СЏ РІ СЃС‚Р°С‚СѓСЃС– pending/queue.

        HiggsField-СЃРїРµС†РёС„С–С‡РЅР° РїРµСЂРµРІС–СЂРєР°:
        - Р"РёРІРёРјРѕСЃСЊ РЅР° placeholder Р·РѕР±СЂР°Р¶РµРЅРЅСЏ (С‚С–, С‰Рѕ РіРµРЅРµСЂСѓСЋС‚СЊСЃСЏ)
        - РЁСѓРєР°С"РјРѕ С‚РµРєСЃС‚ "pending", "queue" Р±С–Р»СЏ placeholder
        - РќР• СЂРµР°РіСѓС"РјРѕ РЅР° Р·Р°РіР°Р»СЊРЅС– СЃРїС–РЅРЅРµСЂРё (РјРѕР¶СѓС‚СЊ Р±СѓС‚Рё РІ С–РЅС€РёС… С‡Р°СЃС‚РёРЅР°С… UI)
        """
        driver = self.browser.driver

        try:
            result = driver.execute_script("""
                // HiggsField specific: Check for placeholder images with pending status
                // Look for images that are being generated (have skeleton or loading overlay)

                // Strategy 1: Look for visible "pending" or "queue" text near image placeholders
                var mainContent = document.querySelector('main') || document.body;
                var text = mainContent.innerText.toLowerCase();

                // Check for explicit pending/queue status text (more specific)
                if (text.includes('generating...') || text.includes('in queue') || text.includes('waiting for generation')) {
                    console.log('Found explicit pending text');
                    return true;
                }

                // Strategy 2: Look for skeleton placeholders specifically in the image gallery area
                // HiggsField uses skeleton loaders for images being generated
                var galleryAreas = document.querySelectorAll('[class*="gallery"], [class*="grid"], [class*="result"]');
                for (var i = 0; i < galleryAreas.length; i++) {
                    var skeletons = galleryAreas[i].querySelectorAll('[class*="skeleton"], [class*="animate-pulse"]');
                    // Only count large skeletons (image-sized, not small UI elements)
                    for (var j = 0; j < skeletons.length; j++) {
                        var rect = skeletons[j].getBoundingClientRect();
                        if (rect.width > 150 && rect.height > 200) {
                            console.log('Found large skeleton in gallery area');
                            return true;
                        }
                    }
                }

                // Strategy 3: Check if Generate button is disabled (generation in progress)
                var generateBtns = document.querySelectorAll('button');
                for (var i = 0; i < generateBtns.length; i++) {
                    var btn = generateBtns[i];
                    if (btn.innerText.toLowerCase().includes('generat') && btn.disabled) {
                        console.log('Generate button is disabled - generation in progress');
                        return true;
                    }
                }

                return false;
            """)

            return result

        except Exception as e:
            logger.debug(f"Error checking pending status: {e}")
            return False

    # ========================================================================
    # DOWNLOAD
    # ========================================================================

    async def _download_generated_images(
        self,
        count: int,
        exclude_urls: Optional[List[str]] = None
    ) -> List[GeneratedImage]:
        """
        Р—Р°РІР°РЅС‚Р°Р¶РёС‚Рё Р·РіРµРЅРµСЂРѕРІР°РЅС– Р·РѕР±СЂР°Р¶РµРЅРЅСЏ Р· retry Р»РѕРіС–РєРѕСЋ.

        РџРѕРІРµСЂС‚Р°С" List[GeneratedImage] Р· path РўРђ url РґР»СЏ РїРѕРґР°Р»СЊС€РѕРіРѕ РІРёРєРѕСЂРёСЃС‚Р°РЅРЅСЏ.
        URL Р·Р±РµСЂС–РіР°С"С‚СЊСЃСЏ РґР»СЏ С€РІРёРґРєРѕС— РіРµРЅРµСЂР°С†С–С— РІС–РґРµРѕ (Р±РµР· РїРѕРІС‚РѕСЂРЅРѕРіРѕ upload).
        """
        logger.debug(f"Downloading up to {count} images...")

        downloaded: List[GeneratedImage] = []
        max_retries = 3
        retry_delay = 3
        exclude_set = set(exclude_urls or [])

        for attempt in range(1, max_retries + 1):
            # Scan ALL images on page (high limit) to avoid missing new ones
            all_image_urls = await asyncio.to_thread(
                self._get_generated_image_urls,
                100
            )

            image_urls = [url for url in all_image_urls if url not in exclude_set]

            logger.debug(f"Found {len(all_image_urls)} total, {len(image_urls)} new (excluding {len(exclude_set)} old)")

            if image_urls:
                logger.debug(f"Found {len(image_urls)} NEW image URLs on attempt {attempt}")
                break

            if attempt < max_retries:
                logger.debug(f"No NEW images found (attempt {attempt}/{max_retries}), retrying in {retry_delay}s...")
                await asyncio.sleep(retry_delay)
                # Re-snapshot BEFORE refresh to catch any gallery images that appeared
                pre_refresh_urls = await asyncio.to_thread(self._get_generated_image_urls, 100)
                exclude_set.update(pre_refresh_urls)
                await self.browser.refresh()
                await asyncio.sleep(3)
                await self.browser.wait_for_page_ready()
                # After refresh, snapshot again to exclude gallery images that reloaded
                post_refresh_urls = await asyncio.to_thread(self._get_generated_image_urls, 100)
                exclude_set.update(post_refresh_urls)
                logger.debug(f"Post-refresh exclude set: {len(exclude_set)} URLs")
            else:
                logger.warning("No NEW generated images found in DOM after all retries")
                return downloaded

        urls_to_download = image_urls[:count]
        # NOTE: For sequential generation (count=1), newest image is first - correct order
        # For PRIMARY candidates (count=4), all 4 are generated together - order preserved
        # Reverse is NO LONGER needed since we switched to sequential generation
        logger.info(f"Downloading {len(urls_to_download)} images (requested: {count})")

        for i, url in enumerate(urls_to_download):
            try:
                output_path = self.download_dir / f"generated_{i}_{int(time.time())}.png"
                await self._download_image_from_url(url, output_path)

                # Р—Р±РµСЂС–РіР°С"РјРѕ Р† path Р† url
                downloaded.append(GeneratedImage(
                    path=output_path,
                    url=url,
                    index=i
                ))
                logger.debug(f"Downloaded image {i+1}/{len(urls_to_download)}: {output_path.name}")
                logger.debug(f"  URL saved: {url[:60]}...")
            except Exception as e:
                logger.warning(f"Failed to download image {i}: {e}")

        return downloaded

    def _get_generated_image_urls(self, limit: int) -> List[str]:
        """РћС‚СЂРёРјР°С‚Рё URLs Р·РіРµРЅРµСЂРѕРІР°РЅРёС… Р·РѕР±СЂР°Р¶РµРЅСЊ Р· DOM"""
        driver = self.browser.driver
        seen_urls = set()
        urls = []

        selectors = [
            'img[data-asset-preview]',
            'img[src*="cloudfront"]',
            'img[src*="higgsfield"]',
            'div[data-testid="image-result"] img',
            '.generated-image img',
            'main img[src*="http"]',
        ]

        found_images = []
        found_srcs = set()

        for selector in selectors:
            try:
                images = driver.find_elements(By.CSS_SELECTOR, selector)
                if images:
                    logger.debug(f"Selector '{selector}' found {len(images)} images")
                    for img in images:
                        src = img.get_attribute("src")
                        if src and src not in found_srcs:
                            found_srcs.add(src)
                            found_images.append(img)
            except Exception as e:
                logger.debug(f"Selector '{selector}' failed: {e}")

        if not found_images:
            logger.warning("No images found with any selector")
            return urls

        logger.debug(f"Found {len(found_images)} unique images")

        for img in found_images[:limit * 2]:
            try:
                src = img.get_attribute("src")
                if not src:
                    continue

                final_url = None
                if "cloudfront" in src or "higgsfield" in src or "blob:" in src:
                    if "/cdn-cgi/image/" in src:
                        parts = src.split("https://")
                        if len(parts) > 2:
                            final_url = "https://" + parts[-1]
                        else:
                            final_url = src
                    else:
                        final_url = src
                elif src.startswith("http") and ("png" in src.lower() or "jpg" in src.lower() or "jpeg" in src.lower() or "webp" in src.lower()):
                    final_url = src

                if final_url and final_url not in seen_urls:
                    seen_urls.add(final_url)
                    urls.append(final_url)

                    if len(urls) >= limit:
                        break

            except Exception as e:
                logger.debug(f"Failed to process image: {e}")

        logger.debug(f"Extracted {len(urls)} unique image URLs (from {len(found_images)} found)")
        return urls

    async def _download_image_from_url(self, url: str, output_path: Path) -> None:
        """Р—Р°РІР°РЅС‚Р°Р¶РёС‚Рё Р·РѕР±СЂР°Р¶РµРЅРЅСЏ Р· URL"""
        try:
            if self._http_client:
                response = await self._http_client.get(url, timeout=60)
            else:
                async with httpx.AsyncClient() as client:
                    response = await client.get(url, timeout=60)

            response.raise_for_status()
            output_path.write_bytes(response.content)
            logger.debug(f"Image saved to: {output_path}")

        except Exception as e:
            raise HiggsFieldWebDownloadError(
                f"Failed to download image from {url[:50]}...",
                cause=e
            )

    # ========================================================================
    # MAIN GENERATION WORKFLOWS
    # ========================================================================

    async def generate_primary_candidates(
        self,
        prompt: str,
        num_candidates: int = 4
    ) -> List[GeneratedImage]:
        """
        WORKFLOW 1: Р"РµРЅРµСЂР°С†С–СЏ 4 candidates РґР»СЏ PRIMARY СЃС†РµРЅРё.
        Unlimited=OFF (РІРёРєРѕСЂРёСЃС‚РѕРІСѓС" РєСЂРµРґРёС‚Рё РґР»СЏ РєСЂР°С‰РѕС— СЏРєРѕСЃС‚С–).

        Returns:
            List[GeneratedImage]: РЎРїРёСЃРѕРє Р· path С‚Р° url РґР»СЏ РєРѕР¶РЅРѕРіРѕ РєР°РЅРґРёРґР°С‚Р°.
        """
        logger.info("=" * 60)
        logger.info("GENERATING PRIMARY CANDIDATES (WORKFLOW 1)")
        logger.info("=" * 60)
        logger.info(f"  Candidates: {num_candidates}")
        logger.info(f"  Aspect Ratio: {self.settings.aspect_ratio}")
        logger.info(f"  Resolution: {self.settings.resolution}")
        logger.info(f"  Unlimited: OFF (using credits for better quality)")
        logger.info(f"  Prompt: {prompt[:80]}...")
        logger.info("=" * 60)

        # force=True to prevent stale gallery images from previous sessions
        await self._navigate_to_image(force=True)

        # Step 1: Р’РёРґР°Р»РёС‚Рё СЂРµС„РµСЂРµРЅСЃ (СЏРєС‰Рѕ С")
        logger.info("Step 1: Clearing reference image (if exists)...")
        await self._clear_reference_image()

        # Step 2: Р’РёРґР°Р»РёС‚Рё СЃС‚Р°СЂРёР№ РїСЂРѕРјРїС‚
        logger.info("Step 2: Clearing old prompt...")
        await asyncio.to_thread(self._sync_clear_prompt)

        # Step 3: Р’СЃС‚Р°РІРёС‚Рё РїСЂРѕРјРїС‚
        logger.info("Step 3: Entering prompt...")
        await asyncio.to_thread(self._sync_enter_prompt, prompt)

        # Step 4: Р’РёР±СЂР°С‚Рё ratio
        logger.info("Step 4: Setting aspect ratio to 9:16...")
        await self._set_aspect_ratio(self.settings.aspect_ratio)

        # Step 5: Р’РёР±СЂР°С‚Рё СЂРµР·РѕР»СЋС†С–СЋ 2K
        logger.info("Step 5: Setting resolution to 2K...")
        await self._set_resolution(self.settings.resolution)

        # Step 6: Р’РёР±СЂР°С‚Рё РєС–Р»СЊРєС–СЃС‚СЊ Р·РѕР±СЂР°Р¶РµРЅСЊ (4)
        logger.info("Step 6: Setting image count to 4...")
        await self._set_image_count(num_candidates)

        # Р—Р°РїР°Рј'СЏС‚Р°С‚Рё СЃС‚Р°СЂС– Р·РѕР±СЂР°Р¶РµРЅРЅСЏ
        initial_image_urls = await asyncio.to_thread(self._get_generated_image_urls, 100)
        logger.info(f"Found {len(initial_image_urls)} existing images (will exclude from download)")

        # РќР°С‚РёСЃРЅСѓС‚Рё Generate
        logger.info("Step 7: Clicking Generate button...")
        await asyncio.to_thread(self._sync_click_generate)

        # Почекати генерацію ВСІХ 4 кандидатів
        logger.info(f"Step 8: Waiting for {num_candidates} images...")
        await self._wait_for_batch_generation(
            expected_count=num_candidates,
            initial_urls=initial_image_urls
        )

        # Р—Р°РІР°РЅС‚Р°Р¶РёС‚Рё СЂРµР·СѓР»СЊС‚Р°С‚Рё
        logger.info("Step 9: Downloading NEW images only...")
        images = await self._download_generated_images(num_candidates, exclude_urls=initial_image_urls)

        logger.info("=" * 60)
        logger.info(f"PRIMARY CANDIDATES COMPLETE: {len(images)} images downloaded")
        logger.info("=" * 60)
        return images

    async def generate_scene_image(
        self,
        prompt: str,
        reference_image: Optional[Path] = None,
        reference_type: str = "REQUIRES_REF"
    ) -> GeneratedImage:
        """
        WORKFLOW 2 (Р±РµР· СЂРµС„РµСЂРµРЅСЃСѓ - INDEPENDENT): clear reference if exists
        WORKFLOW 3 (Р· СЂРµС„РµСЂРµРЅСЃРѕРј - REQUIRES_REF/LOOP_CLOSE): upload reference if not exists

        Args:
            prompt: Image generation prompt
            reference_image: Path to reference image (for REQUIRES_REF/LOOP_CLOSE)
            reference_type: INDEPENDENT, REQUIRES_REF, or LOOP_CLOSE

        Returns:
            GeneratedImage: РћР±'С"РєС‚ Р· path С‚Р° url.
        """
        logger.info("=" * 50)
        logger.info(f"GENERATING SCENE IMAGE")
        logger.info(f"  Reference type: {reference_type}")
        logger.info(f"  Reference image: {'Yes' if reference_image else 'No'}")
        logger.info(f"  Unlimited: ON (free generation)")
        logger.info("=" * 50)

        # force=True to prevent stale gallery images from previous sessions
        await self._navigate_to_image(force=True)

        # Загрузить референс если нужен и его нет на странице
        if reference_image and reference_type != 'INDEPENDENT':
            has_ref = await asyncio.to_thread(self._check_reference_exists)
            if not has_ref:
                logger.info("Uploading reference image...")
                await self._upload_reference_image(reference_image, skip_if_exists=False)

        # Ввод промпта
        logger.info("Entering prompt...")
        await asyncio.to_thread(self._sync_enter_prompt, prompt)

        logger.info("Step 3: Setting Unlimited ON...")
        await self._set_unlimited(True)

        logger.info("Step 4: Setting resolution to 2K...")
        await self._set_resolution(self.settings.resolution)

        logger.info("Step 5: Setting image count to 1...")
        await self._set_image_count(1)

        # Р—Р°РїР°Рј'СЏС‚Р°С‚Рё СЃС‚Р°СЂС– Р·РѕР±СЂР°Р¶РµРЅРЅСЏ
        initial_image_urls = await asyncio.to_thread(self._get_generated_image_urls, 100)
        logger.debug(f"Initial images on page (to exclude): {len(initial_image_urls)}")

        # РќР°С‚РёСЃРЅСѓС‚Рё Generate
        await asyncio.to_thread(self._sync_click_generate)

        # РџРѕС‡РµРєР°С‚Рё РіРµРЅРµСЂР°С†С–СЋ
        await self._wait_for_generation()

        # Р—Р°РІР°РЅС‚Р°Р¶РёС‚Рё СЂРµР·СѓР»СЊС‚Р°С‚
        images = await self._download_generated_images(1, exclude_urls=initial_image_urls)

        if not images:
            raise HiggsFieldWebGenerationError("No images generated")

        result = images[0]
        logger.info(f"Scene image generated: {result.path}")
        logger.info(f"  URL saved: {result.url[:60]}...")
        return result

    async def queue_single_image(
        self,
        prompt: str,
        scene_num: int,
        reference_image: Optional[Path] = None
    ) -> None:
        """РџРѕСЃС‚Р°РІРёС‚Рё РѕРґРЅРµ Р·РѕР±СЂР°Р¶РµРЅРЅСЏ РІ С‡РµСЂРіСѓ РіРµРЅРµСЂР°С†С–С— (РЅРµ С‡РµРєР°С" Р·Р°РІРµСЂС€РµРЅРЅСЏ)"""
        await self._navigate_to_image()
        logger.info(f"[Scene {scene_num}] Queueing image generation...")
        logger.info(f"  Reference: {'Yes' if reference_image else 'No'}")
        logger.info(f"  Prompt: {prompt[:50]}...")

        if reference_image:
            logger.info(f"[Scene {scene_num}] Step 1: Uploading reference (skip if exists)...")
            await self._upload_reference_image(reference_image, skip_if_exists=False)

        logger.info(f"[Scene {scene_num}] Step 2: Clearing old prompt...")
        await asyncio.to_thread(self._sync_clear_prompt)

        logger.info(f"[Scene {scene_num}] Step 3: Entering prompt...")
        await asyncio.to_thread(self._sync_enter_prompt, prompt)

        logger.info(f"[Scene {scene_num}] Step 4: Clicking Generate...")
        await asyncio.to_thread(self._sync_click_generate)

        logger.info(f"[Scene {scene_num}] Step 5: Waiting 15 seconds...")
        await asyncio.sleep(15)

        logger.info(f"[Scene {scene_num}] Image queued successfully!")

    # ========================================================================
    # BATCH GENERATION (SEQUENTIAL - ensures correct order)
    # ========================================================================

    async def generate_batch_images(
        self,
        scenes: List[dict],
        reference_image: Optional[Path] = None,
        reference_url: Optional[str] = None
    ) -> List[GeneratedImage]:
        """
        SEQUENTIAL image generation for multiple scenes.

        IMPORTANT: Generate and download each image IMMEDIATELY to ensure
        correct scene-to-image mapping. Parallel queueing causes order issues
        because HiggsField may complete generations in unpredictable order.

        Workflow:
        1. Navigate to image page ONCE
        2. Set Unlimited ON, 2K, count=1 ONCE
        3. Upload reference ONCE (if needed)
        4. For EACH scene:
           - Clear prompt -> enter prompt -> Generate
           - Wait for THIS image to complete
           - Download THIS image immediately
        5. Return all images in correct order

        Args:
            scenes: List of dicts with:
                - scene_number: int
                - image_prompt: str
                - reference_type: str (INDEPENDENT, REQUIRES_REF, LOOP_CLOSE)
            reference_image: Optional shared reference for scenes that need it
            reference_url: URL for finding reference in gallery

        Returns:
            List[GeneratedImage]: Images in CORRECT order matching scenes.
        """
        if not scenes:
            return []

        logger.info("=" * 70)
        logger.info(f"SEQUENTIAL IMAGE GENERATION: {len(scenes)} scenes")
        logger.info(f"[REF_DEBUG] reference_image param = {reference_image}")
        if reference_image:
            logger.info(f"[REF_DEBUG] reference_image.exists() = {reference_image.exists()}")
        logger.info("=" * 70)

        # Step 1: Navigate ONCE
        logger.info("[SETUP] Step 1: Navigating to image page...")
        await self._navigate_to_image(force=True)

        # Step 2: Set settings FIRST (before reference upload!)
        logger.info("[SETUP] Step 2: Setting Unlimited ON...")
        await self._set_unlimited(True)

        logger.info("[SETUP] Step 3: Setting resolution to 2K...")
        await self._set_resolution(self.settings.resolution)

        logger.info("[SETUP] Step 4: Setting image count to 1...")
        await self._set_image_count(1)

        # Step 5: Upload reference if needed
        if reference_image and reference_image.exists():
            ref_exists = await asyncio.to_thread(self._check_reference_exists)
            if ref_exists:
                logger.success("[SETUP] ✅ Reference already uploaded, skipping")
            else:
                logger.info(f"[SETUP] Step 5: Uploading reference: {reference_image}")
                await self._upload_reference_image(reference_image, skip_if_exists=False, reference_url=reference_url)
                logger.success("[SETUP] ✅ Reference uploaded")
        elif reference_image:
            logger.error(f"[SETUP] Reference file NOT FOUND: {reference_image}")
            raise HiggsFieldWebGenerationError(f"Reference image not found: {reference_image}")
        else:
            logger.warning("[SETUP] No reference image path provided!")

        # Step 6: Generate each scene SEQUENTIALLY
        logger.info("=" * 70)
        logger.info("GENERATING SCENES SEQUENTIALLY (correct order guaranteed)...")
        logger.info("=" * 70)

        generated_images: List[GeneratedImage] = []

        for i, scene in enumerate(scenes):
            scene_num = scene.get('scene_number', i + 1)
            prompt = scene.get('image_prompt', '')

            logger.info(f"[Scene {scene_num}] ({i+1}/{len(scenes)}) Generating...")
            logger.info(f"[Scene {scene_num}]   Prompt: {prompt[:60]}...")

            # Remember URLs before this generation
            urls_before = await asyncio.to_thread(self._get_generated_image_urls, 100)

            # Clear old prompt, enter new one
            await asyncio.to_thread(self._sync_clear_prompt)
            await asyncio.to_thread(self._sync_enter_prompt, prompt)

            # Click Generate
            await asyncio.to_thread(self._sync_click_generate)

            # Wait for THIS image to complete
            logger.info(f"[Scene {scene_num}] Waiting for generation to complete...")
            await self._wait_for_generation(timeout=300)

            # Download the NEW image immediately
            new_images = await self._download_generated_images(
                count=1,
                exclude_urls=urls_before
            )

            if new_images:
                img = new_images[0]
                generated_images.append(img)
                logger.success(f"[Scene {scene_num}] ✅ Image downloaded: {img.path.name}")
            else:
                logger.error(f"[Scene {scene_num}] ❌ No new image found!")
                # Append None placeholder to maintain order
                generated_images.append(None)

        logger.info("=" * 70)
        success_count = sum(1 for img in generated_images if img is not None)
        logger.info(f"SEQUENTIAL GENERATION COMPLETE: {success_count}/{len(scenes)} images")
        logger.info("=" * 70)

        # Filter out None values but log warning
        valid_images = [img for img in generated_images if img is not None]
        if len(valid_images) < len(scenes):
            logger.warning(f"Missing {len(scenes) - len(valid_images)} images!")

        return generated_images  # Return with Nones to preserve index mapping

    async def _wait_for_batch_generation(
        self,
        expected_count: int,
        initial_urls: List[str],
        timeout: int = 300
    ) -> None:
        """
        РћС‡С–РєСѓРІР°РЅРЅСЏ Р·Р°РІРµСЂС€РµРЅРЅСЏ batch РіРµРЅРµСЂР°С†С–С—.

        РџРµСЂРµРІС–СЂСЏС" DOM РєРѕР¶РЅС– 20 СЃРµРєСѓРЅРґ (Р‘Р•Р— refresh).
        РџРµСЂРµРІС–СЂСЏС" СЃС‚Р°С‚СѓСЃ pending/queue - СЏРєС‰Рѕ РІ С‡РµСЂР·С–, РїСЂРѕРґРѕРІР¶СѓС" С‡РµРєР°С‚Рё.
        РўР°Р№РјР°СѓС‚: 5 С…РІРёР»РёРЅ (РґР»СЏ РїС–РєРѕРІРёС… РіРѕРґРёРЅ Higgsfield).
        Refresh С‚С–Р»СЊРєРё РІ РєС–РЅС†С– СЏРєС‰Рѕ РЅРµ РІСЃС– Р·РѕР±СЂР°Р¶РµРЅРЅСЏ Р·'СЏРІРёР»РёСЃСЊ.
        """
        logger.info(f"Waiting for {expected_count} new images (timeout: {timeout}s)...")

        max_cycles = timeout // 20  # 15 cycles for 5 minutes

        for cycle in range(1, max_cycles + 1):
            logger.info(f"Check {cycle}/{max_cycles}: waiting 20s...")
            await asyncio.sleep(20)

            # Check if generation is still in progress (pending/queue)
            is_pending = await asyncio.to_thread(self._check_generation_pending)
            if is_pending:
                logger.info(f"Generation still in progress (pending/queue), continuing to wait...")
                # Don't count this cycle against timeout if still pending
                continue

            # Check DOM for new images (NO refresh)
            current_urls = await asyncio.to_thread(self._get_generated_image_urls, 100)
            new_count = len([url for url in current_urls if url not in initial_urls])

            logger.info(f"  Found {new_count}/{expected_count} new images")

            if new_count >= expected_count:
                logger.success(f"All {expected_count} images generated!")
                return

        # Final refresh if not all images found
        logger.warning(f"Timeout reached. Refreshing to check for remaining images...")
        await self.browser.refresh()
        await asyncio.sleep(5)
        await self.browser.wait_for_page_ready()

