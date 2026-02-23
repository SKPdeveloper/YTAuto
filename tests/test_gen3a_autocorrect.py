"""
Tests for GEN3a Auto-Corrector v1.0

30 tests covering all 16 auto-fixes across 5 phases.
"""

import copy
import pytest

from app.services.gen3a_autocorrect import (
    autocorrect_gen3a,
    _fix_scene_list_key,
    _fix_scene_numbers,
    _fix_metadata_types,
    _fix_speed_map_nesting,
    _fix_speed_map_coverage,
    _fix_speed_map_boundaries,
    _fix_output_duration_recalc,
    _fix_total_duration_range,
    _fix_special_flags_hook,
    _fix_special_flags_loop,
    _fix_special_flags_easter,
    _fix_action_peak_timestamps,
    _fix_sfx_recommendation,
    _fix_sfx_from_gen1_brief,
    _fix_loop_duration_match,
    _fix_gen3b_handoff,
    ACTION_PEAK_SFX_MAP,
)
from app.services.gen1_autocorrect import AutoFixWarning


# ---------------------------------------------------------------------------
# FIXTURES
# ---------------------------------------------------------------------------

def _make_speed_segment(start=0.0, end=10.0, speed=2.5):
    return {
        "source_start": start,
        "source_end": end,
        "speed": speed,
        "output_duration": round((end - start) / speed, 4),
        "reason": "test",
        "motion_density": "MEDIUM",
        "technique": "NORMAL",
    }


def _make_scene(num, speed=2.5, source_dur=10.0, peaks=None, flags=None):
    return {
        "scene_number": num,
        "source_duration": source_dur,
        "output_duration": round(source_dur / speed, 4),
        "speed_map": [_make_speed_segment(0.0, source_dur, speed)],
        "action_peaks": peaks or [],
        "special_flags": flags or [],
        "video_quality": 0.85,
    }


def _make_gen3a_data(num_scenes=8):
    scenes = [_make_scene(i + 1) for i in range(num_scenes)]
    return {
        "version": "1.6.0",
        "scenes": scenes,
        "gen3b_handoff": {},
    }


def _make_gen1_brief(num_scenes=8, easter_egg_scene=5):
    return {
        "scenes": [
            {"scene_number": i + 1, "voiceover_segment": f"Scene {i + 1} voiceover."}
            for i in range(num_scenes)
        ],
        "easter_egg": {"scene_number": easter_egg_scene, "object": "tiny rubber duck"},
        "audio": {
            "sfx_per_scene": [
                {"scene_number": i + 1, "sfx": f"impact_{i + 1}"}
                for i in range(num_scenes)
            ],
        },
    }


# ---------------------------------------------------------------------------
# PHASE 1: STRUCTURAL
# ---------------------------------------------------------------------------

class TestPhase1Structural:
    """Tests for structural fixes."""

    def test_fix_scene_list_key_scene_analysis(self):
        """Fix #1: scene_analysis → scenes."""
        d = {"scene_analysis": [{"scene_number": 1}]}
        w = []
        _fix_scene_list_key(d, w)
        assert "scenes" in d
        assert "scene_analysis" not in d
        assert len(w) == 1

    def test_fix_scene_list_key_already_correct(self):
        """Fix #1: No change when key is already 'scenes'."""
        d = {"scenes": [{"scene_number": 1}]}
        w = []
        _fix_scene_list_key(d, w)
        assert len(w) == 0

    def test_fix_scene_numbers_null(self):
        """Fix #2: null scene_number → sequential int."""
        scenes = [{"scene_number": None}, {"scene_number": None}]
        w = []
        _fix_scene_numbers(scenes, w)
        assert scenes[0]["scene_number"] == 1
        assert scenes[1]["scene_number"] == 2

    def test_fix_scene_numbers_string(self):
        """Fix #2: string scene_number → int."""
        scenes = [{"scene_number": "Scene 3"}]
        w = []
        _fix_scene_numbers(scenes, w)
        assert scenes[0]["scene_number"] == 3

    def test_fix_scene_numbers_zero_based(self):
        """Fix #2: 0-based → 1-based."""
        scenes = [{"scene_number": 0}, {"scene_number": 1}]
        w = []
        _fix_scene_numbers(scenes, w)
        assert scenes[0]["scene_number"] == 1
        assert scenes[1]["scene_number"] == 2

    def test_fix_metadata_types_version(self):
        """Fix #3: version cast to str."""
        d = {"version": 1.6}
        w = []
        _fix_metadata_types(d, w)
        assert d["version"] == "1.6"
        assert isinstance(d["version"], str)

    def test_fix_speed_map_nesting(self):
        """Fix #4: Extract from speed_analysis.speed_map."""
        scenes = [{
            "scene_number": 1,
            "speed_analysis": {"speed_map": [_make_speed_segment()]},
        }]
        w = []
        _fix_speed_map_nesting(scenes, w)
        assert len(scenes[0]["speed_map"]) == 1
        assert len(w) == 1


# ---------------------------------------------------------------------------
# PHASE 2: SPEED MAP INTEGRITY
# ---------------------------------------------------------------------------

class TestPhase2SpeedMap:
    """Tests for speed map integrity fixes."""

    def test_fix_speed_map_coverage_empty(self):
        """Fix #5: Empty speed_map → default 2.5x segment."""
        scenes = [{"scene_number": 1, "source_duration": 10.0, "speed_map": []}]
        w = []
        _fix_speed_map_coverage(scenes, w)
        assert len(scenes[0]["speed_map"]) == 1
        seg = scenes[0]["speed_map"][0]
        assert seg["source_start"] == 0.0
        assert seg["source_end"] == 10.0
        assert seg["speed"] == 2.5

    def test_fix_speed_map_coverage_gap_start(self):
        """Fix #5: Fill gap at beginning of speed_map."""
        scenes = [{
            "scene_number": 1,
            "source_duration": 10.0,
            "speed_map": [_make_speed_segment(3.0, 10.0, 2.5)],
        }]
        w = []
        _fix_speed_map_coverage(scenes, w)
        assert scenes[0]["speed_map"][0]["source_start"] == 0.0
        assert scenes[0]["speed_map"][0]["source_end"] == 3.0

    def test_fix_speed_map_coverage_gap_end(self):
        """Fix #5: Fill gap at end of speed_map."""
        scenes = [{
            "scene_number": 1,
            "source_duration": 10.0,
            "speed_map": [_make_speed_segment(0.0, 7.0, 2.5)],
        }]
        w = []
        _fix_speed_map_coverage(scenes, w)
        assert scenes[0]["speed_map"][-1]["source_end"] == 10.0

    def test_fix_speed_map_boundaries_inverted(self):
        """Fix #6: Inverted boundaries (end < start)."""
        scenes = [{
            "scene_number": 1,
            "source_duration": 10.0,
            "speed_map": [{"source_start": 5.0, "source_end": 3.0, "speed": 2.5}],
        }]
        w = []
        _fix_speed_map_boundaries(scenes, w)
        seg = scenes[0]["speed_map"][0]
        assert seg["source_end"] > seg["source_start"]

    def test_fix_speed_map_boundaries_min_speed(self):
        """Fix #6: Speed below minimum (1.5) → clamped."""
        scenes = [{
            "scene_number": 1,
            "source_duration": 10.0,
            "speed_map": [{"source_start": 0.0, "source_end": 10.0, "speed": 0.8}],
        }]
        w = []
        _fix_speed_map_boundaries(scenes, w)
        assert scenes[0]["speed_map"][0]["speed"] == 1.5

    def test_fix_output_duration_recalc(self):
        """Fix #7: Recalculate output_duration from source/speed."""
        scenes = [{
            "scene_number": 1,
            "output_duration": 999.0,
            "speed_map": [_make_speed_segment(0.0, 10.0, 2.5)],
        }]
        w = []
        _fix_output_duration_recalc(scenes, w)
        assert abs(scenes[0]["output_duration"] - 4.0) < 0.01

    def test_fix_total_duration_range_too_long(self):
        """Fix #8: Scale speeds when total > 25s."""
        # 10 scenes at speed 1.5 → 10 * (10/1.5) = 66.7s → scale down
        scenes = [_make_scene(i + 1, speed=1.5) for i in range(10)]
        w = []
        _fix_total_duration_range(scenes, w)
        total = sum(s["output_duration"] for s in scenes)
        assert 18.0 <= total <= 25.0

    def test_fix_total_duration_range_within(self):
        """Fix #8: No change when total is within [18, 25]."""
        scenes = [_make_scene(i + 1, speed=4.5) for i in range(8)]
        total_before = sum(s["output_duration"] for s in scenes)
        w = []
        # total = 8 * (10/4.5) ≈ 17.8 — just under. Let's use speed=4.0 → 8*2.5=20
        scenes = [_make_scene(i + 1, speed=4.0) for i in range(8)]
        total_before = sum(s["output_duration"] for s in scenes)
        _fix_total_duration_range(scenes, w)
        total_after = sum(s["output_duration"] for s in scenes)
        assert abs(total_before - total_after) < 0.01
        assert len(w) == 0


# ---------------------------------------------------------------------------
# PHASE 3: SPECIAL FLAGS
# ---------------------------------------------------------------------------

class TestPhase3SpecialFlags:
    """Tests for special flag fixes."""

    def test_fix_hook_scene_flag(self):
        """Fix #9: Scene 1 gets HOOK_SCENE flag."""
        scenes = [{"scene_number": 1, "special_flags": []}]
        w = []
        _fix_special_flags_hook(scenes, w)
        assert "HOOK_SCENE" in scenes[0]["special_flags"]

    def test_fix_hook_scene_already_present(self):
        """Fix #9: No duplicate when HOOK_SCENE already present."""
        scenes = [{"scene_number": 1, "special_flags": ["HOOK_SCENE"]}]
        w = []
        _fix_special_flags_hook(scenes, w)
        assert scenes[0]["special_flags"].count("HOOK_SCENE") == 1
        assert len(w) == 0

    def test_fix_loop_scene_flag(self):
        """Fix #10: Last scene gets LOOP_SCENE flag."""
        scenes = [
            {"scene_number": 1, "special_flags": []},
            {"scene_number": 8, "special_flags": []},
        ]
        w = []
        _fix_special_flags_loop(scenes, w)
        assert "LOOP_SCENE" in scenes[-1]["special_flags"]

    def test_fix_easter_egg_flag(self):
        """Fix #11: Easter egg scene gets EASTER_EGG_SCENE flag."""
        scenes = [_make_scene(i + 1) for i in range(8)]
        gen1 = _make_gen1_brief(8, easter_egg_scene=5)
        w = []
        _fix_special_flags_easter(scenes, gen1, w)
        assert "EASTER_EGG_SCENE" in scenes[4]["special_flags"]


# ---------------------------------------------------------------------------
# PHASE 4: SFX & ACTION PEAKS
# ---------------------------------------------------------------------------

class TestPhase4SFX:
    """Tests for SFX and action peak fixes."""

    def test_fix_action_peak_timestamps_clamp(self):
        """Fix #12: Clamp out-of-range timestamp."""
        scenes = [{
            "scene_number": 1,
            "source_duration": 10.0,
            "action_peaks": [
                {"id": "S1_AP1", "source_timestamp": 12.0, "type": "MOTION_PEAK",
                 "intensity": 0.8, "beat_aligned": False, "nearest_beat": 0.0},
            ],
        }]
        w = []
        _fix_action_peak_timestamps(scenes, w)
        assert scenes[0]["action_peaks"][0]["source_timestamp"] == 10.0

    def test_fix_action_peak_dedup(self):
        """Fix #12: Remove peaks within 0.5s of each other."""
        scenes = [{
            "scene_number": 1,
            "source_duration": 10.0,
            "action_peaks": [
                {"id": "S1_AP1", "source_timestamp": 3.0, "type": "MOTION_PEAK",
                 "intensity": 0.8, "beat_aligned": False, "nearest_beat": 0.0},
                {"id": "S1_AP2", "source_timestamp": 3.3, "type": "MOTION_PEAK",
                 "intensity": 0.7, "beat_aligned": False, "nearest_beat": 0.0},
                {"id": "S1_AP3", "source_timestamp": 5.0, "type": "REVEAL",
                 "intensity": 0.9, "beat_aligned": True, "nearest_beat": 5.0},
            ],
        }]
        w = []
        _fix_action_peak_timestamps(scenes, w)
        assert len(scenes[0]["action_peaks"]) == 2

    def test_fix_sfx_recommendation_added(self):
        """Fix #13: sfx_recommendation added to peaks without one."""
        scenes = [{
            "scene_number": 1,
            "action_peaks": [
                {"id": "S1_AP1", "source_timestamp": 3.0, "type": "MOTION_BURST",
                 "intensity": 0.9, "beat_aligned": False, "nearest_beat": 0.0},
            ],
        }]
        w = []
        _fix_sfx_recommendation(scenes, w)
        rec = scenes[0]["action_peaks"][0]["sfx_recommendation"]
        assert rec is not None
        assert rec["type"] == "IMPACT"  # MOTION_BURST → IMPACT
        assert rec["file"] == "scene_1_sfx.mp3"

    def test_fix_sfx_recommendation_preserves_existing(self):
        """Fix #13: Don't overwrite existing sfx_recommendation."""
        existing_rec = {"type": "CUSTOM", "intensity": 1.0, "file": "custom.mp3"}
        scenes = [{
            "scene_number": 1,
            "action_peaks": [
                {"id": "S1_AP1", "source_timestamp": 3.0, "type": "MOTION_BURST",
                 "intensity": 0.9, "beat_aligned": False, "nearest_beat": 0.0,
                 "sfx_recommendation": existing_rec},
            ],
        }]
        w = []
        _fix_sfx_recommendation(scenes, w)
        assert scenes[0]["action_peaks"][0]["sfx_recommendation"]["type"] == "CUSTOM"
        assert len(w) == 0

    def test_fix_sfx_from_gen1_brief(self):
        """Fix #14: Synthetic peak created from gen1 SFX."""
        scenes = [_make_scene(1), _make_scene(2)]  # No action_peaks
        scenes[0]["action_peaks"] = []
        scenes[1]["action_peaks"] = []
        gen1 = _make_gen1_brief(2)
        w = []
        _fix_sfx_from_gen1_brief(scenes, gen1, w)
        assert len(scenes[0]["action_peaks"]) == 1
        assert "synth" in scenes[0]["action_peaks"][0]["id"]
        assert scenes[0]["action_peaks"][0]["sfx_recommendation"]["source"] == "gen1_brief_fallback"

    def test_fix_sfx_from_gen1_preserves_existing_peaks(self):
        """Fix #14: Don't add synthetic peak if scene already has peaks."""
        peak = {
            "id": "S1_AP1", "source_timestamp": 3.0, "type": "MOTION_PEAK",
            "intensity": 0.8, "beat_aligned": False, "nearest_beat": 0.0,
        }
        scenes = [_make_scene(1, peaks=[peak])]
        gen1 = _make_gen1_brief(1)
        w = []
        _fix_sfx_from_gen1_brief(scenes, gen1, w)
        assert len(scenes[0]["action_peaks"]) == 1
        assert scenes[0]["action_peaks"][0]["id"] == "S1_AP1"


# ---------------------------------------------------------------------------
# PHASE 5: LOOP & HANDOFF
# ---------------------------------------------------------------------------

class TestPhase5LoopHandoff:
    """Tests for loop and handoff fixes."""

    def test_fix_loop_duration_match(self):
        """Fix #15: SceneN duration adjusted to match Scene1."""
        scenes = [
            _make_scene(1, speed=2.5),  # dur = 4.0
            _make_scene(8, speed=1.5),  # dur = 6.67 → should be adjusted
        ]
        w = []
        _fix_loop_duration_match(scenes, w)
        assert abs(scenes[-1]["output_duration"] - scenes[0]["output_duration"]) <= 0.5

    def test_fix_loop_duration_already_matching(self):
        """Fix #15: No change when durations already match."""
        scenes = [_make_scene(1, speed=2.5), _make_scene(8, speed=2.5)]
        w = []
        _fix_loop_duration_match(scenes, w)
        assert len(w) == 0

    def test_fix_gen3b_handoff_rebuild(self):
        """Fix #16: gen3b_handoff rebuilt with cumulative starts."""
        data = _make_gen3a_data(8)
        scenes = data["scenes"]
        w = []
        _fix_gen3b_handoff(data, scenes, w)
        handoff = data["gen3b_handoff"]
        assert "cumulative_scene_starts" in handoff
        assert "total_output_duration" in handoff
        assert "loop_compliant" in handoff
        assert handoff["cumulative_scene_starts"]["scene_1"] == 0.0
        assert handoff["total_output_duration"] > 0


# ---------------------------------------------------------------------------
# INTEGRATION TESTS
# ---------------------------------------------------------------------------

class TestIntegration:
    """Full pipeline integration tests."""

    def test_full_autocorrect_basic(self):
        """Full autocorrect with basic 8-scene input."""
        data = _make_gen3a_data(8)
        gen1 = _make_gen1_brief(8)
        corrected, warnings = autocorrect_gen3a(data, gen1_brief=gen1)

        # Check immutability
        assert corrected is not data

        # Check structural
        assert "scenes" in corrected
        assert len(corrected["scenes"]) == 8

        # Check special flags
        assert "HOOK_SCENE" in corrected["scenes"][0]["special_flags"]
        assert "LOOP_SCENE" in corrected["scenes"][-1]["special_flags"]

        # Check handoff
        handoff = corrected["gen3b_handoff"]
        assert handoff["total_output_duration"] > 0

    def test_full_autocorrect_scene_analysis_key(self):
        """Full autocorrect normalizes scene_analysis → scenes."""
        data = _make_gen3a_data(6)
        data["scene_analysis"] = data.pop("scenes")
        corrected, warnings = autocorrect_gen3a(data)
        assert "scenes" in corrected
        assert len(corrected["scenes"]) == 6

    def test_full_autocorrect_empty_peaks_get_sfx(self):
        """Scenes without peaks get synthetic peaks with SFX."""
        data = _make_gen3a_data(6)
        for scene in data["scenes"]:
            scene["action_peaks"] = []
        gen1 = _make_gen1_brief(6)
        corrected, warnings = autocorrect_gen3a(data, gen1_brief=gen1)
        for scene in corrected["scenes"]:
            assert len(scene["action_peaks"]) >= 1
            assert scene["action_peaks"][0].get("sfx_recommendation") is not None

    def test_full_autocorrect_does_not_mutate_original(self):
        """Ensure original data is not mutated."""
        data = _make_gen3a_data(8)
        original = copy.deepcopy(data)
        autocorrect_gen3a(data)
        assert data == original
