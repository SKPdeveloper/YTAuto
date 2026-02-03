"""
YouTube Popup Handler

Dismisses various popups that YouTube shows:
- Cookie consent dialogs
- Premium upsell popups
- Sign-in prompts
- Survey dialogs
"""

import asyncio
from typing import List, Tuple

from playwright.async_api import Page

from .selectors import YouTubeSelectors
from ..biometrics import HumanMouse, GaussianDelay
from ..config import CommenterConfig
from ..safety.logger import get_logger

logger = get_logger(__name__)


class PopupHandler:
    """
    Handles YouTube popups and dialogs.

    Automatically dismisses popups that could interfere with automation,
    using human-like clicking behavior.
    """

    def __init__(self, page: Page, mouse: HumanMouse, config: CommenterConfig):
        self.page = page
        self.mouse = mouse
        self.config = config

        # Popup selectors with dismiss actions (selector, dismiss_selector)
        self._popup_configs: List[Tuple[str, str]] = [
            # Cookie consent - accept all
            ("ytd-consent-bump-v2-lightbox", "button[aria-label*='Accept all']"),
            # Alternative cookie dialog
            ("tp-yt-paper-dialog:has-text('cookie')", "button:has-text('Accept')"),
            # Premium popup
            ("ytd-popup-container yt-upsell-dialog-renderer", "#dismiss-button"),
            # Generic dismiss button
            ("yt-upsell-dialog-renderer", "[aria-label='Dismiss']"),
            # Survey popup
            ("ytd-mealbar-promo-renderer", "#dismiss-button"),
            # Mini player popup
            ("ytd-miniplayer", "#close-button"),
            # "Use YouTube in Chrome" banner
            ("[aria-label='Close']", "[aria-label='Close']"),
        ]

    async def dismiss_all(self) -> int:
        """
        Check for and dismiss all known popups.

        Returns:
            Number of popups dismissed
        """
        dismissed = 0

        for popup_selector, dismiss_selector in self._popup_configs:
            try:
                popup = await self.page.query_selector(popup_selector)
                if popup and await popup.is_visible():
                    if await self._dismiss_popup(popup_selector, dismiss_selector):
                        dismissed += 1
                        # Small delay between dismissals
                        await asyncio.sleep(0.5)
            except Exception:
                continue

        if dismissed > 0:
            logger.info(f"Dismissed {dismissed} popup(s)")

        return dismissed

    async def dismiss_cookies(self) -> bool:
        """
        Dismiss cookie consent dialog if present.

        Returns:
            True if dialog was dismissed
        """
        # Try multiple cookie dialog selectors
        cookie_selectors = [
            ("ytd-consent-bump-v2-lightbox", "button[aria-label*='Accept all']"),
            ("tp-yt-paper-dialog", "button:has-text('Accept')"),
            ("#dialog:has-text('cookie')", "button:has-text('Accept')"),
        ]

        for popup_sel, dismiss_sel in cookie_selectors:
            if await self._dismiss_popup(popup_sel, dismiss_sel):
                logger.info("Dismissed cookie consent dialog")
                return True

        return False

    async def dismiss_premium(self) -> bool:
        """
        Dismiss YouTube Premium upsell popup.

        Returns:
            True if popup was dismissed
        """
        selectors = [
            ("ytd-popup-container yt-upsell-dialog-renderer", "#dismiss-button"),
            ("yt-upsell-dialog-renderer", "[aria-label='Dismiss']"),
            ("ytd-mealbar-promo-renderer", "#dismiss-button"),
        ]

        for popup_sel, dismiss_sel in selectors:
            if await self._dismiss_popup(popup_sel, dismiss_sel):
                logger.info("Dismissed Premium popup")
                return True

        return False

    async def dismiss_signin(self) -> bool:
        """
        Dismiss sign-in prompt if present.

        Returns:
            True if prompt was dismissed
        """
        return await self._dismiss_popup(
            "yt-upsell-dialog-renderer",
            "#dismiss-button"
        )

    async def wait_for_no_popups(self, timeout: float = 5.0) -> bool:
        """
        Wait until no popups are visible.

        Args:
            timeout: Maximum time to wait in seconds

        Returns:
            True if no popups after waiting
        """
        start_time = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start_time < timeout:
            # Check for any visible popups
            has_popup = False

            for popup_selector, _ in self._popup_configs:
                try:
                    popup = await self.page.query_selector(popup_selector)
                    if popup and await popup.is_visible():
                        has_popup = True
                        await self.dismiss_all()
                        break
                except Exception:
                    continue

            if not has_popup:
                return True

            await asyncio.sleep(0.5)

        return False

    async def _dismiss_popup(self, popup_selector: str, dismiss_selector: str) -> bool:
        """
        Internal method to dismiss a specific popup.

        Args:
            popup_selector: Selector for the popup container
            dismiss_selector: Selector for the dismiss button within popup

        Returns:
            True if popup was found and dismissed
        """
        try:
            # Check if popup exists and is visible
            popup = await self.page.query_selector(popup_selector)
            if not popup:
                return False

            is_visible = await popup.is_visible()
            if not is_visible:
                return False

            # Find dismiss button
            dismiss_button = await self.page.query_selector(dismiss_selector)
            if not dismiss_button:
                # Try within popup
                dismiss_button = await popup.query_selector(dismiss_selector)

            if not dismiss_button:
                return False

            # Get button position
            box = await dismiss_button.bounding_box()
            if not box:
                return False

            # Click with human-like behavior
            center_x = box["x"] + box["width"] / 2
            center_y = box["y"] + box["height"] / 2

            await self.mouse.click_at(center_x, center_y)

            # Wait for popup to close
            await asyncio.sleep(0.3)

            return True

        except Exception as e:
            logger.debug(f"Failed to dismiss popup {popup_selector}: {e}")
            return False

    async def click_body_to_dismiss(self) -> None:
        """
        Click on page body to dismiss any overlay.

        Some popups can be dismissed by clicking outside them.
        """
        try:
            viewport = await self.page.viewport_size
            if viewport:
                # Click near center but avoid common popup positions
                x = viewport["width"] * 0.2
                y = viewport["height"] * 0.8
                await self.mouse.click_at(x, y)
        except Exception as e:
            logger.debug(f"Body click failed: {e}")

    async def press_escape(self) -> None:
        """Press Escape to dismiss any popup"""
        await self.page.keyboard.press("Escape")
        await asyncio.sleep(0.2)
