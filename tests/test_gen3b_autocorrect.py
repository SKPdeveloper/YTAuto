"""
Tests for GEN3b Auto-Corrector v1.1

Tests covering all 20 auto-fixes across 5 phases.
"""

import copy
import pytest

from app.services.gen3b_autocorrect import (
    autocorrect_gen3b,
    _fix_scene_list_key,
    _fix_scene_number_types,
    _fix_timeline_nulls,
    _fix_timeline_order,
    _fix_cuts_type,
    _fix_speed_segments_location,
    _fix_speed_segments_from_gen3a,
    _fix_timeline_continuity,
    _fix_vo_timing_constraint,
    _fix_enforce_gen3a_durations,
    _fix_total_duration_cap,
    _fix_populate_sfx_events,
    _fix_sfx_for_scenes_without_peaks,
    _fix_sfx_dedup,
    _fix_audio_layers_structure,
    _fix_subtitle_uppercase,
    _fix_hook_style_match,
    _fix_loop_duration_match,
    _fix_total_duration,
    _fix_effect_palette_compliance,
    TARGET_TOTAL_MAX_GEN3B,
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


def _make_manifest_scene(num, t_start, t_end, speed_segs=None):
    return {
        "scene_number": num,
        "source_file": f"gen3a_work/{num}.mp4",
        "timeline_start": t_start,
        "timeline_end": t_end,
        "speed_segments": speed_segs or [_make_speed_segment()],
        "effects": [],
        "cuts": [],
    }


def _make_gen3b_data(num_scenes=8):
    scenes = []
    t = 0.3  # After hook
    for i in range(num_scenes):
        dur = 2.5
        scenes.append(_make_manifest_scene(i + 1, t, t + dur))
        t += dur

    return {
        "version": "1.3.4",
        "total_duration": t,
        "hook": {"style": "CLASSIC", "duration": 0.3},
        "scenes": scenes,
        "audio_layers": {
            "bed": {"layer": "BED", "file": "", "volume": 0.3},
            "music": {"layer": "MUSIC", "file": "", "volume": 1.0},
            "vo": {"layer": "VO", "file": "", "volume": 1.0},
            "sfx_events": [],
            "foley_events": [],
        },
        "subtitles": [],
    }


def _make_gen3a_data(num_scenes=8):
    scenes = []
    for i in range(num_scenes):
        scenes.append({
            "scene_number": i + 1,
            "source_duration": 10.0,
            "output_duration": 2.5,
            "speed_map": [_make_speed_segment()],
            "action_peaks": [
                {
                    "id": f"S{i + 1}_AP1",
                    "source_timestamp": 5.0,
                    "type": "MOTION_PEAK",
                    "intensity": 0.8,
                    "beat_aligned": False,
                    "nearest_beat": 0.0,
                    "sfx_recommendation": {
                        "type": "IMPACT",
                        "intensity": 0.8,
                        "file": f"scene_{i + 1}_sfx.mp3",
                    },
                }
            ],
            "special_flags": [],
        })

    return {
        "version": "1.6.0",
        "scenes": scenes,
        "vo_segments": [
            {"segment_id": f"VO{i + 1}", "source_start": 0.5, "source_end": 2.0}
            for i in range(num_scenes)
        ],
        "hook_variety_analysis": {"recommended_style": "CLASSIC"},
    }


# ---------------------------------------------------------------------------
# PHASE 1: STRUCTURAL
# ---------------------------------------------------------------------------

class TestPhase1Structural:

    def test_fix_scene_list_key_timeline(self):
        """Fix #1: timeline → scenes."""
        d = {"timeline": [{"scene_number": 1}]}
        w = []
        _fix_scene_list_key(d, w)
        assert "scenes" in d
        assert "timeline" not in d

    def test_fix_scene_list_key_already_scenes(self):
        """Fix #1: No change when key is already 'scenes'."""
        d = {"scenes": [{"scene_number": 1}]}
        w = []
        _fix_scene_list_key(d, w)
        assert len(w) == 0

    def test_fix_scene_number_types_string(self):
        """Fix #2: "8 (last scene)" → 8."""
        scenes = [{"scene_number": "8 (last scene)"}]
        w = []
        _fix_scene_number_types(scenes, w)
        assert scenes[0]["scene_number"] == 8

    def test_fix_scene_number_types_null(self):
        """Fix #2: null → sequential."""
        scenes = [{"scene_number": None}, {"scene_number": None}]
        w = []
        _fix_scene_number_types(scenes, w)
        assert scenes[0]["scene_number"] == 1
        assert scenes[1]["scene_number"] == 2

    def test_fix_timeline_nulls_from_speed(self):
        """Fix #3: Calculate timeline from speed segments."""
        scenes = [{
            "scene_number": 1,
            "speed_segments": [_make_speed_segment(0.0, 10.0, 2.5)],
        }]
        w = []
        _fix_timeline_nulls(scenes, None, w)
        assert scenes[0]["timeline_start"] == 0.0
        assert abs(scenes[0]["timeline_end"] - 4.0) < 0.01

    def test_fix_timeline_nulls_from_gen3a(self):
        """Fix #3: Fallback to gen3a output_duration."""
        scenes = [{"scene_number": 1}]
        gen3a = {"scenes": [{"scene_number": 1, "output_duration": 3.5}]}
        w = []
        _fix_timeline_nulls(scenes, gen3a, w)
        assert abs(scenes[0]["timeline_end"] - 3.5) < 0.01

    def test_fix_timeline_order_inverted(self):
        """Fix #4: end <= start → fix."""
        scenes = [{
            "scene_number": 1,
            "timeline_start": 5.0,
            "timeline_end": 3.0,
            "speed_segments": [_make_speed_segment()],
        }]
        w = []
        _fix_timeline_order(scenes, w)
        assert scenes[0]["timeline_end"] > scenes[0]["timeline_start"]

    def test_fix_cuts_type_dict_to_list(self):
        """Fix #5: dict {"has_cuts": false} → list []."""
        scenes = [{"scene_number": 1, "cuts": {"has_cuts": False}}]
        w = []
        _fix_cuts_type(scenes, w)
        assert isinstance(scenes[0]["cuts"], list)
        assert len(scenes[0]["cuts"]) == 0


# ---------------------------------------------------------------------------
# PHASE 2: SPEED & TIMING
# ---------------------------------------------------------------------------

class TestPhase2SpeedTiming:

    def test_fix_speed_segments_location(self):
        """Fix #6: Extract from speed_processing.speed_map."""
        scenes = [{
            "scene_number": 1,
            "speed_processing": {"speed_map": [_make_speed_segment()]},
        }]
        w = []
        _fix_speed_segments_location(scenes, w)
        assert len(scenes[0]["speed_segments"]) == 1

    def test_fix_speed_segments_from_gen3a(self):
        """Fix #7: Empty → fallback on gen3a speed_map."""
        scenes = [{"scene_number": 1}]
        gen3a = _make_gen3a_data(1)
        w = []
        _fix_speed_segments_from_gen3a(scenes, gen3a, w)
        assert len(scenes[0]["speed_segments"]) == 1

    def test_fix_speed_segments_from_gen3a_preserves_existing(self):
        """Fix #7: Don't override existing speed_segments."""
        existing = [_make_speed_segment(0.0, 5.0, 3.0)]
        scenes = [{"scene_number": 1, "speed_segments": existing}]
        gen3a = _make_gen3a_data(1)
        w = []
        _fix_speed_segments_from_gen3a(scenes, gen3a, w)
        assert scenes[0]["speed_segments"][0]["speed"] == 3.0
        assert len(w) == 0

    def test_fix_timeline_continuity(self):
        """Fix #8: scene[i].end == scene[i+1].start."""
        scenes = [
            _make_manifest_scene(1, 0.3, 2.8),
            _make_manifest_scene(2, 3.5, 6.0),  # Gap: 2.8 → 3.5
        ]
        w = []
        _fix_timeline_continuity(scenes, w)
        assert abs(scenes[1]["timeline_start"] - scenes[0]["timeline_end"]) < 0.01

    def test_fix_vo_timing_constraint(self):
        """Fix #9: Extend scene if shorter than VO + 0.3s (legacy, still exists as function)."""
        scenes = [_make_manifest_scene(1, 0.3, 1.0)]  # 0.7s duration
        gen3a = {
            "scenes": [],
            "vo_segments": [
                {"segment_id": "VO1", "source_start": 0.0, "source_end": 2.0},
            ],
        }
        w = []
        _fix_vo_timing_constraint(scenes, gen3a, w)
        scene_dur = scenes[0]["timeline_end"] - scenes[0]["timeline_start"]
        assert scene_dur >= 2.3  # vo_dur (2.0) + padding (0.3)

    # --- Fix #19: Enforce gen3a durations ---

    def test_fix_enforce_gen3a_durations_scales_down(self):
        """Fix #19: Scene 4.0s with gen3a target 2.5s → scaled to ~2.5s."""
        scenes = [_make_manifest_scene(1, 0.0, 4.0,
                                        speed_segs=[_make_speed_segment(0.0, 10.0, 2.5)])]
        gen3a = {"scenes": [{"scene_number": 1, "output_duration": 2.5}]}
        w = []
        _fix_enforce_gen3a_durations(scenes, gen3a, w)
        new_dur = scenes[0]["timeline_end"] - scenes[0]["timeline_start"]
        assert abs(new_dur - 2.5) < 0.3
        assert len(w) >= 1
        assert "Enforced gen3a" in w[0].message

    def test_fix_enforce_gen3a_durations_no_change_within_tolerance(self):
        """Fix #19: No change when delta < 0.1s."""
        scenes = [_make_manifest_scene(1, 0.0, 2.55,
                                        speed_segs=[_make_speed_segment(0.0, 6.375, 2.5)])]
        gen3a = {"scenes": [{"scene_number": 1, "output_duration": 2.5}]}
        w = []
        _fix_enforce_gen3a_durations(scenes, gen3a, w)
        assert len(w) == 0  # within 0.1s tolerance

    def test_fix_enforce_gen3a_durations_no_gen3a(self):
        """Fix #19: No-op when gen3a_data is None."""
        scenes = [_make_manifest_scene(1, 0.0, 4.0)]
        w = []
        _fix_enforce_gen3a_durations(scenes, None, w)
        assert len(w) == 0
        assert scenes[0]["timeline_end"] == 4.0

    def test_fix_enforce_gen3a_durations_speed_min_clamp(self):
        """Fix #19: Speed never drops below 1.0."""
        scenes = [_make_manifest_scene(1, 0.0, 5.0,
                                        speed_segs=[_make_speed_segment(0.0, 4.0, 1.0)])]
        gen3a = {"scenes": [{"scene_number": 1, "output_duration": 2.0}]}
        w = []
        _fix_enforce_gen3a_durations(scenes, gen3a, w)
        for seg in scenes[0]["speed_segments"]:
            assert seg["speed"] >= 1.0

    # --- Fix #20: Total duration cap ---

    def test_fix_total_duration_cap_compresses(self):
        """Fix #20: 8 scenes × 4.0s = 32.0s → compressed to 25.0s."""
        d = _make_gen3b_data(8)
        # Override each scene to 4.0s duration (total 32.3s with 0.3 hook)
        t = 0.3
        for scene in d["scenes"]:
            scene["timeline_start"] = t
            scene["timeline_end"] = t + 4.0
            scene["speed_segments"] = [_make_speed_segment(0.0, 10.0, 2.5)]
            t += 4.0
        d["total_duration"] = t
        w = []
        _fix_total_duration_cap(d, d["scenes"], w)
        total = d["scenes"][-1]["timeline_end"]
        assert total <= TARGET_TOTAL_MAX_GEN3B
        assert len(w) >= 1
        assert "Duration cap" in w[0].message

    def test_fix_total_duration_cap_no_change_under_limit(self):
        """Fix #20: No change when total ≤ 25s."""
        d = _make_gen3b_data(8)  # default ~20.3s
        w = []
        _fix_total_duration_cap(d, d["scenes"], w)
        assert len(w) == 0

    def test_fix_total_duration_cap_speed_min_clamp(self):
        """Fix #20: Compressed speeds never drop below 1.0."""
        d = _make_gen3b_data(8)
        t = 0.3
        for scene in d["scenes"]:
            scene["timeline_start"] = t
            scene["timeline_end"] = t + 5.0
            scene["speed_segments"] = [_make_speed_segment(0.0, 5.0, 1.0)]
            t += 5.0
        d["total_duration"] = t
        w = []
        _fix_total_duration_cap(d, d["scenes"], w)
        for scene in d["scenes"]:
            for seg in scene["speed_segments"]:
                assert seg["speed"] >= 1.0

    def test_fix_total_duration_cap_continuity(self):
        """Fix #20: After cap, scenes are continuous (no gaps)."""
        d = _make_gen3b_data(8)
        t = 0.0
        for scene in d["scenes"]:
            scene["timeline_start"] = t
            scene["timeline_end"] = t + 4.0
            t += 4.0
        d["total_duration"] = t
        w = []
        _fix_total_duration_cap(d, d["scenes"], w)
        for i in range(1, len(d["scenes"])):
            prev_end = d["scenes"][i - 1]["timeline_end"]
            curr_start = d["scenes"][i]["timeline_start"]
            assert abs(prev_end - curr_start) < 0.01


# ---------------------------------------------------------------------------
# PHASE 3: SFX EVENTS
# ---------------------------------------------------------------------------

class TestPhase3SFXEvents:

    def test_fix_populate_sfx_events(self):
        """Fix #10: SFX events created from gen3a action_peaks."""
        d = _make_gen3b_data(2)
        scenes = d["scenes"]
        gen3a = _make_gen3a_data(2)
        w = []
        _fix_populate_sfx_events(d, scenes, gen3a, w)
        sfx = d["audio_layers"]["sfx_events"]
        assert len(sfx) >= 2
        assert sfx[0]["source"] == "gen3a_action_peak"

    def test_fix_populate_sfx_preserves_existing(self):
        """Fix #10: Don't override existing SFX events."""
        d = _make_gen3b_data(2)
        d["audio_layers"]["sfx_events"] = [
            {"id": "existing", "output_timestamp": 1.0, "effect": "BOOM", "file": "boom.mp3"}
        ]
        gen3a = _make_gen3a_data(2)
        w = []
        _fix_populate_sfx_events(d, d["scenes"], gen3a, w)
        assert d["audio_layers"]["sfx_events"][0]["id"] == "existing"
        assert len(w) == 0

    def test_fix_sfx_for_scenes_without_peaks(self):
        """Fix #11: Fallback SFX at timeline_start + 0.3s."""
        d = _make_gen3b_data(2)
        gen3a = _make_gen3a_data(2)
        # Remove peaks from gen3a scene 2
        gen3a["scenes"][1]["action_peaks"] = []
        w = []
        # First populate from gen3a (only scene 1 has peaks)
        _fix_populate_sfx_events(d, d["scenes"], gen3a, w)
        # Then add fallback for scene 2
        _fix_sfx_for_scenes_without_peaks(d, d["scenes"], gen3a, w)
        sfx = d["audio_layers"]["sfx_events"]
        fallback = [s for s in sfx if s.get("source") == "no_peak_fallback"]
        assert len(fallback) >= 1
        # Check it's at timeline_start + 0.3, NOT midpoint
        scene2 = d["scenes"][1]
        expected_ts = scene2["timeline_start"] + 0.3
        assert abs(fallback[0]["output_timestamp"] - expected_ts) < 0.01

    def test_fix_sfx_dedup(self):
        """Fix #12: Remove events within 0.3s of each other."""
        d = {
            "audio_layers": {
                "sfx_events": [
                    {"id": "sfx1", "output_timestamp": 1.0},
                    {"id": "sfx2", "output_timestamp": 1.2},  # < 0.3s from sfx1
                    {"id": "sfx3", "output_timestamp": 3.0},
                ],
            },
        }
        w = []
        _fix_sfx_dedup(d, w)
        assert len(d["audio_layers"]["sfx_events"]) == 2
        ids = [s["id"] for s in d["audio_layers"]["sfx_events"]]
        assert "sfx1" in ids
        assert "sfx3" in ids


# ---------------------------------------------------------------------------
# PHASE 4: AUDIO & SUBTITLES
# ---------------------------------------------------------------------------

class TestPhase4AudioSubtitles:

    def test_fix_audio_layers_structure_nested(self):
        """Fix #13: Convert nested layers list → flat dict."""
        d = {
            "audio_layers": {
                "layers": [
                    {"type": "MUSIC", "file": "music.mp3", "volume": 0.8},
                    {"type": "VOICEOVER", "file": "vo.mp3", "volume": 1.0},
                    {"type": "BED", "file": "bed.mp3", "volume": 0.3},
                ],
            },
        }
        w = []
        _fix_audio_layers_structure(d, w)
        audio = d["audio_layers"]
        assert "music" in audio
        assert "vo" in audio
        assert "bed" in audio
        assert audio["music"]["file"] == "music.mp3"

    def test_fix_audio_layers_ensures_required(self):
        """Fix #13: Ensure bed, music, vo, sfx_events, foley_events exist."""
        d = {"audio_layers": {}}
        w = []
        _fix_audio_layers_structure(d, w)
        audio = d["audio_layers"]
        assert "bed" in audio
        assert "music" in audio
        assert "vo" in audio
        assert "sfx_events" in audio
        assert "foley_events" in audio

    def test_fix_subtitle_uppercase(self):
        """Fix #14: Subtitle text → uppercase."""
        d = {
            "subtitles": [
                {"text": "This golden crust"},
                {"text": "ALREADY UPPER"},
            ],
        }
        w = []
        _fix_subtitle_uppercase(d, w)
        assert d["subtitles"][0]["text"] == "THIS GOLDEN CRUST"
        assert d["subtitles"][1]["text"] == "ALREADY UPPER"

    def test_fix_hook_style_match_warning(self):
        """Fix #15: Warning when style doesn't match."""
        d = {"hook": {"style": "WHIP_PAN"}}
        gen3a = {"hook_variety_analysis": {"recommended_style": "CLASSIC"}}
        w = []
        _fix_hook_style_match(d, gen3a, w)
        assert len(w) == 1
        assert "warning only" in w[0].message

    def test_fix_hook_style_match_ok(self):
        """Fix #15: No warning when styles match."""
        d = {"hook": {"style": "CLASSIC"}}
        gen3a = {"hook_variety_analysis": {"recommended_style": "CLASSIC"}}
        w = []
        _fix_hook_style_match(d, gen3a, w)
        assert len(w) == 0

    def test_fix_loop_duration_match(self):
        """Fix #16: SceneN duration adjusted to match Scene1."""
        scenes = [
            _make_manifest_scene(1, 0.3, 2.8),   # dur = 2.5
            _make_manifest_scene(8, 15.0, 19.0),  # dur = 4.0 → should adjust
        ]
        w = []
        _fix_loop_duration_match(scenes, w)
        dur1 = scenes[0]["timeline_end"] - scenes[0]["timeline_start"]
        durN = scenes[-1]["timeline_end"] - scenes[-1]["timeline_start"]
        assert abs(dur1 - durN) <= 0.5


# ---------------------------------------------------------------------------
# PHASE 5: VALIDATION
# ---------------------------------------------------------------------------

class TestPhase5Validation:

    def test_fix_total_duration(self):
        """Fix #17: Recalculate total_duration."""
        d = _make_gen3b_data(4)
        d["total_duration"] = 999.0
        w = []
        _fix_total_duration(d, d["scenes"], w)
        assert d["total_duration"] != 999.0
        assert d["total_duration"] == d["scenes"][-1]["timeline_end"]

    def test_fix_effect_palette_compliance_warning(self):
        """Fix #18: Warning for non-standard effects."""
        scenes = [{
            "scene_number": 1,
            "effects": [{"type": "TOTALLY_CUSTOM_EFFECT"}],
        }]
        w = []
        _fix_effect_palette_compliance(scenes, w)
        assert len(w) == 1
        assert "warning only" in w[0].message


# ---------------------------------------------------------------------------
# INTEGRATION TESTS
# ---------------------------------------------------------------------------

class TestIntegration:

    def test_full_autocorrect_basic(self):
        """Full autocorrect with basic 8-scene input."""
        data = _make_gen3b_data(8)
        gen3a = _make_gen3a_data(8)
        corrected, warnings = autocorrect_gen3b(data, gen3a_data=gen3a)

        # Immutability
        assert corrected is not data

        # SFX events populated
        sfx = corrected["audio_layers"]["sfx_events"]
        assert len(sfx) >= 8  # At least 1 per scene

    def test_full_autocorrect_timeline_key(self):
        """Full autocorrect normalizes timeline → scenes."""
        data = _make_gen3b_data(6)
        data["timeline"] = data.pop("scenes")
        corrected, warnings = autocorrect_gen3b(data)
        assert "scenes" in corrected

    def test_full_autocorrect_empty_sfx_populated(self):
        """Empty sfx_events populated from gen3a peaks."""
        data = _make_gen3b_data(4)
        gen3a = _make_gen3a_data(4)
        corrected, warnings = autocorrect_gen3b(data, gen3a_data=gen3a)
        sfx = corrected["audio_layers"]["sfx_events"]
        assert len(sfx) >= 4
        # Each SFX should have output_timestamp
        for event in sfx:
            assert "output_timestamp" in event
            assert event["output_timestamp"] >= 0

    def test_full_autocorrect_does_not_mutate_original(self):
        """Ensure original data is not mutated."""
        data = _make_gen3b_data(8)
        original = copy.deepcopy(data)
        autocorrect_gen3b(data)
        assert data == original

    def test_full_autocorrect_sfx_timestamps_are_absolute(self):
        """SFX timestamps should be absolute (include timeline_start offset)."""
        data = _make_gen3b_data(3)
        gen3a = _make_gen3a_data(3)
        corrected, warnings = autocorrect_gen3b(data, gen3a_data=gen3a)
        sfx = corrected["audio_layers"]["sfx_events"]

        # First SFX should be >= first scene's timeline_start
        first_scene_start = corrected["scenes"][0]["timeline_start"]
        if sfx:
            assert sfx[0]["output_timestamp"] >= first_scene_start

    def test_full_autocorrect_duration_cap_enforced(self):
        """Integration: inflated 32s manifest capped to ≤ 25s."""
        data = _make_gen3b_data(8)
        # Inflate each scene to ~4s (total ~32.3s)
        t = 0.3
        for scene in data["scenes"]:
            scene["timeline_start"] = t
            scene["timeline_end"] = t + 4.0
            scene["speed_segments"] = [_make_speed_segment(0.0, 10.0, 2.5)]
            t += 4.0
        data["total_duration"] = t

        gen3a = _make_gen3a_data(8)
        corrected, warnings = autocorrect_gen3b(data, gen3a_data=gen3a)

        total = corrected["total_duration"]
        assert total <= TARGET_TOTAL_MAX_GEN3B, (
            f"total_duration {total:.2f}s exceeds cap {TARGET_TOTAL_MAX_GEN3B}s"
        )

    def test_full_autocorrect_vo_constraint_removed(self):
        """Integration: VO constraint no longer inflates scenes."""
        data = _make_gen3b_data(4)
        # Scenes are 2.5s each — shorter than VO (1.5s + 0.3s padding = 1.8s)
        gen3a = _make_gen3a_data(4)
        # Make VO segments longer than scene durations
        gen3a["vo_segments"] = [
            {"segment_id": f"VO{i+1}", "source_start": 0.0, "source_end": 3.0}
            for i in range(4)
        ]
        corrected, warnings = autocorrect_gen3b(data, gen3a_data=gen3a)

        # Verify VO constraint did NOT inflate scenes
        vo_warnings = [w for w in warnings if "Extended by" in w.message and "for VO" in w.message]
        assert len(vo_warnings) == 0, "VO constraint should no longer inflate scenes"
