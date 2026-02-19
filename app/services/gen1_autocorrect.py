"""
GEN1 Auto-Corrector v2.0

Deterministic auto-fix layer for GEN1 (Creative Director) output.
Runs BEFORE validation to fix known Gemini 3 Pro hallucinations/confusions.

Separated from gen1_validator.py for maintainability and testability.
Each fix is a standalone method with clear pre/post conditions.

Usage:
    from app.services.gen1_autocorrect import autocorrect_gen1

    corrected_data, warnings = autocorrect_gen1(raw_gen1_json)
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from loguru import logger


# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

# MODE B (CREAMY/CHEWY/SMOOTH) money-shot voiceover pattern:
# "[long pause] [whispers] <word>."
_MODE_B_PATTERN = re.compile(
    r'^\s*\[long\s+pause\]\s*\[whispers\]\s*\S+\.?\s*$', re.IGNORECASE
)

# Soft texture keywords — determines MODE B for money shot
_SOFT_TEXTURES: set = {
    "creamy", "chewy", "smooth", "gooey", "silky", "velvety", "soft", "melty",
}

# ElevenLabs speech tags (presence means NOT silence)
_SPEECH_TAGS: set = {
    "[whispers]", "[calm]", "[warm]", "[gentle]",
    "[excited]", "[sad]", "[angry]", "[happily]", "[shouts]",
}

# Narrative bridge starters — banned first words for VO lines
NARRATIVE_BRIDGE_STARTERS: set = {
    "but", "and", "yet", "so", "then", "deeper", "further",
    "inside", "below", "above", "beyond",
}

# Egg-hunt patterns for pinned comment
_EGG_HUNT_PATTERNS: list = [
    "spot", "find", "hidden", "spotted", "hiding", "secret",
]
_EXPANDED_EGG_PATTERNS: list = _EGG_HUNT_PATTERNS + [
    "passenger", "who", "did you", "anyone", "notice",
]

# Architecture elements whitelist (for warning_line)
VALID_ARCHITECTURE_ELEMENTS: set = {
    "walls", "floor", "ceiling", "stairs", "door", "roof", "window",
    "pool", "fence", "chimney", "columns", "railing", "pipes", "beams", "tiles",
    "foundation", "ledge", "fountain", "bridge", "arch", "balcony", "tower",
    "dome", "porch", "gutter", "bars",
}

# Food actions whitelist (for warning_line)
VALID_FOOD_ACTIONS: set = {
    "lick", "bite", "eat", "drink", "touch", "taste", "chew", "nibble",
    "swallow", "smell", "scrape", "peel", "squeeze", "sip", "crunch",
    "snap", "break", "crack", "slice", "dip",
}

# Temperature words for THERMAL first word auto-fix
TEMPERATURE_WORDS: set = {
    "warm", "hot", "cold", "cool", "steaming", "frozen",
    "still warm", "still hot", "still cold",
}

# Reversal-safe motion elements for Scene N
REVERSAL_SAFE_MOTIONS: set = {
    "shimmer", "glow", "pulse", "sparkle", "gleam", "ripple",
    "shine", "flicker", "throb", "radiate", "hum", "vibrate",
    "glisten", "twinkle", "breathe",
}

# Banned Scene N motion words
_BANNED_LOOP_MOTIONS: set = {
    "drip", "dripping", "fall", "falling", "pour", "pouring",
    "crack", "cracking", "smoke", "smoking", "steam", "steaming",
    "fire", "flame", "walk", "walking", "move", "moving",
    "flow", "flowing", "rise", "rising", "debris", "leaf", "leaves",
    "snow", "rain", "waterfall",
}

# Maps for hook.type: Gemini sometimes uses sonic_hook types here
_HOOK_TYPE_FIXES: dict = {
    "THE_SILENCE": "THE_WHISPER",
    "THE_BOOM": "THE_SCALE_SHOCK",
    "THE_SIZZLE": "THE_SENSORY_ATTACK",
    "THE_CRUNCH": "THE_SENSORY_ATTACK",
    "THE_WHOOSH": "THE_SCALE_SHOCK",
    "THE_CHIME": "THE_WHISPER",
    "THE_DROP": "THE_SCALE_SHOCK",
    "THE_GLITCH": "THE_ABSURD_LOGIC",
    "THE_DANGER": "THE_SCALE_SHOCK",
    "THE_REVEAL": "THE_IMPOSSIBLE",
    "THE_MYSTERY": "THE_ABSURD_LOGIC",
}

# Maps for narrative_purpose: Gemini uses phase labels from duration_config
_PURPOSE_FIXES: dict = {
    "EXPLORATION": "FEATURE",
    "ESCALATION": "DYNAMIC_ACTION",
    "CLIMAX": "FEATURE_HIGHLIGHT",
    "HOOK": "ESTABLISHING",
    "REVEAL": "FEATURE_HIGHLIGHT",
    "TRANSITION": "CONTEXTUAL_ENVIRONMENT",
}

# Texture group → default temperature word mapping
_TEXTURE_TO_TEMP: dict = {
    "crispy": "Still warm.",
    "crunchy": "Still warm.",
    "brittle": "Cool.",
    "creamy": "Cold.",
    "chewy": "Warm.",
    "smooth": "Cool.",
    "gooey": "Warm.",
    "silky": "Cool.",
    "crunchy-wet": "Cool.",
}


# ---------------------------------------------------------------------------
# WARNING DATACLASS (lightweight — full ValidationError lives in validator)
# ---------------------------------------------------------------------------

class AutoFixWarning:
    """Lightweight warning from auto-correction."""
    __slots__ = ("field", "message")

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message

    def __repr__(self) -> str:
        return f"AutoFix[{self.field}]: {self.message}"


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _get_food_name(data: dict) -> Optional[str]:
    """Extract short food name from data. Strips parenthetical qualifiers."""
    food_id = data.get("food_identity", {})
    if isinstance(food_id, dict):
        primary = food_id.get("primary_food", "")
        if isinstance(primary, str) and primary.strip():
            clean = re.sub(r'\s*\([^)]*\)', '', primary).strip()
            return clean if clean else primary.split()[0]
    metadata = data.get("metadata", {})
    concept = metadata.get("concept", {}) if isinstance(metadata, dict) else {}
    fm = concept.get("food_material", "") if isinstance(concept, dict) else ""
    if fm:
        clean = re.sub(r'\s*\([^)]*\)', '', fm).strip()
        return clean if clean else fm.split()[0] if fm else None
    return None


def _is_soft_texture(data: dict) -> bool:
    """Check if food has soft/creamy texture (MODE B for money shot)."""
    food_id = data.get("food_identity", {})
    tex_kws = food_id.get("texture_keywords", []) if isinstance(food_id, dict) else []
    return any(
        kw.lower().strip() in _SOFT_TEXTURES
        for kw in tex_kws if isinstance(kw, str)
    )


def _has_real_easter_egg(data: dict) -> bool:
    """Check if a real easter egg exists (not null/empty)."""
    engagement = data.get("engagement")
    if isinstance(engagement, dict):
        egg = engagement.get("easter_egg")
        if isinstance(egg, dict):
            obj = egg.get("object", "")
            try:
                scene_num = int(egg.get("scene_number", 0))
            except (ValueError, TypeError):
                scene_num = 0
            is_audio = egg.get("format") == "AUDIO_ONLY"
            if is_audio or (obj and obj != "none" and scene_num > 0):
                return True
    # Check top-level easter_egg
    top_egg = data.get("easter_egg")
    if isinstance(top_egg, dict):
        obj = top_egg.get("object", "")
        try:
            sn = int(top_egg.get("scene_number", 0))
        except (ValueError, TypeError):
            sn = 0
        is_audio = top_egg.get("format") == "AUDIO_ONLY"
        if is_audio or (obj and obj != "none" and sn > 0):
            return True
    return False


def _get_subject(data: dict) -> str:
    """Get concept subject for fallback text generation."""
    meta = data.get("metadata", {})
    concept = meta.get("concept", {}) if isinstance(meta, dict) else {}
    return concept.get("subject", "this") if isinstance(concept, dict) else "this"


def _strip_tags(text: str) -> str:
    """Remove all ElevenLabs-style [tags] from text."""
    return re.sub(r'\[[\w\s]+\]\s*', '', text).strip()


def _closest_match(word: str, valid_set: set, default: str) -> str:
    """Find closest match using simple substring/prefix matching."""
    import difflib
    matches = difflib.get_close_matches(word, valid_set, n=1, cutoff=0.5)
    return matches[0] if matches else default


def _get_texture_group(data: dict) -> str:
    """Determine primary texture group from food_identity."""
    food_id = data.get("food_identity", {})
    tex_kws = food_id.get("texture_keywords", []) if isinstance(food_id, dict) else []
    for kw in tex_kws:
        if isinstance(kw, str):
            kw_lower = kw.lower().strip()
            if kw_lower in _TEXTURE_TO_TEMP:
                return kw_lower
    return "crispy"  # safe default


# ---------------------------------------------------------------------------
# MAIN AUTOCORRECT FUNCTION
# ---------------------------------------------------------------------------

def autocorrect_gen1(data: Dict[str, Any]) -> Tuple[Dict[str, Any], List[AutoFixWarning]]:
    """
    Apply all deterministic auto-corrections to GEN1 output.

    Args:
        data: Raw GEN1 JSON output as dict.

    Returns:
        Tuple of (corrected_data, list_of_warnings).
        corrected_data is a deep copy — original is not mutated.
    """
    d = copy.deepcopy(data)
    w: List[AutoFixWarning] = []
    scenes = d.get("scenes", [])

    # --- Order matters: structural fixes first, then content fixes ---

    _fix_metadata_types(d, w)
    _fix_hook_type(d, w)
    _fix_narrative_purposes(d, w)
    _fix_easter_egg_and_pinned(d, w)
    _fix_food_visual_ratio(d, scenes, w)
    _fix_money_shot_vo(d, scenes, w)
    _fix_asmr_whisper_anchor(d, scenes, w)
    _fix_narrative_bridges(scenes, w)
    _fix_silence_speech_contradiction(d, scenes, w)
    _fix_on_screen_text(d, scenes, w)
    _fix_scene_n_minus_1_aerial(scenes, w)
    _fix_warning_line_delivery(d, scenes, w)
    _fix_direction_tags(scenes, w)
    _fix_narrator_script_tags(scenes, w)
    _fix_warning_line_element_sync(d, scenes, w)
    _fix_thermal_first_word(d, scenes, w)
    _fix_narrator_vo_sync(scenes, w)
    _fix_scene_durations(scenes, w)
    _fix_scene_n_constraints(d, scenes, w)
    _fix_scene_n_minus_1_vo(d, scenes, w)
    _fix_vo_trigger_injection(d, scenes, w)
    _fix_description_line1(d, w)
    _fix_full_script_rebuild(d, scenes, w)  # ALWAYS last — rebuilds from segments

    return d, w


# ---------------------------------------------------------------------------
# INDIVIDUAL FIX FUNCTIONS
# ---------------------------------------------------------------------------

def _fix_metadata_types(d: dict, w: list) -> None:
    """Fix metadata type issues (scene_count as string, etc.)."""
    meta = d.get("metadata")
    if not isinstance(meta, dict):
        return
    sc = meta.get("scene_count")
    if isinstance(sc, str):
        try:
            meta["scene_count"] = int(sc)
            w.append(AutoFixWarning("metadata.scene_count", f"Auto-coerced string '{sc}' → int {int(sc)}"))
        except ValueError:
            pass


def _fix_hook_type(d: dict, w: list) -> None:
    """Fix hook.type confusion with sonic_hook.type."""
    hook = d.get("hook")
    if not isinstance(hook, dict):
        return
    hook_type = hook.get("type", "")
    if hook_type in _HOOK_TYPE_FIXES:
        fixed = _HOOK_TYPE_FIXES[hook_type]
        hook["type"] = fixed
        w.append(AutoFixWarning(
            "hook.type",
            f"Auto-corrected '{hook_type}' → '{fixed}' (was sonic_hook type)",
        ))


def _fix_narrative_purposes(d: dict, w: list) -> None:
    """Fix narrative_purpose confusion with phase labels."""
    scenes = d.get("scenes", [])
    total = len(scenes)
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        purpose = scene.get("narrative_purpose", "")
        if purpose in _PURPOSE_FIXES:
            scene_num = i + 1
            if scene_num == 1:
                fixed = "ESTABLISHING"
            elif scene_num == total:
                fixed = "LOOP_CLOSE"
            elif scene_num == total - 1:
                fixed = "AERIAL"
            else:
                fixed = _PURPOSE_FIXES[purpose]
            scene["narrative_purpose"] = fixed
            w.append(AutoFixWarning(
                f"scenes[{i}].narrative_purpose",
                f"Auto-corrected '{purpose}' → '{fixed}' (was phase label)",
            ))


def _fix_easter_egg_and_pinned(d: dict, w: list) -> None:
    """Fix easter egg comment_bait and pinned comment consistency."""
    engagement = d.get("engagement")
    has_real_egg = False

    if isinstance(engagement, dict):
        egg = engagement.get("easter_egg")
        if isinstance(egg, dict):
            obj = egg.get("object", "")
            try:
                scene_num = int(egg.get("scene_number", 0))
            except (ValueError, TypeError):
                scene_num = 0
            is_audio = egg.get("format") == "AUDIO_ONLY"
            has_real_egg = is_audio or (obj and obj != "none" and scene_num > 0)

            if not egg.get("comment_bait"):
                if has_real_egg:
                    egg["comment_bait"] = f"Did anyone spot the {obj}? 👀"
                else:
                    egg["comment_bait"] = "Would you live here? 🏠"
                w.append(AutoFixWarning("engagement.easter_egg.comment_bait", "Auto-filled empty comment_bait"))

    if not has_real_egg:
        has_real_egg = _has_real_easter_egg(d)

    # Fix pinned_comment egg-hunt references when no real egg exists
    youtube = d.get("youtube", {})
    if isinstance(youtube, dict) and not has_real_egg:
        pinned = youtube.get("pinned_comment", "")
        if isinstance(pinned, str) and pinned.strip():
            if any(p in pinned.lower() for p in _EXPANDED_EGG_PATTERNS):
                subject = _get_subject(d)
                youtube["pinned_comment"] = f"Would you visit a {subject}? 🏠"
                w.append(AutoFixWarning(
                    "youtube.pinned_comment",
                    f"Auto-replaced egg-hunt reference (no real easter egg): '{pinned[:60]}'",
                ))


def _fix_food_visual_ratio(d: dict, scenes: list, w: list) -> None:
    """Fix food_visual_ratio: ban ARCHITECTURE_DOMINANT, infer missing."""
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        fvr = scene.get("food_visual_ratio", "")
        purpose = scene.get("narrative_purpose", "")
        ms = scene.get("money_shot")
        is_money = isinstance(ms, dict) and ms.get("is_money_shot")

        if fvr and isinstance(fvr, str) and fvr.strip().upper() == "ARCHITECTURE_DOMINANT":
            if i == 0 or purpose == "STRUCTURAL_DETAIL" or is_money:
                scene["food_visual_ratio"] = "FOOD_DOMINANT"
            else:
                scene["food_visual_ratio"] = "BALANCED"
            w.append(AutoFixWarning(
                f"scenes[{i}].food_visual_ratio",
                f"Auto-corrected 'ARCHITECTURE_DOMINANT' → '{scene['food_visual_ratio']}'",
            ))
        elif not fvr:
            if i == 0 or purpose == "STRUCTURAL_DETAIL" or is_money:
                scene["food_visual_ratio"] = "FOOD_DOMINANT"
            else:
                scene["food_visual_ratio"] = "BALANCED"
            w.append(AutoFixWarning(
                f"scenes[{i}].food_visual_ratio",
                f"Auto-filled missing → '{scene['food_visual_ratio']}'",
            ))


def _fix_money_shot_vo(d: dict, scenes: list, w: list) -> None:
    """Enforce money shot VO rules: MODE A = [silence], MODE B = [long pause] [whispers] <word>."""
    soft = _is_soft_texture(d)
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        ms = scene.get("money_shot")
        if not (isinstance(ms, dict) and ms.get("is_money_shot")):
            continue

        vo_seg = scene.get("voiceover_segment", "")
        if vo_seg and vo_seg.strip() not in ("", "[silence]"):
            if soft and _MODE_B_PATTERN.match(vo_seg.strip()):
                pass  # MODE B valid
            else:
                scene["voiceover_segment"] = "[silence]"
                scene["narrator_script"] = ""
                w.append(AutoFixWarning(
                    f"scenes[{i}].voiceover_segment",
                    f"Auto-forced '[silence]' on money_shot (was: '{vo_seg[:60]}')",
                ))

        narrator = scene.get("narrator_script", "")
        if narrator and narrator.strip():
            if soft and len(narrator.strip().split()) <= 1:
                pass  # MODE B allows 1-word
            else:
                scene["narrator_script"] = ""
                w.append(AutoFixWarning(
                    f"scenes[{i}].narrator_script",
                    "Auto-cleared narrator_script on money_shot scene",
                ))


def _fix_asmr_whisper_anchor(d: dict, scenes: list, w: list) -> None:
    """Ensure pure ASMR scenes have whisper anchor (H3 cold-start fix)."""
    asmr_scene_nums = d.get("asmr_scenes", [])
    if not isinstance(asmr_scene_nums, list):
        return
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        scene_num = scene.get("scene_number", i + 1)
        if scene_num not in asmr_scene_nums:
            continue
        ms = scene.get("money_shot")
        if isinstance(ms, dict) and ms.get("is_money_shot"):
            continue  # money_shot rules override ASMR
        vo_seg = scene.get("voiceover_segment", "")
        narrator = scene.get("narrator_script", "")
        vo_empty = not vo_seg or vo_seg.strip() in ("", "[silence]")
        narrator_empty = not narrator or not narrator.strip()
        if vo_empty and narrator_empty:
            scene["voiceover_segment"] = "[whispers] Warm. [long pause]"
            scene["narrator_script"] = "Warm."
            w.append(AutoFixWarning(
                f"scenes[{i}].voiceover_segment",
                f"Auto-added whisper anchor to ASMR scene {scene_num}",
            ))


def _fix_narrative_bridges(scenes: list, w: list) -> None:
    """Strip narrative bridge words (but/and/yet/so/then...) from VO starts."""
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        for field_key in ("voiceover_segment", "narrator_script"):
            text = scene.get(field_key, "")
            if not text or not isinstance(text, str):
                continue
            lines = text.split("\n")
            fixed_lines = []
            changed = False
            for line in lines:
                stripped = line.strip()
                clean_line = re.sub(r'\[[\w\s]+\]', '', stripped).strip()
                if clean_line:
                    first_word = clean_line.split()[0].rstrip(".,!?;:").lower()
                    if first_word in NARRATIVE_BRIDGE_STARTERS:
                        bridge_pattern = re.compile(
                            r'(\[[\w\s]+\]\s*)*' + re.escape(clean_line.split()[0]) + r'\s*',
                            re.IGNORECASE,
                        )
                        fixed_line = bridge_pattern.sub(
                            lambda m: m.group(1) or '' if m.group(1) else '',
                            stripped, count=1,
                        ).strip()
                        if fixed_line:
                            tag_prefix = re.match(r'((?:\[[\w\s]+\]\s*)*)', fixed_line)
                            prefix = tag_prefix.group(1) if tag_prefix else ""
                            rest = fixed_line[len(prefix):]
                            if rest:
                                rest = rest[0].upper() + rest[1:]
                            fixed_line = prefix + rest
                        w.append(AutoFixWarning(
                            f"scenes[{i}].{field_key}",
                            f"Auto-stripped bridge '{first_word}': '{stripped[:50]}'",
                        ))
                        changed = True
                        fixed_lines.append(fixed_line if fixed_line else line)
                        continue
                fixed_lines.append(line)
            if changed:
                scene[field_key] = "\n".join(fixed_lines).strip()

        # Also strip from micro_open_loop.setup_line
        mol = scene.get("micro_open_loop")
        if isinstance(mol, dict):
            setup = mol.get("setup_line", "")
            if isinstance(setup, str) and setup.strip():
                clean_setup = re.sub(r'\[[\w\s]+\]', '', setup).strip()
                if clean_setup:
                    first_w = clean_setup.split()[0].rstrip(".,!?;:").lower()
                    if first_w in NARRATIVE_BRIDGE_STARTERS:
                        fixed_setup = re.sub(
                            r'(?i)^(\[[\w\s]+\]\s*)?' + re.escape(first_w) + r'\s*',
                            lambda m: m.group(1) or '',
                            setup, count=1,
                        ).strip()
                        mol["setup_line"] = fixed_setup
                        w.append(AutoFixWarning(
                            f"scenes[{i}].micro_open_loop.setup_line",
                            f"Auto-stripped bridge: '{setup[:60]}'",
                        ))


def _fix_silence_speech_contradiction(d: dict, scenes: list, w: list) -> None:
    """Fix [silence] + speech tag contradiction in same VO segment."""
    soft = _is_soft_texture(d)
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        vo_seg = scene.get("voiceover_segment", "")
        if not isinstance(vo_seg, str) or "[silence]" not in vo_seg:
            continue
        has_speech = any(tag in vo_seg for tag in _SPEECH_TAGS)
        if not has_speech:
            continue
        ms = scene.get("money_shot")
        is_money = isinstance(ms, dict) and ms.get("is_money_shot")
        if is_money:
            if soft and _MODE_B_PATTERN.match(vo_seg.replace("[silence]", "").strip()):
                fixed = vo_seg.replace("[silence]", "").strip()
                scene["voiceover_segment"] = fixed
                w.append(AutoFixWarning(f"scenes[{i}].voiceover_segment",
                    f"Auto-stripped '[silence]' from MODE B money_shot"))
            else:
                scene["voiceover_segment"] = "[silence]"
                w.append(AutoFixWarning(f"scenes[{i}].voiceover_segment",
                    f"Auto-forced '[silence]' (money_shot had mixed tags)"))
        else:
            fixed = vo_seg.replace("[silence]", "").strip()
            if fixed:
                scene["voiceover_segment"] = fixed
                w.append(AutoFixWarning(f"scenes[{i}].voiceover_segment",
                    f"Auto-stripped '[silence]' from mixed-tag VO"))


def _fix_on_screen_text(d: dict, scenes: list, w: list) -> None:
    """Clean up on_screen_text: truncate to 6 words, fix parentheticals, prepend food name to Scene 1."""
    food_name = _get_food_name(d)

    # Prepend food name to Scene 1 OSD
    if food_name and scenes:
        scene1 = scenes[0] if isinstance(scenes[0], dict) else {}
        on_screen = scene1.get("on_screen_text", "")
        if on_screen and food_name.lower() not in on_screen.lower():
            scene1["on_screen_text"] = f"{food_name} — {on_screen}"
            w.append(AutoFixWarning("scenes[0].on_screen_text",
                f"Auto-prepended food name '{food_name}'"))

    food_name_val = food_name or ""
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        on_screen = scene.get("on_screen_text", "")
        if not isinstance(on_screen, str) or not on_screen.strip():
            continue
        needs_fix = False
        cleaned = on_screen.strip()
        if "(" in cleaned and ")" not in cleaned:
            cleaned = re.sub(r'\s*\(.*$', '', cleaned).strip()
            needs_fix = True
        if ")" in cleaned and "(" not in cleaned:
            cleaned = cleaned.replace(")", "").strip()
            needs_fix = True
        cleaned = cleaned.rstrip(",").strip()
        if cleaned != on_screen.strip():
            needs_fix = True
        words = cleaned.split()
        if len(words) > 6 or needs_fix:
            if i == 0 and food_name_val:
                meta = d.get("metadata", {})
                concept = meta.get("concept", {}) if isinstance(meta, dict) else {}
                subject = concept.get("subject", "") if isinstance(concept, dict) else ""
                concept_word = subject.split()[-1].upper() if subject else ""
                food_short = food_name_val.split()[-1].upper()
                truncated = f"{food_short} {concept_word}".strip() if concept_word else food_short
            else:
                kept = [wd for wd in words if wd.strip("(,)")][:4]
                if kept:
                    kept[0] = kept[0].upper()
                truncated = " ".join(kept)
            if truncated != on_screen.strip():
                scene["on_screen_text"] = truncated
                w.append(AutoFixWarning(f"scenes[{i}].on_screen_text",
                    f"Auto-cleaned: '{on_screen.strip()[:40]}' → '{truncated}'"))


def _fix_scene_n_minus_1_aerial(scenes: list, w: list) -> None:
    """Force Scene N-1 narrative_purpose to AERIAL."""
    if len(scenes) < 3:
        return
    pen_idx = len(scenes) - 2
    pen = scenes[pen_idx]
    if not isinstance(pen, dict):
        return
    p = pen.get("narrative_purpose", "")
    if p not in ("AERIAL", "AERIAL_WOW", "AERIAL_REVEAL"):
        pen["narrative_purpose"] = "AERIAL"
        w.append(AutoFixWarning(
            f"scenes[{pen_idx}].narrative_purpose",
            f"Auto-corrected '{p}' → 'AERIAL' (Scene N-1 must be AERIAL)",
        ))


def _fix_warning_line_delivery(d: dict, scenes: list, w: list) -> None:
    """Move warning_line from LOOP_CLOSE to AERIAL if needed."""
    wl_raw = d.get("warning_line", "")
    if not isinstance(wl_raw, str) or not wl_raw.strip() or len(scenes) < 3:
        return
    wl_plain = _strip_tags(wl_raw).rstrip(".")
    aerial_idx = len(scenes) - 2
    loop_idx = len(scenes) - 1
    aerial = scenes[aerial_idx] if isinstance(scenes[aerial_idx], dict) else {}
    loop = scenes[loop_idx] if isinstance(scenes[loop_idx], dict) else {}
    aerial_vo = aerial.get("voiceover_segment", "") or ""
    loop_vo = loop.get("voiceover_segment", "") or ""
    loop_plain = _strip_tags(loop_vo).rstrip(".")
    aerial_empty = not aerial_vo.strip() or aerial_vo.strip() == "[silence]"
    loop_has_wl = wl_plain.lower() in loop_plain.lower() if wl_plain else False

    if aerial_empty and loop_has_wl:
        aerial["voiceover_segment"] = loop_vo
        aerial["narrator_script"] = loop.get("narrator_script", "")
        loop["voiceover_segment"] = "[silence]"
        loop["narrator_script"] = ""
        w.append(AutoFixWarning(
            f"scenes[{aerial_idx}].voiceover_segment",
            f"Auto-moved warning_line from LOOP_CLOSE to AERIAL",
        ))


def _fix_direction_tags(scenes: list, w: list) -> None:
    """Prepend [whispers] if VO segment is missing direction tag."""
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        vo_seg = scene.get("voiceover_segment", "")
        if not isinstance(vo_seg, str) or not vo_seg.strip():
            continue
        if vo_seg.strip() == "[silence]":
            continue
        stripped_vo = vo_seg.strip()
        if not stripped_vo.startswith("["):
            scene["voiceover_segment"] = f"[whispers] {stripped_vo}"
            w.append(AutoFixWarning(
                f"scenes[{i}].voiceover_segment",
                f"Auto-prepended [whispers]: '{stripped_vo[:50]}'",
            ))


def _fix_narrator_script_tags(scenes: list, w: list) -> None:
    """Strip ElevenLabs tags from narrator_script (must be plain text)."""
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        narrator = scene.get("narrator_script", "")
        if not isinstance(narrator, str) or not narrator.strip():
            continue
        if re.search(r'\[[\w\s]+\]', narrator):
            cleaned = re.sub(r'\[[\w\s]+\]\s*', '', narrator).strip()
            if cleaned:
                scene["narrator_script"] = cleaned
                w.append(AutoFixWarning(f"scenes[{i}].narrator_script",
                    f"Auto-stripped tags: '{narrator[:50]}' → '{cleaned[:50]}'"))
            else:
                scene["narrator_script"] = ""
                w.append(AutoFixWarning(f"scenes[{i}].narrator_script",
                    f"Auto-cleared (was tags-only: '{narrator[:50]}')"))


def _fix_warning_line_element_sync(d: dict, scenes: list, w: list) -> None:
    """Sync warning_line action/element across scene VOs.

    Also auto-fix non-standard warning_line format (e.g. "Don't bounce.").
    """
    warning_line_raw = d.get("warning_line", "")
    if not isinstance(warning_line_raw, str) or not warning_line_raw.strip():
        return

    wl_stripped = _strip_tags(warning_line_raw)

    # Parse warning_line for action + element
    wl_action, wl_element = None, None
    _formats = [
        re.compile(r"(?:don['\u2019]t)\s+(\w+)\s+the\s+(\w+)", re.IGNORECASE),
        re.compile(r"^(\w+)\s+the\s+(\w+)\.\s*I\s+dare\s+you", re.IGNORECASE),
        re.compile(r"the\s+architect\s+says:\s*nobody\s+(\w+)\s+the\s+(\w+)", re.IGNORECASE),
    ]
    for fmt_re in _formats:
        m = fmt_re.search(wl_stripped)
        if m:
            wl_action = m.group(1).lower()
            wl_element = m.group(2).lower()
            break

    # Auto-fix non-standard short format: "Don't bounce." → "Don't lick the walls."
    if not wl_action and wl_stripped.lower().startswith("don") and "the" not in wl_stripped.lower():
        short_match = re.match(r"(?:don['\u2019]t)\s+(\w+)", wl_stripped, re.IGNORECASE)
        if short_match:
            raw_action = short_match.group(1).lower()
            best_action = raw_action if raw_action in VALID_FOOD_ACTIONS else _closest_match(raw_action, VALID_FOOD_ACTIONS, "lick")
            best_element = _infer_element(d)
            new_wl = f"Don't {best_action} the {best_element}."
            d["warning_line"] = new_wl
            w.append(AutoFixWarning("warning_line", f"Auto-fixed non-standard: '{warning_line_raw}' → '{new_wl}'"))
            wl_action, wl_element = best_action, best_element

    # Auto-fix invalid action/element
    if wl_action and wl_element:
        if wl_action not in VALID_FOOD_ACTIONS:
            fixed_action = _closest_match(wl_action, VALID_FOOD_ACTIONS, "lick")
            old = d.get("warning_line", "")
            d["warning_line"] = old.replace(wl_action, fixed_action, 1)
            w.append(AutoFixWarning("warning_line", f"Auto-fixed action '{wl_action}' → '{fixed_action}'"))
            wl_action = fixed_action

        if wl_element not in VALID_ARCHITECTURE_ELEMENTS:
            fixed_elem = _closest_match(wl_element, VALID_ARCHITECTURE_ELEMENTS, "walls")
            old = d.get("warning_line", "")
            d["warning_line"] = re.sub(
                r"(?i)the\s+" + re.escape(wl_element),
                f"the {fixed_elem}", old, count=1,
            )
            w.append(AutoFixWarning("warning_line", f"Auto-fixed element '{wl_element}' → '{fixed_elem}'"))
            wl_element = fixed_elem

    # Sync element across scene VOs
    if wl_action and wl_element:
        _sync_wl_patterns = [
            (re.compile(r"(don['\u2019]t)\s+(\w+)\s+the\s+(\w+)", re.IGNORECASE), 3),
            (re.compile(r"(\w+)\s+the\s+(\w+)\.\s*I\s+dare\s+you", re.IGNORECASE), 2),
            (re.compile(r"the\s+architect\s+says:\s*nobody\s+(\w+)\s+the\s+(\w+)", re.IGNORECASE), 2),
        ]
        for i, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                continue
            for field_key in ("voiceover_segment", "narrator_script"):
                val = scene.get(field_key, "")
                if not isinstance(val, str):
                    continue
                for wl_re, elem_group in _sync_wl_patterns:
                    m = wl_re.search(val)
                    if m:
                        scene_elem = m.group(elem_group).lower()
                        if scene_elem != wl_element:
                            fixed = val[:m.start(elem_group)] + wl_element + val[m.end(elem_group):]
                            scene[field_key] = fixed
                            w.append(AutoFixWarning(
                                f"scenes[{i}].{field_key}",
                                f"Auto-synced element: '{scene_elem}' → '{wl_element}'",
                            ))
                        break


def _infer_element(d: dict) -> str:
    """Infer architecture element from data context."""
    arch = d.get("architectural_identity", {})
    if isinstance(arch, dict):
        features = arch.get("distinctive_features", [])
        if isinstance(features, list):
            for feat in features:
                if not isinstance(feat, str):
                    continue
                for elem in VALID_ARCHITECTURE_ELEMENTS:
                    if re.search(r'\b' + re.escape(elem) + r'\b', feat.lower()):
                        return elem
    food_id = d.get("food_identity", {})
    food_dna = food_id.get("food_dna", {}) if isinstance(food_id, dict) else {}
    if isinstance(food_dna, dict):
        dna_map = {
            "columns_become": "columns", "stairs_become": "stairs",
            "roof_becomes": "roof", "ceiling_becomes": "ceiling",
            "doors_become": "door", "floors_become": "floor",
            "chimney_becomes": "chimney", "windows_become": "window",
        }
        for dna_key, elem in dna_map.items():
            val = food_dna.get(dna_key, "")
            if isinstance(val, str) and val.strip() and val.strip().upper() != "N/A":
                return elem
    return "walls"


# ---------------------------------------------------------------------------
# NEW AUTO-FIXES (Phase 2 — Path B)
# ---------------------------------------------------------------------------

def _fix_thermal_first_word(d: dict, scenes: list, w: list) -> None:
    """Scene 1 narrator_script MUST start with a temperature word.

    TOP RULE: THERMAL SLOT in Scene 1 is MANDATORY.
    Template: "[temperature]. [rest]"
    """
    if not scenes or not isinstance(scenes[0], dict):
        return
    scene1 = scenes[0]
    narrator = scene1.get("narrator_script", "")
    if not isinstance(narrator, str) or not narrator.strip():
        return

    # Check if already starts with temperature word
    first_word = narrator.strip().split()[0].rstrip(".,!?;:").lower()
    two_word = " ".join(narrator.strip().split()[:2]).rstrip(".,!?;:").lower()

    if first_word in TEMPERATURE_WORDS or two_word in TEMPERATURE_WORDS:
        return  # already compliant

    # Determine temperature word from texture group
    texture = _get_texture_group(d)
    temp_sentence = _TEXTURE_TO_TEMP.get(texture, "Still warm.")

    # Prepend temperature sentence
    new_narrator = f"{temp_sentence} {narrator.strip()}"
    scene1["narrator_script"] = new_narrator

    # Also fix voiceover_segment
    vo_seg = scene1.get("voiceover_segment", "")
    if vo_seg and isinstance(vo_seg, str) and vo_seg.strip() and vo_seg.strip() != "[silence]":
        temp_word = temp_sentence.rstrip(".")
        new_vo = f"[whispers] {temp_word}. [pause] {_strip_tags(vo_seg).strip()}"
        scene1["voiceover_segment"] = new_vo

    w.append(AutoFixWarning(
        "scenes[0].narrator_script",
        f"Auto-prepended THERMAL '{temp_sentence}' (was: '{narrator[:40]}')",
    ))


def _fix_narrator_vo_sync(scenes: list, w: list) -> None:
    """TOP RULE #2: narrator_script ≠ voiceover_segment.

    narrator = plain text (zero tags).
    voiceover = same words + ≥1 tag.
    They must NEVER be identical.
    """
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        narrator = scene.get("narrator_script", "")
        vo_seg = scene.get("voiceover_segment", "")

        if not isinstance(narrator, str):
            narrator = ""
        if not isinstance(vo_seg, str):
            vo_seg = ""

        # Skip silence/empty
        if vo_seg.strip() in ("", "[silence]"):
            continue

        # Case 1: narrator empty, voiceover has content → fill narrator from VO
        if not narrator.strip() and vo_seg.strip():
            cleaned = _strip_tags(vo_seg)
            if cleaned:
                scene["narrator_script"] = cleaned
                w.append(AutoFixWarning(f"scenes[{i}].narrator_script",
                    f"Auto-filled from voiceover_segment: '{cleaned[:50]}'"))
            continue

        # Case 2: narrator has content, voiceover empty → build VO from narrator
        if narrator.strip() and not vo_seg.strip():
            scene["voiceover_segment"] = f"[whispers] {narrator.strip()}"
            w.append(AutoFixWarning(f"scenes[{i}].voiceover_segment",
                f"Auto-built from narrator_script"))
            continue

        # Case 3: both have content, check if identical
        if narrator.strip() == vo_seg.strip():
            # They are identical — narrator has no tags but VO should have tags
            scene["voiceover_segment"] = f"[whispers] {narrator.strip()}"
            w.append(AutoFixWarning(f"scenes[{i}].voiceover_segment",
                f"Auto-added [whispers] (was identical to narrator_script)"))
            continue

        # Case 4: VO has content but no tags → add default tag
        vo_stripped = vo_seg.strip()
        if not vo_stripped.startswith("["):
            # Already handled by _fix_direction_tags, but double-check
            pass


def _fix_scene_durations(scenes: list, w: list) -> None:
    """Force Scene 1 duration=2.0, Scene N duration=1.0."""
    if not scenes:
        return
    # Scene 1
    scene1 = scenes[0]
    if isinstance(scene1, dict):
        dur = scene1.get("duration_seconds")
        try:
            dur_val = float(dur) if dur is not None else None
        except (ValueError, TypeError):
            dur_val = None
        if dur_val != 2.0:
            scene1["duration_seconds"] = 2.0
            w.append(AutoFixWarning("scenes[0].duration_seconds",
                f"Auto-forced 2.0s (was: {dur})"))

    # Scene N
    if len(scenes) >= 2:
        scene_n = scenes[-1]
        if isinstance(scene_n, dict):
            dur = scene_n.get("duration_seconds")
            try:
                dur_val = float(dur) if dur is not None else None
            except (ValueError, TypeError):
                dur_val = None
            if dur_val != 1.0:
                scene_n["duration_seconds"] = 1.0
                w.append(AutoFixWarning(f"scenes[{len(scenes)-1}].duration_seconds",
                    f"Auto-forced 1.0s (was: {dur})"))


def _fix_scene_n_constraints(d: dict, scenes: list, w: list) -> None:
    """Fix Scene N (LOOP_CLOSE) constraints:
    - narrator_script = 1 sensation word
    - motion_elements = reversal-safe only
    """
    if len(scenes) < 2:
        return
    scene_n = scenes[-1]
    if not isinstance(scene_n, dict):
        return
    n_idx = len(scenes) - 1

    # narrator_script → 1 word max
    narrator = scene_n.get("narrator_script", "")
    if isinstance(narrator, str) and narrator.strip():
        words = narrator.strip().split()
        if len(words) > 1:
            # Pick first sensory word (skip bridge words, articles)
            skip = {"the", "a", "an", "and", "but", "or", "is", "are", "was", "it"}
            first_word = next((wd for wd in words if wd.lower().rstrip(".,!?") not in skip), words[0])
            clean_word = first_word.rstrip(".,!?").capitalize() + "."
            scene_n["narrator_script"] = clean_word
            w.append(AutoFixWarning(f"scenes[{n_idx}].narrator_script",
                f"Auto-trimmed to 1 word: '{narrator[:40]}' → '{clean_word}'"))

    # motion_elements → filter to reversal-safe
    vc = scene_n.get("visual_concept")
    if isinstance(vc, dict):
        motion = vc.get("motion_elements", [])
        if isinstance(motion, list) and motion:
            safe = []
            for elem in motion:
                if not isinstance(elem, str):
                    continue
                elem_lower = elem.lower()
                is_banned = any(banned in elem_lower for banned in _BANNED_LOOP_MOTIONS)
                if not is_banned:
                    safe.append(elem)
            if len(safe) < len(motion):
                # Add default safe elements if too few remain
                if len(safe) < 2:
                    defaults = ["subtle shimmer", "gentle glow"]
                    for default in defaults:
                        if default not in safe:
                            safe.append(default)
                        if len(safe) >= 2:
                            break
                vc["motion_elements"] = safe
                w.append(AutoFixWarning(f"scenes[{n_idx}].visual_concept.motion_elements",
                    f"Auto-filtered to reversal-safe ({len(motion)} → {len(safe)})"))


def _fix_scene_n_minus_1_vo(d: dict, scenes: list, w: list) -> None:
    """Scene N-1 voiceover_segment MUST be strictly "[whispers] {warning_line}"."""
    if len(scenes) < 3:
        return
    wl = d.get("warning_line", "")
    if not isinstance(wl, str) or not wl.strip():
        return

    pen_idx = len(scenes) - 2
    pen = scenes[pen_idx]
    if not isinstance(pen, dict):
        return

    wl_clean = _strip_tags(wl).strip()
    expected_vo = f"[whispers] {wl_clean}"
    current_vo = pen.get("voiceover_segment", "")

    # Check if VO already contains just the warning line
    current_clean = _strip_tags(current_vo).strip().rstrip(".")
    wl_cmp = wl_clean.rstrip(".")

    if current_clean.lower() == wl_cmp.lower():
        # Content matches, just ensure correct format
        if current_vo.strip() != expected_vo:
            pen["voiceover_segment"] = expected_vo
            pen["narrator_script"] = wl_clean
            w.append(AutoFixWarning(f"scenes[{pen_idx}].voiceover_segment",
                f"Auto-formatted to '[whispers] {{warning_line}}'"))
        return

    # Content doesn't match — check if warning line is embedded in longer text
    if wl_cmp.lower() in current_clean.lower():
        # Warning line present but with extra text — strip extras
        pen["voiceover_segment"] = expected_vo
        pen["narrator_script"] = wl_clean
        w.append(AutoFixWarning(f"scenes[{pen_idx}].voiceover_segment",
            f"Auto-stripped extras, kept warning_line only: '{current_vo[:50]}' → '{expected_vo}'"))
        return

    # Warning line completely absent — inject it
    if current_vo.strip() and current_vo.strip() != "[silence]":
        pen["voiceover_segment"] = expected_vo
        pen["narrator_script"] = wl_clean
        w.append(AutoFixWarning(f"scenes[{pen_idx}].voiceover_segment",
            f"Auto-replaced with warning_line: '{current_vo[:50]}' → '{expected_vo}'"))


def _fix_vo_trigger_injection(d: dict, scenes: list, w: list) -> None:
    """If completion_bait.vo_trigger not in its scene's voiceover_segment → append it."""
    cb = d.get("completion_bait")
    if not isinstance(cb, dict):
        return
    vo_trigger = cb.get("vo_trigger", "")
    cb_scene_num = cb.get("scene_number")
    if not vo_trigger or cb_scene_num is None:
        return

    trigger_clean = vo_trigger.rstrip(".").rstrip("…").strip()
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        if scene.get("scene_number") != cb_scene_num:
            continue
        segment = scene.get("voiceover_segment", "")
        if trigger_clean in segment:
            return  # already present

        # Append trigger to VO
        if segment and segment.strip() != "[silence]":
            scene["voiceover_segment"] = f"{segment.rstrip()} {vo_trigger}"
        else:
            scene["voiceover_segment"] = f"[whispers] {vo_trigger}"

        # Also update narrator_script
        narrator = scene.get("narrator_script", "")
        trigger_plain = _strip_tags(vo_trigger)
        if trigger_plain and trigger_plain not in narrator:
            scene["narrator_script"] = f"{narrator.rstrip()} {trigger_plain}".strip() if narrator else trigger_plain

        w.append(AutoFixWarning(
            f"scenes[{scene.get('scene_number', '?')}].voiceover_segment",
            f"Auto-injected vo_trigger: '{vo_trigger[:40]}'",
        ))
        break


def _fix_description_line1(d: dict, w: list) -> None:
    """Ensure YouTube description Line 1 contains food name + 'made of'."""
    youtube = d.get("youtube")
    if not isinstance(youtube, dict):
        return
    desc = youtube.get("description", "")
    if not isinstance(desc, str) or not desc.strip():
        return

    food_name = _get_food_name(d)
    if not food_name:
        return

    first_line = desc.strip().split("\n")[0]
    fl_lower = first_line.lower()

    if "made of" in fl_lower and food_name.lower() in fl_lower:
        return  # already compliant

    subject = _get_subject(d)
    new_line1 = f"A {subject} made of {food_name}."

    lines = desc.strip().split("\n")
    # Check if first line looks like an existing summary line
    if lines and len(lines[0].split()) < 15:
        lines[0] = new_line1
    else:
        lines.insert(0, new_line1)

    youtube["description"] = "\n".join(lines)
    w.append(AutoFixWarning("youtube.description",
        f"Auto-fixed Line 1: '{first_line[:50]}' → '{new_line1}'"))


def _fix_full_script_rebuild(d: dict, scenes: list, w: list) -> None:
    """ALWAYS rebuild full_script from per-scene voiceover_segments (must be LAST fix)."""
    vo = d.get("voiceover")
    if not isinstance(vo, dict) or not scenes:
        return
    segments = []
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        seg = scene.get("voiceover_segment", "")
        if isinstance(seg, str) and seg.strip() and seg.strip() != "[silence]":
            segments.append(seg.strip())
    if segments:
        rebuilt = " ".join(segments)
        old_script = vo.get("full_script", "")
        if old_script != rebuilt:
            vo["full_script"] = rebuilt
            w.append(AutoFixWarning("voiceover.full_script",
                "Auto-rebuilt from voiceover_segments"))


# ---------------------------------------------------------------------------
# EXPORT
# ---------------------------------------------------------------------------

__all__ = [
    "autocorrect_gen1",
    "AutoFixWarning",
    "VALID_ARCHITECTURE_ELEMENTS",
    "VALID_FOOD_ACTIONS",
    "NARRATIVE_BRIDGE_STARTERS",
    "TEMPERATURE_WORDS",
    "REVERSAL_SAFE_MOTIONS",
]
