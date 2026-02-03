"""
YouTube Ad Skipper Module

Simulates realistic human behavior when encountering ads.
Different profiles have different ad-skipping personalities.

Behavior Model:
- Sniper (60%): Cursor near button before it appears, clicks 300-600ms after
- Lazy (30%): Notices button after 1.5-4s, then moves and clicks
- Distracted (10%): Watches full ad (AFK, looking at phone, etc.)

These percentages are profile-specific (via seed).
"""

import asyncio
import random
import time
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Tuple

from playwright.async_api import Page, ElementHandle

from ..safety.logger import get_logger
from ..safety.analytics_logger import get_analytics

logger = get_logger(__name__)


class AdSkipperPersonality(Enum):
    """Ad skipping personality types."""
    SNIPER = "sniper"           # Quick skipper, cursor ready
    LAZY = "lazy"               # Slow reaction, casual
    DISTRACTED = "distracted"   # Watches full ad


@dataclass
class AdSkipperConfig:
    """Configuration for ad skipping behavior."""

    # Personality distribution (will be adjusted per profile)
    sniper_chance: float = 0.60
    lazy_chance: float = 0.30
    distracted_chance: float = 0.10

    # Sniper timing
    sniper_pre_position_time: Tuple[float, float] = (1.5, 3.0)
    sniper_click_delay: Tuple[float, float] = (0.3, 0.6)

    # Lazy timing
    lazy_notice_delay: Tuple[float, float] = (1.5, 4.0)
    lazy_move_delay: Tuple[float, float] = (0.3, 0.8)

    # Polling
    poll_interval: float = 0.5
    max_wait_for_button: float = 30.0


class AdSkipper:
    """
    Handles YouTube ad skipping with human-like behavior.

    Usage:
        skipper = AdSkipper(page, mouse, config, profile_seed)
        result = await skipper.handle_ad_if_present()
    """

    # YouTube ad selectors
    SKIP_BUTTON_SELECTORS = [
        ".ytp-ad-skip-button",
        ".ytp-ad-skip-button-modern",
        ".ytp-skip-ad-button",
        "button.ytp-ad-skip-button",
        ".ytp-ad-skip-button-slot button",
        ".ytp-ad-skip-button-container button",
    ]

    OVERLAY_CLOSE_SELECTORS = [
        ".ytp-ad-overlay-close-button",
        ".ytp-ad-overlay-close-container button",
    ]

    AD_PLAYING_SELECTORS = [
        ".ytp-ad-player-overlay",
        ".ytp-ad-text",
        ".ad-showing",
        ".ytp-ad-preview-container",
    ]

    SKIP_BUTTON_CONTAINER = ".ytp-ad-skip-button-container"

    def __init__(
        self,
        page: Page,
        mouse,  # HumanMouse instance
        config: AdSkipperConfig = None,
        profile_seed: int = None
    ):
        self.page = page
        self.mouse = mouse
        self.config = config or AdSkipperConfig()

        # Profile-specific personality distribution
        if profile_seed:
            rng = random.Random(profile_seed)

            # Adjust personality chances per profile
            self._sniper_chance = self.config.sniper_chance + rng.uniform(-0.15, 0.15)
            self._lazy_chance = self.config.lazy_chance + rng.uniform(-0.10, 0.10)
            self._distracted_chance = 1.0 - self._sniper_chance - self._lazy_chance

            # Ensure valid probabilities
            self._sniper_chance = max(0.30, min(0.80, self._sniper_chance))
            self._lazy_chance = max(0.10, min(0.50, self._lazy_chance))
            self._distracted_chance = max(0.02, min(0.25, self._distracted_chance))

            # Normalize to sum to 1
            total = self._sniper_chance + self._lazy_chance + self._distracted_chance
            self._sniper_chance /= total
            self._lazy_chance /= total
            self._distracted_chance /= total
        else:
            self._sniper_chance = self.config.sniper_chance
            self._lazy_chance = self.config.lazy_chance
            self._distracted_chance = self.config.distracted_chance

        self._personality_weights = [
            self._sniper_chance,
            self._lazy_chance,
            self._distracted_chance
        ]

        logger.debug(
            f"AdSkipper profile: sniper={self._sniper_chance:.1%}, "
            f"lazy={self._lazy_chance:.1%}, distracted={self._distracted_chance:.1%}"
        )

    def _select_personality(self) -> AdSkipperPersonality:
        """Select personality for this ad encounter."""
        return random.choices(
            [AdSkipperPersonality.SNIPER,
             AdSkipperPersonality.LAZY,
             AdSkipperPersonality.DISTRACTED],
            weights=self._personality_weights
        )[0]

    async def is_ad_playing(self) -> bool:
        """Check if an ad is currently playing."""
        for selector in self.AD_PLAYING_SELECTORS:
            try:
                element = await self.page.query_selector(selector)
                if element and await element.is_visible():
                    return True
            except Exception:
                pass
        return False

    async def find_skip_button(self) -> Optional[ElementHandle]:
        """Find visible skip button."""
        for selector in self.SKIP_BUTTON_SELECTORS:
            try:
                element = await self.page.query_selector(selector)
                if element and await element.is_visible():
                    return element
            except Exception:
                pass
        return None

    async def find_overlay_close(self) -> Optional[ElementHandle]:
        """Find overlay ad close button."""
        for selector in self.OVERLAY_CLOSE_SELECTORS:
            try:
                element = await self.page.query_selector(selector)
                if element and await element.is_visible():
                    return element
            except Exception:
                pass
        return None

    async def get_skip_button_position(self) -> Optional[Tuple[float, float]]:
        """Get expected position of skip button (even if not visible yet)."""
        try:
            container = await self.page.query_selector(self.SKIP_BUTTON_CONTAINER)
            if container:
                box = await container.bounding_box()
                if box:
                    return (
                        box["x"] + box["width"] / 2,
                        box["y"] + box["height"] / 2
                    )
        except Exception:
            pass

        # Fallback: estimate position (bottom right of video player)
        try:
            player = await self.page.query_selector(".html5-video-player")
            if player:
                box = await player.bounding_box()
                if box:
                    return (
                        box["x"] + box["width"] - 100,
                        box["y"] + box["height"] - 60
                    )
        except Exception:
            pass

        return None

    async def handle_ad_if_present(self) -> dict:
        """
        Main entry point: handle ad if one is playing.

        Returns:
            dict with action taken and timing info
        """
        if not await self.is_ad_playing():
            return {"ad_found": False}

        # Select personality for this ad
        personality = self._select_personality()
        analytics = get_analytics()

        if analytics:
            analytics.log("ad_detected", {
                "personality": personality.value,
                "sniper_chance": round(self._sniper_chance, 3),
                "lazy_chance": round(self._lazy_chance, 3),
                "distracted_chance": round(self._distracted_chance, 3)
            })

        logger.info(f"Ad detected, personality: {personality.value}")

        if personality == AdSkipperPersonality.DISTRACTED:
            return await self._handle_distracted()
        elif personality == AdSkipperPersonality.SNIPER:
            return await self._handle_sniper()
        else:
            return await self._handle_lazy()

    async def _handle_distracted(self) -> dict:
        """Watch the full ad (distracted user)."""
        start_time = time.time()

        logger.debug("Watching full ad (distracted)")

        # Wait for ad to finish
        while await self.is_ad_playing():
            await asyncio.sleep(1.0)
            if time.time() - start_time > 120:  # 2 min max
                break

        return {
            "ad_found": True,
            "action": "watched_full",
            "personality": "distracted",
            "duration_s": round(time.time() - start_time, 1)
        }

    async def _handle_sniper(self) -> dict:
        """Skip ad quickly (sniper user)."""
        start_time = time.time()

        # Pre-position cursor near expected button location
        expected_pos = await self.get_skip_button_position()
        if expected_pos:
            pre_pos_time = random.uniform(*self.config.sniper_pre_position_time)
            await asyncio.sleep(pre_pos_time * 0.3)

            # Move cursor to area (with offset, not exactly on button)
            target_x = expected_pos[0] + random.uniform(-30, 30)
            target_y = expected_pos[1] + random.uniform(-20, 20)
            await self.mouse.move_to(target_x, target_y, apply_overshoot=False)

            logger.debug(f"Sniper: pre-positioned cursor near ({target_x:.0f}, {target_y:.0f})")

        # Wait for skip button
        button = await self._wait_for_skip_button()

        if not button:
            return {
                "ad_found": True,
                "action": "no_skip_button",
                "personality": "sniper"
            }

        # Quick click after button appears
        click_delay = random.uniform(*self.config.sniper_click_delay)
        await asyncio.sleep(click_delay)

        await self._click_skip_button(button)

        return {
            "ad_found": True,
            "action": "skipped",
            "personality": "sniper",
            "reaction_ms": round(click_delay * 1000, 0),
            "total_time_s": round(time.time() - start_time, 1)
        }

    async def _handle_lazy(self) -> dict:
        """Skip ad slowly (lazy user)."""
        start_time = time.time()

        # Wait for skip button first
        button = await self._wait_for_skip_button()

        if not button:
            return {
                "ad_found": True,
                "action": "no_skip_button",
                "personality": "lazy"
            }

        # Lazy delay - takes time to notice
        notice_delay = random.uniform(*self.config.lazy_notice_delay)
        await asyncio.sleep(notice_delay)

        logger.debug(f"Lazy: noticed button after {notice_delay:.1f}s")

        # Maybe look around first
        if random.random() < 0.4:
            box = await button.bounding_box()
            if box:
                await self.mouse.move_to(
                    box["x"] + random.uniform(-50, 100),
                    box["y"] + random.uniform(-30, 30),
                    apply_overshoot=False
                )
                await asyncio.sleep(random.uniform(0.2, 0.5))

        # Additional hesitation
        move_delay = random.uniform(*self.config.lazy_move_delay)
        await asyncio.sleep(move_delay)

        await self._click_skip_button(button)

        return {
            "ad_found": True,
            "action": "skipped",
            "personality": "lazy",
            "reaction_ms": round((notice_delay + move_delay) * 1000, 0),
            "total_time_s": round(time.time() - start_time, 1)
        }

    async def _wait_for_skip_button(self, timeout: float = None) -> Optional[ElementHandle]:
        """Wait for skip button to become available."""
        timeout = timeout or self.config.max_wait_for_button
        start = time.time()

        while time.time() - start < timeout:
            button = await self.find_skip_button()
            if button:
                return button

            overlay = await self.find_overlay_close()
            if overlay:
                return overlay

            await asyncio.sleep(self.config.poll_interval)

        return None

    async def _click_skip_button(self, button: ElementHandle) -> None:
        """Click the skip button with human-like behavior."""
        box = await button.bounding_box()

        if not box:
            await button.click()
            return

        # Calculate click position with jitter
        x = box["x"] + box["width"] * random.uniform(0.3, 0.7)
        y = box["y"] + box["height"] * random.uniform(0.3, 0.7)

        # Move to button
        await self.mouse.move_to(x, y, target_width=box["width"], target_height=box["height"])

        # Click
        await self.mouse.click_at(x, y, use_overshoot=False)

        analytics = get_analytics()
        if analytics:
            analytics.log("ad_skipped", {
                "x": round(x, 1),
                "y": round(y, 1)
            })

        logger.info("Ad skipped")

    def get_personality_distribution(self) -> dict:
        """Get profile's personality distribution for logging."""
        return {
            "sniper_chance": round(self._sniper_chance, 3),
            "lazy_chance": round(self._lazy_chance, 3),
            "distracted_chance": round(self._distracted_chance, 3)
        }
