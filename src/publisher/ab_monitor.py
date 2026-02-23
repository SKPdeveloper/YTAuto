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

# HumanCommenter DISABLED — all comment pinning is done manually by the user
# to avoid YouTube anti-fraud detection. A/B rotation only changes
# title/description/tags; pinned comment must be updated manually.
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

        # --- Phase 1.5: Post deferred comment if video just went live ---
        if video_snapshot.pending_comment_text:
            now = datetime.now(timezone.utc)
            go_live = video_snapshot.scheduled_go_live or video_snapshot.upload_time
            if now >= go_live:
                self._post_deferred_comment(video_id, youtube)

        # --- Phase 2: Fetch stats (NO lock held — slow network I/O) ---
        stats = self._fetch_stats_with_retry(youtube, video_id, video_snapshot.channel_id)
        if stats is None:
            # Could be transient (auth expired, network) or permanent (video deleted).
            # Don't set error immediately — retry next cycle. Only manual intervention
            # or 3 consecutive cycles of failure should set error.
            logger.warning(f"{video_id}: Failed to fetch stats after retries, will retry next cycle")
            return "stats_unavailable"

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

            # Skip evaluation if video is scheduled for future publication
            if video.scheduled_go_live and now < video.scheduled_go_live:
                hours_until = (video.scheduled_go_live - now).total_seconds() / 3600
                logger.debug(
                    f"{video.video_id}: scheduled go-live in {hours_until:.1f}h, skipping"
                )
                return "waiting_for_go_live"

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
        Log the new pinned comment text for manual action.

        Automated comment posting/pinning is DISABLED to avoid YouTube
        anti-fraud detection. The user must update the pinned comment
        manually via YouTube Studio after each A/B swap.

        Returns True always (comment rotation is informational only).
        """
        if not new_comment_text:
            return True

        logger.info(
            f"{video.video_id}: A/B swap suggests new pinned comment — "
            f"please update manually in YouTube Studio:\n"
            f"  \"{new_comment_text[:120]}{'...' if len(new_comment_text) > 120 else ''}\""
        )
        return True

    # ========================================================================
    # DEFERRED COMMENT POSTING
    # ========================================================================

    def _post_deferred_comment(self, video_id: str, youtube: YouTubeAPI) -> None:
        """
        Post a deferred comment when a scheduled video goes live.

        Called by _evaluate_video() on the first cycle after go-live time.
        Posts via YouTube API commentThreads.insert(), then clears
        pending_comment_text under lock. If the video was registered only
        for comment tracking (no AB variants), marks it as SUCCESS.

        Non-fatal: failures are logged but don't block the monitor cycle.
        """
        # Read fresh state
        self.store.reload()
        video = self.store.get_video(video_id)
        if not video or not video.pending_comment_text:
            return

        comment_text = video.pending_comment_text

        # API call (no lock held — slow network I/O)
        try:
            ok, comment_id, err = youtube.insert_comment_thread(
                video_id=video_id,
                text=comment_text,
            )

            if ok:
                # Clear pending comment and save comment_id under lock
                def _commit_comment(v: VideoABRecord) -> str:
                    v.pending_comment_text = None
                    v.current_comment_id = comment_id
                    # If registered only for comment (no real AB variants),
                    # mark as done — no checkpoint evaluation needed
                    if len(v.variants) < 2:
                        v.status = ABStatus.SUCCESS
                        v.final_variant = v.current_variant
                    return "comment_posted"

                self.store.locked_update(
                    video_id, _commit_comment, require_monitoring=False
                )
                logger.success(
                    f"{video_id}: Deferred comment posted via API (id={comment_id}) "
                    f"— PIN IT manually in YouTube Studio"
                )
            else:
                logger.warning(f"{video_id}: Failed to post deferred comment: {err}")

        except Exception as e:
            logger.warning(f"{video_id}: Deferred comment posting failed: {e}")

    # ========================================================================
    # HELPERS
    # ========================================================================

    def _is_swap_window(self) -> bool:
        """Check if current time is within the swap window (02:00-06:00 ET)."""
        tz = ZoneInfo(SWAP_WINDOW_TIMEZONE)
        now_local = datetime.now(tz)
        return SWAP_WINDOW_START_HOUR <= now_local.hour < SWAP_WINDOW_END_HOUR

    def _fetch_stats_with_retry(
        self, youtube: YouTubeAPI, video_id: str, channel_id: str
    ) -> Optional[dict]:
        """Fetch video stats with retry, token refresh on 401, and backoff."""
        for attempt in range(MONITOR_API_MAX_RETRIES):
            stats = youtube.get_video_stats(video_id)
            if stats is not None:
                return stats

            # On first failure, try re-authenticating (token may have expired)
            if attempt == 0:
                logger.info(f"Stats fetch failed for {video_id}, refreshing auth...")
                self._api_cache.pop(channel_id, None)
                youtube_fresh = self._get_youtube_api(channel_id)
                if youtube_fresh and youtube_fresh is not youtube:
                    youtube = youtube_fresh
                    # Immediate retry with fresh token
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
