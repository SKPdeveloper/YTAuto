"""
Human-Like Scroll Behavior

Simulates natural mouse wheel scrolling with:
- Device-specific delta normalization (mouse, touchpad)
- Variable scroll speeds
- Momentum-like behavior
- Occasional overshoots
- Reading pauses
- Bimodal delays

Real scroll devices produce discrete delta values:
- Windows mouse: 120 per notch
- Mac mouse: 40-120 variable
- Touchpad: 2-15 fine-grained

Arbitrary values like 347 are unrealistic and may trigger detection.
"""

import asyncio
import random
from typing import Optional, Tuple, List
from dataclasses import dataclass

from playwright.async_api import Page

from ..config import CommenterConfig, ScrollConfig
from .bimodal_delay import BimodalDelay, BimodalConfig
from ..safety.logger import get_logger
from ..safety.analytics_logger import get_analytics

logger = get_logger(__name__)


@dataclass
class DeviceProfile:
    """Scroll device hardware profile."""
    base_delta: Optional[int]  # None for touchpad (variable)
    noise_range: Tuple[int, int]  # Delta noise/variation
    weight: float  # Market share weight for random selection


class ScrollNormalizer:
    """
    Normalizes scroll values to match real input devices.

    Real scroll hardware produces specific delta patterns:
    - Windows mouse: 120 units per notch (with small noise)
    - Mac mouse: 40-120 variable
    - Precision mouse: 60 units (high-end gaming mice)
    - Touchpad: 2-15 fine-grained continuous events

    Using arbitrary values like 347 is a detection signal.
    This class converts pixel amounts to realistic device events.
    """

    DEVICES = {
        'windows_mouse': DeviceProfile(base_delta=120, noise_range=(-5, 5), weight=55),
        'mac_mouse': DeviceProfile(base_delta=40, noise_range=(-3, 3), weight=15),
        'precision_mouse': DeviceProfile(base_delta=60, noise_range=(-2, 2), weight=10),
        'touchpad': DeviceProfile(base_delta=None, noise_range=(3, 12), weight=20),
    }

    def __init__(self, profile_seed: Optional[int] = None):
        """
        Initialize with optional profile seed for consistent device selection.

        Args:
            profile_seed: Seed for deterministic device selection per profile
        """
        if profile_seed:
            rng = random.Random(profile_seed)
        else:
            rng = random

        # Select device based on market share weights
        devices = list(self.DEVICES.keys())
        weights = [self.DEVICES[d].weight for d in devices]
        self.device_type = rng.choices(devices, weights=weights)[0]
        self.device = self.DEVICES[self.device_type]

        logger.debug(f"ScrollNormalizer using device: {self.device_type}")

    def normalize(self, target_pixels: int) -> List[int]:
        """
        Convert pixel scroll amount to realistic delta events.

        Args:
            target_pixels: Desired scroll amount in pixels (positive = down)

        Returns:
            List of delta values to send as wheel events
        """
        if self.device_type == 'touchpad':
            return self._normalize_touchpad(target_pixels)
        return self._normalize_mouse(target_pixels)

    def _normalize_mouse(self, target: int) -> List[int]:
        """
        Generate discrete mouse wheel events.

        Mouse wheels produce fixed delta values per notch,
        with small noise from hardware imprecision.
        """
        base = self.device.base_delta
        noise_min, noise_max = self.device.noise_range

        direction = 1 if target > 0 else -1
        remaining = abs(target)
        deltas = []

        while remaining > base * 0.4:
            # Occasional double-notch (fast scroll)
            mult = random.choice([1, 1, 1, 2]) if remaining > base * 2.5 else 1

            # Base delta with noise
            delta = base * mult + random.randint(noise_min, noise_max)

            # Don't overshoot too much
            delta = min(delta, int(remaining * 1.2))

            deltas.append(delta * direction)
            remaining -= delta

        return deltas

    def _normalize_touchpad(self, target: int) -> List[int]:
        """
        Generate fine-grained touchpad events.

        Touchpads produce many small delta values,
        often with acceleration in the middle of a gesture.
        """
        min_d, max_d = self.device.noise_range
        direction = 1 if target > 0 else -1
        remaining = abs(target)
        deltas = []

        while remaining > 0:
            # Base delta
            delta = random.randint(min_d, max_d)

            # Acceleration in middle of scroll
            if len(deltas) > 5 and remaining > abs(target) * 0.4:
                delta = int(delta * random.uniform(1.3, 1.7))

            delta = min(delta, remaining)
            deltas.append(delta * direction)
            remaining -= delta

        return deltas

    def get_inter_event_delay(self) -> float:
        """
        Get appropriate delay between scroll events.

        Mouse wheels have longer gaps between events,
        touchpads produce rapid continuous events.
        """
        if self.device_type == 'touchpad':
            return random.uniform(0.008, 0.02)
        return random.uniform(0.025, 0.06)

    def get_device_info(self) -> dict:
        """Get information about the selected device."""
        return {
            'type': self.device_type,
            'base_delta': self.device.base_delta,
            'noise_range': self.device.noise_range,
        }


class HumanScroll:
    """
    Simulates human-like scrolling behavior.

    Features:
    - Device-specific delta normalization (via ScrollNormalizer)
    - Bimodal delays between scroll events
    - Occasional overshoot and correction
    - Smooth momentum simulation
    - Profile-specific behavior
    """

    def __init__(
        self,
        page: Page,
        config: CommenterConfig,
        profile_seed: Optional[int] = None
    ):
        """
        Initialize scroll handler.

        Args:
            page: Playwright page instance
            config: Commenter configuration
            profile_seed: Seed for consistent per-profile behavior
        """
        self.page = page
        self.config = config
        self.scroll_config: ScrollConfig = config.scroll

        # Initialize normalizer with profile seed
        self._normalizer = ScrollNormalizer(profile_seed)

        # Bimodal delay for scroll actions
        self._action_delay = BimodalDelay(BimodalConfig(
            fast_mean=0.3,
            fast_std=0.1,
            slow_mean=1.0,
            slow_std=0.3,
            fast_probability=0.65,
            min_bound=0.1,
            max_bound=2.0
        ))

    async def scroll_down(
        self,
        pixels: Optional[int] = None,
        smooth: bool = True
    ) -> int:
        """
        Scroll down by a number of pixels.

        Args:
            pixels: Number of pixels to scroll (random if None)
            smooth: Use smooth scrolling with device-appropriate events

        Returns:
            Actual pixels scrolled
        """
        if pixels is None:
            pixels = random.randint(200, 500)

        return await self._scroll(pixels, smooth)

    async def scroll_up(
        self,
        pixels: Optional[int] = None,
        smooth: bool = True
    ) -> int:
        """
        Scroll up by a number of pixels.

        Args:
            pixels: Number of pixels to scroll (random if None)
            smooth: Use smooth scrolling with device-appropriate events

        Returns:
            Actual pixels scrolled (negative)
        """
        if pixels is None:
            pixels = random.randint(200, 500)

        return await self._scroll(-pixels, smooth)

    async def scroll_to_element(
        self,
        selector: str,
        offset_top: int = 100
    ) -> bool:
        """
        Scroll until an element is visible.

        Args:
            selector: CSS selector for target element
            offset_top: Pixels from top of viewport to position element

        Returns:
            True if element was found and scrolled to
        """
        try:
            element = await self.page.wait_for_selector(selector, timeout=5000)
            if not element:
                return False

            # Get element position
            box = await element.bounding_box()
            if not box:
                return False

            # Get viewport size
            viewport = self.page.viewport_size
            if not viewport:
                viewport = {"height": 800}

            # Calculate scroll needed
            current_scroll = await self.page.evaluate("window.pageYOffset")
            target_scroll = current_scroll + box["y"] - offset_top

            scroll_needed = target_scroll - current_scroll

            if abs(scroll_needed) < 50:
                # Already visible, no scroll needed
                return True

            # Perform smooth scroll
            await self._scroll(int(scroll_needed), smooth=True)
            return True

        except Exception as e:
            logger.warning(f"Failed to scroll to element {selector}: {e}")
            return False

    async def scroll_to_bottom(
        self,
        pause_interval: int = 500,
        max_scrolls: int = 20
    ) -> int:
        """
        Scroll to the bottom of the page with pauses.

        Args:
            pause_interval: Pixels between reading pauses
            max_scrolls: Maximum number of scroll actions

        Returns:
            Total pixels scrolled
        """
        total_scrolled = 0
        scrolls_done = 0

        while scrolls_done < max_scrolls:
            # Check if at bottom
            at_bottom = await self.page.evaluate("""
                () => window.innerHeight + window.pageYOffset >= document.body.scrollHeight - 10
            """)

            if at_bottom:
                break

            # Scroll down
            scroll_amount = random.randint(
                self.scroll_config.pixels_per_step_min * 3,
                self.scroll_config.pixels_per_step_max * 3
            )
            scrolled = await self.scroll_down(scroll_amount)
            total_scrolled += scrolled
            scrolls_done += 1

            # Pause to "read" (bimodal - sometimes quick scan, sometimes careful reading)
            if scrolled >= pause_interval:
                await self._action_delay.wait()

        logger.debug(f"Scrolled to bottom: {total_scrolled}px in {scrolls_done} scrolls")
        return total_scrolled

    async def scroll_to_top(self) -> int:
        """
        Scroll back to the top of the page.

        Returns:
            Total pixels scrolled (negative)
        """
        current_scroll = await self.page.evaluate("window.pageYOffset")

        if current_scroll < 50:
            return 0

        return await self._scroll(-int(current_scroll), smooth=True)

    async def scroll_into_view_if_needed(self, selector: str) -> bool:
        """
        Scroll element into view if not already visible.

        Uses JavaScript scrollIntoView with smooth behavior.

        Args:
            selector: CSS selector for element

        Returns:
            True if element exists
        """
        try:
            element = await self.page.wait_for_selector(selector, timeout=5000)
            if not element:
                return False

            await element.scroll_into_view_if_needed()

            # Small delay after scroll (bimodal)
            await self._action_delay.wait()
            return True

        except Exception as e:
            logger.warning(f"Failed to scroll element into view {selector}: {e}")
            return False

    async def _scroll(self, total_pixels: int, smooth: bool = True) -> int:
        """
        Internal scroll implementation using device-normalized deltas.

        Args:
            total_pixels: Pixels to scroll (positive = down, negative = up)
            smooth: Use multiple device-appropriate events

        Returns:
            Actual pixels scrolled
        """
        import time
        start_time = time.time()
        analytics = get_analytics()
        direction = "down" if total_pixels > 0 else "up"

        if not smooth or abs(total_pixels) < 50:
            # Quick single scroll
            if analytics:
                analytics.log_scroll_start(direction, abs(total_pixels), self._normalizer.device_type)
                analytics.log_scroll_delta(total_pixels, total_pixels)
                analytics.log_scroll_end(abs(total_pixels), 1, (time.time() - start_time) * 1000)
            await self.page.mouse.wheel(0, total_pixels)
            return total_pixels

        # Get normalized deltas for the device
        deltas = self._normalizer.normalize(total_pixels)

        if not deltas:
            return 0

        # Log scroll start
        if analytics:
            analytics.log_scroll_start(direction, abs(total_pixels), self._normalizer.device_type)

        total_scrolled = 0

        for delta in deltas:
            await self.page.mouse.wheel(0, delta)
            total_scrolled += delta

            # Log each scroll delta
            if analytics:
                analytics.log_scroll_delta(delta, total_scrolled)

            # Device-appropriate delay between events
            await asyncio.sleep(self._normalizer.get_inter_event_delay())

        # Log scroll end
        if analytics:
            duration_ms = (time.time() - start_time) * 1000
            analytics.log_scroll_end(abs(total_scrolled), len(deltas), duration_ms)

        # Check for overshoot behavior
        if random.random() < self.scroll_config.overshoot_chance and abs(total_scrolled) > 100:
            await self._apply_overshoot(total_scrolled)

        logger.debug(f"Scrolled {total_scrolled}px in {len(deltas)} events ({self._normalizer.device_type})")
        return total_scrolled

    async def _apply_overshoot(self, scrolled: int) -> None:
        """
        Apply overshoot and correction (human behavior).

        Humans often scroll a bit too far then correct back.
        """
        direction = 1 if scrolled > 0 else -1
        analytics = get_analytics()

        # Overshoot
        overshoot_amount = random.randint(30, 80)
        overshoot_deltas = self._normalizer.normalize(overshoot_amount * direction)
        for delta in overshoot_deltas:
            await self.page.mouse.wheel(0, delta)
            await asyncio.sleep(self._normalizer.get_inter_event_delay())

        # Brief pause (noticing overshoot)
        await asyncio.sleep(random.uniform(0.1, 0.3))

        # Correct back
        correction_amount = random.randint(30, 80)
        correction_deltas = self._normalizer.normalize(correction_amount * -direction)
        for delta in correction_deltas:
            await self.page.mouse.wheel(0, delta)
            await asyncio.sleep(self._normalizer.get_inter_event_delay())

        # Log overshoot
        if analytics:
            analytics.log_scroll_overshoot(overshoot_amount * direction, correction_amount * -direction)

        logger.debug("Scroll overshoot corrected")

    async def get_scroll_position(self) -> Tuple[int, int]:
        """
        Get current scroll position.

        Returns:
            Tuple of (scrollX, scrollY)
        """
        result = await self.page.evaluate("""
            () => ({ x: window.pageXOffset, y: window.pageYOffset })
        """)
        return (result["x"], result["y"])

    async def get_scroll_height(self) -> int:
        """Get total scrollable height of page."""
        return await self.page.evaluate("document.body.scrollHeight")

    async def get_viewport_height(self) -> int:
        """Get viewport height."""
        viewport = self.page.viewport_size
        return viewport["height"] if viewport else 800

    def get_device_info(self) -> dict:
        """Get information about the scroll device being simulated."""
        return self._normalizer.get_device_info()
