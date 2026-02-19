"""
GEN1 Quality Comparison Report Generator

Generates a structured JSON report comparing:
- OLD: GEN1 v8.5.0 (275K prompt, no validator)
- NEW_RAW: GEN1 v9.0.0 (189K prompt, before validator)
- NEW_VALIDATED: GEN1 v9.0.0 + validator v2.0 (after auto-corrections)

Output: debug/test_outputs/comparison_report.json

Usage:
    python -X utf8 run_comparison_report.py
"""

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_DIR = PROJECT_ROOT / "debug" / "test_outputs"


# ---------------------------------------------------------------------------
# Quality metrics extraction
# ---------------------------------------------------------------------------

def extract_quality_metrics(data: dict, label: str) -> dict:
    """Extract comprehensive quality metrics from a GEN1 JSON output."""

    meta = data.get("metadata", {})
    concept = meta.get("concept", {})
    scenes = data.get("scenes", [])
    hook = data.get("hook", {})
    arch = data.get("architectural_identity", {})
    food = data.get("food_identity", {})
    light = data.get("lighting_master", {})
    fg = data.get("foreground_element", {})
    vo = data.get("voiceover", {})
    audio = data.get("audio", {})
    engage = data.get("engagement", {})
    yt = data.get("youtube", {})
    viral = data.get("viral_assessment", {})
    comp_bait = data.get("completion_bait", {})

    # --- TOP LEVEL FIELDS ---
    top_level_keys = set(data.keys())
    required_top = {
        "metadata", "property", "hook", "architectural_identity",
        "food_identity", "lighting_master", "foreground_element",
        "scenes", "voiceover", "audio", "engagement", "youtube",
    }
    optional_top = {
        "viral_assessment", "completion_bait", "sensory_pressure_map",
        "temperature_contrast", "warning_line",
    }

    # --- SCENE ANALYSIS ---
    scene_metrics = []
    for s in scenes:
        if not isinstance(s, dict):
            continue
        vc = s.get("visual_concept", {}) or {}
        ci = s.get("camera_intent", {}) or {}

        sm = {
            "scene_number": s.get("scene_number"),
            "scene_name": s.get("scene_name", ""),
            "duration_seconds": s.get("duration_seconds"),
            "narrative_purpose": s.get("narrative_purpose", ""),
            "energy_level": s.get("energy_level", ""),
            "reference_hint": s.get("reference_hint", ""),
            "food_visual_ratio": s.get("food_visual_ratio", "MISSING"),
            "sensory_pressure": s.get("sensory_pressure"),
            # Visual concept completeness
            "vc_has_subject": bool(vc.get("subject")),
            "vc_has_environment": bool(vc.get("environment")),
            "vc_has_mood": bool(vc.get("mood")),
            "vc_has_key_elements": bool(vc.get("key_elements")),
            "vc_has_lighting_note": bool(vc.get("lighting_note")),
            "vc_has_motion_elements": bool(vc.get("motion_elements")),
            "vc_motion_count": len(vc.get("motion_elements", []) or []),
            # Camera intent completeness
            "ci_has_movement": bool(ci.get("movement")),
            "ci_has_combo": bool(ci.get("combo")),
            "ci_has_framing": bool(ci.get("framing")),
            "ci_has_special": bool(ci.get("special")),
            # VO
            "voiceover_segment": s.get("voiceover_segment", ""),
            "narrator_script": s.get("narrator_script", ""),
            "narrator_word_count": len(s.get("narrator_script", "").split()) if s.get("narrator_script") else 0,
            "audio_moment": s.get("audio_moment", ""),
            # Extras
            "on_screen_text": s.get("on_screen_text", ""),
            "has_first_frame_composition": bool(s.get("first_frame_composition")),
        }
        scene_metrics.append(sm)

    # --- VOICEOVER ANALYSIS ---
    full_script = vo.get("full_script", "") if isinstance(vo, dict) else ""
    segments = [s.get("voiceover_segment", "") for s in scenes if isinstance(s, dict)]

    # ElevenLabs tags used
    elevenlabs_tags = set()
    tag_pattern = re.compile(r'\[(whispers|calm|warm|gentle|excited|sad|angry|happily|shouts|pause|long pause|silence)\]', re.IGNORECASE)
    for seg in segments:
        for m in tag_pattern.finditer(seg):
            elevenlabs_tags.add(m.group(0).lower())

    # Sensory channel analysis
    thermal_words = {"warm", "hot", "cold", "cool", "frozen", "burning", "searing", "chilled", "steaming", "melting", "boiling", "sizzling", "scalding", "icy", "tepid", "toasty", "heated", "frosty", "crisp"}
    tactile_words = {"sticky", "smooth", "rough", "soft", "hard", "crunchy", "crispy", "gooey", "thick", "thin", "dense", "wet", "dry", "flaky", "crumbly", "tender", "chewy", "brittle", "silky", "velvety"}
    olfactory_words = {"smell", "scent", "aroma", "fragrant", "stink", "musty", "earthy", "fresh", "pungent", "sweet-smelling", "nose", "sniff", "whiff"}
    temporal_words = {"fresh", "yesterday", "morning", "hours ago", "just", "still", "first", "before", "after", "overnight", "ripe", "aged", "fermented"}

    all_vo_text = " ".join(segments).lower()
    sensory_channels = {
        "THERMAL": any(w in all_vo_text for w in thermal_words),
        "TACTILE": any(w in all_vo_text for w in tactile_words),
        "OLFACTORY": any(w in all_vo_text for w in olfactory_words),
        "TEMPORAL_FRESHNESS": any(w in all_vo_text for w in temporal_words),
    }

    # --- MONEY SHOT ---
    money_shot_idx = None
    money_shot_vo = ""
    for s in scenes:
        if isinstance(s, dict) and "money" in s.get("scene_name", "").lower():
            money_shot_idx = s.get("scene_number")
            money_shot_vo = s.get("voiceover_segment", "")
            break

    # --- WARNING LINE ---
    wl = data.get("warning_line", {})

    # --- SP CURVE ---
    sp_values = []
    for s in scenes:
        if isinstance(s, dict):
            sp = s.get("sensory_pressure")
            if sp is not None:
                sp_values.append(sp)

    sp_peak_idx = sp_values.index(max(sp_values)) + 1 if sp_values else None
    sp_peak_val = max(sp_values) if sp_values else None
    total_scenes = len(scenes)
    sp_peak_in_last_third = sp_peak_idx >= (total_scenes * 2 / 3) if sp_peak_idx else None

    # --- YOUTUBE ---
    tags = yt.get("tags", []) or []
    title_variants = yt.get("title_variants", []) or []
    desc_variants = yt.get("description_variants", []) or []

    # --- BUILD REPORT ---
    return {
        "label": label,
        "topic": concept.get("subject", "N/A"),
        "food": food.get("primary_food", "N/A"),
        "category": concept.get("category", "N/A"),

        # Structural completeness
        "structure": {
            "total_scenes": len(scenes),
            "scene_count_declared": meta.get("scene_count"),
            "scene_count_match": meta.get("scene_count") == len(scenes),
            "top_level_present": sorted(top_level_keys & required_top),
            "top_level_missing": sorted(required_top - top_level_keys),
            "optional_present": sorted(top_level_keys & optional_top),
            "has_completion_bait": bool(comp_bait),
            "has_warning_line": bool(wl),
            "has_sensory_pressure_map": "sensory_pressure_map" in data,
            "has_temperature_contrast": "temperature_contrast" in data,
        },

        # Hook
        "hook": {
            "type": hook.get("type", "MISSING"),
            "has_first_words": bool(hook.get("first_words")),
            "has_psych_trigger": bool(hook.get("psychological_trigger")),
            "has_scroll_stop": bool(hook.get("scroll_stop_mechanism")),
            "has_sonic_hook": bool(hook.get("sonic_hook")),
            "sonic_hook_type": hook.get("sonic_hook", {}).get("type", "MISSING") if isinstance(hook.get("sonic_hook"), dict) else "MISSING",
        },

        # Architecture
        "architecture": {
            "style_code": arch.get("style_code", "MISSING"),
            "has_style_description": bool(arch.get("style_description")),
            "has_distinctive_features": bool(arch.get("distinctive_features")),
            "distinctive_features_count": len(arch.get("distinctive_features", []) or []),
            "has_silhouette": bool(arch.get("silhouette_description")),
            "has_interior_style": bool(arch.get("interior_style")),
        },

        # Food
        "food_identity": {
            "primary_food": food.get("primary_food", "MISSING"),
            "has_food_dna": bool(food.get("food_dna")),
            "food_dna_keys": sorted(food.get("food_dna", {}).keys()) if isinstance(food.get("food_dna"), dict) else [],
            "texture_keywords": food.get("texture_keywords", []),
            "color_keywords": food.get("color_keywords", []),
            "has_atmosphere": bool(food.get("atmosphere")),
        },

        # Scenes (per-scene metrics)
        "scenes": scene_metrics,

        # Scene-level aggregates
        "scene_aggregates": {
            "total_duration": sum(s.get("duration_seconds", 0) or 0 for s in scenes if isinstance(s, dict)),
            "scene1_duration": scenes[0].get("duration_seconds") if scenes else None,
            "sceneN_duration": scenes[-1].get("duration_seconds") if scenes else None,
            "narrative_purposes": [s.get("narrative_purpose", "") for s in scenes if isinstance(s, dict)],
            "energy_levels": [s.get("energy_level", "") for s in scenes if isinstance(s, dict)],
            "food_visual_ratios": [s.get("food_visual_ratio", "MISSING") for s in scenes if isinstance(s, dict)],
            "scene_n_minus_1_is_aerial": scenes[-2].get("scene_name", "").upper().find("AERIAL") >= 0 if len(scenes) >= 2 else None,
            "scene_n_is_loop": "loop" in scenes[-1].get("scene_name", "").lower() if scenes else None,
            "has_structural_detail": any("structural" in s.get("scene_name", "").lower() for s in scenes),
            "scene1_has_thermal_first": False,  # filled below
        },

        # Voiceover quality
        "voiceover": {
            "full_script": full_script,
            "full_script_word_count": len(full_script.split()) if full_script else 0,
            "segments": segments,
            "elevenlabs_tags_used": sorted(elevenlabs_tags),
            "has_silence_scene": any("[silence]" in seg for seg in segments),
            "sensory_channels": sensory_channels,
            "sensory_channels_present": sum(1 for v in sensory_channels.values() if v),
            "money_shot_scene": money_shot_idx,
            "money_shot_vo": money_shot_vo,
        },

        # Warning line
        "warning_line": {
            "text": wl.get("text", "MISSING") if isinstance(wl, dict) else "MISSING",
            "format": wl.get("format", "MISSING") if isinstance(wl, dict) else "MISSING",
            "element": wl.get("element", "MISSING") if isinstance(wl, dict) else "MISSING",
            "delivery_scene": wl.get("delivery_scene", "MISSING") if isinstance(wl, dict) else "MISSING",
        },

        # SP curve
        "sensory_pressure": {
            "values": sp_values,
            "peak_value": sp_peak_val,
            "peak_scene": sp_peak_idx,
            "peak_in_last_third": sp_peak_in_last_third,
        },

        # Audio
        "audio": {
            "has_sonic_hook": bool(audio.get("sonic_hook")),
            "has_suno_prompt": bool(audio.get("suno_prompt")),
            "has_foley_palette": bool(audio.get("foley_palette")),
            "foley_count": len(audio.get("foley_palette", []) or []),
            "has_sfx_per_scene": bool(audio.get("sfx_per_scene")),
            "sfx_scene_count": len(audio.get("sfx_per_scene", []) or []),
        },

        # Engagement
        "engagement": {
            "has_easter_egg": bool(engage.get("easter_egg")),
            "has_share_trigger": bool(engage.get("share_trigger")),
            "has_comment_bait": bool(engage.get("comment_bait")),
            "has_hashtags": bool(engage.get("hashtags")),
            "hashtag_count": len(engage.get("hashtags", []) or []),
        },

        # YouTube
        "youtube": {
            "has_title": bool(yt.get("title")),
            "title": yt.get("title", "MISSING"),
            "has_description": bool(yt.get("description")),
            "description_line1": yt.get("description", "").split("\n")[0] if yt.get("description") else "MISSING",
            "title_variants_count": len(title_variants),
            "description_variants_count": len(desc_variants),
            "tag_count": len(tags),
            "tags": tags,
            "has_pinned_comment": bool(yt.get("pinned_comment")),
        },

        # Viral assessment
        "viral_assessment": {
            "overall_score": viral.get("overall_score", "MISSING"),
            "verdict": viral.get("verdict", "MISSING"),
        },

        # Lighting
        "lighting": {
            "preset": light.get("preset", "MISSING"),
            "has_mood_reason": bool(light.get("mood_reason")),
            "has_prompt_snippet": bool(light.get("prompt_snippet")),
        },
    }


def check_thermal_first(metrics: dict) -> None:
    """Check if Scene 1 narrator starts with a temperature word."""
    thermal_starters = {"warm", "hot", "cold", "cool", "frozen", "burning", "still", "fresh", "steaming", "melting", "boiling", "sizzling", "crisp"}
    scenes = metrics.get("scenes", [])
    if scenes:
        narrator = scenes[0].get("narrator_script", "").lower()
        first_word = narrator.split()[0] if narrator.split() else ""
        metrics["scene_aggregates"]["scene1_has_thermal_first"] = first_word in thermal_starters or "warm" in narrator.split()[:3]


def generate_comparison() -> dict:
    """Generate comparison report from all available smoke tests."""

    files = {
        # OLD approach: v8.5.0 prompt (275K), no validator
        "OLD_v850_croissant": ("smoke16_croissant.json", "GEN1 v8.5.0 (275K prompt, no validator)"),
        "OLD_v850_chocolate": ("smoke18_chocolate.json", "GEN1 v8.5.0 (275K prompt, no validator)"),

        # NEW approach: v9.0.0 prompt (189K), BEFORE validator
        "NEW_v900_raw_auto": ("smoke19_auto.json", "GEN1 v9.0.0 (189K prompt, BEFORE validator)"),
        "NEW_v900_raw_matcha": ("smoke20_matcha.json", "GEN1 v9.0.0 (189K prompt, BEFORE validator)"),
        "NEW_v900_raw_honey": ("smoke21_honey.json", "GEN1 v9.0.0 (189K prompt, BEFORE validator)"),

        # NEW approach: v9.0.0 prompt + validator v2.0 (AFTER auto-corrections)
        "NEW_v900_val_auto": ("smoke19_auto_validated.json", "GEN1 v9.0.0 + validator v2.0 (AFTER auto-corrections)"),
        "NEW_v900_val_matcha": ("smoke20_matcha_validated.json", "GEN1 v9.0.0 + validator v2.0 (AFTER auto-corrections)"),
        "NEW_v900_val_honey": ("smoke21_honey_validated.json", "GEN1 v9.0.0 + validator v2.0 (AFTER auto-corrections)"),
    }

    report = {
        "_meta": {
            "description": "GEN1 Quality Comparison Report",
            "purpose": "Compare OLD approach (v8.5.0 big prompt, no validator) vs NEW approach (v9.0.0 compressed prompt + validator v2.0)",
            "methodology": "Extract identical quality metrics from each output and compare side-by-side",
            "approaches": {
                "OLD_v850": "GEN1 prompt v8.5.0 (275K chars, ~77K tokens). Everything enforced in the prompt. No Python validator.",
                "NEW_v900_raw": "GEN1 prompt v9.0.0 (189K chars, ~53K tokens, -31% compression). Same rules, shorter prompt. No validator applied yet.",
                "NEW_v900_validated": "GEN1 v9.0.0 + Python validator v2.0 (22 deterministic auto-fixes + 15 validation checks). ~5-10ms, 0 tokens.",
            },
            "key_questions": [
                "Does the compressed prompt (v9.0.0) lose structural completeness vs the big prompt (v8.5.0)?",
                "Does the validator successfully compensate for prompt compression losses?",
                "Which fields are consistently wrong in raw output but fixed by validator?",
                "Are there quality regressions that neither prompt nor validator catch?",
            ],
        },
        "samples": {},
    }

    for key, (filename, description) in files.items():
        path = OUTPUT_DIR / filename
        if not path.exists():
            print(f"  SKIP: {filename} not found")
            continue

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        metrics = extract_quality_metrics(data, description)
        check_thermal_first(metrics)
        report["samples"][key] = metrics
        print(f"  OK: {key} ({filename})")

    # --- CROSS-SAMPLE SUMMARY ---
    summary = {
        "structural_completeness": {},
        "field_comparison": {},
    }

    for key, metrics in report["samples"].items():
        struct = metrics["structure"]
        summary["structural_completeness"][key] = {
            "top_level_missing": struct["top_level_missing"],
            "total_scenes": struct["total_scenes"],
            "scene_count_match": struct["scene_count_match"],
            "has_completion_bait": struct["has_completion_bait"],
            "has_warning_line": struct["has_warning_line"],
            "has_sensory_pressure_map": struct["has_sensory_pressure_map"],
            "has_temperature_contrast": struct["has_temperature_contrast"],
        }

        sa = metrics["scene_aggregates"]
        summary["field_comparison"][key] = {
            "hook_type": metrics["hook"]["type"],
            "sensory_channels_4of4": metrics["voiceover"]["sensory_channels_present"],
            "has_structural_detail_scene": sa["has_structural_detail"],
            "scene_n_minus_1_aerial": sa["scene_n_minus_1_is_aerial"],
            "scene_n_loop": sa["scene_n_is_loop"],
            "scene1_thermal_first": sa["scene1_has_thermal_first"],
            "sp_peak_in_last_third": metrics["sensory_pressure"]["peak_in_last_third"],
            "money_shot_vo": metrics["voiceover"]["money_shot_vo"],
            "title_variants": metrics["youtube"]["title_variants_count"],
            "desc_variants": metrics["youtube"]["description_variants_count"],
            "pinned_comment": metrics["youtube"]["has_pinned_comment"],
            "elevenlabs_tags": metrics["voiceover"]["elevenlabs_tags_used"],
        }

    report["summary"] = summary
    return report


if __name__ == "__main__":
    print("Generating comparison report...")
    report = generate_comparison()

    out_path = OUTPUT_DIR / "comparison_report.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\nSaved: {out_path} ({out_path.stat().st_size:,} bytes)")
    print(f"Samples: {len(report['samples'])}")

    # Quick console summary
    print("\n" + "=" * 70)
    print("  QUICK COMPARISON")
    print("=" * 70)

    for key, comp in report.get("summary", {}).get("field_comparison", {}).items():
        label = report["samples"][key]["label"]
        topic = report["samples"][key]["topic"]
        print(f"\n  [{key}] {topic}")
        print(f"    {label}")
        print(f"    Hook: {comp['hook_type']}")
        print(f"    Sensory channels: {comp['sensory_channels_4of4']}/4")
        print(f"    STRUCTURAL_DETAIL scene: {comp['has_structural_detail_scene']}")
        print(f"    N-1=AERIAL: {comp['scene_n_minus_1_aerial']}")
        print(f"    N=LOOP: {comp['scene_n_loop']}")
        print(f"    Scene 1 THERMAL first: {comp['scene1_thermal_first']}")
        print(f"    SP peak last third: {comp['sp_peak_in_last_third']}")
        print(f"    Money shot VO: \"{comp['money_shot_vo'][:60]}\"")
        print(f"    Title variants: {comp['title_variants']}")
        print(f"    Desc variants: {comp['desc_variants']}")
        print(f"    Pinned comment: {comp['pinned_comment']}")

    print("\n" + "=" * 70)
