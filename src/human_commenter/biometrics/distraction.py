"""
Distraction Simulation Module

Simulates natural human distraction behavior:
- Window blur/focus events
- Cursor leaving active area
- Idle periods during "distraction"
"""

import asyncio
import random
from typing import Optional

from playwright.async_api import Page

from ..config import CommenterConfig
from ..safety.logger import get_logger
from ..safety.analytics_logger import get_analytics

logger = get_logger(__name__)


class DistractedState:
    """
    Simulates user distraction/focus loss.

    Real users occasionally:
    - Get distracted by other applications
    - Look away from the screen
    - Take short breaks
    - Switch to other browser tabs

    This class simulates these behaviors by:
    1. Triggering blur event (window loses focus)
    2. Moving cursor outside the viewport
    3. Freezing all activity for a random duration
    4. Returning focus and resuming
    """

    def __init__(self, page: Page, config: CommenterConfig):
        self.page = page
        self.config = config
        self._distraction_min_duration: float = 10.0  # seconds
        self._distraction_max_duration: float = 20.0  # seconds
        self._distraction_chance: float = 0.15  # 15% chance per check

    async def maybe_get_distracted(self) -> bool:
        """
        Randomly trigger a distraction event.

        Returns:
            True if distraction occurred
        """
        if random.random() > self._distraction_chance:
            return False

        await self.simulate_distraction()
        return True

    async def simulate_distraction(
        self,
        min_duration: Optional[float] = None,
        max_duration: Optional[float] = None
    ) -> None:
        """
        Simulate a user distraction event.

        1. Move cursor outside viewport
        2. Trigger blur event
        3. Wait (user is "distracted")
        4. Return focus
        5. Move cursor back to safe area

        Args:
            min_duration: Minimum distraction time (default 10s)
            max_duration: Maximum distraction time (default 20s)
        """
        if min_duration is None:
            min_duration = self._distraction_min_duration
        if max_duration is None:
            max_duration = self._distraction_max_duration

        duration = random.uniform(min_duration, max_duration)
        logger.info(f"Simulating distraction for {duration:.1f}s")

        try:
            # Step 1: Move cursor outside viewport (to edge)
            await self._move_cursor_outside()

            # Step 2: Trigger blur event (window loses focus)
            await self._trigger_blur()

            # Step 3: Wait (user is "distracted")
            # During this time, no mouse movements or interactions
            await asyncio.sleep(duration)

            # Step 4: Return focus
            await self._trigger_focus()

            # Step 5: Move cursor back to safe area
            await self._return_cursor()

            logger.debug("Distraction completed, resuming activity")

        except Exception as e:
            logger.warning(f"Distraction simulation error: {e}")
            # Ensure focus is restored
            await self._trigger_focus()

    async def _move_cursor_outside(self) -> None:
        """Move cursor outside the visible viewport area."""
        viewport = self.page.viewport_size
        if not viewport:
            return

        # Move to bottom-right corner (common "rest" position when distracted)
        target_x = viewport["width"] + random.uniform(10, 50)
        target_y = viewport["height"] + random.uniform(10, 50)

        # Quick movement out
        await self.page.mouse.move(target_x, target_y)
        logger.debug("Cursor moved outside viewport for distraction")

    async def _trigger_blur(self) -> None:
        """Trigger window blur event (simulates switching to another app)."""
        try:
            await self.page.evaluate("""
                () => {
                    // Dispatch blur event
                    window.dispatchEvent(new Event('blur'));
                    document.dispatchEvent(new Event('visibilitychange'));

                    // If document.hidden is writable, set it
                    try {
                        Object.defineProperty(document, 'hidden', {
                            value: true,
                            writable: true,
                            configurable: true
                        });
                        Object.defineProperty(document, 'visibilityState', {
                            value: 'hidden',
                            writable: true,
                            configurable: true
                        });
                    } catch (e) {}
                }
            """)

            # Log window blur
            analytics = get_analytics()
            if analytics:
                analytics.log_window_blur()

            logger.debug("Triggered blur event")
        except Exception as e:
            logger.debug(f"Blur trigger failed (non-critical): {e}")

    async def _trigger_focus(self) -> None:
        """Trigger window focus event (simulates returning to the window)."""
        try:
            await self.page.evaluate("""
                () => {
                    // Restore visibility properties
                    try {
                        Object.defineProperty(document, 'hidden', {
                            value: false,
                            writable: true,
                            configurable: true
                        });
                        Object.defineProperty(document, 'visibilityState', {
                            value: 'visible',
                            writable: true,
                            configurable: true
                        });
                    } catch (e) {}

                    // Dispatch focus event
                    window.dispatchEvent(new Event('focus'));
                    document.dispatchEvent(new Event('visibilitychange'));
                }
            """)

            # Log window focus
            analytics = get_analytics()
            if analytics:
                analytics.log_window_focus()

            logger.debug("Triggered focus event")
        except Exception as e:
            logger.debug(f"Focus trigger failed (non-critical): {e}")

    async def _return_cursor(self) -> None:
        """Move cursor back to a natural position in the viewport."""
        viewport = self.page.viewport_size
        if not viewport:
            return

        # Return to a random position in the center-ish area
        target_x = random.uniform(viewport["width"] * 0.3, viewport["width"] * 0.7)
        target_y = random.uniform(viewport["height"] * 0.3, viewport["height"] * 0.7)

        # Slightly slower return movement
        steps = random.randint(5, 10)
        current_x = viewport["width"] + 30
        current_y = viewport["height"] + 30

        for i in range(steps):
            progress = (i + 1) / steps
            x = current_x + (target_x - current_x) * progress
            y = current_y + (target_y - current_y) * progress
            await self.page.mouse.move(x, y)
            await asyncio.sleep(random.uniform(0.03, 0.08))

        logger.debug(f"Cursor returned to ({target_x:.0f}, {target_y:.0f})")

    async def idle_with_minimal_activity(self, duration: float) -> None:
        """
        Simulate idle behavior with minimal activity.

        Unlike full distraction, this keeps focus but reduces activity
        (like user watching video passively).

        Args:
            duration: How long to idle
        """
        start_time = asyncio.get_event_loop().time()
        elapsed = 0

        while elapsed < duration:
            # Very occasional micro-movement (every 15-30 seconds)
            wait_time = random.uniform(15, 30)
            await asyncio.sleep(min(wait_time, duration - elapsed))

            elapsed = asyncio.get_event_loop().time() - start_time

            if elapsed >= duration:
                break

            # 30% chance of tiny cursor drift
            if random.random() < 0.3:
                viewport = self.page.viewport_size
                if viewport:
                    # Small drift (1-5 pixels)
                    drift_x = random.uniform(-5, 5)
                    drift_y = random.uniform(-5, 5)

                    # Get approximate current position (we don't track perfectly)
                    x = random.uniform(200, viewport["width"] - 200) + drift_x
                    y = random.uniform(200, viewport["height"] - 200) + drift_y

                    await self.page.mouse.move(x, y)
