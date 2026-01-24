"""
Higgsfield Image Generator - Р“РµРЅРµСЂР°С†С–СЏ Р·РѕР±СЂР°Р¶РµРЅСЊ С‡РµСЂРµР· Р±СЂР°СѓР·РµСЂ.

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
    Р“РµРЅРµСЂР°С‚РѕСЂ Р·РѕР±СЂР°Р¶РµРЅСЊ С‡РµСЂРµР· Higgsfield Web UI.

    РџРѕС‚СЂРµР±СѓС” AdsPowerClient РґР»СЏ СѓРїСЂР°РІР»С–РЅРЅСЏ Р±СЂР°СѓР·РµСЂРѕРј.

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

        # Ensure download dir exists
        self.download_dir.mkdir(parents=True, exist_ok=True)

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
        1. Р—РЅР°Р№С‚Рё РєРЅРѕРїРєСѓ dropdown (РїРѕРєР°Р·СѓС” 1K Р°Р±Рѕ 2K)
        2. РљР»С–РєРЅСѓС‚Рё С‰РѕР± РІС–РґРєСЂРёС‚Рё
        3. РџРѕС‡РµРєР°С‚Рё РїРѕРєРё dropdown РІС–РґРєСЂРёС”С‚СЊСЃСЏ
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
        """Sync РІСЃС‚Р°РЅРѕРІР»РµРЅРЅСЏ РєС–Р»СЊРєРѕСЃС‚С– Р·РѕР±СЂР°Р¶РµРЅСЊ С‡РµСЂРµР· РєРЅРѕРїРєРё +/-"""
        driver = self.browser.driver

        if count < 1:
            count = 1
        if count > 4:
            count = 4

        logger.info(f"Setting image count to {count}...")

        def find_plus_minus_buttons():
            return driver.execute_script(JS_SCRIPTS.find_plus_minus_buttons())

        try:
            # РљСЂРѕРє 1: РЎРєРёРЅСѓС‚Рё РґРѕ РјС–РЅС–РјСѓРјСѓ
            logger.debug("Resetting to minimum...")
            for i in range(4):
                buttons = find_plus_minus_buttons()
                minus_btn = buttons.get('minus') if buttons else None

                if not minus_btn:
                    logger.debug(f"Minus button gone after {i} clicks - reached minimum (1)")
                    break

                try:
                    driver.execute_script("arguments[0].click();", minus_btn)
                    time.sleep(0.2)
                    logger.debug(f"Clicked - ({i+1})")
                except Exception:
                    break

            time.sleep(0.3)

            # РљСЂРѕРє 2: Р—Р±С–Р»СЊС€РёС‚Рё РґРѕ РїРѕС‚СЂС–Р±РЅРѕС— РєС–Р»СЊРєРѕСЃС‚С–
            clicks_needed = count - 1
            if clicks_needed > 0:
                logger.debug(f"Increasing to {count} (need {clicks_needed} clicks)...")

                for i in range(clicks_needed):
                    buttons = find_plus_minus_buttons()
                    plus_btn = buttons.get('plus') if buttons else None

                    if not plus_btn:
                        logger.debug(f"Plus button gone after {i} clicks - reached maximum (4)")
                        break

                    try:
                        driver.execute_script("arguments[0].click();", plus_btn)
                        time.sleep(0.2)
                        logger.debug(f"Clicked + ({i+1}/{clicks_needed})")
                    except Exception as e:
                        logger.warning(f"Failed to click +: {e}")
                        break

            logger.info(f"Image count set to {count}")

        except Exception as e:
            logger.warning(f"Failed to set image count: {e}")

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
        """Sync РєР»С–Рє РЅР° Generate РєРЅРѕРїРєСѓ"""
        driver = self.browser.driver

        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.5)

            # Find bg-primary buttons
            buttons = driver.find_elements(By.CSS_SELECTOR, IMAGE_SELECTORS.GENERATE_BUTTON)
            logger.info(f"Found {len(buttons)} button(s) with selector: {IMAGE_SELECTORS.GENERATE_BUTTON}")

            if not buttons:
                raise HiggsFieldWebElementNotFoundError("Generate button not found")

            btn = buttons[0]
            btn_disabled = btn.get_attribute("disabled")
            logger.info(f"Generate button: disabled={btn_disabled}, visible={btn.is_displayed()}")

            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
            time.sleep(0.3)
            driver.execute_script("arguments[0].click();", btn)
            logger.info("Generate button clicked successfully!")

        except NoSuchElementException:
            raise HiggsFieldWebElementNotFoundError("Generate button not found")

    # ========================================================================
    # REFERENCE IMAGE HANDLING
    # ========================================================================

    async def _upload_reference_image(self, image_path: Path, skip_if_exists: bool = False) -> None:
        """Р—Р°РІР°РЅС‚Р°Р¶РёС‚Рё reference image РґР»СЏ style consistency"""
        logger.debug(f"Uploading reference image: {image_path}")

        if not image_path.exists():
            raise HiggsFieldWebGenerationError(f"Reference image not found: {image_path}")

        if skip_if_exists:
            has_reference = await asyncio.to_thread(self._check_reference_exists)
            if has_reference:
                logger.info("Reference already uploaded, skipping...")
                return

        await asyncio.to_thread(self._sync_upload_reference, str(image_path.absolute()))

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

    def _sync_upload_reference(self, image_path: str) -> None:
        """Sync upload reference через hidden file input"""
        driver = self.browser.driver

        # CRITICAL: Log and verify the file path
        logger.info(f"[REFERENCE] Uploading file: {image_path}")

        # Check if file exists
        from pathlib import Path
        file_path = Path(image_path)
        if not file_path.exists():
            logger.error(f"[REFERENCE] FILE NOT FOUND: {image_path}")
            raise HiggsFieldWebGenerationError(f"Reference file not found: {image_path}")

        # Log file size
        file_size_mb = file_path.stat().st_size / (1024 * 1024)
        logger.info(f"[REFERENCE] File exists, size: {file_size_mb:.2f} MB")

        try:
            file_input = driver.find_element(By.ID, "image-form-reference")
            file_input.send_keys(image_path)
            logger.info(f"[REFERENCE] File path sent to input, waiting for upload...")

            # Poll for upload completion instead of fixed wait
            max_wait = 60  # 60 seconds max
            poll_interval = 2
            for waited in range(0, max_wait, poll_interval):
                time.sleep(poll_interval)
                if self._verify_reference_uploaded():
                    logger.success(f"[REFERENCE] Upload completed in {waited + poll_interval}s")
                    return
                logger.debug(f"[REFERENCE] Still uploading... ({waited + poll_interval}s)")

            logger.warning(f"[REFERENCE] Upload not verified after {max_wait}s")
            raise HiggsFieldWebGenerationError(f"Reference image upload timed out after {max_wait}s")

        except NoSuchElementException:
            logger.error("[REFERENCE] File input not found (id=image-form-reference)")
            raise HiggsFieldWebGenerationError("Reference image input not found on page")
        except HiggsFieldWebGenerationError:
            raise
        except Exception as e:
            logger.error(f"[REFERENCE] Upload failed: {e}")
            raise HiggsFieldWebGenerationError(f"Reference upload failed: {e}")

    def _verify_reference_uploaded(self) -> bool:
        """РџРµСЂРµРІС–СЂРёС‚Рё С‡Рё reference Р·Р°РІР°РЅС‚Р°Р¶РµРЅРѕ СѓСЃРїС–С€РЅРѕ"""
        driver = self.browser.driver

        try:
            result = driver.execute_script("""
                var buttons = document.querySelectorAll('button.button--fixed, button[class*="remove"], button[class*="clear"], button[class*="delete"]');

                for (var i = 0; i < buttons.length; i++) {
                    var btn = buttons[i];
                    var svg = btn.querySelector('svg path');
                    if (svg) {
                        var d = svg.getAttribute('d') || '';
                        if (!d.includes('V4.16602') && d.length > 10) {
                            return true;
                        }
                    }
                    var label = btn.getAttribute('aria-label') || '';
                    if (label.toLowerCase().includes('remove') || label.toLowerCase().includes('clear') || label.toLowerCase().includes('delete')) {
                        return true;
                    }
                }

                var refImages = document.querySelectorAll('img[data-asset-preview], .reference-preview img, [class*="reference"] img');
                for (var i = 0; i < refImages.length; i++) {
                    if (refImages[i].src && refImages[i].src.length > 50 && !refImages[i].src.includes('placeholder')) {
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
        РџРµСЂРµРІС–СЂСЏС” СЃС‚Р°С‚СѓСЃ pending/queue - СЏРєС‰Рѕ РІ С‡РµСЂР·С–, РїСЂРѕРґРѕРІР¶СѓС” С‡РµРєР°С‚Рё.
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

            # РџРµСЂРµРІС–СЂСЏС”РјРѕ DOM Р‘Р•Р— refresh
            current_first_url = await asyncio.to_thread(self._get_first_image_url)
            logger.debug(f"Current first image URL: {current_first_url[:60] if current_first_url else 'None'}...")

            if current_first_url and current_first_url != initial_first_url:
                logger.info(f"Generation completed! New image detected on cycle {cycle}")
                return

            if current_first_url and not initial_first_url:
                logger.info(f"Generation completed! First image appeared on cycle {cycle}")
                return

            logger.debug(f"No new image yet (cycle {cycle}/{max_cycles})")

        # РўС–Р»СЊРєРё СЏРєС‰Рѕ РїС–СЃР»СЏ РІСЃС–С… С†РёРєР»С–РІ РЅРµРјР°С” СЂРµР·СѓР»СЊС‚Р°С‚Сѓ - РѕРґРёРЅ refresh
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
        - Р”РёРІРёРјРѕСЃСЊ РЅР° placeholder Р·РѕР±СЂР°Р¶РµРЅРЅСЏ (С‚С–, С‰Рѕ РіРµРЅРµСЂСѓСЋС‚СЊСЃСЏ)
        - РЁСѓРєР°С”РјРѕ С‚РµРєСЃС‚ "pending", "queue" Р±С–Р»СЏ placeholder
        - РќР• СЂРµР°РіСѓС”РјРѕ РЅР° Р·Р°РіР°Р»СЊРЅС– СЃРїС–РЅРЅРµСЂРё (РјРѕР¶СѓС‚СЊ Р±СѓС‚Рё РІ С–РЅС€РёС… С‡Р°СЃС‚РёРЅР°С… UI)
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

        РџРѕРІРµСЂС‚Р°С” List[GeneratedImage] Р· path РўРђ url РґР»СЏ РїРѕРґР°Р»СЊС€РѕРіРѕ РІРёРєРѕСЂРёСЃС‚Р°РЅРЅСЏ.
        URL Р·Р±РµСЂС–РіР°С”С‚СЊСЃСЏ РґР»СЏ С€РІРёРґРєРѕС— РіРµРЅРµСЂР°С†С–С— РІС–РґРµРѕ (Р±РµР· РїРѕРІС‚РѕСЂРЅРѕРіРѕ upload).
        """
        logger.debug(f"Downloading up to {count} images...")

        downloaded: List[GeneratedImage] = []
        max_retries = 3
        retry_delay = 3
        exclude_urls = exclude_urls or []

        for attempt in range(1, max_retries + 1):
            all_image_urls = await asyncio.to_thread(
                self._get_generated_image_urls,
                count + len(exclude_urls)
            )

            image_urls = [url for url in all_image_urls if url not in exclude_urls]

            logger.debug(f"Found {len(all_image_urls)} total, {len(image_urls)} new (excluding {len(exclude_urls)} old)")

            if image_urls:
                logger.debug(f"Found {len(image_urls)} NEW image URLs on attempt {attempt}")
                break

            if attempt < max_retries:
                logger.debug(f"No NEW images found (attempt {attempt}/{max_retries}), retrying in {retry_delay}s...")
                await asyncio.sleep(retry_delay)
                await self.browser.refresh()
                await asyncio.sleep(3)
                await self.browser.wait_for_page_ready()
            else:
                logger.warning("No NEW generated images found in DOM after all retries")
                return downloaded

        urls_to_download = image_urls[:count]
        # CRITICAL: Reverse order! Higgsfield shows newest first in History,
        # but we queue scenes in order 2,3,4,5,6 so we need to reverse
        # to match the original scene order
        urls_to_download = list(reversed(urls_to_download))
        logger.info(f"Downloading {len(urls_to_download)} images (requested: {count}, reversed for correct order)")

        for i, url in enumerate(urls_to_download):
            try:
                output_path = self.download_dir / f"generated_{i}_{int(time.time())}.png"
                await self._download_image_from_url(url, output_path)

                # Р—Р±РµСЂС–РіР°С”РјРѕ Р† path Р† url
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
        WORKFLOW 1: Р“РµРЅРµСЂР°С†С–СЏ 4 candidates РґР»СЏ PRIMARY СЃС†РµРЅРё.
        Unlimited=OFF (РІРёРєРѕСЂРёСЃС‚РѕРІСѓС” РєСЂРµРґРёС‚Рё РґР»СЏ РєСЂР°С‰РѕС— СЏРєРѕСЃС‚С–).

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

        await self._navigate_to_image()

        # Step 1: Р’РёРґР°Р»РёС‚Рё СЂРµС„РµСЂРµРЅСЃ (СЏРєС‰Рѕ С”)
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
            GeneratedImage: РћР±'С”РєС‚ Р· path С‚Р° url.
        """
        logger.info("=" * 50)
        logger.info(f"GENERATING SCENE IMAGE")
        logger.info(f"  Reference type: {reference_type}")
        logger.info(f"  Reference image: {'Yes' if reference_image else 'No'}")
        logger.info(f"  Unlimited: ON (free generation)")
        logger.info("=" * 50)

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
        """РџРѕСЃС‚Р°РІРёС‚Рё РѕРґРЅРµ Р·РѕР±СЂР°Р¶РµРЅРЅСЏ РІ С‡РµСЂРіСѓ РіРµРЅРµСЂР°С†С–С— (РЅРµ С‡РµРєР°С” Р·Р°РІРµСЂС€РµРЅРЅСЏ)"""
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
    # BATCH GENERATION (PARALLEL)
    # ========================================================================

    async def generate_batch_images(
        self,
        scenes: List[dict],
        reference_image: Optional[Path] = None
    ) -> List[GeneratedImage]:
        """
        РџР°СЂР°Р»РµР»СЊРЅР° РіРµРЅРµСЂР°С†С–СЏ Р·РѕР±СЂР°Р¶РµРЅСЊ РґР»СЏ РєС–Р»СЊРєРѕС… СЃС†РµРЅ.

        Workflow:
        1. Navigate to image page ONCE
        2. Set Unlimited ON, 2K, count=1 ONCE
        3. For each scene:
           - If INDEPENDENT: clear reference
           - If REQUIRES_REF/LOOP_CLOSE: upload reference (if not exists)
           - Clear prompt в†’ enter prompt в†’ Generate в†’ wait 15s
        4. After all queued: wait for all images to appear
        5. Download all NEW images

        Args:
            scenes: List of dicts with:
                - scene_number: int
                - image_prompt: str
                - reference_type: str (INDEPENDENT, REQUIRES_REF, LOOP_CLOSE)
            reference_image: Optional shared reference for scenes that need it

        Returns:
            List[GeneratedImage]: РћР±'С”РєС‚Рё Р· path С‚Р° url.
        """
        if not scenes:
            return []

        logger.info("=" * 70)
        logger.info(f"BATCH IMAGE GENERATION: {len(scenes)} scenes")
        logger.info(f"Reference available: {'Yes' if reference_image else 'No'}")
        logger.info("=" * 70)

        # Step 1: Navigate ONCE
        logger.info("[SETUP] Step 1: Navigating to image page...")
        await self._navigate_to_image(force=True)

        # Step 1.5: CLEAR old reference to ensure clean state
        logger.info("[SETUP] Step 1.5: Clearing old reference...")
        await self._clear_reference_image()

        # Step 1.6: UPLOAD reference image (один раз для всех сцен)
        if reference_image:
            logger.info(f"[SETUP] Step 1.6: Reference path: {reference_image}")
            if reference_image.exists():
                logger.info(f"[SETUP] Reference file EXISTS, uploading...")
                await self._upload_reference_image(reference_image, skip_if_exists=False)
            else:
                logger.error(f"[SETUP] Reference file NOT FOUND: {reference_image}")
                raise HiggsFieldWebGenerationError(f"Reference image not found: {reference_image}")
        else:
            logger.warning("[SETUP] No reference image path provided!")

        # Step 2: Set settings ONCE
        logger.info("[SETUP] Step 2: Setting Unlimited ON...")
        await self._set_unlimited(True)

        logger.info("[SETUP] Step 3: Setting resolution to 2K...")
        await self._set_resolution(self.settings.resolution)

        logger.info("[SETUP] Step 4: Setting image count to 1...")
        await self._set_image_count(1)

        # Remember initial images to exclude from download
        initial_image_urls = await asyncio.to_thread(self._get_generated_image_urls, 100)
        logger.info(f"[SETUP] Found {len(initial_image_urls)} existing images (will exclude)")

        # Track if reference is currently uploaded
        reference_uploaded = await asyncio.to_thread(self._check_reference_exists)
        logger.info(f"[SETUP] Reference currently on page: {reference_uploaded}")

        # Step 4: Queue all scenes
        logger.info("=" * 70)
        logger.info("QUEUEING ALL SCENES...")
        logger.info("=" * 70)

        for i, scene in enumerate(scenes):
            scene_num = scene.get('scene_number', i + 1)
            prompt = scene.get('image_prompt', '')
            ref_type = scene.get('reference_type', 'REQUIRES_REF')  # Default to requiring ref

            logger.info(f"[Scene {scene_num}] ({i+1}/{len(scenes)}) Queueing...")
            logger.info(f"[Scene {scene_num}]   Type: {ref_type}")
            logger.info(f"[Scene {scene_num}]   Prompt: {prompt[:50]}...")

            # Handle reference based on type
            if ref_type == 'INDEPENDENT':
                # Clear reference for independent scenes
                logger.info(f"[Scene {scene_num}] Clearing reference (INDEPENDENT)...")
                await self._clear_reference_image()
                reference_uploaded = False
            elif not reference_uploaded and ref_type in ('REQUIRES_REF', 'LOOP_CLOSE'):
                # Re-upload reference if needed
                if reference_image and reference_image.exists():
                    logger.info(f"[Scene {scene_num}] Re-uploading reference...")
                    await self._upload_reference_image(reference_image, skip_if_exists=False)
                    reference_uploaded = True

            # Enter prompt
            await asyncio.to_thread(self._sync_enter_prompt, prompt)

            # Click Generate
            await asyncio.to_thread(self._sync_click_generate)

            logger.info(f"[Scene {scene_num}] Queued! Waiting 15s before next...")
            await asyncio.sleep(15)

        logger.info("=" * 70)
        logger.info(f"ALL {len(scenes)} SCENES QUEUED!")
        logger.info("=" * 70)

        # Step 5: Wait for all images to generate
        logger.info("Waiting for all images to generate...")
        await self._wait_for_batch_generation(
            expected_count=len(scenes),
            initial_urls=initial_image_urls
        )

        # Step 6: Download all NEW images
        logger.info("Downloading generated images...")
        images = await self._download_generated_images(
            count=len(scenes),
            exclude_urls=initial_image_urls
        )

        logger.info("=" * 70)
        logger.info(f"BATCH COMPLETE: {len(images)}/{len(scenes)} images downloaded")
        logger.info("=" * 70)

        return images

    async def _wait_for_batch_generation(
        self,
        expected_count: int,
        initial_urls: List[str],
        timeout: int = 300
    ) -> None:
        """
        РћС‡С–РєСѓРІР°РЅРЅСЏ Р·Р°РІРµСЂС€РµРЅРЅСЏ batch РіРµРЅРµСЂР°С†С–С—.

        РџРµСЂРµРІС–СЂСЏС” DOM РєРѕР¶РЅС– 20 СЃРµРєСѓРЅРґ (Р‘Р•Р— refresh).
        РџРµСЂРµРІС–СЂСЏС” СЃС‚Р°С‚СѓСЃ pending/queue - СЏРєС‰Рѕ РІ С‡РµСЂР·С–, РїСЂРѕРґРѕРІР¶СѓС” С‡РµРєР°С‚Рё.
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

