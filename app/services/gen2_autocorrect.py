"""
GEN2 Auto-Corrector v1.0

Deterministic auto-fix layer for GEN2 (Visual Director) output.
Runs BEFORE gen2_validator.py to fix known Gemini 3 Pro hallucinations.

Architecture mirrors gen1_autocorrect.py:
    corrected_data, warnings = autocorrect_gen2(raw_gen2_json, gen1_json)

Separated from gen2_validator.py for maintainability and testability.
Each fix is a standalone method with clear pre/post conditions.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from app.services.gen1_autocorrect import AutoFixWarning


# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

# Tier assignment rules: sensory_pressure ranges → visual_tier
TIER_SP_MAP: Dict[str, Tuple[int, int]] = {
    "TIER_2_HIGH_APPETITE": (8, 9),
    "TIER_3_BALANCED": (5, 7),
    "TIER_4_ARCHITECTURE": (1, 4),
}

VALID_TIERS = {
    "TIER_1_MONEY_SHOT",
    "TIER_2_HIGH_APPETITE",
    "TIER_3_BALANCED",
    "TIER_4_ARCHITECTURE",
}

# Word count ranges per tier (image_prompt)
TIER_WORD_RANGES: Dict[str, Tuple[int, int]] = {
    "TIER_1_MONEY_SHOT": (130, 150),
    "TIER_2_HIGH_APPETITE": (80, 100),
    "TIER_3_BALANCED": (70, 90),
    "TIER_4_ARCHITECTURE": (90, 120),
}

# Body trigger channel → visual keywords to inject in Scene 1
# Synced with gen2_validator.py BODY_TRIGGER_KEYWORDS — MUST match
BODY_TRIGGER_KEYWORDS: Dict[str, List[str]] = {
    "MOUTH": ["glistening", "wet surface", "moisture beading", "liquid sheen", "dripping"],
    "SKIN": ["condensation droplets", "heat shimmer", "frost crystals", "temperature visible"],
    "EARS": ["fracture lines", "cracking surface", "splitting edge", "crevices", "shattered"],
    "NOSE": ["steam wisps rising", "visible vapor", "aromatic haze", "heat haze from surface"],
    "STOMACH": ["overflowing", "impossibly abundant", "stacked layers", "towering pile"],
}

# Energy level → minimum motion_intensity floor
ENERGY_MOTION_FLOOR: Dict[str, int] = {
    "EXPLOSIVE": 7,
    "HIGH": 5,
    "MEDIUM": 3,
    "LOW": 2,
}

# Tier-specific negative prompt additions
TIER_NEGATIVE_ADDITIONS: Dict[str, List[str]] = {
    "TIER_1_MONEY_SHOT": ["dry surface", "matte texture", "cold lighting on food"],
    "TIER_2_HIGH_APPETITE": ["dry surface", "matte texture"],
    "TIER_4_ARCHITECTURE": ["miniature feel", "toy-like proportions"],
}


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _get_gen1_scene(gen1_data: Optional[Dict], scene_number: int) -> Optional[Dict]:
    """Find matching GEN1 scene by scene_number."""
    if not gen1_data:
        return None
    scenes = gen1_data.get("scenes", [])
    for s in scenes:
        if isinstance(s, dict) and s.get("scene_number") == scene_number:
            return s
    return None


def _tier_from_sp(sp: int, is_money_shot: bool) -> str:
    """Determine visual_tier from sensory_pressure + money_shot flag."""
    if is_money_shot or sp == 10:
        return "TIER_1_MONEY_SHOT"
    for tier, (lo, hi) in TIER_SP_MAP.items():
        if lo <= sp <= hi:
            return tier
    return "TIER_3_BALANCED"


# ---------------------------------------------------------------------------
# MAIN AUTOCORRECT FUNCTION
# ---------------------------------------------------------------------------

def autocorrect_gen2(
    data: Dict[str, Any],
    gen1_data: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], List[AutoFixWarning]]:
    """
    Apply all deterministic auto-corrections to GEN2 output.

    Args:
        data: Raw GEN2 JSON output as dict.
        gen1_data: GEN1 output dict for cross-referencing (optional but recommended).

    Returns:
        Tuple of (corrected_data, list_of_warnings).
        corrected_data is a deep copy — original is not mutated.
    """
    d = copy.deepcopy(data)
    w: List[AutoFixWarning] = []
    scenes = d.get("scenes", [])

    # --- Order matters: tier first, then inject keywords, then trim ---
    _fix_tier_assignment(d, scenes, gen1_data, w)
    _fix_body_trigger_keywords(d, scenes, gen1_data, w)  # inject before trim
    _fix_word_counts(d, scenes, w)                        # trim respects injected keywords
    _fix_inheritance_structure(d, scenes, w)
    _fix_motion_intensity_floor(d, scenes, gen1_data, w)
    _fix_first_frame_composition(d, scenes, gen1_data, w)
    _fix_negative_prompt_tier_additions(d, scenes, w)
    _fix_visual_summary_defaults(d, scenes, w)

    return d, w


# ---------------------------------------------------------------------------
# INDIVIDUAL FIX FUNCTIONS
# ---------------------------------------------------------------------------

def _fix_tier_assignment(d: dict, scenes: list, gen1_data: Optional[dict], w: list) -> None:
    """Assign/correct visual_tier based on GEN1 sensory_pressure + money_shot.

    Tier assignment is deterministic:
    - money_shot.is_money_shot=true OR SP=10 → TIER_1_MONEY_SHOT
    - SP 8-9 → TIER_2_HIGH_APPETITE
    - SP 5-7 → TIER_3_BALANCED
    - SP 1-4 → TIER_4_ARCHITECTURE
    """
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        sn = scene.get("scene_number", i + 1)

        # Get SP and money_shot from GEN1 data (more reliable than GEN2's copy)
        gen1_scene = _get_gen1_scene(gen1_data, sn)
        if gen1_scene:
            sp = gen1_scene.get("sensory_pressure")
            ms = gen1_scene.get("money_shot")
        else:
            sp = None
            ms = None

        if sp is None:
            continue

        try:
            sp_val = int(sp)
        except (ValueError, TypeError):
            continue

        is_money = isinstance(ms, dict) and ms.get("is_money_shot")
        expected_tier = _tier_from_sp(sp_val, is_money)
        current_tier = scene.get("visual_tier", "")

        if current_tier != expected_tier:
            scene["visual_tier"] = expected_tier
            w.append(AutoFixWarning(
                f"scenes[{i}].visual_tier",
                f"Tier fix: '{current_tier}' → '{expected_tier}' (SP={sp_val}, money={is_money})",
            ))


def _fix_word_counts(d: dict, scenes: list, w: list) -> None:
    """Trim image_prompt if word count exceeds tier maximum.

    Trims by sentences (not mid-word) to preserve prompt coherence.
    """
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        tier = scene.get("visual_tier", "")
        if tier not in TIER_WORD_RANGES:
            continue

        min_words, max_words = TIER_WORD_RANGES[tier]
        prompt = scene.get("image_prompt", "")
        if not isinstance(prompt, str):
            continue

        words = prompt.split()
        if len(words) <= max_words:
            continue

        # Trim by sentences to stay under max_words
        sentences = re.split(r'(?<=[.!?])\s+', prompt)
        kept = []
        count = 0
        for sent in sentences:
            sent_words = len(sent.split())
            if count + sent_words > max_words and kept:
                break
            kept.append(sent)
            count += sent_words

        trimmed = " ".join(kept)
        if not trimmed.rstrip().endswith((".", "!", "?")):
            trimmed = trimmed.rstrip(",;:—–- ") + "."

        # Don't trim below minimum (especially for TIER_1 money shot at 130 words)
        if len(trimmed.split()) < min_words:
            continue

        scene["image_prompt"] = trimmed
        w.append(AutoFixWarning(
            f"scenes[{i}].image_prompt",
            f"Word count trim: {len(words)} → {len(trimmed.split())} (tier {tier} max={max_words})",
        ))


def _fix_inheritance_structure(d: dict, scenes: list, w: list) -> None:
    """Ensure REQUIRES_REF and LOOP_CLOSE scenes have inheritance data."""
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        ref_type = scene.get("reference_type", "")
        if ref_type not in ("REQUIRES_REF", "LOOP_CLOSE"):
            continue
        if scene.get("inheritance"):
            continue  # already present

        parent = 1  # default parent
        if ref_type == "LOOP_CLOSE":
            inherited = ["architectural_style", "food_material", "lighting_preset", "color_palette", "foreground_element"]
            modified = ["camera_angle", "motion_direction"]
        else:
            inherited = ["architectural_style", "food_material", "lighting_preset", "color_palette"]
            modified = ["camera_angle", "subject_focus"]

        scene["inheritance"] = {
            "parent_scene": parent,
            "inherited_elements": inherited,
            "modified_elements": modified,
        }
        w.append(AutoFixWarning(
            f"scenes[{i}].inheritance",
            f"Auto-filled missing inheritance for {ref_type} (parent=Scene {parent})",
        ))


def _fix_body_trigger_keywords(d: dict, scenes: list, gen1_data: Optional[dict], w: list) -> None:
    """Inject body_trigger sensory keywords into Scene 1 image_prompt.

    GEN1 hook.body_trigger specifies the primary sensory channel (MOUTH, SKIN, etc.).
    Scene 1 image_prompt should contain matching visual keywords.
    """
    if not gen1_data or not scenes:
        return
    hook = gen1_data.get("hook")
    if not isinstance(hook, dict):
        return
    trigger = hook.get("body_trigger", "")
    if not isinstance(trigger, str) or trigger.strip().upper() not in BODY_TRIGGER_KEYWORDS:
        return

    keywords = BODY_TRIGGER_KEYWORDS[trigger.strip().upper()]
    scene1 = scenes[0]
    if not isinstance(scene1, dict):
        return

    prompt = scene1.get("image_prompt", "")
    if not isinstance(prompt, str):
        return

    prompt_lower = prompt.lower()
    missing = [kw for kw in keywords if kw.lower() not in prompt_lower]

    if len(missing) < 2:
        return  # Already has enough keywords

    # Inject up to 2 missing keywords before the last sentence
    inject = ", ".join(missing[:2])
    sentences = re.split(r'(?<=[.!?])\s+', prompt.rstrip())
    if len(sentences) > 1:
        sentences[-1] = f"{inject}, {sentences[-1]}"
        scene1["image_prompt"] = " ".join(sentences)
    else:
        scene1["image_prompt"] = f"{prompt.rstrip('.')}. {inject}."

    w.append(AutoFixWarning(
        "scenes[0].image_prompt",
        f"Injected body_trigger '{trigger}' keywords: {inject}",
    ))


def _fix_motion_intensity_floor(d: dict, scenes: list, gen1_data: Optional[dict], w: list) -> None:
    """Clamp motion_intensity to energy_level floor.

    EXPLOSIVE >= 7, HIGH >= 5, MEDIUM >= 3, LOW >= 2.
    """
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue

        sn = scene.get("scene_number", i + 1)
        gen1_scene = _get_gen1_scene(gen1_data, sn)
        energy = gen1_scene.get("energy_level", "MEDIUM") if gen1_scene else "MEDIUM"
        if not isinstance(energy, str):
            energy = "MEDIUM"

        floor = ENERGY_MOTION_FLOOR.get(energy.upper(), 3)
        current = scene.get("motion_intensity")
        if current is None:
            continue

        try:
            current_val = int(current)
        except (ValueError, TypeError):
            continue

        if current_val < floor:
            scene["motion_intensity"] = floor
            w.append(AutoFixWarning(
                f"scenes[{i}].motion_intensity",
                f"Energy floor: {current_val} → {floor} (energy={energy})",
            ))


def _fix_first_frame_composition(d: dict, scenes: list, gen1_data: Optional[dict], w: list) -> None:
    """Fill missing Scene 1 first_frame_composition fields from GEN1 hook data.

    Merges into existing dict (preserves fields like entry_type, temperature_mood,
    body_trigger_visual that Gemini may have already populated).
    """
    if not scenes or not gen1_data:
        return
    scene1 = scenes[0]
    if not isinstance(scene1, dict):
        return
    ffc = scene1.get("first_frame_composition")
    if not isinstance(ffc, dict):
        ffc = {}

    hook = gen1_data.get("hook", {})
    if not isinstance(hook, dict):
        return

    food_id = gen1_data.get("food_identity", {})
    arch_id = gen1_data.get("architectural_identity", {})
    fg = gen1_data.get("foreground_element", {})

    color_kws = food_id.get("color_keywords", []) if isinstance(food_id, dict) else []
    color_anchor = color_kws[0] if color_kws and isinstance(color_kws[0], str) else "warm golden"

    fg_snippet = fg.get("prompt_snippet", "") if isinstance(fg, dict) else ""
    fg_line = fg_snippet.split(".")[0].strip() if fg_snippet else "atmospheric particles"

    style_desc = arch_id.get("style_description", "") if isinstance(arch_id, dict) else ""
    bg = style_desc[:80] if style_desc else "architectural environment"

    gen1_scene1 = _get_gen1_scene(gen1_data, 1)
    vc = gen1_scene1.get("visual_concept", {}) if gen1_scene1 else {}
    motion_elems = vc.get("motion_elements", []) if isinstance(vc, dict) else []
    motion_vis = motion_elems[0] if motion_elems and isinstance(motion_elems[0], str) else "subtle movement"

    # Defaults for all 11 spec fields — only fill MISSING ones
    defaults = {
        "hook_element": hook.get("type", "THE_IMPOSSIBLE"),
        "entry_type": "MACRO_ENTRY",
        "focal_point": hook.get("first_frame_visual", "food-architecture fusion"),
        "foreground": fg_line,
        "background": bg,
        "color_anchor": color_anchor,
        "temperature_mood": "warm food against cool environment",
        "body_trigger_visual": f"{hook.get('body_trigger', 'MOUTH')} emphasis",
        "safe_zone": "Subject in upper 60%",
        "motion_visible": motion_vis,
        "scroll_stop": hook.get("scroll_stop_element", "impossible food structure"),
    }

    filled = []
    for key, value in defaults.items():
        if not ffc.get(key):
            ffc[key] = value
            filled.append(key)

    if filled:
        scene1["first_frame_composition"] = ffc
        w.append(AutoFixWarning(
            "scenes[0].first_frame_composition",
            f"Filled {len(filled)} missing fields: {', '.join(filled)}",
        ))


def _fix_negative_prompt_tier_additions(d: dict, scenes: list, w: list) -> None:
    """Append tier-specific keywords to global negative_prompt."""
    gs = d.get("global_settings")
    if not isinstance(gs, dict):
        return

    neg = gs.get("negative_prompt", "")
    if not isinstance(neg, str):
        neg = ""

    # Collect unique tier additions from all scenes
    additions = set()
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        tier = scene.get("visual_tier", "")
        tier_adds = TIER_NEGATIVE_ADDITIONS.get(tier, [])
        for kw in tier_adds:
            if kw.lower() not in neg.lower():
                additions.add(kw)

    if not additions:
        return

    sorted_adds = ", ".join(sorted(additions))
    if neg.strip():
        gs["negative_prompt"] = f"{neg.rstrip(', ')}, {sorted_adds}"
    else:
        gs["negative_prompt"] = sorted_adds
    w.append(AutoFixWarning(
        "global_settings.negative_prompt",
        f"Tier-specific additions: {', '.join(sorted(additions))}",
    ))


def _fix_visual_summary_defaults(d: dict, scenes: list, w: list) -> None:
    """Fill missing visual_summary fields with computed defaults."""
    vs = d.get("visual_summary")
    if not isinstance(vs, dict):
        d["visual_summary"] = {}
        vs = d["visual_summary"]

    changed = False

    # total_scenes — fix if missing, zero, or mismatched
    if vs.get("total_scenes") != len(scenes):
        vs["total_scenes"] = len(scenes)
        changed = True

    # reference_breakdown
    if not vs.get("reference_breakdown"):
        breakdown: Dict[str, int] = {}
        for scene in scenes:
            if isinstance(scene, dict):
                rt = scene.get("reference_type", "UNKNOWN")
                breakdown[rt] = breakdown.get(rt, 0) + 1
        vs["reference_breakdown"] = breakdown
        changed = True

    # loop_verified
    if vs.get("loop_verified") is None:
        has_loop = any(
            isinstance(s, dict) and s.get("reference_type") == "LOOP_CLOSE"
            for s in scenes
        )
        vs["loop_verified"] = has_loop
        changed = True

    if changed:
        w.append(AutoFixWarning(
            "visual_summary",
            "Auto-filled missing defaults (total_scenes, reference_breakdown, loop_verified)",
        ))


# ---------------------------------------------------------------------------
# EXPORT
# ---------------------------------------------------------------------------

__all__ = [
    "autocorrect_gen2",
    "VALID_TIERS",
    "TIER_WORD_RANGES",
    "BODY_TRIGGER_KEYWORDS",
    "ENERGY_MOTION_FLOOR",
]
