"""
GEN1 Python Validator v2.8

Deterministic validator for GEN1 (Creative Director) output.
Auto-corrections are handled by gen1_autocorrect.py (runs first).
This module only VALIDATES — it never mutates data.

Usage:
    from app.services.gen1_validator import Gen1Validator, validate_gen1

    validator = Gen1Validator()
    result = validator.validate(gen1_json_data)

    if result.passed:
        corrected = result.corrected_data  # auto-fixed version
    else:
        for error in result.errors:
            logger.error(error)
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from loguru import logger

# Import enums from gen_models (single source of truth)
from app.services.gen_models import (
    ContentCategory,
    HookType,
    PsychologicalTrigger,
    LightingPreset,
    CameraMovement,
    NarrativePurpose,
    EnergyLevel,
    SonicHookType,
    ReferenceType,
)

# Import auto-corrector
from app.services.gen1_autocorrect import (
    autocorrect_gen1,
    AutoFixWarning,
    VALID_ARCHITECTURE_ELEMENTS,
    VALID_FOOD_ACTIONS,
    NARRATIVE_BRIDGE_STARTERS,
    TEMPERATURE_WORDS,
    ARCHITECTURAL_FORM_WORDS,
    _TTS_RATE,
    _estimate_pause_time,
)


# ============================================================================
# BANLIST LOADER
# ============================================================================

_BANLIST_CACHE: Optional[Dict[str, Set[str]]] = None


def _load_banlist(path: Optional[Path] = None) -> Dict[str, Set[str]]:
    if path is None:
        path = Path(__file__).parent.parent.parent / "config" / "ban_list.txt"
    result: Dict[str, Set[str]] = {
        "first_words": set(), "first_phrases": set(), "commands": set(),
        "fillers": set(), "ai_markers": set(), "overused_adjectives": set(),
        "generic_luxury": set(),
    }
    if not path.exists():
        logger.warning(f"Banlist not found: {path}")
        return result
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to read banlist: {e}")
        return result
    section_map = {
        "заборонені перші слова": "first_words",
        "заборонені початкові фрази": "first_phrases",
        "команди": "commands", "філери": "fillers",
        "ші-маркери": "ai_markers",
        "перевикористані прикметники": "overused_adjectives",
        "generic luxury": "generic_luxury",
    }
    current: Optional[str] = None
    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            header = line.lstrip("#").strip().lower()
            for key, name in section_map.items():
                if key in header:
                    current = name
                    break
            continue
        if current and line:
            result[current].add(line.lower())
    total = sum(len(v) for v in result.values())
    logger.debug(f"Banlist loaded: {total} items")
    return result


def get_banlist() -> Dict[str, Set[str]]:
    global _BANLIST_CACHE
    if _BANLIST_CACHE is None:
        _BANLIST_CACHE = _load_banlist()
    return _BANLIST_CACHE


def reload_banlist() -> Dict[str, Set[str]]:
    global _BANLIST_CACHE
    _BANLIST_CACHE = _load_banlist()
    return _BANLIST_CACHE


def get_banned_first_words() -> Set[str]:
    words = get_banlist().get("first_words", set())
    return words if words else {"welcome", "so", "today", "hello", "hi", "hey", "this", "let", "here"}


def get_banned_first_phrases() -> Set[str]:
    return get_banlist().get("first_phrases", set())


def get_ai_markers() -> Set[str]:
    return get_banlist().get("ai_markers", set())


def get_fillers() -> Set[str]:
    return get_banlist().get("fillers", set())


def get_overused_adjectives() -> Set[str]:
    return get_banlist().get("overused_adjectives", set())


def get_generic_luxury() -> Set[str]:
    return get_banlist().get("generic_luxury", set())


# ============================================================================
# VALIDATOR-ONLY ENUMS (not in gen_models.py)
# ============================================================================

class AtmosphereMode:
    VALUES = {"CINEMATIC", "VIBRANT", "PLAYFUL", "GOLDEN_WARM", "TROPICAL", "ETHEREAL", "NOIR", "HAUNTED"}


class VolumeLevel:
    VALUES = {"LOUD", "MEDIUM", "CRISP", "SUBTLE"}


class EasterEggVisibility:
    VALUES = {"FINDABLE", "HIDDEN", "OBVIOUS"}


# ============================================================================
# CONSTANTS
# ============================================================================

BANNED_FIRST_WORDS: Set[str] = {"welcome", "so", "today", "hello", "hi", "hey", "this", "let", "here"}
VALID_CAMERA_MOVEMENTS: Set[str] = {m.value for m in CameraMovement}
BANNED_CAMERA_MOVEMENTS: Set[str] = {"DRIFT", "FLOAT", "GLIDE"}

ELEVENLABS_EMOTION_TAGS: Set[str] = {"[whispers]", "[calm]", "[warm]", "[gentle]", "[excited]", "[sad]", "[angry]", "[happily]", "[shouts]"}
ELEVENLABS_DELIVERY_TAGS: Set[str] = {"[pause]", "[short pause]", "[long pause]", "[silence]", "[laughs]", "[sighs]", "[dry laugh]"}
ELEVENLABS_STYLE_TAGS: Set[str] = {"[rushed]", "[drawn out]"}
ALL_ELEVENLABS_TAGS: Set[str] = ELEVENLABS_EMOTION_TAGS | ELEVENLABS_DELIVERY_TAGS | ELEVENLABS_STYLE_TAGS

BANNED_DIRECTION_TAGS: list = ["[excited]", "[rushed]", "[dramatic]", "[shouts]", "[loud]", "[energetic]", "[cheerful]", "[screams]", "[urgent]", "[intense]"]

MIN_SCENES = 6
MAX_SCENES = 10
MAX_YOUTUBE_TITLE_LENGTH = 50
MIN_YOUTUBE_DESCRIPTION_LENGTH = 100
MIN_VIRAL_SCORE = 0.7
MIN_MOTION_ELEMENTS = 2
MIN_DISTINCTIVE_FEATURES = 2
MIN_TEXTURE_KEYWORDS = 2
MIN_COLOR_KEYWORDS = 2
MIN_PROMPT_SNIPPET_LENGTH = 10

# Excluded "golden", "brown", "orange" — these are valid food sensory descriptors
COLOR_WORDS: Set[str] = {"white", "black", "red", "blue", "green", "pink", "silver", "purple", "yellow"}

# Appetite-suppressing dominant colors (grey/blue kill hunger response)
_APPETITE_KILLER_COLORS: Set[str] = {"grey", "gray", "blue", "purple", "silver", "slate", "charcoal", "ash"}

# Saliva trigger words for money_shot craving anchor
_SALIVA_TRIGGERS: Set[str] = {
    "stretching", "stretch", "dripping", "drip", "drips",
    "cracking", "crack", "cracks", "breaking", "break", "breaks", "snapping", "snap",
    "melting", "melt", "melts", "pouring", "pour", "pours",
    "oozing", "ooze", "oozes", "soaking", "soak", "absorbing", "absorbed",
    "bubbling", "bubble", "sizzling", "sizzle", "pulling", "pull",
    "tearing", "tear", "splitting", "split", "fracturing", "fracture",
}

# Sensory channel keywords for 4-channel audit
_THERMAL_WORDS = {
    "warm", "warmer", "warming", "warmth", "hot", "hotter",
    "cold", "colder", "cool", "cooler", "cooling", "cooled",
    "steaming", "frozen", "freezing", "heat", "heated", "heating",
    "burning", "icy", "chilled", "chilling", "sizzling",
    "boiling", "lukewarm", "scalding", "frosty", "molten",
    "temperature", "degrees", "melted", "scorched",
}
_TACTILE_WORDS = {
    "stick", "sticky", "sticking", "sticks",
    "squishy", "rough", "smooth", "soft", "hard", "wet", "dry",
    "gooey", "crispy", "crunchy", "slippery", "gritty",
    "velvety", "silky", "pull", "pulling", "pulls",
    "sink", "sinking", "sinks", "press", "pressing", "presses",
    "squeeze", "squeezing", "crumble", "crumbling", "crumbles",
    "flaky", "elastic", "rubbery", "brittle",
    "stretching", "stretches", "bounce", "bouncing",
}
_OLFACTORY_WORDS = {
    "smell", "smells", "smelling", "smelled",
    "scent", "scented", "scents",
    "aroma", "aromas", "aromatic",
    "fragrant", "fragrance",
    "yeast", "sweet", "nutty", "buttery", "vanilla", "caramel",
    "smoky", "earthy", "tangy", "pungent", "musky",
    "nose", "inhale", "inhaling", "inhales", "breath", "breathe",
}
# Temporal freshness: "just made" urgency, active process happening NOW
_TEMPORAL_PATTERNS = [
    re.compile(r'\bstill\s+\w+ing\b', re.IGNORECASE),       # "still bubbling", "still dripping"
    re.compile(r'\bjust\s+\w+ed\b', re.IGNORECASE),          # "just baked", "just poured", "just cooled"
    re.compile(r'\bjust\s+(?:set|made|cut|lit|split|out)\b', re.IGNORECASE),  # irregular past participles
    re.compile(r'\bfresh(?:ly)?\b', re.IGNORECASE),           # "fresh out", "freshly baked", "fresh"
]
# Active-process -ing words that strongly indicate temporal freshness (food is alive NOW)
_TEMPORAL_ACTIVE_WORDS = {
    "bubbling", "dripping", "melting", "sizzling", "steaming",
    "oozing", "caramelizing", "crisping", "browning", "toasting",
    "roasting", "baking", "brewing", "boiling", "glazing",
    "crystallizing", "hardening", "setting", "cooling", "rising",
    "frying", "grilling", "smoking", "pouring", "spreading",
}

# STRUCTURAL_DETAIL key_elements food words
_STRUCTURAL_FOOD_WORDS = {"glistening", "dripping", "crystallized", "melting", "sticky", "crispy", "steaming", "sizzling", "bubbling", "glossy", "crunchy", "oozing", "frosted", "caramelized", "glazed"}

# MODE B money-shot pattern
_MODE_B_PATTERN = re.compile(r'^\s*\[long\s+pause\]\s*\[whispers\]\s*\S+\.?\s*$', re.IGNORECASE)


# ============================================================================
# VALIDATION ERROR + RESULT
# ============================================================================

@dataclass
class ValidationError:
    field: str
    message: str
    severity: str = "error"
    code: str = ""
    suggestion: str = ""

    def __str__(self) -> str:
        prefix = "⛔" if self.severity == "error" else "⚠️"
        result = f"{prefix} [{self.field}] {self.message}"
        if self.suggestion:
            result += f" → {self.suggestion}"
        return result

    def to_dict(self) -> Dict[str, str]:
        return {"field": self.field, "message": self.message, "severity": self.severity, "code": self.code, "suggestion": self.suggestion}


@dataclass
class ValidationResult:
    passed: bool
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[ValidationError] = field(default_factory=list)
    validation_time_ms: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now().astimezone().isoformat())
    validator_version: str = "2.0"
    corrected_data: Optional[Dict[str, Any]] = field(default=None)
    # Keep gen2_handoff for backward compat (pipeline reads it)
    gen2_handoff: Dict[str, Any] = field(default_factory=dict)

    @property
    def error_messages(self) -> List[str]:
        return [str(e) for e in self.errors]

    @property
    def warning_messages(self) -> List[str]:
        return [str(w) for w in self.warnings]

    @property
    def all_issues(self) -> List[ValidationError]:
        return self.errors + self.warnings

    def to_dict(self) -> Dict[str, Any]:
        return {
            "validation": {"stage": "VAL_GEN1", "version": self.validator_version, "timestamp": self.timestamp, "validation_time_ms": round(self.validation_time_ms, 2)},
            "phase1_structural": {"status": "PASS" if self.passed else "FAIL", "errors": [e.to_dict() for e in self.errors], "warnings": [w.to_dict() for w in self.warnings]},
            "phase2_quality": None,
            "decision": {"status": "PASSED" if self.passed else "FAILED", "reasoning": self._build_reasoning(), "proceed_to": "GEN2" if self.passed else None},
            "gen2_handoff": self.gen2_handoff if self.passed else {},
            "issues": {"has_issues": len(self.errors) > 0 or len(self.warnings) > 0, "concerns": [str(e) for e in self.all_issues]},
            "retry_guidance": self._build_retry_guidance() if not self.passed else None,
        }

    def _build_reasoning(self) -> str:
        if self.passed:
            return f"All checks passed with {len(self.warnings)} warning(s). Ready for GEN2." if self.warnings else "All checks passed. Ready for GEN2."
        return f"Validation failed with {len(self.errors)} error(s). See retry_guidance."

    def _build_retry_guidance(self) -> Dict[str, Any]:
        return {"fixes_needed": [f"Fix {e.field}: {e.message}" + (f" ({e.suggestion})" if e.suggestion else "") for e in self.errors], "regenerate": True}


# ============================================================================
# VALIDATOR CLASS
# ============================================================================

class Gen1Validator:
    """Deterministic Python validator for GEN1 output (v2.0).

    Architecture: autocorrect → validate → report.
    Auto-corrections live in gen1_autocorrect.py.
    This class only validates and reports errors/warnings.
    """

    # Soft enum fields: produce warnings, not errors
    _SOFT_ENUMS = {"metadata.concept.category", "lighting_master.preset", "atmosphere_mode", "audio.sonic_hook.type"}

    def __init__(self, strict_mode: bool = False):
        """
        Args:
            strict_mode: If True, warnings also block. Default False.
        """
        self.strict_mode = strict_mode
        self._errors: List[ValidationError] = []
        self._warnings: List[ValidationError] = []
        self._data: Dict[str, Any] = {}

    def validate(self, data: Dict[str, Any]) -> ValidationResult:
        start_time = time.perf_counter()
        self._errors = []
        self._warnings = []

        # Phase 1: Auto-correct (deterministic fixes)
        corrected, fix_warnings = autocorrect_gen1(data)
        self._data = corrected

        # Convert AutoFixWarnings to ValidationErrors (as warnings)
        for fw in fix_warnings:
            self._warnings.append(ValidationError(field=fw.field, message=fw.message, severity="warning"))

        # Phase 2: Validate
        self._run_all_validations()

        # Determine pass/fail
        passed = len(self._errors) == 0
        if self.strict_mode and self._warnings:
            passed = False

        validation_time_ms = (time.perf_counter() - start_time) * 1000

        result = ValidationResult(
            passed=passed,
            errors=self._errors.copy(),
            warnings=self._warnings.copy(),
            validation_time_ms=validation_time_ms,
            corrected_data=self._data,
            gen2_handoff=self._build_summary() if passed else {},
        )

        if passed:
            logger.success(f"GEN1 validation PASSED in {validation_time_ms:.2f}ms ({len(self._warnings)} warnings)")
        else:
            logger.warning(f"GEN1 validation FAILED in {validation_time_ms:.2f}ms ({len(self._errors)} errors, {len(self._warnings)} warnings)")

        return result

    # ========================================================================
    # ORCHESTRATION
    # ========================================================================

    def _run_all_validations(self) -> None:
        self._validate_metadata()
        self._validate_property()
        self._validate_hook()
        self._validate_architectural_identity()
        self._validate_food_identity()
        self._validate_lighting_master()
        self._validate_atmosphere_mode()
        self._validate_foreground_element()
        self._validate_voiceover()
        self._validate_warning_line()
        self._validate_vo_sensory()
        self._validate_audio()
        self._validate_engagement()
        self._validate_youtube()
        self._validate_viral_assessment()
        self._validate_scenes()
        self._validate_sensory_pressure()
        self._validate_total_duration()
        self._validate_top_level_fields()
        self._validate_cross_field_consistency()
        # New v2.0 validations
        self._validate_structural_counts()
        self._validate_sensory_channels()
        self._validate_sp_curve_rules()
        self._validate_humor()
        self._validate_dominant_color_appetite()
        self._validate_money_shot_saliva_trigger()
        self._validate_aerial_reveals_architecture()
        self._validate_vo_budget()

    # ========================================================================
    # VALIDATION METHODS
    # ========================================================================

    def _validate_metadata(self) -> None:
        metadata = self._get_field("metadata")
        if metadata is None:
            return
        status = self._nested(metadata, "status")
        if status and status not in ("PRODUCTION_READY", "REJECTED_INPUT"):
            self._error("metadata.status", f"Must be 'PRODUCTION_READY' or 'REJECTED_INPUT', got '{status}'", code="INVALID_STATUS")
        concept = self._nested(metadata, "concept")
        if concept:
            cat = self._nested(concept, "category")
            self._check_enum(cat, [e.value for e in ContentCategory], "metadata.concept.category")
            self._require(concept, "subject", "metadata.concept.subject")
            self._require(concept, "food_material", "metadata.concept.food_material")
        sc = self._nested(metadata, "scene_count")
        if sc is not None:
            if not isinstance(sc, int):
                self._error("metadata.scene_count", f"Expected int, got {type(sc).__name__}", code="INVALID_SCENE_COUNT")
            elif sc < MIN_SCENES or sc > MAX_SCENES:
                self._error("metadata.scene_count", f"Must be {MIN_SCENES}-{MAX_SCENES}, got {sc}", code="INVALID_SCENE_COUNT")

    def _validate_property(self) -> None:
        prop = self._data.get("property") or self._data.get("structure")
        if prop is None:
            self._error("property", "Required field missing (also checked 'structure')", code="MISSING_PROPERTY")
            return
        for f in ("name", "location", "tagline"):
            self._require(prop, f, f"property.{f}")

    def _validate_hook(self) -> None:
        hook = self._get_field("hook")
        if hook is None:
            return
        ht = self._nested(hook, "type")
        self._check_enum(ht, [e.value for e in HookType], "hook.type")
        if not self._nested(hook, "psychological_trigger"):
            self._error("hook.psychological_trigger", "Required field missing or empty")
        fw = self._nested(hook, "first_words", "")
        if not fw:
            self._error("hook.first_words", "Required and cannot be empty", code="MISSING_FIRST_WORDS")
        else:
            self._validate_first_words(fw, hook)
        self._require(hook, "complete_hook_vo", "hook.complete_hook_vo")
        self._require(hook, "first_frame_visual", "hook.first_frame_visual")
        self._require(hook, "scroll_stop_element", "hook.scroll_stop_element")

    def _validate_first_words(self, first_words: str, hook: dict) -> None:
        clean = re.sub(r'\[.*?\]', '', first_words).strip()
        clean_lower = clean.lower()
        banned_words = get_banned_first_words()
        banned_phrases = get_banned_first_phrases()

        # Min 2 words check — 1-word hooks create zero curiosity gap
        word_count = len(clean.split()) if clean else 0
        if word_count < 2:
            self._error(
                "hook.first_words",
                f"Only {word_count} word(s): '{clean}' — minimum 2 words required for curiosity gap",
                code="HOOK_TOO_SHORT",
            )

        if clean:
            actual = clean.split()[0].lower()
            if actual in banned_words:
                self._warn("hook.first_words", f"Starts with '{actual}' (weak)", suggestion="Use IMPACT words: numbers, sensory, warnings, food nouns")
            for phrase in banned_phrases:
                if clean_lower.startswith(phrase):
                    self._warn("hook.first_words", f"Starts with generic phrase '{phrase}'")
                    break

        # Sync check: first_words must match opening of scenes[0].narrator_script
        scenes = self._data.get("scenes", [])
        if scenes and isinstance(scenes[0], dict):
            narrator = scenes[0].get("narrator_script", "")
            if isinstance(narrator, str) and narrator.strip():
                fw_norm = clean_lower.rstrip(".")
                narrator_norm = narrator.strip().lower()
                if fw_norm and not narrator_norm.startswith(fw_norm):
                    self._error(
                        "hook.first_words",
                        f"Mismatch: first_words='{clean}' but Scene 1 narrator_script='{narrator}' — must start with same words",
                        code="HOOK_NARRATOR_MISMATCH",
                    )

        complete_vo = self._nested(hook, "complete_hook_vo", "")
        has_emotion = any(t in first_words for t in ELEVENLABS_EMOTION_TAGS) or any(t in complete_vo for t in ELEVENLABS_EMOTION_TAGS)
        if not has_emotion:
            self._warn("hook.complete_hook_vo", "Should contain an emotion tag", suggestion=f"Add: {', '.join(sorted(ELEVENLABS_EMOTION_TAGS))}")

    def _validate_architectural_identity(self) -> None:
        arch = self._get_field("architectural_identity")
        if arch is None:
            return
        self._require(arch, "style_code", "architectural_identity.style_code")
        self._require(arch, "silhouette_description", "architectural_identity.silhouette_description")
        features = self._nested(arch, "distinctive_features", [])
        if not isinstance(features, list) or len(features) < MIN_DISTINCTIVE_FEATURES:
            self._warn("architectural_identity.distinctive_features", f"Should have ≥{MIN_DISTINCTIVE_FEATURES} items")

    def _validate_food_identity(self) -> None:
        food = self._get_field("food_identity")
        if food is None:
            return
        self._require(food, "primary_food", "food_identity.primary_food")
        dna = self._nested(food, "food_dna", {})
        if not dna:
            self._error("food_identity.food_dna", "Required object missing", code="MISSING_FOOD_DNA")
        else:
            self._require(dna, "walls_become", "food_identity.food_dna.walls_become")
            self._require(dna, "roof_becomes", "food_identity.food_dna.roof_becomes")
        tex = self._nested(food, "texture_keywords", [])
        if not isinstance(tex, list) or len(tex) < MIN_TEXTURE_KEYWORDS:
            self._warn("food_identity.texture_keywords", f"Should have ≥{MIN_TEXTURE_KEYWORDS} items")
        colors = self._nested(food, "color_keywords", [])
        if not isinstance(colors, list) or len(colors) < MIN_COLOR_KEYWORDS:
            self._warn("food_identity.color_keywords", f"Should have ≥{MIN_COLOR_KEYWORDS} items")

    def _validate_lighting_master(self) -> None:
        light = self._get_field("lighting_master")
        if light is None:
            return
        self._check_enum(self._nested(light, "preset"), [e.value for e in LightingPreset], "lighting_master.preset")
        snippet = self._nested(light, "prompt_snippet", "")
        if not snippet or len(snippet) < MIN_PROMPT_SNIPPET_LENGTH:
            self._error("lighting_master.prompt_snippet", f"Must be ≥{MIN_PROMPT_SNIPPET_LENGTH} chars", code="SNIPPET_TOO_SHORT")

    def _validate_atmosphere_mode(self) -> None:
        mode = self._data.get("atmosphere_mode")
        if not mode:
            self._warn("atmosphere_mode", "Missing — defaulting to CINEMATIC")
        elif mode not in AtmosphereMode.VALUES:
            self._warn("atmosphere_mode", f"Non-standard value '{mode}'", suggestion=f"Standard: {', '.join(sorted(AtmosphereMode.VALUES))}")

        # Atmosphere + Lighting collision check
        if mode:
            light = self._data.get("lighting_master", {})
            preset = light.get("preset", "") if isinstance(light, dict) else ""
            if preset:
                _COLLISION_BAN = {
                    "CINEMATIC": {"OVERCAST_SOFT"},
                    "NOIR": {"OVERCAST_SOFT"},
                    "HAUNTED": {"OVERCAST_SOFT", "BLUE_HOUR"},
                    "ETHEREAL": {"MOONLIT_SILVER"},
                }
                banned = _COLLISION_BAN.get(mode.upper(), set())
                if preset.upper() in banned:
                    self._warn("atmosphere_mode",
                               f"Atmosphere '{mode}' + lighting '{preset}' = double-dim collision (low visibility)")

    def _validate_foreground_element(self) -> None:
        fg = self._get_field("foreground_element")
        if fg is None:
            return
        self._require(fg, "type", "foreground_element.type")
        snippet = self._nested(fg, "prompt_snippet", "")
        if not snippet or len(snippet) < MIN_PROMPT_SNIPPET_LENGTH:
            self._error("foreground_element.prompt_snippet", f"Must be ≥{MIN_PROMPT_SNIPPET_LENGTH} chars", code="SNIPPET_TOO_SHORT")

    def _validate_voiceover(self) -> None:
        vo = self._get_field("voiceover")
        if vo is None:
            return
        script = self._nested(vo, "full_script", "")
        if not script:
            self._error("voiceover.full_script", "Required and cannot be empty", code="MISSING_SCRIPT")
        else:
            if not any(t in script for t in ALL_ELEVENLABS_TAGS):
                self._warn("voiceover.full_script", "Should contain ElevenLabs tags")
            sl = script.lower()
            ai = get_ai_markers()
            found_ai = [m for m in ai if re.search(r'\b' + re.escape(m) + r'\b', sl)]
            if found_ai:
                self._error("voiceover.full_script", f"AI markers: {', '.join(found_ai[:5])}", code="AI_MARKERS_DETECTED", suggestion="Remove AI words like 'delve', 'nestled', 'tapestry'")
            overused = get_overused_adjectives()
            found_o = [ow for ow in overused if re.search(r'\b' + re.escape(ow) + r'\b', sl)]
            if found_o:
                self._warn("voiceover.full_script", f"Overused adjectives: {', '.join(found_o[:3])}")
            fillers = get_fillers()
            found_f = [fl for fl in fillers if re.search(r'\b' + re.escape(fl) + r'\b', sl)]
            # Exclude "just" when ALL occurrences are in temporal patterns
            # ("just set", "just cooled", "just poured", etc.) — intentional thermal/temporal hooks
            if "just" in found_f:
                _JUST_TEMPORAL = re.compile(r'\bjust\s+(?:\w+ed|set|made|cut|lit|split|out|mixed)\b', re.IGNORECASE)
                all_just = list(re.finditer(r'\bjust\b', sl))
                temporal_just = list(_JUST_TEMPORAL.finditer(sl))
                if len(all_just) > 0 and len(temporal_just) >= len(all_just):
                    found_f = [f for f in found_f if f != "just"]
            if found_f:
                self._warn("voiceover.full_script", f"Filler phrases: {', '.join(found_f[:3])}")
            generic = get_generic_luxury()
            found_g = [gl for gl in generic if re.search(r'\b' + re.escape(gl) + r'\b', sl)]
            if len(found_g) >= 2:
                self._warn("voiceover.full_script", f"Multiple generic luxury words: {', '.join(found_g[:3])}")
            found_banned = [t for t in BANNED_DIRECTION_TAGS if t in sl]
            if found_banned:
                self._warn("voiceover.full_script", f"Banned direction tags: {', '.join(found_banned)}", suggestion="Use [whispers], [calm], [warm], [gentle], [pause], [silence], [long pause]")
        self._require(vo, "character", "voiceover.character")
        self._require(vo, "voice_id", "voiceover.voice_id")

    def _validate_vo_sensory(self) -> None:
        """Detect color words in voiceover (visual, not sensory)."""
        scenes = self._data.get("scenes", [])
        if not isinstance(scenes, list):
            return
        color_re = re.compile(r'\b(' + '|'.join(re.escape(c) for c in COLOR_WORDS) + r')\b(?:\s+\w+|[.\s]*$)', re.IGNORECASE)
        for i, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                continue
            vo = scene.get("voiceover_segment", "")
            if not isinstance(vo, str) or not vo.strip() or vo.strip() == "[silence]":
                continue
            clean = re.sub(r'\[[\w\s]+\]', '', vo)
            matches = color_re.findall(clean)
            if matches:
                self._warn(f"scenes[{i}].voiceover_segment", f"Color word(s): {', '.join(set(m.lower() for m in matches))} — visual, not sensory", suggestion="Replace with sensation: texture, temperature, taste, smell")

    def _validate_warning_line(self) -> None:
        wl = self._data.get("warning_line")
        scenes = self._data.get("scenes", [])
        pen_aerial = True
        if len(scenes) >= 2:
            pen = scenes[-2]
            pen_aerial = self._nested(pen, "narrative_purpose", "") in ("AERIAL", "AERIAL_WOW", "AERIAL_REVEAL")
        if not wl or not isinstance(wl, str) or not wl.strip():
            sev = "error" if pen_aerial else "warning"
            if sev == "error":
                self._error("warning_line", "Missing or empty", code="MISSING_WARNING_LINE", suggestion="3-8 word warning for AERIAL scene")
            else:
                self._warn("warning_line", "Missing (N-1 not AERIAL, so optional)")
            return
        clean = re.sub(r'\[[\w\s]+\]', '', wl).strip()
        wc = len(clean.split()) if clean else 0
        if wc < 3 or wc > 8:
            self._error("warning_line", f"{wc} words (need 3-8)", code="WARNING_LINE_LENGTH")
        # Cross-check with full_script
        vo = self._data.get("voiceover", {})
        fs = vo.get("full_script", "") if isinstance(vo, dict) else ""
        if isinstance(fs, str):
            wl_plain = re.sub(r'\[[\w\s]+\]\s*', '', wl).strip().rstrip(".")
            if wl_plain.lower() not in re.sub(r'\[[\w\s]+\]\s*', '', fs).lower():
                self._warn("warning_line", f"'{wl.strip()}' not in full_script", suggestion="Must appear in AERIAL scene VO")

    def _validate_audio(self) -> None:
        audio = self._get_field("audio")
        if audio is None:
            return
        sonic = self._nested(audio, "sonic_hook", {})
        if not sonic:
            self._error("audio.sonic_hook", "Required object missing", code="MISSING_SONIC_HOOK")
        else:
            self._check_enum(self._nested(sonic, "type"), [e.value for e in SonicHookType], "audio.sonic_hook.type")
            vol = self._nested(sonic, "volume")
            if vol and vol not in VolumeLevel.VALUES:
                self._warn("audio.sonic_hook.volume", f"Non-standard: '{vol}'")
        self._require(audio, "suno_prompt", "audio.suno_prompt")
        if not self._nested(audio, "foley_palette"):
            self._error("audio.foley_palette", "Required object missing", code="MISSING_FOLEY")
        sfx = self._nested(audio, "sfx_per_scene")
        if not isinstance(sfx, list):
            self._error("audio.sfx_per_scene", "Must be array", code="INVALID_SFX")

    def _validate_engagement(self) -> None:
        eng = self._get_field("engagement")
        if eng is None:
            return
        egg = self._nested(eng, "easter_egg", {})
        if not egg:
            rh = self._nested(eng, "replay_hooks", [])
            if not rh:
                self._warn("engagement", "Neither easter_egg nor replay_hooks found")
        elif isinstance(egg, dict):
            fmt = self._nested(egg, "format", "VISUAL")
            if fmt == "AUDIO_ONLY":
                self._require(egg, "audio_hint", "engagement.easter_egg.audio_hint")
                self._require(egg, "comment_bait", "engagement.easter_egg.comment_bait")
            else:
                self._require(egg, "object", "engagement.easter_egg.object")
                sn = self._nested(egg, "scene_number")
                total = len(self._data.get("scenes", []))
                try:
                    sn_int = int(sn) if sn is not None else None
                except (ValueError, TypeError):
                    sn_int = None
                if sn_int is None:
                    self._error("engagement.easter_egg.scene_number", "Required field missing", code="MISSING_SCENE_NUMBER")
                elif total > 0 and not (2 <= sn_int <= total - 1):
                    self._error("engagement.easter_egg.scene_number", f"Must be 2-{total - 1}, got {sn_int}", code="INVALID_EGG_SCENE")
                self._require(egg, "placement", "engagement.easter_egg.placement")
                vis = self._nested(egg, "visibility")
                if vis and vis not in EasterEggVisibility.VALUES:
                    self._warn("engagement.easter_egg.visibility", f"Non-standard: '{vis}'")
                self._require(egg, "comment_bait", "engagement.easter_egg.comment_bait")
        st = self._nested(eng, "share_trigger")
        if st is None:
            self._error("engagement.share_trigger", "Missing share_trigger", code="MISSING_SHARE_TRIGGER")
        elif isinstance(st, dict) and not (st.get("text") or "").strip():
            self._error("engagement.share_trigger.text", "Cannot be empty", code="EMPTY_SHARE_TRIGGER")
        elif isinstance(st, str) and not st.strip():
            self._error("engagement.share_trigger", "Cannot be empty", code="EMPTY_SHARE_TRIGGER")
        sv = self._nested(eng, "save_trigger")
        if sv is None:
            self._warn("engagement.save_trigger", "Missing save_trigger")
        elif isinstance(sv, str) and len(sv.strip()) > 60:
            self._warn("engagement.save_trigger", f"Too long ({len(sv.strip())} chars, max 60)")
        hashtags = self._nested(eng, "hashtags", [])
        if isinstance(hashtags, list) and hashtags and not (3 <= len(hashtags) <= 10):
            self._warn("engagement.hashtags", f"Expected 3-10, got {len(hashtags)}")

    def _validate_youtube(self) -> None:
        yt = self._get_field("youtube")
        if yt is None:
            if not self._data.get("youtube_title"):
                self._error("youtube_title", "Either youtube.title or youtube_title must exist", code="MISSING_FLAT_TITLE")
            if not self._data.get("youtube_description"):
                self._error("youtube_description", "Either youtube.description or youtube_description must exist", code="MISSING_FLAT_DESC")
            return
        title = self._nested(yt, "title", "")
        if not title:
            self._error("youtube.title", "REQUIRED and NEVER NULL", code="NULL_YOUTUBE_TITLE")
        elif len(title) > MAX_YOUTUBE_TITLE_LENGTH:
            self._error("youtube.title", f"Max {MAX_YOUTUBE_TITLE_LENGTH} chars, got {len(title)}", code="TITLE_TOO_LONG")
        desc = self._nested(yt, "description", "")
        if not desc:
            self._error("youtube.description", "REQUIRED and NEVER NULL", code="NULL_YOUTUBE_DESC")
        elif len(desc) < MIN_YOUTUBE_DESCRIPTION_LENGTH:
            self._warn("youtube.description", f"Short ({len(desc)} chars, {MIN_YOUTUBE_DESCRIPTION_LENGTH}+ recommended)")
        if desc:
            ht_in_desc = re.findall(r'#[\w\-]+', desc.lower())
            if len(ht_in_desc) < 6:
                self._warn("youtube.description", f"Only {len(ht_in_desc)} hashtags — min 6 recommended")
            if '#glazecity' in ht_in_desc:
                self._error("youtube.description", "#glazecity banned (0 search volume)", code="BANNED_HASHTAG_GLAZECITY")
        tags = self._nested(yt, "tags", [])
        if isinstance(tags, list):
            if len(tags) < 3:
                self._warn("youtube.tags", f"Only {len(tags)} tags — 5-8 recommended")
            _BANNED_TAGS = {"glaze city", "ai art", "blender 3d", "midjourney", "kling", "yumestate", "edible architecture", "weirdcore", "visual asmr", "food art", "satisfying", "shorts"}
            for t in tags:
                if isinstance(t, str) and t.lower().strip() in _BANNED_TAGS:
                    self._warn("youtube.tags", f"'{t}' is banned/default tag")
        # Title/description variants count
        tv = self._nested(yt, "title_variants")
        if tv is not None and isinstance(tv, list) and len(tv) != 4:
            self._warn("youtube.title_variants", f"Expected 4, got {len(tv)}")
        dv = self._nested(yt, "description_variants")
        if dv is not None and isinstance(dv, list) and len(dv) != 3:
            self._warn("youtube.description_variants", f"Expected 3, got {len(dv)}")

    def _validate_viral_assessment(self) -> None:
        va = self._get_field("viral_assessment")
        if va is None:
            return
        has_verdicts = any(self._nested(va, f) is not None for f in ("hook_verdict", "retention_verdict", "share_verdict"))
        has_scores = self._nested(va, "overall_score") is not None
        if has_verdicts:
            for vf in ("hook_verdict", "retention_verdict", "share_verdict"):
                v = self._nested(va, vf)
                if v is not None and not isinstance(v, str):
                    self._warn(f"viral_assessment.{vf}", "Should be string")
        elif has_scores:
            overall = self._nested(va, "overall_score")
            if isinstance(overall, (int, float)) and overall < MIN_VIRAL_SCORE:
                self._warn("viral_assessment.overall_score", f"Low: {overall} (≥{MIN_VIRAL_SCORE} recommended)")
        else:
            self._warn("viral_assessment", "Missing both verdicts and scores")

    def _validate_scenes(self) -> None:
        scenes = self._data.get("scenes")
        if not isinstance(scenes, list):
            self._error("scenes", "Must be array", code="INVALID_SCENES_TYPE")
            return
        if len(scenes) < MIN_SCENES or len(scenes) > MAX_SCENES:
            self._error("scenes", f"Must have {MIN_SCENES}-{MAX_SCENES}, got {len(scenes)}", code="INVALID_SCENE_COUNT")
            return
        total = len(scenes)
        meta = self._data.get("metadata")
        if isinstance(meta, dict):
            dc = meta.get("scene_count")
            if dc is not None and dc != total:
                self._warn("metadata.scene_count", f"Declared {dc} but actual {total}")

        scene1_movement = ""
        low_count = 0
        prev_low = False
        dual_id_checked = 0
        dual_id_missing = 0

        for i, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                self._error(f"scenes[{i}]", f"Expected object, got {type(scene).__name__}")
                continue
            sn = i + 1
            prefix = f"scenes[{i}]"
            purpose = self._nested(scene, "narrative_purpose", "")
            hint = self._nested(scene, "reference_hint", "")
            energy = self._nested(scene, "energy_level", "")

            self._check_enum(purpose, [e.value for e in NarrativePurpose], f"{prefix}.narrative_purpose")
            self._check_enum(hint, [e.value for e in ReferenceType], f"{prefix}.reference_hint")
            self._check_enum(energy, [e.value for e in EnergyLevel], f"{prefix}.energy_level")

            # Energy rules
            is_low = energy == "LOW"
            if is_low:
                low_count += 1
                if sn <= 3 and purpose != "STRUCTURAL_DETAIL":
                    self._error(f"{prefix}.energy_level", f"Scene {sn} LOW before Scene 4 — retention killer", code="ENERGY_LOW_EARLY")
                if prev_low:
                    self._error(f"{prefix}.energy_level", f"Consecutive LOW energy (Scene {sn-1} and {sn}) — retention killer", code="CONSECUTIVE_LOW")
                if low_count > 1:
                    self._error(f"{prefix}.energy_level", f"Multiple LOW scenes ({low_count} found, max 1 allowed) — only money_shot gets LOW", code="EXCESS_LOW")
            prev_low = is_low
            if energy and sn == total - 1 and energy != "EXPLOSIVE":
                self._warn(f"{prefix}.energy_level", f"N-1 (AERIAL) should be EXPLOSIVE, got '{energy}'")
            if energy and sn == total and energy not in ("HIGH", "EXPLOSIVE"):
                self._warn(f"{prefix}.energy_level", f"N (LOOP_CLOSE) should be HIGH, got '{energy}'")

            # Visual concept
            vc = self._nested(scene, "visual_concept", {})
            if not vc:
                self._error(f"{prefix}.visual_concept", "Required object missing", code="MISSING_VISUAL")
            else:
                self._require(vc, "subject", f"{prefix}.visual_concept.subject")
                self._require(vc, "environment", f"{prefix}.visual_concept.environment")
                motion = self._nested(vc, "motion_elements", [])
                mc = len(motion) if isinstance(motion, list) else 0
                if mc < MIN_MOTION_ELEMENTS:
                    self._warn(f"{prefix}.visual_concept.motion_elements", f"Only {mc} ({MIN_MOTION_ELEMENTS}+ recommended)")

            # Camera
            cam = self._nested(scene, "camera_intent", {})
            if not cam:
                self._error(f"{prefix}.camera_intent", "Required object missing", code="MISSING_CAMERA")
            else:
                mv = self._nested(cam, "movement", "")
                if not mv:
                    self._error(f"{prefix}.camera_intent.movement", "Required field missing", code="MISSING_MOVEMENT")
                else:
                    mv_up = mv.upper()
                    for banned in BANNED_CAMERA_MOVEMENTS:
                        if banned in mv_up:
                            self._error(f"{prefix}.camera_intent.movement", f"Banned: '{banned}'", code="BANNED_MOVEMENT")
                    if sn == 1 and mv_up in ("STATIC", "ORBIT"):
                        self._warn(f"{prefix}.camera_intent.movement", f"'{mv_up}' too slow for hook scene")
                    if mv_up not in VALID_CAMERA_MOVEMENTS:
                        self._warn(f"{prefix}.camera_intent.movement", f"Non-standard: '{mv_up}'")
                if sn == 1:
                    scene1_movement = self._nested(cam, "movement", "")

            # VO AI marker check
            vo_text = self._nested(scene, "voiceover_segment", "") or self._nested(scene, "narrator_script", "")
            if vo_text:
                ai = get_ai_markers()
                found = [m for m in ai if re.search(r'\b' + re.escape(m) + r'\b', vo_text.lower())]
                if found:
                    self._error(f"{prefix}.voiceover_segment", f"AI markers: {', '.join(found[:3])}", code="AI_MARKERS_IN_SCENE")

            # Narrator word count vs duration (pause-aware)
            narrator = self._nested(scene, "narrator_script", "")
            dur = scene.get("duration_seconds")
            is_middle = 1 < sn < total - 1
            if is_middle and narrator and isinstance(narrator, str) and narrator.strip() and dur is not None:
                try:
                    dv = float(dur)
                except (ValueError, TypeError):
                    dv = None
                if dv and dv > 0:
                    # Account for pause tags consuming scene time
                    vo_seg_check = self._nested(scene, "voiceover_segment", "")
                    pause_penalty = 0.0
                    if isinstance(vo_seg_check, str):
                        import re as _re
                        for _m in _re.finditer(r'\[(long\s+pause|short\s+pause|pause)\]', vo_seg_check, _re.IGNORECASE):
                            _tag = _re.sub(r'\s+', ' ', _m.group(1).lower().strip())
                            pause_penalty += {"long pause": 0.7, "pause": 0.3, "short pause": 0.2}.get(_tag, 0.3)
                    effective_dv = max(dv - pause_penalty, 1.0)
                    wds = len(narrator.strip().split())
                    _LIMITS = {2.0: 4, 2.5: 5, 3.0: 7, 3.5: 8, 4.0: 10}
                    mx = _LIMITS.get(effective_dv, int(effective_dv * 2.5) if effective_dv else 10)
                    if mx < 4:
                        mx = 4
                    if wds > mx:
                        extra = f" (pause tags consume {pause_penalty:.1f}s)" if pause_penalty > 0 else ""
                        self._warn(f"{prefix}.narrator_script", f"Too many words ({wds}) for {dv}s{extra} (max {mx})")

            # Numbers in narrator_script ban
            if narrator and isinstance(narrator, str) and narrator.strip():
                if re.search(r'\d', narrator) and sn != 1:
                    self._warn(f"{prefix}.narrator_script", "Contains numbers (banned except Scene 1 hook)")

            # On-screen text
            ost = self._nested(scene, "on_screen_text", "")
            if sn != total and (not ost or not ost.strip()):
                self._warn(f"{prefix}.on_screen_text", "Missing — mute viewers need headlines")
            elif ost and ost.strip():
                ost_words = ost.strip().split()
                if len(ost_words) > 6:
                    self._warn(f"{prefix}.on_screen_text", f"Too long ({len(ost_words)} words, max 6)")

                # Dual identity check (scenes 2 to N-1)
                if 1 < sn < total:
                    ost_token_set = {wd.strip(".,!?:;\"'").lower() for wd in ost.split()}
                    has_form = bool(ost_token_set & ARCHITECTURAL_FORM_WORDS)
                    dual_id_checked += 1
                    if not has_form:
                        dual_id_missing += 1
                        self._warn(f"{prefix}.on_screen_text",
                                   "No architectural form word (wall/arch/dome/column...) — mute viewers miss dual identity")

            # Money shot
            ms = scene.get("money_shot")
            if isinstance(ms, dict) and ms.get("is_money_shot"):
                vo_seg = self._nested(scene, "voiceover_segment", "")
                if vo_seg and vo_seg.strip() not in ("", "[silence]"):
                    if not _MODE_B_PATTERN.match(vo_seg.strip()):
                        self._warn(f"{prefix}.voiceover_segment", "Money shot should be [silence] or MODE B pattern")
                snap = scene.get("snap_moment")
                if not snap or not isinstance(snap, dict):
                    self._warn(f"{prefix}.snap_moment", "Missing snap_moment on money_shot")
                elif not snap.get("snap_sfx"):
                    self._warn(f"{prefix}.snap_moment.snap_sfx", "snap_sfx is empty")

            # food_visual_ratio
            fvr = self._nested(scene, "food_visual_ratio", "")
            valid_fvr = {"FOOD_DOMINANT", "BALANCED", "ARCHITECTURE_DOMINANT"}
            if fvr:
                fu = fvr.strip().upper()
                if fu not in valid_fvr:
                    self._error(f"{prefix}.food_visual_ratio", f"Invalid: '{fvr}'", code="INVALID_FOOD_VISUAL_RATIO")
                elif fu == "ARCHITECTURE_DOMINANT":
                    self._error(f"{prefix}.food_visual_ratio", "ARCHITECTURE_DOMINANT NEVER allowed", code="ARCHITECTURE_DOMINANT_BANNED")

            # Banned direction tags in VO
            vo_check = self._nested(scene, "voiceover_segment", "")
            if vo_check:
                found_banned = [t for t in BANNED_DIRECTION_TAGS if t in vo_check.lower()]
                if found_banned:
                    self._warn(f"{prefix}.voiceover_segment", f"Banned tags: {', '.join(found_banned)}")

            # Scene 1 rules
            if sn == 1:
                if hint != "PRIMARY":
                    self._error(f"{prefix}.reference_hint", f"Scene 1 must be PRIMARY, got '{hint}'", code="INVALID_SCENE1_REF")
                if purpose != "ESTABLISHING":
                    self._error(f"{prefix}.narrative_purpose", f"Scene 1 must be ESTABLISHING, got '{purpose}'", code="INVALID_SCENE1_PURPOSE")
                ffc = scene.get("first_frame_composition")
                if not isinstance(ffc, dict):
                    self._warn(f"{prefix}.first_frame_composition", "Missing — required for thumbnail")
                else:
                    for ff in ("dominant_subject", "silhouette_clarity", "pareidolia_element"):
                        if not ffc.get(ff):
                            self._warn(f"{prefix}.first_frame_composition.{ff}", f"Missing '{ff}'")

            # Scene N rules
            if sn == total:
                if purpose != "LOOP_CLOSE":
                    self._error(f"{prefix}.narrative_purpose", f"Last scene must be LOOP_CLOSE, got '{purpose}'", code="INVALID_LAST_SCENE_PURPOSE")
                if cam and scene1_movement:
                    last_mv = self._nested(cam, "movement", "")
                    if last_mv and scene1_movement.upper() == last_mv.upper():
                        self._warn(f"{prefix}.camera_intent.movement", f"Same as Scene 1 — use complementary")

            # Scene N-1 rules
            if sn == total - 1:
                if purpose not in ("AERIAL", "AERIAL_WOW", "AERIAL_REVEAL"):
                    self._warn(f"{prefix}.narrative_purpose", f"N-1 should be AERIAL, got '{purpose}'")
                wl = self._data.get("warning_line")
                if wl and isinstance(wl, str):
                    vs = self._nested(scene, "voiceover_segment", "")
                    if isinstance(vs, str):
                        wl_cmp = re.sub(r'\[[\w\s]+\]\s*', '', wl).strip().rstrip(".")
                        vs_cmp = re.sub(r'\[[\w\s]+\]\s*', '', vs)
                        if wl_cmp.lower() not in vs_cmp.lower():
                            self._warn(f"{prefix}.voiceover_segment", f"warning_line not found in N-1 VO")

        if low_count > 1:
            self._warn("scenes", f"{low_count} LOW energy scenes (max 1 recommended)")

        # Dual identity aggregate check
        if dual_id_checked > 0 and dual_id_missing > dual_id_checked * 0.5:
            self._warn("on_screen_text.dual_identity",
                        f"{dual_id_missing}/{dual_id_checked} middle scenes lack architectural form words — "
                        f"mute viewers miss dual identity (>50%)")

        # Money shot count
        ms_count = sum(1 for s in scenes if isinstance(s, dict) and isinstance(s.get("money_shot"), dict) and s["money_shot"].get("is_money_shot"))
        if ms_count == 0:
            self._warn("scenes", "No money_shot scene (exactly 1 required)")
        elif ms_count > 1:
            self._warn("scenes", f"{ms_count} money_shot scenes (exactly 1 allowed)")

        # Money shot timing — must be in optimal range [ceil(N*0.6), ceil(N*0.8)]
        lower = math.ceil(total * 0.6)
        upper = math.ceil(total * 0.8)
        for i, s in enumerate(scenes):
            if isinstance(s, dict) and isinstance(s.get("money_shot"), dict) and s["money_shot"].get("is_money_shot"):
                msn = s.get("scene_number", i + 1)
                if msn < lower or msn > upper:
                    self._warn(f"scenes[{i}].money_shot",
                               f"money_shot Scene {msn} outside optimal range ({lower}-{upper})")

    def _validate_sensory_pressure(self) -> None:
        scenes = self._data.get("scenes", [])
        if not isinstance(scenes, list):
            return
        sp_pairs = []  # (scene_index, sp_value)
        for i, s in enumerate(scenes):
            if not isinstance(s, dict):
                continue
            sp = s.get("sensory_pressure")
            if sp is not None:
                try:
                    sp_pairs.append((i, int(sp) if not isinstance(sp, int) else sp))
                except (ValueError, TypeError):
                    pass
        if not sp_pairs:
            self._warn("scenes.sensory_pressure", "No SP values found")
            return
        sp_vals = [sp for _, sp in sp_pairs]
        for scene_idx, sp in sp_pairs:
            if sp < 1 or sp > 10:
                self._warn(f"scenes[{scene_idx}].sensory_pressure", f"SP {sp} out of range (1-10)")
        avg = sum(sp_vals) / len(sp_vals)
        if avg < 5:
            self._warn("scenes.sensory_pressure", f"Average {avg:.1f} too low (min 5.0)")
        peak = max(sp_vals)
        if peak < 9:
            self._warn("scenes.sensory_pressure", f"Peak {peak} too low (need ≥9)")
        if sp_pairs and (sp_pairs[0][1] < 5 or sp_pairs[0][1] > 8):
            self._warn(f"scenes[{sp_pairs[0][0]}].sensory_pressure", f"Scene 1 SP should be 5-8, got {sp_pairs[0][1]}")
        if len(sp_pairs) >= 2 and (sp_pairs[-1][1] < 5 or sp_pairs[-1][1] > 8):
            self._warn(f"scenes[{sp_pairs[-1][0]}].sensory_pressure", f"Last SP should be 5-8, got {sp_pairs[-1][1]}")

    def _validate_total_duration(self) -> None:
        scenes = self._data.get("scenes", [])
        total_dur = 0.0
        for s in scenes:
            if isinstance(s, dict):
                d = s.get("duration_seconds")
                if d is not None:
                    try:
                        total_dur += float(d)
                    except (ValueError, TypeError):
                        pass
        if total_dur <= 0:
            return
        if total_dur > 20:
            self._warn("total_duration", f"{total_dur:.1f}s exceeds 20s max")
        elif total_dur > 18:
            self._warn("total_duration", f"{total_dur:.1f}s long (13-16s preferred)")
        elif total_dur < 12:
            self._warn("total_duration", f"{total_dur:.1f}s too short (min ~12s)")

    def _validate_top_level_fields(self) -> None:
        cr = self._data.get("_concept_reasoning") or self._data.get("concept_reasoning")
        if not cr or (isinstance(cr, str) and not cr.strip()):
            self._warn("_concept_reasoning", "Missing or empty — required as first field")

        # --- P0 Required fields (pipeline crash if missing) ---
        loop = self._data.get("loop")
        if not isinstance(loop, dict):
            self._error("loop", "Missing loop object — pipeline cannot generate loop transition", code="MISSING_LOOP")
        else:
            for f in ("technique", "scene_n_exit", "scene_1_entry"):
                if not loop.get(f):
                    self._warn(f"loop.{f}", f"Missing '{f}'")

        ffc = self._data.get("first_frame_composition")
        if not isinstance(ffc, dict):
            self._error("first_frame_composition", "Missing — thumbnail generator needs composition data", code="MISSING_FIRST_FRAME")
        else:
            for f in ("dominant_subject", "silhouette_clarity", "pareidolia_element"):
                if not ffc.get(f):
                    self._warn(f"first_frame_composition.{f}", f"Missing '{f}'")

        tc = self._data.get("temperature_contrast")
        if not isinstance(tc, dict):
            self._error("temperature_contrast", "Missing — GEN2 needs global temperature guidance", code="MISSING_TEMP_CONTRAST")

        cb = self._data.get("completion_bait")
        if not isinstance(cb, dict):
            self._error("completion_bait", "Missing completion_bait object — no open loop for retention", code="MISSING_COMPLETION_BAIT")
        else:
            for f in ("scene_number", "technique", "vo_trigger"):
                if not cb.get(f):
                    self._warn(f"completion_bait.{f}", f"Missing '{f}'")
        scenes = self._data.get("scenes", [])
        has_recl = any(isinstance(s, dict) and s.get("food_reclamation") for s in scenes) if isinstance(scenes, list) else False
        if not has_recl:
            self._warn("scenes.food_reclamation", "No food_reclamation found (≥1 required)")
        eng = self._data.get("engagement", {})
        if isinstance(eng, dict):
            rh = eng.get("replay_hooks", [])
            if isinstance(rh, list) and len(rh) < 2:
                self._warn("engagement.replay_hooks", f"Only {len(rh)} hooks (min 2)")

    def _validate_cross_field_consistency(self) -> None:
        scenes = self._data.get("scenes", [])
        if not isinstance(scenes, list):
            return
        # full_script = concat of voiceover_segments
        vo = self._data.get("voiceover", {})
        fs = vo.get("full_script", "") if isinstance(vo, dict) else ""
        if fs and scenes:
            segs = []
            for s in scenes:
                if isinstance(s, dict):
                    seg = s.get("voiceover_segment", "")
                    # Skip [silence] — not spoken text, excluded from full_script
                    if seg and seg.strip() and seg.strip() != "[silence]":
                        segs.append(seg.strip())
            expected = " ".join(segs)
            if expected and fs.strip() != expected.strip():
                self._warn("voiceover.full_script", "Doesn't match concatenation of voiceover_segments")

        # completion_bait.vo_trigger in scene VO
        # Check declared scene first, then scan all scenes (autocorrect may relocate)
        # Also check partial match (first 2 words) since truncation may shorten it
        cb = self._data.get("completion_bait")
        if isinstance(cb, dict):
            vt = cb.get("vo_trigger", "")
            csn = cb.get("scene_number")
            if vt and csn is not None:
                vt_clean = vt.rstrip(".…").strip()
                vt_words = vt_clean.split()
                # Build match candidates: full trigger + first 2 words (for truncated matches)
                candidates = [vt_clean]
                if len(vt_words) >= 2:
                    candidates.append(" ".join(vt_words[:2]))
                found = False
                # Scan all scenes (trigger may have been relocated or truncated)
                for s in scenes:
                    if isinstance(s, dict):
                        seg = s.get("voiceover_segment", "")
                        if isinstance(seg, str):
                            seg_clean = re.sub(r'\[[\w\s]+\]', '', seg).strip()
                            for c in candidates:
                                if c.lower() in seg_clean.lower():
                                    found = True
                                    break
                        if found:
                            break
                if not found:
                    self._warn("completion_bait.vo_trigger", f"Not found in any scene VO")
            res = cb.get("resolution_scene")
            if csn is not None and res is not None:
                try:
                    dist = int(res) - int(csn)
                    if dist > 3:
                        self._warn("completion_bait", f"Distance {dist} scenes (max 3)")
                except (TypeError, ValueError):
                    pass

        # micro_open_loop.setup_line ≠ completion_bait.vo_trigger
        vt2 = cb.get("vo_trigger", "") if isinstance(cb, dict) else ""
        if vt2:
            for s in scenes:
                if not isinstance(s, dict):
                    continue
                mol = s.get("micro_open_loop", {})
                if isinstance(mol, dict):
                    sl = mol.get("setup_line", "")
                    if sl and sl.strip().lower() == vt2.strip().lower():
                        self._warn(f"scenes[{s.get('scene_number', '?')}].micro_open_loop.setup_line", "Identical to vo_trigger — wasting retention slot")
                        break

    # ========================================================================
    # NEW v2.0 VALIDATIONS
    # ========================================================================

    def _validate_structural_counts(self) -> None:
        """Validate exact-count structural requirements."""
        scenes = self._data.get("scenes", [])
        if not isinstance(scenes, list):
            return
        total = len(scenes)

        # Exactly 1 STRUCTURAL_DETAIL
        sd_count = sum(1 for s in scenes if isinstance(s, dict) and s.get("narrative_purpose") == "STRUCTURAL_DETAIL")
        if sd_count == 0:
            self._warn("scenes", "No STRUCTURAL_DETAIL scene (exactly 1 required)")
        elif sd_count > 1:
            self._warn("scenes", f"{sd_count} STRUCTURAL_DETAIL scenes (exactly 1 allowed)")

        # Exactly 1 pattern_interrupt
        pi_count = sum(1 for s in scenes if isinstance(s, dict) and s.get("pattern_interrupt"))
        if pi_count == 0:
            self._warn("scenes", "No pattern_interrupt (exactly 1 required)")
        elif pi_count > 1:
            self._warn("scenes", f"{pi_count} pattern_interrupts (exactly 1 allowed)")

        # micro_open_loop max 2, only scenes 2-3
        mol_scenes = []
        for s in scenes:
            if isinstance(s, dict) and s.get("micro_open_loop"):
                mol_scenes.append(s.get("scene_number", 0))
        if len(mol_scenes) > 2:
            self._warn("scenes.micro_open_loop", f"{len(mol_scenes)} micro_open_loops (max 2)")
        for msn in mol_scenes:
            if msn not in (2, 3):
                self._warn(f"scenes[{msn}].micro_open_loop", f"micro_open_loop in Scene {msn} (only 2-3 allowed)")

        # sfx_per_scene must cover ALL scenes
        audio = self._data.get("audio", {})
        sfx = audio.get("sfx_per_scene", []) if isinstance(audio, dict) else []
        if isinstance(sfx, list):
            covered = set()
            for item in sfx:
                if isinstance(item, dict):
                    covered.add(item.get("scene"))
            missing = set(range(1, total + 1)) - covered
            if missing:
                self._warn("audio.sfx_per_scene", f"Missing scenes: {sorted(missing)}")

        # Temperature contrast same-temp ban
        tc = self._data.get("temperature_contrast")
        if isinstance(tc, dict):
            st = tc.get("subject_temp", "").upper()
            bt = tc.get("background_temp", "").upper()
            if st and bt and st == bt:
                self._warn("temperature_contrast", f"Same temp subject={st}, bg={bt} — need contrast")

    def _validate_sensory_channels(self) -> None:
        """4-channel sensory audit: THERMAL, TACTILE, OLFACTORY, TEMPORAL FRESHNESS."""
        scenes = self._data.get("scenes", [])
        if not isinstance(scenes, list):
            return
        all_vo = ""
        for s in scenes:
            if isinstance(s, dict):
                vo = s.get("voiceover_segment", "")
                if isinstance(vo, str) and vo.strip() != "[silence]":
                    all_vo += " " + vo.lower()
        if not all_vo.strip():
            return
        clean = re.sub(r'\[[\w\s]+\]', '', all_vo)
        has_thermal = any(re.search(r'\b' + re.escape(w) + r'\b', clean) for w in _THERMAL_WORDS)
        has_tactile = any(re.search(r'\b' + re.escape(w) + r'\b', clean) for w in _TACTILE_WORDS)
        has_olfactory = any(re.search(r'\b' + re.escape(w) + r'\b', clean) for w in _OLFACTORY_WORDS)
        has_temporal = (
            any(p.search(clean) for p in _TEMPORAL_PATTERNS)
            or any(re.search(r'\b' + re.escape(w) + r'\b', clean) for w in _TEMPORAL_ACTIVE_WORDS)
        )
        missing = []
        if not has_thermal:
            missing.append("THERMAL")
        if not has_tactile:
            missing.append("TACTILE")
        if not has_olfactory:
            missing.append("OLFACTORY")
        if not has_temporal:
            missing.append("TEMPORAL FRESHNESS")
        if missing:
            self._warn("voiceover.sensory_channels", f"Missing channels: {', '.join(missing)}", suggestion="Each channel must appear in ≥1 voiceover_segment")

    def _validate_sp_curve_rules(self) -> None:
        """Advanced SP curve rules: peak position, adjacency, post-peak drop."""
        scenes = self._data.get("scenes", [])
        if not isinstance(scenes, list):
            return
        sp_vals = []
        for s in scenes:
            if isinstance(s, dict):
                sp = s.get("sensory_pressure")
                if sp is not None:
                    try:
                        sp_vals.append(int(sp))
                    except (ValueError, TypeError):
                        sp_vals.append(0)
                else:
                    sp_vals.append(0)
        if not sp_vals or max(sp_vals) == 0:
            return
        total = len(sp_vals)

        # SP peak position check (two tiers)
        peak_idx = sp_vals.index(max(sp_vals))
        half_point = total // 2  # first half boundary
        last_third_start = total * 2 // 3
        if max(sp_vals) >= 9:
            if peak_idx < half_point:
                # Peak in first half = ERROR (creates boring second half, kills completion)
                self._error("scenes.sensory_pressure",
                            f"Peak SP={max(sp_vals)} at Scene {peak_idx+1}/{total} — in first half! "
                            f"Must be Scene {half_point+1}+ (completion rate drops when climax is too early)",
                            code="SP_PEAK_FIRST_HALF")
            elif peak_idx < last_third_start:
                self._warn("scenes.sensory_pressure",
                           f"Peak SP at Scene {peak_idx+1} — should be in last third (Scene {last_third_start+1}+)")

        # SP 9-10 not adjacent
        for i in range(len(sp_vals) - 1):
            if sp_vals[i] >= 9 and sp_vals[i+1] >= 9:
                self._warn(f"scenes.sensory_pressure", f"SP 9+ adjacent: Scene {i+1} ({sp_vals[i]}) and Scene {i+2} ({sp_vals[i+1]})")

        # After peak SP → next ≤ 4
        if peak_idx < len(sp_vals) - 1:
            next_sp = sp_vals[peak_idx + 1]
            if max(sp_vals) >= 9 and next_sp > 4:
                self._warn(f"scenes[{peak_idx+1}].sensory_pressure", f"Post-peak SP={next_sp} (should be ≤4 for contrast)")

        # At least 1 SP 8-9 before money shot (ramp)
        ms_idx = None
        for i, s in enumerate(scenes):
            if isinstance(s, dict) and isinstance(s.get("money_shot"), dict) and s["money_shot"].get("is_money_shot"):
                ms_idx = i
                break
        if ms_idx is not None and ms_idx > 0:
            has_ramp = any(8 <= sp <= 9 for sp in sp_vals[:ms_idx])
            if not has_ramp:
                self._warn("scenes.sensory_pressure", f"No SP 8-9 ramp before money_shot (Scene {ms_idx+1})")

    def _validate_humor(self) -> None:
        """Validate humor array: count, types, placement."""
        humor = self._data.get("humor")
        if humor is None or not isinstance(humor, list):
            self._warn("humor", "Missing humor array (exactly 2 entries required)")
            return
        if len(humor) < 2:
            self._warn("humor", f"Only {len(humor)} humor beat(s) (exactly 2 required)")
        # Duplicate humor_type check
        types_seen: list = []
        deadpan_count = 0
        for i, h in enumerate(humor):
            if not isinstance(h, dict):
                continue
            ht = h.get("humor_type", "")
            if ht in types_seen:
                self._warn(f"humor[{i}].humor_type", f"Duplicate humor_type '{ht}' (each joke must use a different type)")
            types_seen.append(ht)
            if ht == "DEADPAN_CONSEQUENCE":
                deadpan_count += 1
        if deadpan_count > 1:
            self._warn("humor", f"DEADPAN_CONSEQUENCE used {deadpan_count}x (max 1 per video)")
        # Humor in high-SP scenes check
        scenes = self._data.get("scenes", [])
        sp_map: dict = {}
        for s in scenes:
            if isinstance(s, dict):
                sn = s.get("scene_number")
                sp = s.get("sensory_pressure")
                if sn is not None and sp is not None:
                    try:
                        sp_map[int(sn)] = int(sp)
                    except (ValueError, TypeError):
                        pass
        for i, h in enumerate(humor):
            if not isinstance(h, dict):
                continue
            hsn = h.get("scene_number")
            if hsn is not None:
                try:
                    sp_val = sp_map.get(int(hsn))
                    if sp_val is not None and sp_val > 6:
                        self._warn(f"humor[{i}]", f"Humor in Scene {hsn} (SP={sp_val}) — jokes only in SP ≤ 6 scenes")
                except (ValueError, TypeError):
                    pass

    def _validate_dominant_color_appetite(self) -> None:
        """Warn when food-dominant scenes use appetite-killing dominant_color."""
        scenes = self._data.get("scenes", [])
        if not isinstance(scenes, list):
            return
        # Check if food is cold (ice cream, frozen) — cold food gets a pass on blue
        food_identity = self._data.get("food_identity", {})
        is_cold_food = False
        if isinstance(food_identity, dict):
            atmos = food_identity.get("atmosphere", "")
            if isinstance(atmos, str) and any(w in atmos.lower() for w in ("cold", "frozen", "icy", "glacial")):
                is_cold_food = True
        for i, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                continue
            fvr = scene.get("food_visual_ratio", "")
            if fvr != "FOOD_DOMINANT":
                continue
            g2 = scene.get("gen2_visual_params")
            if not isinstance(g2, dict):
                continue
            dom_color = g2.get("dominant_color", "")
            if not isinstance(dom_color, str):
                continue
            dom_lower = dom_color.lower()
            # Skip cold-food exceptions
            if is_cold_food:
                continue
            for killer in _APPETITE_KILLER_COLORS:
                if killer in dom_lower:
                    self._warn(
                        f"scenes[{i}].gen2_visual_params.dominant_color",
                        f"Appetite-suppressing color '{dom_color}' in food-dominant scene",
                        suggestion="Use warm food color: golden, brown, amber, copper, caramel",
                    )
                    break

    def _validate_money_shot_saliva_trigger(self) -> None:
        """Ensure money_shot still_image_description contains a saliva trigger word."""
        scenes = self._data.get("scenes", [])
        if not isinstance(scenes, list):
            return
        for i, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                continue
            ms = scene.get("money_shot")
            if not isinstance(ms, dict) or not ms.get("is_money_shot"):
                continue
            desc = ms.get("still_image_description", "")
            if not isinstance(desc, str):
                continue
            desc_lower = desc.lower()
            has_trigger = any(re.search(r'\b' + re.escape(trigger) + r'\b', desc_lower) for trigger in _SALIVA_TRIGGERS)
            if not has_trigger:
                self._warn(
                    f"scenes[{i}].money_shot.still_image_description",
                    "No saliva trigger word found (craving anchor missing)",
                    suggestion="Include one of: stretching, dripping, cracking, melting, pouring, oozing, soaking, bubbling, sizzling",
                )
            break  # Only one money_shot

    def _validate_aerial_reveals_architecture(self) -> None:
        """Warn if AERIAL scene has FOOD_DOMINANT ratio — AERIAL should be BALANCED to show building form."""
        scenes = self._data.get("scenes", [])
        if not isinstance(scenes, list):
            return
        for i, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                continue
            purpose = scene.get("narrative_purpose", "")
            if not isinstance(purpose, str) or purpose.upper() not in ("AERIAL", "AERIAL_WOW", "AERIAL_REVEAL"):
                continue
            ratio = scene.get("food_visual_ratio", "")
            if isinstance(ratio, str) and ratio.upper() == "FOOD_DOMINANT":
                self._warn(
                    f"scenes[{i}].food_visual_ratio",
                    f"AERIAL scene is FOOD_DOMINANT — viewers may not see building form. Consider BALANCED.",
                    suggestion="AERIAL exists to reveal the building shape. FOOD_DOMINANT hides architecture.",
                )

    # ========================================================================
    # VO BUDGET VALIDATION (v2.8)
    # ========================================================================

    def _validate_vo_budget(self) -> None:
        """Validate total voiceover duration fits within target video length.

        Uses corrected ElevenLabs TTS rates from gen1_autocorrect._TTS_RATE.
        ratio > 1.3 → ERROR (triggers retry in prompt_router)
        ratio > 1.15 → WARNING (tight but passable)
        """
        scenes = self._data.get("scenes")
        if not isinstance(scenes, list) or not scenes:
            return

        # Get target duration
        target = 16.0
        meta = self._data.get("metadata")
        if isinstance(meta, dict):
            try:
                target = float(meta.get("target_duration_seconds", 16))
            except (ValueError, TypeError):
                target = 16.0

        total_est = 0.0
        scene_details = []  # (scene_number, word_count, est_seconds)

        for i, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                continue

            vo = scene.get("voiceover_segment", "")
            if not isinstance(vo, str) or not vo.strip() or vo.strip() == "[silence]":
                continue

            # Detect delivery style
            vo_lower = vo.lower()
            style = "default"
            for tag in ("whispers", "drawn out", "calm", "gentle"):
                if f"[{tag}]" in vo_lower:
                    style = tag
                    break

            # Count pauses
            pause_time = _estimate_pause_time(vo)

            # Count content words (strip all [tags])
            words = [w_ for w_ in re.sub(r'\[.*?\]', '', vo).split() if w_.strip()]
            word_count = len(words)
            word_time = word_count * _TTS_RATE.get(style, 0.45)

            scene_est = word_time + pause_time
            total_est += scene_est

            sn = scene.get("scene_number", i + 1)
            scene_details.append((sn, word_count, scene_est, style))

        if target <= 0:
            return

        ratio = total_est / target

        # Find heaviest scenes for diagnostic
        scene_details.sort(key=lambda x: x[2], reverse=True)
        top3 = scene_details[:3]
        heaviest_str = ", ".join(
            f"S{sn}={wc}w/{est:.1f}s({sty})" for sn, wc, est, sty in top3
        )

        total_words = sum(wc for _, wc, _, _ in scene_details)
        word_budget = int(target * 0.75)

        if ratio > 1.3:
            self._error(
                "voiceover.total_budget",
                f"Total VO ~{total_est:.1f}s for {target:.0f}s video "
                f"(ratio {ratio:.2f}x). Total words: {total_words}, "
                f"budget: ~{word_budget} words. "
                f"Heaviest: {heaviest_str}. "
                f"Shorten narrator_script across scenes to fit ≤{word_budget} total words.",
                code="VO_BUDGET_EXCEEDED",
                suggestion=f"Target ≤{word_budget} total narrator_script words for a {target:.0f}s video. "
                           f"Current {total_words} words produce ~{total_est:.1f}s of audio.",
            )
        elif ratio > 1.15:
            self._warn(
                "voiceover.total_budget",
                f"VO budget tight: ~{total_est:.1f}s for {target:.0f}s video "
                f"(ratio {ratio:.2f}x). Total words: {total_words}, "
                f"budget: ~{word_budget}. Heaviest: {heaviest_str}.",
                suggestion=f"Consider trimming to ≤{word_budget} total words.",
            )

    # ========================================================================
    # HELPERS
    # ========================================================================

    def _get_field(self, name: str) -> Optional[Any]:
        val = self._data.get(name)
        if val is None:
            self._error(name, "Required field missing", code=f"MISSING_{name.upper()}")
        return val

    def _nested(self, obj: dict, key: str, default: Any = None) -> Any:
        return obj.get(key, default) if isinstance(obj, dict) else default

    def _require(self, obj: dict, key: str, path: str) -> bool:
        if not self._nested(obj, key):
            self._error(path, "Required and cannot be empty", code="EMPTY_FIELD")
            return False
        return True

    def _check_enum(self, value: Any, valid: list, path: str) -> bool:
        if value is None:
            self._error(path, "Required field missing", code="MISSING_ENUM")
            return False
        if value not in valid:
            if path in self._SOFT_ENUMS:
                self._warn(path, f"Non-standard: '{value}'", suggestion=f"Standard: {', '.join(valid[:5])}...")
                return True
            self._error(path, f"Invalid: '{value}'", code="INVALID_ENUM", suggestion=f"Must be: {', '.join(valid)}")
            return False
        return True

    def _error(self, field: str, message: str, code: str = "", suggestion: str = "") -> None:
        self._errors.append(ValidationError(field=field, message=message, severity="error", code=code, suggestion=suggestion))

    def _warn(self, field: str, message: str, suggestion: str = "") -> None:
        self._warnings.append(ValidationError(field=field, message=message, severity="warning", suggestion=suggestion))

    def _build_summary(self) -> Dict[str, Any]:
        """Build minimal validation summary for backward compat."""
        meta = self._data.get("metadata", {})
        concept = meta.get("concept", {}) if isinstance(meta, dict) else {}
        light = self._data.get("lighting_master", {})
        scenes = self._data.get("scenes", [])
        return {
            "atmosphere_mode": self._data.get("atmosphere_mode", "CINEMATIC"),
            "lighting_preset": light.get("preset", "") if isinstance(light, dict) else "",
            "category": concept.get("category", "") if isinstance(concept, dict) else "",
            "food_material": concept.get("food_material", "") if isinstance(concept, dict) else "",
            "scene_count": len(scenes) if isinstance(scenes, list) else 0,
        }


# ============================================================================
# CONVENIENCE FUNCTION
# ============================================================================

def validate_gen1(data: Dict[str, Any], strict_mode: bool = False) -> ValidationResult:
    """Validate GEN1 JSON output.

    Args:
        data: GEN1 JSON as dict.
        strict_mode: If True, warnings also block. Default False.

    Returns:
        ValidationResult with errors, warnings, corrected_data.
    """
    return Gen1Validator(strict_mode=strict_mode).validate(data)


# ============================================================================
# EXPORT
# ============================================================================

__all__ = [
    "Gen1Validator",
    "ValidationResult",
    "ValidationError",
    "validate_gen1",
    # Banlist
    "get_banlist",
    "reload_banlist",
    "get_banned_first_words",
    "get_ai_markers",
    "get_fillers",
    # Constants
    "BANNED_CAMERA_MOVEMENTS",
    "ALL_ELEVENLABS_TAGS",
    "VALID_CAMERA_MOVEMENTS",
]
