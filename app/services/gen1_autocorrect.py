"""
GEN1 Auto-Corrector v3.10

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

from app.services.structural_memory import structural_memory


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
    # Religious/cultural architecture
    "altar", "pew", "pews", "nave", "aisle", "spire", "vault", "crypt",
    "chancel", "apse", "pillar", "gargoyle", "buttress", "minaret", "bell",
    # Industrial/special
    "reactor", "turbine", "conveyor", "silo", "tank", "vent", "hatch",
    "platform", "catwalk", "crane", "furnace", "boiler",
    # Mechanical/security (bank vaults, factories, etc.)
    "lock", "dial", "handle", "knob", "lever", "switch", "panel",
    "grate", "grille", "shutter", "valve", "gauge", "gear",
    # Nature-integrated
    "terrace", "courtyard", "garden", "pathway", "canal", "well",
    # Transport/vehicle structures
    "wheel", "track", "rail", "mast", "hull", "rudder", "propeller",
    "cockpit", "cabin", "deck",
    # Fortification/castle
    "moat", "tunnel", "corridor", "chamber", "gate", "drawbridge",
    "parapet", "turret", "bunker",
    # Plumbing/conduit
    "sewer", "duct", "chute", "slot", "nozzle", "funnel", "drain", "spout",
}

# Food actions whitelist (for warning_line)
VALID_FOOD_ACTIONS: set = {
    "lick", "bite", "eat", "drink", "touch", "taste", "chew", "nibble",
    "swallow", "smell", "scrape", "peel", "squeeze", "sip", "crunch",
    "snap", "break", "crack", "slice", "dip",
    # Extended actions (from smoke tests 22-26)
    "poke", "bounce", "press", "pull", "twist", "scratch", "tap",
    "rub", "pinch", "grab", "yank", "prod", "punch", "kick", "step",
}

# Temperature words for THERMAL first word auto-fix
TEMPERATURE_WORDS: set = {
    "warm", "hot", "cold", "cool", "steaming", "frozen",
    "still warm", "still hot", "still cold",
}

# Number words that already serve as thermal/sensory hook openers
# (e.g. "Seventy-two layers", "Three thousand degrees", "Ninety degrees")
_NUMBER_WORDS: set = {
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen", "twenty", "thirty",
    "forty", "fifty", "sixty", "seventy", "eighty", "ninety",
    "hundred", "thousand", "million", "billion",
}

# Words that already imply temperature/sensation and shouldn't be prefixed
_THERMAL_HOOK_WORDS: set = TEMPERATURE_WORDS | {
    "degrees", "celsius", "fahrenheit", "boiling", "sizzling", "melting",
    "burning", "scalding", "icy", "chilled", "molten", "bubbling",
    "fresh", "crisp",
    # Expanded thermal variants (from _TEXTURE_TO_TEMPS) — prevent double-prepend
    "barely", "scorched", "body", "room", "forty", "ice", "frozen",
}

# Architectural form words for dual identity check (on_screen_text scenes 2..N-1)
# Includes structural, transport/vehicle, and scale words that hint at FORM
ARCHITECTURAL_FORM_WORDS: set = {
    # Structural
    "wall", "walls", "arch", "arches", "dome", "domes", "column", "columns",
    "tower", "towers", "vault", "vaults", "floor", "floors", "ceiling",
    "gate", "gates", "bridge", "hull", "deck", "window", "windows",
    "stair", "stairs", "spire", "spires", "buttress", "nave", "pillar",
    "pillars", "facade", "parapet", "rampart", "turret", "balcony",
    "corridor", "tunnel", "chamber", "roof", "rooftop",
    # Transport/vehicle forms (pirate ships, trains, etc.)
    "mast", "cabin", "rudder", "cockpit", "galleon", "keel",
    # Aquatic/futuristic/industrial enclosures
    "room", "rooms", "tank", "tanks", "aquarium", "pod", "pods",
    "capsule", "hangar", "atrium", "lobby", "shaft", "duct",
    "pipe", "pipes", "silo", "bunker", "observatory",
    # Scale/structural words used in food-form context
    "layer", "layers", "tier", "tiers", "level", "levels",
    # Interior/furniture-scale architectural elements
    "shelf", "shelves", "aisle", "aisles", "panel", "panels",
    "ledge", "ledges", "alcove", "niche", "slab", "ramp",
    "terrace", "rack", "racks", "beam", "beams",
    "rail", "rails", "platform", "joint", "joints",
    "hall", "halls", "archive", "archives", "gallery",
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

# Olfactory word stems for 4-channel sensory audit (matches inflected forms via prefix)
_OLFACTORY_STEMS: set = {
    "smell", "smells", "smelling", "scent", "scented", "scents",
    "aroma", "aromas", "aromatic", "fragrant", "fragrance",
    "yeast", "sweet", "nutty", "buttery", "vanilla", "caramel",
    "smoky", "earthy", "tangy", "pungent", "musky",
    "nose", "inhale", "inhaling", "breath", "breathe",
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
    # New hallucinations from Gemini 3 Pro (smoke23+)
    "CONTEXT": "CONTEXTUAL_ENVIRONMENT",
    "ACTION": "DYNAMIC_ACTION",
    "OVERVIEW": "EXTERIOR_ANGLE",
    "INTRO": "ESTABLISHING",
    "CLOSE": "LOOP_CLOSE",
    "WIDE": "EXTERIOR_ANGLE",
    "MACRO": "DETAIL",
    "SENSATION": "FEATURE",
    # Phase labels used as narrative_purpose (smoke27-29)
    "SENSORY_BUILD": "STRUCTURAL_DETAIL",
    "TENSION": "DYNAMIC_ACTION",
    "AFTERMATH": "FEATURE_HIGHLIGHT",
    # Gemini 3 Pro hallucinations (prod 2026-02)
    "ASMR_BEAT": "DETAIL",
    "ASMR": "DETAIL",
    "SENSORY": "DETAIL",
    "TEXTURE": "DETAIL",
}

# Appetite-killing dominant_color keywords → auto-replace with food color
_GREY_COLOR_WORDS: set = {"grey", "gray", "slate", "charcoal", "ash"}

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

# Expanded thermal variants for concept_hash rotation (anti-"Still warm." lock)
# IMPORTANT: index 0 must be DIFFERENT across texture groups so hash%4==0
# doesn't produce the same opener for every food. See memory/MEMORY.md.
_TEXTURE_TO_TEMPS: dict = {
    # EVERY variant MUST contain a word from _THERMAL_WORDS (validator check)
    # Index 0 MUST be unique across groups (anti-"Still warm." lock)
    "crispy": ["Barely cooled.", "The heat.", "Scorched.", "Warm. Flaky."],
    "crunchy": ["Still hot.", "Cool. Loud.", "The heat.", "Just cooled."],
    "brittle": ["Room temperature.", "Cool.", "Forty degrees.", "Chilled."],
    "creamy": ["Chilled.", "Cold.", "Frozen.", "Still cold."],
    "chewy": ["Steaming.", "Body heat.", "Warm.", "Still warm."],
    "smooth": ["Forty degrees.", "Room temperature.", "Cool.", "Just cooled."],
    "gooey": ["The heat.", "Just melted.", "Still hot.", "Warm."],
    "silky": ["Just cooled.", "Chilled.", "Still cool.", "Cool."],
    "crunchy-wet": ["Ice cold.", "Still cold.", "Just cooled.", "Cool."],
}

# Pause tag approximate durations (seconds) for word-count budget
# ElevenLabs SSML: [pause] → <break time="0.3s"/>, etc.
_PAUSE_TAG_RE = re.compile(r'\[(long\s+pause|short\s+pause|pause)\]', re.IGNORECASE)
_PAUSE_TAG_TIME: dict = {
    "long pause": 0.7,
    "pause": 0.3,
    "short pause": 0.2,
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


def _estimate_pause_time(vo_segment: str) -> float:
    """Estimate time consumed by pause/delivery tags in voiceover_segment.

    [pause] ≈ 0.3s, [short pause] ≈ 0.2s, [long pause] ≈ 0.7s.
    These eat into scene duration → fewer words fit.
    """
    if not vo_segment:
        return 0.0
    total = 0.0
    for match in _PAUSE_TAG_RE.finditer(vo_segment):
        tag_name = re.sub(r'\s+', ' ', match.group(1).lower().strip())
        total += _PAUSE_TAG_TIME.get(tag_name, 0.3)
    return total


def _closest_match(word: str, valid_set: set, default: str, cutoff: float = 0.7) -> str:
    """Find closest match using difflib. Higher cutoff = more conservative.

    Returns default only if no match found at given cutoff.
    Use cutoff=0.7 (stricter) to avoid absurd replacements like 'lock' → 'silo'.
    """
    import difflib
    matches = difflib.get_close_matches(word, valid_set, n=1, cutoff=cutoff)
    return matches[0] if matches else default


def _element_in_concept(element: str, data: dict) -> bool:
    """Check if element appears in concept data (architectural_identity or food_dna).

    If an element is part of the concept, it should be kept as-is even if not
    in VALID_ARCHITECTURE_ELEMENTS — it's a creative choice, not a hallucination.
    """
    elem_lower = element.lower()
    # Check architectural_identity.distinctive_features
    arch = data.get("architectural_identity", {})
    if isinstance(arch, dict):
        features = arch.get("distinctive_features", [])
        if isinstance(features, list):
            for feat in features:
                if isinstance(feat, str) and elem_lower in feat.lower():
                    return True
    # Check food_identity.food_dna values
    food_id = data.get("food_identity", {})
    food_dna = food_id.get("food_dna", {}) if isinstance(food_id, dict) else {}
    if isinstance(food_dna, dict):
        for val in food_dna.values():
            if isinstance(val, str) and elem_lower in val.lower():
                return True
    return False


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


def _concept_hash(data: dict) -> int:
    """Deterministic hash from concept data for rotation decisions.

    Uses food name + subject to produce a stable integer.
    Different concepts → different hash → different rotation choices.
    """
    food = _get_food_name(data) or "x"
    subject = _get_subject(data) or "x"
    return sum(ord(c) for c in (food + subject).lower())


# ---------------------------------------------------------------------------
# MAIN AUTOCORRECT FUNCTION
# ---------------------------------------------------------------------------

def autocorrect_gen1(data: Dict[str, Any], thermal_blacklist: Optional[Set[str]] = None, channel_id: str = "glaze_city") -> Tuple[Dict[str, Any], List[AutoFixWarning]]:
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
    _fix_body_trigger_hard_limits(d, w)
    _fix_entry_type_hard_limit(d, w)
    _warn_frequency_limits(d, w)
    _fix_narrative_purposes(d, w)
    _fix_structural_detail_count(scenes, w)  # Exactly 1 STRUCTURAL_DETAIL (Gemini ignores count)
    _fix_easter_egg_and_pinned(d, w)
    _fix_food_visual_ratio(d, scenes, w)
    _fix_sp_commitment_floor(d, scenes, w)
    _fix_money_shot_vo(d, scenes, w)
    _fix_asmr_whisper_anchor(d, scenes, w)
    _fix_narrative_bridges(scenes, w)
    _fix_silence_speech_contradiction(d, scenes, w)
    _fix_on_screen_text(d, scenes, w)
    _surface_humor_to_vo(d, scenes, w)  # Humor must be heard/seen — inject BEFORE word count
    _warn_on_screen_text_dual_identity(d, scenes, w)
    _warn_vo_dual_identity(d, scenes, w)
    _fix_scene_n_minus_1_aerial(scenes, w)
    _fix_warning_line_format_rotation(d, scenes, w)  # BUG 4: must be BEFORE delivery+sync
    _fix_warning_line_delivery(d, scenes, w)
    _fix_direction_tags(scenes, w)
    _fix_narrator_script_tags(scenes, w)
    _fix_warning_line_element_sync(d, scenes, w)
    _fix_thermal_first_word(d, scenes, w, thermal_blacklist=thermal_blacklist)
    _fix_narrator_vo_sync(scenes, w)
    _fix_duplicate_vo_across_scenes(scenes, w)  # Silence duplicate VO BEFORE duration/truncation
    _fix_scene_durations(scenes, w)
    # _fix_narrator_word_count(scenes, w)     # DISABLED: validator-driven VO enforcement — Gemini owns word budget
    _fix_dangling_narrator_endings(d, scenes, w)  # P0-2: standalone dangling strip (after truncation)
    _flag_semantic_truncation(d, scenes, w)        # P1: flag transitive verb truncation
    _fix_scene_n_constraints(d, scenes, w)
    _fix_scene_n_minus_1_vo(d, scenes, w)
    _fix_description_hashtags(d, w, channel_id=channel_id)  # OPSEC: strip AI/cross-channel hashtags
    _fix_generic_cta(d, w)                                   # OPSEC: replace template CTAs
    _fix_description_line1(d, w)
    _fix_title_default_rotation(d, w)       # BUG 6: FOOD_BUILD → other
    _fix_controversy_rotation(d, w)         # BUG 9: THE_PHYSICS → other
    _fix_completion_bait_rotation(d, w)     # Anti-template-lock: "One more [noun]" (BEFORE injection)
    _fix_vo_trigger_injection(d, scenes, w) # Inject AFTER rotation so text matches
    _fix_share_trigger_rotation(d, w)       # Anti-template-lock: "[qualifier] [identity]"
    _fix_series_hook(d, w, channel_id=channel_id)  # P0-2: series_hook missing fallback
    _fix_grey_dominant_color(d, scenes, w)  # OPT: grey→warm color in food scenes
    _fix_lighting_rotation(d, w)                  # Anti-template-lock: NIGHT_NEON/MORNING_GOLDEN
    _fix_warm_food_warm_light_collision(d, w)     # P1: warm food + warm light = visual monotony (AFTER rotation)
    _fix_required_top_level_fields(d, scenes, w)  # P0: loop, first_frame, temp_contrast fallbacks
    _fix_consecutive_warm_backgrounds(d, scenes, w)  # Fix 6: break WARM/NEUTRAL runs
    _fix_energy_floor(d, scenes, w)        # P0: consecutive LOW ban + max 1 LOW + ramp
    _fix_hook_first_words_sync(d, scenes, w)  # P0: hook.first_words ↔ narrator_script sync
    _fix_money_shot_saliva_trigger(d, scenes, w)     # Craving anchor: inject saliva trigger word
    _fix_olfactory_channel_injection(d, scenes, w)  # 4-channel: inject smell word if missing
    _fix_temporal_channel_injection(d, scenes, w)   # 4-channel: inject "still X-ing" if missing
    _fix_tactile_channel_injection(d, scenes, w)    # 4-channel: inject texture word if missing
    # _fix_narrator_word_count(scenes, w)     # DISABLED: validator-driven VO enforcement — Gemini owns word budget
    # _verify_humor_survived(d, scenes, w)   # DISABLED: no truncation → no humor rescue needed
    _fix_voiceover_segment_word_sync(d, scenes, w)  # Sync VO content words to narrator (after truncation)
    _warn_total_vo_budget(d, scenes, w)              # Warn if estimated VO > target duration
    _fix_full_script_rebuild(d, scenes, w)  # ALWAYS last — rebuilds from segments

    return d, w


# ---------------------------------------------------------------------------
# INDIVIDUAL FIX FUNCTIONS
# ---------------------------------------------------------------------------

def _fix_metadata_types(d: dict, w: list) -> None:
    """Fix metadata type issues (scene_count/target_duration_seconds as string, etc.)."""
    meta = d.get("metadata")
    if not isinstance(meta, dict):
        return

    # scene_count: string → int
    sc = meta.get("scene_count")
    if isinstance(sc, str):
        try:
            meta["scene_count"] = int(sc)
            w.append(AutoFixWarning("metadata.scene_count", f"Auto-coerced string '{sc}' → int {int(sc)}"))
        except ValueError:
            pass

    # target_duration_seconds: string → float (or int if whole number)
    tds = meta.get("target_duration_seconds")
    if isinstance(tds, str):
        try:
            val = float(tds)
            meta["target_duration_seconds"] = int(val) if val == int(val) else val
            w.append(AutoFixWarning("metadata.target_duration_seconds", f"Auto-coerced string '{tds}' → {meta['target_duration_seconds']}"))
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# STRUCTURAL MEMORY ENFORCEMENT (HARD LIMITS)
# ---------------------------------------------------------------------------

_BODY_TRIGGERS = ["MOUTH", "EARS", "NOSE", "STOMACH", "SKIN"]


def _fix_body_trigger_hard_limits(d: dict, w: list) -> None:
    """Enforce body_trigger HARD LIMITS via StructuralMemory.

    HARD LIMIT #17: same body_trigger 2x in a row → rotate to next
    HARD LIMIT #16: SKIN max 1 in 3 → rotate if exceeded
    """
    hook = d.get("hook")
    if not isinstance(hook, dict):
        return
    current = hook.get("body_trigger")
    if not current or not isinstance(current, str):
        return

    current_upper = current.upper()

    # Skip if not enough history
    if len(structural_memory.fingerprints) < 1:
        return

    rotated = False

    # HARD LIMIT #17: same trigger 2x in row → rotate
    last = structural_memory.last_value("body_trigger")
    if last and last.upper() == current_upper:
        # Pick first trigger not used in last 2
        recent_2 = {
            str(fp.get("body_trigger", "")).upper()
            for fp in structural_memory.get_recent(2)
        }
        for candidate in _BODY_TRIGGERS:
            if candidate != current_upper and candidate not in recent_2:
                hook["body_trigger"] = candidate
                w.append(AutoFixWarning(
                    "hook.body_trigger",
                    f"HARD LIMIT #17: '{current_upper}' 2x in row → rotated to '{candidate}'",
                ))
                rotated = True
                break

    # HARD LIMIT #16: SKIN max 1 in 3
    if not rotated and current_upper == "SKIN":
        skin_count = structural_memory.count_in_window("body_trigger", "SKIN", 3)
        if skin_count >= 1:
            recent_3 = {
                str(fp.get("body_trigger", "")).upper()
                for fp in structural_memory.get_recent(3)
            }
            for candidate in _BODY_TRIGGERS:
                if candidate != "SKIN" and candidate not in recent_3:
                    hook["body_trigger"] = candidate
                    w.append(AutoFixWarning(
                        "hook.body_trigger",
                        f"HARD LIMIT #16: SKIN {skin_count + 1}/3 → rotated to '{candidate}'",
                    ))
                    break


def _fix_entry_type_hard_limit(d: dict, w: list) -> None:
    """Enforce HARD LIMIT #18: MACRO_ENTRY max 3 consecutive → force SCALE_SHOCK."""
    hook = d.get("hook")
    if not isinstance(hook, dict):
        return
    current = hook.get("scene_1_entry_type", "")
    if not isinstance(current, str):
        return

    if current.upper() != "MACRO_ENTRY":
        return

    consecutive = structural_memory.consecutive_count("scene_1_entry_type", "MACRO_ENTRY")
    if consecutive >= 3:
        hook["scene_1_entry_type"] = "SCALE_SHOCK"
        w.append(AutoFixWarning(
            "hook.scene_1_entry_type",
            f"HARD LIMIT #18: MACRO_ENTRY {consecutive + 1}x consecutive → forced SCALE_SHOCK",
        ))


def _warn_frequency_limits(d: dict, w: list) -> None:
    """Issue warnings for frequency HARD LIMITS (no mutation — changing these would break concept coherence).

    #4: THE_IMPOSSIBLE max 1 in 4
    #5: THE_SENSORY_ATTACK max 1 in 4
    #8: FOG_GATE max 1 in 4
    #3: scene_count=7 max 3 in 5
    #19: SP peak at Scene 5 max 2 in 4
    #20: Scene 1 SP=7 max 2 in 4
    """
    if len(structural_memory.fingerprints) < 2:
        return

    hook = d.get("hook", {})
    if not isinstance(hook, dict):
        hook = {}
    hook_type = hook.get("type", "")
    loop = d.get("loop", {})
    if not isinstance(loop, dict):
        loop = {}
    loop_conn = loop.get("connection", "")
    scenes = d.get("scenes", [])
    scene_count = len(scenes)

    # #4: THE_IMPOSSIBLE max 1 in 4
    if hook_type == "THE_IMPOSSIBLE":
        cnt = structural_memory.count_in_window("hook_type", "THE_IMPOSSIBLE", 4)
        if cnt >= 1:
            w.append(AutoFixWarning(
                "hook.type",
                f"HARD LIMIT #4 WARNING: THE_IMPOSSIBLE {cnt + 1}/4 in last 4 (max 1)",
            ))

    # #5: THE_SENSORY_ATTACK max 1 in 4
    if hook_type == "THE_SENSORY_ATTACK":
        cnt = structural_memory.count_in_window("hook_type", "THE_SENSORY_ATTACK", 4)
        if cnt >= 1:
            w.append(AutoFixWarning(
                "hook.type",
                f"HARD LIMIT #5 WARNING: THE_SENSORY_ATTACK {cnt + 1}/4 in last 4 (max 1)",
            ))

    # #8: FOG_GATE max 1 in 4
    if loop_conn == "FOG_GATE":
        cnt = structural_memory.count_in_window("loop_technique", "FOG_GATE", 4)
        if cnt >= 1:
            w.append(AutoFixWarning(
                "loop.connection",
                f"HARD LIMIT #8 WARNING: FOG_GATE {cnt + 1}/4 in last 4 (max 1)",
            ))

    # #3: scene_count=7 max 3 in 5
    if scene_count == 7:
        cnt = structural_memory.count_in_window("scene_count", "7", 5)
        if cnt >= 3:
            w.append(AutoFixWarning(
                "metadata.scene_count",
                f"HARD LIMIT #3 WARNING: scene_count=7 {cnt + 1}/5 in last 5 (max 3)",
            ))

    # #19: SP peak at Scene 5 max 2 in 4
    sp_values = []
    for s in scenes:
        sp = s.get("sensory_pressure")
        if isinstance(sp, (int, float)):
            sp_values.append((s.get("scene_number", 0), int(sp)))
    if sp_values:
        peak = max(sp_values, key=lambda x: x[1])
        if peak[0] == 5:
            cnt = structural_memory.count_in_window("sp_peak_scene", "5", 4)
            if cnt >= 2:
                w.append(AutoFixWarning(
                    "sensory_pressure.peak",
                    f"HARD LIMIT #19 WARNING: SP peak at S5 {cnt + 1}/4 in last 4 (max 2)",
                ))

    # #20: Scene 1 SP=7 max 2 in 4
    scene1_sp = None
    for s in scenes:
        if s.get("scene_number") == 1:
            scene1_sp = s.get("sensory_pressure")
            break
    if scene1_sp == 7:
        cnt = structural_memory.count_in_window("sp_scene_1", "7", 4)
        if cnt >= 2:
            w.append(AutoFixWarning(
                "scenes[0].sensory_pressure",
                f"HARD LIMIT #20 WARNING: Scene 1 SP=7 {cnt + 1}/4 in last 4 (max 2)",
            ))


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


_VALID_NARRATIVE_PURPOSES: set = {
    "ESTABLISHING", "EXTERIOR_ANGLE", "AERIAL", "INTERIOR", "DETAIL",
    "FEATURE", "LOOP_CLOSE", "STRUCTURAL_DETAIL", "THEMATIC_INTERIOR",
    "CONTEXTUAL_ENVIRONMENT", "DYNAMIC_ACTION", "FEATURE_HIGHLIGHT",
    "AERIAL_WOW", "AERIAL_REVEAL",
}


def _fix_narrative_purposes(d: dict, w: list) -> None:
    """Fix narrative_purpose confusion with phase labels.

    Priority order:
    1. Scene 1 → ESTABLISHING
    2. Scene N → LOOP_CLOSE
    3. Scene N-1 → AERIAL
    4. Money shot scene → FEATURE_HIGHLIGHT
    5. Known fix mapping → _PURPOSE_FIXES
    6. Catch-all unknown → DETAIL (prevents validator error on hallucinations)
    """
    scenes = d.get("scenes", [])
    total = len(scenes)
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        purpose = scene.get("narrative_purpose", "")
        needs_fix = purpose in _PURPOSE_FIXES
        is_unknown = purpose and purpose not in _VALID_NARRATIVE_PURPOSES
        if not needs_fix and not is_unknown:
            continue
        scene_num = i + 1

        # Positional overrides (highest priority)
        if scene_num == 1:
            fixed = "ESTABLISHING"
        elif scene_num == total:
            fixed = "LOOP_CLOSE"
        elif scene_num == total - 1:
            fixed = "AERIAL"
        else:
            # Money shot → always FEATURE_HIGHLIGHT
            ms = scene.get("money_shot")
            is_money = isinstance(ms, dict) and ms.get("is_money_shot")
            if is_money:
                fixed = "FEATURE_HIGHLIGHT"
            elif needs_fix:
                fixed = _PURPOSE_FIXES[purpose]
            else:
                # Catch-all: unknown hallucination → DETAIL (safest generic)
                fixed = "DETAIL"

        scene["narrative_purpose"] = fixed
        label = "was phase label" if needs_fix else "unknown hallucination"
        w.append(AutoFixWarning(
            f"scenes[{i}].narrative_purpose",
            f"Auto-corrected '{purpose}' → '{fixed}' ({label})",
        ))


def _fix_structural_detail_count(scenes: list, w: list) -> None:
    """Ensure exactly 1 STRUCTURAL_DETAIL scene. Extra → DETAIL.

    Gemini 3 Pro guide: "reorder tables doesn't work" — Gemini ignores
    inline count constraints. Deterministic fix: keep the money_shot one
    (or the first one), rename extras to DETAIL.
    """
    sd_indices = [
        i for i, s in enumerate(scenes)
        if isinstance(s, dict) and s.get("narrative_purpose") == "STRUCTURAL_DETAIL"
    ]
    if len(sd_indices) <= 1:
        return

    # Prefer keeping the one with money_shot, else the first
    keep_idx = sd_indices[0]
    for idx in sd_indices:
        ms = scenes[idx].get("money_shot")
        if isinstance(ms, dict) and ms.get("is_money_shot"):
            keep_idx = idx
            break

    for idx in sd_indices:
        if idx == keep_idx:
            continue
        sn = scenes[idx].get("scene_number", idx + 1)
        scenes[idx]["narrative_purpose"] = "DETAIL"
        w.append(AutoFixWarning(
            f"scenes[{idx}].narrative_purpose",
            f"Scene {sn}: STRUCTURAL_DETAIL → DETAIL (only 1 allowed, kept Scene "
            f"{scenes[keep_idx].get('scene_number', keep_idx + 1)})",
        ))


def _fix_easter_egg_and_pinned(d: dict, w: list) -> None:
    """Fix easter egg fields, comment_bait, and pinned comment consistency."""
    engagement = d.get("engagement")
    has_real_egg = False
    scenes = d.get("scenes", [])

    if isinstance(engagement, dict):
        egg = engagement.get("easter_egg")
        if isinstance(egg, dict):
            is_audio = egg.get("format") == "AUDIO_ONLY"

            # --- Fill missing object/scene_number/placement (Gemini often omits 1-2) ---
            if not is_audio:
                if not egg.get("object") or egg.get("object") == "none":
                    food = d.get("food_identity", {}).get("primary_food", "candy")
                    egg["object"] = f"tiny {food} figurine"
                    w.append(AutoFixWarning("engagement.easter_egg.object", f"Auto-filled missing object: '{egg['object']}'"))

                try:
                    scene_num = int(egg.get("scene_number", 0))
                except (ValueError, TypeError):
                    scene_num = 0
                if scene_num < 2 or (scenes and scene_num > len(scenes) - 1):
                    # Pick a middle scene (scene 3, or clamped to valid range)
                    max_scene = max(len(scenes) - 1, 2)
                    egg["scene_number"] = min(3, max_scene)
                    w.append(AutoFixWarning("engagement.easter_egg.scene_number", f"Auto-filled invalid scene_number: {scene_num} → {egg['scene_number']}"))

                if not egg.get("placement"):
                    egg["placement"] = "background left, 5% of frame, behind main subject"
                    w.append(AutoFixWarning("engagement.easter_egg.placement", "Auto-filled missing placement"))

            obj = egg.get("object", "")
            try:
                scene_num = int(egg.get("scene_number", 0))
            except (ValueError, TypeError):
                scene_num = 0
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


def _fix_sp_commitment_floor(d: dict, scenes: list, w: list) -> None:
    """Clamp scenes[1] and scenes[2] sensory_pressure to min 6 (COMMITMENT ZONE).

    Scenes 2-3 are where the viewer decides to stay or swipe.
    SP < 6 in these scenes signals low energy → higher drop-off risk.
    """
    for idx in (1, 2):  # 0-based: Scene 2 and Scene 3
        if idx >= len(scenes):
            continue
        scene = scenes[idx]
        if not isinstance(scene, dict):
            continue
        sp = scene.get("sensory_pressure")
        if sp is None:
            continue
        try:
            sp_val = int(sp)
        except (ValueError, TypeError):
            continue
        if sp_val < 6:
            scene["sensory_pressure"] = 6
            w.append(AutoFixWarning(
                f"scenes[{idx}].sensory_pressure",
                f"Commitment zone floor: SP {sp_val} → 6 (Scene {idx + 1} must be >= 6)",
            ))


def _fix_money_shot_vo(d: dict, scenes: list, w: list) -> None:
    """Enforce money shot VO rules: MODE A = [silence], MODE B = [long pause] [whispers] <word>.

    SMART RULE: If VO already matches MODE_B_PATTERN, respect it as valid creative
    choice regardless of texture classification. Gemini knows the food better than
    a keyword lookup — if it chose a whisper, keep it.
    """
    soft = _is_soft_texture(d)
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        ms = scene.get("money_shot")
        if not (isinstance(ms, dict) and ms.get("is_money_shot")):
            continue

        vo_seg = scene.get("voiceover_segment", "")
        if vo_seg and vo_seg.strip() not in ("", "[silence]"):
            # MODE B pattern is valid for ANY texture — respect Gemini's creative choice
            if _MODE_B_PATTERN.match(vo_seg.strip()):
                pass  # Valid MODE B — keep as-is
            else:
                scene["voiceover_segment"] = "[silence]"
                scene["narrator_script"] = ""
                w.append(AutoFixWarning(
                    f"scenes[{i}].voiceover_segment",
                    f"Auto-forced '[silence]' on money_shot (was: '{vo_seg[:60]}')",
                ))
                continue  # narrator already cleared

        narrator = scene.get("narrator_script", "")
        if narrator and narrator.strip():
            # Allow 1-word narrator for MODE B (any texture) or soft texture
            vo_is_mode_b = vo_seg and _MODE_B_PATTERN.match(vo_seg.strip())
            if (soft or vo_is_mode_b) and len(narrator.strip().split()) <= 1:
                pass  # MODE B allows 1-word
            elif not vo_is_mode_b:
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
    """Clean up on_screen_text: truncate to 6 words, fix parentheticals.

    SMART RULES:
    - Scene 1: Only prepend food name if missing AND original ≤ 4 words (room to add).
      Never overwrite original with generic fallback if it already has good content
      (numbers, food names, emoji, concept keywords).
    - Other scenes: Only fix broken parentheticals and >6 word truncation.
    """
    food_name = _get_food_name(d)

    # Scene 1: conditionally prepend food name (only if short enough & not already present)
    if food_name and scenes:
        scene1 = scenes[0] if isinstance(scenes[0], dict) else {}
        on_screen = scene1.get("on_screen_text", "")
        if on_screen and isinstance(on_screen, str):
            ost_words = on_screen.strip().split()
            food_present = food_name.lower() in on_screen.lower()
            # Only prepend if: food not present, result would be ≤ 6 words
            if not food_present and len(ost_words) <= 4:
                new_ost = f"{food_name} — {on_screen.strip()}"
                if len(new_ost.split()) <= 6:
                    scene1["on_screen_text"] = new_ost
                    w.append(AutoFixWarning("scenes[0].on_screen_text",
                        f"Auto-prepended food name '{food_name}'"))

    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        on_screen = scene.get("on_screen_text", "")
        if not isinstance(on_screen, str) or not on_screen.strip():
            continue

        cleaned = on_screen.strip()
        needs_fix = False

        # Fix broken parentheticals
        if "(" in cleaned and ")" not in cleaned:
            cleaned = re.sub(r'\s*\(.*$', '', cleaned).strip()
            needs_fix = True
        if ")" in cleaned and "(" not in cleaned:
            cleaned = cleaned.replace(")", "").strip()
            needs_fix = True
        cleaned = cleaned.rstrip(",").strip()
        if cleaned != on_screen.strip():
            needs_fix = True

        # Only truncate if > 6 words
        words = cleaned.split()
        if len(words) > 6:
            # Keep first 6 words (preserve numbers, emoji, food names)
            truncated = " ".join(words[:6])
            scene["on_screen_text"] = truncated
            w.append(AutoFixWarning(f"scenes[{i}].on_screen_text",
                f"Auto-truncated: '{on_screen.strip()[:40]}' → '{truncated}'"))
        elif needs_fix:
            scene["on_screen_text"] = cleaned
            w.append(AutoFixWarning(f"scenes[{i}].on_screen_text",
                f"Auto-cleaned parentheticals: '{on_screen.strip()[:40]}' → '{cleaned}'"))


def _extract_turn_words(line: str) -> Optional[Set[str]]:
    """Extract punchline/turn words from humor line's last sentence.

    Returns None if line has only 1 sentence (no distinct turn).
    """
    sentences = re.split(r'(?<=[.!?])\s+', line.strip())
    sentences = [s for s in sentences if s.strip()]
    if len(sentences) < 2:
        return None  # single sentence — general matcher handles it

    turn_sentence = sentences[-1]
    turn_words = {
        wd.strip(".,!?:;\"'").lower()
        for wd in turn_sentence.split()
        if len(wd.strip(".,!?:;\"'")) >= 3  # >=3 not >3, catch short punchlines like "Jam"
    }
    return turn_words if turn_words else None


def _surface_humor_to_vo(d: dict, scenes: list, w: list) -> None:
    """Surface humor lines into VO or on-screen text so viewers actually see/hear them.

    Problem: humor array is metadata — viewers never see it unless the humor line
    also appears in voiceover_segment or on_screen_text. Gemini often assigns humor
    to [silence] scenes, leaving jokes orphaned.

    Strategy:
    1. For each humor entry, check if its key words appear in the scene's VO or OSD.
    2. If the scene has [silence] VO → inject first sentence of humor line as whispered VO.
    3. If the scene already has VO but humor is still absent → warn (can't auto-fix safely).
    """
    humor = d.get("humor")
    if not humor or not isinstance(humor, list):
        return

    for h_idx, h in enumerate(humor):
        if not isinstance(h, dict):
            continue
        scene_num = h.get("scene_number")
        line = h.get("line", "")
        if not scene_num or not isinstance(line, str) or not line.strip():
            continue

        # Find the associated scene (0-indexed)
        try:
            s_idx = int(scene_num) - 1
        except (ValueError, TypeError):
            continue
        if s_idx < 0 or s_idx >= len(scenes):
            continue
        scene = scenes[s_idx]
        if not isinstance(scene, dict):
            continue

        # Check if humor is already surfaced in VO or on-screen text
        vo_seg = scene.get("voiceover_segment", "") or ""
        on_screen = scene.get("on_screen_text", "") or ""
        narrator = scene.get("narrator_script", "") or ""

        # Extract key content words from humor line (strip punctuation, lowercase)
        humor_words = {
            wd.strip(".,!?:;\"'").lower()
            for wd in line.split()
            if len(wd.strip(".,!?:;\"'")) > 3  # skip short words
        }
        vo_plain = _strip_tags(vo_seg).lower()
        osd_plain = on_screen.lower()

        # Count how many humor keywords appear in VO or OSD
        vo_hits = sum(1 for hw in humor_words if hw in vo_plain)
        osd_hits = sum(1 for hw in humor_words if hw in osd_plain)
        surfaced = (vo_hits >= 2) or (osd_hits >= 2)  # at least 2 key words match

        # Turn-word check: if humor has distinct turn (≥2 sentences),
        # require at least 1 turn word present — setup match alone is not enough
        turn_words = _extract_turn_words(line)
        if surfaced and turn_words:
            turn_in_vo = any(tw in vo_plain for tw in turn_words)
            turn_in_osd = any(tw in osd_plain for tw in turn_words)
            if not turn_in_vo and not turn_in_osd:
                surfaced = False  # setup words matched but punchline is missing

        if surfaced:
            continue  # humor is already visible/audible

        # --- Attempt auto-fix: inject humor into [silence] VO ---
        is_silence = (not vo_seg.strip() or vo_seg.strip() == "[silence]")
        if not is_silence:
            # Scene has existing VO — try 3 injection paths instead of giving up

            # Current narrator word count
            narrator_words = [wd for wd in narrator.split() if wd.strip()] if narrator.strip() else []
            narrator_wc = len(narrator_words)

            dur = scene.get("duration_seconds", 2.0)
            try:
                dur_f = float(dur)
            except (ValueError, TypeError):
                dur_f = 2.0
            max_w = _max_words_for_duration(dur_f)

            # Extract humor first sentence
            humor_sentences = re.split(r'(?<=[.!?])\s+', line.strip())
            humor_first = humor_sentences[0].rstrip(".")
            humor_first_words = humor_first.split()

            # Check if this is a turn-substitution case (setup in VO, turn missing)
            is_turn_substitution = (turn_words is not None
                                    and vo_hits >= 2
                                    and not any(tw in vo_plain for tw in turn_words))

            if is_turn_substitution:
                # Gemini wrote the setup but substituted the punchline — replace with humor line
                humor_clean = line.strip().rstrip(".")
                humor_wc = len(humor_clean.split())
                if humor_wc <= max_w:
                    scene["narrator_script"] = f"{humor_clean}."
                    tag_match = re.match(r'\[[\w\s]+\]', vo_seg.strip())
                    leading_tag = tag_match.group(0) if tag_match else "[whispers]"
                    scene["voiceover_segment"] = f"{leading_tag} {humor_clean}."
                    w.append(AutoFixWarning(
                        f"scenes[{s_idx}].voiceover_segment",
                        f"Humor TURN FIX: replaced substituted punchline in VO: '{humor_clean[:50]}.'"
                    ))
                    continue
                # Fall through to PATH 1/2/3 if humor line too long

            # PATH 1: Append full first sentence with [pause] separator
            if narrator_wc + len(humor_first_words) <= max_w:
                appended_narrator = f"{narrator.rstrip().rstrip('.')}. {humor_first}."
                scene["narrator_script"] = appended_narrator
                # Rebuild voiceover_segment with pause separator
                tag_match = re.match(r'\[[\w\s]+\]', vo_seg.strip())
                leading_tag = tag_match.group(0) if tag_match else "[whispers]"
                scene["voiceover_segment"] = f"{leading_tag} {_strip_tags(narrator).rstrip().rstrip('.')}. [pause] {humor_first}."
                w.append(AutoFixWarning(
                    f"scenes[{s_idx}].voiceover_segment",
                    f"Humor PATH 1: appended to existing VO: '...{humor_first[:40]}.'"
                ))
                continue

            # PATH 2: Extract first clause (before comma/dash) — shortened version
            clause_match = re.split(r'[,\u2014—]', humor_first, maxsplit=1)
            if len(clause_match) > 1:
                short_clause = clause_match[0].strip().rstrip(".")
                short_clause_words = short_clause.split()
                if narrator_wc + len(short_clause_words) <= max_w and len(short_clause_words) >= 2:
                    appended_narrator = f"{narrator.rstrip().rstrip('.')}. {short_clause}."
                    scene["narrator_script"] = appended_narrator
                    tag_match = re.match(r'\[[\w\s]+\]', vo_seg.strip())
                    leading_tag = tag_match.group(0) if tag_match else "[whispers]"
                    scene["voiceover_segment"] = f"{leading_tag} {_strip_tags(narrator).rstrip().rstrip('.')}. [pause] {short_clause}."
                    w.append(AutoFixWarning(
                        f"scenes[{s_idx}].voiceover_segment",
                        f"Humor PATH 2: appended shortened clause: '...{short_clause[:40]}.'"
                    ))
                    continue

            # PATH 3: OSD fallback — put humor in on_screen_text (≤6 words)
            osd_candidate_words = humor_first_words[:6]
            osd_text = " ".join(osd_candidate_words)
            if len(osd_candidate_words) >= 2:
                existing_osd = scene.get("on_screen_text", "")
                if not existing_osd or not existing_osd.strip():
                    scene["on_screen_text"] = osd_text
                    w.append(AutoFixWarning(
                        f"scenes[{s_idx}].on_screen_text",
                        f"Humor PATH 3: placed in OSD (VO full): '{osd_text}'"
                    ))
                    continue

            # All 3 paths exhausted — warn
            w.append(AutoFixWarning(
                f"humor[{h_idx}]",
                f"Humor line orphaned — all injection paths exhausted for "
                f"Scene {scene_num}: '{line[:60]}'"
            ))
            continue

        # Extract first sentence (the punchier part) from humor line
        sentences = re.split(r'(?<=[.!?])\s+', line.strip())
        candidate = sentences[0].rstrip(".")
        candidate_words = candidate.split()

        # Check word limit for scene duration
        dur = scene.get("duration_seconds", 2.0)
        try:
            dur_f = float(dur)
        except (ValueError, TypeError):
            dur_f = 2.0
        max_w = _max_words_for_duration(dur_f)

        if len(candidate_words) > max_w:
            # First sentence too long — try second sentence if exists
            if len(sentences) > 1:
                candidate = sentences[1].rstrip(".")
                candidate_words = candidate.split()
            if len(candidate_words) > max_w:
                # Still too long — warn
                w.append(AutoFixWarning(
                    f"humor[{h_idx}]",
                    f"Humor line too long for Scene {scene_num} ({len(candidate_words)}w > {max_w}w limit): "
                    f"'{line[:60]}'"
                ))
                continue

        # Inject as whispered VO
        scene["voiceover_segment"] = f"[whispers] {candidate}."
        scene["narrator_script"] = f"{candidate}."
        w.append(AutoFixWarning(
            f"scenes[{s_idx}].voiceover_segment",
            f"Auto-injected humor line into [silence] scene: '[whispers] {candidate}.'"
        ))


def _warn_on_screen_text_dual_identity(d: dict, scenes: list, w: list) -> None:
    """Warn if on_screen_text in scenes 2..N-1 lacks architectural form words.

    NOT an autofix — we can't deterministically pick the right form word
    without visual_concept context. Gemini handles this via GEN1 prompt rules.
    This just catches misses.
    """
    if len(scenes) < 3:
        return
    total = len(scenes)
    missing_count = 0
    checked_count = 0
    for i, scene in enumerate(scenes):
        sn = i + 1
        if sn <= 1 or sn >= total:
            continue  # skip Scene 1 (macro) and Scene N (LOOP_CLOSE)
        if not isinstance(scene, dict):
            continue
        ost = scene.get("on_screen_text", "")
        if not ost or not isinstance(ost, str) or not ost.strip():
            continue
        checked_count += 1
        ost_words = {wd.strip(".,!?:;\"'").lower() for wd in ost.split()}
        has_form = bool(ost_words & ARCHITECTURAL_FORM_WORDS)
        if not has_form:
            missing_count += 1
            w.append(AutoFixWarning(
                f"scenes[{i}].on_screen_text",
                f"No architectural form word (wall/arch/dome/column...) — "
                f"mute viewers miss dual identity: '{ost.strip()[:40]}'"
            ))
    if checked_count > 0 and missing_count > checked_count * 0.5:
        w.append(AutoFixWarning(
            "on_screen_text.dual_identity",
            f"{missing_count}/{checked_count} middle scenes lack form words — "
            f"dual identity weak (>50% miss)"
        ))


# Interior/structural narrative purposes where VO should reinforce dual identity
_VO_DUAL_IDENTITY_PURPOSES: set = {
    "THEMATIC_INTERIOR", "FEATURE_HIGHLIGHT", "STRUCTURAL_DETAIL", "CONTEXTUAL_ENVIRONMENT",
}


def _warn_vo_dual_identity(d: dict, scenes: list, w: list) -> None:
    """Warn if voiceover in interior/structural scenes lacks architectural context words.

    Scenes with narrative_purpose in (THEMATIC_INTERIOR, FEATURE_HIGHLIGHT,
    STRUCTURAL_DETAIL, CONTEXTUAL_ENVIRONMENT) should reference architectural
    forms in VO to reinforce dual identity for sound-on viewers.

    NOT an autofix — VO is too nuanced for deterministic changes.
    """
    if len(scenes) < 3:
        return
    total = len(scenes)
    missing_count = 0
    checked_count = 0
    for i, scene in enumerate(scenes):
        sn = i + 1
        if sn <= 1 or sn >= total:
            continue  # skip Scene 1 (macro) and Scene N (LOOP_CLOSE)
        if not isinstance(scene, dict):
            continue
        purpose = scene.get("narrative_purpose", "")
        if not isinstance(purpose, str) or purpose.upper() not in _VO_DUAL_IDENTITY_PURPOSES:
            continue
        # Check narrator_script or voiceover_segment for arch words
        # Strip VO tags ([whispers], [pause], etc.) before matching
        narrator = scene.get("narrator_script", "") or ""
        vo_seg = _strip_tags(scene.get("voiceover_segment", "") or "")
        combined = f"{narrator} {vo_seg}".lower()
        combined_words = {wd.strip(".,!?:;\"'") for wd in combined.split()}
        has_form = bool(combined_words & ARCHITECTURAL_FORM_WORDS)
        checked_count += 1
        if not has_form:
            missing_count += 1
            w.append(AutoFixWarning(
                f"scenes[{i}].voiceover_segment",
                f"VO lacks architectural context word (wall/corridor/tank...) — "
                f"sound-on viewers miss dual identity: '{narrator.strip()[:40]}'"
            ))
    if checked_count > 0 and missing_count > checked_count * 0.5:
        w.append(AutoFixWarning(
            "voiceover.dual_identity",
            f"{missing_count}/{checked_count} interior scenes lack arch words in VO — "
            f"dual identity weak for sound-on viewers (>50% miss)"
        ))


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
    Supports formats A-F. Formats D/E/F skip action+element sync (different structure).
    """
    warning_line_raw = d.get("warning_line", "")
    if not isinstance(warning_line_raw, str) or not warning_line_raw.strip():
        return

    wl_stripped = _strip_tags(warning_line_raw)

    # ---- NEW FORMATS D/E/F — early return (no action+element structure) ----
    _CONSEQUENCE_VERBS = {"remember", "remembers", "know", "knows", "watch", "watches",
                          "wait", "waits", "listen", "listens", "breathe", "breathes"}
    _FORMAT_D = re.compile(r"^the\s+(\w+)\s+(\w+)\b", re.IGNORECASE)
    _FORMAT_E = re.compile(r"^(\w+)\s+was\s+never\s+meant\s+for\s+(\w+)", re.IGNORECASE)
    _FORMAT_F = re.compile(r"^nobody\s+warns\s+you\s+about\s+the\s+(.+)", re.IGNORECASE)

    _d_match = _FORMAT_D.match(wl_stripped)
    _d_is_format_d = _d_match and _d_match.group(2).lower() in _CONSEQUENCE_VERBS
    if _d_is_format_d or _FORMAT_E.match(wl_stripped) or _FORMAT_F.match(wl_stripped):
        # Formats D/E/F are structurally valid — skip action+element sync
        return

    # ---- FORMATS A/B/C — original logic ----
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
            best_action = raw_action if raw_action in VALID_FOOD_ACTIONS else _closest_match(raw_action, VALID_FOOD_ACTIONS, raw_action)
            best_element = _infer_element(d)
            new_wl = f"Don't {best_action} the {best_element}."
            d["warning_line"] = new_wl
            w.append(AutoFixWarning("warning_line", f"Auto-fixed non-standard: '{warning_line_raw}' → '{new_wl}'"))
            wl_action, wl_element = best_action, best_element

    # Auto-fix invalid action/element
    if wl_action and wl_element:
        if wl_action not in VALID_FOOD_ACTIONS:
            fixed_action = _closest_match(wl_action, VALID_FOOD_ACTIONS, wl_action)
            if fixed_action != wl_action:
                old = d.get("warning_line", "")
                d["warning_line"] = re.sub(re.escape(wl_action), fixed_action, old, count=1, flags=re.IGNORECASE)
                w.append(AutoFixWarning("warning_line", f"Auto-fixed action '{wl_action}' → '{fixed_action}'"))
                wl_action = fixed_action
            else:
                # No close match — keep original, just warn
                w.append(AutoFixWarning("warning_line", f"Non-standard action '{wl_action}' (kept as-is, no close match)"))

        if wl_element not in VALID_ARCHITECTURE_ELEMENTS:
            # Concept-aware bypass: if element is in concept data, keep it
            if _element_in_concept(wl_element, d):
                w.append(AutoFixWarning("warning_line",
                    f"Non-standard element '{wl_element}' kept (found in concept data)"))
            else:
                fixed_elem = _closest_match(wl_element, VALID_ARCHITECTURE_ELEMENTS, wl_element)
                if fixed_elem != wl_element:
                    old = d.get("warning_line", "")
                    d["warning_line"] = re.sub(
                        r"(?i)the\s+" + re.escape(wl_element),
                        f"the {fixed_elem}", old, count=1,
                    )
                    w.append(AutoFixWarning("warning_line", f"Auto-fixed element '{wl_element}' → '{fixed_elem}'"))
                    wl_element = fixed_elem
                else:
                    # No close match — keep original creative choice, just warn
                    w.append(AutoFixWarning("warning_line", f"Non-standard element '{wl_element}' (kept as-is, no close match)"))

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

def _fix_thermal_first_word(d: dict, scenes: list, w: list, thermal_blacklist: Optional[Set[str]] = None) -> None:
    """Scene 1 narrator_script MUST start with a temperature word.

    TOP RULE: THERMAL SLOT in Scene 1 is MANDATORY.
    Template: "[temperature]. [rest]"

    SMART DETECTION: Skip prepend if narrator already opens with:
    - A temperature/thermal word ("Warm.", "Steaming.", "Ninety degrees.")
    - A number word ("Seventy-two layers") — numbers are strong hooks
    - "Still X" pattern already present anywhere in first sentence
    """
    if not scenes or not isinstance(scenes[0], dict):
        return
    scene1 = scenes[0]
    narrator = scene1.get("narrator_script", "")
    if not isinstance(narrator, str) or not narrator.strip():
        return

    words = narrator.strip().split()
    first_word = words[0].rstrip(".,!?;:").lower()
    two_word = " ".join(words[:2]).rstrip(".,!?;:").lower() if len(words) >= 2 else first_word

    # Already starts with temperature word
    if first_word in TEMPERATURE_WORDS or two_word in TEMPERATURE_WORDS:
        return

    # Already starts with thermal/sensation hook word
    if first_word in _THERMAL_HOOK_WORDS:
        return

    # Starts with a number word (strong sensory hook, don't weaken it)
    # Handles both word-numbers ("Seventy-two") and digit-numbers ("72")
    first_word_base = first_word.split("-")[0]  # "seventy-two" → "seventy"
    if first_word_base in _NUMBER_WORDS or first_word.isdigit():
        return

    # Check if "Still warm" / "Still hot" etc. already exists in first sentence
    first_sentence = narrator.strip().split(".")[0].lower()
    if any(tw in first_sentence for tw in ("still warm", "still hot", "still cold")):
        return

    # "This [X] isn't [Y]" / "This [X] is [Y]" = impossibility hook — don't weaken with thermal prefix
    if re.match(r"^this\s+\w+\s+(isn['\u2019]t|is|was|has|looks|smells|tastes)\b", narrator.strip(), re.IGNORECASE):
        return

    # Determine temperature word from texture group + concept_hash for variety
    texture = _get_texture_group(d)
    h = _concept_hash(d)
    temps = _TEXTURE_TO_TEMPS.get(texture, ["Still warm.", "The heat.", "Barely cooled.", "Scorched."])
    temp_sentence = temps[h % len(temps)]

    # Blacklist check: rotate to next candidate if selected phrase matches recent opener
    if thermal_blacklist:
        selected_key = temp_sentence.split(".")[0].strip().lower()
        if selected_key in thermal_blacklist:
            original_idx = h % len(temps)
            for offset in range(1, len(temps)):
                candidate_idx = (original_idx + offset) % len(temps)
                candidate_key = temps[candidate_idx].split(".")[0].strip().lower()
                if candidate_key not in thermal_blacklist:
                    temp_sentence = temps[candidate_idx]
                    break
            # If all blocked, keep original (better than nothing)

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

        # Skip intentional silence only (not empty — empty needs Case 2)
        if vo_seg.strip() == "[silence]":
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


def _fix_duplicate_vo_across_scenes(scenes: list, w: list) -> None:
    """Detect and silence duplicate narrator_script lines across scenes.

    Duplicate VO → ElevenLabs generates same audio twice → broken pacing.
    Second occurrence → [silence], narrator cleared.
    Skips: [silence], empty, 1-word lines (too generic: "Warm.", "Cold.").
    """
    if len(scenes) < 3:
        return

    seen: dict = {}  # normalized text → first scene index

    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue

        narrator = scene.get("narrator_script", "")
        if not isinstance(narrator, str) or not narrator.strip():
            continue

        vo_seg = scene.get("voiceover_segment", "")
        if isinstance(vo_seg, str) and vo_seg.strip() == "[silence]":
            continue

        # Normalize: lowercase, strip punctuation, collapse whitespace
        normalized = re.sub(r'[.,!?;:\-\u2014\u2013]+', '', narrator.lower()).strip()
        normalized = re.sub(r'\s+', ' ', normalized)

        # Skip 1-word lines (generic: "Warm.", "Cold.", "Crunch.")
        if len(normalized.split()) < 2:
            continue

        if normalized in seen:
            first_idx = seen[normalized]
            first_sn = (
                scenes[first_idx].get("scene_number", first_idx + 1)
                if isinstance(scenes[first_idx], dict) else first_idx + 1
            )
            sn = scene.get("scene_number", i + 1)
            scene["voiceover_segment"] = "[silence]"
            scene["narrator_script"] = ""
            w.append(AutoFixWarning(
                f"scenes[{i}].narrator_script",
                f"Duplicate VO in Scene {sn} (same as Scene {first_sn}): "
                f"'{narrator[:50]}' → [silence]",
            ))
        else:
            seen[normalized] = i


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
                is_banned = any(re.search(r'\b' + re.escape(banned) + r'\b', elem_lower) for banned in _BANNED_LOOP_MOTIONS)
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

    # Warning line completely absent — inject it (including empty/silence scenes)
    pen["voiceover_segment"] = expected_vo
    pen["narrator_script"] = wl_clean
    w.append(AutoFixWarning(f"scenes[{pen_idx}].voiceover_segment",
        f"Auto-replaced with warning_line: '{current_vo[:50]}' → '{expected_vo}'"))


def _fix_vo_trigger_injection(d: dict, scenes: list, w: list) -> None:
    """If completion_bait.vo_trigger not in its scene's voiceover_segment → append it.

    When the target scene is a money_shot ([silence]/MODE_B), relocate
    completion_bait to an adjacent scene (prefer scene_number - 1).
    """
    cb = d.get("completion_bait")
    if not isinstance(cb, dict):
        return
    vo_trigger = cb.get("vo_trigger", "")
    cb_scene_num = cb.get("scene_number")
    if not vo_trigger or cb_scene_num is None:
        return

    trigger_clean = vo_trigger.rstrip(".").rstrip("…").strip()

    # Find target scene — may relocate if money_shot blocks injection
    target_scene = None
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        if scene.get("scene_number") != cb_scene_num:
            continue

        ms = scene.get("money_shot")
        if isinstance(ms, dict) and ms.get("is_money_shot"):
            # Money_shot blocks injection — relocate to adjacent scene
            # Prefer scene before money_shot, fallback to scene after
            candidates = []
            for s in scenes:
                if not isinstance(s, dict):
                    continue
                sn = s.get("scene_number", 0)
                s_ms = s.get("money_shot")
                is_ms = isinstance(s_ms, dict) and s_ms.get("is_money_shot")
                vo = s.get("voiceover_segment", "")
                is_silence = isinstance(vo, str) and vo.strip() in ("", "[silence]")
                # Skip: money_shot, silence-only, first scene, last 2 scenes
                if is_ms or is_silence or sn <= 1 or sn >= len(scenes) - 1:
                    continue
                candidates.append(s)
            if not candidates:
                return
            # Pick the closest scene before money_shot, else closest after
            best = None
            for c in candidates:
                csn = c.get("scene_number", 0)
                if csn < cb_scene_num:
                    if best is None or csn > best.get("scene_number", 0):
                        best = c
            if best is None:
                best = candidates[0]  # fallback: first available
            target_scene = best
            # Update completion_bait.scene_number to match relocation
            new_sn = target_scene.get("scene_number", cb_scene_num - 1)
            cb["scene_number"] = new_sn
            w.append(AutoFixWarning(
                "completion_bait.scene_number",
                f"Relocated from money_shot Scene {cb_scene_num} → Scene {new_sn}",
            ))
            break
        else:
            target_scene = scene
            break

    if target_scene is None:
        return

    segment = target_scene.get("voiceover_segment", "")
    if trigger_clean in segment:
        return  # already present

    # Word-budget check: ensure trigger fits within scene duration limit
    trigger_plain = _strip_tags(vo_trigger)
    trigger_words = len(trigger_plain.split()) if trigger_plain else 0
    narrator = target_scene.get("narrator_script", "")
    current_words = len(narrator.strip().split()) if isinstance(narrator, str) and narrator.strip() else 0
    dur = target_scene.get("duration_seconds", 2.0)
    try:
        dur_f = float(dur)
    except (ValueError, TypeError):
        dur_f = 2.0
    max_w = _max_words_for_duration(dur_f)

    if current_words + trigger_words > max_w:
        # Try other non-money, non-silence scenes for room
        fallback = None
        for s in scenes:
            if not isinstance(s, dict) or s is target_scene:
                continue
            sn = s.get("scene_number", 0)
            if sn <= 1 or sn >= len(scenes) - 1:
                continue
            s_ms = s.get("money_shot")
            if isinstance(s_ms, dict) and s_ms.get("is_money_shot"):
                continue
            s_vo = s.get("voiceover_segment", "")
            if isinstance(s_vo, str) and s_vo.strip() in ("", "[silence]"):
                continue
            s_nar = s.get("narrator_script", "")
            s_words = len(s_nar.strip().split()) if isinstance(s_nar, str) and s_nar.strip() else 0
            s_dur = s.get("duration_seconds", 2.0)
            try:
                s_dur_f = float(s_dur)
            except (ValueError, TypeError):
                s_dur_f = 2.0
            if s_words + trigger_words <= _max_words_for_duration(s_dur_f):
                fallback = s
                break
        if fallback is not None:
            target_scene = fallback
            cb["scene_number"] = target_scene.get("scene_number", cb.get("scene_number"))
            segment = target_scene.get("voiceover_segment", "")
            narrator = target_scene.get("narrator_script", "")
        else:
            return  # No scene has room — skip injection, validator will flag

    # Append trigger to VO
    if segment and segment.strip() != "[silence]":
        target_scene["voiceover_segment"] = f"{segment.rstrip()} {vo_trigger}"
    else:
        target_scene["voiceover_segment"] = f"[whispers] {vo_trigger}"

    # Also update narrator_script
    if trigger_plain and (not isinstance(narrator, str) or trigger_plain not in narrator):
        nar_str = narrator if isinstance(narrator, str) else ""
        target_scene["narrator_script"] = f"{nar_str.rstrip()} {trigger_plain}".strip() if nar_str else trigger_plain

    w.append(AutoFixWarning(
        f"scenes[{target_scene.get('scene_number', '?')}].voiceover_segment",
        f"Auto-injected vo_trigger: '{vo_trigger[:40]}'",
    ))
    return


# ---------------------------------------------------------------------------
# OPSEC: AI hashtag & cross-channel ban lists
# ---------------------------------------------------------------------------

_BANNED_AI_HASHTAGS: frozenset = frozenset({
    "#aiart", "#aigenerated", "#midjourney", "#dalle", "#stablediffusion",
    "#blender3d", "#blender", "#ai", "#aiartwork", "#generativeart",
    "#aianimation", "#kling", "#runway", "#sora", "#veo", "#openai",
    "#aigeneratedfood", "#aiartcommunity",
})

_CROSS_CHANNEL_BANS: dict = {
    "glaze_city": frozenset({"#yumestate", "#yum", "#appraiser", "#inspector", "#theinspector"}),
    "yum_estate": frozenset({"#glazecity", "#glaze", "#architect", "#thewitness", "#sensorywitness"}),
}

# Default safe hashtags when count drops below 3
_DEFAULT_HASHTAGS: list = ["#oddlysatisfying", "#satisfying", "#shorts"]

# Generic CTA patterns — template-like, hurts OPSEC
_GENERIC_CTA_PATTERNS: list = [
    re.compile(r"[Ww]ould you (?:live|stay|visit|go|be|come) (?:here|there|in this)\??"),
    re.compile(r"[Yy]es or [Nn]o\??"),
    re.compile(r"[Cc]omment (?:below|yes|no)"),
    re.compile(r"[Ll]ike if you"),
]

# Food-specific CTA actions
_CTA_ACTIONS: list = ["taste", "touch", "bite", "try", "smell"]


def _fix_description_hashtags(d: dict, w: list, channel_id: str = "glaze_city") -> None:
    """Strip AI/cross-channel hashtags from YouTube description. Enforce 3-5 count."""
    youtube = d.get("youtube")
    if not isinstance(youtube, dict):
        return
    desc = youtube.get("description", "")
    if not isinstance(desc, str) or not desc.strip():
        return

    # Find all hashtags in description
    all_hashtags = re.findall(r'#[\w\-]+', desc)
    if not all_hashtags:
        return

    banned = _BANNED_AI_HASHTAGS | _CROSS_CHANNEL_BANS.get(channel_id, frozenset())
    cleaned = []
    removed = []

    for ht in all_hashtags:
        if ht.lower() in banned:
            removed.append(ht)
        else:
            cleaned.append(ht)

    # Trim to max 5
    if len(cleaned) > 5:
        excess = cleaned[5:]
        removed.extend(excess)
        cleaned = cleaned[:5]

    # Pad to min 3 with defaults
    if len(cleaned) < 3:
        for dht in _DEFAULT_HASHTAGS:
            if dht not in [h.lower() for h in cleaned]:
                cleaned.append(dht)
            if len(cleaned) >= 3:
                break

    if not removed:
        return  # nothing changed

    # Rebuild description: remove all old hashtags, append cleaned block
    desc_no_ht = desc
    for ht in all_hashtags:
        desc_no_ht = desc_no_ht.replace(ht, "")
    # Clean up leftover whitespace from removal
    desc_no_ht = re.sub(r' {2,}', ' ', desc_no_ht).strip()
    # Remove trailing empty lines
    desc_no_ht = desc_no_ht.rstrip()

    hashtag_block = " ".join(cleaned)
    youtube["description"] = f"{desc_no_ht}\n\n{hashtag_block}" if desc_no_ht else hashtag_block

    for ht in removed:
        w.append(AutoFixWarning("youtube.description.hashtags", f"Removed banned/excess hashtag: {ht}"))

    # Also clean description_variants if present
    variants = youtube.get("description_variants")
    if isinstance(variants, list):
        for i, var in enumerate(variants):
            if not isinstance(var, str):
                continue
            var_hashtags = re.findall(r'#[\w\-]+', var)
            changed = False
            for ht in var_hashtags:
                if ht.lower() in banned:
                    var = var.replace(ht, "")
                    changed = True
            if changed:
                var = re.sub(r' {2,}', ' ', var).strip()
                variants[i] = var


def _fix_generic_cta(d: dict, w: list) -> None:
    """Replace generic CTAs in description with food-specific ones."""
    youtube = d.get("youtube")
    if not isinstance(youtube, dict):
        return
    desc = youtube.get("description", "")
    if not isinstance(desc, str) or not desc.strip():
        return

    food_name = _get_food_name(d)

    replaced = False
    for pattern in _GENERIC_CTA_PATTERNS:
        match = pattern.search(desc)
        if match:
            old_cta = match.group()
            if food_name:
                # Deterministic action pick based on food_name hash
                action = _CTA_ACTIONS[sum(ord(c) for c in food_name.lower()) % len(_CTA_ACTIONS)]
                new_cta = f"Would you {action} the {food_name}?"
            else:
                new_cta = ""  # no food_name → remove entirely
            desc = desc[:match.start()] + new_cta + desc[match.end():]
            replaced = True
            w.append(AutoFixWarning("youtube.description.cta", f"Replaced generic CTA: '{old_cta}' → '{new_cta or '(removed)'}''"))

    if replaced:
        # Clean up double spaces/newlines from removals
        desc = re.sub(r' {2,}', ' ', desc)
        desc = re.sub(r'\n{3,}', '\n\n', desc)
        youtube["description"] = desc.strip()


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
    # Don't generate broken line if subject is missing/generic
    if not subject or subject.lower() in ("this", "n/a", "none", ""):
        return  # can't build a meaningful line1 without subject

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


# Word limits by scene duration (TOP RULE #1)
# v3.10: whisper-aware budget — native TTS speed 1.05x reduces pressure,
# but whisper delivery is ~30% slower than neutral. Limits account for this.
# Total budget (validator) is the real safety net.
_DURATION_WORD_LIMITS: dict = {
    1.0: 2, 1.5: 3, 2.0: 4, 2.5: 5, 3.0: 7, 3.5: 8, 4.0: 10,
}

_CONSEQUENCE_VERBS_LIST = ["remembers", "knows", "watches", "waits", "listens", "breathes"]
_FOOD_BUILD_RE = re.compile(r"^I\s+\w+(?:ed|ED)\s+", re.IGNORECASE)
_CONTROVERSY_ROTATION = ["THE_CHALLENGE", "THE_CURSED", "THE_DIVIDE", "THE_TASTE", "THE_PRICE"]


def _max_words_for_duration(duration: float) -> int:
    """Max narrator_script words for a given scene duration (TOP RULE #1)."""
    for d_val in sorted(_DURATION_WORD_LIMITS.keys()):
        if duration <= d_val + 0.01:
            return _DURATION_WORD_LIMITS[d_val]
    return 12


def _fix_narrator_word_count(scenes: list, w: list) -> None:
    """Truncate narrator_script if word count exceeds duration limit.

    TOP RULE #1: 2.0s = MAX 4 words, 3.0s = MAX 7, 4.0s = MAX 10.
    Whisper-aware: accounts for ~30% slower delivery + pause tags.
    Skips last 2 scenes (overwritten by _fix_scene_n_constraints / _fix_scene_n_minus_1_vo).
    """
    if len(scenes) < 3:
        return

    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        # Skip last 2 scenes (dedicated fixers overwrite them)
        if i >= len(scenes) - 2:
            continue

        narrator = scene.get("narrator_script", "")
        if not isinstance(narrator, str) or not narrator.strip():
            continue

        duration = scene.get("duration_seconds", 2.0)
        try:
            duration = float(duration)
        except (ValueError, TypeError):
            duration = 2.0

        # Account for pause tags consuming scene time budget
        vo_seg = scene.get("voiceover_segment", "")
        pause_time = _estimate_pause_time(vo_seg) if isinstance(vo_seg, str) else 0.0

        # Account for slow-delivery tags (ElevenLabs whisper/calm = slower TTS)
        # v3.10: native speed 1.05x partially compensates, so factors reduced
        whisper_factor = 1.0
        if isinstance(vo_seg, str):
            vo_lower = vo_seg.lower()
            if "[whispers]" in vo_lower or "[drawn out]" in vo_lower:
                whisper_factor = 1.3  # whisper ~30% slower (was 1.4, native speed 1.05 compensates)
            elif "[calm]" in vo_lower or "[gentle]" in vo_lower:
                whisper_factor = 1.1  # calm delivery slightly slower (was 1.15)

        effective_duration = max((duration - pause_time) / whisper_factor, 0.8)

        max_words = _max_words_for_duration(effective_duration)
        words = narrator.strip().split()

        if len(words) <= max_words:
            continue

        # Truncate to max_words, then strip dangling words for grammatical completeness
        DANGLING = {
            # Articles & determiners
            "a", "an", "the", "this", "that", "these", "those",
            # Prepositions
            "of", "in", "on", "at", "to", "for", "by", "with", "from",
            "about", "into", "through", "between", "under", "over", "like",
            # Conjunctions
            "and", "or", "but", "nor", "yet", "so",
            # Linking/auxiliary verbs
            "is", "are", "was", "were", "be", "been",
            "has", "have", "had", "do", "does",
            # Modal verbs
            "would", "could", "should", "can", "may", "might", "will",
            # Possessives
            "my", "your", "his", "her", "its", "our", "their",
            # Relative pronouns
            "who", "which", "whom", "whose",
            # Weak-ending adverbs
            "very", "really", "just", "even", "only", "not",
        }
        kept = words[:max_words]
        while len(kept) > 1 and kept[-1].lower().rstrip(".,!?;:") in DANGLING:
            kept.pop()
        truncated = " ".join(kept)
        if truncated[-1] not in ".!?":
            truncated = truncated.rstrip(",;:—–-") + "."

        old_count = len(words)
        scene["narrator_script"] = truncated

        # Also update voiceover_segment to match
        vo_seg = scene.get("voiceover_segment", "")
        if isinstance(vo_seg, str) and vo_seg.strip() and vo_seg.strip() != "[silence]":
            # Preserve the opening delivery tag ([whispers], [warm], etc.)
            leading_tag = "[whispers]"
            tag_match = re.match(r'\[[\w\s]+\]', vo_seg.strip())
            if tag_match:
                leading_tag = tag_match.group(0)
            scene["voiceover_segment"] = f"{leading_tag} {truncated}"

        w.append(AutoFixWarning(
            f"scenes[{i}].narrator_script",
            f"Word overflow: {old_count}→{max_words} for {duration}s: "
            f"'{narrator[:35]}' → '{truncated}'",
        ))


def _verify_humor_survived(d: dict, scenes: list, w: list) -> None:
    """Post-truncation humor rescue — re-check that humor keywords survive in VO/OSD.

    After _fix_narrator_word_count truncation, humor lines appended by Fix 1 may have
    been chopped off. This function re-checks and attempts rescue:
    1. Re-check ≥2 keyword hits in VO/OSD
    2. If humor lost: replace scene narrator with humor first sentence (if fits in word budget)
    3. If can't restore: emit HIGH severity warning
    """
    humor = d.get("humor")
    if not humor or not isinstance(humor, list):
        return

    for h_idx, h in enumerate(humor):
        if not isinstance(h, dict):
            continue
        scene_num = h.get("scene_number")
        line = h.get("line", "")
        if not scene_num or not isinstance(line, str) or not line.strip():
            continue

        try:
            s_idx = int(scene_num) - 1
        except (ValueError, TypeError):
            continue
        if s_idx < 0 or s_idx >= len(scenes):
            continue
        scene = scenes[s_idx]
        if not isinstance(scene, dict):
            continue

        vo_seg = scene.get("voiceover_segment", "") or ""
        on_screen = scene.get("on_screen_text", "") or ""
        narrator = scene.get("narrator_script", "") or ""

        # Extract humor keywords (>3 chars)
        humor_words = {
            wd.strip(".,!?:;\"'").lower()
            for wd in line.split()
            if len(wd.strip(".,!?:;\"'")) > 3
        }
        if not humor_words:
            continue

        vo_plain = _strip_tags(vo_seg).lower()
        osd_plain = on_screen.lower()

        vo_hits = sum(1 for hw in humor_words if hw in vo_plain)
        osd_hits = sum(1 for hw in humor_words if hw in osd_plain)
        surfaced = (vo_hits >= 2) or (osd_hits >= 2)

        # Turn-word check (same as _surface_humor_to_vo)
        turn_words = _extract_turn_words(line)
        if surfaced and turn_words:
            turn_in_vo = any(tw in vo_plain for tw in turn_words)
            turn_in_osd = any(tw in osd_plain for tw in turn_words)
            if not turn_in_vo and not turn_in_osd:
                surfaced = False

        if surfaced:
            continue  # humor survived truncation

        # Humor lost — attempt rescue: replace narrator with humor first sentence
        humor_sentences = re.split(r'(?<=[.!?])\s+', line.strip())
        humor_first = humor_sentences[0].rstrip(".,!?;:")
        humor_first_words = humor_first.split()

        dur = scene.get("duration_seconds", 2.0)
        try:
            dur_f = float(dur)
        except (ValueError, TypeError):
            dur_f = 2.0
        max_w = _max_words_for_duration(dur_f)

        if len(humor_first_words) <= max_w:
            # Replace narrator with humor first sentence
            scene["narrator_script"] = f"{humor_first}."
            tag_match = re.match(r'\[[\w\s]+\]', vo_seg.strip()) if vo_seg.strip() else None
            leading_tag = tag_match.group(0) if tag_match else "[whispers]"
            scene["voiceover_segment"] = f"{leading_tag} {humor_first}."
            w.append(AutoFixWarning(
                f"scenes[{s_idx}].narrator_script",
                f"Humor RESCUE: replaced truncated VO with humor line: '{humor_first[:50]}.'"
            ))
        else:
            # Can't restore — HIGH severity warning
            w.append(AutoFixWarning(
                f"humor[{h_idx}]",
                f"[HIGH] Humor lost after truncation — cannot fit in Scene {scene_num} "
                f"({len(humor_first_words)}w > {max_w}w): '{line[:60]}'"
            ))


# Dangling words for standalone strip (broader than truncation-only set)
_DANGLING_ENDINGS = {
    # Articles & determiners (NOT "that" — often a pronoun object: "Did you hear that?")
    "a", "an", "the", "this", "these", "those",
    # Prepositions
    "of", "in", "on", "at", "to", "for", "by", "with", "from",
    "about", "into", "through", "between", "under", "over", "like",
    # Conjunctions
    "and", "or", "but", "nor", "yet", "so",
    # Linking/auxiliary verbs
    "is", "are", "was", "were", "be", "been",
    "has", "have", "had", "do", "does",
    # Modal verbs
    "would", "could", "should", "can", "may", "might", "will",
    # Possessives
    "my", "your", "his", "her", "its", "our", "their",
}

# Transitive verbs that expect an object — semantic truncation flag
_TRANSITIVE_VERBS = {
    "asked", "smells", "made", "built", "found", "gave", "took", "saw",
    "feels", "looks", "sounds", "needs", "wants", "gets", "keeps",
    "leaves", "brings", "holds", "sends", "tells", "shows", "makes",
    "takes", "gives", "knows", "sees", "hears", "means", "turns",
    # Sensory verbs (common VO truncation targets)
    "tastes", "watches", "reaches", "touches", "covers", "fills",
    "catches", "remembers", "measures", "carries", "produces",
}


def _fix_dangling_narrator_endings(d: dict, scenes: list, w: list) -> None:
    """Strip dangling prepositions/articles from ALL narrator_scripts, regardless of word count."""
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        narrator = scene.get("narrator_script", "")
        if not isinstance(narrator, str) or not narrator.strip():
            continue

        words = narrator.strip().split()
        if len(words) < 2:
            continue

        last_word = words[-1].rstrip(".,!?;:")
        if last_word.lower() not in _DANGLING_ENDINGS:
            continue

        # Strip the dangling word
        original = narrator
        kept = words[:-1]
        while len(kept) > 1 and kept[-1].rstrip(".,!?;:").lower() in _DANGLING_ENDINGS:
            kept.pop()
        fixed = " ".join(kept)
        if fixed and fixed[-1] not in ".!?":
            fixed = fixed.rstrip(",;:—–-") + "."
        scene["narrator_script"] = fixed

        # Also fix voiceover_segment
        vo_seg = scene.get("voiceover_segment", "")
        if isinstance(vo_seg, str) and vo_seg.strip() and vo_seg.strip() != "[silence]":
            tag_match = re.match(r'\[[\w\s]+\]', vo_seg.strip())
            leading_tag = tag_match.group(0) if tag_match else "[whispers]"
            scene["voiceover_segment"] = f"{leading_tag} {fixed}"

        sn = scene.get("scene_number", i + 1)
        w.append(AutoFixWarning(
            f"scenes[{sn}].narrator_script",
            f"Dangling '{last_word}' stripped: '{original}' → '{fixed}'",
        ))


def _flag_semantic_truncation(d: dict, scenes: list, w: list) -> None:
    """Flag VO segments that end with a transitive verb (semantic truncation).

    Heuristic: if narrator_script has ≤5 words and ends with a transitive verb,
    it's likely been truncated to lose its object. Flag as warning for review.
    Also catches 1-word transitive verbs ("Smells.", "Tastes.") — always truncated.
    """
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        narrator = scene.get("narrator_script", "")
        if not isinstance(narrator, str) or not narrator.strip():
            continue

        words = narrator.strip().split()
        if len(words) > 5:
            continue

        # 1-word transitive verb = always truncated (missing object)
        if len(words) == 1:
            only_word = words[0].rstrip(".,!?;:").lower()
            if only_word in _TRANSITIVE_VERBS:
                sn = scene.get("scene_number", i + 1)
                w.append(AutoFixWarning(
                    f"scenes[{sn}].narrator_script",
                    f"Lone transitive verb: '{narrator}' — missing object (truncated VO)",
                ))
            continue

        last_word = words[-1].rstrip(".,!?;:").lower()
        if last_word in _TRANSITIVE_VERBS:
            sn = scene.get("scene_number", i + 1)
            w.append(AutoFixWarning(
                f"scenes[{sn}].narrator_script",
                f"Possible semantic truncation: '{narrator}' ends with transitive verb '{last_word}' — missing object?",
            ))


def _fix_warning_line_format_rotation(d: dict, scenes: list, w: list) -> None:
    """Rotate warning_line away from Format A if Gemini defaults to it.

    BUG 4: Gemini locks to Format A ("Don't [action] the [element].") 100% of the time.
    This fix deterministically rotates to B/C/D/F using concept-hash.
    """
    wl = d.get("warning_line", "")
    if not isinstance(wl, str) or not wl.strip():
        return

    stripped = _strip_tags(wl)

    # Only fix Format A (the locked default)
    m = re.match(r"^don['\u2019]t\s+(\w+)\s+the\s+(\w+)", stripped, re.IGNORECASE)
    if not m:
        return  # Not Format A — already diverse

    action = m.group(1).lower()
    element = m.group(2).lower()

    # Concept-hash picks target format (B, C, D, F — never back to A)
    h = _concept_hash(d)
    targets = ["B", "C", "D", "F"]
    target = targets[h % len(targets)]

    if target == "B":
        new_wl = f"{action.capitalize()} the {element}. I dare you."
    elif target == "C":
        new_wl = f"The architect says: nobody {action} the {element}."
    elif target == "D":
        verb_s = _CONSEQUENCE_VERBS_LIST[h % len(_CONSEQUENCE_VERBS_LIST)]
        # Plural elements (walls, columns, stairs) need base verb form
        # Exclude singular nouns ending in "s" (buttress, apse, etc.)
        _SINGULAR_S = {"buttress", "apse", "glass", "gas", "recess", "truss", "compass"}
        is_plural = element.endswith("s") and element.lower() not in _SINGULAR_S
        if is_plural:
            # De-conjugate 3rd person: "watches"→"watch" (-es), "breathes"→"breathe" (-s)
            if verb_s.endswith(("ches", "shes", "xes", "zes", "sses")):
                verb = verb_s[:-2]
            else:
                verb = verb_s[:-1] if verb_s.endswith("s") else verb_s
        else:
            verb = verb_s
        new_wl = f"The {element} {verb}."
    else:  # F
        new_wl = f"Nobody warns you about the {element}."

    d["warning_line"] = new_wl
    w.append(AutoFixWarning("warning_line",
        f"Format rotation A→{target}: '{stripped[:40]}' → '{new_wl}'"))


def _fix_title_default_rotation(d: dict, w: list) -> None:
    """If title is FOOD_BUILD, swap with first non-FOOD_BUILD variant.

    BUG 6: Gemini locks to FOOD_BUILD ("I [verb]ed a [structure]...") 91% of the time.
    This fix promotes a non-FOOD_BUILD variant to title position.
    """
    yt = d.get("youtube")
    if not isinstance(yt, dict):
        return

    variants = yt.get("title_variants", [])
    if not isinstance(variants, list) or len(variants) < 2:
        return

    title = yt.get("title", "")
    if not isinstance(title, str):
        return

    # Only fix if current title matches FOOD_BUILD pattern
    if not _FOOD_BUILD_RE.match(title.strip()):
        return

    # Find first non-FOOD_BUILD variant
    for i, v in enumerate(variants):
        if i == 0 or not isinstance(v, str):
            continue
        if not _FOOD_BUILD_RE.match(v.strip()):
            old_title = title
            yt["title"] = v
            variants[0], variants[i] = variants[i], variants[0]
            w.append(AutoFixWarning("youtube.title",
                f"Title rotation FOOD_BUILD→other: '{old_title[:35]}' → '{v[:35]}'"))
            return


def _fix_controversy_rotation(d: dict, w: list) -> None:
    """Rotate controversy away from THE_PHYSICS if it's the default lock.

    BUG 9: Gemini locks to THE_PHYSICS 73% of the time because all structures
    have physics properties. This fix rotates to other techniques using concept-hash.
    """
    cs = d.get("controversy_seed")
    if not isinstance(cs, dict):
        return

    technique = cs.get("technique", "")
    if not isinstance(technique, str) or technique.strip() != "THE_PHYSICS":
        return  # Not locked

    h = _concept_hash(d)
    new_tech = _CONTROVERSY_ROTATION[h % len(_CONTROVERSY_ROTATION)]
    cs["technique"] = new_tech
    w.append(AutoFixWarning("controversy_seed.technique",
        f"Controversy rotation: THE_PHYSICS → {new_tech}"))


_ONE_MORE_PATTERN = re.compile(r"^One\s+more\s+\w+", re.IGNORECASE)

_CB_ALTERNATIVES = [
    "Wait for it.",       # 3 words — fits 1.5s scenes
    "Watch the {food}.",  # 3 words
    "Almost there.",      # 2 words
    "Not yet.",           # 2 words
    "Keep watching.",     # 2 words
]

_IDENTITY_PATTERN = re.compile(
    r"^(Real|True|Only|Every)\s+(architects?|chefs?|engineers?|bakers?|foodies?)\b",
    re.IGNORECASE,
)

_ST_ALTERNATIVES = [
    "Tag someone who needs to see this.",
    "This changes everything about {food}.",
    "Send this to a {food} lover.",
    "Nobody expected {element} to look like this.",
    "Would you eat this?",
]


def _fix_completion_bait_rotation(d: dict, w: list) -> None:
    """Rotate completion_bait.vo_trigger away from 'One more [noun]' lock.
    Also creates missing completion_bait object with sensible defaults.

    Gemini defaults to 'One more slice/layer/piece' — deterministic rotation
    via concept-hash selects from 5 alternatives.
    """
    cb = d.get("completion_bait")
    h = _concept_hash(d)
    food = _get_food_name(d) or "this"
    element = _get_subject(d) or "inside"

    if not isinstance(cb, dict):
        # Missing entirely — create from scratch
        scenes = d.get("scenes", [])
        ms_scene = None
        for s in scenes:
            if isinstance(s, dict) and isinstance(s.get("money_shot"), dict) and s["money_shot"].get("is_money_shot"):
                ms_scene = s.get("scene_number")
                break
        bait_scene = max(1, (ms_scene or 5) - 2)
        template = _CB_ALTERNATIVES[h % len(_CB_ALTERNATIVES)]
        vo_trigger = template.format(food=food, element=element)
        d["completion_bait"] = {
            "scene_number": bait_scene,
            "technique": "VO_PROMISE",
            "vo_trigger": vo_trigger,
            "resolution_scene": ms_scene or bait_scene + 2,
        }
        w.append(AutoFixWarning(
            "completion_bait",
            f"Auto-created missing completion_bait at Scene {bait_scene}: '{vo_trigger}'",
        ))
        return

    vo_trigger = cb.get("vo_trigger", "")
    # Treat tag-only triggers as empty ("[silence]", "[pause]", etc.)
    _TAG_ONLY = re.compile(r'^\s*(\[[\w\s]+\]\s*)+$')
    is_empty = (
        not isinstance(vo_trigger, str)
        or not vo_trigger.strip()
        or _TAG_ONLY.match(vo_trigger)
    )
    if is_empty:
        # Present but empty/garbage vo_trigger — fill it
        template = _CB_ALTERNATIVES[h % len(_CB_ALTERNATIVES)]
        cb["vo_trigger"] = template.format(food=food, element=element)
        w.append(AutoFixWarning(
            "completion_bait.vo_trigger",
            f"Auto-filled empty vo_trigger: '{cb['vo_trigger']}'",
        ))
        return

    if not _ONE_MORE_PATTERN.match(vo_trigger.strip()):
        return  # Not locked — already diverse

    template = _CB_ALTERNATIVES[h % len(_CB_ALTERNATIVES)]
    new_trigger = template.format(food=food, element=element)
    cb["vo_trigger"] = new_trigger
    w.append(AutoFixWarning(
        "completion_bait.vo_trigger",
        f"Template rotation: '{vo_trigger[:40]}' → '{new_trigger}'",
    ))


def _fix_share_trigger_rotation(d: dict, w: list) -> None:
    """Rotate share_trigger away from '[qualifier] + [identity group]' lock.

    Gemini defaults to 'Real architects would...' / 'Only chefs understand...' —
    deterministic rotation via concept-hash selects from 5 alternatives.
    """
    eng = d.get("engagement")
    if not isinstance(eng, dict):
        return
    st = eng.get("share_trigger")
    if isinstance(st, dict):
        text = st.get("text", "")
    elif isinstance(st, str):
        text = st
    else:
        return

    if not isinstance(text, str) or not text.strip():
        return
    if not _IDENTITY_PATTERN.match(text.strip()):
        return  # Not locked

    h = _concept_hash(d)
    food = _get_food_name(d) or "food"
    element = _get_subject(d) or "this"

    template = _ST_ALTERNATIVES[h % len(_ST_ALTERNATIVES)]
    new_text = template.format(food=food, element=element)

    if isinstance(st, dict):
        st["text"] = new_text
    else:
        eng["share_trigger"] = new_text

    w.append(AutoFixWarning(
        "engagement.share_trigger",
        f"Template rotation: '{text[:40]}' → '{new_text}'",
    ))


_SERIES_HOOK_FALLBACK_TECHNIQUES = [
    "UNANSWERED_QUESTION",
    "COLLECTION_TRIGGER",
    "ARCHITECT_TEASE",
    "WORLD_REFERENCE",
]

_SERIES_HOOK_FALLBACK_ELEMENTS = {
    "UNANSWERED_QUESTION": "What else was built?",
    "COLLECTION_TRIGGER": "Collection — more to explore",
    "ARCHITECT_TEASE": "Blueprints of a different food structure",
    "WORLD_REFERENCE": "Brief VO mention of another structure nearby",
}


def _load_series_hooks_for_channel(channel_id: str):
    """Load channel-specific series hook techniques and elements from persona.json."""
    try:
        from app.utils.prompt_loader import load_persona
        persona = load_persona(channel_id)
        sh = persona.get("series_hooks", {})
        types = sh.get("types", {})
        if types:
            techniques = list(types.keys())
            elements = {k: v.get("description", v.get("example", "")) if isinstance(v, dict) else str(v) for k, v in types.items()}
            return techniques, elements
    except Exception:
        pass
    return _SERIES_HOOK_FALLBACK_TECHNIQUES, _SERIES_HOOK_FALLBACK_ELEMENTS


def _fix_series_hook(d: dict, w: list, channel_id: str = "glaze_city") -> None:
    """Ensure series_identity.series_hook exists AND rotate technique via concept hash.

    Gemini template-locks to UNANSWERED_QUESTION — deterministic rotation
    via concept-hash selects from 4 techniques. Channel-aware via persona.json.
    """
    si = d.get("series_identity")
    if not isinstance(si, dict):
        return

    techniques, elements = _load_series_hooks_for_channel(channel_id)

    h = _concept_hash(d)
    target_tech = techniques[h % len(techniques)]

    sh = si.get("series_hook")
    if not isinstance(sh, dict) or not sh.get("technique"):
        # Missing entirely — create with rotated technique
        si["series_hook"] = {
            "technique": target_tech,
            "element": elements.get(target_tech, ""),
            "placement": "Last 2 seconds",
        }
        w.append(AutoFixWarning(
            "series_identity.series_hook",
            f"Auto-filled missing series_hook → {target_tech}",
        ))
        return

    current = sh.get("technique", "")
    if current == target_tech:
        return  # already the right technique for this concept

    old_tech = current
    sh["technique"] = target_tech
    sh["element"] = elements.get(target_tech, sh.get("element", ""))
    w.append(AutoFixWarning(
        "series_identity.series_hook",
        f"Series hook rotation: {old_tech} → {target_tech}",
    ))


def _fix_grey_dominant_color(d: dict, scenes: list, w: list) -> None:
    """Replace grey/gray dominant_color in food-dominant scenes with food's primary color."""
    food_identity = d.get("food_identity")
    if not isinstance(food_identity, dict):
        return
    color_kws = food_identity.get("color_keywords", [])
    if not isinstance(color_kws, list) or not color_kws:
        return
    # Use first color keyword as replacement (e.g. "golden amber", "baked brown")
    replacement_color = color_kws[0] if isinstance(color_kws[0], str) else "golden brown"

    # Check if food is cold — skip fix for frozen foods
    atmos = food_identity.get("atmosphere", "")
    if isinstance(atmos, str) and any(w_word in atmos.lower() for w_word in ("cold", "frozen", "icy", "glacial")):
        return

    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        if scene.get("food_visual_ratio") != "FOOD_DOMINANT":
            continue
        g2 = scene.get("gen2_visual_params")
        if not isinstance(g2, dict):
            continue
        dom = g2.get("dominant_color", "")
        if not isinstance(dom, str):
            continue
        dom_lower = dom.lower()
        if any(grey_word in dom_lower for grey_word in _GREY_COLOR_WORDS):
            old_val = dom
            g2["dominant_color"] = replacement_color
            sn = scene.get("scene_number", "?")
            w.append(AutoFixWarning(
                f"scenes[S{sn}].gen2_visual_params.dominant_color",
                f"Grey '{old_val}' → '{replacement_color}' (appetite-suppressing color in food scene)"))


_WARM_COLOR_WORDS = {
    "golden", "amber", "brown", "honey", "butter", "caramel",
    "copper", "bronze", "toffee", "cinnamon", "maple", "ochre",
    "burnt", "russet", "sienna", "tan", "wheat", "biscuit",
}

_WARM_LIGHTING_PRESETS = {
    "MORNING_GOLDEN", "SUNSET_DRAMATIC", "CANDLELIT_WARM",
    "AFTERNOON_WARM",
}

_COLD_LIGHTING_ALTERNATIVES = [
    "MOONLIT_SILVER",
    "BLUE_HOUR",
    "OVERCAST_SOFT",
    "TWILIGHT_PURPLE",
    # NIGHT_NEON excluded — it's a Gemini default we rotate AWAY from
]


# All valid lighting presets for rotation
_ALL_LIGHTING_PRESETS = [
    "MORNING_GOLDEN", "SUNSET_DRAMATIC", "BLUE_HOUR", "NIGHT_NEON",
    "TWILIGHT_PURPLE", "OVERCAST_SOFT", "CANDLELIT_WARM", "MOONLIT_SILVER",
]

# Presets Gemini over-uses (template-lock targets)
_DEFAULT_LIGHTING_PRESETS = {
    "NIGHT_NEON", "MORNING_GOLDEN",
}


def _fix_lighting_rotation(d: dict, w: list) -> None:
    """Rotate lighting_master.preset away from Gemini defaults via concept_hash.

    Gemini template-locks to NIGHT_NEON (industrial/cold) or MORNING_GOLDEN (warm).
    Different concepts should get different lighting for batch variety.
    Runs BEFORE _fix_warm_food_warm_light_collision (which handles warm food specifically).
    """
    light = d.get("lighting_master")
    if not isinstance(light, dict):
        return
    preset = light.get("preset", "")
    if not isinstance(preset, str):
        return
    if preset.upper() not in _DEFAULT_LIGHTING_PRESETS:
        return  # Already non-default — skip

    h = _concept_hash(d)
    target = _ALL_LIGHTING_PRESETS[h % len(_ALL_LIGHTING_PRESETS)]
    if target == preset.upper():
        # Hash landed on same preset — pick next one
        target = _ALL_LIGHTING_PRESETS[(h + 1) % len(_ALL_LIGHTING_PRESETS)]

    old = preset
    light["preset"] = target
    w.append(AutoFixWarning(
        "lighting_master.preset",
        f"Lighting rotation: '{old}' → '{target}' (anti-default lock)",
    ))


def _fix_warm_food_warm_light_collision(d: dict, w: list) -> None:
    """Force cold/neutral lighting when food color palette is warm.

    Warm food + warm light = visual monotony (golden-on-golden).
    If food has 2+ warm color_keywords AND lighting is warm → rotate to cold.
    """
    fi = d.get("food_identity")
    if not isinstance(fi, dict):
        return
    color_kws = fi.get("color_keywords", [])
    if not isinstance(color_kws, list):
        return

    warm_count = sum(
        1 for kw in color_kws
        if isinstance(kw, str) and any(wc in kw.lower() for wc in _WARM_COLOR_WORDS)
    )
    if warm_count < 2:
        return  # Not enough warm colors to trigger

    light = d.get("lighting_master")
    if not isinstance(light, dict):
        return
    preset = light.get("preset", "")
    if not isinstance(preset, str) or preset.upper() not in _WARM_LIGHTING_PRESETS:
        return  # Already cold/neutral

    h = _concept_hash(d)
    new_preset = _COLD_LIGHTING_ALTERNATIVES[h % len(_COLD_LIGHTING_ALTERNATIVES)]
    old_preset = preset
    light["preset"] = new_preset
    w.append(AutoFixWarning(
        "lighting_master.preset",
        f"Warm food + warm light collision: '{old_preset}' → '{new_preset}' (visual contrast)",
    ))


_LOOP_TECHNIQUES = [
    "FOG_GATE", "OBJECT_WIPE", "MOTION_MATCH",
    "PARTICLE_DISSOLVE", "TEXTURE_MORPH", "ZOOM_TUNNEL", "COLOR_SHIFT",
]


def _fix_required_top_level_fields(d: dict, scenes: list, w: list) -> None:
    """Create missing required top-level fields that would crash the pipeline.

    Fields: loop, first_frame_composition, temperature_contrast.
    (completion_bait is handled by _fix_completion_bait_rotation)
    """
    food = _get_food_name(d) or "food"
    subject = _get_subject(d) or "structure"
    h = _concept_hash(d)

    # --- loop ---
    if not isinstance(d.get("loop"), dict):
        tech = _LOOP_TECHNIQUES[h % len(_LOOP_TECHNIQUES)]
        d["loop"] = {
            "technique": tech,
            "scene_n_exit": f"{food.capitalize()} texture fills frame completely",
            "scene_1_entry": f"Same texture pulls back to reveal {subject}",
            "bridge_sfx": "Ambient hum swelling into silence",
        }
        w.append(AutoFixWarning("loop", f"Auto-created missing loop → {tech}"))

    # --- first_frame_composition ---
    if not isinstance(d.get("first_frame_composition"), dict):
        # Also check if Scene 1 has it nested
        s1_ffc = None
        if scenes and isinstance(scenes[0], dict):
            s1_ffc = scenes[0].get("first_frame_composition")
        if isinstance(s1_ffc, dict):
            d["first_frame_composition"] = s1_ffc
            w.append(AutoFixWarning("first_frame_composition",
                "Promoted Scene 1 first_frame_composition to top level"))
        else:
            d["first_frame_composition"] = {
                "dominant_subject": f"Macro {food} detail against {subject} backdrop",
                "silhouette_clarity": "HIGH",
                "pareidolia_element": f"{food.capitalize()} texture forming architectural shapes",
            }
            w.append(AutoFixWarning("first_frame_composition",
                "Auto-created missing first_frame_composition"))

    # --- temperature_contrast ---
    if not isinstance(d.get("temperature_contrast"), dict):
        fi = d.get("food_identity", {})
        warm_foods = {"croissant", "waffle", "pancake", "donut", "bread", "pie",
                      "cookie", "pretzel", "baklava", "churro", "bun", "pastry",
                      "pizza", "soup", "coffee", "chocolate", "caramel", "honey",
                      "honeycomb", "cinnamon", "toffee", "fudge"}
        food_lower = food.lower()
        is_warm_food = any(wf in food_lower for wf in warm_foods)
        subj_temp = "WARM" if is_warm_food else "COLD"
        bg_temp = "COLD" if is_warm_food else "WARM"
        d["temperature_contrast"] = {
            "subject_temp": subj_temp,
            "background_temp": bg_temp,
        }
        w.append(AutoFixWarning("temperature_contrast",
            f"Auto-created missing temperature_contrast: subject={subj_temp}, bg={bg_temp}"))


def _fix_consecutive_warm_backgrounds(d: dict, scenes: list, w: list) -> None:
    """Audit consecutive WARM/NEUTRAL background_temp and inject COLD to break runs.

    Rules:
    - If two adjacent scenes both have background_temp in {WARM, NEUTRAL}: fix the second
    - Exception: skip if both scenes have SP ≥ 8 AND narrative_purpose suggests FOOD_DOMINANT
      (macro harmony in high-SP food scenes is intentional)
    - Fix: set second scene's background_temp to COLD
    - Also inject a cold keyword into image_prompt if no cold terms present
    """
    _WARM_TEMPS = {"WARM", "NEUTRAL"}
    _COLD_TERMS = {"cold", "cool", "ice", "frozen", "icy", "frost", "snow", "steel", "blue",
                   "concrete", "marble", "stone", "shadow", "night", "dark", "neon"}
    _FOOD_DOMINANT_PURPOSES = {"DETAIL", "FEATURE", "FEATURE_HIGHLIGHT"}

    for i in range(len(scenes) - 1):
        s1, s2 = scenes[i], scenes[i + 1]
        if not isinstance(s1, dict) or not isinstance(s2, dict):
            continue

        bg1 = (s1.get("background_temp") or "").upper()
        bg2 = (s2.get("background_temp") or "").upper()

        if bg1 not in _WARM_TEMPS or bg2 not in _WARM_TEMPS:
            continue

        # Exception: high SP + food dominant (macro harmony)
        sp1 = s1.get("sensory_pressure", 0)
        sp2 = s2.get("sensory_pressure", 0)
        try:
            sp1, sp2 = int(sp1), int(sp2)
        except (ValueError, TypeError):
            sp1, sp2 = 0, 0
        purpose2 = (s2.get("narrative_purpose") or "").upper()
        if sp1 >= 8 and sp2 >= 8 and purpose2 in _FOOD_DOMINANT_PURPOSES:
            continue

        # Fix: set second scene to COLD
        s2["background_temp"] = "COLD"
        s2_sn = s2.get("scene_number", i + 2)
        w.append(AutoFixWarning(
            f"scenes[S{s2_sn}].background_temp",
            f"Consecutive warm backgrounds (S{s1.get('scene_number', i+1)}={bg1}, S{s2_sn}={bg2})"
            f" — set S{s2_sn} to COLD",
        ))

        # Inject cold keyword into image_prompt if missing
        img_prompt = s2.get("image_prompt", "")
        if isinstance(img_prompt, str) and img_prompt.strip():
            img_words = set(img_prompt.lower().split())
            if not img_words & _COLD_TERMS:
                s2["image_prompt"] = f"{img_prompt.rstrip().rstrip('.')}. Cool steel undertones."
                w.append(AutoFixWarning(
                    f"scenes[S{s2_sn}].image_prompt",
                    f"Injected cold term into image_prompt for temperature contrast",
                ))


def _fix_energy_floor(d: dict, scenes: list, w: list) -> None:
    """Fix consecutive LOW energy scenes and enforce max 1 LOW per video.

    Rules:
    - MAX 1 LOW scene per video (money_shot/ASMR gets the slot)
    - NO consecutive LOW scenes — if found, raise the first to MEDIUM
    - Scene before money_shot must be MEDIUM or higher
    """
    if not scenes:
        return

    # Find money_shot scene number
    money_shot_sn = None
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        ms = scene.get("money_shot")
        if isinstance(ms, dict) and ms.get("is_money_shot"):
            money_shot_sn = scene.get("scene_number")
            break

    # Pass 1: Fix consecutive LOW — raise the FIRST one to MEDIUM
    for i in range(len(scenes) - 1):
        cur = scenes[i]
        nxt = scenes[i + 1]
        if not isinstance(cur, dict) or not isinstance(nxt, dict):
            continue
        if cur.get("energy_level") == "LOW" and nxt.get("energy_level") == "LOW":
            cur_sn = cur.get("scene_number", "?")
            cur["energy_level"] = "MEDIUM"
            w.append(AutoFixWarning(
                f"scenes[S{cur_sn}].energy_level",
                f"Consecutive LOW (S{cur_sn}→S{nxt.get('scene_number', '?')})"
                f" — raised S{cur_sn} to MEDIUM",
            ))

    # Pass 2: Enforce max 1 LOW per video — keep only the money_shot LOW
    low_scenes = [
        s for s in scenes
        if isinstance(s, dict) and s.get("energy_level") == "LOW"
    ]
    if len(low_scenes) > 1:
        for scene in low_scenes:
            sn = scene.get("scene_number")
            if sn != money_shot_sn:
                scene["energy_level"] = "MEDIUM"
                w.append(AutoFixWarning(
                    f"scenes[S{sn}].energy_level",
                    f"Multiple LOW scenes — raised S{sn} to MEDIUM (only money_shot keeps LOW)",
                ))

    # Pass 3: Scene before money_shot must be MEDIUM or higher
    if money_shot_sn is not None:
        for i, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                continue
            if scene.get("scene_number") == money_shot_sn and i > 0:
                prev = scenes[i - 1]
                if isinstance(prev, dict) and prev.get("energy_level") == "LOW":
                    prev_sn = prev.get("scene_number", "?")
                    prev["energy_level"] = "MEDIUM"
                    w.append(AutoFixWarning(
                        f"scenes[S{prev_sn}].energy_level",
                        f"Scene before money_shot (S{money_shot_sn}) was LOW"
                        f" — raised to MEDIUM for contrast ramp",
                    ))
                break

    # Pass 4: Break 3+ consecutive same energy (MEDIUM or HIGH)
    for i in range(len(scenes) - 2):
        s1, s2, s3 = scenes[i], scenes[i + 1], scenes[i + 2]
        if not all(isinstance(s, dict) for s in (s1, s2, s3)):
            continue
        e1 = s1.get("energy_level")
        e2 = s2.get("energy_level")
        e3 = s3.get("energy_level")
        if e1 == e2 == e3 and e1 in ("MEDIUM", "HIGH"):
            mid = scenes[i + 1]
            mid_sn = mid.get("scene_number", i + 2)
            if e1 == "MEDIUM":
                mid["energy_level"] = "HIGH"
                w.append(AutoFixWarning(
                    f"scenes[S{mid_sn}].energy_level",
                    f"3x consecutive MEDIUM (S{s1.get('scene_number', '?')}-S{s3.get('scene_number', '?')})"
                    f" — pumped S{mid_sn} to HIGH",
                ))
            else:  # HIGH
                mid["energy_level"] = "MEDIUM"
                w.append(AutoFixWarning(
                    f"scenes[S{mid_sn}].energy_level",
                    f"3x consecutive HIGH (S{s1.get('scene_number', '?')}-S{s3.get('scene_number', '?')})"
                    f" — dropped S{mid_sn} to MEDIUM for valley",
                ))


def _fix_hook_first_words_sync(d: dict, scenes: list, w: list) -> None:
    """Sync hook.first_words with scenes[0].narrator_script.

    Rules:
    - first_words must be the opening words of scenes[0].narrator_script
    - If they diverge, fix narrator_script to start with first_words
    """
    hook = d.get("hook")
    if not isinstance(hook, dict) or not scenes:
        return
    first_words = hook.get("first_words", "")
    if not isinstance(first_words, str) or not first_words.strip():
        return

    scene1 = scenes[0]
    if not isinstance(scene1, dict):
        return
    narrator = scene1.get("narrator_script", "")
    if not isinstance(narrator, str) or not narrator.strip():
        return

    fw_clean = first_words.strip().rstrip(".")
    narrator_clean = narrator.strip()

    # Check if narrator_script starts with first_words (case-insensitive)
    if not narrator_clean.lower().startswith(fw_clean.lower()):
        # Narrator may have been modified by prior fixes (thermal prefix, word count).
        # Narrator is authoritative — update hook.first_words to match narrator start.
        narrator_words = narrator_clean.split()
        fw_word_count = len(first_words.strip().split())
        new_fw = " ".join(narrator_words[:fw_word_count])
        # Ensure ends with punctuation
        if new_fw and new_fw[-1] not in ".!?":
            new_fw = new_fw.rstrip(",;:—–-") + "."
        hook["first_words"] = new_fw
        w.append(AutoFixWarning(
            "hook.first_words",
            f"Hook sync: updated first_words '{first_words}' → '{new_fw}'"
            f" (narrator is authoritative after thermal/truncation fixes)",
        ))

    # Sync complete_hook_vo with scene[0].voiceover_segment
    scene1_vo = scene1.get("voiceover_segment", "")
    old_complete = hook.get("complete_hook_vo", "")
    if scene1_vo and old_complete != scene1_vo:
        hook["complete_hook_vo"] = scene1_vo
        w.append(AutoFixWarning(
            "hook.complete_hook_vo",
            f"Synced with scene[0].voiceover_segment: '{scene1_vo[:60]}'",
        ))


def _fix_money_shot_saliva_trigger(d: dict, scenes: list, w: list) -> None:
    """Inject a saliva trigger word into money_shot.still_image_description.

    Craving anchor: the money_shot description MUST contain a physical action word
    (stretching, dripping, cracking, melting, etc.) to trigger salivation response.
    If missing, append a texture-appropriate trigger phrase.
    """
    _SALIVA_TRIGGER_WORDS: set = {
        "stretching", "stretch", "dripping", "drip", "drips",
        "cracking", "crack", "cracks", "breaking", "break", "breaks", "snapping", "snap",
        "melting", "melt", "melts", "pouring", "pour", "pours",
        "oozing", "ooze", "oozes", "soaking", "soak", "absorbing", "absorbed",
        "bubbling", "bubble", "sizzling", "sizzle", "pulling", "pull",
        "tearing", "tear", "splitting", "split", "fracturing", "fracture",
    }

    # Texture → best saliva trigger phrase to append
    _TEXTURE_TRIGGERS: dict = {
        "crispy": "with cracks splitting across the surface",
        "crunchy": "with fractures cracking through layers",
        "brittle": "with pieces snapping apart",
        "creamy": "with filling oozing from the center",
        "chewy": "with strands stretching between halves",
        "smooth": "with glaze melting down the surface",
        "gooey": "with filling dripping in thick strands",
        "silky": "with liquid pouring over the edge",
        "crunchy-wet": "with juice dripping through the crust",
    }

    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        ms = scene.get("money_shot")
        if not isinstance(ms, dict) or not ms.get("is_money_shot"):
            continue

        desc = ms.get("still_image_description", "")
        if not isinstance(desc, str) or not desc.strip():
            continue

        desc_lower = desc.lower()
        if any(re.search(r'\b' + re.escape(t) + r'\b', desc_lower) for t in _SALIVA_TRIGGER_WORDS):
            return  # Already has trigger (word-boundary match, synced with validator)

        texture = _get_texture_group(d)
        trigger_phrase = _TEXTURE_TRIGGERS.get(texture, "with filling oozing from the center")
        new_desc = f"{desc.rstrip('., ')} {trigger_phrase}"
        ms["still_image_description"] = new_desc
        w.append(AutoFixWarning(
            f"scenes[{scene.get('scene_number', '?')}].money_shot.still_image_description",
            f"Injected saliva trigger: '{trigger_phrase}'",
        ))
        return  # Only one money_shot


def _fix_olfactory_channel_injection(d: dict, scenes: list, w: list) -> None:
    """Inject olfactory word when 4-channel audit finds ZERO olfactory content.

    Gemini 3 Pro guide: STOP-LEVEL verification instructions are unreliable.
    Deterministic fallback: inject "Smells like [food]." into a suitable scene.
    Only fires when NO olfactory stem found after all prior VO fixes.
    """
    # Scan all VO for olfactory stems
    all_vo = ""
    for s in scenes:
        if isinstance(s, dict):
            vo = s.get("voiceover_segment", "")
            if isinstance(vo, str) and vo.strip() != "[silence]":
                all_vo += " " + vo.lower()
    clean = re.sub(r'\[[\w\s]+\]', '', all_vo)

    if any(re.search(r'\b' + re.escape(stem), clean) for stem in _OLFACTORY_STEMS):
        return  # Already has olfactory content

    # Build tiered olfactory phrases (3-word, 2-word, 1-word)
    food_name = _get_food_name(d) or "sugar"
    food_words = food_name.lower().split()
    _COLORS = {"red", "blue", "green", "yellow", "white", "black", "brown", "pink", "orange", "purple", "golden"}
    food_word = next((fw for fw in food_words if fw not in _COLORS), food_words[-1])

    # Tiered by word count: try longest first, fall back to shorter
    _PHRASES = [
        (3, f"Smells like {food_word}."),   # 3 words: "Smells like croissant."
        (2, "Sweet air."),                   # 2 words: "Sweet air."
        (1, "Yeast."),                       # 1 word:  "Yeast."
    ]

    # Find target scene: not scene 1, not last 2, not money_shot, not [silence]
    target_idx = None
    chosen_phrase = None
    for need_words, phrase_candidate in _PHRASES:
        for i in range(1, max(len(scenes) - 2, 2)):
            scene = scenes[i] if i < len(scenes) else None
            if not isinstance(scene, dict):
                continue
            ms = scene.get("money_shot")
            if isinstance(ms, dict) and ms.get("is_money_shot"):
                continue
            vo = scene.get("voiceover_segment", "")
            if isinstance(vo, str) and vo.strip() == "[silence]":
                continue
            narrator = scene.get("narrator_script", "")
            if not isinstance(narrator, str):
                continue
            dur = scene.get("duration_seconds", 2.0)
            try:
                dur_f = float(dur)
            except (ValueError, TypeError):
                dur_f = 2.0
            current_words = len(narrator.strip().split()) if narrator.strip() else 0
            max_w = _max_words_for_duration(dur_f)
            if current_words + need_words <= max_w:
                target_idx = i
                chosen_phrase = phrase_candidate
                break
        if target_idx is not None:
            break

    phrase = chosen_phrase
    if target_idx is None:
        w.append(AutoFixWarning(
            "voiceover.sensory_channels",
            "Missing OLFACTORY — no scene has room to inject (flag only)",
        ))
        return

    scene = scenes[target_idx]
    old_narrator = scene.get("narrator_script", "")
    old_vo = scene.get("voiceover_segment", "")

    new_narrator = f"{old_narrator} {phrase}".strip() if old_narrator.strip() else phrase
    scene["narrator_script"] = new_narrator

    # Append phrase to existing VO, preserving all intermediate tags ([pause], etc.)
    if old_vo and old_vo.strip():
        scene["voiceover_segment"] = f"{old_vo.rstrip()} {phrase}"
    else:
        scene["voiceover_segment"] = f"[warm] {new_narrator}"

    sn = scene.get("scene_number", target_idx + 1)
    w.append(AutoFixWarning(
        f"scenes[{target_idx}].narrator_script",
        f"Injected OLFACTORY in Scene {sn}: '{phrase}'",
    ))


def _fix_temporal_channel_injection(d: dict, scenes: list, w: list) -> None:
    """Inject temporal freshness word when 4-channel audit finds ZERO temporal content.

    Temporal freshness = "just made" urgency, active process happening NOW.
    Detected by: "still X-ing", "just X-ed", "fresh", or active-process -ing words.
    """
    _TEMPORAL_PATTERNS_AC = [
        re.compile(r'\bstill\s+\w+ing\b', re.IGNORECASE),
        re.compile(r'\bjust\s+\w+ed\b', re.IGNORECASE),
        re.compile(r'\bjust\s+(?:set|made|cut|lit|split|out)\b', re.IGNORECASE),
        re.compile(r'\bfresh(?:ly)?\b', re.IGNORECASE),
    ]
    _TEMPORAL_ACTIVE = {
        "bubbling", "dripping", "melting", "sizzling", "steaming",
        "oozing", "caramelizing", "crisping", "browning", "toasting",
        "roasting", "baking", "brewing", "boiling", "glazing",
        "crystallizing", "hardening", "setting", "cooling", "rising",
        "frying", "grilling", "smoking", "pouring", "spreading",
    }

    all_vo = ""
    for s in scenes:
        if isinstance(s, dict):
            vo = s.get("voiceover_segment", "")
            if isinstance(vo, str) and vo.strip() != "[silence]":
                all_vo += " " + vo.lower()
    clean = re.sub(r'\[[\w\s]+\]', '', all_vo)

    has_temporal = (
        any(p.search(clean) for p in _TEMPORAL_PATTERNS_AC)
        or any(re.search(r'\b' + re.escape(w) + r'\b', clean) for w in _TEMPORAL_ACTIVE)
    )
    if has_temporal:
        return

    # Tiered phrases (2-word, 1-word)
    _PHRASES = [
        (2, "Still dripping."),
        (1, "Fresh."),
    ]

    target_idx = None
    chosen_phrase = None
    for need_words, phrase_candidate in _PHRASES:
        for i in range(1, max(len(scenes) - 2, 2)):
            scene = scenes[i] if i < len(scenes) else None
            if not isinstance(scene, dict):
                continue
            ms = scene.get("money_shot")
            if isinstance(ms, dict) and ms.get("is_money_shot"):
                continue
            vo = scene.get("voiceover_segment", "")
            if isinstance(vo, str) and vo.strip() == "[silence]":
                continue
            narrator = scene.get("narrator_script", "")
            if not isinstance(narrator, str):
                continue
            dur = scene.get("duration_seconds", 2.0)
            try:
                dur_f = float(dur)
            except (ValueError, TypeError):
                dur_f = 2.0
            current_words = len(narrator.strip().split()) if narrator.strip() else 0
            max_w = _max_words_for_duration(dur_f)
            if current_words + need_words <= max_w:
                target_idx = i
                chosen_phrase = phrase_candidate
                break
        if target_idx is not None:
            break

    if target_idx is None:
        w.append(AutoFixWarning(
            "voiceover.sensory_channels",
            "Missing TEMPORAL FRESHNESS — no scene has room to inject (flag only)",
        ))
        return

    phrase = chosen_phrase
    scene = scenes[target_idx]
    old_narrator = scene.get("narrator_script", "")
    old_vo = scene.get("voiceover_segment", "")

    new_narrator = f"{old_narrator} {phrase}".strip() if old_narrator.strip() else phrase
    scene["narrator_script"] = new_narrator

    # Append phrase to existing VO, preserving all intermediate tags ([pause], etc.)
    if old_vo and old_vo.strip():
        scene["voiceover_segment"] = f"{old_vo.rstrip()} {phrase}"
    else:
        scene["voiceover_segment"] = f"[whispers] {new_narrator}"

    sn = scene.get("scene_number", target_idx + 1)
    w.append(AutoFixWarning(
        f"scenes[{target_idx}].narrator_script",
        f"Injected TEMPORAL in Scene {sn}: '{phrase}'",
    ))


def _fix_tactile_channel_injection(d: dict, scenes: list, w: list) -> None:
    """Inject tactile word when 4-channel audit finds ZERO tactile content.

    Tactile = physical texture sensation the viewer can imagine feeling.
    Detected by: _TACTILE_STEMS word list (sticky, crunchy, gooey, etc.).
    """
    _TACTILE_STEMS: set = {
        "stick", "sticky", "sticking", "sticks",
        "squishy", "rough", "smooth", "soft", "hard", "wet", "dry",
        "gooey", "crispy", "crunchy", "slippery", "gritty",
        "velvety", "silky", "pull", "pulling", "pulls",
        "sink", "sinking", "sinks", "press", "pressing", "presses",
        "squeeze", "squeezing", "crumble", "crumbling", "crumbles",
        "flaky", "elastic", "rubbery", "brittle",
        "stretching", "stretches", "bounce", "bouncing",
    }

    all_vo = ""
    for s in scenes:
        if isinstance(s, dict):
            vo = s.get("voiceover_segment", "")
            if isinstance(vo, str) and vo.strip() != "[silence]":
                all_vo += " " + vo.lower()
    clean = re.sub(r'\[[\w\s]+\]', '', all_vo)

    if any(re.search(r'\b' + re.escape(stem) + r'\b', clean) for stem in _TACTILE_STEMS):
        return  # Already has tactile content

    # Build tiered tactile phrases keyed to food texture
    texture = _get_texture_group(d)
    _TEXTURE_PHRASES: dict = {
        "crispy": [(1, "Crunchy."), (1, "Crispy.")],
        "crunchy": [(1, "Crunchy."), (1, "Crispy.")],
        "brittle": [(1, "Brittle."), (1, "Flaky.")],
        "creamy": [(1, "Smooth."), (1, "Silky.")],
        "chewy": [(1, "Sticky."), (2, "Still pulling.")],
        "smooth": [(1, "Smooth."), (1, "Silky.")],
        "gooey": [(1, "Sticky."), (1, "Gooey.")],
        "silky": [(1, "Silky."), (1, "Smooth.")],
        "crunchy-wet": [(1, "Crunchy."), (1, "Wet.")],
    }
    phrases = _TEXTURE_PHRASES.get(texture, [(1, "Sticky."), (1, "Crunchy.")])

    target_idx = None
    chosen_phrase = None
    for need_words, phrase_candidate in phrases:
        for i in range(1, max(len(scenes) - 2, 2)):
            scene = scenes[i] if i < len(scenes) else None
            if not isinstance(scene, dict):
                continue
            ms = scene.get("money_shot")
            if isinstance(ms, dict) and ms.get("is_money_shot"):
                continue
            vo = scene.get("voiceover_segment", "")
            if isinstance(vo, str) and vo.strip() == "[silence]":
                continue
            narrator = scene.get("narrator_script", "")
            if not isinstance(narrator, str):
                continue
            dur = scene.get("duration_seconds", 2.0)
            try:
                dur_f = float(dur)
            except (ValueError, TypeError):
                dur_f = 2.0
            current_words = len(narrator.strip().split()) if narrator.strip() else 0
            max_w = _max_words_for_duration(dur_f)
            if current_words + need_words <= max_w:
                target_idx = i
                chosen_phrase = phrase_candidate
                break
        if target_idx is not None:
            break

    if target_idx is None:
        w.append(AutoFixWarning(
            "voiceover.sensory_channels",
            "Missing TACTILE — no scene has room to inject (flag only)",
        ))
        return

    phrase = chosen_phrase
    scene = scenes[target_idx]
    old_narrator = scene.get("narrator_script", "")
    old_vo = scene.get("voiceover_segment", "")

    new_narrator = f"{old_narrator} {phrase}".strip() if old_narrator.strip() else phrase
    scene["narrator_script"] = new_narrator

    # Append phrase to existing VO, preserving all intermediate tags ([pause], etc.)
    if old_vo and old_vo.strip():
        scene["voiceover_segment"] = f"{old_vo.rstrip()} {phrase}"
    else:
        scene["voiceover_segment"] = f"[warm] {new_narrator}"

    sn = scene.get("scene_number", target_idx + 1)
    w.append(AutoFixWarning(
        f"scenes[{target_idx}].narrator_script",
        f"Injected TACTILE in Scene {sn}: '{phrase}'",
    ))


# ---------------------------------------------------------------------------
# VO SEGMENT WORD SYNC + BUDGET (v3.6)
# ---------------------------------------------------------------------------

# Empirical TTS rate (seconds per content word) by ElevenLabs delivery style
# v3.10: rates adjusted for native speed 1.05x (divides old rates by 1.05)
_TTS_RATE = {
    "whispers": 0.81,    # 0.85/1.05 — whisper rate at native 1.05x speed
    "drawn out": 0.86,   # 0.90/1.05 — drawn-out rate at native 1.05x speed
    "calm": 0.71,        # 0.75/1.05 — calm rate at native 1.05x speed
    "gentle": 0.67,      # 0.70/1.05 — gentle rate at native 1.05x speed
    "default": 0.62,     # 0.65/1.05 — neutral rate at native 1.05x speed
}


def _rebuild_vo_from_narrator(leading_tags: str, narrator: str, original_tags: list) -> str:
    """Rebuild voiceover_segment from narrator_script + leading tags.

    Keeps first 1-2 emotion/delivery tags, inserts [pause] at sentence
    boundaries (after . ! ?).
    """
    parts = []
    if leading_tags.strip():
        parts.append(leading_tags.strip())
    # Insert [pause] at sentence boundaries inside narrator
    words = narrator.strip().split()
    for word in words:
        parts.append(word)
        if word.rstrip().endswith((".")) and word != words[-1]:
            # Check if original had [pause] — preserve intent
            if any("pause" in t.lower() for t in original_tags):
                parts.append("[pause]")
    return " ".join(parts)


def _fix_voiceover_segment_word_sync(d: dict, scenes: list, w: list) -> None:
    """Ensure voiceover_segment content words match narrator_script.

    narrator_script = clean text (word-count-limited).
    voiceover_segment = same words + [tags].
    If voiceover_segment has MORE content words -> rebuild from tags + narrator_script.
    """
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue

        narrator = scene.get("narrator_script", "")
        vo = scene.get("voiceover_segment", "")

        # Skip silence / empty scenes
        if not isinstance(narrator, str) or not narrator.strip():
            continue
        if not isinstance(vo, str) or vo.strip() == "[silence]" or not vo.strip():
            continue

        # Extract content words (strip all [tags])
        narrator_words = [w_ for w_ in re.sub(r'\[.*?\]', '', narrator).split() if w_.strip()]
        vo_words = [w_ for w_ in re.sub(r'\[.*?\]', '', vo).split() if w_.strip()]

        if len(vo_words) > len(narrator_words) and narrator_words:
            # Rebuild: extract tags + narrator content
            tags = re.findall(r'\[.*?\]', vo)
            leading_tags = " ".join(tags[:2]) if tags else ""

            rebuilt = _rebuild_vo_from_narrator(leading_tags, narrator, tags)
            scene["voiceover_segment"] = rebuilt

            w.append(AutoFixWarning(
                f"scenes[{i}].voiceover_segment",
                f"VO had {len(vo_words)} content words vs narrator's {len(narrator_words)} "
                f"— rebuilt from narrator_script + tags"
            ))


def _warn_total_vo_budget(d: dict, scenes: list, w: list) -> None:
    """Estimate total VO duration from text + tags, warn if exceeds target."""
    target = 16  # default
    meta = d.get("metadata")
    if isinstance(meta, dict):
        try:
            target = float(meta.get("target_duration_seconds", 16))
        except (ValueError, TypeError):
            target = 16

    total_est = 0.0
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        vo = scene.get("voiceover_segment", "")
        if not isinstance(vo, str) or not vo.strip() or vo.strip() == "[silence]":
            continue

        # Detect style
        vo_lower = vo.lower()
        style = "default"
        for tag in ("whispers", "drawn out", "calm", "gentle"):
            if f"[{tag}]" in vo_lower:
                style = tag
                break

        # Count pauses
        pause_time = _estimate_pause_time(vo)

        # Count content words
        words = [w_ for w_ in re.sub(r'\[.*?\]', '', vo).split() if w_.strip()]
        word_time = len(words) * _TTS_RATE.get(style, 0.40)

        total_est += word_time + pause_time

    ratio = total_est / target if target > 0 else 999
    if ratio > 1.1:
        w.append(AutoFixWarning(
            "voiceover.total_budget",
            f"Estimated VO ~{total_est:.1f}s for {target:.0f}s video "
            f"(ratio {ratio:.2f}x) — likely to overshoot target duration"
        ))


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
    "ARCHITECTURAL_FORM_WORDS",
    "_TTS_RATE",
    "_estimate_pause_time",
]
