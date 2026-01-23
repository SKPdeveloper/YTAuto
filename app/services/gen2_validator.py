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

# Мінімальна кількість motion_elements (оновлено в v1.2)
MIN_MOTION_ELEMENTS: int = 3

# Максимальна кількість слів у video_prompt
MAX_VIDEO_PROMPT_WORDS: int = 40

# Мінімальна кількість scale keywords для Scene 1
MIN_SCALE_KEYWORDS: int = 2

# Scale keywords для Scene 1 (VAL_GEN2 рядок 457-463)
SCALE_KEYWORDS: Set[str] = {
    "towering", "imposing", "massive", "low angle", "looking up", "looms"
}

# Anti-toy keywords в negative_prompt (VAL_GEN2 рядок 246)
ANTI_TOY_KEYWORDS: Set[str] = {
    "tilt-shift", "miniature", "diorama", "toy"
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
    "rack focus", "speed ramp", "dolly zoom"
}

# Banned camera movements (VAL_GEN2 рядки 316-323)
# Note: "drifting/floating" for objects (clouds, particles) is OK
#       Only banned when referring to CAMERA movement
BANNED_CAMERA_MOVEMENTS: Set[str] = {
    "drifting", "floating", "gliding",
    "drift", "float", "glide"
}

# Patterns where drifting/floating is OK (object motion, not camera)
ALLOWED_DRIFTING_CONTEXTS: Set[str] = {
    "clouds drifting",
    "cloud drifting",
    "smoke drifting",
    "mist drifting",
    "particles drifting",
    "leaves drifting",
    "petals drifting",
    "clouds floating",
    "particles floating",
    "debris floating"
}

# Allowed camera movements (gerunds) (VAL_GEN2 рядки 324-326)
ALLOWED_CAMERA_MOVEMENTS: Set[str] = {
    "pushing", "pulling", "orbiting", "rising", "descending",
    "tracking", "emerging", "crane", "craning", "ascending"
}

# Meta-instructions заборонені в Scene 6 (VAL_GEN2 рядки 342-347)
BANNED_SCENE6_META: Set[str] = {
    "matching scene 1",
    "matching opening shot",
    "(reverse in post)",
    "reverse in post",
    "same as before",
    "10s"
}

# Easter egg forbidden zones (VAL_GEN2 рядки 403-407)
FORBIDDEN_EGG_ZONES: Set[str] = {"bottom-center", "bottom center"}
WARNING_EGG_ZONES: Set[str] = {"bottom-left", "bottom-right", "bottom left", "bottom right"}
SAFE_EGG_ZONES: Set[str] = {
    "top-left", "top-right", "center-left", "center-right",
    "top left", "top right", "center left", "center right",
    "center", "top", "top-center", "top center"
}

# Exterior scenes що потребують scale_techniques
EXTERIOR_SCENES: Set[int] = {1, 5, 6}


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

    # Метадані
    validation_time_ms: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now().astimezone().isoformat())
    validator_version: str = "1.0"

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
        return {
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

    def __init__(self):
        self._errors: List[ValidationError] = []
        self._warnings: List[ValidationError] = []
        self._scene_checks: List[SceneCheckResult] = []
        self._data: Dict[str, Any] = {}
        self._gen1_data: Optional[Dict[str, Any]] = None

        # Для loop verification
        self._scene1_movement: str = ""
        self._scene6_movement: str = ""

    def validate(
        self,
        data: Dict[str, Any],
        gen1_data: Optional[Dict[str, Any]] = None
    ) -> Gen2ValidationResult:
        """
        Валідувати GEN2 JSON вихід.

        Args:
            data: Словник з GEN2 JSON виходом
            gen1_data: Опціональний GEN1 вихід для cross-validation

        Returns:
            Gen2ValidationResult
        """
        start_time = time.perf_counter()

        # Reset state
        self._errors = []
        self._warnings = []
        self._scene_checks = []
        self._data = data
        self._gen1_data = gen1_data
        self._scene1_movement = ""
        self._scene6_movement = ""

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
            validation_time_ms=validation_time_ms
        )

        # Log result
        if passed:
            logger.success(
                f"GEN2 validation PASSED in {validation_time_ms:.2f}ms "
                f"({len(self._warnings)} warnings)"
            )
        else:
            logger.warning(
                f"GEN2 validation FAILED in {validation_time_ms:.2f}ms "
                f"({len(self._errors)} errors, {len(self._warnings)} warnings)"
            )

        return result

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

        # gigantism_applied
        if gs.get("gigantism_applied") is not True:
            self._add_error(
                "global_settings.gigantism_applied",
                "Must be true",
                code="GIGANTISM_NOT_APPLIED"
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
            # Check for anti-toy keywords
            negative_lower = negative.lower()
            missing_keywords = []
            for keyword in ANTI_TOY_KEYWORDS:
                if keyword not in negative_lower:
                    missing_keywords.append(keyword)

            if missing_keywords:
                self._add_error(
                    "global_settings.negative_prompt",
                    f"Missing anti-toy keywords: {', '.join(missing_keywords)}",
                    code="MISSING_ANTI_TOY",
                    suggestion="Add: tilt-shift, miniature, diorama, toy"
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

        # total_scenes
        if vs.get("total_scenes") != 6:
            self._add_error(
                "visual_summary.total_scenes",
                f"Must be 6, got {vs.get('total_scenes')}",
                code="INVALID_TOTAL_SCENES"
            )

        # gigantism_protocol
        if vs.get("gigantism_protocol") != "APPLIED":
            self._add_error(
                "visual_summary.gigantism_protocol",
                f"Must be 'APPLIED', got '{vs.get('gigantism_protocol')}'",
                code="GIGANTISM_NOT_APPLIED"
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
        if lv.get("movements_are_different") is not True:
            self._add_error(
                "visual_summary.loop_verification.movements_are_different",
                "Must be true — Scene 6 movement must differ from Scene 1",
                code="SAME_LOOP_MOVEMENT",
                suggestion="Use COMPLEMENTARY movement for Scene 6"
            )

        # loop_ready
        if lv.get("loop_ready") is not True:
            self._add_error(
                "visual_summary.loop_verification.loop_ready",
                "Must be true",
                code="LOOP_NOT_READY"
            )

        # Match fields
        if lv.get("foreground_match") is not True:
            self._add_warning(
                "visual_summary.loop_verification.foreground_match",
                "Should be true — Scene 1 and 6 foreground should match"
            )

        if lv.get("lighting_match") is not True:
            self._add_warning(
                "visual_summary.loop_verification.lighting_match",
                "Should be true — Scene 1 and 6 lighting should match"
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

        if len(scenes) != 6:
            self._add_error(
                "scenes",
                f"Must have exactly 6 items, got {len(scenes)}",
                code="INVALID_SCENE_COUNT"
            )
            return

        # Get easter egg scene from GEN1 or from scenes
        easter_egg_scene = self._get_easter_egg_scene()

        for i, scene in enumerate(scenes):
            scene_num = scene.get("scene_number", i + 1)
            self._validate_scene(scene, scene_num, i, easter_egg_scene)

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
        if not ref_type:
            self._add_error(
                f"{prefix}.reference_type",
                "Required field is missing",
                code="MISSING_REF_TYPE"
            )
        elif ref_type not in [e.value for e in ReferenceType]:
            self._add_error(
                f"{prefix}.reference_type",
                f"Invalid value '{ref_type}'",
                code="INVALID_REF_TYPE",
                suggestion=f"Must be one of: {', '.join(e.value for e in ReferenceType)}"
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
            if not self._validate_image_prompt(image_prompt, scene_num, prefix):
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
            elif scene_num == 6:
                self._scene6_movement = video_prompt

        # motion_elements
        motion = scene.get("motion_elements", [])
        if not isinstance(motion, list) or len(motion) < MIN_MOTION_ELEMENTS:
            self._add_error(
                f"{prefix}.motion_elements",
                f"Must have at least {MIN_MOTION_ELEMENTS} items, got {len(motion) if isinstance(motion, list) else 0}",
                code="INSUFFICIENT_MOTION"
            )
            check.motion_elements = "FAIL"

        # scale_techniques (required for exterior scenes 1, 5, 6)
        if scene_num in EXTERIOR_SCENES:
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
            elif not inheritance.get("parent_scene"):
                self._add_error(
                    f"{prefix}.inheritance.parent_scene",
                    "Required field is missing",
                    code="MISSING_PARENT_SCENE"
                )
                check.inheritance = "FAIL"

        # Scene 1 specific
        if scene_num == 1:
            self._validate_scene1_specific(scene, prefix, check)

        # Scene 6 specific
        if scene_num == 6:
            self._validate_scene6_specific(scene, prefix, check)

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
            # Check required fields
            required = ["hook_element", "foreground", "scale_proof", "safe_zone"]
            for field_name in required:
                if not ffc.get(field_name):
                    self._add_warning(
                        f"{prefix}.first_frame_composition.{field_name}",
                        "Should not be empty"
                    )

        # image_prompt must have >= 2 scale keywords
        image_prompt = scene.get("image_prompt", "").lower()
        scale_count = sum(1 for kw in SCALE_KEYWORDS if kw in image_prompt)
        if scale_count < MIN_SCALE_KEYWORDS:
            self._add_error(
                f"{prefix}.image_prompt",
                f"Scene 1 must have at least {MIN_SCALE_KEYWORDS} scale keywords, found {scale_count}",
                code="INSUFFICIENT_SCALE_KEYWORDS",
                suggestion=f"Add: {', '.join(SCALE_KEYWORDS)}"
            )

    def _validate_scene6_specific(
        self,
        scene: Dict[str, Any],
        prefix: str,
        check: SceneCheckResult
    ) -> None:
        """Валідація специфічних правил для Scene 6."""
        check.loop_complementary = "PASS"

        # reference_type must be LOOP_CLOSE
        if scene.get("reference_type") != ReferenceType.LOOP_CLOSE.value:
            self._add_error(
                f"{prefix}.reference_type",
                f"Scene 6 must be 'LOOP_CLOSE', got '{scene.get('reference_type')}'",
                code="INVALID_SCENE6_REF_TYPE"
            )

        # video_prompt must not have meta-instructions
        video_prompt = scene.get("video_prompt", "").lower()
        for meta in BANNED_SCENE6_META:
            if meta in video_prompt:
                self._add_error(
                    f"{prefix}.video_prompt",
                    f"Scene 6 contains banned meta-instruction: '{meta}'",
                    code="BANNED_META_INSTRUCTION",
                    suggestion="Remove meta-instructions — Kling doesn't understand them"
                )
                check.loop_complementary = "FAIL"

    # ========================================================================
    # IMAGE PROMPT VALIDATION
    # ========================================================================

    def _validate_image_prompt(
        self,
        prompt: str,
        scene_num: int,
        prefix: str
    ) -> bool:
        """
        Валідація image_prompt.

        Returns:
            True якщо валідний
        """
        valid = True
        prompt_lower = prompt.lower()

        # Check for safe zone instruction
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
        if "--ar 9:16" in prompt or "--ar 9\\:16" in prompt:
            self._add_warning(
                f"{prefix}.image_prompt",
                "Contains --ar 9:16 which is hardcoded in software",
                suggestion="Remove aspect ratio — it's added automatically"
            )

        # Note: Anti-toy keywords are enforced via global_settings.negative_prompt (ERROR).
        # Per-scene check removed as redundant - global negative is appended during generation.

        return valid

    # ========================================================================
    # VIDEO PROMPT VALIDATION
    # ========================================================================

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

        # Word count check
        word_count = len(prompt.split())
        if word_count > MAX_VIDEO_PROMPT_WORDS:
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

        # Check for banned camera movements
        for banned in BANNED_CAMERA_MOVEMENTS:
            pattern = r'\b' + re.escape(banned) + r'\b'
            if re.search(pattern, prompt_lower):
                # Check if it's in an allowed context (e.g., "clouds drifting")
                is_allowed_context = any(
                    ctx in prompt_lower for ctx in ALLOWED_DRIFTING_CONTEXTS
                )
                if not is_allowed_context:
                    self._add_error(
                        f"{prefix}.video_prompt",
                        f"Contains banned camera movement: '{banned}'",
                        code="BANNED_CAMERA_MOVEMENT",
                        suggestion=self._get_banned_movement_replacement(banned)
                    )
                    valid = False

        # Check for at least one allowed camera movement (gerund)
        has_movement = any(mv in prompt_lower for mv in ALLOWED_CAMERA_MOVEMENTS)
        if not has_movement:
            self._add_warning(
                f"{prefix}.video_prompt",
                "No camera movement gerund found",
                suggestion=f"Add one of: {', '.join(sorted(ALLOWED_CAMERA_MOVEMENTS))}"
            )

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
            "gliding": "tracking, pushing"
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
        """Валідація loop (Scene 1 vs Scene 6 movements)."""
        if not self._scene1_movement or not self._scene6_movement:
            return  # Already reported as missing

        # Extract key movement words
        scene1_movements = self._extract_movement_words(self._scene1_movement)
        scene6_movements = self._extract_movement_words(self._scene6_movement)

        # Check if movements are too similar
        if scene1_movements and scene6_movements:
            common = scene1_movements & scene6_movements
            # If more than half are common, movements are too similar
            total = len(scene1_movements | scene6_movements)
            if len(common) > total / 2:
                self._add_warning(
                    "scenes[5].video_prompt",
                    f"Scene 6 movement similar to Scene 1. Common: {', '.join(common)}",
                    suggestion="Use COMPLEMENTARY movement (e.g., if Scene 1 is PUSH, Scene 6 should be RISE)"
                )

    def _extract_movement_words(self, prompt: str) -> Set[str]:
        """Витягнути movement слова з prompt."""
        prompt_lower = prompt.lower()
        movements = set()

        movement_keywords = {
            "push", "pushing", "pull", "pulling",
            "orbit", "orbiting", "rise", "rising",
            "descend", "descending", "track", "tracking",
            "crane", "craning", "ascend", "ascending",
            "emerge", "emerging"
        }

        for word in movement_keywords:
            if word in prompt_lower:
                # Normalize to base form
                base = word.rstrip("ing")
                if base.endswith("n"):
                    base = base + "e"  # crane, rise
                movements.add(base if len(base) > 3 else word)

        return movements

    # ========================================================================
    # HELPER METHODS
    # ========================================================================

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
        suggestion: str = ""
    ) -> None:
        """Додати попередження."""
        self._warnings.append(ValidationError(
            field=field,
            message=message,
            severity="warning",
            suggestion=suggestion
        ))

    def _build_gigantism_check(self) -> Dict[str, str]:
        """Побудувати gigantism_check об'єкт."""
        gs = self._data.get("global_settings", {})
        scenes = self._data.get("scenes", [])
        scene1 = scenes[0] if scenes else {}

        gs_status = "PASS"
        if not gs or gs.get("gigantism_applied") is not True:
            gs_status = "FAIL"

        # Check anti-toy in negative
        negative = gs.get("negative_prompt", "").lower() if gs else ""
        anti_toy_status = "PASS"
        if not all(kw in negative for kw in ANTI_TOY_KEYWORDS):
            anti_toy_status = "FAIL"

        # Check Scene 1 scale keywords
        s1_prompt = scene1.get("image_prompt", "").lower()
        scale_count = sum(1 for kw in SCALE_KEYWORDS if kw in s1_prompt)
        scale_status = "PASS" if scale_count >= MIN_SCALE_KEYWORDS else "FAIL"

        return {
            "global_settings": gs_status,
            "scene1_scale_keywords": scale_status,
            "anti_toy_negative": anti_toy_status
        }

    def _build_loop_check(self) -> Dict[str, str]:
        """Побудувати loop_check об'єкт."""
        vs = self._data.get("visual_summary", {})
        lv = vs.get("loop_verification", {})

        return {
            "movements_different": "PASS" if lv.get("movements_are_different") else "FAIL",
            "no_meta_instructions": self._check_scene6_meta(),
            "foreground_match": "PASS" if lv.get("foreground_match") else "WARNING",
            "lighting_match": "PASS" if lv.get("lighting_match") else "WARNING"
        }

    def _check_scene6_meta(self) -> str:
        """Перевірити Scene 6 на meta-instructions."""
        scenes = self._data.get("scenes", [])
        if len(scenes) < 6:
            return "N/A"

        scene6 = scenes[5]
        video_prompt = scene6.get("video_prompt", "").lower()

        for meta in BANNED_SCENE6_META:
            if meta in video_prompt:
                return "FAIL"

        return "PASS"


# ============================================================================
# CONVENIENCE FUNCTION
# ============================================================================

def validate_gen2(
    data: Dict[str, Any],
    gen1_data: Optional[Dict[str, Any]] = None
) -> Gen2ValidationResult:
    """
    Зручна функція для валідації GEN2 виходу.

    Args:
        data: GEN2 JSON вихід як словник
        gen1_data: Опціональний GEN1 вихід для cross-validation

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
    return validator.validate(data, gen1_data)


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
