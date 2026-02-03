"""
Human Browser - Unified Interface

Combines all human-like interaction modules into a single class.
This is the main entry point for generic browser automation with human behavior.

For YouTube-specific automation, use HumanCommenter instead.
"""

import asyncio
import random
import logging
from typing import Optional, Tuple, Any
from dataclasses import dataclass, field

from playwright.async_api import Page

from ..biometrics import (
    BimodalDelay,
    HumanMouse,
    HumanKeyboard,
    HumanScroll,
    ScrollNormalizer,
)
from ..config import (
    ProfileSeedGenerator,
    ViewportPool,
    CommenterConfig,
)
from ..utils import RetryHandler, RetryError
from ..state import SessionState
from ..safety.logger import get_logger

logger = get_logger(__name__)


@dataclass
class HumanBrowserConfig:
    """Configuration for HumanBrowser."""
    profile_id: str
    viewport_max_width: Optional[int] = None
    viewport_max_height: Optional[int] = None
    typing_error_rate: float = 0.05
    hover_before_click_chance: float = 0.4
    enable_state_persistence: bool = True
    max_retry_attempts: int = 3
    retry_base_delay: float = 2.0

    # Internal config (created from CommenterConfig)
    _commenter_config: Optional[CommenterConfig] = field(default=None, repr=False)

    def __post_init__(self):
        if self._commenter_config is None:
            self._commenter_config = CommenterConfig()
            # Apply typing error rate to keyboard config
            self._commenter_config.keyboard.wrong_key_chance = self.typing_error_rate


class HumanBrowser:
    """
    Human-like browser interaction interface.

    Provides unified access to:
    - Realistic mouse movements (Bezier curves, Fitts' Law, tremor)
    - Natural click timing (overshoot, spiral approach)
    - Human typing patterns (5 typo types, bimodal delays)
    - Proper scroll behavior (device-specific deltas)
    - Session state management (scroll positions, visited pages)

    Usage:
        config = HumanBrowserConfig(profile_id="my_profile")
        async with HumanBrowser(page, config) as browser:
            await browser.click("#button")
            await browser.type("#input", "Hello world")
            await browser.scroll_down(300)

    For YouTube automation specifically, use HumanCommenter instead.
    """

    def __init__(self, page: Page, config: HumanBrowserConfig):
        """
        Initialize HumanBrowser.

        Args:
            page: Playwright page instance
            config: Browser configuration
        """
        self.page = page
        self.config = config
        self._commenter_config = config._commenter_config

        # Initialize seed generator for profile-consistent behavior
        self._seed_gen = ProfileSeedGenerator(config.profile_id)

        # Apply profile-specific personality to config
        self._commenter_config.randomize_for_profile(config.profile_id)

        # Initialize biometrics components
        self._mouse = HumanMouse(page, self._commenter_config)
        self._keyboard = HumanKeyboard(
            page,
            self._commenter_config,
            mouse=self._mouse,
            profile_seed=self._seed_gen.get_behavior_seed('keyboard')
        )
        self._scroll = HumanScroll(
            page,
            self._commenter_config,
            profile_seed=self._seed_gen.get_behavior_seed('scroll')
        )

        # Retry handler
        self._retry = RetryHandler(
            max_attempts=config.max_retry_attempts,
            base_delay=config.retry_base_delay
        )

        # State management
        if config.enable_state_persistence:
            self._state = SessionState(config.profile_id)
        else:
            self._state = None

        # Action delays
        self._action_delay = BimodalDelay.for_clicks()
        self._nav_delay = BimodalDelay.for_navigation()

        logger.info(f"HumanBrowser initialized for profile: {config.profile_id}")
        logger.debug(f"Seed generator: {self._seed_gen}")
        logger.debug(f"Scroll device: {self._scroll.get_device_info()}")

    async def __aenter__(self) -> "HumanBrowser":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit - save state if enabled."""
        if self._state:
            await self._save_current_state()

    # === High-Level Actions ===

    async def click(
        self,
        selector: str,
        hover_first: Optional[bool] = None,
        timeout: float = 10.0,
        use_retry: bool = True
    ) -> bool:
        """
        Click element with human-like behavior.

        Args:
            selector: CSS selector or XPath
            hover_first: Hover before click (None = random based on config)
            timeout: Max wait time for element in seconds
            use_retry: Whether to retry on failure

        Returns:
            True if successful
        """
        async def do_click():
            element = await self.page.wait_for_selector(selector, timeout=timeout * 1000)
            if not element:
                raise ValueError(f"Element not found: {selector}")

            box = await element.bounding_box()
            if not box:
                raise ValueError(f"Element has no bounding box: {selector}")

            # Calculate click position (randomized within element)
            x = box["x"] + box["width"] * random.uniform(0.3, 0.7)
            y = box["y"] + box["height"] * random.uniform(0.35, 0.65)

            # Move to element
            await self._mouse.move_to(
                x, y,
                target_width=box["width"],
                target_height=box["height"]
            )

            # Optional hover with tremor
            should_hover = hover_first if hover_first is not None else (
                random.random() < self.config.hover_before_click_chance
            )
            if should_hover:
                await self._mouse.hover_with_tremor(
                    x, y,
                    duration=random.uniform(0.2, 0.6)
                )

            # Click
            await self._mouse.click_at(x, y)

            logger.debug(f"Clicked: {selector} at ({x:.0f}, {y:.0f})")
            return True

        try:
            if use_retry:
                return await self._retry.execute(do_click, page=self.page)
            return await do_click()
        except Exception as e:
            logger.error(f"Click failed: {selector} - {e}")
            return False

    async def type_text(
        self,
        selector: str,
        text: str,
        clear_first: bool = True,
        timeout: float = 10.0,
        use_retry: bool = True
    ) -> bool:
        """
        Type text into element with human-like patterns.

        Args:
            selector: CSS selector for input element
            text: Text to type
            clear_first: Clear existing content first
            timeout: Max wait time for element

        Returns:
            True if successful
        """
        async def do_type():
            # Focus element via click
            if not await self.click(selector, timeout=timeout, use_retry=False):
                raise ValueError(f"Failed to focus: {selector}")

            # Type with natural patterns
            await self._keyboard.type_text(text, clear_first=clear_first)

            logger.debug(f"Typed {len(text)} chars into: {selector}")
            return True

        try:
            if use_retry:
                return await self._retry.execute(do_type, page=self.page)
            return await do_type()
        except Exception as e:
            logger.error(f"Type failed: {selector} - {e}")
            return False

    async def scroll_down(self, pixels: Optional[int] = None) -> int:
        """
        Scroll down with realistic wheel events.

        Args:
            pixels: Amount to scroll (None = random 200-500)

        Returns:
            Actual pixels scrolled
        """
        return await self._scroll.scroll_down(pixels)

    async def scroll_up(self, pixels: Optional[int] = None) -> int:
        """
        Scroll up with realistic wheel events.

        Args:
            pixels: Amount to scroll (None = random 200-500)

        Returns:
            Actual pixels scrolled (negative)
        """
        return await self._scroll.scroll_up(pixels)

    async def scroll_to_element(
        self,
        selector: str,
        timeout: float = 10.0,
        offset_top: int = 100
    ) -> bool:
        """
        Scroll until element is visible.

        Args:
            selector: CSS selector
            timeout: Max time to spend scrolling
            offset_top: Desired offset from top of viewport

        Returns:
            True if element found and scrolled to
        """
        return await self._scroll.scroll_to_element(selector, offset_top=offset_top)

    async def scroll_to_bottom(self, max_scrolls: int = 20) -> int:
        """
        Scroll to page bottom with reading pauses.

        Args:
            max_scrolls: Maximum scroll actions

        Returns:
            Total pixels scrolled
        """
        return await self._scroll.scroll_to_bottom(max_scrolls=max_scrolls)

    async def hover(
        self,
        selector: str,
        duration: Optional[float] = None,
        timeout: float = 10.0
    ) -> bool:
        """
        Hover over element with micro-tremor.

        Args:
            selector: CSS selector
            duration: Hover duration (None = random 0.3-0.8s)
            timeout: Max wait for element

        Returns:
            True if successful
        """
        try:
            element = await self.page.wait_for_selector(selector, timeout=timeout * 1000)
            if not element:
                return False

            box = await element.bounding_box()
            if not box:
                return False

            x = box["x"] + box["width"] / 2
            y = box["y"] + box["height"] / 2

            # Move to element
            await self._mouse.move_to(x, y, target_width=box["width"], target_height=box["height"])

            # Hover with tremor
            if duration is None:
                duration = random.uniform(0.3, 0.8)
            await self._mouse.hover_with_tremor(x, y, duration=duration)

            logger.debug(f"Hovered: {selector} for {duration:.2f}s")
            return True

        except Exception as e:
            logger.error(f"Hover failed: {selector} - {e}")
            return False

    async def double_click(self, selector: str, timeout: float = 10.0) -> bool:
        """
        Double-click element.

        Args:
            selector: CSS selector
            timeout: Max wait for element

        Returns:
            True if successful
        """
        try:
            element = await self.page.wait_for_selector(selector, timeout=timeout * 1000)
            if not element:
                return False

            box = await element.bounding_box()
            if not box:
                return False

            x = box["x"] + box["width"] / 2
            y = box["y"] + box["height"] / 2

            await self._mouse.move_to(x, y, target_width=box["width"], target_height=box["height"])
            await self._mouse.double_click_at(x, y)

            logger.debug(f"Double-clicked: {selector}")
            return True

        except Exception as e:
            logger.error(f"Double-click failed: {selector} - {e}")
            return False

    async def press_key(self, key: str, hold_time: Optional[float] = None) -> None:
        """
        Press a keyboard key.

        Args:
            key: Key name (e.g., "Enter", "Tab", "Escape")
            hold_time: Optional hold duration
        """
        await self._keyboard.press_key(key, hold_time)

    async def press_combo(self, *keys: str) -> None:
        """
        Press key combination (e.g., Ctrl+A).

        Args:
            keys: Keys to press together
        """
        await self._keyboard.press_combo(*keys)

    # === Timing ===

    async def wait(self, min_seconds: float = 0.5, max_seconds: float = 2.0) -> float:
        """
        Wait with random duration.

        Args:
            min_seconds: Minimum wait
            max_seconds: Maximum wait

        Returns:
            Actual wait duration
        """
        duration = random.uniform(min_seconds, max_seconds)
        await asyncio.sleep(duration)
        return duration

    async def action_delay(self) -> float:
        """
        Natural bimodal delay between actions.

        Returns:
            Actual delay duration
        """
        return await self._action_delay.wait()

    async def navigation_delay(self) -> float:
        """
        Longer delay for navigation decisions.

        Returns:
            Actual delay duration
        """
        return await self._nav_delay.wait()

    # === State Management ===

    async def _save_current_state(self) -> None:
        """Save current page state."""
        if not self._state:
            return

        try:
            # Save scroll position
            scroll_y = await self.page.evaluate("window.pageYOffset")
            self._state.save_scroll_position(self.page.url, scroll_y)

            # Mark page as visited
            self._state.add_visited(self.page.url)

            logger.debug(f"State saved for: {self.page.url}")
        except Exception as e:
            logger.warning(f"Failed to save state: {e}")

    async def restore_scroll_position(self) -> bool:
        """
        Restore previously saved scroll position.

        Returns:
            True if position was restored
        """
        if not self._state:
            return False

        position = self._state.get_scroll_position(self.page.url)
        if position is None:
            return False

        # Scroll to saved position
        await self._scroll.scroll_to_element(f"body")  # First scroll to top
        if position > 0:
            await self._scroll.scroll_down(position)

        logger.debug(f"Restored scroll position: {position}px")
        return True

    def was_recently_visited(self, url: Optional[str] = None) -> bool:
        """Check if page was recently visited."""
        if not self._state:
            return False
        return self._state.was_recently_visited(url or self.page.url)

    def save_custom_data(self, key: str, value: Any) -> None:
        """Save custom data to state."""
        if self._state:
            self._state.set(key, value)

    def get_custom_data(self, key: str, default: Any = None) -> Any:
        """Get custom data from state."""
        if self._state:
            return self._state.get(key, default)
        return default

    # === Utilities ===

    @property
    def viewport(self) -> Tuple[int, int]:
        """Get configured viewport for this profile."""
        return ViewportPool.get_for_profile(
            self.config.profile_id,
            max_width=self.config.viewport_max_width,
            max_height=self.config.viewport_max_height
        )

    @property
    def seed_generator(self) -> ProfileSeedGenerator:
        """Access seed generator for custom randomization."""
        return self._seed_gen

    @property
    def state(self) -> Optional[SessionState]:
        """Access session state (may be None if disabled)."""
        return self._state

    @property
    def mouse(self) -> HumanMouse:
        """Direct access to mouse controller."""
        return self._mouse

    @property
    def keyboard(self) -> HumanKeyboard:
        """Direct access to keyboard controller."""
        return self._keyboard

    @property
    def scroll(self) -> HumanScroll:
        """Direct access to scroll controller."""
        return self._scroll

    def get_profile_info(self) -> dict:
        """Get information about the current profile configuration."""
        return {
            "profile_id": self.config.profile_id,
            "viewport": self.viewport,
            "seed_info": self._seed_gen.get_info(),
            "scroll_device": self._scroll.get_device_info(),
            "typo_weights": self._keyboard.get_typo_stats(),
            "personality": self._commenter_config.get_personality_info(),
        }
