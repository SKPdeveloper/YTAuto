"""
GEN3b Auto-Corrector v1.1

Deterministic auto-fix layer for GEN3b (FFmpeg Manifest) output.
Runs BEFORE conversion to fix known Gemini 3 Pro hallucinations.

Architecture mirrors gen1_autocorrect.py / gen2_autocorrect.py:
    corrected_data, warnings = autocorrect_gen3b(raw_json, gen3a_data, gen1_brief)

20 auto-fixes in 5 phases:
  Phase 1: Structural (P0)        — scene key, numbers, timeline nulls/order, cuts type
  Phase 2: Speed & Timing (P0-P1) — speed location, gen3a fallback, continuity,
                                     gen3a duration enforcement, total duration cap
  Phase 3: SFX Events (P0)        — populate from gen3a peaks, fallback, dedup
  Phase 4: Audio & Subtitles (P1) — audio layers, subtitle uppercase, hook style, loop
  Phase 5: Validation (P1-P2)     — total duration, effect palette compliance
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from app.services.gen1_autocorrect import AutoFixWarning
from app.services.timing_utils import (
    transform_source_to_output,
    calculate_output_duration,
)


# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

# Valid effect palettes
VALID_EFFECT_PALETTES: set = {
    "DRAMATIC", "ELEGANT", "AGGRESSIVE", "MINIMAL", "ORGANIC",
    "CINEMATIC", "EPIC", "WARM", "COLD", "NEUTRAL",
}

MIN_SPEED = 1.5
VO_PADDING = 0.3  # scene_dur must be >= vo_dur + VO_PADDING
TARGET_TOTAL_MAX_GEN3B = 25.0  # hard cap for total video duration (seconds)


# ---------------------------------------------------------------------------
# PHASE 1: STRUCTURAL (P0)
# ---------------------------------------------------------------------------

def _fix_scene_list_key(d: dict, w: list) -> None:
    """Fix #1: Normalize scene list key: timeline → scenes."""
    if "timeline" in d and "scenes" not in d:
        d["scenes"] = d.pop("timeline")
        w.append(AutoFixWarning("scenes", "Renamed 'timeline' → 'scenes'"))
    if "scene_list" in d and "scenes" not in d:
        d["scenes"] = d.pop("scene_list")
        w.append(AutoFixWarning("scenes", "Renamed 'scene_list' → 'scenes'"))


def _fix_scene_number_types(scenes: list, w: list) -> None:
    """Fix #2: Normalize scene_number: "N (last scene)" → int N."""
    for i, scene in enumerate(scenes):
        raw = scene.get("scene_number")
        expected = i + 1

        if raw is None:
            scene["scene_number"] = expected
            w.append(AutoFixWarning(f"scene_{expected}.scene_number",
                                    f"null → {expected}"))
        elif isinstance(raw, str):
            digits = re.findall(r'\d+', raw)
            scene["scene_number"] = int(digits[0]) if digits else expected
            w.append(AutoFixWarning(f"scene_{expected}.scene_number",
                                    f"'{raw}' → {scene['scene_number']}"))
        elif isinstance(raw, float):
            scene["scene_number"] = int(raw)


def _fix_timeline_nulls(scenes: list, gen3a_data: Optional[dict], w: list) -> None:
    """Fix #3: Calculate timeline_start/end from speed_segments or gen3a."""
    for scene in scenes:
        sn = scene.get("scene_number", "?")
        has_start = scene.get("timeline_start") is not None
        has_end = scene.get("timeline_end") is not None

        if has_start and has_end:
            continue

        # Try to calculate from speed_segments
        speed_segs = scene.get("speed_segments", [])
        if speed_segs:
            scene_dur = calculate_output_duration(
                [s if isinstance(s, dict) else {} for s in speed_segs]
            )
        elif gen3a_data:
            # Fallback to gen3a output_duration
            gen3a_scenes = gen3a_data.get("scenes", [])
            matching = [s for s in gen3a_scenes
                       if s.get("scene_number") == scene.get("scene_number")]
            scene_dur = float(matching[0].get("output_duration", 2.0)) if matching else 2.0
        else:
            scene_dur = 2.0

        if not has_start:
            scene["timeline_start"] = 0.0
        if not has_end:
            scene["timeline_end"] = float(scene.get("timeline_start", 0)) + scene_dur

        w.append(AutoFixWarning(f"scene_{sn}.timeline",
                               f"Computed timeline: {scene['timeline_start']:.2f}—{scene['timeline_end']:.2f}"))


def _fix_timeline_order(scenes: list, w: list) -> None:
    """Fix #4: Fix timeline_end <= timeline_start."""
    for scene in scenes:
        sn = scene.get("scene_number", "?")
        start = float(scene.get("timeline_start", 0))
        end = float(scene.get("timeline_end", 0))

        if end <= start:
            # Calculate from speed segments or default 2.0s
            speed_segs = scene.get("speed_segments", [])
            if speed_segs:
                dur = calculate_output_duration(
                    [s if isinstance(s, dict) else {} for s in speed_segs]
                )
            else:
                dur = 2.0
            scene["timeline_end"] = round(start + dur, 4)
            w.append(AutoFixWarning(f"scene_{sn}.timeline",
                                   f"end ({end}) <= start ({start}), fixed to {scene['timeline_end']}"))


def _fix_cuts_type(scenes: list, w: list) -> None:
    """Fix #5: Convert cuts from dict {"has_cuts": false} → list []."""
    for scene in scenes:
        sn = scene.get("scene_number", "?")
        cuts = scene.get("cuts")
        if isinstance(cuts, dict):
            cut_list = cuts.get("cut_list", cuts.get("cuts", []))
            if isinstance(cut_list, list):
                scene["cuts"] = cut_list
            else:
                scene["cuts"] = []
            w.append(AutoFixWarning(f"scene_{sn}.cuts", "dict → list"))
        elif cuts is None:
            scene["cuts"] = []


# ---------------------------------------------------------------------------
# PHASE 2: SPEED & TIMING (P0-P1)
# ---------------------------------------------------------------------------

def _fix_speed_segments_location(scenes: list, w: list) -> None:
    """Fix #6: Extract speed_segments from speed_processing.speed_map."""
    for scene in scenes:
        sn = scene.get("scene_number", "?")
        if scene.get("speed_segments"):
            continue

        speed_proc = scene.get("speed_processing", {})
        if isinstance(speed_proc, dict):
            speed_map = speed_proc.get("speed_map", [])
            if speed_map:
                scene["speed_segments"] = copy.deepcopy(speed_map)
                w.append(AutoFixWarning(f"scene_{sn}.speed_segments",
                                       "Extracted from speed_processing.speed_map"))


def _fix_speed_segments_from_gen3a(scenes: list, gen3a_data: Optional[dict], w: list) -> None:
    """Fix #7: Empty speed_segments → fallback on gen3a speed_map."""
    if not gen3a_data:
        return

    gen3a_scenes = {
        s.get("scene_number"): s
        for s in gen3a_data.get("scenes", [])
    }

    for scene in scenes:
        sn = scene.get("scene_number")
        if scene.get("speed_segments"):
            continue

        gen3a_scene = gen3a_scenes.get(sn, {})
        speed_map = gen3a_scene.get("speed_map", [])
        if speed_map:
            scene["speed_segments"] = copy.deepcopy(speed_map)
            w.append(AutoFixWarning(f"scene_{sn}.speed_segments",
                                   f"Fallback to gen3a speed_map ({len(speed_map)} segments)"))


def _fix_timeline_continuity(scenes: list, w: list) -> None:
    """Fix #8: Ensure scene[i].end == scene[i+1].start (cascading rebuild)."""
    if len(scenes) < 2:
        return

    # Sort by scene_number
    scenes.sort(key=lambda s: int(s.get("scene_number", 0)))

    for i in range(1, len(scenes)):
        prev_end = float(scenes[i - 1].get("timeline_end", 0))
        curr_start = float(scenes[i].get("timeline_start", 0))

        if abs(prev_end - curr_start) > 0.01:
            scene_dur = float(scenes[i].get("timeline_end", 0)) - float(scenes[i].get("timeline_start", 0))
            scenes[i]["timeline_start"] = round(prev_end, 4)
            scenes[i]["timeline_end"] = round(prev_end + scene_dur, 4)
            sn = scenes[i].get("scene_number", "?")
            w.append(AutoFixWarning(f"scene_{sn}.timeline",
                                   f"Continuity fix: start {curr_start:.2f} → {prev_end:.2f}"))


def _fix_vo_timing_constraint(scenes: list, gen3a_data: Optional[dict], w: list) -> None:
    """Fix #9: Ensure scene_dur >= vo_dur + 0.3s."""
    if not gen3a_data:
        return

    # Build VO segment lookup from gen3a
    vo_segments = gen3a_data.get("vo_segments", [])
    vo_dur_by_scene = {}
    for vo in vo_segments:
        seg_id = vo.get("segment_id", "")
        # Extract scene number from segment_id like "VO1", "VO2"
        digits = re.findall(r'\d+', seg_id)
        if digits:
            scene_num = int(digits[0])
            source_start = float(vo.get("source_start", 0))
            source_end = float(vo.get("source_end", 0))
            vo_dur_by_scene[scene_num] = source_end - source_start

    for scene in scenes:
        sn = scene.get("scene_number")
        vo_dur = vo_dur_by_scene.get(sn, 0)
        if vo_dur <= 0:
            continue

        scene_dur = float(scene.get("timeline_end", 0)) - float(scene.get("timeline_start", 0))
        min_dur = vo_dur + VO_PADDING

        if scene_dur < min_dur:
            deficit = min_dur - scene_dur
            scene["timeline_end"] = round(float(scene.get("timeline_end", 0)) + deficit, 4)
            w.append(AutoFixWarning(f"scene_{sn}.timeline",
                                   f"Extended by {deficit:.2f}s for VO "
                                   f"(scene {scene_dur:.2f}s < vo {vo_dur:.2f}s + {VO_PADDING}s)"))


def _fix_enforce_gen3a_durations(scenes: list, gen3a_data: Optional[dict], w: list) -> None:
    """Fix #19: Scale speed_segments so scene_dur matches gen3a output_duration.

    GEN3b often ignores gen3a timing and generates its own slower speeds,
    inflating each scene by +1-2s.  This fix rescales speed_segments
    proportionally so that the output duration of each scene equals
    the gen3a-analysed output_duration.
    """
    if not gen3a_data:
        return

    gen3a_scenes = gen3a_data.get("scenes", gen3a_data.get("scene_analysis", []))
    gen3a_dur = {
        s.get("scene_number"): float(s.get("output_duration", 0))
        for s in gen3a_scenes
    }

    for scene in scenes:
        sn = scene.get("scene_number")
        target = gen3a_dur.get(sn)
        if not target or target <= 0:
            continue

        current = float(scene.get("timeline_end", 0)) - float(scene.get("timeline_start", 0))
        if current <= 0 or abs(current - target) < 0.1:
            continue  # tolerance 0.1s

        # ratio >1 means scene is too long → speeds must increase
        ratio = current / target

        for seg in scene.get("speed_segments", []):
            old_speed = float(seg.get("speed", 2.0))
            seg["speed"] = round(max(1.0, old_speed * ratio), 4)
            src_dur = float(seg.get("source_end", 0)) - float(seg.get("source_start", 0))
            seg["output_duration"] = round(src_dur / seg["speed"], 4)

        # Recalculate timeline_end from speed_segments
        new_dur = sum(float(seg.get("output_duration", 0)) for seg in scene.get("speed_segments", []))
        if new_dur <= 0:
            new_dur = target
        scene["timeline_end"] = round(float(scene.get("timeline_start", 0)) + new_dur, 4)
        w.append(AutoFixWarning(
            f"scene_{sn}.duration",
            f"Enforced gen3a duration: {current:.2f}s → {new_dur:.2f}s (target {target:.2f}s)",
        ))


def _fix_total_duration_cap(d: dict, scenes: list, w: list) -> None:
    """Fix #20: Proportionally compress all scenes if total > TARGET_TOTAL_MAX_GEN3B (25s).

    This is the last-resort cap — even if gen3a durations are honoured,
    the sum across 8-10 scenes can still exceed the Shorts budget.
    """
    if not scenes:
        return

    total = float(scenes[-1].get("timeline_end", 0))
    if total <= TARGET_TOTAL_MAX_GEN3B:
        return

    ratio = TARGET_TOTAL_MAX_GEN3B / total  # <1 → compress
    cumulative = 0.0

    for scene in scenes:
        old_dur = float(scene.get("timeline_end", 0)) - float(scene.get("timeline_start", 0))
        new_dur = round(old_dur * ratio, 4)
        scene["timeline_start"] = round(cumulative, 4)
        scene["timeline_end"] = round(cumulative + new_dur, 4)

        # Increase speeds by 1/ratio to compress output
        for seg in scene.get("speed_segments", []):
            old_speed = float(seg.get("speed", 2.0))
            seg["speed"] = round(max(1.0, old_speed / ratio), 4)
            src_dur = float(seg.get("source_end", 0)) - float(seg.get("source_start", 0))
            seg["output_duration"] = round(src_dur / seg["speed"], 4)

        cumulative += new_dur

    d["total_duration"] = round(cumulative, 4)
    w.append(AutoFixWarning(
        "total_duration",
        f"Duration cap: {total:.2f}s → {cumulative:.2f}s (max {TARGET_TOTAL_MAX_GEN3B}s)",
    ))


# ---------------------------------------------------------------------------
# PHASE 3: SFX EVENTS — MAIN FIX (P0)
# ---------------------------------------------------------------------------

def _fix_populate_sfx_events(d: dict, scenes: list, gen3a_data: Optional[dict], w: list) -> None:
    """Fix #10: Create sfx_events from gen3a action_peaks.

    KEY FIX: Transforms source_timestamp through speed_segments
    to get accurate output_timestamp, then adds timeline_start offset.
    """
    if not gen3a_data:
        return

    gen3a_scenes = {
        s.get("scene_number"): s
        for s in gen3a_data.get("scenes", [])
    }

    # Ensure audio_layers exists
    audio_layers = d.get("audio_layers", {})
    if not isinstance(audio_layers, dict):
        audio_layers = {}
    existing_sfx = audio_layers.get("sfx_events", [])

    # Don't override if Gemini already generated non-empty SFX
    if existing_sfx:
        return

    new_sfx_events = []

    for scene in scenes:
        sn = scene.get("scene_number")
        gen3a_scene = gen3a_scenes.get(sn, {})
        peaks = gen3a_scene.get("action_peaks", [])
        speed_segments = scene.get("speed_segments", [])
        timeline_start = float(scene.get("timeline_start", 0))

        for peak in peaks:
            source_ts = float(peak.get("source_timestamp", 0))
            sfx_rec = peak.get("sfx_recommendation", {})
            if not sfx_rec:
                # Fallback: generate SFX recommendation from peak type
                # (handles case when gen3a_autocorrect didn't run)
                peak_type = peak.get("type", "MOTION_PEAK")
                sfx_type_map = {
                    "MOTION_BURST": "IMPACT", "MOTION_PEAK": "IMPACT",
                    "REVEAL": "MOTION", "TRANSITION": "WHOOSH",
                }
                sfx_rec = {
                    "type": sfx_type_map.get(peak_type, "IMPACT"),
                    "intensity": float(peak.get("intensity", 0.8)),
                    "file": f"scene_{sn}_sfx.mp3",
                }

            # Transform source timestamp → output timestamp
            output_relative = transform_source_to_output(source_ts, speed_segments)
            output_absolute = round(timeline_start + output_relative, 4)

            sfx_file = sfx_rec.get("file", f"scene_{sn}_sfx.mp3")
            sfx_type = sfx_rec.get("type", "IMPACT")
            peak_id = peak.get("id", f"S{sn}_AP1")

            new_sfx_events.append({
                "id": f"sfx_{peak_id}",
                "output_timestamp": output_absolute,
                "effect": sfx_type,
                "file": sfx_file,
                "volume": min(1.0, float(sfx_rec.get("intensity", 0.8))),
                "source": "gen3a_action_peak",
            })

    if new_sfx_events:
        audio_layers["sfx_events"] = new_sfx_events
        d["audio_layers"] = audio_layers
        w.append(AutoFixWarning("audio_layers.sfx_events",
                               f"Populated {len(new_sfx_events)} SFX events from gen3a action_peaks"))


def _fix_sfx_for_scenes_without_peaks(
    d: dict, scenes: list, gen3a_data: Optional[dict], w: list
) -> None:
    """Fix #11: Scenes without gen3a peaks → SFX at timeline_start + 0.3s (NOT midpoint)."""
    if not gen3a_data:
        return

    gen3a_scenes = {
        s.get("scene_number"): s
        for s in gen3a_data.get("scenes", [])
    }

    audio_layers = d.get("audio_layers", {})
    if not isinstance(audio_layers, dict):
        audio_layers = {}
    sfx_events = audio_layers.get("sfx_events", [])

    # Find scenes that already have SFX
    scenes_with_sfx = set()
    for sfx in sfx_events:
        sfx_id = sfx.get("id", "")
        digits = re.findall(r'S(\d+)', sfx_id)
        if digits:
            scenes_with_sfx.add(int(digits[0]))

    added = 0
    for scene in scenes:
        sn = scene.get("scene_number")
        if sn in scenes_with_sfx:
            continue

        gen3a_scene = gen3a_scenes.get(sn, {})
        peaks = gen3a_scene.get("action_peaks", [])
        if peaks:
            continue  # Has peaks but SFX was added in fix #10

        timeline_start = float(scene.get("timeline_start", 0))
        sfx_timestamp = round(timeline_start + 0.3, 4)

        sfx_events.append({
            "id": f"sfx_S{sn}_fallback",
            "output_timestamp": sfx_timestamp,
            "effect": "IMPACT",
            "file": f"scene_{sn}_sfx.mp3",
            "volume": 0.7,
            "source": "no_peak_fallback",
        })
        added += 1

    if added:
        audio_layers["sfx_events"] = sfx_events
        d["audio_layers"] = audio_layers
        w.append(AutoFixWarning("audio_layers.sfx_events",
                               f"Added {added} fallback SFX for scenes without peaks"))


def _fix_sfx_dedup(d: dict, w: list) -> None:
    """Fix #12: Remove SFX events with delta < 0.3s."""
    audio_layers = d.get("audio_layers", {})
    if not isinstance(audio_layers, dict):
        return

    sfx_events = audio_layers.get("sfx_events", [])
    if len(sfx_events) < 2:
        return

    sfx_events.sort(key=lambda s: float(s.get("output_timestamp", 0)))
    deduped = [sfx_events[0]]

    for sfx in sfx_events[1:]:
        prev_ts = float(deduped[-1].get("output_timestamp", 0))
        curr_ts = float(sfx.get("output_timestamp", 0))
        if curr_ts - prev_ts >= 0.3:
            deduped.append(sfx)
        else:
            w.append(AutoFixWarning("sfx_dedup",
                                   f"Removed SFX at {curr_ts:.2f}s "
                                   f"(delta {curr_ts - prev_ts:.2f}s < 0.3s)"))

    if len(deduped) != len(sfx_events):
        audio_layers["sfx_events"] = deduped


# ---------------------------------------------------------------------------
# PHASE 4: AUDIO & SUBTITLES (P1-P2)
# ---------------------------------------------------------------------------

def _fix_audio_layers_structure(d: dict, w: list) -> None:
    """Fix #13: Normalize audio layers: nested → flat, ensure bed+music+vo."""
    audio = d.get("audio_layers") or d.get("audio", {})
    if not isinstance(audio, dict):
        audio = {}

    # Handle "layers" list format → flat dict
    if "layers" in audio:
        layers_list = audio.get("layers", [])
        flat = {}
        for layer in layers_list:
            if not isinstance(layer, dict):
                continue
            layer_type = str(layer.get("type", "")).upper()
            if layer_type == "MUSIC":
                flat["music"] = {
                    "layer": "MUSIC",
                    "file": layer.get("file", ""),
                    "volume": layer.get("volume", 1.0),
                    "duck_during_vo": layer.get("duck_during_vo", True),
                    "duck_amount": 0.4,
                }
            elif layer_type in ("VOICEOVER", "VO"):
                flat["vo"] = {
                    "layer": "VO",
                    "file": layer.get("file", ""),
                    "volume": layer.get("volume", 1.0),
                }
            elif layer_type == "BED":
                flat["bed"] = {
                    "layer": "BED",
                    "file": layer.get("file", ""),
                    "volume": layer.get("volume", 0.3),
                }
            elif layer_type == "SFX":
                flat["sfx_events"] = layer.get("events", [])
            elif layer_type == "FOLEY":
                flat["foley_events"] = layer.get("events", [])

        # Preserve existing sfx_events/foley_events if not in layers
        if "sfx_events" not in flat and "sfx_events" in audio:
            flat["sfx_events"] = audio["sfx_events"]
        if "foley_events" not in flat and "foley_events" in audio:
            flat["foley_events"] = audio["foley_events"]

        audio = flat
        w.append(AutoFixWarning("audio_layers", "Converted nested layers → flat structure"))

    # Ensure required layers exist
    if "bed" not in audio:
        audio["bed"] = {"layer": "BED", "file": "", "volume": 0.3}
    if "music" not in audio:
        audio["music"] = {"layer": "MUSIC", "file": "", "volume": 1.0,
                         "duck_during_vo": True, "duck_amount": 0.4}
    if "vo" not in audio:
        audio["vo"] = {"layer": "VO", "file": "", "volume": 1.0}
    if "sfx_events" not in audio:
        audio["sfx_events"] = []
    if "foley_events" not in audio:
        audio["foley_events"] = []

    d["audio_layers"] = audio


def _fix_subtitle_uppercase(d: dict, w: list) -> None:
    """Fix #14: Subtitle text → uppercase."""
    subtitles = d.get("subtitles", [])
    if not isinstance(subtitles, list):
        return

    count = 0
    for sub in subtitles:
        if isinstance(sub, dict):
            text = sub.get("text", "")
            if text and text != text.upper():
                sub["text"] = text.upper()
                count += 1

    if count:
        w.append(AutoFixWarning("subtitles", f"Uppercased {count} subtitle texts"))


def _fix_hook_style_match(d: dict, gen3a_data: Optional[dict], w: list) -> None:
    """Fix #15: Warning if hook style doesn't match gen3a recommendation."""
    if not gen3a_data:
        return

    hook = d.get("hook", {})
    if not isinstance(hook, dict):
        return

    gen3a_hook = gen3a_data.get("hook_variety_analysis", {})
    recommended = gen3a_hook.get("recommended_style", "")
    actual = hook.get("style", "")

    if recommended and actual and actual != recommended:
        w.append(AutoFixWarning("hook.style",
                               f"Style '{actual}' ≠ gen3a recommended '{recommended}' "
                               f"(warning only, not auto-fixed)"))


def _fix_loop_duration_match(scenes: list, w: list) -> None:
    """Fix #16: Scene1.timeline_duration == SceneN.timeline_duration."""
    if len(scenes) < 2:
        return

    scene1 = scenes[0]
    sceneN = scenes[-1]
    dur1 = float(scene1.get("timeline_end", 0)) - float(scene1.get("timeline_start", 0))
    durN = float(sceneN.get("timeline_end", 0)) - float(sceneN.get("timeline_start", 0))

    if dur1 <= 0 or durN <= 0:
        return

    delta = abs(dur1 - durN)
    if delta <= 0.5:
        return

    # Adjust last scene end to match scene 1 duration
    new_end = round(float(sceneN.get("timeline_start", 0)) + dur1, 4)
    sceneN["timeline_end"] = new_end
    w.append(AutoFixWarning("loop_duration",
                           f"SceneN duration {durN:.2f}s → {dur1:.2f}s (match Scene1)"))


# ---------------------------------------------------------------------------
# PHASE 5: VALIDATION (P1-P2)
# ---------------------------------------------------------------------------

def _fix_total_duration(d: dict, scenes: list, w: list) -> None:
    """Fix #17: Recalculate total_duration from scenes."""
    if not scenes:
        return

    calculated = float(scenes[-1].get("timeline_end", 0))
    existing = d.get("total_duration", 0)

    if abs(calculated - float(existing or 0)) > 0.05:
        d["total_duration"] = round(calculated, 4)
        w.append(AutoFixWarning("total_duration",
                               f"{existing} → {d['total_duration']} (recalculated)"))


def _fix_effect_palette_compliance(scenes: list, w: list) -> None:
    """Fix #18: Warning if effect type not in valid palette (not auto-fixed)."""
    for scene in scenes:
        sn = scene.get("scene_number", "?")
        for effect in scene.get("effects", []):
            if isinstance(effect, dict):
                eff_type = effect.get("type", "")
                if eff_type and eff_type.upper() not in VALID_EFFECT_PALETTES:
                    # Just warn, don't auto-fix effects
                    w.append(AutoFixWarning(f"scene_{sn}.effects",
                                          f"Effect '{eff_type}' not in standard palette "
                                          f"(warning only)"))


# ---------------------------------------------------------------------------
# MAIN ENTRY POINT
# ---------------------------------------------------------------------------

def autocorrect_gen3b(
    data: Dict[str, Any],
    gen3a_data: Optional[Dict[str, Any]] = None,
    gen1_brief: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], List[AutoFixWarning]]:
    """
    Apply all deterministic auto-corrections to GEN3b output.

    Args:
        data: Raw GEN3b JSON output as dict.
        gen3a_data: Optional GEN3a output for speed/SFX fallback.
        gen1_brief: Optional GEN1 output for context.

    Returns:
        Tuple of (corrected_data, list_of_warnings).
        corrected_data is a deep copy — original is not mutated.
    """
    d = copy.deepcopy(data)
    w: List[AutoFixWarning] = []

    # Phase 1: Structural
    _fix_scene_list_key(d, w)
    scenes = d.get("scenes", [])
    _fix_scene_number_types(scenes, w)
    _fix_timeline_nulls(scenes, gen3a_data, w)
    _fix_timeline_order(scenes, w)
    _fix_cuts_type(scenes, w)

    # Phase 2: Speed & Timing
    _fix_speed_segments_location(scenes, w)
    _fix_speed_segments_from_gen3a(scenes, gen3a_data, w)
    _fix_timeline_continuity(scenes, w)
    _fix_enforce_gen3a_durations(scenes, gen3a_data, w)   # Fix #19
    _fix_timeline_continuity(scenes, w)                    # re-cascade after duration enforcement
    _fix_total_duration_cap(d, scenes, w)                  # Fix #20
    _fix_timeline_continuity(scenes, w)                    # re-cascade after cap
    # NOTE: _fix_vo_timing_constraint removed — it was the primary inflator (+8.6s).
    # ManifestRenderer handles VO fitting via _compress_and_retime_vo.

    # Phase 3: SFX Events — MAIN FIX
    _fix_audio_layers_structure(d, w)  # Must come before SFX population
    _fix_populate_sfx_events(d, scenes, gen3a_data, w)
    _fix_sfx_for_scenes_without_peaks(d, scenes, gen3a_data, w)
    _fix_sfx_dedup(d, w)

    # Phase 4: Audio & Subtitles
    _fix_subtitle_uppercase(d, w)
    _fix_hook_style_match(d, gen3a_data, w)
    _fix_loop_duration_match(scenes, w)

    # Phase 5: Validation
    _fix_total_duration(d, scenes, w)
    _fix_effect_palette_compliance(scenes, w)

    logger.info(f"GEN3b autocorrect: {len(w)} fixes applied to {len(scenes)} scenes")
    return d, w


# ============================================================================
# EXPORT
# ============================================================================

__all__ = ["autocorrect_gen3b", "AutoFixWarning"]
