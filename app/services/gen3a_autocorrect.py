"""
GEN3a Auto-Corrector v1.0

Deterministic auto-fix layer for GEN3a (Video Analyst) output.
Runs BEFORE validation/conversion to fix known Gemini 3 Pro hallucinations.

Architecture mirrors gen1_autocorrect.py / gen2_autocorrect.py:
    corrected_data, warnings = autocorrect_gen3a(raw_gen3a_json, gen1_brief)

16 auto-fixes in 5 phases:
  Phase 1: Structural (P0)           — scene key, scene numbers, metadata, speed_map nesting
  Phase 2: Speed Map Integrity (P0)  — coverage, boundaries, duration recalc, total range
  Phase 3: Special Flags (P0-P1)     — hook, loop, easter egg
  Phase 4: SFX & Action Peaks (P0-P1)— timestamps, sfx_recommendation, gen1 fallback
  Phase 5: Loop & Handoff (P0-P1)    — loop duration, gen3b handoff (ALWAYS LAST)
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from app.services.gen1_autocorrect import AutoFixWarning
from app.services.timing_utils import (
    calculate_output_duration,
    build_cumulative_starts,
)


# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

# Action peak type → SFX type mapping
ACTION_PEAK_SFX_MAP: Dict[str, str] = {
    "MOTION_BURST": "IMPACT",
    "MOTION_PEAK": "IMPACT",
    "REVEAL": "MOTION",
    "TRANSITION": "WHOOSH",
    "TEXTURE_CHANGE": "FOLEY",
    "CAMERA_SHIFT": "WHOOSH",
    "IMPACT": "IMPACT",
}

# SFX type → default file mapping
SFX_TYPE_FILE_MAP: Dict[str, str] = {
    "IMPACT": "impact_hit.mp3",
    "MOTION": "whoosh_motion.mp3",
    "WHOOSH": "whoosh_motion.mp3",
    "FOLEY": "foley_texture.mp3",
}

# Valid special flags
VALID_SPECIAL_FLAGS: set = {
    "HOOK_SCENE", "LOOP_SCENE", "MONEY_SHOT_SCENE",
    "EASTER_EGG_SCENE", "AERIAL_SCENE",
}

# Speed constraints
MIN_SPEED = 1.5
SOURCE_DURATION = 10.0  # Kling videos are always 10s
TARGET_TOTAL_MIN = 18.0
TARGET_TOTAL_MAX = 25.0


# ---------------------------------------------------------------------------
# PHASE 1: STRUCTURAL (P0)
# ---------------------------------------------------------------------------

def _fix_scene_list_key(d: dict, w: list) -> None:
    """Fix #1: Normalize scene list key: scene_analysis → scenes."""
    if "scene_analysis" in d and "scenes" not in d:
        d["scenes"] = d.pop("scene_analysis")
        w.append(AutoFixWarning("scenes", "Renamed 'scene_analysis' → 'scenes'"))
    # Also handle "scene_list" variant
    if "scene_list" in d and "scenes" not in d:
        d["scenes"] = d.pop("scene_list")
        w.append(AutoFixWarning("scenes", "Renamed 'scene_list' → 'scenes'"))


def _fix_scene_numbers(scenes: list, w: list) -> None:
    """Fix #2: Normalize scene_number: string/null/0-based → int 1..N."""
    for i, scene in enumerate(scenes):
        raw = scene.get("scene_number")
        expected = i + 1

        if raw is None or raw == 0:
            scene["scene_number"] = expected
            w.append(AutoFixWarning(f"scene_{expected}.scene_number",
                                    f"null/0 → {expected}"))
        elif isinstance(raw, str):
            digits = re.findall(r'\d+', raw)
            scene["scene_number"] = int(digits[0]) if digits else expected
            w.append(AutoFixWarning(f"scene_{expected}.scene_number",
                                    f"'{raw}' → {scene['scene_number']}"))
        elif isinstance(raw, float):
            scene["scene_number"] = int(raw)
        elif isinstance(raw, int) and raw != expected:
            scene["scene_number"] = expected
            w.append(AutoFixWarning(f"scene_{expected}.scene_number",
                                    f"{raw} → {expected} (reindex)"))


def _fix_metadata_types(d: dict, w: list) -> None:
    """Fix #3: Ensure version is str, timestamp is ISO string."""
    if "version" in d and not isinstance(d["version"], str):
        d["version"] = str(d["version"])
        w.append(AutoFixWarning("version", f"Cast to string: {d['version']}"))

    if "analysis_timestamp" in d:
        ts = d["analysis_timestamp"]
        if isinstance(ts, (int, float)):
            from datetime import datetime
            d["analysis_timestamp"] = datetime.fromtimestamp(ts).isoformat()
            w.append(AutoFixWarning("analysis_timestamp", "Epoch → ISO string"))


def _fix_speed_map_nesting(scenes: list, w: list) -> None:
    """Fix #4: Extract speed_map from speed_analysis.speed_map nesting."""
    for scene in scenes:
        sn = scene.get("scene_number", "?")
        if "speed_map" not in scene or not scene["speed_map"]:
            speed_analysis = scene.get("speed_analysis", {})
            if isinstance(speed_analysis, dict):
                nested_map = speed_analysis.get("speed_map", [])
                if nested_map:
                    scene["speed_map"] = nested_map
                    w.append(AutoFixWarning(f"scene_{sn}.speed_map",
                                           "Extracted from speed_analysis.speed_map"))


# ---------------------------------------------------------------------------
# PHASE 2: SPEED MAP INTEGRITY (P0)
# ---------------------------------------------------------------------------

def _fix_speed_map_coverage(scenes: list, w: list) -> None:
    """Fix #5: Fill gaps in speed_map to cover 0.0—source_duration."""
    for scene in scenes:
        sn = scene.get("scene_number", "?")
        speed_map = scene.get("speed_map", [])
        source_dur = float(scene.get("source_duration", SOURCE_DURATION))

        if not speed_map:
            # Create default single-segment map
            scene["speed_map"] = [{
                "source_start": 0.0,
                "source_end": source_dur,
                "speed": 2.5,
                "output_duration": round(source_dur / 2.5, 4),
                "reason": "autocorrect_default",
                "motion_density": "MEDIUM",
                "technique": "NORMAL",
            }]
            w.append(AutoFixWarning(f"scene_{sn}.speed_map",
                                    "Empty → default 2.5x single segment"))
            continue

        # Sort by source_start
        speed_map.sort(key=lambda s: float(s.get("source_start", 0)))

        # Fill gap at beginning
        first_start = float(speed_map[0].get("source_start", 0))
        if first_start > 0.1:
            speed_map.insert(0, {
                "source_start": 0.0,
                "source_end": first_start,
                "speed": 2.5,
                "output_duration": round(first_start / 2.5, 4),
                "reason": "gap_fill_start",
                "motion_density": "MEDIUM",
                "technique": "NORMAL",
            })
            w.append(AutoFixWarning(f"scene_{sn}.speed_map",
                                    f"Filled gap 0.0—{first_start:.1f}"))

        # Fill gap at end
        last_end = float(speed_map[-1].get("source_end", 0))
        if last_end < source_dur - 0.1:
            speed_map.append({
                "source_start": last_end,
                "source_end": source_dur,
                "speed": 2.5,
                "output_duration": round((source_dur - last_end) / 2.5, 4),
                "reason": "gap_fill_end",
                "motion_density": "MEDIUM",
                "technique": "NORMAL",
            })
            w.append(AutoFixWarning(f"scene_{sn}.speed_map",
                                    f"Filled gap {last_end:.1f}—{source_dur:.1f}"))

        # Fill internal gaps
        filled = []
        for j, seg in enumerate(speed_map):
            if j > 0:
                prev_end = float(filled[-1].get("source_end", 0))
                curr_start = float(seg.get("source_start", 0))
                if curr_start - prev_end > 0.1:
                    filled.append({
                        "source_start": prev_end,
                        "source_end": curr_start,
                        "speed": 2.5,
                        "output_duration": round((curr_start - prev_end) / 2.5, 4),
                        "reason": "gap_fill_internal",
                        "motion_density": "MEDIUM",
                        "technique": "NORMAL",
                    })
                    w.append(AutoFixWarning(f"scene_{sn}.speed_map",
                                           f"Filled internal gap {prev_end:.1f}—{curr_start:.1f}"))
            filled.append(seg)

        scene["speed_map"] = filled


def _fix_speed_map_boundaries(scenes: list, w: list) -> None:
    """Fix #6: Enforce source_start < source_end, speed >= MIN_SPEED, clamp [0, source_dur]."""
    for scene in scenes:
        sn = scene.get("scene_number", "?")
        source_dur = float(scene.get("source_duration", SOURCE_DURATION))

        for seg in scene.get("speed_map", []):
            s_start = float(seg.get("source_start", 0))
            s_end = float(seg.get("source_end", 0))
            speed = float(seg.get("speed", 2.5))

            # Clamp to valid range
            s_start = max(0.0, min(s_start, source_dur))
            s_end = max(0.0, min(s_end, source_dur))

            # Fix inverted boundaries
            if s_end <= s_start:
                s_end = min(s_start + 1.0, source_dur)
                w.append(AutoFixWarning(f"scene_{sn}.speed_map",
                                       f"Inverted boundaries fixed: {s_start:.1f}—{s_end:.1f}"))

            # Enforce minimum speed
            if speed < MIN_SPEED:
                w.append(AutoFixWarning(f"scene_{sn}.speed_map",
                                       f"Speed {speed:.1f} → {MIN_SPEED} (minimum)"))
                speed = MIN_SPEED

            seg["source_start"] = round(s_start, 4)
            seg["source_end"] = round(s_end, 4)
            seg["speed"] = round(speed, 4)


def _fix_output_duration_recalc(scenes: list, w: list) -> None:
    """Fix #7: Recalculate output_duration for each segment and scene."""
    for scene in scenes:
        sn = scene.get("scene_number", "?")
        total_output = 0.0
        for seg in scene.get("speed_map", []):
            source_dur = float(seg.get("source_end", 0)) - float(seg.get("source_start", 0))
            speed = float(seg.get("speed", 2.5)) or 2.5
            calculated = round(source_dur / speed, 4)
            if abs(calculated - float(seg.get("output_duration", 0))) > 0.01:
                seg["output_duration"] = calculated
            total_output += calculated

        old_dur = scene.get("output_duration", 0)
        if total_output > 0 and abs(total_output - float(old_dur or 0)) > 0.05:
            scene["output_duration"] = round(total_output, 4)
            w.append(AutoFixWarning(f"scene_{sn}.output_duration",
                                    f"{old_dur} → {scene['output_duration']} (recalculated)"))


def _fix_total_duration_range(scenes: list, w: list) -> None:
    """Fix #8: Scale speeds if total output duration is outside [18, 25]."""
    total = sum(float(s.get("output_duration", 0)) for s in scenes)
    if total == 0:
        return

    if TARGET_TOTAL_MIN <= total <= TARGET_TOTAL_MAX:
        return

    # Target midpoint
    target = (TARGET_TOTAL_MIN + TARGET_TOTAL_MAX) / 2.0  # 21.5
    ratio = total / target

    w.append(AutoFixWarning("total_duration",
                           f"Total {total:.1f}s outside [{TARGET_TOTAL_MIN}-{TARGET_TOTAL_MAX}], "
                           f"scaling speeds by {ratio:.2f}x"))

    for scene in scenes:
        for seg in scene.get("speed_map", []):
            old_speed = float(seg.get("speed", 2.5))
            new_speed = max(MIN_SPEED, round(old_speed * ratio, 4))
            seg["speed"] = new_speed
            source_dur = float(seg.get("source_end", 0)) - float(seg.get("source_start", 0))
            seg["output_duration"] = round(source_dur / new_speed, 4)

        # Recalculate scene output_duration
        scene["output_duration"] = round(
            sum(float(seg.get("output_duration", 0)) for seg in scene.get("speed_map", [])),
            4
        )


# ---------------------------------------------------------------------------
# PHASE 3: SPECIAL FLAGS (P0-P1)
# ---------------------------------------------------------------------------

def _fix_special_flags_hook(scenes: list, w: list) -> None:
    """Fix #9: Scene 1 must have HOOK_SCENE flag."""
    if not scenes:
        return
    scene1 = scenes[0]
    flags = scene1.get("special_flags", [])
    if not isinstance(flags, list):
        flags = []
    if "HOOK_SCENE" not in flags:
        flags.append("HOOK_SCENE")
        scene1["special_flags"] = flags
        w.append(AutoFixWarning("scene_1.special_flags", "Added HOOK_SCENE"))


def _fix_special_flags_loop(scenes: list, w: list) -> None:
    """Fix #10: Last scene must have LOOP_SCENE flag."""
    if not scenes:
        return
    last = scenes[-1]
    flags = last.get("special_flags", [])
    if not isinstance(flags, list):
        flags = []
    if "LOOP_SCENE" not in flags:
        flags.append("LOOP_SCENE")
        last["special_flags"] = flags
        sn = last.get("scene_number", len(scenes))
        w.append(AutoFixWarning(f"scene_{sn}.special_flags", "Added LOOP_SCENE"))


def _fix_special_flags_easter(scenes: list, gen1_brief: Optional[dict], w: list) -> None:
    """Fix #11: Mark easter egg scene from gen1_brief if not already flagged."""
    if not gen1_brief:
        return

    # Find easter egg scene number from gen1_brief
    easter_egg = gen1_brief.get("easter_egg", {})
    if isinstance(easter_egg, dict):
        egg_scene = easter_egg.get("scene_number")
    else:
        egg_scene = None

    if egg_scene is None:
        # Try scenes-level easter egg data
        for gen1_scene in gen1_brief.get("scenes", []):
            if gen1_scene.get("easter_egg_object") or gen1_scene.get("has_easter_egg"):
                egg_scene = gen1_scene.get("scene_number")
                break

    if egg_scene is None:
        return

    for scene in scenes:
        if scene.get("scene_number") == egg_scene:
            flags = scene.get("special_flags", [])
            if not isinstance(flags, list):
                flags = []
            if "EASTER_EGG_SCENE" not in flags:
                flags.append("EASTER_EGG_SCENE")
                scene["special_flags"] = flags
                w.append(AutoFixWarning(f"scene_{egg_scene}.special_flags",
                                       "Added EASTER_EGG_SCENE from gen1_brief"))
            break


# ---------------------------------------------------------------------------
# PHASE 4: SFX & ACTION PEAKS (P0-P1)
# ---------------------------------------------------------------------------

def _fix_action_peak_timestamps(scenes: list, w: list) -> None:
    """Fix #12: Clamp action_peak timestamps to [0, source_dur], dedup delta < 0.5s."""
    for scene in scenes:
        sn = scene.get("scene_number", "?")
        source_dur = float(scene.get("source_duration", SOURCE_DURATION))
        peaks = scene.get("action_peaks", [])
        if not peaks:
            continue

        # Clamp timestamps
        for peak in peaks:
            ts = float(peak.get("source_timestamp", 0))
            clamped = max(0.0, min(ts, source_dur))
            if abs(clamped - ts) > 0.01:
                peak["source_timestamp"] = round(clamped, 4)
                w.append(AutoFixWarning(f"scene_{sn}.action_peaks",
                                       f"Clamped timestamp {ts:.2f} → {clamped:.2f}"))

        # Ensure IDs
        for idx, peak in enumerate(peaks):
            if not peak.get("id"):
                peak["id"] = f"S{sn}_AP{idx + 1}"

        # Deduplicate peaks too close together (< 0.5s)
        peaks.sort(key=lambda p: float(p.get("source_timestamp", 0)))
        deduped = [peaks[0]]
        for peak in peaks[1:]:
            prev_ts = float(deduped[-1].get("source_timestamp", 0))
            curr_ts = float(peak.get("source_timestamp", 0))
            if curr_ts - prev_ts >= 0.5:
                deduped.append(peak)
            else:
                w.append(AutoFixWarning(f"scene_{sn}.action_peaks",
                                       f"Removed duplicate peak at {curr_ts:.2f}s "
                                       f"(delta {curr_ts - prev_ts:.2f}s < 0.5s)"))

        scene["action_peaks"] = deduped


def _fix_sfx_recommendation(scenes: list, w: list) -> None:
    """Fix #13: Add sfx_recommendation to each action peak that lacks one.

    KEY FIX: Maps peak type → SFX type using ACTION_PEAK_SFX_MAP.
    """
    for scene in scenes:
        sn = scene.get("scene_number", "?")
        for peak in scene.get("action_peaks", []):
            if peak.get("sfx_recommendation"):
                continue

            peak_type = peak.get("type", "MOTION_PEAK")
            sfx_type = ACTION_PEAK_SFX_MAP.get(peak_type, "IMPACT")
            sfx_file = SFX_TYPE_FILE_MAP.get(sfx_type, "impact_hit.mp3")
            intensity = float(peak.get("intensity", 0.8))

            peak["sfx_recommendation"] = {
                "type": sfx_type,
                "intensity": round(intensity, 2),
                "file": f"scene_{sn}_sfx.mp3",
                "fallback_file": sfx_file,
            }
            w.append(AutoFixWarning(f"scene_{sn}.action_peaks.sfx_recommendation",
                                    f"Added SFX {sfx_type} for peak {peak.get('id', '?')}"))


def _fix_sfx_from_gen1_brief(scenes: list, gen1_brief: Optional[dict], w: list) -> None:
    """Fix #14: Scenes without action_peaks get synthetic peak from gen1.audio.sfx_per_scene."""
    if not gen1_brief:
        return

    # Build sfx_per_scene lookup from gen1_brief
    audio = gen1_brief.get("audio", {})
    sfx_per_scene = {}
    if isinstance(audio, dict):
        for item in audio.get("sfx_per_scene", []):
            if isinstance(item, dict):
                s_num = item.get("scene_number") or item.get("scene")
                if s_num is not None:
                    try:
                        sfx_per_scene[int(s_num)] = item
                    except (ValueError, TypeError):
                        pass  # Skip non-numeric scene_number

    for scene in scenes:
        sn = scene.get("scene_number", 0)
        peaks = scene.get("action_peaks", [])

        if peaks:
            continue  # Already has peaks

        gen1_sfx = sfx_per_scene.get(sn, {})
        sfx_desc = gen1_sfx.get("sfx") or gen1_sfx.get("description", "")

        # Create synthetic action peak at 50% of source video
        source_dur = float(scene.get("source_duration", SOURCE_DURATION))
        synthetic_peak = {
            "id": f"S{sn}_AP1_synth",
            "source_timestamp": round(source_dur * 0.5, 2),
            "type": "MOTION_PEAK",
            "intensity": 0.7,
            "beat_aligned": False,
            "nearest_beat": 0.0,
            "sfx_recommendation": {
                "type": "IMPACT",
                "intensity": 0.7,
                "file": f"scene_{sn}_sfx.mp3",
                "fallback_file": "impact_hit.mp3",
                "source": "gen1_brief_fallback",
                "description": sfx_desc,
            },
        }
        scene["action_peaks"] = [synthetic_peak]
        w.append(AutoFixWarning(f"scene_{sn}.action_peaks",
                               f"Created synthetic peak from gen1 SFX: '{sfx_desc[:40]}'"))


# ---------------------------------------------------------------------------
# PHASE 5: LOOP & HANDOFF (P0-P1)
# ---------------------------------------------------------------------------

def _fix_loop_duration_match(scenes: list, w: list) -> None:
    """Fix #15: Scene1.output_duration ≈ SceneN.output_duration (±0.5s)."""
    if len(scenes) < 2:
        return

    scene1 = scenes[0]
    sceneN = scenes[-1]
    dur1 = float(scene1.get("output_duration", 0))
    durN = float(sceneN.get("output_duration", 0))

    if dur1 == 0 or durN == 0:
        return

    delta = abs(dur1 - durN)
    if delta <= 0.5:
        return

    # Adjust last scene speed_map to match scene 1 duration
    target_dur = dur1
    speed_map_N = sceneN.get("speed_map", [])

    if not speed_map_N:
        return

    current_dur = sum(
        float(seg.get("output_duration", 0)) for seg in speed_map_N
    )
    if current_dur <= 0:
        return

    ratio = current_dur / target_dur
    for seg in speed_map_N:
        old_speed = float(seg.get("speed", 2.5))
        new_speed = max(MIN_SPEED, round(old_speed * ratio, 4))
        seg["speed"] = new_speed
        source_dur = float(seg.get("source_end", 0)) - float(seg.get("source_start", 0))
        seg["output_duration"] = round(source_dur / new_speed, 4)

    sceneN["output_duration"] = round(
        sum(float(seg.get("output_duration", 0)) for seg in speed_map_N), 4
    )
    w.append(AutoFixWarning("loop_duration",
                           f"SceneN duration {durN:.2f}s → {sceneN['output_duration']:.2f}s "
                           f"(match Scene1 {dur1:.2f}s)"))


def _fix_gen3b_handoff(d: dict, scenes: list, w: list) -> None:
    """Fix #16: Rebuild gen3b_handoff: cumulative starts, total duration, loop flag. ALWAYS LAST."""
    handoff = d.get("gen3b_handoff", {})
    if not isinstance(handoff, dict):
        handoff = {}

    # Rebuild cumulative starts using shared utility
    cumulative = build_cumulative_starts(scenes)
    total_duration = sum(float(s.get("output_duration", 0)) for s in scenes)

    handoff["cumulative_scene_starts"] = cumulative
    handoff["total_output_duration"] = round(total_duration, 4)

    # Loop compliance check
    if len(scenes) >= 2:
        dur1 = float(scenes[0].get("output_duration", 0))
        durN = float(scenes[-1].get("output_duration", 0))
        handoff["loop_compliant"] = abs(dur1 - durN) <= 0.5
    else:
        handoff["loop_compliant"] = True

    # Post-check: warn if total outside target range (Phase 5 loop fix may have shifted it)
    if total_duration > 0 and not (TARGET_TOTAL_MIN <= total_duration <= TARGET_TOTAL_MAX):
        w.append(AutoFixWarning("gen3b_handoff",
                               f"Post-loop total {total_duration:.1f}s outside "
                               f"[{TARGET_TOTAL_MIN}-{TARGET_TOTAL_MAX}] — "
                               f"loop duration match may have shifted it"))

    d["gen3b_handoff"] = handoff
    w.append(AutoFixWarning("gen3b_handoff",
                           f"Rebuilt: total={handoff['total_output_duration']:.1f}s, "
                           f"{len(cumulative)} scenes, "
                           f"loop_compliant={handoff['loop_compliant']}"))


# ---------------------------------------------------------------------------
# MAIN ENTRY POINT
# ---------------------------------------------------------------------------

def autocorrect_gen3a(
    data: Dict[str, Any],
    gen1_brief: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], List[AutoFixWarning]]:
    """
    Apply all deterministic auto-corrections to GEN3a output.

    Args:
        data: Raw GEN3a JSON output as dict.
        gen1_brief: Optional GEN1 output for SFX fallback and easter egg detection.

    Returns:
        Tuple of (corrected_data, list_of_warnings).
        corrected_data is a deep copy — original is not mutated.
    """
    d = copy.deepcopy(data)
    w: List[AutoFixWarning] = []

    # Phase 1: Structural
    _fix_scene_list_key(d, w)
    scenes = d.get("scenes", [])
    _fix_scene_numbers(scenes, w)
    _fix_metadata_types(d, w)
    _fix_speed_map_nesting(scenes, w)

    # Phase 2: Speed Map Integrity
    _fix_speed_map_coverage(scenes, w)
    _fix_speed_map_boundaries(scenes, w)
    _fix_output_duration_recalc(scenes, w)
    _fix_total_duration_range(scenes, w)

    # Phase 3: Special Flags
    _fix_special_flags_hook(scenes, w)
    _fix_special_flags_loop(scenes, w)
    _fix_special_flags_easter(scenes, gen1_brief, w)

    # Phase 4: SFX & Action Peaks
    _fix_action_peak_timestamps(scenes, w)
    _fix_sfx_recommendation(scenes, w)
    _fix_sfx_from_gen1_brief(scenes, gen1_brief, w)

    # Phase 5: Loop & Handoff (ALWAYS LAST)
    _fix_loop_duration_match(scenes, w)
    _fix_gen3b_handoff(d, scenes, w)

    logger.info(f"GEN3a autocorrect: {len(w)} fixes applied to {len(scenes)} scenes")
    return d, w


# ============================================================================
# EXPORT
# ============================================================================

__all__ = ["autocorrect_gen3a", "AutoFixWarning"]
