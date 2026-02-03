"""
Interaction Phase

Handles typing and submitting the comment with human-like behavior.
"""

import asyncio
import random
from typing import Optional

from playwright.async_api import Page

from ..biometrics import HumanMouse, HumanScroll, HumanKeyboard, GaussianDelay
from ..youtube.selectors import YouTubeSelectors
from ..config import CommenterConfig
from ..safety.logger import get_logger

logger = get_logger(__name__)


class InteractionPhase:
    """
    Handles the comment interaction phase.

    Focuses the comment input, types the comment with human-like
    patterns (including errors), and submits.
    """

    def __init__(
        self,
        page: Page,
        mouse: HumanMouse,
        scroll: HumanScroll,
        keyboard: HumanKeyboard,
        config: CommenterConfig
    ):
        self.page = page
        self.mouse = mouse
        self.scroll = scroll
        self.keyboard = keyboard
        self.config = config
        self._selectors = YouTubeSelectors()

    async def execute(self, comment_text: str) -> bool:
        """
        Execute the interaction phase - type and submit comment.

        Args:
            comment_text: The comment to post

        Returns:
            True if comment was submitted successfully
        """
        logger.info("Starting interaction phase")

        try:
            # Ensure comment input is visible
            await self._ensure_comment_input_visible()

            # Focus the comment input
            if not await self._focus_comment_input():
                logger.error("Failed to focus comment input")
                return False

            # Small pause before typing
            await GaussianDelay.from_config(self.config.delay_before_click).wait()

            # Type the comment
            await self.keyboard.type_text(comment_text)

            # Small pause after typing (reviewing what we typed)
            await asyncio.sleep(random.uniform(0.5, 1.5))

            # Submit the comment
            if not await self._submit_comment():
                logger.error("Failed to submit comment")
                return False

            logger.info("Comment submitted successfully")
            return True

        except Exception as e:
            logger.error(f"Interaction phase failed: {e}")
            return False

    async def _ensure_comment_input_visible(self) -> bool:
        """
        Scroll to ensure comment input is visible.

        Returns:
            True if input is visible
        """
        # First try to find the comment box
        comment_box = await self.page.query_selector(self._selectors.COMMENT_INPUT_BOX)

        if not comment_box:
            # Try alternative selector
            comment_box = await self.page.query_selector(self._selectors.COMMENT_INPUT_SIMPLE)

        if not comment_box:
            # Scroll down to find it
            await self.scroll.scroll_to_element(self._selectors.COMMENTS_SECTION)
            await asyncio.sleep(0.5)

            comment_box = await self.page.query_selector(self._selectors.COMMENT_INPUT_BOX)

        if comment_box:
            await comment_box.scroll_into_view_if_needed()
            return True

        return False

    async def _focus_comment_input(self) -> bool:
        """
        Click to focus the comment input field.

        YouTube has a two-stage comment box:
        1. Click placeholder to activate
        2. Then type in the actual input

        Returns:
            True if input is focused
        """
        # Try clicking the placeholder first
        placeholder = await self.page.query_selector(self._selectors.COMMENT_INPUT_BOX)

        if not placeholder:
            placeholder = await self.page.query_selector(self._selectors.COMMENT_INPUT_SIMPLE)

        if placeholder:
            box = await placeholder.bounding_box()
            if box:
                # Click with human-like behavior
                await self.mouse.click_at(
                    box["x"] + box["width"] / 2,
                    box["y"] + box["height"] / 2
                )

                # Wait for actual input to appear
                await asyncio.sleep(0.5)

        # Now try to find and focus the actual input
        tries = 0
        max_tries = 5

        while tries < max_tries:
            # Look for the contenteditable input
            input_field = await self.page.query_selector(self._selectors.COMMENT_INPUT_FOCUSED)

            if input_field:
                # Verify it's editable
                is_editable = await input_field.is_editable()
                if is_editable:
                    # Click to ensure focus
                    box = await input_field.bounding_box()
                    if box:
                        await self.mouse.click_at(
                            box["x"] + 20,  # Click near start of input
                            box["y"] + box["height"] / 2
                        )
                    await asyncio.sleep(0.2)
                    return True

            # Not found, wait and retry
            await asyncio.sleep(0.3)
            tries += 1

        return False

    async def _submit_comment(self) -> bool:
        """
        Click the submit button to post the comment.

        Returns:
            True if submit was successful
        """
        # Wait a moment (human would pause before clicking submit)
        await asyncio.sleep(random.uniform(0.3, 0.8))

        # Find submit button
        submit_button = await self.page.query_selector(self._selectors.COMMENT_SUBMIT_BUTTON)

        if not submit_button:
            logger.warning("Submit button not found")
            return False

        # Check if button is enabled
        is_disabled = await submit_button.get_attribute("disabled")
        if is_disabled:
            logger.warning("Submit button is disabled")
            return False

        # Get button position
        box = await submit_button.bounding_box()
        if not box:
            logger.warning("Could not get submit button position")
            return False

        # Click submit
        await self.mouse.click_at(
            box["x"] + box["width"] / 2,
            box["y"] + box["height"] / 2
        )

        # Wait for comment to be posted
        await asyncio.sleep(2.0)

        # Verify comment was posted (button should be disabled or hidden)
        submit_button = await self.page.query_selector(self._selectors.COMMENT_SUBMIT_BUTTON)

        if submit_button:
            is_disabled = await submit_button.get_attribute("disabled")
            if is_disabled:
                return True

        # Alternative check: look for our comment in the list
        # (Would need to implement comment matching)

        return True  # Assume success if no errors

    async def clear_and_retype(self, new_text: str) -> bool:
        """
        Clear current text and type new comment.

        Useful for error correction.

        Args:
            new_text: New comment text

        Returns:
            True if successful
        """
        # Select all and delete
        await self.keyboard.press_combo("Control", "a")
        await asyncio.sleep(0.1)
        await self.keyboard.press_key("Backspace")
        await asyncio.sleep(0.3)

        # Type new text
        await self.keyboard.type_text(new_text)

        return True
