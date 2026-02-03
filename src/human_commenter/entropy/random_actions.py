"""
Random Entropy Actions

Adds unpredictable "meaningless" actions to browsing behavior.
Real humans occasionally:
- Click on unrelated things
- Visit home page
- Check shorts briefly
- Search for something and abandon it
"""

import asyncio
import random
from enum import Enum
from typing import List, Optional, Tuple

from playwright.async_api import Page

from ..biometrics import HumanMouse, HumanScroll, HumanKeyboard, GaussianDelay
from ..youtube.selectors import YouTubeSelectors
from ..config import CommenterConfig
from ..safety.logger import get_logger
from ..safety.analytics_logger import get_analytics, EventType
from ..safety.watch_history import get_watch_history

logger = get_logger(__name__)


class EntropyActionType(Enum):
    """Types of random actions"""
    VISIT_HOME = "visit_home"
    VISIT_SHORTS = "visit_shorts"
    SEARCH_ABANDON = "search_abandon"
    HOVER_THUMBNAIL = "hover_thumbnail"
    CHECK_SUBSCRIPTIONS = "check_subscriptions"


class EntropyActions:
    """
    Performs random "human" actions to add behavioral entropy.

    Real humans don't follow perfectly linear paths. They:
    - Get distracted
    - Click on things out of curiosity
    - Start searches and abandon them
    - Browse aimlessly before returning to task
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

        # Per-profile like chance (varies by personality seed)
        # Base: 25%, varied ±40% -> range ~15% to ~35%
        self._like_chance = self._calculate_profile_like_chance()

    def _calculate_profile_like_chance(self) -> float:
        """
        Calculate like chance based on profile personality.

        Different profiles have different "liking" behavior:
        - Some users like frequently (35%)
        - Some rarely like anything (15%)
        - This prevents the pattern of "all accounts like every 3rd short"
        """
        import hashlib

        # Use profile_id from config if available
        profile_id = getattr(self.config, '_profile_id', None)
        if profile_id:
            # Create deterministic but varied chance per profile
            seed = int(hashlib.md5(f"{profile_id}_like".encode()).hexdigest()[:8], 16)
            import random as rnd
            gen = rnd.Random(seed)
            # Base 25%, vary by ±40% -> range 15% to 35%
            return 0.25 * (1.0 + gen.uniform(-0.4, 0.4))
        else:
            # No profile set, use random base
            return random.uniform(0.15, 0.35)

    async def maybe_do_random_action(
        self,
        keywords: Optional[List[str]] = None
    ) -> bool:
        """
        Maybe perform a random action based on configured chance.

        Args:
            keywords: Optional keywords for search actions

        Returns:
            True if an action was performed
        """
        if random.random() > self.config.workflow.entropy_chance:
            return False

        # Choose random action
        action = random.choice(list(EntropyActionType))
        logger.debug(f"Performing entropy action: {action.value}")

        try:
            if action == EntropyActionType.VISIT_HOME:
                await self._visit_home()
            elif action == EntropyActionType.VISIT_SHORTS:
                await self._visit_shorts()
            elif action == EntropyActionType.SEARCH_ABANDON:
                await self._search_and_abandon(keywords)
            elif action == EntropyActionType.HOVER_THUMBNAIL:
                await self._hover_random_thumbnail()
            elif action == EntropyActionType.CHECK_SUBSCRIPTIONS:
                await self._check_subscriptions()

            return True

        except Exception as e:
            logger.warning(f"Entropy action failed: {e}")
            return False

    async def _visit_home(self) -> None:
        """
        Click YouTube logo to go home, browse briefly, then return.
        """
        logger.debug("Entropy: Visiting home page")

        # Remember current URL
        original_url = self.page.url

        # Click logo
        await self.mouse.click_element(self._selectors.YOUTUBE_LOGO)
        await asyncio.sleep(1.0)

        # Wait for home to load
        await self.page.wait_for_load_state("networkidle", timeout=10000)

        # Browse briefly (3-8 seconds)
        browse_time = random.uniform(3, 8)
        await self._browse_page(browse_time)

        # Go back
        await self.page.goto(original_url)
        await self.page.wait_for_load_state("networkidle", timeout=10000)

    async def _visit_shorts(self) -> None:
        """
        Visit Shorts tab briefly, watch one short partially.
        """
        logger.debug("Entropy: Visiting Shorts")

        # Remember current URL
        original_url = self.page.url

        # Click Shorts button or navigate directly
        shorts_clicked = await self.mouse.click_element(self._selectors.SHORTS_BUTTON)

        if not shorts_clicked:
            await self.page.goto("https://www.youtube.com/shorts")

        await self.page.wait_for_load_state("networkidle", timeout=10000)

        # Watch briefly (10-20 seconds)
        watch_time = random.uniform(10, 20)
        await asyncio.sleep(watch_time)

        # Maybe scroll to next short
        if random.random() < 0.5:
            await self.scroll.scroll_down(pixels=500)
            await asyncio.sleep(random.uniform(3, 8))

        # Go back
        await self.page.goto(original_url)
        await self.page.wait_for_load_state("networkidle", timeout=10000)

    async def _search_and_abandon(self, keywords: Optional[List[str]] = None) -> None:
        """
        Start typing a search, then abandon it.
        """
        logger.debug("Entropy: Abandoned search")

        if not keywords:
            keywords = ["relaxing", "music", "tutorial", "review", "funny"]

        keyword = random.choice(keywords)

        # Focus search box
        search_box = await self.page.query_selector(self._selectors.SEARCH_BOX)
        if not search_box:
            return

        box = await search_box.bounding_box()
        if not box:
            return

        await self.mouse.click_at(
            box["x"] + box["width"] / 2,
            box["y"] + box["height"] / 2
        )

        # Type partial search (not full keyword)
        partial_length = random.randint(2, min(len(keyword), 5))
        partial_keyword = keyword[:partial_length]

        await self.keyboard.type_text(partial_keyword)

        # Pause as if thinking
        await asyncio.sleep(random.uniform(0.5, 1.5))

        # Abandon: press Escape or click elsewhere
        if random.random() < 0.5:
            await self.page.keyboard.press("Escape")
        else:
            await self.mouse.click_at(
                random.uniform(200, 600),
                random.uniform(300, 500)
            )

        await asyncio.sleep(0.5)

    async def _hover_random_thumbnail(self) -> None:
        """
        Hover over a random video thumbnail on the page.
        """
        logger.debug("Entropy: Hovering thumbnail")

        # Find thumbnails
        thumbnails = await self.page.query_selector_all("ytd-thumbnail")

        if not thumbnails:
            return

        # Pick random thumbnail
        thumbnail = random.choice(thumbnails[:10])  # Limit to visible ones
        box = await thumbnail.bounding_box()

        if not box:
            return

        # Hover with tremor (as if considering clicking)
        await self.mouse.hover_with_tremor(
            box["x"] + box["width"] / 2,
            box["y"] + box["height"] / 2,
            duration=random.uniform(1, 3)
        )

    async def _check_subscriptions(self) -> None:
        """
        Click subscriptions, browse briefly, return.
        """
        logger.debug("Entropy: Checking subscriptions")

        original_url = self.page.url

        # Click subscriptions
        clicked = await self.mouse.click_element(self._selectors.SUBSCRIPTIONS_BUTTON)

        if not clicked:
            await self.page.goto("https://www.youtube.com/feed/subscriptions")

        await self.page.wait_for_load_state("networkidle", timeout=10000)

        # Browse briefly
        await self._browse_page(random.uniform(5, 12))

        # Return
        await self.page.goto(original_url)
        await self.page.wait_for_load_state("networkidle", timeout=10000)

    async def _browse_page(self, duration: float) -> None:
        """
        Simulate brief browsing behavior.

        Args:
            duration: How long to browse in seconds
        """
        start = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start < duration:
            # Random action
            action = random.choice(["scroll", "hover", "wait"])

            if action == "scroll":
                await self.scroll.scroll_down(pixels=random.randint(100, 300))
            elif action == "hover":
                viewport = self.page.viewport_size
                if viewport:
                    await self.mouse.hover_with_tremor(
                        random.uniform(100, viewport["width"] - 100),
                        random.uniform(100, viewport["height"] - 100),
                        duration=0.5
                    )
            else:
                await asyncio.sleep(random.uniform(0.5, 1.5))

            await asyncio.sleep(0.5)

    async def organic_exit_wandering(self) -> Tuple[bool, int]:
        """
        Organic exit workflow - surf Shorts before closing.

        Aggressive Shorts surfing for better cookie diversity:
        1. Navigate to Shorts
        2. Surf through 4-8 Shorts (watch ~1 loop each)
        3. Maybe like one Short (personality-based chance)
        4. Return after organic browsing

        Returns:
            Tuple of (success, number of shorts watched)
        """
        analytics = get_analytics()
        logger.info("Starting organic exit wandering (Shorts Surfing)")

        shorts_watched = 0
        liked_one = False
        target_shorts = random.randint(4, 8)  # More Shorts for better diversity
        scroll_methods_used = []

        # DEBUG: Log method entry
        if analytics:
            analytics.log(EventType.SHORTS_SURF_DEBUG, {
                "action": "organic_exit_start",
                "target_shorts": target_shorts,
                "like_chance": round(self._like_chance, 3)
            })

        try:
            # Navigate to Shorts
            shorts_clicked = await self.mouse.click_element(self._selectors.SHORTS_BUTTON)
            if not shorts_clicked:
                await self.page.goto("https://www.youtube.com/shorts")

            await self.page.wait_for_load_state("networkidle", timeout=15000)
            await asyncio.sleep(random.uniform(1.5, 3.0))

            current_url = self.page.url
            if analytics:
                analytics.log(EventType.SHORTS_SURF_START, {
                    "url": current_url[:100],
                    "target_shorts": target_shorts
                })

            # Surf through Shorts
            for i in range(target_shorts):
                logger.debug(f"Surfing Short {i + 1}/{target_shorts}")

                # Get actual Short duration
                short_duration = await self._get_short_duration()

                # ULTRA-AGGRESSIVE LOOP LIMITS
                # Most people scroll BEFORE video ends or right at end
                if short_duration <= 15:
                    # Short videos (5-15s): 0.5-0.9 loops
                    max_loops = random.uniform(0.5, 0.9)
                elif short_duration <= 30:
                    # Medium videos (15-30s): 0.4-0.8 loops
                    max_loops = random.uniform(0.4, 0.8)
                else:
                    # Long videos (30s+): 0.2-0.6 loops
                    max_loops = random.uniform(0.2, 0.6)

                # Calculate watch time
                watch_time = short_duration * max_loops
                watch_time *= random.uniform(0.95, 1.05)  # Small variance (±5%)

                # Absolute bounds
                # Min: at least 2s
                # Max: NEVER more than 1.0x video length
                min_watch = 2.0
                max_watch = short_duration * 1.0  # Hard cap at 1 loop
                watch_time = max(min_watch, min(watch_time, max_watch))

                # LOG PLANNED WATCH TIME (before watching)
                if analytics:
                    analytics.log(EventType.SHORTS_WATCHING, {
                        "short_number": i + 1,
                        "video_duration": round(short_duration, 1),
                        "planned_watch_time": round(watch_time, 1),
                        "max_loops": round(max_loops, 2),
                        "planned_loops": round(watch_time / short_duration, 2) if short_duration > 0 else 1
                    })

                await self._watch_current_short(watch_time)
                shorts_watched += 1

                actual_loops = watch_time / short_duration if short_duration > 0 else 1

                # Mark Short as watched (for dedup)
                current_url = self.page.url
                video_hash = None
                try:
                    watch_history = get_watch_history()
                    profile_id = getattr(self.config, '_profile_id', 'unknown')
                    video_hash = watch_history.mark_watched(profile_id, current_url)
                except Exception as e:
                    logger.debug(f"Failed to mark Short as watched: {e}")

                # DEBUG: Log each Short watched
                if analytics:
                    analytics.log(EventType.SHORTS_WATCHED_ONE, {
                        "short_number": shorts_watched,
                        "watch_duration": round(watch_time, 1),
                        "video_duration": round(short_duration, 1),
                        "max_loops": round(max_loops, 2),
                        "actual_loops": round(actual_loops, 2),
                        "video_hash": video_hash
                    })

                # Maybe like this Short (only once per session)
                if not liked_one and random.random() < self._like_chance:
                    if await self._like_current_short():
                        liked_one = True
                        logger.debug(f"Liked a Short (profile like_chance: {self._like_chance:.1%})")

                # Scroll to next Short
                if i < target_shorts - 1:
                    scroll_result = await self._scroll_to_next_short()
                    scroll_methods_used.append(scroll_result.get("method", "unknown"))
                    await asyncio.sleep(random.uniform(0.5, 1.2))

            # DEBUG: Log completion
            if analytics:
                analytics.log(EventType.SHORTS_SURF_END, {
                    "shorts_watched": shorts_watched,
                    "liked": liked_one,
                    "scroll_methods_used": scroll_methods_used
                })

            logger.info(f"Shorts surfing complete: watched {shorts_watched} Shorts, liked={liked_one}")
            return (True, shorts_watched)

        except Exception as e:
            if analytics:
                analytics.log(EventType.SHORTS_ERROR, {
                    "error": str(e),
                    "shorts_watched": shorts_watched
                })
            logger.warning(f"Organic exit wandering error: {e}")
            return (False, shorts_watched)

    async def _get_short_duration(self) -> float:
        """Get duration of current Short video."""
        try:
            duration = await self.page.evaluate("""
                () => {
                    const video = document.querySelector(
                        'div#shorts-player video, ytd-shorts video, video'
                    );
                    if (video && video.duration && !isNaN(video.duration)) {
                        return video.duration;
                    }
                    return null;
                }
            """)
            if duration and 5 < duration < 180:
                return duration
        except Exception:
            pass
        # Fallback estimate
        return random.uniform(15, 35)

    async def _watch_current_short(self, duration: float) -> None:
        """
        Watch the current short with occasional micro-interactions.

        Includes check for paused/frozen state to avoid "Shorts coma".

        Args:
            duration: How long to watch in seconds
        """
        analytics = get_analytics()
        start_time = asyncio.get_event_loop().time()
        elapsed = 0
        last_check_time = 0  # Track video currentTime to detect frozen state

        while elapsed < duration:
            # CRITICAL: Check if video is actually playing (not paused/frozen)
            video_state = await self.page.evaluate("""
                () => {
                    const video = document.querySelector('div#shorts-player video, ytd-shorts video, video');
                    if (!video) return null;
                    return {
                        paused: video.paused,
                        readyState: video.readyState,
                        currentTime: video.currentTime,
                        duration: video.duration || 0
                    };
                }
            """)

            if video_state:
                # DEBUG: Log video state (first check only to avoid spam)
                if elapsed < 1 and analytics:
                    analytics.log(EventType.SHORTS_VIDEO_STATE, {
                        "paused": video_state.get("paused"),
                        "readyState": video_state.get("readyState"),
                        "currentTime": round(video_state.get("currentTime", 0), 1),
                        "duration": round(video_state.get("duration", 0), 1)
                    })

                # Check if paused or frozen (same currentTime as last check)
                is_paused = video_state.get("paused", True)
                current_time = video_state.get("currentTime", 0)

                # Detect frozen state (currentTime hasn't changed in 5+ seconds)
                is_frozen = (elapsed > 5 and abs(current_time - last_check_time) < 0.1)

                if is_paused or is_frozen:
                    logger.debug(f"Shorts video paused/frozen, clicking to play")

                    # DEBUG: Log paused detection
                    if analytics:
                        analytics.log(EventType.SHORTS_PAUSED_DETECTED, {
                            "is_paused": is_paused,
                            "is_frozen": is_frozen,
                            "elapsed": round(elapsed, 1)
                        })

                    # Click center of viewport to resume
                    viewport = self.page.viewport_size
                    if viewport:
                        center_x = viewport["width"] / 2 + random.uniform(-30, 30)
                        center_y = viewport["height"] / 2 + random.uniform(-50, 50)
                        await asyncio.sleep(random.uniform(0.3, 0.8))
                        await self.mouse.move_to(center_x, center_y)
                        await self.page.mouse.click(center_x, center_y)
                        await asyncio.sleep(random.uniform(0.5, 1.0))

                        if analytics:
                            analytics.log(EventType.SHORTS_PLAY_CLICKED, {
                                "was_paused": is_paused,
                                "was_frozen": is_frozen
                            })

                last_check_time = current_time

            # Wait interval
            wait_interval = random.uniform(3, 8)  # Shorter intervals for better monitoring
            await asyncio.sleep(min(wait_interval, duration - elapsed))

            elapsed = asyncio.get_event_loop().time() - start_time

            if elapsed >= duration:
                break

            # Occasional micro-action
            action = random.choice(["hover", "tremor", "nothing", "nothing"])

            if action == "hover":
                viewport = self.page.viewport_size
                if viewport:
                    # Hover near the video
                    x = random.uniform(viewport["width"] * 0.3, viewport["width"] * 0.7)
                    y = random.uniform(viewport["height"] * 0.3, viewport["height"] * 0.7)
                    await self.mouse.hover_with_tremor(x, y, duration=random.uniform(0.3, 0.8))

            elif action == "tremor":
                pos = await self.mouse.get_current_position()
                await self.mouse.hover_with_tremor(pos.x, pos.y, duration=random.uniform(0.2, 0.5))

    async def _like_current_short(self) -> bool:
        """
        Like the current short video.

        Returns:
            True if liked successfully
        """
        try:
            # Find like button in Shorts player
            like_selectors = [
                "#like-button button",
                "ytd-toggle-button-renderer#like-button",
                "[aria-label*='like']",
                "#actions button:first-child",
            ]

            like_button = None
            for selector in like_selectors:
                like_button = await self.page.query_selector(selector)
                if like_button:
                    is_visible = await like_button.is_visible()
                    if is_visible:
                        break
                    like_button = None

            if not like_button:
                return False

            # Check if already liked
            aria_pressed = await like_button.get_attribute("aria-pressed")
            if aria_pressed == "true":
                return False  # Already liked

            # Click like
            box = await like_button.bounding_box()
            if box:
                await self.mouse.click_at(
                    box["x"] + box["width"] / 2,
                    box["y"] + box["height"] / 2
                )
                await asyncio.sleep(random.uniform(0.3, 0.7))
                return True

            return False

        except Exception as e:
            logger.debug(f"Like short failed: {e}")
            return False

    async def _scroll_to_next_short(self) -> dict:
        """
        Scroll to the next short video.

        Uses only FAST methods:
        - arrow_down: instant keyboard navigation (most reliable)
        - swipe: quick touch-like gesture

        scroll_wheel REMOVED: takes 5-7s vs 2-3s for arrow_down

        Returns:
            dict with method used and success status
        """
        analytics = get_analytics()
        result = {"method": None, "success": False}

        try:
            viewport = self.page.viewport_size

            # Choose scroll method (scroll_wheel REMOVED - too slow)
            # arrow_down: 70%, swipe: 30%
            methods = ["arrow_down", "swipe"]
            weights = [70, 30]
            method = random.choices(methods, weights=weights, k=1)[0]
            result["method"] = method

            # DEBUG: Log before attempting scroll
            if analytics:
                analytics.log(EventType.SHORTS_NEXT_ATTEMPT, {
                    "method": method
                })

            if method == "arrow_down":
                # KEYBOARD METHOD - Most reliable, instant transition
                await self.page.keyboard.press("ArrowDown")
                result["success"] = True
                logger.debug("ArrowDown pressed for next Short")

            elif method == "swipe":
                # SWIPE GESTURE - Quick touch-like movement
                if viewport:
                    start_y = viewport["height"] * 0.75
                    end_y = viewport["height"] * 0.15
                    center_x = viewport["width"] / 2 + random.uniform(-20, 20)

                    # Move to start position
                    await self.page.mouse.move(center_x, start_y)
                    await asyncio.sleep(0.03)

                    # Mouse down (start drag)
                    await self.page.mouse.down()

                    # Swipe up (quick) with ease-out
                    steps = random.randint(6, 10)
                    for i in range(steps):
                        progress = (i + 1) / steps
                        eased_progress = 1 - (1 - progress) ** 2
                        current_y = start_y + (end_y - start_y) * eased_progress
                        await self.page.mouse.move(center_x, current_y)
                        await asyncio.sleep(random.uniform(0.008, 0.015))

                    # Mouse up (release)
                    await self.page.mouse.up()
                    result["success"] = True
                    logger.debug("Swipe completed for next Short")
                else:
                    # Fallback to arrow_down if no viewport
                    await self.page.keyboard.press("ArrowDown")
                    result["method"] = "arrow_down_fallback"
                    result["success"] = True
                    logger.debug("ArrowDown fallback (no viewport)")

            # Brief wait for transition
            await asyncio.sleep(random.uniform(0.3, 0.6))

            # Wait for new short to load
            await asyncio.sleep(random.uniform(1.2, 2.0))

            # DEBUG: Log success
            if analytics:
                analytics.log(EventType.SHORTS_NEXT, {
                    "method": result["method"],
                    "success": result["success"]
                })

        except Exception as e:
            result["success"] = False
            result["error"] = str(e)
            if analytics:
                analytics.log(EventType.SHORTS_SCROLL_ERROR, {
                    "method": result["method"],
                    "error": str(e)
                })
            logger.debug(f"Scroll to next short failed: {e}")

        return result

    async def clean_exit(self) -> None:
        """
        Perform a clean session exit.

        1. Close current YouTube tab (navigate to about:blank)
        2. Wait 5-10 seconds
        3. Ready for session close

        This ensures the next session doesn't start on a YouTube page
        with potentially incorrect settings.
        """
        logger.info("Performing clean exit")

        try:
            # Step 1: Navigate to blank page
            await self.page.goto("about:blank")

            # Step 2: Wait on blank page (5-10 seconds)
            wait_time = random.uniform(5, 10)
            logger.debug(f"Waiting {wait_time:.1f}s on blank page before close")
            await asyncio.sleep(wait_time)

            logger.info("Clean exit complete, ready for session close")

        except Exception as e:
            logger.warning(f"Clean exit error: {e}")
