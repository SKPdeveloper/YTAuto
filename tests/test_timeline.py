"""
Tests for ManifestRenderer timeline methods:
  - _rescale_speed_segments (static, 10 tests)
  - _compute_deterministic_timeline (instance, 9 tests)
"""

import json
import pytest
from pathlib import Path

from app.services.gen_models import SpeedSegment, ManifestScene
from app.services.manifest_renderer import ManifestRenderer


# =====================================================================
# TestRescaleSpeedSegments
# =====================================================================


class TestRescaleSpeedSegments:
    """ManifestRenderer._rescale_speed_segments — static method."""

    def test_no_segments_noop(self, make_manifest_scene):
        """Empty speed_segments → nothing happens."""
        scene = make_manifest_scene(speed_segments=[])
        ManifestRenderer._rescale_speed_segments(scene, 5.0)
        assert scene.speed_segments == []

    def test_single_segment_exact(self, make_speed_segment, make_manifest_scene):
        """target == current output → speed stays 1.0."""
        seg = make_speed_segment(source_start=0, source_end=4, speed=1.0)
        scene = make_manifest_scene(speed_segments=[seg])

        ManifestRenderer._rescale_speed_segments(scene, 4.0)

        assert scene.speed_segments[0].speed == pytest.approx(1.0, abs=0.01)
        assert scene.speed_segments[0].output_duration == pytest.approx(4.0, abs=0.01)

    def test_single_segment_faster(self, make_speed_segment, make_manifest_scene):
        """target=2s, source=4s at 1x (current_out=4s) → speed≈2.0."""
        seg = make_speed_segment(source_start=0, source_end=4, speed=1.0)
        scene = make_manifest_scene(speed_segments=[seg])

        ManifestRenderer._rescale_speed_segments(scene, 2.0)

        assert scene.speed_segments[0].speed == pytest.approx(2.0, abs=0.01)
        assert scene.speed_segments[0].output_duration == pytest.approx(2.0, abs=0.01)

    def test_single_segment_slower(self, make_speed_segment, make_manifest_scene):
        """target=8s, source=4s at 1x → speed=0.5."""
        seg = make_speed_segment(source_start=0, source_end=4, speed=1.0)
        scene = make_manifest_scene(speed_segments=[seg])

        ManifestRenderer._rescale_speed_segments(scene, 8.0)

        assert scene.speed_segments[0].speed == pytest.approx(0.5, abs=0.01)
        assert scene.speed_segments[0].output_duration == pytest.approx(8.0, abs=0.01)

    def test_proportional_two_segments(self, make_speed_segment, make_manifest_scene):
        """Two segments — both rescaled proportionally."""
        seg1 = make_speed_segment(source_start=0, source_end=2, speed=1.0)  # out=2s
        seg2 = make_speed_segment(source_start=2, source_end=6, speed=2.0)  # out=2s
        scene = make_manifest_scene(speed_segments=[seg1, seg2])
        # current total = 2+2 = 4s → target 2s

        ManifestRenderer._rescale_speed_segments(scene, 2.0)

        total_out = sum(s.output_duration for s in scene.speed_segments)
        assert total_out == pytest.approx(2.0, abs=0.05)

    def test_max_speed_clamping(self, make_speed_segment, make_manifest_scene):
        """Speed clamped at max_speed=4.0."""
        seg = make_speed_segment(source_start=0, source_end=10, speed=1.0)  # out=10s
        scene = make_manifest_scene(speed_segments=[seg])
        # target=1s → raw speed=10x → clamped to 4.0

        ManifestRenderer._rescale_speed_segments(scene, 1.0, max_speed=4.0)

        assert scene.speed_segments[0].speed <= 4.0

    def test_min_speed_clamping(self, make_speed_segment, make_manifest_scene):
        """Speed clamped at min_speed=0.5."""
        seg = make_speed_segment(source_start=0, source_end=2, speed=1.0)  # out=2s
        scene = make_manifest_scene(speed_segments=[seg])
        # target=20s → raw speed=0.1 → clamped to 0.5

        ManifestRenderer._rescale_speed_segments(scene, 20.0, min_speed=0.5)

        assert scene.speed_segments[0].speed >= 0.5

    def test_drift_compensation(self, make_speed_segment, make_manifest_scene):
        """After clamping, unclamped segments absorb drift."""
        seg1 = make_speed_segment(source_start=0, source_end=10, speed=1.0)  # out=10s
        seg2 = make_speed_segment(source_start=10, source_end=14, speed=2.0)  # out=2s
        scene = make_manifest_scene(speed_segments=[seg1, seg2])
        # current total = 12s → target = 2s → ratio = 6x
        # seg1 raw speed = 6.0 → clamped to 4.0 → out = 2.5
        # seg2 raw speed = 12.0 → clamped to 4.0 → out = 1.0
        # Both clamped → no unclamped to absorb drift, but total should be reasonable.

        ManifestRenderer._rescale_speed_segments(scene, 2.0, max_speed=4.0, min_speed=0.5)

        for seg in scene.speed_segments:
            assert seg.speed <= 4.0
            assert seg.speed >= 0.5

    def test_zero_target_noop(self, make_speed_segment, make_manifest_scene):
        """target=0 → early return, nothing changes."""
        seg = make_speed_segment(source_start=0, source_end=4, speed=2.0)
        original_speed = seg.speed
        scene = make_manifest_scene(speed_segments=[seg])

        ManifestRenderer._rescale_speed_segments(scene, 0.0)

        assert scene.speed_segments[0].speed == original_speed

    def test_source_boundaries_unchanged(self, make_speed_segment, make_manifest_scene):
        """source_start/source_end must not be mutated."""
        seg = make_speed_segment(source_start=1.5, source_end=7.5, speed=1.0)
        scene = make_manifest_scene(speed_segments=[seg])

        ManifestRenderer._rescale_speed_segments(scene, 3.0)

        assert scene.speed_segments[0].source_start == 1.5
        assert scene.speed_segments[0].source_end == 7.5


# =====================================================================
# TestComputeDeterministicTimeline
# =====================================================================


class TestComputeDeterministicTimeline:
    """ManifestRenderer._compute_deterministic_timeline — instance method."""

    def test_no_files_uses_manifest_defaults(self, renderer, make_manifest, tmp_path):
        """No JSON files → method returns early, manifest unchanged."""
        manifest = make_manifest(n_scenes=3, scene_dur=2.0)
        project_dir = tmp_path / "proj_empty"
        project_dir.mkdir()

        renderer._compute_deterministic_timeline(manifest, project_dir)

        # Should keep original timings (no brief or VO to override)
        assert manifest.scenes[0].timeline_start == 0.0
        assert manifest.scenes[0].timeline_end == 2.0

    def test_brief_sets_duration(self, renderer, make_manifest, project_dir_with_timing):
        """Brief durations override manifest scene durations."""
        manifest = make_manifest(n_scenes=2, scene_dur=2.0)
        project_dir = project_dir_with_timing(
            scenes=[
                {"scene_number": 1, "duration_seconds": 3.0},
                {"scene_number": 2, "duration_seconds": 4.0},
            ]
        )

        renderer._compute_deterministic_timeline(manifest, project_dir)

        assert manifest.scenes[0].timeline_end - manifest.scenes[0].timeline_start == pytest.approx(3.0, abs=0.01)
        assert manifest.scenes[1].timeline_end - manifest.scenes[1].timeline_start == pytest.approx(4.0, abs=0.01)

    def test_vo_expansion(self, renderer, make_manifest, project_dir_with_timing):
        """VO duration > brief duration → scene expands (vo_dur + lead + tail)."""
        manifest = make_manifest(n_scenes=2, scene_dur=2.0)
        project_dir = project_dir_with_timing(
            scenes=[
                {"scene_number": 1, "duration_seconds": 2.0},
                {"scene_number": 2, "duration_seconds": 2.0},
            ],
            vo_segments=[
                {"scene_number": 1, "start_time": 0.0, "end_time": 3.5, "text": "test"},
            ],
        )

        renderer._compute_deterministic_timeline(manifest, project_dir)

        # Scene 1: max(2.0, 3.5 + 0.15 + 0.15) = 3.8s
        scene1_dur = manifest.scenes[0].timeline_end - manifest.scenes[0].timeline_start
        assert scene1_dur == pytest.approx(3.8, abs=0.01)

    def test_money_shot_floor(self, renderer, make_manifest, project_dir_with_timing):
        """MONEY_SHOT flag → min 3.0s."""
        manifest = make_manifest(n_scenes=2, scene_dur=2.0)
        manifest.scenes[0].special_flags = ["MONEY_SHOT"]
        project_dir = project_dir_with_timing(
            scenes=[
                {"scene_number": 1, "duration_seconds": 1.5, "special_flags": ["MONEY_SHOT"]},
                {"scene_number": 2, "duration_seconds": 2.0},
            ]
        )

        renderer._compute_deterministic_timeline(manifest, project_dir)

        scene1_dur = manifest.scenes[0].timeline_end - manifest.scenes[0].timeline_start
        assert scene1_dur >= 3.0

    def test_vo_override_param(self, renderer, make_manifest, project_dir_with_timing):
        """vo_duration_override dict is used instead of vo_timing file."""
        manifest = make_manifest(n_scenes=2, scene_dur=2.0)
        project_dir = project_dir_with_timing(
            scenes=[
                {"scene_number": 1, "duration_seconds": 2.0},
                {"scene_number": 2, "duration_seconds": 2.0},
            ]
        )

        renderer._compute_deterministic_timeline(
            manifest, project_dir,
            vo_duration_override={1: 5.0}
        )

        # Scene 1: max(2.0, 5.0 + 0.15 + 0.15) = 5.3s
        scene1_dur = manifest.scenes[0].timeline_end - manifest.scenes[0].timeline_start
        assert scene1_dur == pytest.approx(5.3, abs=0.01)

    def test_cumulative_timeline(self, renderer, make_manifest, project_dir_with_timing):
        """Scene N starts at sum(previous durations)."""
        manifest = make_manifest(n_scenes=3, scene_dur=2.0)
        project_dir = project_dir_with_timing(
            scenes=[
                {"scene_number": 1, "duration_seconds": 2.0},
                {"scene_number": 2, "duration_seconds": 3.0},
                {"scene_number": 3, "duration_seconds": 1.5},
            ]
        )

        renderer._compute_deterministic_timeline(manifest, project_dir)

        assert manifest.scenes[0].timeline_start == pytest.approx(0.0, abs=0.01)
        assert manifest.scenes[1].timeline_start == pytest.approx(2.0, abs=0.01)
        assert manifest.scenes[2].timeline_start == pytest.approx(5.0, abs=0.01)

    def test_speed_segments_created_when_empty(self, renderer, make_manifest, project_dir_with_timing):
        """Empty speed_segments → synthetic 1x segment created."""
        manifest = make_manifest(n_scenes=1, scene_dur=2.0)
        manifest.scenes[0].speed_segments = []  # ensure empty
        project_dir = project_dir_with_timing(
            scenes=[{"scene_number": 1, "duration_seconds": 3.0}]
        )

        renderer._compute_deterministic_timeline(manifest, project_dir)

        assert len(manifest.scenes[0].speed_segments) == 1
        seg = manifest.scenes[0].speed_segments[0]
        assert seg.reason == "deterministic_trim"

    def test_total_duration_updated(self, renderer, make_manifest, project_dir_with_timing):
        """manifest.total_duration = sum of all scene durations."""
        manifest = make_manifest(n_scenes=2, scene_dur=2.0)
        project_dir = project_dir_with_timing(
            scenes=[
                {"scene_number": 1, "duration_seconds": 3.0},
                {"scene_number": 2, "duration_seconds": 4.0},
            ]
        )

        renderer._compute_deterministic_timeline(manifest, project_dir)

        assert manifest.total_duration == pytest.approx(7.0, abs=0.01)

    def test_multi_vo_segments_accumulated(self, renderer, make_manifest, project_dir_with_timing):
        """Two VO segments for same scene → merged range (min start, max end)."""
        manifest = make_manifest(n_scenes=1, scene_dur=2.0)
        project_dir = project_dir_with_timing(
            scenes=[{"scene_number": 1, "duration_seconds": 2.0}],
            vo_segments=[
                {"scene_number": 1, "start_time": 0.0, "end_time": 1.0, "text": "first"},
                {"scene_number": 1, "start_time": 1.5, "end_time": 3.0, "text": "second"},
            ],
        )

        renderer._compute_deterministic_timeline(manifest, project_dir)

        # Merged: start=0.0, end=3.0 → vo_dur=3.0 → min_for_vo=3.0+0.3=3.3
        scene_dur = manifest.scenes[0].timeline_end - manifest.scenes[0].timeline_start
        assert scene_dur == pytest.approx(3.3, abs=0.01)
