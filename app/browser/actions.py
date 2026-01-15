"""
Browser Actions with Human-Like Delays

Provides browser interaction methods that simulate human behavior
to avoid detection and rate limiting.
"""

import asyncio
import random
from typing import Optional, List, Tuple
from pathlib import Path

from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    ElementClickInterceptedException,
    StaleElementReferenceException,
)
from loguru import logger

from config.timeouts import HUMAN, BROWSER


class BrowserActions:
    """
    Human-like browser interactions with random delays.

    All actions include appropriate delays to simulate natural user behavior.

    Usage:
        actions = BrowserActions(driver)

        # Click with human-like delay
        await actions.click("button.submit")

        # Type with realistic typing speed
        await actions.type_text("input.prompt", "Hello world")

        # Wait for element
        element = await actions.wait_for_element(".result", timeout=30)
    """

    def __init__(self, driver: WebDriver):
        self.driver = driver
        self._action_chains = ActionChains(driver)

    # ========================================================================
    # WAITING
    # ========================================================================

    async def wait_for_element(
        self,
        selector: str,
        by: str = By.CSS_SELECTOR,
        timeout: int = None,
        visible: bool = True
    ) -> Optional[WebElement]:
        """
        Wait for element to appear on page.

        Args:
            selector: CSS selector or XPath
            by: Selector type (By.CSS_SELECTOR or By.XPATH)
            timeout: Max wait time in seconds
            visible: Wait for visibility (True) or just presence (False)

        Returns:
            WebElement if found, None if timeout
        """
        timeout = timeout or BROWSER.ELEMENT_WAIT

        try:
            wait = WebDriverWait(self.driver, timeout)
            condition = (
                EC.visibility_of_element_located((by, selector))
                if visible
                else EC.presence_of_element_located((by, selector))
            )
            element = await asyncio.to_thread(wait.until, condition)
            return element
        except TimeoutException:
            logger.debug(f"Element not found: {selector}")
            return None

    async def wait_for_elements(
        self,
        selector: str,
        by: str = By.CSS_SELECTOR,
        timeout: int = None,
        min_count: int = 1
    ) -> List[WebElement]:
        """
        Wait for multiple elements to appear.

        Args:
            selector: CSS selector or XPath
            by: Selector type
            timeout: Max wait time
            min_count: Minimum number of elements to wait for

        Returns:
            List of WebElements (may be empty)
        """
        timeout = timeout or BROWSER.ELEMENT_WAIT

        try:
            wait = WebDriverWait(self.driver, timeout)
            elements = await asyncio.to_thread(
                wait.until,
                lambda d: d.find_elements(by, selector) if len(d.find_elements(by, selector)) >= min_count else False
            )
            return elements if elements else []
        except TimeoutException:
            return []

    async def wait_for_element_gone(
        self,
        selector: str,
        by: str = By.CSS_SELECTOR,
        timeout: int = None
    ) -> bool:
        """
        Wait for element to disappear from page.

        Returns:
            True if element disappeared, False if timeout
        """
        timeout = timeout or BROWSER.ELEMENT_WAIT

        try:
            wait = WebDriverWait(self.driver, timeout)
            await asyncio.to_thread(
                wait.until,
                EC.invisibility_of_element_located((by, selector))
            )
            return True
        except TimeoutException:
            return False

    # ========================================================================
    # CLICKING
    # ========================================================================

    async def click(
        self,
        selector: str,
        by: str = By.CSS_SELECTOR,
        timeout: int = None,
        scroll_into_view: bool = True
    ) -> bool:
        """
        Click element with human-like delay.

        Args:
            selector: CSS selector or XPath
            by: Selector type
            timeout: Max wait time for element
            scroll_into_view: Scroll to element before clicking

        Returns:
            True if clicked successfully, False otherwise
        """
        element = await self.wait_for_element(selector, by, timeout)
        if not element:
            logger.warning(f"Cannot click - element not found: {selector}")
            return False

        return await self.click_element(element, scroll_into_view)

    async def click_element(
        self,
        element: WebElement,
        scroll_into_view: bool = True
    ) -> bool:
        """
        Click a WebElement with human-like delay.

        Args:
            element: WebElement to click
            scroll_into_view: Scroll to element before clicking

        Returns:
            True if clicked successfully
        """
        try:
            # Scroll into view if needed
            if scroll_into_view:
                await asyncio.to_thread(
                    self.driver.execute_script,
                    "arguments[0].scrollIntoView({block: 'center'});",
                    element
                )
                await asyncio.sleep(HUMAN.SCROLL_PAUSE.get())

            # Human-like delay before click
            await asyncio.sleep(HUMAN.BEFORE_CLICK.get())

            # Click
            await asyncio.to_thread(element.click)

            # Human-like delay after click
            await asyncio.sleep(HUMAN.AFTER_CLICK.get())

            return True

        except ElementClickInterceptedException:
            # Try JavaScript click as fallback
            logger.debug("Click intercepted, trying JS click")
            try:
                await asyncio.to_thread(
                    self.driver.execute_script,
                    "arguments[0].click();",
                    element
                )
                await asyncio.sleep(HUMAN.AFTER_CLICK.get())
                return True
            except Exception as e:
                logger.warning(f"JS click also failed: {e}")
                return False

        except StaleElementReferenceException:
            logger.warning("Element became stale before click")
            return False

        except Exception as e:
            logger.warning(f"Click failed: {e}")
            return False

    # ========================================================================
    # TYPING
    # ========================================================================

    async def type_text(
        self,
        selector: str,
        text: str,
        by: str = By.CSS_SELECTOR,
        clear_first: bool = True,
        human_like: bool = True
    ) -> bool:
        """
        Type text into input field with human-like delays.

        Args:
            selector: CSS selector or XPath
            text: Text to type
            by: Selector type
            clear_first: Clear existing text before typing
            human_like: Use realistic typing speed

        Returns:
            True if typed successfully
        """
        element = await self.wait_for_element(selector, by)
        if not element:
            logger.warning(f"Cannot type - element not found: {selector}")
            return False

        return await self.type_into_element(element, text, clear_first, human_like)

    async def type_into_element(
        self,
        element: WebElement,
        text: str,
        clear_first: bool = True,
        human_like: bool = True
    ) -> bool:
        """
        Type text into a WebElement.

        Args:
            element: WebElement to type into
            text: Text to type
            clear_first: Clear existing text
            human_like: Use realistic typing speed
        """
        try:
            # Focus element
            await asyncio.to_thread(element.click)
            await asyncio.sleep(HUMAN.BEFORE_CLICK.get())

            # Clear if requested
            if clear_first:
                await asyncio.to_thread(element.clear)
                await asyncio.sleep(0.1)

                # Select all and delete (more reliable)
                await asyncio.to_thread(
                    element.send_keys,
                    Keys.CONTROL + "a"
                )
                await asyncio.sleep(0.05)
                await asyncio.to_thread(
                    element.send_keys,
                    Keys.DELETE
                )
                await asyncio.sleep(0.1)

            if human_like:
                # Type character by character with random delays
                for i, char in enumerate(text):
                    await asyncio.to_thread(element.send_keys, char)
                    await asyncio.sleep(HUMAN.CHAR_TYPING.get())

                    # Occasional word pause
                    if char == ' ' and random.random() < 0.3:
                        await asyncio.sleep(HUMAN.WORD_PAUSE.get())
            else:
                # Fast typing (still async)
                await asyncio.to_thread(element.send_keys, text)

            await asyncio.sleep(HUMAN.AFTER_CLICK.get())
            return True

        except Exception as e:
            logger.warning(f"Type failed: {e}")
            return False

    async def clear_field(
        self,
        selector: str,
        by: str = By.CSS_SELECTOR
    ) -> bool:
        """
        Clear text field.

        Args:
            selector: CSS selector or XPath
            by: Selector type
        """
        element = await self.wait_for_element(selector, by)
        if not element:
            return False

        try:
            await asyncio.to_thread(element.click)
            await asyncio.sleep(0.1)
            await asyncio.to_thread(element.send_keys, Keys.CONTROL + "a")
            await asyncio.sleep(0.05)
            await asyncio.to_thread(element.send_keys, Keys.DELETE)
            await asyncio.sleep(HUMAN.AFTER_CLICK.get())
            return True
        except Exception as e:
            logger.warning(f"Clear failed: {e}")
            return False

    # ========================================================================
    # FILE UPLOAD
    # ========================================================================

    async def upload_file(
        self,
        selector: str,
        file_path: Path,
        by: str = By.CSS_SELECTOR
    ) -> bool:
        """
        Upload file to input[type=file] element.

        Args:
            selector: CSS selector for file input
            file_path: Path to file to upload
            by: Selector type

        Returns:
            True if uploaded successfully
        """
        if not file_path.exists():
            logger.error(f"File not found: {file_path}")
            return False

        element = await self.wait_for_element(selector, by, visible=False)
        if not element:
            logger.warning(f"File input not found: {selector}")
            return False

        try:
            await asyncio.sleep(HUMAN.BEFORE_CLICK.get())
            await asyncio.to_thread(element.send_keys, str(file_path.absolute()))
            await asyncio.sleep(HUMAN.BETWEEN_UPLOADS.get())
            logger.debug(f"Uploaded file: {file_path.name}")
            return True
        except Exception as e:
            logger.warning(f"Upload failed: {e}")
            return False

    # ========================================================================
    # SCROLLING
    # ========================================================================

    async def scroll_to_element(
        self,
        selector: str,
        by: str = By.CSS_SELECTOR,
        block: str = "center"
    ) -> bool:
        """
        Scroll element into view.

        Args:
            selector: CSS selector or XPath
            by: Selector type
            block: Scroll position ("start", "center", "end")
        """
        element = await self.wait_for_element(selector, by, visible=False)
        if not element:
            return False

        try:
            await asyncio.to_thread(
                self.driver.execute_script,
                f"arguments[0].scrollIntoView({{block: '{block}', behavior: 'smooth'}});",
                element
            )
            await asyncio.sleep(HUMAN.SCROLL_PAUSE.get())
            return True
        except Exception as e:
            logger.warning(f"Scroll failed: {e}")
            return False

    async def scroll_page(self, direction: str = "down", amount: int = 300) -> None:
        """
        Scroll page up or down.

        Args:
            direction: "up" or "down"
            amount: Pixels to scroll
        """
        y = amount if direction == "down" else -amount
        await asyncio.to_thread(
            self.driver.execute_script,
            f"window.scrollBy(0, {y});"
        )
        await asyncio.sleep(HUMAN.SCROLL_PAUSE.get())

    # ========================================================================
    # NAVIGATION
    # ========================================================================

    async def navigate(self, url: str) -> bool:
        """
        Navigate to URL with human-like delay after load.

        Args:
            url: URL to navigate to

        Returns:
            True if navigation successful
        """
        try:
            await asyncio.to_thread(self.driver.get, url)
            await asyncio.sleep(HUMAN.PAGE_THINK.get())
            return True
        except Exception as e:
            logger.error(f"Navigation failed: {e}")
            return False

    async def refresh(self) -> None:
        """Refresh page with human-like delay"""
        await asyncio.to_thread(self.driver.refresh)
        await asyncio.sleep(HUMAN.PAGE_THINK.get())

    # ========================================================================
    # UTILITIES
    # ========================================================================

    async def get_element_text(
        self,
        selector: str,
        by: str = By.CSS_SELECTOR
    ) -> Optional[str]:
        """Get text content of element"""
        element = await self.wait_for_element(selector, by)
        if element:
            return await asyncio.to_thread(lambda: element.text)
        return None

    async def get_element_attribute(
        self,
        selector: str,
        attribute: str,
        by: str = By.CSS_SELECTOR
    ) -> Optional[str]:
        """Get attribute value of element"""
        element = await self.wait_for_element(selector, by)
        if element:
            return await asyncio.to_thread(element.get_attribute, attribute)
        return None

    async def element_exists(
        self,
        selector: str,
        by: str = By.CSS_SELECTOR
    ) -> bool:
        """Check if element exists (non-blocking)"""
        try:
            elements = await asyncio.to_thread(
                self.driver.find_elements,
                by, selector
            )
            return len(elements) > 0
        except Exception:
            return False

    async def get_page_source(self) -> str:
        """Get current page HTML source"""
        return await asyncio.to_thread(lambda: self.driver.page_source)

    async def execute_script(self, script: str, *args) -> any:
        """Execute JavaScript on page"""
        return await asyncio.to_thread(
            self.driver.execute_script,
            script,
            *args
        )
