"""
A/B Monitor — Core Evaluation & Rotation Logic

Runs every 30 minutes (via ab_daemon). For each actively monitored video:
1. Fetch current stats from YouTube API
2. Log metrics snapshot
3. Evaluate against checkpoint thresholds
4. Execute swap if criteria met (respecting swap window for non-dead videos)

Key design decisions:
- Timer resets on swap: variant_start_time = now(), checks_completed = []
- CHECK #1 (dead) swaps immediately regardless of time
- CHECK #2/3 swaps deferred to 02:00-06:00 ET window
- CHECK #3 dead with remaining variants = "last chance" swap (per TZ spec)
- Max 3 swaps (A->B->C->D). All exhausted -> status "exhausted"
- API errors after 3 retries -> status "manual"
- Video not found -> status "error"
"""

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional
from zoneinfo import ZoneInfo

from loguru import logger

from .ab_config import (
    MAX_SWAPS,
    MONITOR_API_MAX_RETRIES,
    ROTATION_ORDER,
    SWAP_WINDOW_END_HOUR,
    SWAP_WINDOW_START_HOUR,
    SWAP_WINDOW_TIMEZONE,
    THRESHOLDS,
)
from .ab_models import (
    ABStatus,
    MetricsSnapshot,
    SwapRecord,
    VideoABRecord,
)
from .ab_store import ABStore
from .config_manager import get_config_manager
from .youtube_api import YouTubeAPI

# HumanCommenter for pinning comments via browser automation
try:
    from ..human_commenter import HumanCommenter, CommenterConfig
    HUMAN_COMMENTER_AVAILABLE = True
except ImportError:
    try:
        from human_commenter import HumanCommenter, CommenterConfig
        HUMAN_COMMENTER_AVAILABLE = True
    except ImportError:
        HUMAN_COMMENTER_AVAILABLE = False


def _set_error(video: VideoABRecord) -> str:
    """Helper: mark video as error (used inside locked_update)."""
    video.status = ABStatus.ERROR
    return "error"


def _set_manual(video: VideoABRecord) -> str:
    """Helper: mark video as manual (used inside locked_update)."""
    video.status = ABStatus.MANUAL
    return "manual"


class ABMonitor:
    """
    Core A/B rotation monitor.

    Evaluates video performance and swaps metadata variants
    when checkpoints indicate a "dead" video.
    """

    def __init__(self, store: Optional[ABStore] = None):
        self._config = get_config_manager()
        self.store = store or ABStore(config_dir=self._config.config_dir)
        self._api_cache: Dict[str, YouTubeAPI] = {}

    # ========================================================================
    # MAIN CYCLE
    # ========================================================================

    def run_cycle(self) -> Dict[str, str]:
        """
        Run one monitor cycle across all active videos.

        Returns:
            Dict mapping video_id -> action taken (e.g., "swap_B", "keep", "success")
        """
        # Locked reload to get a consistent snapshot of active video IDs
        self.store.reload()
        active_ids = [v.video_id for v in self.store.get_active_videos()]

        if not active_ids:
            logger.debug("No active videos to monitor")
            return {}

        logger.info(f"Monitor cycle: {len(active_ids)} active videos")
        results = {}

        for video_id in active_ids:
            try:
                action = self._evaluate_video(video_id)
                results[video_id] = action
            except Exception as e:
                logger.error(f"Error evaluating {video_id}: {e}")
                results[video_id] = f"error: {e}"

        logger.info(f"Cycle complete: {results}")
        return results

    # ========================================================================
    # SINGLE VIDEO EVALUATION
    # ========================================================================

    def _evaluate_video(self, video_id: str) -> str:
        """
        Evaluate a single video: fetch stats, log, check thresholds.

        Uses locked_update() for atomic read-modify-write to prevent
        lost-update races with concurrent CLI/pipeline operations.

        Returns action string: "keep", "swap_X", "success", "exhausted", etc.
        """
        # --- Phase 1: Read video state (no lock needed — just reading channel_id) ---
        # reload() is safe without lock because save() uses atomic os.replace.
        self.store.reload()
        video_snapshot = self.store.get_video(video_id)
        if not video_snapshot or video_snapshot.status != ABStatus.MONITORING:
            return "skipped_stale"

        youtube = self._get_youtube_api(video_snapshot.channel_id)
        if not youtube:
            logger.warning(f"Cannot get YouTube API for channel {video_snapshot.channel_id}")
            return "no_api"

        # --- Phase 2: Fetch stats (NO lock held — slow network I/O) ---
        stats = self._fetch_stats_with_retry(youtube, video_id)
        if stats is None:
            # Video might be deleted/blocked
            self.store.locked_update(video_id, _set_error, require_monitoring=False)
            return "error_not_found"

        views = stats["views"]
        snapshot = MetricsSnapshot(
            views=views,
            likes=stats["likes"],
            comments=stats["comments"],
        )

        # --- Phase 3: Evaluate checkpoint under lock (atomic read-modify-write) ---
        def _evaluate_and_decide(video: VideoABRecord) -> str:
            """Mutate video in-place under lock, return decision string."""
            video.metrics_log.append(snapshot)

            now = datetime.now(timezone.utc)
            hours_elapsed = (now - video.variant_start_time).total_seconds() / 3600

            if hours_elapsed < 0:
                logger.warning(
                    f"{video.video_id}: variant_start_time is in the future "
                    f"({video.variant_start_time}), resetting to now"
                )
                video.variant_start_time = now
                hours_elapsed = 0.0

            decision = self._evaluate_checkpoint(video, views, hours_elapsed)

            if decision == "alive":
                video.status = ABStatus.SUCCESS
                video.final_variant = video.current_variant
                video.final_views_48h = views
                logger.info(f"{video.video_id}: ALIVE with {views} views on variant {video.current_variant}")
                return "alive"

            elif decision.startswith("swap"):
                if not self._can_swap(video):
                    video.status = ABStatus.EXHAUSTED
                    video.final_variant = video.current_variant
                    video.final_views_48h = views
                    logger.warning(f"{video.video_id}: EXHAUSTED all {len(ROTATION_ORDER)} variants")
                    return "exhausted"

                is_immediate = decision == "swap_immediate"
                if not is_immediate and not self._is_swap_window():
                    logger.info(f"{video.video_id}: Swap deferred (outside window), {views} views")
                    return "swap_deferred"

                return f"need_swap:{decision}"

            elif decision == "final_dead":
                if self._can_swap(video):
                    return "need_swap:last_chance_48h"
                else:
                    video.status = ABStatus.EXHAUSTED
                    video.final_variant = video.current_variant
                    video.final_views_48h = views
                    logger.warning(f"{video.video_id}: EXHAUSTED at {views} views after 48h")
                    return "exhausted"

            return "keep"

        decision = self.store.locked_update(video_id, _evaluate_and_decide)
        if decision is None:
            return "skipped_stale"

        # Append metrics to JSONL after main store is saved (keeps them in sync)
        self.store.append_metrics(video_id, snapshot)

        # If no swap needed, we're done
        if not decision.startswith("need_swap:"):
            return decision if decision != "alive" else "success"

        # --- Phase 4: Execute swap (YouTube API call WITHOUT lock, then save under lock) ---
        swap_reason = decision.split(":", 1)[1]
        action = self._execute_swap(video_id, youtube, views, swap_reason)
        return action

    # ========================================================================
    # CHECKPOINT EVALUATION
    # ========================================================================

    def _evaluate_checkpoint(
        self, video: VideoABRecord, views: int, hours_elapsed: float
    ) -> str:
        """
        Evaluate which checkpoint applies and return decision.

        Evaluates from LOWEST to HIGHEST (check_1 -> check_2 -> check_3)
        so that skipped lower checkpoints are always processed first.

        Returns:
            "alive" — video performing well, stop monitoring
            "swap_immediate" — dead at check_1, swap now
            "swap_window" — dead at check_2/3, swap in window
            "final_dead" — 48h passed and dead, last-chance swap
            "wait" — not enough time for next checkpoint
        """
        # Check 1: 6h (seed test) — evaluate FIRST
        check1 = THRESHOLDS["check_1"]
        if hours_elapsed >= check1["hours"] and "check_1" not in video.checks_completed:
            video.checks_completed.append("check_1")
            if views >= check1["alive_above"]:
                return "alive"
            elif views < check1["dead_below"]:
                return "swap_immediate"
            # Uncertain zone (50-200 views) — wait for check_2
            return "wait"

        # Check 2: 18h
        check2 = THRESHOLDS["check_2"]
        if hours_elapsed >= check2["hours"] and "check_2" not in video.checks_completed:
            video.checks_completed.append("check_2")
            if views >= check2["alive_above"]:
                return "alive"
            elif views < check2["dead_below"]:
                return "swap_window"
            # Between dead and alive — wait for check_3
            return "wait"

        # Check 3: 48h (final evaluation)
        check3 = THRESHOLDS["check_3"]
        if hours_elapsed >= check3["hours"] and "check_3" not in video.checks_completed:
            video.checks_completed.append("check_3")
            if views >= check3["alive_above"]:
                return "alive"
            else:
                return "final_dead"

        return "wait"

    # ========================================================================
    # SWAP EXECUTION
    # ========================================================================

    def _can_swap(self, video: VideoABRecord) -> bool:
        """Check if the video has remaining variants to swap to."""
        swap_count = len(video.swap_history)
        if swap_count >= MAX_SWAPS:
            return False
        # Also verify the next variant actually exists
        try:
            current_idx = ROTATION_ORDER.index(video.current_variant)
        except ValueError:
            return False
        if current_idx + 1 >= len(ROTATION_ORDER):
            return False
        next_letter = ROTATION_ORDER[current_idx + 1]
        return next_letter in video.variants

    def _execute_swap(
        self,
        video_id: str,
        youtube: YouTubeAPI,
        views_at_swap: int,
        decision: str,
    ) -> str:
        """
        Execute a metadata swap to the next variant.

        Phase A: Read current state under lock → determine next variant
        Phase B: YouTube API call (no lock)
        Phase C: Record swap result under lock

        Returns action string like "swap_B".
        """
        # --- Phase A: determine next variant under lock ---
        swap_info: Optional[dict] = None

        def _resolve_next(video: VideoABRecord) -> Optional[dict]:
            try:
                current_idx = ROTATION_ORDER.index(video.current_variant)
            except ValueError:
                logger.error(f"{video.video_id}: Invalid current_variant '{video.current_variant}'")
                video.status = ABStatus.MANUAL
                return None

            if current_idx + 1 >= len(ROTATION_ORDER):
                logger.error(f"{video.video_id}: No next variant after '{video.current_variant}'")
                video.status = ABStatus.EXHAUSTED
                video.final_variant = video.current_variant
                return None

            next_letter = ROTATION_ORDER[current_idx + 1]
            if next_letter not in video.variants:
                logger.error(f"{video.video_id}: Variant {next_letter} not available")
                video.status = ABStatus.MANUAL
                return None

            nv = video.variants[next_letter]
            return {
                "from": video.current_variant,
                "to": next_letter,
                "title": nv.title,
                "description": nv.description,
                "pinned_comment": nv.pinned_comment,
            }

        swap_info = self.store.locked_update(video_id, _resolve_next)
        if swap_info is None:
            return "error_resolve_variant"

        next_letter = swap_info["to"]

        # --- Phase B: YouTube API calls (NO lock held) ---
        success, error = youtube.update_video(
            video_id=video_id,
            title=swap_info["title"],
            description=swap_info["description"],
        )

        if not success:
            logger.error(f"{video_id}: Failed to update metadata: {error}")
            self.store.locked_update(video_id, _set_manual, require_monitoring=False)
            return f"error_update: {error}"

        # Rotate pinned comment (non-fatal, outside lock — does YouTube API calls).
        # We read a snapshot, let _rotate_pinned_comment mutate it, then capture
        # the resulting comment_id to save in Phase C.
        self.store.reload()
        comment_snapshot = self.store.get_video(video_id)
        new_comment_id = None
        if comment_snapshot:
            self._rotate_pinned_comment(comment_snapshot, youtube, swap_info["pinned_comment"])
            new_comment_id = comment_snapshot.current_comment_id

        # --- Phase C: Record swap + comment_id under lock (single atomic write) ---
        def _commit_swap(video: VideoABRecord) -> str:
            video.swap_history.append(SwapRecord(
                from_variant=swap_info["from"],
                to_variant=next_letter,
                views_at_swap=views_at_swap,
                reason=decision,
            ))
            video.current_variant = next_letter
            video.variant_start_time = datetime.now(timezone.utc)
            video.checks_completed = []
            if new_comment_id is not None:
                video.current_comment_id = new_comment_id
            return f"swap_{next_letter}"

        # require_monitoring=False: swap already happened on YouTube, must record it
        result = self.store.locked_update(
            video_id, _commit_swap, require_monitoring=False
        )
        if result:
            logger.info(
                f"{video_id}: SWAPPED {swap_info['from']}->"
                f"{next_letter} at {views_at_swap} views"
            )
            return result
        return "error_commit_swap"

    def _rotate_pinned_comment(
        self,
        video: VideoABRecord,
        youtube: YouTubeAPI,
        new_comment_text: Optional[str],
    ) -> bool:
        """
        Delete old pinned comment and post+pin new one (if provided).

        Strategy:
        1. Try HumanCommenter (AdsPower browser automation) — posts AND pins
        2. Fallback to YouTube API — posts comment but CANNOT pin it

        Returns True if all operations succeeded, False if any failed.
        """
        all_ok = True

        # Delete old comment via API (always works, no browser needed)
        if video.current_comment_id:
            success, error = youtube.delete_comment(video.current_comment_id)
            if not success:
                logger.warning(f"Failed to delete old comment {video.current_comment_id}: {error}")
                all_ok = False
            video.current_comment_id = None

        if not new_comment_text:
            return all_ok

        # Try HumanCommenter first (posts + pins via browser)
        channel_config = self._config.load_channel_config(video.channel_id)
        if (
            HUMAN_COMMENTER_AVAILABLE
            and channel_config
            and getattr(channel_config, "adspower_profile_id", None)
        ):
            try:
                commenter = HumanCommenter(CommenterConfig())
                loop = asyncio.new_event_loop()
                try:
                    result = loop.run_until_complete(
                        commenter.add_and_pin_comment(
                            video_id=video.video_id,
                            comment_text=new_comment_text,
                            profile_id=channel_config.adspower_profile_id,
                            channel_keywords=getattr(channel_config, "channel_keywords", None),
                            expected_region=getattr(channel_config, "region", None),
                            expected_timezone=getattr(channel_config, "timezone", None),
                        )
                    )
                finally:
                    loop.close()

                if result.success:
                    video.current_comment_id = "human_commenter"
                    logger.info(f"{video.video_id}: Comment posted and pinned via HumanCommenter")
                    return all_ok
                else:
                    logger.warning(
                        f"{video.video_id}: HumanCommenter failed ({result.error}), "
                        f"falling back to API (comment will NOT be pinned)"
                    )
            except Exception as e:
                logger.warning(
                    f"{video.video_id}: HumanCommenter error ({e}), "
                    f"falling back to API (comment will NOT be pinned)"
                )

        # Fallback: post via API (comment will NOT be pinned)
        success, comment_id, error = youtube.insert_comment_thread(
            video_id=video.video_id,
            text=new_comment_text,
        )
        if success:
            video.current_comment_id = comment_id
            if HUMAN_COMMENTER_AVAILABLE and channel_config and getattr(channel_config, "adspower_profile_id", None):
                logger.warning(f"{video.video_id}: Comment posted via API but NOT pinned (HumanCommenter failed)")
            else:
                logger.warning(f"{video.video_id}: Comment posted via API but NOT pinned (no AdsPower profile)")
        else:
            logger.warning(f"Failed to post new comment: {error}")
            all_ok = False

        return all_ok

    # ========================================================================
    # HELPERS
    # ========================================================================

    def _is_swap_window(self) -> bool:
        """Check if current time is within the swap window (02:00-06:00 ET)."""
        tz = ZoneInfo(SWAP_WINDOW_TIMEZONE)
        now_local = datetime.now(tz)
        return SWAP_WINDOW_START_HOUR <= now_local.hour < SWAP_WINDOW_END_HOUR

    def _fetch_stats_with_retry(
        self, youtube: YouTubeAPI, video_id: str
    ) -> Optional[dict]:
        """Fetch video stats with retry and exponential backoff."""
        for attempt in range(MONITOR_API_MAX_RETRIES):
            stats = youtube.get_video_stats(video_id)
            if stats is not None:
                return stats
            if attempt < MONITOR_API_MAX_RETRIES - 1:
                delay = 2 ** attempt  # 1s, 2s, 4s...
                logger.warning(f"Retry {attempt + 1} fetching stats for {video_id} (backoff {delay}s)")
                time.sleep(delay)
        return None

    def _get_youtube_api(self, channel_id: str) -> Optional[YouTubeAPI]:
        """Get or create a YouTubeAPI instance for a channel."""
        if channel_id in self._api_cache:
            return self._api_cache[channel_id]

        channel_config = self._config.load_channel_config(channel_id)
        if not channel_config:
            logger.error(f"Channel config not found: {channel_id}")
            return None

        youtube = YouTubeAPI(
            channel_config=channel_config,
            client_secrets_path=self._config.get_client_secrets_path(channel_id),
            token_path=self._config.get_token_path(channel_id),
        )

        if not youtube.authenticate():
            logger.error(f"Failed to authenticate channel: {channel_id}")
            return None

        self._api_cache[channel_id] = youtube
        return youtube

    # ========================================================================
    # SINGLE VIDEO CHECK (for CLI)
    # ========================================================================

    def check_single(self, video_id: str) -> str:
        """
        Run evaluation for a single video (for 'ab check' CLI command).

        Returns action string.
        """
        self.store.reload()
        video = self.store.get_video(video_id)
        if not video:
            return f"Video {video_id} not found in AB store"

        if video.status != ABStatus.MONITORING:
            return f"Video {video_id} is not being monitored (status: {video.status.value})"

        return self._evaluate_video(video_id)
