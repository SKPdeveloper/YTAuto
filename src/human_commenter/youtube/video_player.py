"""
YouTube Video Player Controller

Controls video playback state and interactions:
- Play/pause verification
- Volume control
- Quality settings
- Progress monitoring
- Ad detection and skipping
- Shorts handling
"""

import asyncio
import random
import time
from typing import Optional, Tuple, List
from enum import Enum

from playwright.async_api import Page

from .selectors import YouTubeSelectors
from ..biometrics import HumanMouse, GaussianDelay
from ..config import CommenterConfig
from ..safety.logger import get_logger
from ..safety.analytics_logger import get_analytics, EventType
from ..safety.watch_history import get_watch_history

logger = get_logger(__name__)


class PlayerState(Enum):
    """Video player states"""
    UNKNOWN = "unknown"
    PLAYING = "playing"
    PAUSED = "paused"
    BUFFERING = "buffering"
    ENDED = "ended"
    ERROR = "error"


class VideoPlayer:
    """
    Controls YouTube video player interactions.

    Provides human-like control over video playback including
    play/pause, volume adjustment, quality changes, ad skipping,
    and Shorts handling.
    """

    def __init__(
        self,
        page: Page,
        mouse: HumanMouse,
        config: CommenterConfig,
        profile_seed: int = None
    ):
        self.page = page
        self.mouse = mouse
        self.config = config
        self._selectors = YouTubeSelectors()

        # Profile-specific randomization
        if profile_seed:
            rng = random.Random(profile_seed)
        else:
            rng = random.Random()

        # Ad skipping personality distribution (varies per profile)
        base_sniper = 0.60 + rng.uniform(-0.15, 0.15)   # 45-75%
        base_lazy = 0.30 + rng.uniform(-0.10, 0.10)     # 20-40%
        base_distracted = 1.0 - base_sniper - base_lazy # Remainder

        # Ensure valid (positive) probabilities
        base_distracted = max(0.02, min(0.25, base_distracted))

        # Normalize
        total = base_sniper + base_lazy + base_distracted
        self._ad_personality_weights = {
            "sniper": base_sniper / total,
            "lazy": base_lazy / total,
            "distracted": base_distracted / total
        }

        # Shorts Surfing Mode parameters (profile-specific)

        # Rewatch chance: rare behavior (most people don't rewatch)
        # Range: 8-15% (was 15-45%)
        self._shorts_rewatch_chance = rng.uniform(0.08, 0.15)

        # Watch duration multiplier: some users watch full Short, some skip early
        # Range: 0.6-1.1 (60%-110% of Short duration)
        self._shorts_watch_multiplier_base = rng.uniform(0.6, 1.1)

        # Scroll method preference (profile-specific)
        # scroll_wheel REMOVED: too slow (5-7s vs 2-3s for arrow_down)
        self._shorts_scroll_weights = {
            "arrow_down": 60 + rng.randint(-15, 15),   # 45-75 (primary)
            "swipe": 40 + rng.randint(-15, 15)         # 25-55 (secondary)
        }

        # Patience level: affects max loops per Short
        # Minimal variance - most people behave similarly
        # Range: 0.9-1.1 multiplier (very narrow)
        self._shorts_patience = rng.uniform(0.9, 1.1)

        # Log profile characteristics
        analytics = get_analytics()
        if analytics:
            analytics.log(EventType.VIDEO_PLAYER_PROFILE, {
                "ad_personality_weights": {
                    k: round(v, 3) for k, v in self._ad_personality_weights.items()
                },
                "shorts_rewatch_chance": round(self._shorts_rewatch_chance, 3),
                "shorts_watch_multiplier": round(self._shorts_watch_multiplier_base, 3),
                "shorts_scroll_weights": self._shorts_scroll_weights,
                "shorts_patience": round(self._shorts_patience, 3)
            })

        logger.debug(
            f"VideoPlayer profile: ad_weights={self._ad_personality_weights}, "
            f"shorts_rewatch={self._shorts_rewatch_chance:.1%}, "
            f"shorts_watch_mult={self._shorts_watch_multiplier_base:.2f}, "
            f"shorts_patience={self._shorts_patience:.2f}"
        )

    async def get_state(self) -> PlayerState:
        """
        Get current player state.

        Returns:
            PlayerState enum value
        """
        try:
            state = await self.page.evaluate("""
                () => {
                    const video = document.querySelector('video.html5-main-video');
                    if (!video) return 'unknown';
                    if (video.error) return 'error';
                    if (video.ended) return 'ended';
                    if (video.paused) return 'paused';
                    if (video.readyState < 3) return 'buffering';
                    return 'playing';
                }
            """)
            return PlayerState(state)
        except Exception:
            return PlayerState.UNKNOWN

    async def is_playing(self) -> bool:
        """Check if video is currently playing"""
        state = await self.get_state()
        return state == PlayerState.PLAYING

    async def wait_for_playing(self, timeout: float = 10.0) -> bool:
        """
        Wait for video to start playing.

        Args:
            timeout: Maximum wait time in seconds

        Returns:
            True if video started playing
        """
        start = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start < timeout:
            if await self.is_playing():
                return True
            await asyncio.sleep(0.5)

        return False

    async def play(self) -> bool:
        """
        Start video playback.

        Returns:
            True if video is now playing
        """
        if await self.is_playing():
            return True

        # Click play button with human-like behavior
        clicked = await self.mouse.click_element(self._selectors.PLAY_BUTTON)

        if clicked:
            await asyncio.sleep(0.5)

        return await self.wait_for_playing(timeout=5.0)

    async def pause(self) -> bool:
        """
        Pause video playback.

        Returns:
            True if video is now paused
        """
        if not await self.is_playing():
            return True

        await self.mouse.click_element(self._selectors.PLAY_BUTTON)
        await asyncio.sleep(0.5)

        return not await self.is_playing()

    async def toggle_play(self) -> PlayerState:
        """
        Toggle play/pause state.

        Returns:
            New player state
        """
        await self.mouse.click_element(self._selectors.PLAY_BUTTON)
        await asyncio.sleep(0.5)
        return await self.get_state()

    async def get_current_time(self) -> float:
        """Get current playback position in seconds"""
        try:
            return await self.page.evaluate("""
                () => {
                    const video = document.querySelector('video.html5-main-video');
                    return video ? video.currentTime : 0;
                }
            """)
        except Exception:
            return 0

    async def get_duration(self) -> float:
        """Get video duration in seconds"""
        try:
            return await self.page.evaluate("""
                () => {
                    const video = document.querySelector('video.html5-main-video');
                    return video ? video.duration : 0;
                }
            """)
        except Exception:
            return 0

    async def get_progress(self) -> Tuple[float, float]:
        """
        Get current time and duration.

        Returns:
            Tuple of (current_time, duration) in seconds
        """
        return (await self.get_current_time(), await self.get_duration())

    async def seek_to(self, seconds: float) -> bool:
        """
        Seek to specific position.

        Args:
            seconds: Target position in seconds

        Returns:
            True if seek was successful
        """
        try:
            await self.page.evaluate(f"""
                () => {{
                    const video = document.querySelector('video.html5-main-video');
                    if (video) video.currentTime = {seconds};
                }}
            """)
            return True
        except Exception as e:
            logger.warning(f"Seek failed: {e}")
            return False

    async def get_volume(self) -> float:
        """Get current volume (0.0 to 1.0)"""
        try:
            return await self.page.evaluate("""
                () => {
                    const video = document.querySelector('video.html5-main-video');
                    return video ? video.volume : 1.0;
                }
            """)
        except Exception:
            return 1.0

    async def set_volume(self, volume: float) -> None:
        """
        Set video volume.

        Args:
            volume: Volume level (0.0 to 1.0)
        """
        volume = max(0.0, min(1.0, volume))

        try:
            await self.page.evaluate(f"""
                () => {{
                    const video = document.querySelector('video.html5-main-video');
                    if (video) video.volume = {volume};
                }}
            """)
            logger.debug(f"Set volume to {volume:.2f}")
        except Exception as e:
            logger.warning(f"Failed to set volume: {e}")

    async def is_muted(self) -> bool:
        """Check if video is muted"""
        try:
            return await self.page.evaluate("""
                () => {
                    const video = document.querySelector('video.html5-main-video');
                    return video ? video.muted : false;
                }
            """)
        except Exception:
            return False

    async def mute(self) -> None:
        """Mute video"""
        if not await self.is_muted():
            await self.mouse.click_element(self._selectors.MUTE_BUTTON)

    async def unmute(self) -> None:
        """Unmute video"""
        if await self.is_muted():
            await self.mouse.click_element(self._selectors.MUTE_BUTTON)

    async def change_quality(self, quality: str = "auto") -> bool:
        """
        Change video quality.

        Args:
            quality: Quality setting (e.g., "1080p", "720p", "auto")

        Returns:
            True if quality was changed
        """
        try:
            # Click settings button
            await self.mouse.click_element(self._selectors.SETTINGS_BUTTON)
            await asyncio.sleep(0.3)

            # Click quality option
            quality_button = await self.page.query_selector("text='Quality'")
            if quality_button:
                box = await quality_button.bounding_box()
                if box:
                    await self.mouse.click_at(
                        box["x"] + box["width"] / 2,
                        box["y"] + box["height"] / 2
                    )
                    await asyncio.sleep(0.3)

                    # Select quality
                    quality_option = await self.page.query_selector(f"text='{quality}'")
                    if quality_option:
                        box = await quality_option.bounding_box()
                        if box:
                            await self.mouse.click_at(
                                box["x"] + box["width"] / 2,
                                box["y"] + box["height"] / 2
                            )
                            return True

            # Close settings if open
            await self.page.keyboard.press("Escape")
            return False

        except Exception as e:
            logger.warning(f"Failed to change quality: {e}")
            return False

    async def random_volume_adjustment(self) -> None:
        """
        Make a random small volume adjustment (human behavior).

        Simulates humans occasionally adjusting volume while watching.
        """
        current = await self.get_volume()
        change = random.uniform(-0.1, 0.1)
        new_volume = max(0.2, min(1.0, current + change))
        await self.set_volume(new_volume)

    async def watch_for_duration(self, seconds: float) -> float:
        """
        Watch video for specified duration.

        Occasionally makes human-like interactions during watching.

        Args:
            seconds: How long to watch in seconds

        Returns:
            Actual time watched
        """
        start_time = asyncio.get_event_loop().time()
        watched = 0

        # Ensure video is playing
        await self.play()

        while watched < seconds:
            # Random chance of small interaction
            if random.random() < 0.1:  # 10% chance per second
                action = random.choice(["volume", "hover", "none", "none"])

                if action == "volume":
                    await self.random_volume_adjustment()
                elif action == "hover":
                    # Hover over player briefly
                    viewport = await self.page.viewport_size
                    if viewport:
                        x = random.uniform(200, viewport["width"] - 200)
                        y = random.uniform(100, 400)
                        await self.mouse.hover_with_tremor(x, y, duration=0.5)

            await asyncio.sleep(1.0)
            watched = asyncio.get_event_loop().time() - start_time

            # Verify still playing
            if not await self.is_playing():
                state = await self.get_state()
                if state == PlayerState.ENDED:
                    break
                elif state == PlayerState.PAUSED:
                    await self.play()

        return watched

    async def wait_for_video_element(self, timeout: float = 10.0) -> bool:
        """
        Wait for video element to exist in DOM.

        Args:
            timeout: Maximum wait time in seconds

        Returns:
            True if video element found
        """
        try:
            await self.page.wait_for_selector(
                self._selectors.VIDEO_PLAYER,
                timeout=timeout * 1000
            )
            return True
        except Exception:
            return False

    # =========================================================================
    # SHORTS SURFING MODE
    # =========================================================================

    async def surf_shorts(self, total_duration: float = 180.0) -> dict:
        """
        Shorts Surfing Mode — optimized for cookie farming.

        Instead of watching one Short for full duration,
        surfs through multiple Shorts (5-10 per session).

        Args:
            total_duration: Total time to spend surfing Shorts (seconds)

        Returns:
            dict with surfing stats
        """
        analytics = get_analytics()
        current_url = self.page.url

        # DEBUG: Log entry point
        if analytics:
            analytics.log(EventType.SHORTS_SURF_DEBUG, {
                "action": "method_called",
                "url": current_url[:100],
                "target_duration": total_duration
            })

        logger.debug(f"surf_shorts() called, url={current_url[:80]}")

        # FLEXIBLE URL CHECK - multiple patterns
        is_shorts = any([
            "/shorts/" in current_url,
            "feature=shorts" in current_url,
        ])

        if not is_shorts:
            if analytics:
                analytics.log(EventType.SHORTS_SURF_SKIP, {
                    "reason": "not_shorts_url",
                    "url": current_url[:100],
                    "checked_patterns": ["/shorts/", "feature=shorts"]
                })
            logger.warning(f"surf_shorts() skipped - not Shorts URL: {current_url[:80]}")
            return {"error": "not_shorts_page", "url": current_url}

        start_time = time.time()
        stats = {
            "shorts_watched": 0,
            "shorts_rewatched": 0,
            "total_scrolls": 0,
            "scroll_methods_used": [],
            "ads_skipped": 0,
            "errors": [],
            "total_duration": 0
        }

        if analytics:
            analytics.log(EventType.SHORTS_SURF_START, {
                "url": current_url[:100],
                "target_duration": total_duration
            })

        logger.info(f"Starting Shorts surfing for {total_duration:.0f}s")

        while (time.time() - start_time) < total_duration:
            try:
                # Watch current Short
                watch_result = await self._watch_single_short()

                if watch_result.get("error"):
                    stats["errors"].append(watch_result["error"])
                    continue

                if watch_result.get("ad_handled"):
                    stats["ads_skipped"] += 1
                    continue

                stats["shorts_watched"] += 1

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
                        "short_number": stats["shorts_watched"],
                        "watch_duration": watch_result.get("watch_duration", 0),
                        "video_hash": video_hash
                    })

                logger.debug(f"Watched Short #{stats['shorts_watched']}, duration={watch_result.get('watch_duration', 0):.1f}s")

                # Maybe rewatch (profile-specific chance — "liked it")
                if self._should_rewatch():
                    if analytics:
                        analytics.log(EventType.SHORTS_REWATCH, {
                            "reason": "liked_it",
                            "short_number": stats["shorts_watched"]
                        })

                    logger.debug(f"Rewatching Short #{stats['shorts_watched']} (liked it)")
                    await self._watch_single_short()
                    stats["shorts_rewatched"] += 1

                # Scroll to next Short
                scroll_result = await self._scroll_to_next_short()
                stats["total_scrolls"] += 1
                stats["scroll_methods_used"].append(scroll_result.get("method", "unknown"))

                # Brief pause for next Short to load
                await asyncio.sleep(random.uniform(0.8, 1.5))

            except Exception as e:
                error_msg = str(e)
                stats["errors"].append(error_msg)
                if analytics:
                    analytics.log(EventType.SHORTS_ERROR, {
                        "error": error_msg,
                        "shorts_watched": stats["shorts_watched"]
                    })
                logger.warning(f"Shorts surfing error: {e}")
                await asyncio.sleep(1.0)

        stats["total_duration"] = round(time.time() - start_time, 1)

        if analytics:
            analytics.log(EventType.SHORTS_SURF_END, stats)

        logger.info(f"Shorts surfing complete: watched={stats['shorts_watched']}, scrolls={stats['total_scrolls']}, errors={len(stats['errors'])}")

        return stats

    async def _watch_single_short(self) -> dict:
        """
        Watch a single Short — ultra-realistic behavior.

        Most people scroll BEFORE video ends or right at the end.
        Rewatching is rare (<10% of cases, handled separately).

        Ultra-aggressive loop limits:
        - Short (5-15s): 0.5-0.9 loops
        - Medium (15-30s): 0.4-0.8 loops
        - Long (30s+): 0.2-0.6 loops

        Returns:
            dict with watch result including loops count
        """
        analytics = get_analytics()
        result = {"ad_handled": False, "watch_duration": 0, "loops": 0}

        # 1. Check for ads first
        ad_result = await self.check_and_skip_ads()
        if ad_result.get("ad_detected"):
            result["ad_handled"] = True
            return result

        # 2. Make sure video is playing
        await self._ensure_short_playing()

        # 3. Get Short duration (or estimate)
        short_duration = await self._get_short_duration()

        # 4. ULTRA-AGGRESSIVE LOOP LIMITS
        # Most people scroll before video ends or right at end
        if short_duration <= 15:
            # Short videos (5-15s): 0.5-0.9 loops
            max_loops_raw = random.uniform(0.5, 0.9)
        elif short_duration <= 30:
            # Medium videos (15-30s): 0.4-0.8 loops
            max_loops_raw = random.uniform(0.4, 0.8)
        else:
            # Long videos (30s+): 0.2-0.6 loops
            max_loops_raw = random.uniform(0.2, 0.6)

        # 5. Apply profile's patience multiplier (0.9-1.1, minimal variance)
        patience = getattr(self, '_shorts_patience', 1.0)
        max_loops = max_loops_raw * patience

        # 6. Calculate watch time
        watch_time = short_duration * max_loops

        # 7. Small variance (±5%)
        watch_time *= random.uniform(0.95, 1.05)

        # 8. Absolute bounds
        # Min: at least 2s (saw something)
        # Max: NEVER more than 1.0x video length without explicit rewatch
        min_watch = 2.0
        max_watch = short_duration * 1.0  # Hard cap at 1 loop
        watch_time = max(min_watch, min(watch_time, max_watch))

        # Calculate actual loops for logging
        actual_loops = watch_time / short_duration if short_duration > 0 else 1

        # LOG the planned watch
        if analytics:
            analytics.log(EventType.SHORTS_WATCHING, {
                "video_duration": round(short_duration, 1),
                "watch_time": round(watch_time, 1),
                "max_loops_raw": round(max_loops_raw, 2),
                "max_loops_with_patience": round(max_loops, 2),
                "actual_loops": round(actual_loops, 2),
                "patience": round(patience, 2)
            })

        logger.debug(
            f"Watching Short: duration={short_duration:.1f}s, "
            f"watch_time={watch_time:.1f}s, loops={actual_loops:.2f}"
        )

        # 9. Watch loop with MINIMAL overhead
        watch_start = time.time()

        while (time.time() - watch_start) < watch_time:
            # Quick ad check only
            if await self._quick_ad_check():
                result["ad_handled"] = True
                break

            # Minimal micro-actions (3% chance)
            if random.random() < 0.03:
                await self._add_mouse_tremor()

            # Short sleep intervals (0.5-1.0s)
            await asyncio.sleep(random.uniform(0.5, 1.0))

        result["watch_duration"] = round(time.time() - watch_start, 1)
        result["loops"] = round(result["watch_duration"] / short_duration, 2) if short_duration > 0 else 1

        return result

    async def _get_short_duration(self) -> float:
        """
        Get duration of current Short video.

        Returns:
            Duration in seconds (or estimate if unavailable)
        """
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

        # Fallback: random estimate (most Shorts are 15-60 sec)
        return random.uniform(15, 45)

    async def _ensure_short_playing(self) -> bool:
        """
        Ensure Short video is playing (not paused).

        Returns:
            True if video is now playing
        """
        analytics = get_analytics()

        video_state = await self.page.evaluate("""
            () => {
                const video = document.querySelector(
                    'div#shorts-player video, ytd-shorts video, video'
                );
                if (!video) return null;
                return {
                    paused: video.paused,
                    readyState: video.readyState,
                    currentTime: video.currentTime,
                    duration: video.duration || 0
                };
            }
        """)

        # DEBUG: Log video state
        if analytics and video_state:
            analytics.log(EventType.SHORTS_VIDEO_STATE, {
                "paused": video_state.get("paused"),
                "readyState": video_state.get("readyState"),
                "currentTime": round(video_state.get("currentTime", 0), 1),
                "duration": round(video_state.get("duration", 0), 1)
            })

        if video_state is None:
            logger.warning("No video element found for Short")
            return False

        logger.debug(f"Short video state: paused={video_state.get('paused')}, ready={video_state.get('readyState')}")

        if video_state.get("paused", True) or video_state.get("readyState", 0) < 3:
            # Click to play
            viewport = self.page.viewport_size
            if viewport:
                center_x = viewport["width"] / 2 + random.uniform(-20, 20)
                center_y = viewport["height"] / 2 + random.uniform(-30, 30)

                await asyncio.sleep(random.uniform(0.3, 0.8))
                await self.mouse.move_to(center_x, center_y)
                await self.mouse.click_at(center_x, center_y)

                if analytics:
                    analytics.log(EventType.SHORTS_PLAY_CLICKED, {
                        "was_paused": video_state.get("paused"),
                        "ready_state": video_state.get("readyState")
                    })

                logger.debug("Clicked to play Short")
                await asyncio.sleep(random.uniform(0.5, 1.0))
                return True

        return True

    def _should_rewatch(self) -> bool:
        """
        Determine if we should rewatch current Short.

        Profile-specific: some users rewatch more often.
        """
        return random.random() < self._shorts_rewatch_chance

    async def _scroll_to_next_short(self) -> dict:
        """
        Scroll to next Short with debug logging.

        Returns:
            dict with method used and success status
        """
        analytics = get_analytics()
        result = {"method": None, "success": False}

        # Pre-scroll delay (finishing watching)
        await asyncio.sleep(random.uniform(0.3, 0.8))

        # Choose scroll method based on profile weights
        methods = list(self._shorts_scroll_weights.keys())
        weights = list(self._shorts_scroll_weights.values())
        method = random.choices(methods, weights=weights, k=1)[0]

        result["method"] = method

        # DEBUG: Log before attempting scroll
        if analytics:
            analytics.log(EventType.SHORTS_NEXT_ATTEMPT, {
                "method": method,
                "weights": self._shorts_scroll_weights
            })

        logger.debug(f"Attempting scroll to next Short via {method}")

        try:
            if method == "arrow_down":
                # KEYBOARD METHOD - Most reliable for Shorts
                await self.page.keyboard.press("ArrowDown")
                result["success"] = True
                logger.debug("ArrowDown pressed")

            else:  # swipe
                # SWIPE GESTURE with proper mouse down/up
                viewport = self.page.viewport_size
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
                        # Ease-out curve for natural swipe
                        eased_progress = 1 - (1 - progress) ** 2
                        current_y = start_y + (end_y - start_y) * eased_progress
                        await self.page.mouse.move(center_x, current_y)
                        await asyncio.sleep(random.uniform(0.008, 0.015))

                    # Mouse up (release)
                    await self.page.mouse.up()
                    result["success"] = True
                    logger.debug("Swipe completed")
                else:
                    # Fallback to arrow_down if no viewport
                    await self.page.keyboard.press("ArrowDown")
                    result["method"] = "arrow_down_fallback"
                    result["success"] = True
                    logger.debug("ArrowDown fallback (no viewport)")

        except Exception as e:
            result["success"] = False
            result["error"] = str(e)

            if analytics:
                analytics.log(EventType.SHORTS_SCROLL_ERROR, {
                    "method": method,
                    "error": str(e)
                })
            logger.warning(f"Scroll failed: {e}")

        # DEBUG: Log result
        if analytics:
            analytics.log(EventType.SHORTS_NEXT, {
                "method": method,
                "success": result["success"]
            })

        # Wait for transition
        await asyncio.sleep(random.uniform(0.5, 1.0))

        return result

    async def _quick_ad_check(self) -> bool:
        """
        Quick check for ads during Short playback.

        Returns:
            True if ad was detected and handled
        """
        # Fast selector check
        for selector in [".ad-showing", ".ytp-ad-player-overlay"]:
            try:
                element = await self.page.query_selector(selector)
                if element and await element.is_visible():
                    # Ad found — handle it
                    await self.check_and_skip_ads()
                    return True
            except Exception:
                pass

        return False

    async def _add_mouse_tremor(self) -> None:
        """Add small mouse tremor (human behavior)."""
        viewport = self.page.viewport_size
        if viewport:
            x = random.uniform(viewport["width"] * 0.3, viewport["width"] * 0.7)
            y = random.uniform(viewport["height"] * 0.3, viewport["height"] * 0.7)
            await self.mouse.hover_with_tremor(x, y, duration=random.uniform(0.2, 0.5))

    async def _random_hover_action(self) -> None:
        """Random hover movement (human behavior)."""
        viewport = self.page.viewport_size
        if viewport:
            x = random.uniform(viewport["width"] * 0.2, viewport["width"] * 0.8)
            y = random.uniform(viewport["height"] * 0.2, viewport["height"] * 0.8)
            await self.mouse.move_to(x, y)

    # =========================================================================
    # AD DETECTION AND SKIPPING
    # =========================================================================

    def _select_ad_personality(self) -> str:
        """
        Select personality for this ad encounter.

        Uses profile-specific weights set during initialization.
        """
        personalities = list(self._ad_personality_weights.keys())
        probs = list(self._ad_personality_weights.values())
        return random.choices(personalities, weights=probs, k=1)[0]

    async def check_and_skip_ads(self) -> dict:
        """
        Aggressive ad detection and skipping.

        Checks multiple selector types to catch YouTube's changing UI.
        Uses human-like delays before clicking.

        Returns:
            dict with action taken and details for logging
        """
        analytics = get_analytics()

        result = {
            "ad_detected": False,
            "action": None,
            "selector_used": None
        }

        # 1. First check if any ad is playing
        ad_playing = False
        ad_indicator = None

        for selector in self._selectors.AD_PLAYING_SELECTORS:
            try:
                element = await self.page.query_selector(selector)
                if element and await element.is_visible():
                    ad_playing = True
                    ad_indicator = selector
                    break
            except Exception:
                continue

        if not ad_playing:
            return result

        # Ad is playing — log detection
        result["ad_detected"] = True
        result["ad_indicator"] = ad_indicator

        if analytics:
            analytics.log(EventType.AD_DETECTED, {
                "indicator": ad_indicator,
                "url_hash": hash(self.page.url) % 10000
            })

        logger.info(f"Ad detected via {ad_indicator}")

        # 2. Determine personality for this ad
        personality = self._select_ad_personality()
        result["personality"] = personality

        if personality == "distracted":
            # Watch the full ad
            if analytics:
                analytics.log(EventType.AD_ACTION, {
                    "action": "watching_full",
                    "personality": "distracted"
                })
            logger.debug("Ad: watching full (distracted personality)")
            result["action"] = "watching_full"
            return result

        # 3. Look for skip button
        skip_button = None
        skip_selector = None

        # Try skip buttons first
        for selector in self._selectors.AD_SKIP_SELECTORS:
            try:
                element = await self.page.query_selector(selector)
                if element and await element.is_visible():
                    skip_button = element
                    skip_selector = selector
                    break
            except Exception:
                continue

        # Try overlay close buttons if no skip button
        if not skip_button:
            for selector in self._selectors.AD_OVERLAY_CLOSE_SELECTORS:
                try:
                    element = await self.page.query_selector(selector)
                    if element and await element.is_visible():
                        skip_button = element
                        skip_selector = selector
                        break
                except Exception:
                    continue

        if not skip_button:
            # No skip button available (yet) — might need to wait
            result["action"] = "no_skip_button"
            logger.debug("Ad: no skip button found yet")
            return result

        # 4. Human-like reaction delay based on personality
        if personality == "sniper":
            # Quick reaction: 0.3-0.8s
            delay = random.uniform(0.3, 0.8)
        else:  # "lazy"
            # Slow reaction: 1.5-4.0s
            delay = random.uniform(1.5, 4.0)

        if analytics:
            analytics.log(EventType.AD_SKIP_PREPARING, {
                "personality": personality,
                "delay_ms": round(delay * 1000),
                "selector": skip_selector
            })

        logger.debug(f"Ad: preparing to skip ({personality}), waiting {delay:.1f}s")
        await asyncio.sleep(delay)

        # 5. Click the skip button
        try:
            box = await skip_button.bounding_box()

            if box:
                # Click with jitter (not exact center)
                x = box["x"] + box["width"] * random.uniform(0.25, 0.75)
                y = box["y"] + box["height"] * random.uniform(0.25, 0.75)

                # Move mouse to button
                await self.mouse.move_to(x, y, target_width=box["width"], target_height=box["height"])

                # Click
                await self.mouse.click_at(x, y)
            else:
                # Fallback: direct click
                await skip_button.click()

            result["action"] = "skipped"
            result["selector_used"] = skip_selector

            if analytics:
                analytics.log(EventType.AD_SKIPPED, {
                    "selector": skip_selector,
                    "personality": personality,
                    "reaction_ms": round(delay * 1000)
                })

            logger.info(f"Ad skipped via {skip_selector}")

            # Wait for ad to disappear
            await asyncio.sleep(random.uniform(0.8, 1.5))

        except Exception as e:
            result["action"] = "skip_failed"
            result["error"] = str(e)

            if analytics:
                analytics.log(EventType.AD_SKIP_FAILED, {
                    "error": str(e),
                    "selector": skip_selector
                })

            logger.warning(f"Ad skip failed: {e}")

        return result

    async def wait_for_ad_skip(self, timeout: float = 30.0) -> dict:
        """
        Wait for ad skip button to appear and skip.

        Polls for ad presence and skip button availability.

        Args:
            timeout: Maximum time to wait for skip button

        Returns:
            dict with result of ad handling
        """
        start_time = asyncio.get_event_loop().time()

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            result = await self.check_and_skip_ads()

            if result.get("action") in ["skipped", "watching_full", "no_skip_button"]:
                if result.get("action") == "no_skip_button":
                    # Wait and retry
                    await asyncio.sleep(0.5)
                    continue
                return result

            if not result.get("ad_detected"):
                # No ad playing
                return result

            await asyncio.sleep(0.5)

        return {"ad_detected": True, "action": "timeout"}

    # =========================================================================
    # INTEGRATED WATCH LOOP
    # =========================================================================

    async def watch_with_ad_handling(self, duration: float = 60.0) -> dict:
        """
        Watch video with integrated ad and Shorts handling.

        Automatically uses Shorts Surfing Mode if on Shorts page.

        Args:
            duration: How long to watch (seconds)

        Returns:
            dict with session stats
        """
        current_url = self.page.url

        # Auto-detect Shorts and use surfing mode (flexible URL detection)
        is_shorts = "/shorts/" in current_url or "feature=shorts" in current_url
        if is_shorts:
            logger.debug(f"Detected Shorts URL, switching to surf_shorts()")
            return await self.surf_shorts(total_duration=duration)

        # Regular video watching
        analytics = get_analytics()
        start_time = asyncio.get_event_loop().time()

        stats = {
            "ads_skipped": 0,
            "ads_watched": 0,
            "watch_duration": 0
        }

        while (asyncio.get_event_loop().time() - start_time) < duration:
            # 1. CRITICAL: Check Ads First (every iteration)
            ad_result = await self.check_and_skip_ads()

            if ad_result.get("ad_detected"):
                if ad_result.get("action") == "skipped":
                    stats["ads_skipped"] += 1
                elif ad_result.get("action") == "watching_full":
                    stats["ads_watched"] += 1

                # If ad was handled, continue loop immediately
                if ad_result.get("action") in ["skipped", "watching_full"]:
                    await asyncio.sleep(0.5)
                    continue

            # 2. Normal video watching behavior
            action_roll = random.random()

            if action_roll < 0.05:
                # Random volume adjustment
                await self.random_volume_adjustment()
            elif action_roll < 0.08:
                # Hover over player
                viewport = self.page.viewport_size
                if viewport:
                    x = random.uniform(200, viewport["width"] - 200)
                    y = random.uniform(100, 400)
                    await self.mouse.hover_with_tremor(x, y, duration=0.5)

            # Wait before next check
            await asyncio.sleep(random.uniform(2.0, 5.0))

        stats["watch_duration"] = round(asyncio.get_event_loop().time() - start_time, 1)

        if analytics:
            analytics.log(EventType.WATCH_SESSION_END, stats)

        logger.info(f"Watch session: {stats}")

        return stats
