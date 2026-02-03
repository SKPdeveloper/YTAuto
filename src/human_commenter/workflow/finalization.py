"""
Finalization Phase

Handles pinning the comment directly on the YouTube watch page.
After posting a comment, waits, refreshes, finds the comment,
hovers to reveal the 3-dot menu, and pins it.

This approach is more natural than going to YouTube Studio -
it mimics the author checking their own video after posting.
"""

import asyncio
import random
from typing import Optional, Tuple

from playwright.async_api import Page, ElementHandle

from ..biometrics import HumanMouse, HumanScroll, GaussianDelay
from ..youtube.selectors import YouTubeSelectors
from ..youtube.popup_handler import PopupHandler
from ..config import CommenterConfig
from ..safety.logger import get_logger

logger = get_logger(__name__)


class FinalizationPhase:
    """
    Handles the finalization phase - pinning the comment on watch page.

    Instead of navigating to YouTube Studio, pins the comment directly
    on the video watch page by:
    1. Waiting (cooling period with micro-movements)
    2. Refreshing the page
    3. Scrolling to comments
    4. Hovering to reveal 3-dot menu
    5. Clicking Pin
    6. Confirming in modal
    """

    def __init__(
        self,
        page: Page,
        mouse: HumanMouse,
        scroll: HumanScroll,
        popup_handler: PopupHandler,
        config: CommenterConfig
    ):
        self.page = page
        self.mouse = mouse
        self.scroll = scroll
        self.popup_handler = popup_handler
        self.config = config
        self._selectors = YouTubeSelectors()

    async def execute(self, video_id: str, comment_text: str) -> bool:
        """
        Execute the finalization phase - pin the comment on watch page.

        Args:
            video_id: YouTube video ID
            comment_text: The comment text (for identification)

        Returns:
            True if comment was pinned successfully
        """
        logger.info("Starting finalization phase (watch page pinning)")

        try:
            # Step 1: Cooling period with micro-movements
            await self._cooling_period()

            # Step 2: Refresh page to get author controls
            await self._refresh_page()

            # Step 3: Scroll to comments section
            if not await self._scroll_to_comments():
                logger.error("Failed to scroll to comments")
                return False

            # Step 4: Find and pin our comment
            if not await self._find_and_pin_comment(comment_text):
                logger.error("Failed to pin comment")
                return False

            # Step 5: Post-action entropy
            await self._post_action_entropy()

            logger.info("Comment pinned successfully on watch page")
            return True

        except Exception as e:
            logger.error(f"Finalization phase failed: {e}")
            return False

    async def _cooling_period(self) -> None:
        """
        Wait after posting comment with micro-movements.

        Gaussian delay: μ=45s, σ=10s
        During this time, simulate "zoning out" with micro-movements.
        """
        # Calculate wait time with Gaussian distribution
        delay = GaussianDelay(mean=45.0, std_dev=10.0, min_bound=30.0, max_bound=70.0)
        wait_time = delay.sample()

        logger.info(f"Cooling period: waiting {wait_time:.1f}s with micro-movements")

        start_time = asyncio.get_event_loop().time()
        elapsed = 0

        while elapsed < wait_time:
            # Random micro-action every 5-15 seconds
            action_interval = random.uniform(5, 15)
            await asyncio.sleep(min(action_interval, wait_time - elapsed))

            elapsed = asyncio.get_event_loop().time() - start_time

            if elapsed >= wait_time:
                break

            # Choose random micro-action
            action = random.choice([
                "micro_scroll",
                "hover_description",
                "hover_player",
                "tremor",
                "nothing"
            ])

            await self._do_micro_action(action)

    async def _do_micro_action(self, action: str) -> None:
        """Execute a micro-action during cooling period."""
        try:
            viewport = await self.page.viewport_size
            if not viewport:
                return

            if action == "micro_scroll":
                # Small scroll up or down
                pixels = random.randint(30, 100)
                if random.random() < 0.5:
                    pixels = -pixels
                await self.scroll._scroll(pixels, smooth=True)

            elif action == "hover_description":
                # Hover over video description area
                x = random.uniform(100, viewport["width"] * 0.6)
                y = random.uniform(450, 550)
                await self.mouse.hover_with_tremor(x, y, duration=random.uniform(0.5, 1.5))

            elif action == "hover_player":
                # Hover near the video player
                x = random.uniform(200, viewport["width"] - 200)
                y = random.uniform(150, 350)
                await self.mouse.hover_with_tremor(x, y, duration=random.uniform(0.3, 1.0))

            elif action == "tremor":
                # Just micro-tremor at current position
                pos = await self.mouse.get_current_position()
                await self.mouse.hover_with_tremor(pos.x, pos.y, duration=random.uniform(0.5, 2.0))

            # "nothing" - just wait

        except Exception as e:
            logger.debug(f"Micro-action {action} failed: {e}")

    async def _refresh_page(self) -> None:
        """
        Refresh the page to get author controls on comments.

        YouTube needs a refresh for the channel owner to see
        the full comment management menu.
        """
        logger.debug("Refreshing page to get author controls")

        # Small pause before refresh (human hesitation)
        await asyncio.sleep(random.uniform(0.5, 1.5))

        await self.page.reload()

        # Wait for page to load
        await GaussianDelay(mean=3.0, std_dev=1.0, min_bound=2.0, max_bound=5.0).wait()

        # Dismiss any popups that appeared
        await self.popup_handler.dismiss_all()

        # Additional wait for dynamic content
        await asyncio.sleep(random.uniform(1.0, 2.0))

    async def _scroll_to_comments(self) -> bool:
        """
        Scroll down to the comments section.

        Returns:
            True if comments section found
        """
        logger.debug("Scrolling to comments section")

        max_attempts = 2
        attempt = 0

        while attempt < max_attempts:
            # Gradual scroll down
            total_scrolled = 0
            max_scroll = 2500

            while total_scrolled < max_scroll:
                # Check if comments are visible
                comments_section = await self.page.query_selector(self._selectors.COMMENTS_SECTION)
                if comments_section:
                    box = await comments_section.bounding_box()
                    if box and box["y"] < 700:
                        logger.debug("Comments section found")
                        # Scroll a bit more to ensure full visibility
                        await self.scroll.scroll_down(pixels=random.randint(100, 200))
                        await asyncio.sleep(random.uniform(0.5, 1.0))
                        return True

                # Scroll down
                scroll_amount = random.randint(200, 350)
                await self.scroll.scroll_down(pixels=scroll_amount)
                total_scrolled += scroll_amount

                # Brief pause
                await asyncio.sleep(random.uniform(0.3, 0.7))

            attempt += 1
            if attempt < max_attempts:
                logger.debug(f"Comments not found, attempt {attempt + 1}")
                await self.scroll.scroll_to_top()
                await asyncio.sleep(1.0)

        return False

    async def _find_and_pin_comment(self, comment_text: str) -> bool:
        """
        Find our comment and pin it using the 3-dot menu.

        Args:
            comment_text: Text of our comment

        Returns:
            True if successfully pinned
        """
        # Wait for comments to fully load
        await asyncio.sleep(random.uniform(1.5, 2.5))

        # Find all comment threads
        comment_threads = await self.page.query_selector_all(self._selectors.COMMENT_THREAD)

        if not comment_threads:
            logger.warning("No comment threads found")
            return False

        logger.debug(f"Found {len(comment_threads)} comment threads")

        # Search for our comment (should be among the first few)
        target_comment = None
        partial_text = comment_text[:50]  # First 50 chars for matching

        for i, thread in enumerate(comment_threads[:10]):  # Check first 10
            try:
                # Get comment text content
                content_element = await thread.query_selector(self._selectors.COMMENT_CONTENT)
                if content_element:
                    content = await content_element.text_content()
                    if content and partial_text in content:
                        target_comment = thread
                        logger.debug(f"Found our comment at position {i + 1}")
                        break
            except Exception as e:
                logger.debug(f"Error checking comment {i}: {e}")
                continue

        if not target_comment:
            logger.warning(f"Could not find comment with text: {partial_text[:30]}...")
            return False

        # Step 1: Scroll comment into view
        await target_comment.scroll_into_view_if_needed()
        await asyncio.sleep(random.uniform(0.5, 1.0))

        # Step 2: Hover over comment to trigger menu appearance
        if not await self._hover_to_reveal_menu(target_comment):
            logger.error("Failed to reveal comment menu")
            return False

        # Step 3: Click the 3-dot menu
        if not await self._click_three_dot_menu(target_comment):
            logger.error("Failed to click 3-dot menu")
            return False

        # Step 4: Click "Pin" in the dropdown
        if not await self._click_pin_option():
            logger.error("Failed to click Pin option")
            return False

        # Step 5: Confirm in modal
        if not await self._confirm_pin_modal():
            logger.error("Failed to confirm pin")
            return False

        return True

    async def _hover_to_reveal_menu(self, comment_element: ElementHandle) -> bool:
        """
        Hover over the comment to reveal the 3-dot menu button.

        Uses dynamic hover radius approach:
        1. First enter the comment container area
        2. Wait 0.7s for CSS hover to trigger
        3. Move towards the menu button area

        This mimics how real users interact with hidden menus.

        Args:
            comment_element: The comment thread element

        Returns:
            True if menu button became visible
        """
        logger.debug("Hovering over comment to reveal menu (dynamic radius)")

        try:
            # Use the new hover_for_menu method with CSS hover wait
            success = await self.mouse.hover_for_menu(
                comment_element,
                menu_area_ratio=0.85,  # Menu appears on right side
                wait_for_css=0.7  # YouTube needs ~0.7s for hover effect
            )

            if not success:
                # Fallback to direct hover
                box = await comment_element.bounding_box()
                if not box:
                    return False

                hover_x = box["x"] + box["width"] * 0.85
                hover_y = box["y"] + box["height"] * 0.3

                await self.mouse.move_to(hover_x, hover_y)
                await self.mouse.hover_with_tremor(hover_x, hover_y, duration=1.5)

            # Check if menu button appeared
            await asyncio.sleep(0.3)

            # Look for the 3-dot menu button (action menu)
            menu_button = await comment_element.query_selector(
                "#action-menu button, #action-menu-button, ytd-menu-renderer button, "
                "yt-icon-button#button, [aria-label*='Action'], [aria-label*='More']"
            )

            if menu_button:
                is_visible = await menu_button.is_visible()
                if is_visible:
                    logger.debug("Menu button is now visible")
                    return True

            # Try broader search
            menu_button = await comment_element.query_selector("yt-icon-button, ytd-menu-renderer")
            if menu_button:
                return True

            logger.warning("Menu button not found after hover")
            return True  # Continue anyway, sometimes it's hidden in shadow DOM

        except Exception as e:
            logger.error(f"Hover failed: {e}")
            return False

    async def _click_three_dot_menu(self, comment_element: ElementHandle) -> bool:
        """
        Click the 3-dot menu button on the comment.

        Uses aiming behavior for small targets (overshoot + spiral approach).

        Args:
            comment_element: The comment thread element

        Returns:
            True if menu opened
        """
        logger.debug("Clicking 3-dot menu with aiming behavior")

        try:
            # Find the menu button - try multiple selectors
            menu_selectors = [
                "#action-menu button",
                "#action-menu-button",
                "ytd-menu-renderer yt-icon-button",
                "yt-icon-button#button",
                "[aria-label='Action menu']",
                "[aria-label='More actions']",
                "#action-menu yt-icon-button",
            ]

            menu_button = None
            for selector in menu_selectors:
                menu_button = await comment_element.query_selector(selector)
                if menu_button:
                    is_visible = await menu_button.is_visible()
                    if is_visible:
                        break
                    menu_button = None

            if not menu_button:
                # Try clicking in the general menu area
                box = await comment_element.bounding_box()
                if box:
                    # Click on the right side where menu typically is
                    click_x = box["x"] + box["width"] - 30
                    click_y = box["y"] + 30

                    # Use click_with_aiming for small target
                    await self.mouse.click_with_aiming(click_x, click_y, target_width=24, target_height=24)
                    await asyncio.sleep(0.5)
                    return True

                return False

            # Get button position
            button_box = await menu_button.bounding_box()
            if not button_box:
                return False

            # Use click_with_aiming for the small menu button
            # This includes overshoot correction and possible spiral approach
            await self.mouse.click_with_aiming(
                button_box["x"] + button_box["width"] / 2,
                button_box["y"] + button_box["height"] / 2,
                target_width=button_box["width"],
                target_height=button_box["height"]
            )

            # Wait for dropdown to appear
            await asyncio.sleep(random.uniform(0.5, 1.0))

            return True

        except Exception as e:
            logger.error(f"Click menu failed: {e}")
            return False

    async def _click_pin_option(self) -> bool:
        """
        Click the "Pin" option in the dropdown menu.

        Returns:
            True if Pin was clicked
        """
        logger.debug("Looking for Pin option in menu")

        # Wait for menu to fully render
        await asyncio.sleep(random.uniform(0.3, 0.6))

        # Selectors for the pin option
        pin_selectors = [
            "tp-yt-paper-listbox tp-yt-paper-item:has-text('Pin')",
            "ytd-menu-service-item-renderer:has-text('Pin')",
            "tp-yt-paper-item:has-text('Pin')",
            "[role='menuitem']:has-text('Pin')",
            "yt-formatted-string:has-text('Pin')",
        ]

        # Try to find pin option
        pin_element = None

        for selector in pin_selectors:
            try:
                pin_element = await self.page.query_selector(selector)
                if pin_element:
                    is_visible = await pin_element.is_visible()
                    if is_visible:
                        break
                    pin_element = None
            except Exception:
                continue

        # If not found, try searching all menu items
        if not pin_element:
            menu_items = await self.page.query_selector_all(
                "tp-yt-paper-item, ytd-menu-service-item-renderer, [role='menuitem']"
            )

            for item in menu_items:
                try:
                    text = await item.text_content()
                    if text and "pin" in text.lower():
                        is_visible = await item.is_visible()
                        if is_visible:
                            pin_element = item
                            break
                except Exception:
                    continue

        if not pin_element:
            logger.warning("Pin option not found in menu")
            # Press Escape to close menu
            await self.page.keyboard.press("Escape")
            return False

        # Delay before clicking (human reading the menu)
        await GaussianDelay(mean=0.8, std_dev=0.2, min_bound=0.5, max_bound=1.2).wait()

        # Click the pin option
        box = await pin_element.bounding_box()
        if box:
            await self.mouse.click_at(
                box["x"] + box["width"] / 2,
                box["y"] + box["height"] / 2
            )
        else:
            await pin_element.click()

        logger.debug("Clicked Pin option")

        # Wait for modal to appear
        await asyncio.sleep(random.uniform(0.5, 1.0))

        return True

    async def _confirm_pin_modal(self) -> bool:
        """
        Handle the pin confirmation modal.

        While waiting, apply micro-tremor to the cursor.

        Returns:
            True if confirmed successfully
        """
        logger.debug("Handling pin confirmation modal")

        # Wait for modal with micro-tremor
        modal_wait_start = asyncio.get_event_loop().time()
        max_modal_wait = 5.0
        modal_found = False

        # Selectors for confirmation button
        confirm_selectors = [
            "yt-button-renderer#confirm-button",
            "[aria-label='Pin']",
            "tp-yt-paper-button:has-text('Pin')",
            "button:has-text('Pin')",
            "#confirm-button",
            "yt-button-renderer:has-text('Pin')",
        ]

        while asyncio.get_event_loop().time() - modal_wait_start < max_modal_wait:
            # Apply micro-tremor while waiting (8-12 Hz)
            current_pos = await self.mouse.get_current_position()
            tremor_duration = random.uniform(0.3, 0.6)
            await self.mouse.hover_with_tremor(
                current_pos.x,
                current_pos.y,
                duration=tremor_duration,
                amplitude=1.0
            )

            # Check for confirmation button
            for selector in confirm_selectors:
                try:
                    confirm_button = await self.page.query_selector(selector)
                    if confirm_button:
                        is_visible = await confirm_button.is_visible()
                        if is_visible:
                            modal_found = True

                            # Small delay before confirming
                            await asyncio.sleep(random.uniform(0.3, 0.7))

                            # Click confirm
                            box = await confirm_button.bounding_box()
                            if box:
                                await self.mouse.click_at(
                                    box["x"] + box["width"] / 2,
                                    box["y"] + box["height"] / 2
                                )
                            else:
                                await confirm_button.click()

                            logger.debug("Confirmed pin in modal")

                            # Wait for modal to close
                            await asyncio.sleep(random.uniform(1.0, 2.0))
                            return True
                except Exception:
                    continue

            await asyncio.sleep(0.2)

        if not modal_found:
            logger.warning("Confirmation modal not found - pin may have succeeded without confirmation")
            return True  # Some videos don't show confirmation

        return False

    async def _post_action_entropy(self) -> None:
        """
        Post-pin entropy actions.

        After pinning:
        1. Scroll up to the player
        2. Maybe like the video
        3. Wait 15-30 seconds observing the result
        """
        logger.debug("Executing post-action entropy")

        try:
            # Scroll up to player
            await self.scroll.scroll_to_top()
            await asyncio.sleep(random.uniform(1.0, 2.0))

            # Maybe like the video (30% chance)
            if random.random() < 0.3:
                await self._maybe_like_video()

            # Final observation period (15-30 seconds)
            observation_time = random.uniform(15, 30)
            logger.debug(f"Final observation: {observation_time:.1f}s")

            start_time = asyncio.get_event_loop().time()
            while asyncio.get_event_loop().time() - start_time < observation_time:
                # Random micro-actions during observation
                action = random.choice(["hover", "tremor", "nothing", "nothing"])

                if action == "hover":
                    viewport = await self.page.viewport_size
                    if viewport:
                        x = random.uniform(200, viewport["width"] - 200)
                        y = random.uniform(150, 400)
                        await self.mouse.hover_with_tremor(x, y, duration=random.uniform(0.5, 1.5))

                elif action == "tremor":
                    pos = await self.mouse.get_current_position()
                    await self.mouse.hover_with_tremor(pos.x, pos.y, duration=random.uniform(0.3, 0.8))

                await asyncio.sleep(random.uniform(3, 7))

        except Exception as e:
            logger.debug(f"Post-action entropy error: {e}")

    async def _maybe_like_video(self) -> None:
        """Try to like the video if not already liked."""
        try:
            # Find like button
            like_button = await self.page.query_selector(
                "ytd-toggle-button-renderer#segmented-like-button button, "
                "#top-level-buttons-computed ytd-toggle-button-renderer button, "
                "[aria-label*='like']"
            )

            if not like_button:
                return

            # Check if already liked (aria-pressed="true")
            is_pressed = await like_button.get_attribute("aria-pressed")
            if is_pressed == "true":
                logger.debug("Video already liked")
                return

            # Click like with human behavior
            box = await like_button.bounding_box()
            if box:
                await self.mouse.click_at(
                    box["x"] + box["width"] / 2,
                    box["y"] + box["height"] / 2
                )
                logger.debug("Liked the video")
                await asyncio.sleep(random.uniform(0.5, 1.0))

        except Exception as e:
            logger.debug(f"Like video failed: {e}")

    async def verify_pin(self) -> bool:
        """
        Verify that the comment is pinned.

        Returns:
            True if a pinned comment indicator is found
        """
        try:
            # Refresh and check for pinned indicator
            await self.page.reload()
            await asyncio.sleep(2.0)

            # Scroll to comments
            await self._scroll_to_comments()

            # Look for "Pinned by" text
            pinned_indicator = await self.page.query_selector(
                "#pinned-comment-badge, "
                "span:has-text('Pinned'), "
                "[class*='pinned']"
            )

            return pinned_indicator is not None

        except Exception as e:
            logger.warning(f"Verify pin failed: {e}")
            return False
