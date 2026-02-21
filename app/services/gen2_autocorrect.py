"""
GEN2 Auto-Corrector v2.3

Deterministic auto-fix layer for GEN2 (Visual Director) output.
Runs BEFORE gen2_validator.py to fix known Gemini 3 Pro hallucinations.

Architecture mirrors gen1_autocorrect.py:
    corrected_data, warnings = autocorrect_gen2(raw_gen2_json, gen1_json)

Separated from gen2_validator.py for maintainability and testability.
Each fix is a standalone method with clear pre/post conditions.

v2.3 changelog (19→20 auto-fixes):
  - NEW: _fix_aerial_scene_no_block — remove "architecture dominant", "building exterior"
    from AERIAL scene --no blocks (these block architectural FORM that aerial must reveal)

v2.2 changelog (18→19 auto-fixes):
  - NEW: _fix_subject_motion_enforcement — inject physical state change into scenes
    with ambient-only motion (light shifting, shadows, fog). Prevents Ken Burns effect.

v2.1 changelog (17→18 auto-fixes):
  - NEW: _fix_money_shot_cold_contrast — enforce cold/dark background for TIER_1_MONEY_SHOT

v2.0 changelog (8→17 auto-fixes):
  - BUG FIX: _fix_word_counts preserves --no negative block during trim
  - NEW: _fix_motion_elements_count — pad motion_elements per energy minimum
  - NEW: _fix_loop_close_reversal_safety — replace unsafe motion words in LOOP_CLOSE
  - NEW: _fix_gigantism_applied — set gigantism_applied from tier distribution
  - NEW: _fix_safe_zone_instruction — add safe zone text to image_prompts
  - NEW: _fix_video_prompt_expansion — expand short video_prompts to tier minimum
  - NEW: _fix_video_prompt_camera_gerund — ensure camera movement gerund present
  - NEW: _fix_atmosphere_negatives — atmosphere-mode-specific negative additions
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional, Set, Tuple

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
    "TIER_1_MONEY_SHOT": (130, 160),
    "TIER_2_HIGH_APPETITE": (80, 100),
    "TIER_3_BALANCED": (70, 90),
    "TIER_4_ARCHITECTURE": (90, 120),
}

# Body trigger channel → visual keywords to inject in Scene 1
# Synced with gen2_validator.py BODY_TRIGGER_KEYWORDS — MUST match
BODY_TRIGGER_KEYWORDS: Dict[str, List[str]] = {
    "MOUTH": ["glistening", "wet surface", "moisture beading", "liquid sheen", "dripping"],
    "SKIN": ["condensation droplets", "heat shimmer", "frost crystals", "temperature visible"],
    "EARS": ["fracture lines", "cracking surface", "splitting edge", "crevices", "shattered",
             "crunchy breading detail", "crispy broken edges"],
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

# Motion element count minimums per energy level (validator: _energy_min)
ENERGY_MOTION_MIN: Dict[str, int] = {
    "EXPLOSIVE": 4,
    "HIGH": 3,
    "MEDIUM": 2,
    "LOW": 2,
}

# Reversal-unsafe → safe replacement map for LOOP_CLOSE motion_elements
# Synced with gen2_validator.py REVERSAL_UNSAFE set
REVERSAL_SAFE_REPLACEMENTS: Dict[str, str] = {
    "rising": "shimmering",
    "falling": "settling",
    "dripping": "glistening",
    "pouring": "flowing",
    "cascading": "undulating",
    "sinking": "shifting",
    "dropping": "hovering",
    "growing": "pulsing",
    "waterfall": "water shimmer",
    "fire": "warm glow",
    "flames": "warm glow",
    "walking": "standing",
    "running": "standing",
    "vehicles": "parked vehicles",
    "birds flying": "perched birds",
}

# Tier-specific negative prompt additions
TIER_NEGATIVE_ADDITIONS: Dict[str, List[str]] = {
    "TIER_1_MONEY_SHOT": ["dry surface", "matte texture", "cold lighting on food"],
    "TIER_2_HIGH_APPETITE": ["dry surface", "matte texture"],
    "TIER_4_ARCHITECTURE": ["miniature feel", "toy-like proportions"],
}

# Atmosphere-specific negative additions (synced with gen2_validator.py)
ATMOSPHERE_NEGATIVE_ADDITIONS: Dict[str, List[str]] = {
    "NOIR": ["flat lighting", "even illumination"],
    "HAUNTED": ["flat lighting", "even illumination"],
    "ETHEREAL": ["harsh shadows", "high contrast"],
}

# Video prompt word count ranges per tier (synced with gen2_validator.py)
VIDEO_WORD_RANGES: Dict[str, Tuple[int, int]] = {
    "TIER_1_MONEY_SHOT": (15, 20),
    "TIER_2_HIGH_APPETITE": (20, 30),
    "TIER_3_BALANCED": (25, 35),
    "TIER_4_ARCHITECTURE": (30, 40),
}

# Allowed camera movements (gerunds) — synced with gen2_validator.py
ALLOWED_CAMERA_MOVEMENTS: Set[str] = {
    "pushing", "pulling", "orbiting", "rising", "descending",
    "tracking", "emerging", "crane", "craning", "ascending",
}

# Safe zone phrases the validator checks for
SAFE_ZONE_PHRASES: List[str] = [
    "upper portion",
    "upper 60%",
    "upper part",
    "top portion",
]

# Warm/neutral background phrases to replace in money shot image_prompts
MONEY_SHOT_WARM_BG_PATTERNS: List[Tuple[str, str]] = [
    (r"against\s+(?:neutral\s+)?(?:bright\s+)?white\s+back(?:light|ground)", "against deep cool blue-black background"),
    (r"against\s+warm\s+\w+\s+back(?:light|ground)", "against deep cool blue-black background"),
    (r"warm\s+(?:amber|golden|orange)\s+background", "deep cool blue-black background"),
]

# Cold background indicators — if ANY present in money shot, skip fix
COLD_BG_INDICATORS: Set[str] = {
    "cool blue", "blue-black", "charcoal", "midnight", "deep blue",
    "dark background", "cold blue", "cool grey background", "cool dark",
}

# Atmospheric expansion phrases for short video_prompts
_VIDEO_EXPANSION_PHRASES: List[str] = [
    "texture detail resolving",
    "atmospheric depth building",
    "surface tension visible",
    "ambient particles drifting",
    "light interaction intensifying",
    "material qualities emerging",
    "dimensional depth increasing",
    "environmental atmosphere present",
    "volumetric haze thickening",
    "color temperature shifting",
    "micro-details sharpening",
    "foreground elements separating",
    "spatial depth layering",
    "tonal contrast building",
]

# Words to REMOVE from --no blocks of AERIAL scenes (they block architectural FORM visibility)
_AERIAL_NO_BLOCK_REMOVE: Set[str] = {
    "architecture dominant",
    "building exterior",
    "architecture",
}

# Narrative purposes that count as AERIAL
_AERIAL_PURPOSES: Set[str] = {"AERIAL", "AERIAL_WOW", "AERIAL_REVEAL"}

# Replacement negatives for AERIAL scenes: ban material realism, not form
_AERIAL_REPLACEMENT_NEGATIVES: List[str] = [
    "real stone", "real concrete", "mundane building", "suburban", "residential",
]

# ---------------------------------------------------------------------------
# SUBJECT MOTION ENFORCEMENT — physical state change detection
# ---------------------------------------------------------------------------

# Regex matching gerund/base forms of physical state change verbs.
# Video prompts with ONLY ambient motion (light shifting, shadows sweeping, fog drifting)
# cause Kling to render Ken Burns-style animated images instead of actual video.
_PHYSICAL_STATE_CHANGE_RE = re.compile(
    r'\b(?:'
    # Liquid motion
    r'drip(?:ping|s)?|flow(?:ing|s)?|pour(?:ing|s)?|cascad(?:ing|e|es)?|'
    r'splash(?:ing|es)?|spill(?:ing|s)?|pool(?:ing|s)?|seep(?:ing|s)?|'
    r'leak(?:ing|s)?|trickl(?:ing|e|es)?|drizzl(?:ing|e|es)?|'
    r'welling|spray(?:ing|s)?|ooz(?:ing|e|es)?|'
    # Structural change
    r'crack(?:ing|s)?|shatter(?:ing|s)?|break(?:ing|s)?|fractur(?:ing|e|es)?|'
    r'split(?:ting|s)?|tear(?:ing|s)?|crumbl(?:ing|e|es)?|collaps(?:ing|e|es)?|'
    # Thermal change
    r'melt(?:ing|s)?|bubbl(?:ing|e|es)?|sizzl(?:ing|e|es)?|erupt(?:ing|s)?|'
    r'boil(?:ing|s)?|'
    # Elastic / explosive
    r'stretch(?:ing|es)?|swell(?:ing|s)?|burst(?:ing|s)?|'
    # Liquid surface
    r'rippl(?:ing|e|es)?'
    r')\b', re.IGNORECASE,
)

# Food noun → its natural liquid form (for motion injection)
_FOOD_TO_LIQUID: Dict[str, str] = {
    "pomegranate": "juice", "orange": "juice", "lemon": "juice",
    "lime": "juice", "watermelon": "juice", "grape": "juice",
    "berry": "juice", "mango": "juice", "peach": "juice",
    "cherry": "juice", "plum": "juice", "apple": "juice",
    "honey": "honey", "chocolate": "chocolate", "caramel": "caramel",
    "cheese": "cheese", "butter": "butter", "cream": "cream",
    "croissant": "butter", "pastry": "butter", "bread": "moisture",
    "ice": "meltwater", "gelatin": "gelatin", "jelly": "jelly",
    "syrup": "syrup", "sauce": "sauce", "soup": "broth",
    "baklava": "honey", "cake": "glaze", "donut": "glaze",
    "waffle": "syrup", "pancake": "syrup", "pie": "filling",
}

# Liquid words detectable in image_prompt text
_LIQUID_FOOD_WORDS: Set[str] = {
    "juice", "honey", "sauce", "syrup", "cream", "chocolate", "caramel",
    "oil", "broth", "soup", "milk", "butter", "glaze", "nectar", "jam",
    "jelly", "custard", "molasses", "gravy", "wine", "sap", "liquid",
    "moisture", "condensation", "water", "meltwater", "gelatin",
}

# Crispy/hard surface words
_CRISPY_FOOD_WORDS: Set[str] = {
    "crust", "bread", "pastry", "shell", "chips", "cracker", "cookie",
    "biscuit", "wafer", "phyllo", "croissant", "crispy", "crunchy",
    "flaky", "brittle", "toast", "pretzel", "rind", "skin", "bark",
}

# Injection templates per food type: (video_prompt_phrase, motion_element)
# {food} is replaced with detected food liquid (e.g. "juice", "honey")
_LIQUID_MOTION_TEMPLATES: List[Tuple[str, str]] = [
    ("{food} seeping through structural joints", "{food} seeping through joints"),
    ("{food} dripping from surface edges", "{food} dripping from edges"),
    ("{food} trickling down wall faces", "{food} trickling down walls"),
    ("{food} pooling on ledge surfaces", "{food} pooling on ledges"),
]

_CRISPY_MOTION_TEMPLATES: List[Tuple[str, str]] = [
    ("{food} fragments crumbling from weathered edges", "{food} crumbling from edges"),
    ("surface {food} cracking under thermal stress", "{food} surface cracking"),
    ("{food} debris breaking loose from facade", "{food} debris breaking loose"),
]

_DEFAULT_MOTION_TEMPLATES: List[Tuple[str, str]] = [
    ("moisture dripping from overhanging edges", "moisture dripping"),
    ("surface texture cracking under temperature shift", "surface cracking"),
    ("condensation trickling down walls", "condensation trickling"),
]


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


def _split_no_block(prompt: str) -> Tuple[str, str]:
    """Split image_prompt into (core_prompt, no_block).

    The --no block is a negative prompt directive at the end that should be
    preserved during word count trimming (it doesn't count toward word budget).
    """
    match = re.search(r'\s*(--no\s+.+)$', prompt, re.IGNORECASE)
    if match:
        core = prompt[:match.start()].rstrip()
        no_block = match.group(1)
        return core, no_block
    return prompt, ""


def _extract_gerunds_from_text(text: str) -> List[str]:
    """Extract gerund-based phrases (2-3 words starting with gerund) from text."""
    # Match patterns like "liquid stretching", "steam rising softly"
    matches = re.findall(r'\b(\w+ing(?:\s+\w+){0,2})\b', text, re.IGNORECASE)
    return [m.strip() for m in matches if len(m.split()) >= 1]


def _has_physical_state_change(text: str) -> bool:
    """Check if text contains at least one physical state change verb."""
    return bool(_PHYSICAL_STATE_CHANGE_RE.search(text))


def _detect_food_noun(gen1_data: Optional[Dict]) -> str:
    """Extract primary food noun from GEN1 food_identity."""
    if not gen1_data:
        return "food"
    food_id = gen1_data.get("food_identity", {})
    if isinstance(food_id, dict):
        primary = food_id.get("primary_food", "")
        if isinstance(primary, str) and primary.strip():
            # Last word is usually the food noun: "Ruby Red Pomegranate" → "pomegranate"
            return primary.strip().split()[-1].lower()
    return "food"


def _detect_food_liquid(image_prompt: str, food_noun: str) -> Optional[str]:
    """Detect appropriate liquid word for motion injection.

    Strategy: check image_prompt for explicit liquid words, then fall back to
    food_noun → liquid mapping.
    """
    ip_lower = image_prompt.lower()

    # Direct liquid word in image_prompt (word-boundary match to avoid "oil" in "soil")
    for word in sorted(_LIQUID_FOOD_WORDS, key=len, reverse=True):
        if re.search(r'\b' + re.escape(word) + r'\b', ip_lower):
            return word

    # Food noun → liquid mapping
    if food_noun in _FOOD_TO_LIQUID:
        return _FOOD_TO_LIQUID[food_noun]

    return None


def _pick_food_motion(
    scene_number: int,
    image_prompt: str,
    food_noun: str,
) -> Tuple[str, str]:
    """Pick a food-appropriate physical motion phrase for injection.

    Returns (video_prompt_phrase, motion_element_phrase).
    Uses scene_number for deterministic rotation across templates.
    """
    ip_lower = image_prompt.lower()

    # Strategy 1: liquid food → liquid motion
    liquid = _detect_food_liquid(image_prompt, food_noun)
    if liquid:
        templates = _LIQUID_MOTION_TEMPLATES
        idx = (scene_number - 1) % len(templates)
        vp, me = templates[idx]
        return vp.replace("{food}", liquid), me.replace("{food}", liquid)

    # Strategy 2: crispy food → structural motion (word-boundary to avoid "encrusted"→"crust")
    for word in _CRISPY_FOOD_WORDS:
        if re.search(r'\b' + re.escape(word) + r'\b', ip_lower) or word == food_noun:
            templates = _CRISPY_MOTION_TEMPLATES
            idx = (scene_number - 1) % len(templates)
            vp, me = templates[idx]
            return vp.replace("{food}", food_noun), me.replace("{food}", food_noun)

    # Strategy 3: default moisture motion
    idx = (scene_number - 1) % len(_DEFAULT_MOTION_TEMPLATES)
    return _DEFAULT_MOTION_TEMPLATES[idx]


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

    # Phase 1: Tier & structure
    _fix_tier_assignment(d, scenes, gen1_data, w)
    _fix_body_trigger_keywords(d, scenes, gen1_data, w)  # inject before trim
    _fix_word_counts(d, scenes, w)                        # trim respects --no block
    _fix_safe_zone_instruction(d, scenes, w)              # after trim, add safe zone
    _fix_money_shot_cold_contrast(d, scenes, w)           # enforce cold bg on money shot
    _fix_inheritance_structure(d, scenes, w)

    # Phase 2: Motion & energy
    _fix_motion_intensity_floor(d, scenes, gen1_data, w)
    _fix_motion_elements_count(d, scenes, gen1_data, w)         # pad to energy minimum
    _fix_subject_motion_enforcement(d, scenes, gen1_data, w)    # inject physical state change
    _fix_loop_close_reversal_safety(d, scenes, gen1_data, w)    # fix unsafe motion words

    # Phase 3: Composition & prompts
    _fix_first_frame_composition(d, scenes, gen1_data, w)
    _fix_video_prompt_camera_gerund(d, scenes, w)               # ensure camera gerund
    _fix_video_prompt_expansion(d, scenes, gen1_data, w)        # expand short video_prompts
    _fix_aerial_scene_no_block(d, scenes, gen1_data, w)           # remove form-blocking words from AERIAL --no

    # Phase 4: Global settings
    _fix_negative_prompt_tier_additions(d, scenes, w)
    _fix_atmosphere_negatives(d, scenes, gen1_data, w)          # atmosphere-specific negatives
    _fix_gigantism_applied(d, scenes, w)                        # set gigantism flag

    # Phase 5: Summary
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

    Preserves --no negative block during trim (it's not counted toward word budget).
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

        # Separate --no block before counting words
        core, no_block = _split_no_block(prompt)
        core_words = core.split()
        if len(core_words) <= max_words:
            continue

        # Trim core by sentences to stay under max_words
        sentences = re.split(r'(?<=[.!?])\s+', core)
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

        # Re-append --no block
        if no_block:
            trimmed = f"{trimmed} {no_block}"

        # Count only core words for reporting (--no block doesn't count)
        trimmed_core, _ = _split_no_block(trimmed)
        scene["image_prompt"] = trimmed
        w.append(AutoFixWarning(
            f"scenes[{i}].image_prompt",
            f"Word count trim: {len(core_words)} → {len(trimmed_core.split())} core words (tier {tier} max={max_words})",
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

    # gigantism_protocol — must match global_settings.gigantism_applied
    gs = d.get("global_settings", {})
    gigantism_applied = gs.get("gigantism_applied") if isinstance(gs, dict) else None
    gp = vs.get("gigantism_protocol")
    if gigantism_applied is True and gp != "APPLIED":
        vs["gigantism_protocol"] = "APPLIED"
        changed = True
    elif gigantism_applied is False and gp == "APPLIED":
        vs["gigantism_protocol"] = "SKIPPED"
        changed = True
    elif gigantism_applied is not None and gp is None:
        vs["gigantism_protocol"] = "APPLIED" if gigantism_applied else "SKIPPED"
        changed = True

    if changed:
        w.append(AutoFixWarning(
            "visual_summary",
            "Auto-filled missing defaults (total_scenes, reference_breakdown, loop_verified, gigantism_protocol)",
        ))


# ---------------------------------------------------------------------------
# NEW FIX FUNCTIONS (v2.0)
# ---------------------------------------------------------------------------

def _fix_motion_elements_count(d: dict, scenes: list, gen1_data: Optional[dict], w: list) -> None:
    """Pad motion_elements to meet energy-level minimum count.

    EXPLOSIVE needs 4+, HIGH needs 3+, MEDIUM/LOW need 2+.
    Extracts additional motion phrases from video_prompt when padding is needed.
    """
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue

        sn = scene.get("scene_number", i + 1)
        gen1_scene = _get_gen1_scene(gen1_data, sn)
        energy = gen1_scene.get("energy_level", "MEDIUM") if gen1_scene else "MEDIUM"
        if not isinstance(energy, str):
            energy = "MEDIUM"

        required_min = ENERGY_MOTION_MIN.get(energy.upper(), 2)
        motion = scene.get("motion_elements", [])
        if not isinstance(motion, list):
            motion = []
            scene["motion_elements"] = motion

        if len(motion) >= required_min:
            continue

        # Try to extract gerund phrases from video_prompt
        video_prompt = scene.get("video_prompt", "")
        existing_lower = {m.lower() for m in motion if isinstance(m, str)}
        candidates = []

        if isinstance(video_prompt, str):
            gerunds = _extract_gerunds_from_text(video_prompt)
            for g in gerunds:
                if g.lower() not in existing_lower and len(g.split()) >= 2:
                    candidates.append(g)
                    existing_lower.add(g.lower())

        # Also try image_prompt
        if len(motion) + len(candidates) < required_min:
            image_prompt = scene.get("image_prompt", "")
            if isinstance(image_prompt, str):
                # Extract from --no-free core
                core, _ = _split_no_block(image_prompt)
                gerunds = _extract_gerunds_from_text(core)
                for g in gerunds:
                    if g.lower() not in existing_lower and len(g.split()) >= 2:
                        candidates.append(g)
                        existing_lower.add(g.lower())

        # Fallback generic motion phrases
        fallbacks = [
            "light shifting across surface",
            "texture detail emerging",
            "atmospheric particles drifting",
            "surface tension resolving",
            "ambient glow intensifying",
        ]
        for fb in fallbacks:
            if len(motion) + len(candidates) >= required_min:
                break
            if fb.lower() not in existing_lower:
                candidates.append(fb)
                existing_lower.add(fb.lower())

        # Append needed candidates
        needed = required_min - len(motion)
        added = candidates[:needed]
        if added:
            motion.extend(added)
            scene["motion_elements"] = motion
            w.append(AutoFixWarning(
                f"scenes[{i}].motion_elements",
                f"Padded {len(motion) - len(added)} → {len(motion)} (energy={energy} min={required_min}): +{added}",
            ))


def _fix_subject_motion_enforcement(d: dict, scenes: list, gen1_data: Optional[dict], w: list) -> None:
    """Ensure every scene (except LOOP_CLOSE) has at least one physical state change.

    Video prompts with only ambient motion (light shifting, shadows sweeping, fog
    drifting) cause Kling to render Ken Burns-style animated images instead of
    actual video.  At least one physical state change verb (drip, crack, flow,
    melt, etc.) is required in the combined video_prompt + motion_elements text.

    Injection strategy:
    1. Detect food type from GEN1 food_identity
    2. Pick food-appropriate physical motion phrase (liquid seeping, crust crumbling, etc.)
    3. Insert into video_prompt after camera clause + add to motion_elements
    """
    food_noun = _detect_food_noun(gen1_data)

    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue

        # Skip LOOP_CLOSE — reversal safety constraints take priority
        if scene.get("reference_type") == "LOOP_CLOSE":
            continue

        sn = scene.get("scene_number", i + 1)
        video_prompt = scene.get("video_prompt", "")
        motion_elements = scene.get("motion_elements", [])
        if not isinstance(motion_elements, list):
            motion_elements = []
            scene["motion_elements"] = motion_elements

        if not isinstance(video_prompt, str) or not video_prompt.strip():
            continue

        # Combine video_prompt + motion_elements text for checking
        combined = video_prompt.lower()
        for me in motion_elements:
            if isinstance(me, str):
                combined += " " + me.lower()

        if _has_physical_state_change(combined):
            continue  # Already has physical state change — skip

        # Pick food-appropriate physical motion
        image_prompt = scene.get("image_prompt", "")
        if not isinstance(image_prompt, str):
            image_prompt = ""
        vp_phrase, me_phrase = _pick_food_motion(sn, image_prompt, food_noun)

        # Inject into video_prompt after the camera movement clause (first comma)
        first_comma = video_prompt.find(",")
        if first_comma != -1:
            before = video_prompt[:first_comma].rstrip()
            after = video_prompt[first_comma + 1:].lstrip()
            scene["video_prompt"] = f"{before}, {vp_phrase}, {after}"
        else:
            scene["video_prompt"] = f"{video_prompt.rstrip('. ,')}, {vp_phrase}"

        # Add to motion_elements (but respect LOW energy max of 2)
        gen1_scene = _get_gen1_scene(gen1_data, sn)
        energy = gen1_scene.get("energy_level", "MEDIUM") if gen1_scene else "MEDIUM"
        if not isinstance(energy, str):
            energy = "MEDIUM"
        if energy.upper() == "LOW" and len(motion_elements) >= 2:
            pass  # Don't exceed LOW cap, video_prompt injection is enough
        else:
            motion_elements.insert(0, me_phrase)
            scene["motion_elements"] = motion_elements

        w.append(AutoFixWarning(
            f"scenes[{i}].video_prompt",
            f"Subject motion: injected '{me_phrase}' (was ambient-only, no physical state change)",
        ))


def _fix_loop_close_reversal_safety(d: dict, scenes: list, gen1_data: Optional[dict], w: list) -> None:
    """Replace reversal-unsafe words in LOOP_CLOSE scene motion_elements.

    Last scene is reversed in post-production, so directional motion
    (rising, falling, dripping, etc.) looks unnatural. Replace with
    reversal-safe alternatives.
    """
    if not scenes:
        return

    last_scene = scenes[-1]
    if not isinstance(last_scene, dict):
        return
    if last_scene.get("reference_type") != "LOOP_CLOSE":
        return

    idx = len(scenes) - 1
    motion = last_scene.get("motion_elements", [])
    if not isinstance(motion, list):
        return

    fixed_any = False
    new_motion = []
    for me in motion:
        if not isinstance(me, str):
            new_motion.append(me)
            continue

        me_lower = me.lower()
        replaced = False
        new_elem = me
        replaced_words = []
        for unsafe, safe in REVERSAL_SAFE_REPLACEMENTS.items():
            if re.search(r'\b' + re.escape(unsafe) + r'\b', me_lower):
                # Replace the unsafe word within the element (word-boundary)
                new_elem = re.sub(
                    r'\b' + re.escape(unsafe) + r'\b',
                    safe,
                    new_elem,
                    flags=re.IGNORECASE,
                )
                replaced = True
                fixed_any = True
                replaced_words.append(unsafe)
                me_lower = new_elem.lower()  # re-scan with updated text
        if replaced:
            w.append(AutoFixWarning(
                f"scenes[{idx}].motion_elements",
                f"Reversal-safe fix: '{me}' → '{new_elem}' (replaced: {', '.join(replaced_words)})",
            ))
            new_motion.append(new_elem)
        else:
            new_motion.append(me)

    if fixed_any:
        last_scene["motion_elements"] = new_motion

        # Also fix loop_verification.motion_elements_reversal_safe
        vs = d.get("visual_summary")
        if isinstance(vs, dict):
            lv = vs.get("loop_verification")
            if isinstance(lv, dict):
                if not lv.get("motion_elements_reversal_safe"):
                    lv["motion_elements_reversal_safe"] = True
                    w.append(AutoFixWarning(
                        "visual_summary.loop_verification.motion_elements_reversal_safe",
                        "Set to true after fixing unsafe motion_elements",
                    ))


def _fix_gigantism_applied(d: dict, scenes: list, w: list) -> None:
    """Set global_settings.gigantism_applied based on tier distribution.

    If any scene has TIER_4_ARCHITECTURE → true (architecture/gigantism mode).
    Otherwise → false (appetite/macro mode).
    """
    gs = d.get("global_settings")
    if not isinstance(gs, dict):
        return

    if gs.get("gigantism_applied") is not None:
        return  # already set

    has_architecture = any(
        isinstance(s, dict) and s.get("visual_tier") == "TIER_4_ARCHITECTURE"
        for s in scenes
    )
    gs["gigantism_applied"] = has_architecture
    w.append(AutoFixWarning(
        "global_settings.gigantism_applied",
        f"Set to {has_architecture} (based on {'TIER_4 present' if has_architecture else 'no TIER_4 scenes'})",
    ))


def _fix_safe_zone_instruction(d: dict, scenes: list, w: list) -> None:
    """Add safe zone text to image_prompts missing it.

    Validator checks for phrases like "upper portion", "upper 60%", etc.
    Inserts before the --no block (or at end if no --no block).
    """
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        prompt = scene.get("image_prompt", "")
        if not isinstance(prompt, str) or not prompt:
            continue

        prompt_lower = prompt.lower()
        has_safe_zone = any(phrase in prompt_lower for phrase in SAFE_ZONE_PHRASES)
        if has_safe_zone:
            continue

        safe_zone_text = "Subject positioned in upper portion of frame."

        core, no_block = _split_no_block(prompt)
        # Ensure core ends with period
        if not core.rstrip().endswith((".", "!", "?")):
            core = core.rstrip(",;:—–- ") + "."

        if no_block:
            scene["image_prompt"] = f"{core} {safe_zone_text} {no_block}"
        else:
            scene["image_prompt"] = f"{core} {safe_zone_text}"

        w.append(AutoFixWarning(
            f"scenes[{i}].image_prompt",
            "Appended safe zone instruction: 'Subject positioned in upper portion of frame'",
        ))


def _fix_money_shot_cold_contrast(d: dict, scenes: list, w: list) -> None:
    """Enforce cold/dark background for TIER_1_MONEY_SHOT scenes.

    Warm food against cold background = maximum appetite contrast.
    Replaces warm/neutral/white background phrases with cold alternatives.
    If no cold indicator found and no warm phrase matched, inserts cold bg before --no block.
    """
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        if scene.get("visual_tier") != "TIER_1_MONEY_SHOT":
            continue

        prompt = scene.get("image_prompt", "")
        if not isinstance(prompt, str) or not prompt:
            continue

        prompt_lower = prompt.lower()

        # Skip if already has a cold background indicator
        if any(ind in prompt_lower for ind in COLD_BG_INDICATORS):
            continue

        # Try to replace warm/neutral background phrases
        new_prompt = prompt
        replaced = False
        for pattern, replacement in MONEY_SHOT_WARM_BG_PATTERNS:
            new_prompt, count = re.subn(pattern, replacement, new_prompt, flags=re.IGNORECASE)
            if count > 0:
                replaced = True

        if replaced:
            scene["image_prompt"] = new_prompt
            w.append(AutoFixWarning(
                f"scenes[{i}].image_prompt",
                "Money shot cold contrast: replaced warm/neutral background with cold palette",
            ))
            continue

        # No warm phrase found but also no cold indicator → inject before --no block
        core, no_block = _split_no_block(prompt)
        cold_insert = "Deep cool blue-black background behind subject."
        if not core.rstrip().endswith((".", "!", "?")):
            core = core.rstrip(",;:—–- ") + "."

        if no_block:
            scene["image_prompt"] = f"{core} {cold_insert} {no_block}"
        else:
            scene["image_prompt"] = f"{core} {cold_insert}"

        w.append(AutoFixWarning(
            f"scenes[{i}].image_prompt",
            "Money shot cold contrast: inserted cold background instruction (no warm/cold indicator found)",
        ))


def _fix_video_prompt_expansion(d: dict, scenes: list, gen1_data: Optional[dict], w: list) -> None:
    """Expand short video_prompts to meet tier word count minimum.

    Extracts texture/atmosphere descriptors from image_prompt and
    appends as comma-separated clauses. Tracks exact word count.
    """
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue

        tier = scene.get("visual_tier", "")
        tier_range = VIDEO_WORD_RANGES.get(tier)
        if not tier_range:
            continue

        min_wc, max_wc = tier_range
        video_prompt = scene.get("video_prompt", "")
        if not isinstance(video_prompt, str):
            continue

        word_count = len(video_prompt.split())
        if word_count >= min_wc:
            continue

        # Collect candidate phrases from image_prompt
        image_prompt = scene.get("image_prompt", "")
        candidates: List[str] = []
        # Use word set for dedup (not substring — avoids "light" blocking "golden light")
        existing_words = set(video_prompt.lower().split())

        if isinstance(image_prompt, str):
            core, _ = _split_no_block(image_prompt)
            # Extract adjective+noun pairs that describe texture/motion
            pairs = re.findall(r'\b(\w+(?:ing|ed|ent|ous|al)\s+\w+)\b', core)
            for pair in pairs:
                pair_words = set(pair.lower().split())
                # Skip if ALL words already present (partial overlap is OK)
                if not pair_words.issubset(existing_words) and len(pair) > 5:
                    candidates.append(pair)
                    existing_words.update(pair_words)

        # Add generic atmospheric phrases as fallback
        for phrase in _VIDEO_EXPANSION_PHRASES:
            phrase_words = set(phrase.lower().split())
            if not phrase_words.issubset(existing_words):
                candidates.append(phrase)
                existing_words.update(phrase_words)

        if not candidates:
            continue

        # Build expansion by adding phrases one-by-one until we reach min_wc
        # Commas don't count as words (they attach to previous word)
        selected: List[str] = []
        running_wc = word_count
        for phrase in candidates:
            phrase_wc = len(phrase.split())
            if running_wc + phrase_wc > max_wc:
                continue
            selected.append(phrase)
            running_wc += phrase_wc
            if running_wc >= min_wc:
                break

        if not selected:
            continue

        suffix = ", ".join(selected)
        expanded = f"{video_prompt.rstrip('. ,')}, {suffix}."
        scene["video_prompt"] = expanded
        w.append(AutoFixWarning(
            f"scenes[{i}].video_prompt",
            f"Expanded: {word_count} → {len(expanded.split())} words (tier {tier} min={min_wc})",
        ))


def _fix_aerial_scene_no_block(d: dict, scenes: list, gen1_data: Optional[Dict], w: list) -> None:
    """Remove form-blocking words from AERIAL scene --no blocks and add replacements.

    AERIAL scenes must reveal the architectural FORM of the building.
    Words like "architecture dominant" and "building exterior" in the --no
    block prevent Kling from showing the building shape. Remove them and
    inject material-realism negatives ("real stone", "real concrete", etc.)
    to ban photorealistic architecture without blocking the food-form shape.

    NOTE: narrative_purpose lives in GEN1 output, not GEN2. We look it up
    via _get_gen1_scene() — same pattern as other cross-referencing fixes.
    """
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue

        # narrative_purpose is a GEN1 field — look it up from gen1_data
        sn = scene.get("scene_number", i + 1)
        gen1_scene = _get_gen1_scene(gen1_data, sn)
        purpose = gen1_scene.get("narrative_purpose", "") if gen1_scene else ""
        if not isinstance(purpose, str) or purpose.upper() not in _AERIAL_PURPOSES:
            continue

        prompt = scene.get("image_prompt", "")
        if not isinstance(prompt, str) or not prompt:
            continue

        core, no_block = _split_no_block(prompt)
        if not no_block:
            continue

        # Extract the words after "--no " prefix
        no_prefix_match = re.match(r'--no\s+', no_block, re.IGNORECASE)
        if not no_prefix_match:
            continue
        no_content = no_block[no_prefix_match.end():]

        # Split into comma-separated items and filter (skip empty from double commas)
        items = [item.strip() for item in no_content.split(",") if item.strip()]
        removed = []
        kept = []
        for item in items:
            item_lower = item.lower()
            if any(banned == item_lower for banned in _AERIAL_NO_BLOCK_REMOVE):
                removed.append(item)
            else:
                kept.append(item)

        if not removed:
            continue

        # Inject replacement negatives (ban material realism, not form)
        kept_lower = {k.lower() for k in kept}
        for repl in _AERIAL_REPLACEMENT_NEGATIVES:
            if repl.lower() not in kept_lower:
                kept.append(repl)
                kept_lower.add(repl.lower())

        # Rejoin
        if kept:
            new_no_block = "--no " + ", ".join(kept)
        else:
            new_no_block = ""

        if new_no_block:
            scene["image_prompt"] = f"{core} {new_no_block}"
        else:
            scene["image_prompt"] = core

        w.append(AutoFixWarning(
            f"scenes[{i}].image_prompt",
            f"AERIAL --no cleanup: removed {', '.join(removed)} → added material-realism negatives",
        ))


def _fix_video_prompt_camera_gerund(d: dict, scenes: list, w: list) -> None:
    """Ensure video_prompt contains at least one camera movement gerund.

    Validator checks for words from ALLOWED_CAMERA_MOVEMENTS.
    If missing, prepend "Camera [gerund]" based on context.
    """
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        video_prompt = scene.get("video_prompt", "")
        if not isinstance(video_prompt, str) or not video_prompt:
            continue

        prompt_lower = video_prompt.lower()

        # Skip if already has a camera movement gerund
        if any(mv in prompt_lower for mv in ALLOWED_CAMERA_MOVEMENTS):
            continue

        # Skip truly stationary scenes (rare; "static macro" gets a subtle gerund)
        if "stationary" in prompt_lower:
            continue

        # Infer best gerund from scene context (word-boundary to avoid "cup"→"up")
        ref_type = scene.get("reference_type", "")
        _wb = lambda w: bool(re.search(r'\b' + re.escape(w) + r'\b', prompt_lower))
        if ref_type == "LOOP_CLOSE":
            gerund = "pulling"  # safe for reversal
        elif _wb("orbit") or _wb("around"):
            gerund = "orbiting"
        elif _wb("up") or _wb("above"):
            gerund = "ascending"
        elif _wb("down") or _wb("below"):
            gerund = "descending"
        elif _wb("close") or _wb("macro") or _wb("static"):
            gerund = "pushing"
        elif _wb("wide") or _wb("reveal"):
            gerund = "pulling"
        else:
            gerund = "tracking"

        # For "Static macro" prompts, replace "Static" with camera gerund
        if prompt_lower.startswith("static"):
            video_prompt = re.sub(r'^[Ss]tatic\s*', '', video_prompt).lstrip(', ')

        scene["video_prompt"] = f"Camera {gerund}, {video_prompt}"
        w.append(AutoFixWarning(
            f"scenes[{i}].video_prompt",
            f"Prepended camera gerund: 'Camera {gerund}'",
        ))


def _fix_atmosphere_negatives(d: dict, scenes: list, gen1_data: Optional[dict], w: list) -> None:
    """Append atmosphere-mode-specific keywords to global negative_prompt.

    NOIR/HAUNTED need "flat lighting, even illumination" in negative.
    ETHEREAL needs "harsh shadows, high contrast".
    """
    if not gen1_data:
        return

    atmosphere_mode = gen1_data.get("atmosphere_mode", "")
    if not isinstance(atmosphere_mode, str) or not atmosphere_mode:
        return

    atmosphere_upper = atmosphere_mode.upper().strip()
    required_negatives = ATMOSPHERE_NEGATIVE_ADDITIONS.get(atmosphere_upper)
    if not required_negatives:
        return

    gs = d.get("global_settings")
    if not isinstance(gs, dict):
        return

    neg = gs.get("negative_prompt", "")
    if not isinstance(neg, str):
        neg = ""

    neg_lower = neg.lower()
    missing = [kw for kw in required_negatives if kw.lower() not in neg_lower]
    if not missing:
        return

    addition = ", ".join(missing)
    if neg.strip():
        gs["negative_prompt"] = f"{neg.rstrip(', ')}, {addition}"
    else:
        gs["negative_prompt"] = addition
    w.append(AutoFixWarning(
        "global_settings.negative_prompt",
        f"Atmosphere '{atmosphere_upper}' additions: {addition}",
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
    "ENERGY_MOTION_MIN",
    "VIDEO_WORD_RANGES",
    "REVERSAL_SAFE_REPLACEMENTS",
    "ATMOSPHERE_NEGATIVE_ADDITIONS",
    "_PHYSICAL_STATE_CHANGE_RE",
]
