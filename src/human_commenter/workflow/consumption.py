"""
Consumption Phase

Simulates watching the video for 45-120 seconds before commenting.
Includes human-like behaviors like volume adjustments and hovering.
"""

import asyncio
import random
from typing import Optional

from playwright.async_api import Page

from ..biometrics import HumanMouse, HumanScroll, GaussianDelay
from ..youtube.video_player import VideoPlayer
from ..youtube.popup_handler import PopupHandler
from ..youtube.selectors import YouTubeSelectors
from ..config import CommenterConfig
from ..safety.logger import get_logger

logger = get_logger(__name__)


class ConsumptionPhase:
    """
    Handles the video consumption phase of the workflow.

    Before commenting, a human would watch part of the video.
    This phase simulates that behavior.
    """

    def __init__(
        self,
        page: Page,
        mouse: HumanMouse,
        scroll: HumanScroll,
        player: VideoPlayer,
        popup_handler: PopupHandler,
        config: CommenterConfig
    ):
        self.page = page
        self.mouse = mouse
        self.scroll = scroll
        self.player = player
        self.popup_handler = popup_handler
        self.config = config
        self._selectors = YouTubeSelectors()

    async def execute(self, video_id: str) -> bool:
        """
        Execute the consumption phase.

        Args:
            video_id: YouTube video ID

        Returns:
            True if phase completed successfully
        """
        logger.info("Starting consumption phase")

        try:
            # Navigate to video
            video_url = self._selectors.video_url(video_id)
            await self.page.goto(video_url)

            # Wait for page load
            await GaussianDelay.from_config(self.config.delay_page_load).wait()

            # Dismiss any popups
            await self.popup_handler.dismiss_all()

            # Wait for video element
            if not await self.player.wait_for_video_element(timeout=15.0):
                logger.error("Video element not found")
                return False

            # Ensure video is playing
            await asyncio.sleep(1.0)  # Brief pause for autoplay
            if not await self.player.is_playing():
                await self.player.play()

            # Dismiss any remaining popups
            await self.popup_handler.dismiss_all()

            # Calculate watch duration
            min_duration = self.config.workflow.consumption_duration_min
            max_duration = self.config.workflow.consumption_duration_max
            watch_duration = random.uniform(min_duration, max_duration)

            logger.info(f"Watching video for {watch_duration:.1f}s")

            # Watch with human behaviors
            await self._watch_with_behaviors(watch_duration)

            logger.info("Consumption phase complete")
            return True

        except Exception as e:
            logger.error(f"Consumption phase failed: {e}")
            return False

    async def _watch_with_behaviors(self, duration: float) -> None:
        """
        Watch video with occasional human-like behaviors.

        Args:
            duration: How long to watch in seconds
        """
        start_time = asyncio.get_event_loop().time()
        elapsed = 0

        # Plan some random behaviors
        behavior_times = self._plan_behaviors(duration)

        while elapsed < duration:
            # Check for planned behaviors
            for behavior, planned_time in behavior_times:
                if elapsed >= planned_time and planned_time > 0:
                    await self._do_behavior(behavior)
                    behavior_times.remove((behavior, planned_time))

            # Small sleep
            await asyncio.sleep(1.0)
            elapsed = asyncio.get_event_loop().time() - start_time

            # Verify video still playing
            if not await self.player.is_playing():
                state = await self.player.get_state()
                if state.value == "ended":
                    break
                elif state.value == "paused":
                    await self.player.play()

    def _plan_behaviors(self, duration: float) -> list:
        """
        Plan random behaviors throughout the watch period.

        Returns list of (behavior_name, time_to_execute) tuples.
        """
        behaviors = []

        # Volume adjustment (1-2 times)
        num_volume = random.randint(1, 2)
        for _ in range(num_volume):
            behaviors.append(("volume", random.uniform(5, duration - 5)))

        # Hover over player (0-2 times)
        if random.random() < 0.5:
            behaviors.append(("hover_player", random.uniform(10, duration - 10)))

        # Look at description (30% chance)
        if random.random() < 0.3:
            behaviors.append(("check_description", random.uniform(15, duration - 10)))

        # Small scroll (20% chance)
        if random.random() < 0.2:
            behaviors.append(("small_scroll", random.uniform(20, duration - 5)))

        return behaviors

    async def _do_behavior(self, behavior: str) -> None:
        """Execute a specific behavior"""
        logger.debug(f"Doing behavior: {behavior}")

        try:
            if behavior == "volume":
                await self._adjust_volume()
            elif behavior == "hover_player":
                await self._hover_player()
            elif behavior == "check_description":
                await self._check_description()
            elif behavior == "small_scroll":
                await self._small_scroll()
        except Exception as e:
            logger.debug(f"Behavior {behavior} failed: {e}")

    async def _adjust_volume(self) -> None:
        """Make a small volume adjustment"""
        current = await self.player.get_volume()
        change = random.uniform(-0.15, 0.15)
        new_vol = max(0.2, min(1.0, current + change))
        await self.player.set_volume(new_vol)

    async def _hover_player(self) -> None:
        """Hover over video player briefly"""
        viewport = await self.page.viewport_size
        if viewport:
            # Hover over center-ish of player area
            x = viewport["width"] / 2 + random.uniform(-100, 100)
            y = 300 + random.uniform(-50, 50)
            await self.mouse.hover_with_tremor(x, y, duration=random.uniform(0.5, 1.5))

    async def _check_description(self) -> None:
        """Scroll down to glance at description"""
        await self.scroll.scroll_down(pixels=random.randint(100, 200))
        await asyncio.sleep(random.uniform(2, 4))
        await self.scroll.scroll_up(pixels=random.randint(100, 200))

    async def _small_scroll(self) -> None:
        """Small random scroll"""
        direction = random.choice(["down", "up"])
        pixels = random.randint(50, 150)

        if direction == "down":
            await self.scroll.scroll_down(pixels=pixels)
        else:
            await self.scroll.scroll_up(pixels=pixels)

        await asyncio.sleep(random.uniform(0.5, 1.0))
