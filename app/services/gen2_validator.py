"""
GEN2 Python Validator v1.0

Детермінований валідатор для виходу GEN2 (Visual Director).
Замінює LLM-валідатор VAL_GEN2.txt для швидшої та надійнішої валідації.

Автор: Senior Python Backend Engineer + QA Automation Engineer
Дата: 2025-01

Переваги над LLM-валідатором:
┌─────────────────┬──────────────┬─────────────────┐
│ Метрика         │ LLM (GPT-4)  │ Python          │
├─────────────────┼──────────────┼─────────────────┤
│ Час             │ ~10-15 сек   │ ~5 мс           │
│ Токени          │ ~4000-6000   │ 0               │
│ Детермінізм     │ Ні           │ Так             │
│ Галюцинації     │ Можливі      │ Неможливі       │
└─────────────────┴──────────────┴─────────────────┘

Використання:
    from app.services.gen2_validator import Gen2Validator, validate_gen2

    validator = Gen2Validator()
    result = validator.validate(gen2_json_data)

    if result.passed:
        proceed_to_img_gen()
    else:
        for error in result.errors:
            print(error)
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from loguru import logger


# ============================================================================
# ENUMS — Дозволені значення
# ============================================================================

class ReferenceType(str, Enum):
    """Reference types для сцен."""
    PRIMARY = "PRIMARY"
    REQUIRES_REF = "REQUIRES_REF"
    INDEPENDENT = "INDEPENDENT"
    LOOP_CLOSE = "LOOP_CLOSE"


# ============================================================================
# CONSTANTS — Правила валідації з VAL_GEN2.txt
# ============================================================================

# Мінімальна кількість motion_elements
MIN_MOTION_ELEMENTS: int = 2  # GEN2.txt: MEDIUM=2-3, LOW=2, HIGH=3+, EXPLOSIVE=4+

# Максимальна кількість слів у video_prompt
MAX_VIDEO_PROMPT_WORDS: int = 40

# Мінімальна кількість scale keywords для Scene 1
MIN_SCALE_KEYWORDS: int = 2

# Scale keywords для Scene 1 (VAL_GEN2 рядок 457-463)
SCALE_KEYWORDS: Set[str] = {
    "towering", "imposing", "massive", "low angle", "looking up",
    "enormous", "colossal", "vast", "monumental", "gigantic",
}

# Anti-toy keywords в negative_prompt (VAL_GEN2 рядок 246)
ANTI_TOY_KEYWORDS: Set[str] = {
    "tilt-shift", "miniature", "diorama", "toy"
}

# Anti-yellow keywords в negative_prompt (GEN2 v6.1.0 Color Accuracy Doctrine)
ANTI_YELLOW_KEYWORDS: Set[str] = {
    "yellow color cast", "sepia tone"
}

# Full mandatory base negative keywords (GEN2.txt line 451)
MANDATORY_NEGATIVE_KEYWORDS: Set[str] = {
    "tilt-shift", "miniature", "diorama", "toy",
    "small scale", "plastic", "fake", "3d render", "isometric",
    "text", "watermark", "cute", "tiny", "dollhouse",
    "yellow color cast", "sepia tone", "amber tint",
}

# Banned words у video_prompt (VAL_GEN2 рядки 308-315)
BANNED_VIDEO_WORDS: Set[str] = {
    "slow", "slowly",
    "gentle", "gently",
    "subtle", "subtly",
    "calm",
    "gradual", "gradually",
    "leisurely",
    "accelerating",
    "rack focus", "speed ramp", "dolly zoom",
    "slo-mo",
}

# Banned camera movements (VAL_GEN2 рядки 316-323)
# Note: "drifting/floating" for objects (clouds, particles) is OK
#       Only banned when referring to CAMERA movement
BANNED_CAMERA_MOVEMENTS: Set[str] = {
    "drifting", "floating", "gliding",
    "drift", "float", "glide",
    "pan", "panning",
}

# Patterns where drifting/floating is OK (object motion, not camera)
ALLOWED_DRIFTING_CONTEXTS: Set[str] = {
    # "subject drifting/floating" patterns
    "clouds drifting",
    "cloud drifting",
    "smoke drifting",
    "mist drifting",
    "particles drifting",
    "leaves drifting",
    "petals drifting",
    "plankton drifting",
    "dust drifting",
    "snow drifting",
    "fog drifting",
    "clouds floating",
    "particles floating",
    "debris floating",
    "dust floating",
    "motes floating",
    "plankton floating",
    "bubbles floating",
    "jellyfish floating",
    "pollen floating",
    "embers floating",
    "snowflakes floating",
    # reversed word order: "drifting/floating subject"
    "drifting clouds",
    "drifting cloud",
    "drifting smoke",
    "drifting mist",
    "drifting particles",
    "drifting leaves",
    "drifting petals",
    "drifting plankton",
    "drifting dust",
    "drifting snow",
    "drifting fog",
    "floating clouds",
    "floating particles",
    "floating debris",
    "floating dust",
    "floating motes",
    "floating plankton",
    "floating bubbles",
    "floating jellyfish",
    "floating pollen",
    "floating embers",
    "floating snowflakes",
}

# Allowed camera movements (gerunds) (VAL_GEN2 рядки 324-326)
ALLOWED_CAMERA_MOVEMENTS: Set[str] = {
    "pushing", "pulling", "orbiting", "rising", "descending",
    "tracking", "emerging", "crane", "craning", "ascending"
}

# Meta-instructions заборонені в video prompts (GEN2.txt lines 909-918)
BANNED_VIDEO_META: Set[str] = {
    "matching scene 1",
    "matching opening shot",
    "(reverse in post)",
    "reverse in post",
    "same as before",
    "like earlier",
    "10s",
    "10 seconds",
}

# Meta-instructions заборонені в last scene (LOOP_CLOSE) video prompts
BANNED_LAST_SCENE_META: Set[str] = {
    "matching scene 1",
    "matching opening shot",
    "matching opening",
    "same as scene 1",
    "identical",
    "mirroring",
    "(reverse in post)",
    "reverse in post",
    "opening shot",
}

# Meta-instruction patterns заборонені в image prompts (GEN2.txt lines 392-439)
IMAGE_META_PATTERNS: List[str] = [
    r'\bfrom\s+(back|top|side|front|above|below)\b',
    r'\bper\s+(clear|light|heavy|fog)\b',
    r'\bscene\s+\d',
    r'\bidentical\b',
    r'\bopening\s+shot\b',
    r'\bmatching\s+scene\b',
]

# Banned meta-instructions in LOOP_CLOSE image_prompt (CRITICAL #1)
BANNED_LOOP_IMAGE_META: Set[str] = {
    "identical", "matching scene", "same as scene", "mirroring",
    "opening shot", "scene 1", "same as opening",
}

# Banned human presence indicators in image_prompts (CRITICAL #3)
# GEN2.txt: food architecture — NO humans
BANNED_HUMAN_INDICATORS_RE = re.compile(
    r'\b(?:person|people|human|silhouette|crowd|pedestrian|'
    r'man\b(?!\s*(?:go|made|ner))|woman|child(?:ren)?|'
    r'tourist|visitor|passerby|bystander)\b',
    re.IGNORECASE,
)

# Scene reference pattern in post_production_notes (CRITICAL #2)
_SCENE_REF_RE = re.compile(
    r'\b(?:scene\s+\d|match(?:ing)?\s+scene|from\s+scene)\b',
    re.IGNORECASE,
)

# Reversal-unsafe motion words — unified constant for last scene checks (HIGH #3)
REVERSAL_UNSAFE_WORDS: Set[str] = {
    "rising", "falling", "dripping", "pouring", "cascading",
    "sinking", "dropping", "growing", "waterfall", "fire",
    "flames", "walking", "running", "vehicles", "birds flying",
}

# Per-tier image_prompt word count ranges (HIGH #1)
IMAGE_WORD_COUNT_RANGES: Dict[str, Tuple[int, int]] = {
    "TIER_1_MONEY_SHOT": (130, 160),
    "TIER_2_HIGH_APPETITE": (60, 120),
    "TIER_3_BALANCED": (40, 100),
    "TIER_4_ARCHITECTURE": (50, 120),
}

# GEN1 fields that GEN2 must NOT duplicate (GEN2.txt lines 1406-1417)
FORBIDDEN_GEN1_FIELDS: Set[str] = {
    "scene_name", "duration_seconds", "narrative_purpose", "reference_hint",
    "energy_level", "visual_concept", "camera_intent", "gen2_visual_params",
    "narrator_script", "voiceover_segment", "audio_moment", "audio_texture_layer",
    "sensory_pressure", "money_shot", "temperature_contrast", "scene_tricks",
}

# Valid atmosphere modes (GEN2.txt lines 789-807)
VALID_ATMOSPHERE_MODES: Set[str] = {
    "CINEMATIC", "VIBRANT", "PLAYFUL", "GOLDEN_WARM",
    "TROPICAL", "ETHEREAL", "NOIR", "HAUNTED",
}

# Atmosphere-specific negative prompt additions (GEN2.txt lines 789-807)
ATMOSPHERE_NEGATIVE_ADDITIONS: Dict[str, List[str]] = {
    "NOIR": ["flat lighting", "even illumination"],
    "HAUNTED": ["flat lighting", "even illumination"],
    "ETHEREAL": ["harsh shadows", "high contrast"],
}

# Valid scale_mode values (GEN2.txt lines 228-234)
VALID_SCALE_MODES: Set[str] = {"APPETITE", "BALANCED", "ARCHITECTURE"}

# Easter egg forbidden zones (VAL_GEN2 рядки 403-407)
FORBIDDEN_EGG_ZONES: Set[str] = {"bottom-center", "bottom center"}
WARNING_EGG_ZONES: Set[str] = {"bottom-left", "bottom-right", "bottom left", "bottom right"}
SAFE_EGG_ZONES: Set[str] = {
    "top-left", "top-right", "center-left", "center-right",
    "top left", "top right", "center left", "center right",
    "center", "top", "top-center", "top center"
}

# Exterior scenes що потребують scale_techniques
# Dynamically computed in validator based on narrative_purpose
# Scene 1 + scenes with AERIAL/ESTABLISHING/LOOP_CLOSE purpose
EXTERIOR_SCENES_BASE: Set[int] = {1}  # Scene 1 always exterior

# Physical state change verbs — used to detect "animated image" risk.
# Scenes with ONLY ambient motion (light, shadows, fog) and no physical state
# change will be rendered by Kling as Ken Burns still images.
# Synced with gen2_autocorrect.py _PHYSICAL_STATE_CHANGE_RE
_PHYSICAL_STATE_CHANGE_RE = re.compile(
    r'\b(?:'
    r'drip(?:ping|s)?|flow(?:ing|s)?|pour(?:ing|s)?|cascad(?:ing|e|es)?|'
    r'splash(?:ing|es)?|spill(?:ing|s)?|pool(?:ing|s)?|seep(?:ing|s)?|'
    r'leak(?:ing|s)?|trickl(?:ing|e|es)?|drizzl(?:ing|e|es)?|'
    r'welling|spray(?:ing|s)?|ooz(?:ing|e|es)?|'
    r'crack(?:ing|s)?|shatter(?:ing|s)?|break(?:ing|s)?|fractur(?:ing|e|es)?|'
    r'split(?:ting|s)?|tear(?:ing|s)?|crumbl(?:ing|e|es)?|collaps(?:ing|e|es)?|'
    r'melt(?:ing|s)?|bubbl(?:ing|e|es)?|sizzl(?:ing|e|es)?|erupt(?:ing|s)?|'
    r'boil(?:ing|s)?|'
    r'stretch(?:ing|es)?|swell(?:ing|s)?|burst(?:ing|s)?|'
    r'rippl(?:ing|e|es)?'
    r')\b', re.IGNORECASE,
)


# ============================================================================
# VALIDATION ERROR — Структурована помилка
# ============================================================================

@dataclass
class ValidationError:
    """
    Структурована помилка валідації.

    Attributes:
        field: Шлях до поля (напр. "scenes[0].video_prompt")
        message: Опис помилки
        severity: "error" або "warning"
        code: Код помилки для програмної обробки
        suggestion: Пропозиція як виправити (опціонально)
    """
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
        return {
            "field": self.field,
            "message": self.message,
            "severity": self.severity,
            "code": self.code,
            "suggestion": self.suggestion
        }


# ============================================================================
# SCENE CHECK RESULT — Результат перевірки сцени
# ============================================================================

@dataclass
class SceneCheckResult:
    """Результат перевірки окремої сцени."""
    scene: int
    image_prompt: str = "PASS"
    video_prompt: str = "PASS"
    motion_elements: str = "PASS"
    scale_techniques: str = "N/A"
    inheritance: str = "N/A"
    easter_egg: str = "N/A"
    loop_complementary: str = "N/A"

    def to_dict(self) -> Dict[str, str]:
        result = {
            "scene": self.scene,
            "image_prompt": self.image_prompt,
            "video_prompt": self.video_prompt,
            "motion_elements": self.motion_elements,
        }
        if self.scale_techniques != "N/A":
            result["scale_techniques"] = self.scale_techniques
        if self.inheritance != "N/A":
            result["inheritance"] = self.inheritance
        if self.easter_egg != "N/A":
            result["easter_egg"] = self.easter_egg
        if self.loop_complementary != "N/A":
            result["loop_complementary"] = self.loop_complementary
        return result


# ============================================================================
# VALIDATION RESULT — Результат валідації
# ============================================================================

@dataclass
class Gen2ValidationResult:
    """
    Результат валідації GEN2.

    Сумісний з Gen2ValidationResponse з validation_models.py
    """
    passed: bool
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[ValidationError] = field(default_factory=list)
    scene_checks: List[SceneCheckResult] = field(default_factory=list)

    # Детальні перевірки
    gigantism_check: Dict[str, str] = field(default_factory=dict)
    loop_check: Dict[str, str] = field(default_factory=dict)

    # Auto-fix tracking
    auto_fixes: List[str] = field(default_factory=list)

    # Метадані
    validation_time_ms: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now().astimezone().isoformat())
    validator_version: str = "1.1"

    @property
    def error_messages(self) -> List[str]:
        """Список текстових повідомлень про помилки."""
        return [str(e) for e in self.errors]

    @property
    def warning_messages(self) -> List[str]:
        """Список текстових попереджень."""
        return [str(w) for w in self.warnings]

    def to_dict(self) -> Dict[str, Any]:
        """Конвертувати в словник для JSON."""
        result = {
            "validation": {
                "stage": "VAL_GEN2_PYTHON",
                "version": self.validator_version,
                "timestamp": self.timestamp,
                "validation_time_ms": round(self.validation_time_ms, 2)
            },
            "phase1_structural": {
                "status": "PASS" if self.passed else "FAIL",
                "scene_checks": [sc.to_dict() for sc in self.scene_checks],
                "gigantism_check": self.gigantism_check,
                "loop_check": self.loop_check,
                "errors": [e.to_dict() for e in self.errors],
                "warnings": [w.to_dict() for w in self.warnings]
            },
            "phase2_quality": None,  # Пропускаємо суб'єктивні критерії
            "decision": {
                "status": "PASSED" if self.passed else "FAILED",
                "reasoning": self._build_reasoning(),
                "proceed_to": "IMG_GEN" if self.passed else None
            },
            "issues": {
                "has_issues": len(self.errors) > 0 or len(self.warnings) > 0,
                "concerns": [str(e) for e in self.errors + self.warnings]
            },
            "retry_guidance": self._build_retry_guidance() if not self.passed else None
        }
        if self.auto_fixes:
            result["auto_fixes"] = self.auto_fixes
        return result

    def _build_reasoning(self) -> str:
        if self.passed:
            if self.warnings:
                return f"Structural validation passed with {len(self.warnings)} warning(s). Ready for IMG_GEN."
            return "All structural checks passed. Ready for IMG_GEN."
        return f"Validation failed with {len(self.errors)} error(s). See retry_guidance."

    def _build_retry_guidance(self) -> Dict[str, Any]:
        fixes = []
        for error in self.errors:
            fix = f"Fix {error.field}: {error.message}"
            if error.suggestion:
                fix += f" ({error.suggestion})"
            fixes.append(fix)
        return {
            "fixes_needed": fixes,
            "regenerate": True
        }


# ============================================================================
# VALIDATOR CLASS
# ============================================================================

class Gen2Validator:
    """
    Детермінований Python-валідатор для GEN2 виходу.

    Замінює LLM-валідатор VAL_GEN2.txt.
    Фокусується на структурних перевірках, пропускає суб'єктивні критерії.
    """

    # Auto-replacement map for banned words (single best replacement)
    AUTO_REPLACEMENTS: Dict[str, str] = {
        "slow motion": "suspended mid-air",
        "slo-mo": "suspended mid-air",
        "slowly": "",
        "slow": "steady",
        "gentle": "soft",
        "gently": "softly",
        "subtle": "visible",
        "subtly": "visibly",
        "calm": "smooth",
        "gradual": "progressive",
        "gradually": "progressively",
        "leisurely": "measured",
        "accelerating": "",
        "rack focus": "",
        "speed ramp": "",
        "dolly zoom": "",
        "slo-mo": "suspended mid-air",
    }

    def __init__(self):
        self._errors: List[ValidationError] = []
        self._warnings: List[ValidationError] = []
        self._scene_checks: List[SceneCheckResult] = []
        self._auto_fixes: List[str] = []
        self._data: Dict[str, Any] = {}
        self._gen1_data: Optional[Dict[str, Any]] = None
        self._total_scenes: int = 0

        # Для loop verification
        self._scene1_movement: str = ""
        self._last_scene_movement: str = ""

    def validate(
        self,
        data: Dict[str, Any],
        gen1_data: Optional[Dict[str, Any]] = None,
        auto_fix: bool = True,
    ) -> Gen2ValidationResult:
        """
        Валідувати GEN2 JSON вихід.

        Args:
            data: Словник з GEN2 JSON виходом (modified in-place if auto_fix=True)
            gen1_data: Опціональний GEN1 вихід для cross-validation
            auto_fix: Якщо True, автоматично виправляти банальні помилки
                      (заборонені слова, "10s", "--ar 9:16") замість FAIL

        Returns:
            Gen2ValidationResult
        """
        start_time = time.perf_counter()

        # Reset state
        self._errors = []
        self._warnings = []
        self._scene_checks = []
        self._auto_fixes = []
        self._data = data
        self._gen1_data = gen1_data
        self._scene1_movement = ""
        self._last_scene_movement = ""
        # Pre-compute _total_scenes so it's always available (even if _validate_scenes returns early)
        scenes = data.get("scenes", [])
        self._total_scenes = len(scenes) if isinstance(scenes, list) else 0

        # Auto-fix common issues BEFORE validation (saves a full retry)
        if auto_fix:
            self._auto_fix_data()

        # Run validations
        self._run_all_validations()

        # Build result
        passed = len(self._errors) == 0
        validation_time_ms = (time.perf_counter() - start_time) * 1000

        result = Gen2ValidationResult(
            passed=passed,
            errors=self._errors.copy(),
            warnings=self._warnings.copy(),
            scene_checks=self._scene_checks.copy(),
            gigantism_check=self._build_gigantism_check(),
            loop_check=self._build_loop_check(),
            auto_fixes=self._auto_fixes.copy(),
            validation_time_ms=validation_time_ms
        )

        # Log result
        if passed:
            fix_msg = f", {len(self._auto_fixes)} auto-fixes" if self._auto_fixes else ""
            logger.success(
                f"GEN2 validation PASSED in {validation_time_ms:.2f}ms "
                f"({len(self._warnings)} warnings{fix_msg})"
            )
        else:
            logger.warning(
                f"GEN2 validation FAILED in {validation_time_ms:.2f}ms "
                f"({len(self._errors)} errors, {len(self._warnings)} warnings)"
            )

        return result

    # ========================================================================
    # AUTO-FIX — Pre-validation fixes that save a full GEN2 retry (~4400 tokens)
    # ========================================================================

    def _auto_fix_data(self) -> None:
        """
        Auto-fix common Gemini mistakes BEFORE validation.

        Fixes banned words, "10s" duration, "--ar 9:16" in prompts.
        Each fix is logged as a warning (not error) and tracked in auto_fixes.
        This prevents a full GEN2 retry that costs ~4400 tokens.
        """
        scenes = self._data.get("scenes", [])
        if not isinstance(scenes, list):
            return

        for i, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                continue

            # 1. Fix banned words in video_prompt
            video_prompt = scene.get("video_prompt", "")
            if video_prompt:
                fixed = self._replace_banned_words(video_prompt)
                if fixed != video_prompt:
                    scene["video_prompt"] = fixed
                    fix_desc = f"scenes[{i}].video_prompt: auto-replaced banned words"
                    self._auto_fixes.append(fix_desc)
                    self._add_warning(
                        f"scenes[{i}].video_prompt",
                        f"Auto-fixed banned words (saved a retry)",
                        suggestion=f"Original: ...{video_prompt[-60:]}",
                    )
                    logger.info(f"  [AUTO-FIX] {fix_desc}")

            # 2. Fix "10s" in video_prompt (hardcoded in software)
            video_prompt = scene.get("video_prompt", "")
            if re.search(r'\b10s\b', video_prompt):
                fixed = re.sub(r',?\s*\b10s\b', '', video_prompt).strip()
                fixed = re.sub(r'\s+', ' ', fixed).strip().rstrip(',')
                scene["video_prompt"] = fixed
                fix_desc = f"scenes[{i}].video_prompt: auto-removed '10s'"
                self._auto_fixes.append(fix_desc)
                logger.info(f"  [AUTO-FIX] {fix_desc}")

            # 3. Fix "slow motion"/"slo-mo" in image_prompt (banned in ALL prompts)
            image_prompt = scene.get("image_prompt", "")
            if image_prompt:
                fixed_img = re.sub(r'\bslow\s+motion\b', 'suspended mid-air', image_prompt, flags=re.IGNORECASE)
                fixed_img = re.sub(r'\bslo-mo\b', 'suspended mid-air', fixed_img, flags=re.IGNORECASE)
                if fixed_img != image_prompt:
                    scene["image_prompt"] = fixed_img
                    fix_desc = f"scenes[{i}].image_prompt: auto-replaced 'slow motion'/'slo-mo'"
                    self._auto_fixes.append(fix_desc)
                    logger.info(f"  [AUTO-FIX] {fix_desc}")
                    image_prompt = fixed_img

            # 4. Fix "--ar 9:16" in image_prompt (hardcoded in software)
            if "--ar 9:16" in image_prompt or "--ar 9\\:16" in image_prompt:
                fixed = image_prompt.replace("--ar 9:16", "").replace("--ar 9\\:16", "")
                fixed = re.sub(r'\s+', ' ', fixed).strip()
                scene["image_prompt"] = fixed
                fix_desc = f"scenes[{i}].image_prompt: auto-removed '--ar 9:16'"
                self._auto_fixes.append(fix_desc)
                logger.info(f"  [AUTO-FIX] {fix_desc}")

            # 5. Auto-fix banned camera movements in video_prompt (#19)
            video_prompt = scene.get("video_prompt", "")
            if video_prompt:
                _cam_replacements = {
                    "drifting": "pushing", "floating": "rising", "gliding": "tracking",
                    "drift": "push", "float": "rise", "glide": "track",
                    "panning": "orbiting", "pan": "orbit",
                }
                fixed_vp = video_prompt
                for banned_cam, replacement in _cam_replacements.items():
                    pattern = r'\b' + re.escape(banned_cam) + r'\b'
                    # Loop until no more replacements (re-scan after each to avoid index shift)
                    while True:
                        match = re.search(pattern, fixed_vp, re.IGNORECASE)
                        if not match:
                            break
                        start = max(0, match.start() - 100)
                        end = min(len(fixed_vp), match.end() + 50)
                        context = fixed_vp[start:end].lower()
                        is_allowed = any(ctx in context for ctx in ALLOWED_DRIFTING_CONTEXTS)
                        if not is_allowed:
                            fixed_vp = fixed_vp[:match.start()] + replacement + fixed_vp[match.end():]
                        else:
                            break  # This occurrence is allowed, stop checking this word
                if fixed_vp != video_prompt:
                    scene["video_prompt"] = fixed_vp
                    fix_desc = f"scenes[{i}].video_prompt: auto-replaced banned camera movement"
                    self._auto_fixes.append(fix_desc)
                    logger.info(f"  [AUTO-FIX] {fix_desc}")

    def _replace_banned_words(self, prompt: str) -> str:
        """
        Replace banned words in a video prompt with safe alternatives.

        Processes multi-word phrases first (e.g., "slow motion" before "slow"),
        then cleans up whitespace/punctuation artifacts.
        """
        fixed = prompt

        # Process multi-word replacements first (longest match first)
        for banned in sorted(self.AUTO_REPLACEMENTS.keys(), key=len, reverse=True):
            pattern = r'\b' + re.escape(banned) + r'\b'
            if re.search(pattern, fixed, re.IGNORECASE):
                replacement = self.AUTO_REPLACEMENTS[banned]
                fixed = re.sub(pattern, replacement, fixed, flags=re.IGNORECASE)

        # Clean up artifacts: double spaces, double commas, trailing commas
        fixed = re.sub(r'\s+', ' ', fixed).strip()
        fixed = re.sub(r',\s*,', ',', fixed)
        fixed = re.sub(r',\s*$', '', fixed)
        fixed = re.sub(r'^\s*,\s*', '', fixed)

        return fixed

    # ========================================================================
    # ORCHESTRATION
    # ========================================================================

    def _run_all_validations(self) -> None:
        """Запустити всі перевірки."""

        # 1. Global settings
        self._validate_global_settings()

        # 2. Visual summary
        self._validate_visual_summary()

        # 3. Scenes array
        self._validate_scenes()

        # 4. Loop verification (after scenes)
        self._validate_loop()

        # 5. TIER vs SP/money_shot cross-check (requires gen1_data)
        self._validate_tier_assignment()

        # 6. Image prompt word count hierarchy (money shot ≥130, longest)
        self._validate_word_count_hierarchy()

        # 7. body_trigger visual keywords in Scene 1
        self._validate_body_trigger()

        # 8. --no block in image_prompts
        self._validate_image_negative_blocks()

        # 9. GEN1 field duplication check
        self._validate_no_gen1_field_duplication()

        # 10. atmosphere_mode validation
        self._validate_atmosphere_mode()

        # 11. visual_punctuation for EXPLOSIVE scenes
        self._validate_visual_punctuation()

        # 12. loop_verification string fields + reversal_safe cross-check
        self._validate_loop_verification_details()

        # 13. tier_breakdown cross-validation
        self._validate_tier_breakdown()

        # 14. first_frame_composition.entry_type vs GEN1
        self._validate_entry_type()

        # 15. post_production_notes scene references (CRITICAL #2)
        self._validate_post_production_notes()

        # 16. No human figures in image_prompts (CRITICAL #3)
        self._validate_no_human_figures()

        # 17. Only one PRIMARY reference_type (CRITICAL #4)
        self._validate_primary_count()

    # ========================================================================
    # GLOBAL SETTINGS VALIDATION
    # ========================================================================

    def _validate_global_settings(self) -> None:
        """Валідація global_settings."""
        gs = self._data.get("global_settings")

        if not gs:
            self._add_error(
                "global_settings",
                "Required object is missing",
                code="MISSING_GLOBAL_SETTINGS"
            )
            return

        # gigantism_applied — adaptive per v6: depends on subject_scale
        # MACRO/INTIMATE/CLOSE_UP → false (APPETITE MODE), MASSIVE/TOWERING → true (ARCHITECTURE)
        # Accept both true and false; only warn if missing entirely
        if gs.get("gigantism_applied") is None:
            self._add_warning(
                "global_settings.gigantism_applied",
                "Field missing — should be true (architecture) or false (appetite/macro)",
                code="MISSING_GIGANTISM"
            )

        # negative_prompt
        negative = gs.get("negative_prompt", "")
        if not negative:
            self._add_error(
                "global_settings.negative_prompt",
                "Required field is missing",
                code="MISSING_NEGATIVE"
            )
        else:
            # Check for full mandatory base negative keywords (GEN2.txt line 451)
            negative_lower = negative.lower()
            missing_keywords = [kw for kw in MANDATORY_NEGATIVE_KEYWORDS if kw not in negative_lower]

            if missing_keywords:
                self._add_error(
                    "global_settings.negative_prompt",
                    f"Missing mandatory negative keywords: {', '.join(sorted(missing_keywords))}",
                    code="MISSING_NEGATIVE_KEYWORDS",
                    suggestion="Add all mandatory base negative keywords per GEN2.txt"
                )

    # ========================================================================
    # VISUAL SUMMARY VALIDATION
    # ========================================================================

    def _validate_visual_summary(self) -> None:
        """Валідація visual_summary."""
        vs = self._data.get("visual_summary")

        if not vs:
            self._add_error(
                "visual_summary",
                "Required object is missing",
                code="MISSING_VISUAL_SUMMARY"
            )
            return

        # total_scenes (6-10)
        total = vs.get("total_scenes")
        if total is not None and (total < 6 or total > 10):
            self._add_error(
                "visual_summary.total_scenes",
                f"Must be 6-10, got {total}",
                code="INVALID_TOTAL_SCENES"
            )

        # Cross-validate total_scenes vs actual scenes array length
        actual_scenes = self._data.get("scenes", [])
        actual_count = len(actual_scenes) if isinstance(actual_scenes, list) else 0
        if total is not None and actual_count > 0 and total != actual_count:
            self._add_error(
                "visual_summary.total_scenes",
                f"total_scenes={total} but scenes array has {actual_count} items",
                code="TOTAL_SCENES_MISMATCH"
            )

        # Cross-validate against GEN1 delivery scene count (M5)
        if self._gen1_data:
            gen1_scenes = self._gen1_data.get("scenes", [])
            gen1_count = len(gen1_scenes) if isinstance(gen1_scenes, list) else 0
            if gen1_count > 0 and actual_count > 0 and gen1_count != actual_count:
                self._add_warning(
                    "visual_summary.total_scenes",
                    f"GEN2 has {actual_count} scenes but GEN1 delivered {gen1_count}",
                    suggestion="GEN2 scene count should match GEN1 delivery"
                )

        # gigantism_protocol — adaptive: depends on global_settings.gigantism_applied
        gs = self._data.get("global_settings", {})
        gigantism_applied = gs.get("gigantism_applied") if gs else None
        gp = vs.get("gigantism_protocol")
        if gigantism_applied is True:
            # Architecture mode: protocol must be APPLIED
            if gp != "APPLIED":
                self._add_error(
                    "visual_summary.gigantism_protocol",
                    f"gigantism_applied=true but protocol is '{gp}' (expected 'APPLIED')",
                    code="GIGANTISM_NOT_APPLIED"
                )
        elif gigantism_applied is False:
            # Appetite/macro mode: protocol should be SKIPPED or N/A
            if gp == "APPLIED":
                self._add_warning(
                    "visual_summary.gigantism_protocol",
                    "gigantism_applied=false but protocol is 'APPLIED' — consider 'SKIPPED'",
                    suggestion="Set gigantism_protocol to 'SKIPPED' for appetite/macro subjects"
                )
        else:
            # gigantism_applied missing — accept APPLIED as default
            if gp not in ("APPLIED", "SKIPPED", None):
                self._add_warning(
                    "visual_summary.gigantism_protocol",
                    f"Unexpected gigantism_protocol value: '{gp}'",
                    suggestion="Use 'APPLIED' or 'SKIPPED'"
                )

        # loop_verified
        if vs.get("loop_verified") is not True:
            self._add_warning(
                "visual_summary.loop_verified",
                "Should be true",
                suggestion="Ensure loop is properly configured"
            )

        # banned_words_checked
        if vs.get("banned_words_checked") is not True:
            self._add_warning(
                "visual_summary.banned_words_checked",
                "Should be true"
            )

        # loop_verification object
        lv = vs.get("loop_verification")
        if not lv:
            self._add_error(
                "visual_summary.loop_verification",
                "Required object is missing",
                code="MISSING_LOOP_VERIFICATION"
            )
        else:
            self._validate_loop_verification_object(lv)

        # motion_summary (should not be empty)
        if not vs.get("motion_summary"):
            self._add_warning(
                "visual_summary.motion_summary",
                "Should not be empty"
            )

        # energy_pattern (should not be empty)
        if not vs.get("energy_pattern"):
            self._add_warning(
                "visual_summary.energy_pattern",
                "Should not be empty"
            )

    def _validate_loop_verification_object(self, lv: Dict[str, Any]) -> None:
        """Валідація loop_verification об'єкту."""
        # movements_are_different
        movements_val = lv.get("movements_are_different")
        if movements_val is True:
            pass  # OK
        elif movements_val is False:
            self._add_error(
                "visual_summary.loop_verification.movements_are_different",
                "Must be true — last scene movement must differ from Scene 1",
                code="SAME_LOOP_MOVEMENT",
                suggestion="Use COMPLEMENTARY movement for last scene (LOOP_CLOSE)"
            )
        else:
            self._add_warning(
                "visual_summary.loop_verification.movements_are_different",
                f"Missing or non-boolean value: {movements_val!r} (expected true/false)",
            )

        # loop_ready
        loop_ready_val = lv.get("loop_ready")
        if loop_ready_val is True:
            pass  # OK
        elif loop_ready_val is False:
            self._add_error(
                "visual_summary.loop_verification.loop_ready",
                "Must be true",
                code="LOOP_NOT_READY"
            )
        else:
            self._add_warning(
                "visual_summary.loop_verification.loop_ready",
                f"Missing or non-boolean value: {loop_ready_val!r} (expected true/false)",
            )

        # Match fields
        if lv.get("foreground_match") is not True:
            self._add_warning(
                "visual_summary.loop_verification.foreground_match",
                f"Should be true — Scene 1 and {self._total_scenes} foreground should match"
            )

        if lv.get("lighting_match") is not True:
            self._add_warning(
                "visual_summary.loop_verification.lighting_match",
                f"Should be true — Scene 1 and {self._total_scenes} lighting should match"
            )

        if lv.get("same_reference_image") is not True:
            self._add_warning(
                "visual_summary.loop_verification.same_reference_image",
                "Should be true"
            )

    # ========================================================================
    # SCENES VALIDATION
    # ========================================================================

    def _validate_scenes(self) -> None:
        """Валідація scenes масиву."""
        scenes = self._data.get("scenes")

        if not isinstance(scenes, list):
            self._add_error(
                "scenes",
                "Must be an array",
                code="INVALID_SCENES_TYPE"
            )
            return

        if len(scenes) < 6 or len(scenes) > 10:
            self._add_error(
                "scenes",
                f"Must have 6-10 items, got {len(scenes)}",
                code="INVALID_SCENE_COUNT"
            )
            return

        # _total_scenes already set in validate() before this method runs

        # Compute exterior scenes dynamically
        self._exterior_scenes = set(EXTERIOR_SCENES_BASE)
        for i, s in enumerate(scenes):
            sn = s.get("scene_number", i + 1)
            ref = s.get("reference_type", "")
            if ref in ("PRIMARY", "LOOP_CLOSE") or sn == len(scenes):
                self._exterior_scenes.add(sn)

        # Get easter egg scene from GEN1 or from scenes
        easter_egg_scene = self._get_easter_egg_scene()

        for i, scene in enumerate(scenes):
            scene_num = scene.get("scene_number", i + 1)
            self._validate_scene(scene, scene_num, i, easter_egg_scene)

    def _get_scene_energy(self, scene_num: int) -> Optional[str]:
        """Get energy_level for a scene from GEN1 handoff data."""
        if not self._gen1_data:
            return None
        gen1_scenes = self._gen1_data.get("scenes", [])
        for s in gen1_scenes:
            if s.get("scene_number") == scene_num:
                return s.get("energy_level")
        return None

    def _get_easter_egg_scene(self) -> Optional[int]:
        """Отримати номер сцени з easter egg."""
        # Try from GEN1
        if self._gen1_data:
            engagement = self._gen1_data.get("engagement", {})
            egg = engagement.get("easter_egg", {})
            if egg:
                return egg.get("scene_number")

        # Try from scenes
        scenes = self._data.get("scenes", [])
        for scene in scenes:
            if scene.get("easter_egg_integration"):
                return scene.get("scene_number")

        return None

    def _validate_scene(
        self,
        scene: Dict[str, Any],
        scene_num: int,
        index: int,
        easter_egg_scene: Optional[int]
    ) -> None:
        """Валідація окремої сцени."""
        prefix = f"scenes[{index}]"
        check = SceneCheckResult(scene=scene_num)

        # reference_type
        ref_type = scene.get("reference_type")
        if ref_type is None:
            self._add_error(
                f"{prefix}.reference_type",
                "Required field is missing (null or absent)",
                code="MISSING_REF_TYPE"
            )
        elif ref_type == "":
            self._add_error(
                f"{prefix}.reference_type",
                "Field is empty string — GEN2 likely failed to determine reference type",
                code="EMPTY_REF_TYPE",
                suggestion=f"Must be one of: {', '.join(e.value for e in ReferenceType)}"
            )
        elif ref_type not in [e.value for e in ReferenceType]:
            self._add_error(
                f"{prefix}.reference_type",
                f"Invalid value '{ref_type}'",
                code="INVALID_REF_TYPE",
                suggestion=f"Must be one of: {', '.join(e.value for e in ReferenceType)}"
            )

        # visual_tier (GEN2 v6.1.0 — TIER SYSTEM)
        VALID_VISUAL_TIERS = {
            "TIER_1_MONEY_SHOT", "TIER_2_HIGH_APPETITE",
            "TIER_3_BALANCED", "TIER_4_ARCHITECTURE"
        }
        visual_tier = scene.get("visual_tier")
        if not visual_tier:
            self._add_warning(
                f"{prefix}.visual_tier",
                "Missing visual_tier — should be assigned based on sensory_pressure",
                suggestion=f"Must be one of: {', '.join(sorted(VALID_VISUAL_TIERS))}"
            )
        elif visual_tier == "LOOP_CLOSE":
            self._add_error(
                f"{prefix}.visual_tier",
                "LOOP_CLOSE is NOT a tier — it belongs in reference_type",
                code="LOOP_CLOSE_IN_TIER",
                suggestion="Assign a real tier based on sensory_pressure, put LOOP_CLOSE in reference_type"
            )
        elif visual_tier not in VALID_VISUAL_TIERS:
            self._add_error(
                f"{prefix}.visual_tier",
                f"Invalid visual_tier '{visual_tier}'",
                code="INVALID_VISUAL_TIER",
                suggestion=f"Must be one of: {', '.join(sorted(VALID_VISUAL_TIERS))}"
            )

        # motion_intensity (GEN2 v6.1.0 — 1-10 scale)
        motion_intensity = scene.get("motion_intensity")
        if motion_intensity is None:
            self._add_warning(
                f"{prefix}.motion_intensity",
                "Missing motion_intensity — should be 1-10 based on energy_level",
                suggestion="EXPLOSIVE=8-9, HIGH=6-7, MEDIUM=4-5, LOW=2-3"
            )
        elif not isinstance(motion_intensity, (int, float)) or (isinstance(motion_intensity, float) and (motion_intensity != motion_intensity)) or motion_intensity < 1 or motion_intensity > 10:
            self._add_error(
                f"{prefix}.motion_intensity",
                f"Must be integer 1-10, got {motion_intensity}",
                code="INVALID_MOTION_INTENSITY"
            )

        # image_prompt
        image_prompt = scene.get("image_prompt", "")
        if not image_prompt:
            self._add_error(
                f"{prefix}.image_prompt",
                "Required and cannot be empty",
                code="MISSING_IMAGE_PROMPT"
            )
            check.image_prompt = "FAIL"
        else:
            if not self._validate_image_prompt(image_prompt, scene_num, prefix, visual_tier=scene.get("visual_tier", "")):
                check.image_prompt = "FAIL"

        # video_prompt
        video_prompt = scene.get("video_prompt", "")
        if not video_prompt:
            self._add_error(
                f"{prefix}.video_prompt",
                "Required and cannot be empty",
                code="MISSING_VIDEO_PROMPT"
            )
            check.video_prompt = "FAIL"
        else:
            if not self._validate_video_prompt(video_prompt, scene_num, prefix):
                check.video_prompt = "FAIL"

            # Store movements for loop check
            if scene_num == 1:
                self._scene1_movement = video_prompt
            elif scene_num == self._total_scenes:
                self._last_scene_movement = video_prompt

        # motion_elements: energy-dependent minimums (GEN2.txt: EXPLOSIVE=4+, HIGH=3+, MEDIUM=2-3, LOW=2)
        motion = scene.get("motion_elements", [])
        motion_count = len(motion) if isinstance(motion, list) else 0
        scene_energy = self._get_scene_energy(scene_num)
        _energy_min = {"EXPLOSIVE": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 2}
        required_min = _energy_min.get(scene_energy, MIN_MOTION_ELEMENTS)

        if motion_count < MIN_MOTION_ELEMENTS:
            # Hard floor: no scene can have <2
            self._add_error(
                f"{prefix}.motion_elements",
                f"Must have at least {MIN_MOTION_ELEMENTS} items, got {motion_count}",
                code="INSUFFICIENT_MOTION"
            )
            check.motion_elements = "FAIL"
        elif motion_count < required_min:
            # Energy-dependent minimum
            self._add_error(
                f"{prefix}.motion_elements",
                f"{scene_energy} scene requires {required_min}+ motion_elements, got {motion_count}",
                code="INSUFFICIENT_MOTION_FOR_ENERGY"
            )
            check.motion_elements = "FAIL"

        # Subject motion: at least one physical state change in video_prompt + motion_elements
        # Scenes with only ambient motion (light shifting, shadows, fog) render as Ken Burns stills
        if ref_type != ReferenceType.LOOP_CLOSE.value:
            combined_motion_text = (video_prompt or "").lower()
            if isinstance(motion, list):
                for me in motion:
                    if isinstance(me, str):
                        combined_motion_text += " " + me.lower()
            if combined_motion_text.strip() and not _PHYSICAL_STATE_CHANGE_RE.search(combined_motion_text):
                self._add_warning(
                    f"{prefix}.video_prompt",
                    "No physical state change found (drip, crack, flow, melt, etc.) — "
                    "ambient-only motion risks Ken Burns animated image",
                    suggestion="Add at least one food-interaction motion: seeping, cracking, trickling, pooling",
                    code="AMBIENT_ONLY_MOTION"
                )

        # scale_techniques (required for exterior scenes)
        exterior_scenes = getattr(self, '_exterior_scenes', EXTERIOR_SCENES_BASE)
        if scene_num in exterior_scenes:
            check.scale_techniques = "PASS"
            scale = scene.get("scale_techniques")
            if not scale:
                self._add_error(
                    f"{prefix}.scale_techniques",
                    f"Required for exterior scene {scene_num}",
                    code="MISSING_SCALE_TECHNIQUES"
                )
                check.scale_techniques = "FAIL"
            else:
                # Validate scale_techniques content
                if not scale.get("camera_angle"):
                    self._add_warning(
                        f"{prefix}.scale_techniques.camera_angle",
                        "Should specify camera angle"
                    )
                if not scale.get("atmospheric_depth"):
                    self._add_warning(
                        f"{prefix}.scale_techniques.atmospheric_depth",
                        "Should mention haze/fog"
                    )
                if not scale.get("scale_indicators"):
                    self._add_warning(
                        f"{prefix}.scale_techniques.scale_indicators",
                        "Should list scale indicators"
                    )
                # Validate scale_mode value (#11)
                scale_mode = scale.get("scale_mode")
                if scale_mode and scale_mode not in VALID_SCALE_MODES:
                    self._add_warning(
                        f"{prefix}.scale_techniques.scale_mode",
                        f"Invalid scale_mode '{scale_mode}'",
                        suggestion=f"Must be one of: {', '.join(sorted(VALID_SCALE_MODES))}"
                    )

        # inheritance (required for REQUIRES_REF and LOOP_CLOSE)
        if ref_type in (ReferenceType.REQUIRES_REF.value, ReferenceType.LOOP_CLOSE.value):
            check.inheritance = "PASS"
            inheritance = scene.get("inheritance")
            if not inheritance:
                self._add_error(
                    f"{prefix}.inheritance",
                    f"Required for {ref_type} scene",
                    code="MISSING_INHERITANCE"
                )
                check.inheritance = "FAIL"
            elif not isinstance(inheritance.get("parent_scene"), int) or inheritance.get("parent_scene") < 1:
                self._add_error(
                    f"{prefix}.inheritance.parent_scene",
                    f"Must be a positive integer, got {inheritance.get('parent_scene')}",
                    code="INVALID_PARENT_SCENE"
                )
                check.inheritance = "FAIL"
            elif ref_type == ReferenceType.LOOP_CLOSE.value and inheritance.get("parent_scene") != 1:
                self._add_warning(
                    f"{prefix}.inheritance.parent_scene",
                    f"LOOP_CLOSE should inherit from Scene 1, got Scene {inheritance.get('parent_scene')}",
                    suggestion="Set parent_scene to 1 for seamless loop"
                )

        # Scene 1 specific
        if scene_num == 1:
            self._validate_scene1_specific(scene, prefix, check)

        # Last scene specific (LOOP_CLOSE)
        total = self._total_scenes
        if scene_num == total:
            self._validate_last_scene_specific(scene, prefix, check, total)

        # Easter egg integration
        if easter_egg_scene and scene_num == easter_egg_scene:
            check.easter_egg = "PASS"
            egg_int = scene.get("easter_egg_integration")
            if not egg_int:
                self._add_error(
                    f"{prefix}.easter_egg_integration",
                    "Required for easter egg scene",
                    code="MISSING_EASTER_EGG_INTEGRATION"
                )
                check.easter_egg = "FAIL"
            else:
                if not self._validate_easter_egg(egg_int, prefix):
                    check.easter_egg = "FAIL"

        self._scene_checks.append(check)

    def _validate_scene1_specific(
        self,
        scene: Dict[str, Any],
        prefix: str,
        check: SceneCheckResult
    ) -> None:
        """Валідація специфічних правил для Scene 1."""
        # reference_type must be PRIMARY
        if scene.get("reference_type") != ReferenceType.PRIMARY.value:
            self._add_error(
                f"{prefix}.reference_type",
                f"Scene 1 must be 'PRIMARY', got '{scene.get('reference_type')}'",
                code="INVALID_SCENE1_REF_TYPE"
            )

        # first_frame_composition must exist
        ffc = scene.get("first_frame_composition")
        if not ffc:
            self._add_error(
                f"{prefix}.first_frame_composition",
                "Required for Scene 1",
                code="MISSING_FIRST_FRAME_COMPOSITION"
            )
        else:
            # Check required fields (scale_proof only required for TIER_4 architecture)
            visual_tier = scene.get("visual_tier", "")
            required = ["hook_element", "foreground", "safe_zone"]
            if visual_tier in ("TIER_4_ARCHITECTURE",):
                required.append("scale_proof")
            for field_name in required:
                if not ffc.get(field_name):
                    self._add_error(
                        f"{prefix}.first_frame_composition.{field_name}",
                        "Required for Scene 1 first frame",
                        code="MISSING_FFC_FIELD"
                    )

        # image_prompt scale keywords — tier-dependent per GEN2.txt v6:
        # TIER 1-2 (MACRO/APPETITE): scale keywords BANNED
        # TIER 3 (BALANCED): selective
        # TIER 4 (ARCHITECTURE): required 2+
        # Since Scene 1 is often MACRO_ENTRY (80%), only warn if missing
        image_prompt = scene.get("image_prompt", "").lower()
        scale_count = sum(1 for kw in SCALE_KEYWORDS if kw in image_prompt)
        visual_tier = scene.get("visual_tier", "")
        if visual_tier in ("TIER_4_ARCHITECTURE",) and scale_count < MIN_SCALE_KEYWORDS:
            self._add_error(
                f"{prefix}.image_prompt",
                f"TIER_4 Scene 1 must have at least {MIN_SCALE_KEYWORDS} scale keywords, found {scale_count}",
                code="INSUFFICIENT_SCALE_KEYWORDS",
                suggestion=f"Add: {', '.join(SCALE_KEYWORDS)}"
            )
        elif not visual_tier.startswith("TIER_4") and scale_count < MIN_SCALE_KEYWORDS:
            # Non-architecture tiers: scale keywords optional
            pass

    def _validate_last_scene_specific(
        self,
        scene: Dict[str, Any],
        prefix: str,
        check: SceneCheckResult,
        total_scenes: int = None
    ) -> None:
        """Валідація специфічних правил для last scene (LOOP_CLOSE)."""
        if total_scenes is None:
            total_scenes = self._total_scenes
        check.loop_complementary = "PASS"

        # reference_type must be LOOP_CLOSE
        if scene.get("reference_type") != ReferenceType.LOOP_CLOSE.value:
            self._add_error(
                f"{prefix}.reference_type",
                f"Last scene (Scene {total_scenes}) must be 'LOOP_CLOSE', got '{scene.get('reference_type')}'",
                code="INVALID_LAST_SCENE_REF_TYPE"
            )

        # video_prompt meta-instructions: now checked in _validate_video_prompt() for ALL scenes
        # Keep LOOP_CLOSE-specific check for loop_complementary tracking
        video_prompt = scene.get("video_prompt", "").lower()
        for meta in BANNED_VIDEO_META:
            if meta in video_prompt:
                check.loop_complementary = "FAIL"
                break

        # CRITICAL #1: Check image_prompt for meta-instructions in LOOP_CLOSE
        image_prompt = scene.get("image_prompt", "").lower()
        for meta in BANNED_LOOP_IMAGE_META:
            if meta in image_prompt:
                self._add_error(
                    f"{prefix}.image_prompt",
                    f"LOOP_CLOSE image_prompt contains meta-instruction: '{meta}'",
                    code="LOOP_IMAGE_META_INSTRUCTION",
                    suggestion="Describe visual content only — image generators have no pipeline context"
                )
                check.loop_complementary = "FAIL"
                break

        # motion_elements must be reversal-safe (Scene N is reversed in post-production)
        # GEN2.txt line 1192: waterfall, falling, cascading, smoke rising, steam rising,
        # dripping, pouring, fire, flames, walking, running, vehicles, birds flying
        motion_elements = scene.get("motion_elements", [])
        if isinstance(motion_elements, list):
            for me in motion_elements:
                if isinstance(me, str):
                    me_lower = me.lower()
                    for unsafe in REVERSAL_UNSAFE_WORDS:
                        if re.search(r'\b' + re.escape(unsafe) + r'\b', me_lower):
                            self._add_error(
                                f"{prefix}.motion_elements",
                                f"Contains reversal-unsafe word '{unsafe}' in '{me}' — will look unnatural when reversed",
                                code="REVERSAL_UNSAFE_MOTION",
                                suggestion="Use reversal-safe motion: shimmer, glow, pulse, fog drift, heat haze"
                            )
                            break

    # ========================================================================
    # IMAGE PROMPT VALIDATION
    # ========================================================================

    def _validate_image_prompt(
        self,
        prompt: str,
        scene_num: int,
        prefix: str,
        visual_tier: str = ""
    ) -> bool:
        """
        Валідація image_prompt.

        Returns:
            True якщо валідний
        """
        valid = True
        prompt_lower = prompt.lower()

        # Check for safe zone instruction (WARNING only — doesn't fail validation)
        safe_zone_phrases = [
            "upper portion",
            "upper 60%",
            "upper part",
            "top portion"
        ]
        has_safe_zone = any(phrase in prompt_lower for phrase in safe_zone_phrases)
        if not has_safe_zone:
            self._add_warning(
                f"{prefix}.image_prompt",
                "Should contain safe zone instruction",
                suggestion="Add: 'subject positioned in upper portion of frame'"
            )

        # Check for --ar 9:16 (should NOT be present)
        if "--ar 9:16" in prompt_lower or "--ar 9\\:16" in prompt_lower:
            self._add_warning(
                f"{prefix}.image_prompt",
                "Contains --ar 9:16 which is hardcoded in software",
                suggestion="Remove aspect ratio — it's added automatically"
            )

        # Note: Anti-toy keywords are enforced via global_settings.negative_prompt (ERROR).
        # Per-scene check removed as redundant - global negative is appended during generation.

        # Check for meta-instruction patterns (GEN2.txt lines 392-439)
        for pattern in IMAGE_META_PATTERNS:
            match = re.search(pattern, prompt_lower)
            if match:
                self._add_error(
                    f"{prefix}.image_prompt",
                    f"Contains meta-instruction pattern: '{match.group()}'",
                    code="IMAGE_META_INSTRUCTION",
                    suggestion="Remove — image generators have no pipeline context"
                )
                valid = False

        # Check for "slow motion"/"slo-mo" in image_prompt (GEN2.txt: "any prompt")
        if re.search(r'\bslow\s+motion\b', prompt_lower) or re.search(r'\bslo-mo\b', prompt_lower):
            self._add_error(
                f"{prefix}.image_prompt",
                "Contains 'slow motion'/'slo-mo' — banned in all prompts",
                code="BANNED_SLOW_MOTION_IMAGE",
                suggestion="Replace with 'suspended mid-air' or 'time-stretched'"
            )
            valid = False

        # Check money shot has cold/dark background (GEN2.txt: Negative J)
        if visual_tier == "TIER_1_MONEY_SHOT":
            cold_indicators = {
                "cool blue", "blue-black", "charcoal", "midnight", "deep blue",
                "dark background", "cold blue", "cool grey background", "cool dark",
            }
            has_cold_bg = any(ind in prompt_lower for ind in cold_indicators)
            if not has_cold_bg:
                self._add_warning(
                    f"{prefix}.image_prompt",
                    "Money shot missing cold/dark background indicator",
                    code="MONEY_SHOT_WARM_BACKGROUND",
                    suggestion="Use cold palette for contrast_color: deep blue, charcoal, midnight, blue-black"
                )

        # Per-tier image_prompt word count check (HIGH #1)
        # Count only core words (exclude --no block) to match autocorrect behavior
        if visual_tier:
            no_idx_p = prompt.find("--no")
            core_p = prompt[:no_idx_p].rstrip() if no_idx_p > 0 else prompt
            img_word_count = len(core_p.split())
            tier_range = IMAGE_WORD_COUNT_RANGES.get(visual_tier)
            if tier_range:
                min_wc, max_wc = tier_range
                if img_word_count < min_wc:
                    self._add_warning(
                        f"{prefix}.image_prompt",
                        f"Has {img_word_count} words, {visual_tier} minimum is {min_wc}",
                        suggestion=f"Expand image_prompt to {min_wc}-{max_wc} words",
                        code="IMAGE_PROMPT_TOO_SHORT"
                    )

        # TIER 1 (MONEY_SHOT) should NOT use architecture scale words
        # TIER 2 can be architecture-adjacent, so allow there
        if visual_tier == "TIER_1_MONEY_SHOT":
            arch_words = {"towering", "imposing", "colossal", "gigantic", "monumental"}
            found_arch = [w for w in arch_words if w in prompt_lower]
            if found_arch:
                self._add_warning(
                    f"{prefix}.image_prompt",
                    f"TIER_1_MONEY_SHOT uses architecture scale words: {', '.join(found_arch)}",
                    code="TIER1_ARCHITECTURE_WORDS",
                    suggestion="Money shot should use macro/appetite language, not architecture scale"
                )

        return valid

    # ========================================================================
    # VIDEO PROMPT VALIDATION
    # ========================================================================

    # Per-tier video_prompt word count ranges (GEN2.txt lines 163, 1095-1101)
    VIDEO_WORD_COUNT_RANGES: Dict[str, Tuple[int, int]] = {
        "TIER_1_MONEY_SHOT": (15, 20),
        "TIER_2_HIGH_APPETITE": (20, 30),
        "TIER_3_BALANCED": (25, 35),
        "TIER_4_ARCHITECTURE": (30, 40),
    }

    def _validate_video_prompt(
        self,
        prompt: str,
        scene_num: int,
        prefix: str
    ) -> bool:
        """
        Валідація video_prompt.

        Returns:
            True якщо валідний
        """
        valid = True
        prompt_lower = prompt.lower()

        # Word count check — per-tier if tier is available
        word_count = len(prompt.split())
        scene_data = self._get_scene_by_number(scene_num)
        visual_tier = scene_data.get("visual_tier", "") if scene_data else ""
        tier_range = self.VIDEO_WORD_COUNT_RANGES.get(visual_tier)

        if tier_range:
            min_wc, max_wc = tier_range
            if word_count < min_wc:
                self._add_warning(
                    f"{prefix}.video_prompt",
                    f"Has {word_count} words, {visual_tier} minimum is {min_wc}",
                    suggestion=f"Expand video_prompt to {min_wc}-{max_wc} words"
                )
            elif word_count > max_wc:
                self._add_warning(
                    f"{prefix}.video_prompt",
                    f"Has {word_count} words, {visual_tier} maximum is {max_wc}",
                    suggestion=f"Trim video_prompt to {min_wc}-{max_wc} words"
                )
        elif word_count > MAX_VIDEO_PROMPT_WORDS:
            self._add_warning(
                f"{prefix}.video_prompt",
                f"Has {word_count} words, recommended max is {MAX_VIDEO_PROMPT_WORDS}",
                suggestion="Shorten the prompt for better Kling results"
            )

        # Check for "10s" at end
        if prompt.strip().endswith("10s") or "10s" in prompt_lower:
            self._add_warning(
                f"{prefix}.video_prompt",
                "Contains '10s' which is hardcoded in software",
                suggestion="Remove duration — it's added automatically"
            )

        # Check for banned words
        for banned in BANNED_VIDEO_WORDS:
            # Use word boundary check
            pattern = r'\b' + re.escape(banned) + r'\b'
            if re.search(pattern, prompt_lower):
                self._add_error(
                    f"{prefix}.video_prompt",
                    f"Contains banned word: '{banned}'",
                    code="BANNED_VIDEO_WORD",
                    suggestion=self._get_banned_word_replacement(banned)
                )
                valid = False

        # Check for banned camera movements (proximity-based context check)
        for banned in BANNED_CAMERA_MOVEMENTS:
            pattern = r'\b' + re.escape(banned) + r'\b'
            for match in re.finditer(pattern, prompt_lower):
                # Extract context window around the match for allowed-context check
                # 100 chars before handles multi-word subjects like "magnificent white clouds"
                start = max(0, match.start() - 100)
                end = min(len(prompt_lower), match.end() + 50)
                context_window = prompt_lower[start:end]
                # Check if THIS occurrence is in an allowed context
                is_allowed = any(ctx in context_window for ctx in ALLOWED_DRIFTING_CONTEXTS)
                if not is_allowed:
                    self._add_error(
                        f"{prefix}.video_prompt",
                        f"Contains banned camera movement: '{banned}'",
                        code="BANNED_CAMERA_MOVEMENT",
                        suggestion=self._get_banned_movement_replacement(banned)
                    )
                    valid = False
                    break  # One error per banned word is enough

        # Check for at least one allowed camera movement (gerund)
        has_movement = any(mv in prompt_lower for mv in ALLOWED_CAMERA_MOVEMENTS)
        if not has_movement:
            self._add_warning(
                f"{prefix}.video_prompt",
                "No camera movement gerund found",
                suggestion=f"Add one of: {', '.join(sorted(ALLOWED_CAMERA_MOVEMENTS))}"
            )

        # Check for banned meta-instructions in ALL scenes (GEN2.txt lines 909-918)
        for meta in BANNED_VIDEO_META:
            if meta in prompt_lower:
                self._add_error(
                    f"{prefix}.video_prompt",
                    f"Contains banned meta-instruction: '{meta}'",
                    code="BANNED_META_INSTRUCTION",
                    suggestion="Remove — Kling has no context about other scenes or pipeline"
                )
                valid = False

        return valid

    def _get_banned_word_replacement(self, word: str) -> str:
        """Отримати заміну для забороненого слова."""
        replacements = {
            "slow": "steady, smooth",
            "slowly": "remove entirely",
            "gentle": "soft, fluid",
            "gently": "softly",
            "subtle": "visible, clear",
            "subtly": "visibly",
            "calm": "smooth, controlled",
            "gradual": "progressive, building",
            "gradually": "progressively",
            "leisurely": "measured, paced",
            "accelerating": "remove — not supported",
            "rack focus": "remove — post-production",
            "speed ramp": "remove — post-production",
            "dolly zoom": "remove — not supported"
        }
        return replacements.get(word.lower(), "remove or replace")

    def _get_banned_movement_replacement(self, movement: str) -> str:
        """Отримати заміну для забороненого camera movement."""
        replacements = {
            "drift": "push, track, orbit",
            "drifting": "pushing, tracking, orbiting",
            "float": "rise, ascend, crane up",
            "floating": "rising, ascending",
            "glide": "track, push",
            "gliding": "tracking, pushing",
            "pan": "orbit, push",
            "panning": "orbiting, pushing"
        }
        return replacements.get(movement.lower(), "pushing, tracking, orbiting")

    # ========================================================================
    # EASTER EGG VALIDATION
    # ========================================================================

    def _validate_easter_egg(
        self,
        egg: Dict[str, Any],
        prefix: str
    ) -> bool:
        """
        Валідація easter_egg_integration.

        Returns:
            True якщо валідний
        """
        valid = True

        # object
        if not egg.get("object"):
            self._add_error(
                f"{prefix}.easter_egg_integration.object",
                "Required field is missing",
                code="MISSING_EGG_OBJECT"
            )
            valid = False

        # placement_in_prompt
        placement = egg.get("placement_in_prompt", "").lower()
        if not placement:
            self._add_error(
                f"{prefix}.easter_egg_integration.placement_in_prompt",
                "Required field is missing",
                code="MISSING_EGG_PLACEMENT"
            )
            valid = False
        else:
            # Check for forbidden zone
            for zone in FORBIDDEN_EGG_ZONES:
                if zone in placement:
                    self._add_error(
                        f"{prefix}.easter_egg_integration.placement_in_prompt",
                        f"Easter egg in forbidden zone: '{zone}' — will be covered by UI",
                        code="FORBIDDEN_EGG_ZONE",
                        suggestion="Move to center-left, center-right, or top area"
                    )
                    valid = False

            # Check for warning zones
            for zone in WARNING_EGG_ZONES:
                if zone in placement:
                    self._add_warning(
                        f"{prefix}.easter_egg_integration.placement_in_prompt",
                        f"Easter egg in risky zone: '{zone}' — may be partially covered",
                        suggestion="Consider moving to center-left or center-right"
                    )

        # integrated_in_image_prompt
        if egg.get("integrated_in_image_prompt") is not True:
            self._add_warning(
                f"{prefix}.easter_egg_integration.integrated_in_image_prompt",
                "Should be true"
            )

        return valid

    # ========================================================================
    # LOOP VALIDATION
    # ========================================================================

    def _validate_loop(self) -> None:
        """Валідація loop (Scene 1 vs last scene movements)."""
        if not self._scene1_movement or not self._last_scene_movement:
            return  # Already reported as missing

        total_scenes = self._total_scenes

        # Extract key movement words
        scene1_movements = self._extract_movement_words(self._scene1_movement)
        last_scene_movements = self._extract_movement_words(self._last_scene_movement)

        # Check if movements are too similar
        if scene1_movements and last_scene_movements:
            common = scene1_movements & last_scene_movements
            # If more than half are common, movements are too similar
            total = len(scene1_movements | last_scene_movements)
            if len(common) > total / 2:
                self._add_warning(
                    f"scenes[{total_scenes - 1}].video_prompt",
                    f"Last scene movement similar to Scene 1. Common: {', '.join(common)}",
                    suggestion="Use COMPLEMENTARY movement (e.g., if Scene 1 is PUSH, last scene should be RISE)"
                )

    def _extract_movement_words(self, prompt: str) -> Set[str]:
        """Витягнути movement слова з prompt і нормалізувати до base form."""
        prompt_lower = prompt.lower()
        movements = set()

        # Explicit gerund→base mapping (rstrip("ing") is unreliable)
        _GERUND_TO_BASE = {
            "pushing": "push", "pulling": "pull",
            "orbiting": "orbit", "rising": "rise",
            "descending": "descend", "tracking": "track",
            "craning": "crane", "ascending": "ascend",
            "emerging": "emerge",
        }
        _BASE_FORMS = {"push", "pull", "orbit", "rise", "descend", "track", "crane", "ascend", "emerge"}

        for word in list(_GERUND_TO_BASE.keys()) + list(_BASE_FORMS):
            if word in prompt_lower:
                base = _GERUND_TO_BASE.get(word, word)
                movements.add(base)

        return movements

    # ========================================================================
    # TIER vs SP/MONEY_SHOT CROSS-CHECK (P4)
    # ========================================================================

    def _validate_tier_assignment(self) -> None:
        """
        Cross-check visual_tier against sensory_pressure + money_shot from GEN1.

        GEN2.txt tier rules (MECHANICAL, no exceptions):
        - money_shot.is_money_shot=true OR SP=10 → TIER_1_MONEY_SHOT
        - SP ≥ 8 (no money_shot) → TIER_2_HIGH_APPETITE
        - SP 5-7 → TIER_3_BALANCED
        - SP 1-4 → TIER_4_ARCHITECTURE
        """
        if not self._gen1_data:
            return  # Can't cross-check without GEN1 data

        gen1_scenes = self._gen1_data.get("scenes", [])
        if not isinstance(gen1_scenes, list):
            return

        # Build lookup: scene_number → {sp, money_shot}
        gen1_lookup = {}
        for gs in gen1_scenes:
            if not isinstance(gs, dict):
                continue
            sn = gs.get("scene_number")
            if sn is not None:
                gen1_lookup[sn] = {
                    "sp": gs.get("sensory_pressure"),
                    "money_shot": gs.get("money_shot"),
                }

        scenes = self._data.get("scenes", [])
        if not isinstance(scenes, list):
            return

        for i, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                continue
            scene_num = scene.get("scene_number", i + 1)
            visual_tier = scene.get("visual_tier", "")
            prefix = f"scenes[{i}]"

            gen1_info = gen1_lookup.get(scene_num)
            if not gen1_info:
                continue

            sp = gen1_info["sp"]
            ms = gen1_info["money_shot"]
            is_money_shot = isinstance(ms, dict) and ms.get("is_money_shot") is True

            # Determine expected tier
            expected_tier = None
            if is_money_shot or (isinstance(sp, (int, float)) and sp >= 10):
                expected_tier = "TIER_1_MONEY_SHOT"
            elif isinstance(sp, (int, float)):
                if sp >= 8:
                    expected_tier = "TIER_2_HIGH_APPETITE"
                elif sp >= 5:
                    expected_tier = "TIER_3_BALANCED"
                else:
                    expected_tier = "TIER_4_ARCHITECTURE"

            if expected_tier and visual_tier and visual_tier != expected_tier:
                self._add_error(
                    f"{prefix}.visual_tier",
                    f"Tier mismatch: GEN2 assigned '{visual_tier}' but GEN1 SP={sp}, "
                    f"money_shot={is_money_shot} → expected '{expected_tier}'",
                    code="TIER_MISMATCH",
                    suggestion=f"Set visual_tier to '{expected_tier}'"
                )

    # ========================================================================
    # WORD COUNT HIERARCHY (P5)
    # ========================================================================

    def _validate_word_count_hierarchy(self) -> None:
        """
        Validate image_prompt word count hierarchy per GEN2.txt:
        - Money shot (TIER_1): 130-150 words, LONGEST in output
        - No other scene > 130 words
        """
        scenes = self._data.get("scenes", [])
        if not isinstance(scenes, list) or not scenes:
            return

        # Find money shot scene and word counts
        money_shot_idx = None
        word_counts: list[tuple[int, int, int]] = []  # (index, scene_number, word_count)

        for i, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                continue
            scene_num = scene.get("scene_number", i + 1)
            image_prompt = scene.get("image_prompt", "")
            # Count only core words (exclude --no block) to match autocorrect behavior
            no_idx = image_prompt.find("--no") if image_prompt else -1
            core_prompt = image_prompt[:no_idx].rstrip() if no_idx > 0 else (image_prompt or "")
            wc = len(core_prompt.split()) if core_prompt else 0
            word_counts.append((i, scene_num, wc))

            # Check if money shot from visual_tier
            visual_tier = scene.get("visual_tier", "")
            if visual_tier == "TIER_1_MONEY_SHOT":
                money_shot_idx = i

        # Also check from gen1_data
        if money_shot_idx is None and self._gen1_data:
            gen1_scenes = self._gen1_data.get("scenes", [])
            if isinstance(gen1_scenes, list):
                for gs in gen1_scenes:
                    if isinstance(gs, dict):
                        ms = gs.get("money_shot")
                        if isinstance(ms, dict) and ms.get("is_money_shot"):
                            sn = gs.get("scene_number")
                            for idx, s_num, _ in word_counts:
                                if s_num == sn:
                                    money_shot_idx = idx
                                    break

        if money_shot_idx is None:
            return  # No money shot identified

        money_shot_wc = word_counts[money_shot_idx][2]
        money_shot_sn = word_counts[money_shot_idx][1]

        # Check money shot ≥ 130 words
        if money_shot_wc < 130:
            self._add_error(
                f"scenes[{money_shot_idx}].image_prompt",
                f"Money shot (Scene {money_shot_sn}) has {money_shot_wc} words, "
                f"minimum is 130 per GEN2.txt WORD COUNT HIERARCHY",
                code="MONEY_SHOT_TOO_SHORT",
                suggestion="Expand money shot image_prompt to 130-150 words"
            )

        # Check money shot is longest
        for idx, sn, wc in word_counts:
            if idx == money_shot_idx:
                continue
            if wc > money_shot_wc and money_shot_wc > 0:
                self._add_error(
                    f"scenes[{idx}].image_prompt",
                    f"Scene {sn} ({wc} words) is longer than money shot "
                    f"Scene {money_shot_sn} ({money_shot_wc} words)",
                    code="EXCEEDS_MONEY_SHOT",
                    suggestion="Money shot must be the longest image_prompt"
                )
            # No non-money-shot scene > 130 words
            if wc > 130:
                self._add_error(
                    f"scenes[{idx}].image_prompt",
                    f"Scene {sn} has {wc} words — non-money-shot scenes must not exceed 130",
                    code="NON_MONEY_SHOT_TOO_LONG",
                    suggestion="Trim this scene's image_prompt to ≤130 words"
                )

    # ========================================================================
    # BODY_TRIGGER VISUAL KEYWORDS (P7)
    # ========================================================================

    # body_trigger → required keywords mapping (from GEN2.txt)
    BODY_TRIGGER_KEYWORDS: Dict[str, List[str]] = {
        "MOUTH": ["glistening", "wet surface", "moisture beading", "liquid sheen", "dripping"],
        "SKIN": ["condensation droplets", "heat shimmer", "frost crystals", "temperature visible"],
        "NOSE": ["steam wisps rising", "visible vapor", "aromatic haze", "heat haze from surface"],
        "EARS": ["fracture lines", "cracking surface", "splitting edge", "crevices", "shattered",
                 "crunchy breading detail", "crispy broken edges"],
        "STOMACH": ["overflowing", "impossibly abundant", "stacked layers", "towering pile"],
    }

    def _validate_body_trigger(self) -> None:
        """
        Validate Scene 1 image_prompt contains ≥2 keywords from body_trigger row.

        GEN2.txt: "Scene 1 image prompt MUST contain ≥2 keywords from the matching body_trigger row."
        """
        if not self._gen1_data:
            return

        # Get body_trigger from hook
        hook = self._gen1_data.get("hook", {})
        if not isinstance(hook, dict):
            return

        body_trigger = hook.get("body_trigger", "")
        if not body_trigger:
            return

        body_trigger_upper = body_trigger.upper().strip()
        keywords = self.BODY_TRIGGER_KEYWORDS.get(body_trigger_upper)
        if not keywords:
            return

        # Find Scene 1 image_prompt
        scenes = self._data.get("scenes", [])
        if not isinstance(scenes, list) or not scenes:
            return

        scene1 = scenes[0]
        if not isinstance(scene1, dict):
            return

        image_prompt = scene1.get("image_prompt", "").lower()
        if not image_prompt:
            return

        # Count matching keywords
        matches = [kw for kw in keywords if kw.lower() in image_prompt]

        if len(matches) < 2:
            self._add_error(
                "scenes[0].image_prompt",
                f"body_trigger={body_trigger_upper}: found {len(matches)}/2 required keywords "
                f"(found: {matches or 'none'})",
                code="MISSING_BODY_TRIGGER",
                suggestion=f"Add ≥2 of: {', '.join(keywords)}"
            )

    # ========================================================================
    # IMAGE NEGATIVE BLOCK VALIDATION (#3)
    # ========================================================================

    def _validate_image_negative_blocks(self) -> None:
        """
        Validate that each image_prompt contains a --no negative block.

        GEN2.txt line 448-458: every image_prompt must end with --no block
        containing mandatory base negative keywords.
        """
        scenes = self._data.get("scenes", [])
        if not isinstance(scenes, list):
            return

        for i, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                continue
            image_prompt = scene.get("image_prompt", "")
            if not image_prompt:
                continue

            if "--no" not in image_prompt:
                self._add_warning(
                    f"scenes[{i}].image_prompt",
                    "Missing --no negative block at end of image_prompt",
                    suggestion="Append --no block with mandatory negative keywords"
                )

    # ========================================================================
    # GEN1 FIELD DUPLICATION CHECK (#12)
    # ========================================================================

    def _validate_no_gen1_field_duplication(self) -> None:
        """
        Check that GEN2 output doesn't duplicate GEN1 fields.

        GEN2.txt lines 1406-1417: 16 fields that GEN2 must NOT output.
        """
        scenes = self._data.get("scenes", [])
        if not isinstance(scenes, list):
            return

        for i, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                continue
            duplicated = [f for f in FORBIDDEN_GEN1_FIELDS if f in scene]
            if duplicated:
                self._add_warning(
                    f"scenes[{i}]",
                    f"Contains GEN1 fields that GEN2 should not duplicate: {', '.join(sorted(duplicated))}",
                    suggestion="Remove GEN1 fields — they're already in the handoff payload"
                )

    # ========================================================================
    # ATMOSPHERE MODE VALIDATION (#13)
    # ========================================================================

    def _validate_atmosphere_mode(self) -> None:
        """
        Validate atmosphere_mode and check mode-specific negative prompt additions.

        GEN2.txt lines 789-807: NOIR/HAUNTED need "flat lighting, even illumination" in negative.
        ETHEREAL needs "harsh shadows, high contrast".
        """
        if not self._gen1_data:
            return

        atmosphere_mode = self._gen1_data.get("atmosphere_mode", "")
        if not atmosphere_mode:
            return

        atmosphere_upper = atmosphere_mode.upper().strip()
        if atmosphere_upper not in VALID_ATMOSPHERE_MODES:
            self._add_warning(
                "atmosphere_mode",
                f"Unknown atmosphere_mode '{atmosphere_mode}'",
                suggestion=f"Valid modes: {', '.join(sorted(VALID_ATMOSPHERE_MODES))}"
            )

        # Check atmosphere-specific negative prompt additions
        required_negatives = ATMOSPHERE_NEGATIVE_ADDITIONS.get(atmosphere_upper)
        if required_negatives:
            gs = self._data.get("global_settings", {})
            negative = gs.get("negative_prompt", "").lower() if isinstance(gs, dict) else ""
            missing = [kw for kw in required_negatives if kw not in negative]
            if missing:
                self._add_error(
                    "global_settings.negative_prompt",
                    f"atmosphere_mode={atmosphere_upper} requires negative additions: {', '.join(missing)}",
                    code="MISSING_ATMOSPHERE_NEGATIVES",
                    suggestion=f"Add to negative_prompt: {', '.join(missing)}"
                )

    # ========================================================================
    # VISUAL PUNCTUATION VALIDATION (#15)
    # ========================================================================

    def _validate_visual_punctuation(self) -> None:
        """
        Validate visual_punctuation presence per energy level.

        GEN2.txt lines 1077-1091: EXPLOSIVE = required, HIGH = optional.
        """
        scenes = self._data.get("scenes", [])
        if not isinstance(scenes, list):
            return

        for i, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                continue
            scene_num = scene.get("scene_number", i + 1)
            energy = self._get_scene_energy(scene_num)
            vp = scene.get("visual_punctuation")

            if energy == "EXPLOSIVE" and (not vp or vp == "None"):
                self._add_error(
                    f"scenes[{i}].visual_punctuation",
                    "EXPLOSIVE scene requires visual_punctuation (lens flare, light burst, etc.)",
                    code="MISSING_EXPLOSIVE_PUNCTUATION",
                    suggestion="Add visual_punctuation: Light Burst, Lens Flare, Cloud Pass, Drip Cascade"
                )

    # ========================================================================
    # LOOP VERIFICATION DETAILS (#17, #18)
    # ========================================================================

    def _validate_loop_verification_details(self) -> None:
        """
        Validate loop_verification string fields and cross-check reversal_safe boolean.

        #17: Required string fields in loop_verification object.
        #18: motion_elements_reversal_safe cross-check.
        """
        vs = self._data.get("visual_summary", {})
        if not isinstance(vs, dict):
            return
        lv = vs.get("loop_verification", {})
        if not isinstance(lv, dict):
            return

        # #17: Required string fields
        required_strings = ["scene1_camera_movement", "sceneN_camera_movement", "sceneN_after_reverse"]
        for field_name in required_strings:
            val = lv.get(field_name)
            if not val or not isinstance(val, str) or not val.strip():
                self._add_warning(
                    f"visual_summary.loop_verification.{field_name}",
                    "Missing or empty — required for loop debugging",
                    suggestion="Describe the camera movement for loop verification"
                )

        # #18: Cross-check motion_elements_reversal_safe
        reversal_safe = lv.get("motion_elements_reversal_safe")
        if reversal_safe is True:
            # Verify against actual last scene motion_elements
            scenes = self._data.get("scenes", [])
            if isinstance(scenes, list) and scenes:
                last_scene = scenes[-1]
                if isinstance(last_scene, dict):
                    motion_elements = last_scene.get("motion_elements", [])
                    if isinstance(motion_elements, list):
                        for me in motion_elements:
                            if isinstance(me, str):
                                me_lower = me.lower()
                                for unsafe in REVERSAL_UNSAFE_WORDS:
                                    if re.search(r'\b' + re.escape(unsafe) + r'\b', me_lower):
                                        self._add_error(
                                            "visual_summary.loop_verification.motion_elements_reversal_safe",
                                            f"Claims reversal-safe but last scene contains '{unsafe}' in '{me}'",
                                            code="REVERSAL_SAFE_LIE",
                                            suggestion="Fix motion_elements first, then set reversal_safe to true"
                                        )
                                        return  # One error is enough

    # ========================================================================
    # TIER BREAKDOWN CROSS-VALIDATION (#21)
    # ========================================================================

    def _validate_tier_breakdown(self) -> None:
        """
        Cross-validate visual_summary.tier_breakdown against actual scene tiers.
        """
        vs = self._data.get("visual_summary", {})
        if not isinstance(vs, dict):
            return
        tier_breakdown = vs.get("tier_breakdown")
        if not isinstance(tier_breakdown, dict):
            return

        scenes = self._data.get("scenes", [])
        if not isinstance(scenes, list):
            return

        # Build actual tier→scene_numbers map
        actual_tiers: Dict[str, List[int]] = {}
        for scene in scenes:
            if isinstance(scene, dict):
                tier = scene.get("visual_tier", "")
                sn = scene.get("scene_number")
                if tier and sn is not None:
                    actual_tiers.setdefault(tier, []).append(sn)

        # Compare with reported tier_breakdown
        for tier_name, reported_scenes in tier_breakdown.items():
            if not isinstance(reported_scenes, list):
                continue
            actual = sorted(actual_tiers.get(tier_name, []))
            reported = sorted(reported_scenes)
            if actual != reported:
                self._add_warning(
                    "visual_summary.tier_breakdown",
                    f"{tier_name}: reported {reported} but actual scenes are {actual}",
                    suggestion="tier_breakdown must match actual scene visual_tier values"
                )

    # ========================================================================
    # ENTRY TYPE VALIDATION (#22)
    # ========================================================================

    def _validate_entry_type(self) -> None:
        """
        Validate first_frame_composition.entry_type vs GEN1 hook.scene_1_entry_type.
        """
        scenes = self._data.get("scenes", [])
        if not isinstance(scenes, list) or not scenes:
            return

        scene1 = scenes[0]
        if not isinstance(scene1, dict):
            return

        ffc = scene1.get("first_frame_composition")
        if not isinstance(ffc, dict):
            return

        # Check entry_type is valid
        VALID_ENTRY_TYPES = {"MACRO_ENTRY", "SCALE_SHOCK"}
        entry_type = ffc.get("entry_type")
        if entry_type and entry_type not in VALID_ENTRY_TYPES:
            self._add_warning(
                "scenes[0].first_frame_composition.entry_type",
                f"Invalid entry_type '{entry_type}'",
                suggestion=f"Must be one of: {', '.join(sorted(VALID_ENTRY_TYPES))}"
            )

        # Cross-check with GEN1 hook
        if self._gen1_data and entry_type:
            hook = self._gen1_data.get("hook", {})
            if isinstance(hook, dict):
                gen1_entry = hook.get("scene_1_entry_type", "")
                if gen1_entry and entry_type != gen1_entry:
                    self._add_warning(
                        "scenes[0].first_frame_composition.entry_type",
                        f"Mismatch: GEN2 has '{entry_type}' but GEN1 hook says '{gen1_entry}'",
                        suggestion=f"Should match GEN1 hook.scene_1_entry_type: '{gen1_entry}'"
                    )

    # ========================================================================
    # POST PRODUCTION NOTES VALIDATION (CRITICAL #2)
    # ========================================================================

    def _validate_post_production_notes(self) -> None:
        """
        Validate post_production_notes don't contain scene references.

        Post-production software has no scene context — references like
        "Scene 1", "Match Scene 3" are meaningless and indicate meta-leakage.
        """
        scenes = self._data.get("scenes", [])
        if not isinstance(scenes, list):
            return

        for i, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                continue
            ppn = scene.get("post_production_notes")
            if not isinstance(ppn, dict):
                continue
            for field_name in ("color_grade", "loop_match", "speed_ramp"):
                val = ppn.get(field_name, "")
                if isinstance(val, str) and _SCENE_REF_RE.search(val):
                    self._add_error(
                        f"scenes[{i}].post_production_notes.{field_name}",
                        f"Contains scene reference: '{val}' — post-production has no scene context",
                        code="POST_PROD_SCENE_REF",
                        suggestion="Describe the effect without referencing other scenes"
                    )

    # ========================================================================
    # NO HUMAN FIGURES VALIDATION (CRITICAL #3)
    # ========================================================================

    def _validate_no_human_figures(self) -> None:
        """
        Validate no human presence indicators in image_prompts.

        GEN2.txt: food architecture videos must NOT contain human figures.
        """
        scenes = self._data.get("scenes", [])
        if not isinstance(scenes, list):
            return

        for i, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                continue
            image_prompt = scene.get("image_prompt", "")
            if not image_prompt:
                continue
            # Strip --no block before checking (human words in negative block are OK)
            no_idx = image_prompt.find("--no")
            prompt_to_check = image_prompt[:no_idx] if no_idx >= 0 else image_prompt
            match = BANNED_HUMAN_INDICATORS_RE.search(prompt_to_check)
            if match:
                self._add_error(
                    f"scenes[{i}].image_prompt",
                    f"Contains human presence indicator: '{match.group()}'",
                    code="HUMAN_FIGURE_IN_PROMPT",
                    suggestion="Remove human references — use non-human proxies (shadows, traces, footprints)"
                )

    # ========================================================================
    # PRIMARY COUNT VALIDATION (CRITICAL #4)
    # ========================================================================

    def _validate_primary_count(self) -> None:
        """
        Validate exactly one PRIMARY reference_type across all scenes.

        Only Scene 1 should be PRIMARY.
        """
        scenes = self._data.get("scenes", [])
        if not isinstance(scenes, list):
            return

        primary_scenes = []
        for i, scene in enumerate(scenes):
            if isinstance(scene, dict) and scene.get("reference_type") == "PRIMARY":
                primary_scenes.append(scene.get("scene_number", i + 1))

        if len(primary_scenes) > 1:
            self._add_error(
                "scenes",
                f"Found {len(primary_scenes)} PRIMARY scenes ({primary_scenes}) — only Scene 1 should be PRIMARY",
                code="MULTIPLE_PRIMARY",
                suggestion="Only Scene 1 gets reference_type=PRIMARY; others should be INDEPENDENT, REQUIRES_REF, or LOOP_CLOSE"
            )
        elif len(primary_scenes) == 0:
            self._add_error(
                "scenes",
                "No PRIMARY scene found — Scene 1 must be PRIMARY",
                code="NO_PRIMARY",
                suggestion="Set Scene 1 reference_type to PRIMARY"
            )

    # ========================================================================
    # HELPER METHODS
    # ========================================================================

    def _get_scene_by_number(self, scene_num: int) -> Optional[Dict[str, Any]]:
        """Get scene dict from data by scene_number."""
        scenes = self._data.get("scenes", [])
        if isinstance(scenes, list):
            for s in scenes:
                if isinstance(s, dict) and s.get("scene_number") == scene_num:
                    return s
        return None

    def _add_error(
        self,
        field: str,
        message: str,
        code: str = "",
        suggestion: str = ""
    ) -> None:
        """Додати помилку."""
        self._errors.append(ValidationError(
            field=field,
            message=message,
            severity="error",
            code=code,
            suggestion=suggestion
        ))

    def _add_warning(
        self,
        field: str,
        message: str,
        code: str = "",
        suggestion: str = ""
    ) -> None:
        """Додати попередження."""
        self._warnings.append(ValidationError(
            field=field,
            message=message,
            severity="warning",
            code=code,
            suggestion=suggestion
        ))

    def _build_gigantism_check(self) -> Dict[str, str]:
        """Побудувати gigantism_check об'єкт."""
        gs = self._data.get("global_settings", {})
        scenes = self._data.get("scenes", [])
        scene1 = scenes[0] if scenes else {}

        gs_status = "PASS"
        if not gs or gs.get("gigantism_applied") is None:
            gs_status = "WARN"

        # Check anti-toy in negative
        negative = gs.get("negative_prompt", "").lower() if gs else ""
        anti_toy_status = "PASS"
        if not all(kw in negative for kw in ANTI_TOY_KEYWORDS):
            anti_toy_status = "FAIL"

        anti_yellow_status = "PASS"
        if not all(kw in negative for kw in ANTI_YELLOW_KEYWORDS):
            anti_yellow_status = "FAIL"

        # Check Scene 1 scale keywords (tier-dependent)
        s1_prompt = scene1.get("image_prompt", "").lower()
        s1_tier = scene1.get("visual_tier", "")
        scale_count = sum(1 for kw in SCALE_KEYWORDS if kw in s1_prompt)
        if s1_tier in ("TIER_4_ARCHITECTURE",):
            scale_status = "PASS" if scale_count >= MIN_SCALE_KEYWORDS else "FAIL"
        else:
            scale_status = "PASS"  # Non-architecture tiers don't require scale keywords

        return {
            "global_settings": gs_status,
            "scene1_scale_keywords": scale_status,
            "anti_toy_negative": anti_toy_status,
            "anti_yellow_negative": anti_yellow_status
        }

    def _build_loop_check(self) -> Dict[str, str]:
        """Побудувати loop_check об'єкт."""
        vs = self._data.get("visual_summary", {})
        lv = vs.get("loop_verification", {})

        return {
            "movements_different": "PASS" if lv.get("movements_are_different") else "FAIL",
            "no_meta_instructions": self._check_last_scene_meta(),
            "foreground_match": "PASS" if lv.get("foreground_match") else "WARNING",
            "lighting_match": "PASS" if lv.get("lighting_match") else "WARNING"
        }

    def _check_last_scene_meta(self) -> str:
        """Перевірити last scene на meta-instructions."""
        scenes = self._data.get("scenes", [])
        if not scenes:
            return "N/A"

        last_scene = scenes[-1]
        video_prompt = last_scene.get("video_prompt", "").lower()

        for meta in BANNED_LAST_SCENE_META:
            if meta in video_prompt:
                return "FAIL"

        return "PASS"


# ============================================================================
# CONVENIENCE FUNCTION
# ============================================================================

def validate_gen2(
    data: Dict[str, Any],
    gen1_data: Optional[Dict[str, Any]] = None,
    auto_fix: bool = True,
) -> Gen2ValidationResult:
    """
    Зручна функція для валідації GEN2 виходу.

    Args:
        data: GEN2 JSON вихід як словник (modified in-place if auto_fix=True)
        gen1_data: Опціональний GEN1 вихід для cross-validation
        auto_fix: Автоматично виправляти банальні помилки (default True)

    Returns:
        Gen2ValidationResult

    Example:
        result = validate_gen2(gen2_json)

        if result.passed:
            print("✅ Ready for IMG_GEN")
        else:
            for error in result.errors:
                print(f"  - {error}")
    """
    validator = Gen2Validator()
    return validator.validate(data, gen1_data, auto_fix=auto_fix)


# ============================================================================
# EXPORT
# ============================================================================

__all__ = [
    # Main
    "Gen2Validator",
    "Gen2ValidationResult",
    "ValidationError",
    "SceneCheckResult",
    "validate_gen2",

    # Enums
    "ReferenceType",

    # Constants
    "BANNED_VIDEO_WORDS",
    "BANNED_CAMERA_MOVEMENTS",
    "ALLOWED_CAMERA_MOVEMENTS",
    "SCALE_KEYWORDS",
    "ANTI_TOY_KEYWORDS",
]
