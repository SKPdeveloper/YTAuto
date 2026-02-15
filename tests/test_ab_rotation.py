"""
Unit tests for A/B Metadata Rotation System.

All YouTube API calls are mocked — NO real uploads, NO real API requests.
Tests run entirely in-memory with temporary files.
"""

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.publisher.ab_config import ROTATION_ORDER, THRESHOLDS
from src.publisher.ab_models import (
    ABRotationStore,
    ABStatus,
    MetricsSnapshot,
    SwapRecord,
    VariantData,
    VideoABRecord,
    parse_metadata_variants,
)
from src.publisher.ab_store import ABStore
from src.publisher.ab_monitor import ABMonitor


# ============================================================================
# FIXTURES
# ============================================================================


def make_variants(letters="ABCD"):
    """Create test variant data for given letters."""
    triggers = {"A": "SATISFYING", "B": "FORBIDDEN", "C": "MYSTERY", "D": "ASMR"}
    return {
        letter: VariantData(
            trigger=triggers.get(letter, letter),
            title=f"Title {letter}",
            description=f"Description {letter}",
            pinned_comment=f"Pin {letter}",
        )
        for letter in letters
    }


def make_video(
    video_id="vid_001",
    variant="A",
    variants_letters="ABCD",
    hours_ago=0,
    views_history=None,
    checks_completed=None,
    swap_history=None,
    status=ABStatus.MONITORING,
):
    """Create a test VideoABRecord with controllable time offset."""
    start_time = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return VideoABRecord(
        video_id=video_id,
        project_id="proj_001",
        channel_id="ch_001",
        current_variant=variant,
        variant_start_time=start_time,
        variants=make_variants(variants_letters),
        checks_completed=checks_completed or [],
        swap_history=swap_history or [],
        status=status,
    )


def make_monitor(tmp_path, videos=None):
    """Create an ABMonitor with mocked dependencies."""
    config_dir = tmp_path
    store = ABStore(config_dir=config_dir)

    if videos:
        for v in videos:
            store.register_video(v)

    mock_config = MagicMock()
    mock_config.config_dir = config_dir
    mock_config.load_channel_config.return_value = MagicMock(
        adspower_profile_id=None,
    )

    monitor = ABMonitor(store=store)
    monitor._config = mock_config

    return monitor, store


def make_youtube_mock(views=100, likes=5, comments=1):
    """Create a mock YouTubeAPI that returns given stats."""
    yt = MagicMock()
    yt.get_video_stats.return_value = {
        "views": views,
        "likes": likes,
        "comments": comments,
    }
    yt.update_video.return_value = (True, None)
    yt.insert_comment_thread.return_value = (True, "comment_123", None)
    yt.delete_comment.return_value = (True, None)
    return yt


# ============================================================================
# 1. CHECKPOINT EVALUATION LOGIC
# ============================================================================


class TestCheckpointEvaluation:
    """Test _evaluate_checkpoint with various view counts and time offsets."""

    def test_check1_dead_below_50(self, tmp_path):
        """< 50 views at 6h → swap_immediate."""
        video = make_video(hours_ago=7)
        monitor, _ = make_monitor(tmp_path)

        result = monitor._evaluate_checkpoint(video, views=30, hours_elapsed=7)
        assert result == "swap_immediate"
        assert "check_1" in video.checks_completed

    def test_check1_alive_above_200(self, tmp_path):
        """≥ 200 views at 6h → alive."""
        video = make_video(hours_ago=7)
        monitor, _ = make_monitor(tmp_path)

        result = monitor._evaluate_checkpoint(video, views=250, hours_elapsed=7)
        assert result == "alive"
        assert "check_1" in video.checks_completed

    def test_check1_uncertain_zone(self, tmp_path):
        """50-199 views at 6h → wait (uncertain zone)."""
        video = make_video(hours_ago=7)
        monitor, _ = make_monitor(tmp_path)

        result = monitor._evaluate_checkpoint(video, views=100, hours_elapsed=7)
        assert result == "wait"
        assert "check_1" in video.checks_completed

    def test_check1_exactly_50_is_uncertain(self, tmp_path):
        """Exactly 50 views = NOT dead (dead is strictly < 50)."""
        video = make_video(hours_ago=7)
        monitor, _ = make_monitor(tmp_path)

        result = monitor._evaluate_checkpoint(video, views=50, hours_elapsed=7)
        assert result == "wait"  # uncertain, not dead

    def test_check1_exactly_200_is_alive(self, tmp_path):
        """Exactly 200 views = alive (alive is >= 200)."""
        video = make_video(hours_ago=7)
        monitor, _ = make_monitor(tmp_path)

        result = monitor._evaluate_checkpoint(video, views=200, hours_elapsed=7)
        assert result == "alive"

    def test_check2_dead_below_200(self, tmp_path):
        """< 200 views at 18h → swap_window."""
        video = make_video(hours_ago=19, checks_completed=["check_1"])
        monitor, _ = make_monitor(tmp_path)

        result = monitor._evaluate_checkpoint(video, views=150, hours_elapsed=19)
        assert result == "swap_window"
        assert "check_2" in video.checks_completed

    def test_check2_alive_above_500(self, tmp_path):
        """≥ 500 views at 18h → alive."""
        video = make_video(hours_ago=19, checks_completed=["check_1"])
        monitor, _ = make_monitor(tmp_path)

        result = monitor._evaluate_checkpoint(video, views=600, hours_elapsed=19)
        assert result == "alive"

    def test_check2_uncertain_zone(self, tmp_path):
        """200-499 views at 18h → wait."""
        video = make_video(hours_ago=19, checks_completed=["check_1"])
        monitor, _ = make_monitor(tmp_path)

        result = monitor._evaluate_checkpoint(video, views=350, hours_elapsed=19)
        assert result == "wait"

    def test_check3_alive(self, tmp_path):
        """≥ 500 views at 48h → alive."""
        video = make_video(hours_ago=49, checks_completed=["check_1", "check_2"])
        monitor, _ = make_monitor(tmp_path)

        result = monitor._evaluate_checkpoint(video, views=500, hours_elapsed=49)
        assert result == "alive"

    def test_check3_final_dead(self, tmp_path):
        """< 500 views at 48h → final_dead."""
        video = make_video(hours_ago=49, checks_completed=["check_1", "check_2"])
        monitor, _ = make_monitor(tmp_path)

        result = monitor._evaluate_checkpoint(video, views=400, hours_elapsed=49)
        assert result == "final_dead"

    def test_before_any_checkpoint(self, tmp_path):
        """< 6h elapsed → wait."""
        video = make_video(hours_ago=3)
        monitor, _ = make_monitor(tmp_path)

        result = monitor._evaluate_checkpoint(video, views=0, hours_elapsed=3)
        assert result == "wait"
        assert len(video.checks_completed) == 0

    def test_checkpoint_order_skipped_check1(self, tmp_path):
        """If daemon was down and 18h passed, check_1 runs FIRST (not check_2)."""
        video = make_video(hours_ago=20)  # no checks completed
        monitor, _ = make_monitor(tmp_path)

        # With 10 views at 20h, check_1 should fire first (dead < 50)
        result = monitor._evaluate_checkpoint(video, views=10, hours_elapsed=20)
        assert result == "swap_immediate"
        assert video.checks_completed == ["check_1"]
        # check_2 NOT evaluated yet

    def test_checkpoint_order_skipped_to_48h(self, tmp_path):
        """If daemon was down for 2 days, check_1 still runs first."""
        video = make_video(hours_ago=50)
        monitor, _ = make_monitor(tmp_path)

        result = monitor._evaluate_checkpoint(video, views=5, hours_elapsed=50)
        assert result == "swap_immediate"
        assert video.checks_completed == ["check_1"]

    def test_check_not_repeated(self, tmp_path):
        """A completed checkpoint is not re-evaluated."""
        video = make_video(hours_ago=10, checks_completed=["check_1"])
        monitor, _ = make_monitor(tmp_path)

        # check_1 already done, and not yet 18h → wait
        result = monitor._evaluate_checkpoint(video, views=30, hours_elapsed=10)
        assert result == "wait"

    def test_uncertain_at_check1_then_dead_at_check2(self, tmp_path):
        """Uncertain at 6h (100 views), then dead at 18h (still 100 views)."""
        video = make_video(hours_ago=7)
        monitor, _ = make_monitor(tmp_path)

        # check_1: uncertain
        r1 = monitor._evaluate_checkpoint(video, views=100, hours_elapsed=7)
        assert r1 == "wait"

        # check_2: same views, dead at 18h
        r2 = monitor._evaluate_checkpoint(video, views=100, hours_elapsed=19)
        assert r2 == "swap_window"


# ============================================================================
# 2. SWAP LOGIC
# ============================================================================


class TestSwapLogic:
    """Test _can_swap, _execute_swap, and variant rotation."""

    def test_can_swap_from_a(self, tmp_path):
        """Video on A with B available → can swap."""
        video = make_video(variant="A")
        monitor, _ = make_monitor(tmp_path)
        assert monitor._can_swap(video) is True

    def test_can_swap_from_c(self, tmp_path):
        """Video on C with D available → can swap."""
        video = make_video(variant="C")
        monitor, _ = make_monitor(tmp_path)
        assert monitor._can_swap(video) is True

    def test_cannot_swap_from_d(self, tmp_path):
        """Video on D → no next variant → cannot swap."""
        video = make_video(variant="D")
        monitor, _ = make_monitor(tmp_path)
        assert monitor._can_swap(video) is False

    def test_cannot_swap_max_swaps_reached(self, tmp_path):
        """3 swaps done (A→B→C→D) → cannot swap."""
        swaps = [
            SwapRecord(from_variant="A", to_variant="B", views_at_swap=10, reason="dead"),
            SwapRecord(from_variant="B", to_variant="C", views_at_swap=15, reason="dead"),
            SwapRecord(from_variant="C", to_variant="D", views_at_swap=20, reason="dead"),
        ]
        video = make_video(variant="D", swap_history=swaps)
        monitor, _ = make_monitor(tmp_path)
        assert monitor._can_swap(video) is False

    def test_cannot_swap_invalid_variant(self, tmp_path):
        """Corrupted current_variant → cannot swap (no crash)."""
        video = make_video(variant="Z")
        monitor, _ = make_monitor(tmp_path)
        assert monitor._can_swap(video) is False

    def test_cannot_swap_next_variant_missing(self, tmp_path):
        """On A but only A available (no B) → cannot swap."""
        video = make_video(variant="A", variants_letters="A")
        monitor, _ = make_monitor(tmp_path)
        assert monitor._can_swap(video) is False

    def test_execute_swap_a_to_b(self, tmp_path):
        """Swap from A to B: updates YouTube, records swap, resets timer."""
        video = make_video(variant="A", hours_ago=7)
        monitor, store = make_monitor(tmp_path, videos=[video])
        yt = make_youtube_mock()

        result = monitor._execute_swap(video, yt, views_at_swap=30, decision="check_1_dead")

        assert result == "swap_B"
        assert video.current_variant == "B"
        assert len(video.swap_history) == 1
        assert video.swap_history[0].from_variant == "A"
        assert video.swap_history[0].to_variant == "B"
        assert video.swap_history[0].views_at_swap == 30
        assert video.checks_completed == []  # reset on swap
        yt.update_video.assert_called_once()

    def test_execute_swap_rotates_comment(self, tmp_path):
        """Swap deletes old comment and posts new one."""
        video = make_video(variant="A", hours_ago=7)
        video.current_comment_id = "old_comment_id"
        monitor, store = make_monitor(tmp_path, videos=[video])
        yt = make_youtube_mock()

        monitor._execute_swap(video, yt, views_at_swap=30, decision="dead")

        yt.delete_comment.assert_called_once_with("old_comment_id")
        yt.insert_comment_thread.assert_called_once()

    def test_execute_swap_youtube_api_fails(self, tmp_path):
        """If YouTube update fails → status MANUAL, no swap recorded."""
        video = make_video(variant="A", hours_ago=7)
        monitor, store = make_monitor(tmp_path, videos=[video])
        yt = make_youtube_mock()
        yt.update_video.return_value = (False, "quota exceeded")

        result = monitor._execute_swap(video, yt, views_at_swap=30, decision="dead")

        assert "error_update" in result
        assert video.status == ABStatus.MANUAL
        assert len(video.swap_history) == 0  # swap NOT recorded
        assert video.current_variant == "A"  # NOT changed

    def test_execute_swap_invalid_variant_error(self, tmp_path):
        """Corrupted current_variant during swap → error, status MANUAL."""
        video = make_video(variant="Z")
        monitor, store = make_monitor(tmp_path, videos=[video])
        yt = make_youtube_mock()

        result = monitor._execute_swap(video, yt, views_at_swap=0, decision="dead")

        assert result == "error_invalid_variant"
        assert video.status == ABStatus.MANUAL

    def test_sequential_swaps_a_b_c_d(self, tmp_path):
        """Full rotation: A→B→C→D, then exhausted."""
        video = make_video(variant="A")
        monitor, store = make_monitor(tmp_path, videos=[video])
        yt = make_youtube_mock()

        # Swap A→B
        r1 = monitor._execute_swap(video, yt, 10, "dead")
        assert r1 == "swap_B"
        assert video.current_variant == "B"

        # Swap B→C
        r2 = monitor._execute_swap(video, yt, 20, "dead")
        assert r2 == "swap_C"
        assert video.current_variant == "C"

        # Swap C→D
        r3 = monitor._execute_swap(video, yt, 30, "dead")
        assert r3 == "swap_D"
        assert video.current_variant == "D"

        # No more swaps
        assert monitor._can_swap(video) is False
        assert len(video.swap_history) == 3


# ============================================================================
# 3. FULL EVALUATE_VIDEO FLOW
# ============================================================================


class TestEvaluateVideo:
    """Test _evaluate_video end-to-end with mocked YouTube API."""

    def _setup(self, tmp_path, video, views=100):
        monitor, store = make_monitor(tmp_path, videos=[video])
        yt = make_youtube_mock(views=views)
        monitor._get_youtube_api = Mock(return_value=yt)
        return monitor, store, yt

    def test_dead_at_6h_swaps_immediately(self, tmp_path):
        """30 views at 7h → check_1 dead → immediate swap to B."""
        video = make_video(hours_ago=7)
        monitor, store, yt = self._setup(tmp_path, video, views=30)

        result = monitor._evaluate_video(video)

        assert result == "swap_B"
        assert video.current_variant == "B"

    def test_alive_at_6h_success(self, tmp_path):
        """300 views at 7h → alive → status SUCCESS."""
        video = make_video(hours_ago=7)
        monitor, store, yt = self._setup(tmp_path, video, views=300)

        result = monitor._evaluate_video(video)

        assert result == "success"
        assert video.status == ABStatus.SUCCESS
        assert video.final_variant == "A"
        assert video.final_views_48h == 300

    def test_uncertain_at_6h_keeps_monitoring(self, tmp_path):
        """100 views at 7h → uncertain → keep monitoring."""
        video = make_video(hours_ago=7)
        monitor, store, yt = self._setup(tmp_path, video, views=100)

        result = monitor._evaluate_video(video)

        assert result == "keep"
        assert video.status == ABStatus.MONITORING

    def test_dead_at_18h_deferred_outside_window(self, tmp_path):
        """Dead at 18h, outside swap window → deferred."""
        video = make_video(hours_ago=19, checks_completed=["check_1"])
        monitor, store, yt = self._setup(tmp_path, video, views=50)
        monitor._is_swap_window = Mock(return_value=False)

        result = monitor._evaluate_video(video)

        assert result == "swap_deferred"
        assert video.current_variant == "A"  # no swap yet

    def test_dead_at_18h_swaps_in_window(self, tmp_path):
        """Dead at 18h, inside swap window → swap."""
        video = make_video(hours_ago=19, checks_completed=["check_1"])
        monitor, store, yt = self._setup(tmp_path, video, views=50)
        monitor._is_swap_window = Mock(return_value=True)

        result = monitor._evaluate_video(video)

        assert result == "swap_B"

    def test_final_dead_48h_last_chance_swap(self, tmp_path):
        """Dead at 48h with variants remaining → last-chance swap (immediate)."""
        video = make_video(
            hours_ago=49,
            checks_completed=["check_1", "check_2"],
        )
        monitor, store, yt = self._setup(tmp_path, video, views=100)

        result = monitor._evaluate_video(video)

        assert result == "swap_B"
        assert video.swap_history[-1].reason == "last_chance_48h"

    def test_final_dead_48h_exhausted(self, tmp_path):
        """Dead at 48h, on variant D (no more) → exhausted."""
        swaps = [
            SwapRecord(from_variant="A", to_variant="B", views_at_swap=10, reason="d"),
            SwapRecord(from_variant="B", to_variant="C", views_at_swap=10, reason="d"),
            SwapRecord(from_variant="C", to_variant="D", views_at_swap=10, reason="d"),
        ]
        video = make_video(
            variant="D",
            hours_ago=49,
            checks_completed=["check_1", "check_2"],
            swap_history=swaps,
        )
        monitor, store, yt = self._setup(tmp_path, video, views=100)

        result = monitor._evaluate_video(video)

        assert result == "exhausted"
        assert video.status == ABStatus.EXHAUSTED
        assert video.final_variant == "D"

    def test_no_api_returns_no_api(self, tmp_path):
        """No YouTube API for channel → no_api."""
        video = make_video(hours_ago=7)
        monitor, store = make_monitor(tmp_path, videos=[video])
        monitor._get_youtube_api = Mock(return_value=None)

        result = monitor._evaluate_video(video)
        assert result == "no_api"

    def test_video_not_found_error(self, tmp_path):
        """YouTube API returns None stats → error."""
        video = make_video(hours_ago=7)
        monitor, store = make_monitor(tmp_path, videos=[video])
        yt = make_youtube_mock()
        yt.get_video_stats.return_value = None
        monitor._get_youtube_api = Mock(return_value=yt)

        result = monitor._evaluate_video(video)

        assert result == "error_not_found"
        assert video.status == ABStatus.ERROR

    def test_negative_hours_reset(self, tmp_path):
        """variant_start_time in future → reset to now, hours = 0 → wait."""
        video = make_video(hours_ago=-5)  # 5 hours in the future
        monitor, store, yt = self._setup(tmp_path, video, views=1000)

        result = monitor._evaluate_video(video)

        # After reset, hours_elapsed ≈ 0, so no checkpoint triggers → wait/keep
        assert result == "keep"

    def test_metrics_logged(self, tmp_path):
        """Every evaluation logs a MetricsSnapshot."""
        video = make_video(hours_ago=3)
        monitor, store, yt = self._setup(tmp_path, video, views=42)

        monitor._evaluate_video(video)

        assert len(video.metrics_log) == 1
        assert video.metrics_log[0].views == 42


# ============================================================================
# 4. FULL CYCLE (run_cycle)
# ============================================================================


class TestRunCycle:
    """Test run_cycle with multiple videos."""

    def test_empty_store(self, tmp_path):
        """No videos → empty results."""
        monitor, _ = make_monitor(tmp_path)
        results = monitor.run_cycle()
        assert results == {}

    def test_multiple_videos(self, tmp_path):
        """Two active videos processed in one cycle."""
        v1 = make_video(video_id="vid_1", hours_ago=7)
        v2 = make_video(video_id="vid_2", hours_ago=3)
        monitor, store = make_monitor(tmp_path, videos=[v1, v2])

        yt = make_youtube_mock(views=30)
        monitor._get_youtube_api = Mock(return_value=yt)

        results = monitor.run_cycle()

        assert "vid_1" in results
        assert "vid_2" in results
        # vid_1: 7h with 30 views → dead → swap
        assert results["vid_1"] == "swap_B"
        # vid_2: 3h → no checkpoint yet → keep
        assert results["vid_2"] == "keep"

    def test_skips_non_monitoring(self, tmp_path):
        """Videos with status != MONITORING are skipped."""
        v1 = make_video(video_id="vid_1", status=ABStatus.SUCCESS)
        v2 = make_video(video_id="vid_2", status=ABStatus.MONITORING, hours_ago=3)
        monitor, store = make_monitor(tmp_path, videos=[v1, v2])

        yt = make_youtube_mock(views=100)
        monitor._get_youtube_api = Mock(return_value=yt)

        results = monitor.run_cycle()

        # v1 is SUCCESS so not in active list
        assert "vid_1" not in results
        assert "vid_2" in results

    def test_error_in_one_video_doesnt_stop_others(self, tmp_path):
        """Exception in one video doesn't prevent processing others."""
        v1 = make_video(video_id="vid_1", hours_ago=7)
        v2 = make_video(video_id="vid_2", hours_ago=7)
        monitor, store = make_monitor(tmp_path, videos=[v1, v2])

        call_count = 0
        def mock_evaluate(video):
            nonlocal call_count
            call_count += 1
            if video.video_id == "vid_1":
                raise RuntimeError("API explosion")
            return "keep"

        monitor._evaluate_video = mock_evaluate

        results = monitor.run_cycle()

        assert "error" in results["vid_1"]
        assert results["vid_2"] == "keep"


# ============================================================================
# 5. STORE OPERATIONS
# ============================================================================


class TestABStore:
    """Test ABStore persistence and resilience."""

    def test_register_and_retrieve(self, tmp_path):
        """Register a video and retrieve it."""
        store = ABStore(config_dir=tmp_path)
        video = make_video(video_id="v1")
        store.register_video(video)

        retrieved = store.get_video("v1")
        assert retrieved is not None
        assert retrieved.video_id == "v1"
        assert retrieved.current_variant == "A"

    def test_update_video(self, tmp_path):
        """Update a video's status."""
        store = ABStore(config_dir=tmp_path)
        video = make_video(video_id="v1")
        store.register_video(video)

        video.status = ABStatus.SUCCESS
        store.update_video(video)

        retrieved = store.get_video("v1")
        assert retrieved.status == ABStatus.SUCCESS

    def test_stop_video(self, tmp_path):
        """Stop monitoring a video."""
        store = ABStore(config_dir=tmp_path)
        video = make_video(video_id="v1")
        store.register_video(video)

        result = store.stop_video("v1")
        assert result is True

        retrieved = store.get_video("v1")
        assert retrieved.status == ABStatus.STOPPED

    def test_stop_nonexistent(self, tmp_path):
        """Stop a video that doesn't exist."""
        store = ABStore(config_dir=tmp_path)
        result = store.stop_video("nonexistent")
        assert result is False

    def test_get_active_videos(self, tmp_path):
        """Only MONITORING videos returned as active."""
        store = ABStore(config_dir=tmp_path)

        v1 = make_video(video_id="v1", status=ABStatus.MONITORING)
        v2 = make_video(video_id="v2", status=ABStatus.SUCCESS)
        v3 = make_video(video_id="v3", status=ABStatus.MONITORING)
        store.register_video(v1)
        store.register_video(v2)
        store.register_video(v3)

        active = store.get_active_videos()
        assert len(active) == 2
        assert {v.video_id for v in active} == {"v1", "v3"}

    def test_persistence_across_instances(self, tmp_path):
        """Data survives creating a new ABStore instance."""
        store1 = ABStore(config_dir=tmp_path)
        store1.register_video(make_video(video_id="v1"))

        store2 = ABStore(config_dir=tmp_path)
        retrieved = store2.get_video("v1")
        assert retrieved is not None
        assert retrieved.video_id == "v1"

    def test_duplicate_registration_updates(self, tmp_path):
        """Re-registering same video_id updates, not duplicates."""
        store = ABStore(config_dir=tmp_path)
        v1 = make_video(video_id="v1", variant="A")
        store.register_video(v1)

        v1_updated = make_video(video_id="v1", variant="B")
        store.register_video(v1_updated)

        all_videos = store.get_all_videos()
        assert len(all_videos) == 1
        assert all_videos[0].current_variant == "B"

    def test_corrupted_file_recovery(self, tmp_path):
        """Corrupted main file → recover from backup."""
        store = ABStore(config_dir=tmp_path)
        store.register_video(make_video(video_id="v1"))

        # Create a second save to generate .bak
        store.register_video(make_video(video_id="v2"))

        # Corrupt main file
        state_path = tmp_path / "ab_rotation.json"
        state_path.write_text("{broken!", encoding="utf-8")

        # New instance should recover from .bak (has v1 only)
        store2 = ABStore(config_dir=tmp_path)
        loaded = store2.load()
        assert len(loaded.videos) == 1
        assert loaded.videos[0].video_id == "v1"

    def test_empty_file_recovery(self, tmp_path):
        """Empty main file → try backup, else empty store."""
        state_path = tmp_path / "ab_rotation.json"
        state_path.write_text("", encoding="utf-8")

        store = ABStore(config_dir=tmp_path)
        loaded = store.load()
        assert len(loaded.videos) == 0

    def test_metrics_append(self, tmp_path):
        """Metrics append to JSONL file."""
        store = ABStore(config_dir=tmp_path)
        snapshot = MetricsSnapshot(views=100, likes=5, comments=2)
        store.append_metrics("v1", snapshot)

        metrics_path = tmp_path / "ab_metrics.jsonl"
        assert metrics_path.exists()

        with open(metrics_path, "r") as f:
            lines = f.readlines()
        assert len(lines) == 1

        entry = json.loads(lines[0])
        assert entry["video_id"] == "v1"
        assert entry["views"] == 100

    def test_atomic_save_no_leftover_tmp(self, tmp_path):
        """After save, no .tmp file remains."""
        store = ABStore(config_dir=tmp_path)
        store.register_video(make_video(video_id="v1"))

        tmp_file = tmp_path / "ab_rotation.json.tmp"
        assert not tmp_file.exists()


# ============================================================================
# 6. parse_metadata_variants UTILITY
# ============================================================================


class TestParseMetadataVariants:
    """Test the shared parse_metadata_variants function."""

    def test_full_4_variants(self):
        """All 4 variants valid → 4 returned."""
        data = {
            "metadata_variants": {
                "variant_a": {"trigger": "X", "title": "A", "description": "Da"},
                "variant_b": {"trigger": "Y", "title": "B", "description": "Db"},
                "variant_c": {"trigger": "Z", "title": "C", "description": "Dc"},
                "variant_d": {"trigger": "W", "title": "D", "description": "Dd"},
            }
        }
        variants, warnings = parse_metadata_variants(data)
        assert len(variants) == 4
        assert len(warnings) == 0

    def test_empty_title_skipped(self):
        """Variant with empty title is skipped."""
        data = {
            "metadata_variants": {
                "variant_a": {"trigger": "X", "title": "A", "description": "D"},
                "variant_b": {"trigger": "Y", "title": "  ", "description": "D"},
            }
        }
        variants, warnings = parse_metadata_variants(data)
        assert len(variants) == 1
        assert "A" in variants
        assert len(warnings) == 1

    def test_no_metadata_variants_key(self):
        """No metadata_variants → empty dict + warning."""
        variants, warnings = parse_metadata_variants({})
        assert len(variants) == 0
        assert len(warnings) == 1

    def test_pinned_comment_optional(self):
        """pinned_comment is optional (None if missing)."""
        data = {
            "metadata_variants": {
                "variant_a": {"trigger": "X", "title": "A", "description": "D"},
            }
        }
        variants, _ = parse_metadata_variants(data)
        assert variants["A"].pinned_comment is None

    def test_trigger_defaults_to_letter(self):
        """Missing trigger → defaults to letter."""
        data = {
            "metadata_variants": {
                "variant_a": {"title": "A", "description": "D"},
            }
        }
        variants, _ = parse_metadata_variants(data)
        assert variants["A"].trigger == "A"

    def test_non_dict_variant_skipped(self):
        """Variant that is not a dict is silently skipped."""
        data = {
            "metadata_variants": {
                "variant_a": {"trigger": "X", "title": "A", "description": "D"},
                "variant_b": "invalid",
                "variant_c": None,
            }
        }
        variants, _ = parse_metadata_variants(data)
        assert len(variants) == 1


# ============================================================================
# 7. EDGE CASES & SCENARIOS
# ============================================================================


class TestEdgeCases:
    """Complex scenarios and edge cases."""

    def test_full_lifecycle_dead_video(self, tmp_path):
        """Simulate: dead at 6h → swap B → dead at 6h → swap C → alive at 18h."""
        video = make_video(hours_ago=7)
        monitor, store = make_monitor(tmp_path, videos=[video])
        yt = make_youtube_mock(views=10)
        monitor._get_youtube_api = Mock(return_value=yt)

        # Cycle 1: 7h, 10 views → dead → swap to B
        r1 = monitor._evaluate_video(video)
        assert r1 == "swap_B"
        assert video.current_variant == "B"
        assert video.checks_completed == []

        # Simulate 7 more hours
        video.variant_start_time = datetime.now(timezone.utc) - timedelta(hours=7)
        yt.get_video_stats.return_value = {"views": 20, "likes": 0, "comments": 0}

        # Cycle 2: 7h on B, 20 views → dead → swap to C
        r2 = monitor._evaluate_video(video)
        assert r2 == "swap_C"
        assert video.current_variant == "C"

        # Simulate 19 hours on C with good views
        video.variant_start_time = datetime.now(timezone.utc) - timedelta(hours=19)
        yt.get_video_stats.return_value = {"views": 800, "likes": 50, "comments": 10}

        # Cycle 3: 19h on C, 800 views → check_1 alive (>= 200)
        r3 = monitor._evaluate_video(video)
        assert r3 == "success"
        assert video.status == ABStatus.SUCCESS
        assert video.final_variant == "C"

    def test_all_variants_exhausted(self, tmp_path):
        """Every variant dies → final status EXHAUSTED."""
        video = make_video(hours_ago=7)
        monitor, store = make_monitor(tmp_path, videos=[video])
        yt = make_youtube_mock(views=5)
        monitor._get_youtube_api = Mock(return_value=yt)

        # Swap through A→B→C→D
        for expected_next in ["B", "C", "D"]:
            result = monitor._evaluate_video(video)
            assert result == f"swap_{expected_next}"
            # Reset timer for next cycle
            video.variant_start_time = datetime.now(timezone.utc) - timedelta(hours=7)

        # Now on D, dead again → exhausted
        video.variant_start_time = datetime.now(timezone.utc) - timedelta(hours=7)
        result = monitor._evaluate_video(video)
        assert result == "exhausted"
        assert video.status == ABStatus.EXHAUSTED

    def test_swap_window_respected_for_check2(self, tmp_path):
        """Check 2 dead → only swaps inside window."""
        video = make_video(hours_ago=19, checks_completed=["check_1"])
        monitor, store = make_monitor(tmp_path, videos=[video])
        yt = make_youtube_mock(views=50)
        monitor._get_youtube_api = Mock(return_value=yt)

        # Outside window → deferred
        monitor._is_swap_window = Mock(return_value=False)
        r1 = monitor._evaluate_video(video)
        assert r1 == "swap_deferred"
        assert video.current_variant == "A"

        # Reset for second try (check_2 already completed, so need fresh video)
        video2 = make_video(hours_ago=19, checks_completed=["check_1"])
        store.register_video(video2)
        monitor._is_swap_window = Mock(return_value=True)
        r2 = monitor._evaluate_video(video2)
        assert r2 == "swap_B"

    def test_check1_dead_ignores_swap_window(self, tmp_path):
        """Check 1 dead → swap_immediate, doesn't check window."""
        video = make_video(hours_ago=7)
        monitor, store = make_monitor(tmp_path, videos=[video])
        yt = make_youtube_mock(views=10)
        monitor._get_youtube_api = Mock(return_value=yt)
        monitor._is_swap_window = Mock(return_value=False)

        result = monitor._evaluate_video(video)

        assert result == "swap_B"  # swaps regardless of window
        monitor._is_swap_window.assert_not_called()

    def test_check_single_cli(self, tmp_path):
        """check_single (CLI command) works correctly."""
        video = make_video(video_id="vid_cli", hours_ago=7)
        monitor, store = make_monitor(tmp_path, videos=[video])
        yt = make_youtube_mock(views=300)
        monitor._get_youtube_api = Mock(return_value=yt)

        result = monitor.check_single("vid_cli")
        assert result == "success"

    def test_check_single_not_found(self, tmp_path):
        """check_single for nonexistent video → message."""
        monitor, _ = make_monitor(tmp_path)
        result = monitor.check_single("nonexistent")
        assert "not found" in result

    def test_check_single_not_monitoring(self, tmp_path):
        """check_single for video not in MONITORING → message."""
        video = make_video(video_id="v1", status=ABStatus.SUCCESS)
        monitor, store = make_monitor(tmp_path, videos=[video])
        result = monitor.check_single("v1")
        assert "not being monitored" in result

    def test_variant_start_time_resets_on_swap(self, tmp_path):
        """After swap, variant_start_time is recent (within 5 seconds)."""
        video = make_video(hours_ago=7)
        monitor, store = make_monitor(tmp_path, videos=[video])
        yt = make_youtube_mock(views=10)

        before_swap = datetime.now(timezone.utc)
        monitor._execute_swap(video, yt, 10, "dead")
        after_swap = datetime.now(timezone.utc)

        assert before_swap <= video.variant_start_time <= after_swap
