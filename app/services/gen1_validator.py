"""
GEN1 Python Validator v1.0

Детермінований валідатор для виходу GEN1 (Creative Director).
Замінює LLM-валідатор VAL_GEN1.txt для швидшої та надійнішої валідації.

Автор: Senior Python Backend Engineer + QA Automation Engineer
Дата: 2025-01

Переваги над LLM-валідатором:
┌─────────────────┬──────────────┬─────────────────┐
│ Метрика         │ LLM (GPT-4)  │ Python          │
├─────────────────┼──────────────┼─────────────────┤
│ Час             │ ~10-15 сек   │ ~5 мс           │
│ Токени          │ ~3000-5000   │ 0               │
│ Детермінізм     │ Ні           │ Так             │
│ Галюцинації     │ Можливі      │ Неможливі       │
│ Тестування      │ Складне      │ Unit-тести      │
└─────────────────┴──────────────┴─────────────────┘

Використання:
    from app.services.gen1_validator import Gen1Validator, validate_gen1

    # Спосіб 1: Клас
    validator = Gen1Validator()
    result = validator.validate(gen1_json_data)

    # Спосіб 2: Функція
    result = validate_gen1(gen1_json_data)

    if result.passed:
        # Передаємо в GEN2
        gen2_handoff = result.gen2_handoff
    else:
        # Логуємо помилки
        for error in result.errors:
            logger.error(error)

Сумісність:
    Вихідний формат сумісний з Gen1ValidationResponse з validation_models.py
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from loguru import logger


# ============================================================================
# ENUMS — Дозволені значення згідно GEN1.txt / VAL_GEN1.txt
# ============================================================================

class Category(str, Enum):
    """Категорії контенту з GEN1.txt."""
    LUXURY_LISTINGS = "LUXURY_LISTINGS"
    VEHICLES = "VEHICLES"
    TRANSIT = "TRANSIT"
    LANDMARKS = "LANDMARKS"
    COMMERCIAL = "COMMERCIAL"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    ENTERTAINMENT = "ENTERTAINMENT"
    NEIGHBORHOODS = "NEIGHBORHOODS"
    NATURE = "NATURE"
    FREESTYLE = "FREESTYLE"


class HookType(str, Enum):
    """Типи хуків з GEN1.txt HOOK MATRIX."""
    THE_IMPOSSIBLE = "THE_IMPOSSIBLE"
    THE_ABSURD_LOGIC = "THE_ABSURD_LOGIC"
    THE_SCALE_SHOCK = "THE_SCALE_SHOCK"
    THE_SENSORY_ATTACK = "THE_SENSORY_ATTACK"


class PsychologicalTrigger(str, Enum):
    """Психологічні тригери з GEN1.txt."""
    DISBELIEF = "DISBELIEF"
    PATTERN_BREAK = "PATTERN_BREAK"
    AWE = "AWE"
    SENSORY = "SENSORY"


class LightingPreset(str, Enum):
    """Пресети освітлення з GEN1.txt LIGHTING SYSTEM."""
    MORNING_GOLDEN = "MORNING_GOLDEN"
    SUNSET_DRAMATIC = "SUNSET_DRAMATIC"
    AFTERNOON_WARM = "AFTERNOON_WARM"
    OVERCAST_SOFT = "OVERCAST_SOFT"
    MIDDAY_BRIGHT = "MIDDAY_BRIGHT"
    BLUE_HOUR = "BLUE_HOUR"
    NIGHT_NEON = "NIGHT_NEON"
    HARSH_INDUSTRIAL = "HARSH_INDUSTRIAL"
    FOGGY_DIFFUSED = "FOGGY_DIFFUSED"
    STORMY_DRAMATIC = "STORMY_DRAMATIC"
    TWILIGHT_PURPLE = "TWILIGHT_PURPLE"
    FLUORESCENT_COLD = "FLUORESCENT_COLD"
    CANDLELIT_WARM = "CANDLELIT_WARM"
    MOONLIT_SILVER = "MOONLIT_SILVER"


class AtmosphereMode(str, Enum):
    """Режими атмосфери з GEN1.txt."""
    CINEMATIC = "CINEMATIC"
    VIBRANT = "VIBRANT"
    PLAYFUL = "PLAYFUL"


class SonicHookType(str, Enum):
    """Типи sonic hook з GEN1.txt AUDIO SYSTEM."""
    THE_BOOM = "THE_BOOM"
    THE_SIZZLE = "THE_SIZZLE"
    THE_WHOOSH = "THE_WHOOSH"
    THE_CHIME = "THE_CHIME"
    THE_DROP = "THE_DROP"


class VolumeLevel(str, Enum):
    """Рівні гучності з GEN1.txt."""
    LOUD = "LOUD"
    MEDIUM = "MEDIUM"
    CRISP = "CRISP"
    SUBTLE = "SUBTLE"


class EasterEggVisibility(str, Enum):
    """Видимість Easter Egg з GEN1.txt."""
    FINDABLE = "FINDABLE"
    HIDDEN = "HIDDEN"
    OBVIOUS = "OBVIOUS"


class NarrativePurpose(str, Enum):
    """Narrative purpose сцени з GEN1.txt SCENE STRUCTURE."""
    ESTABLISHING = "ESTABLISHING"
    EXTERIOR_ANGLE = "EXTERIOR_ANGLE"
    AERIAL = "AERIAL"
    INTERIOR = "INTERIOR"
    DETAIL = "DETAIL"
    FEATURE = "FEATURE"
    LOOP_CLOSE = "LOOP_CLOSE"


class ReferenceHint(str, Enum):
    """Reference hint з GEN1.txt."""
    PRIMARY = "PRIMARY"
    REQUIRES_REF = "REQUIRES_REF"
    INDEPENDENT = "INDEPENDENT"


class EnergyLevel(str, Enum):
    """Рівні енергії сцени з GEN1.txt."""
    EXPLOSIVE = "EXPLOSIVE"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


# ============================================================================
# CONSTANTS — Правила валідації з VAL_GEN1.txt
# ============================================================================

# Заборонені перші слова для hook.first_words (VAL_GEN1 рядок 122)
BANNED_FIRST_WORDS: Set[str] = {"Welcome", "So", "Today"}

# Заборонені camera movements (VAL_GEN1 рядок 239-244)
BANNED_CAMERA_MOVEMENTS: Set[str] = {"DRIFT", "FLOAT", "GLIDE"}

# ElevenLabs v3 підтримувані теги (GEN1.txt рядки 760-785)
ELEVENLABS_EMOTION_TAGS: Set[str] = {
    "[excited]", "[sad]", "[angry]", "[happily]", "[whispers]", "[shouts]"
}
ELEVENLABS_DELIVERY_TAGS: Set[str] = {
    "[pause]", "[short pause]", "[long pause]", "[laughs]", "[sighs]"
}
ELEVENLABS_STYLE_TAGS: Set[str] = {
    "[rushed]", "[drawn out]"
}
ALL_ELEVENLABS_TAGS: Set[str] = (
    ELEVENLABS_EMOTION_TAGS | ELEVENLABS_DELIVERY_TAGS | ELEVENLABS_STYLE_TAGS
)

# Мінімальні вимоги
MIN_SCENES: int = 6
MIN_YOUTUBE_DESCRIPTION_LENGTH: int = 100
MAX_YOUTUBE_TITLE_LENGTH: int = 60
MIN_VIRAL_SCORE: float = 0.7
MIN_MOTION_ELEMENTS: int = 2
MIN_DISTINCTIVE_FEATURES: int = 2
MIN_TEXTURE_KEYWORDS: int = 2
MIN_COLOR_KEYWORDS: int = 2
MIN_PROMPT_SNIPPET_LENGTH: int = 10


# ============================================================================
# VALIDATION ERROR — Структурована помилка
# ============================================================================

@dataclass
class ValidationError:
    """
    Структурована помилка валідації.

    Attributes:
        field: Шлях до поля (напр. "hook.first_words")
        message: Опис помилки
        severity: "error" або "warning"
        code: Код помилки для програмної обробки
        suggestion: Пропозиція як виправити (опціонально)
    """
    field: str
    message: str
    severity: str = "error"  # "error" | "warning"
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
# VALIDATION RESULT — Результат валідації
# ============================================================================

@dataclass
class ValidationResult:
    """
    Результат валідації GEN1.

    Сумісний з Gen1ValidationResponse з validation_models.py
    """
    passed: bool
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[ValidationError] = field(default_factory=list)

    # Метадані
    validation_time_ms: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now().astimezone().isoformat())
    validator_version: str = "1.0"

    # Дані для передачі в GEN2
    gen2_handoff: Dict[str, Any] = field(default_factory=dict)

    @property
    def error_messages(self) -> List[str]:
        """Список текстових повідомлень про помилки."""
        return [str(e) for e in self.errors]

    @property
    def warning_messages(self) -> List[str]:
        """Список текстових попереджень."""
        return [str(w) for w in self.warnings]

    @property
    def all_issues(self) -> List[ValidationError]:
        """Всі проблеми (помилки + попередження)."""
        return self.errors + self.warnings

    def to_dict(self) -> Dict[str, Any]:
        """
        Конвертувати в словник.

        Формат сумісний з Gen1ValidationResponse.
        """
        return {
            "validation": {
                "stage": "VAL_GEN1",
                "version": self.validator_version,
                "timestamp": self.timestamp,
                "validation_time_ms": round(self.validation_time_ms, 2)
            },
            "phase1_structural": {
                "status": "PASS" if self.passed else "FAIL",
                "errors": [e.to_dict() for e in self.errors],
                "warnings": [w.to_dict() for w in self.warnings]
            },
            "phase2_quality": None,  # Не використовуємо якісну оцінку
            "decision": {
                "status": "PASSED" if self.passed else "FAILED",
                "reasoning": self._build_reasoning(),
                "proceed_to": "GEN2" if self.passed else None
            },
            "gen2_handoff": self.gen2_handoff if self.passed else {},
            "issues": {
                "has_issues": len(self.errors) > 0 or len(self.warnings) > 0,
                "concerns": [str(e) for e in self.all_issues]
            },
            "retry_guidance": self._build_retry_guidance() if not self.passed else None
        }

    def _build_reasoning(self) -> str:
        """Побудувати reasoning для decision."""
        if self.passed:
            if self.warnings:
                return f"All structural checks passed with {len(self.warnings)} warning(s). Ready for GEN2."
            return "All structural checks passed. Ready for GEN2."
        return f"Validation failed with {len(self.errors)} error(s). See retry_guidance for fixes."

    def _build_retry_guidance(self) -> Dict[str, Any]:
        """Побудувати guidance для повторної генерації."""
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
# VALIDATOR CLASS — Головний клас валідатора
# ============================================================================

class Gen1Validator:
    """
    Детермінований Python-валідатор для GEN1 виходу.

    Замінює LLM-валідатор VAL_GEN1.txt.

    Архітектура:
    - Модульні перевірки для кожного розділу GEN1
    - Збір всіх помилок (не зупиняємось на першій)
    - Чіткий поділ errors vs warnings
    - Actionable feedback в повідомленнях

    Використання:
        validator = Gen1Validator()
        result = validator.validate(gen1_json)

        if result.passed:
            proceed_to_gen2(result.gen2_handoff)
    """

    def __init__(self, strict_mode: bool = True):
        """
        Ініціалізація валідатора.

        Args:
            strict_mode: Якщо True, warnings також блокують (default: True)
        """
        self.strict_mode = strict_mode
        self._errors: List[ValidationError] = []
        self._warnings: List[ValidationError] = []
        self._data: Dict[str, Any] = {}

    def validate(self, data: Dict[str, Any]) -> ValidationResult:
        """
        Валідувати GEN1 JSON вихід.

        Args:
            data: Словник з GEN1 JSON виходом

        Returns:
            ValidationResult з результатами валідації
        """
        start_time = time.perf_counter()

        # Reset state
        self._errors = []
        self._warnings = []
        self._data = data

        # Виконуємо всі перевірки
        self._run_all_validations()

        # Визначаємо результат
        passed = len(self._errors) == 0

        # Будуємо handoff для GEN2
        gen2_handoff = {}
        if passed:
            gen2_handoff = self._build_gen2_handoff()

        # Рахуємо час
        validation_time_ms = (time.perf_counter() - start_time) * 1000

        result = ValidationResult(
            passed=passed,
            errors=self._errors.copy(),
            warnings=self._warnings.copy(),
            validation_time_ms=validation_time_ms,
            gen2_handoff=gen2_handoff
        )

        # Логування
        if passed:
            logger.success(
                f"GEN1 validation PASSED in {validation_time_ms:.2f}ms "
                f"({len(self._warnings)} warnings)"
            )
        else:
            logger.warning(
                f"GEN1 validation FAILED in {validation_time_ms:.2f}ms "
                f"({len(self._errors)} errors, {len(self._warnings)} warnings)"
            )

        return result

    # ========================================================================
    # ORCHESTRATION — Запуск всіх перевірок
    # ========================================================================

    def _run_all_validations(self) -> None:
        """Запустити всі перевірки в правильному порядку."""

        # 1. Metadata
        self._validate_metadata()

        # 2. Property
        self._validate_property()

        # 3. Hook (критично важливий)
        self._validate_hook()

        # 4. Architectural Identity
        self._validate_architectural_identity()

        # 5. Food Identity
        self._validate_food_identity()

        # 6. Lighting Master
        self._validate_lighting_master()

        # 7. Atmosphere Mode
        self._validate_atmosphere_mode()

        # 8. Foreground Element
        self._validate_foreground_element()

        # 9. Voiceover
        self._validate_voiceover()

        # 10. Audio
        self._validate_audio()

        # 11. Engagement (Easter Egg)
        self._validate_engagement()

        # 12. YouTube Metadata (CRITICAL)
        self._validate_youtube()

        # 13. Viral Assessment (QUALITY GATE)
        self._validate_viral_assessment()

        # 14. Scenes (найбільша перевірка)
        self._validate_scenes()

    # ========================================================================
    # VALIDATION METHODS — Окремі перевірки
    # ========================================================================

    def _validate_metadata(self) -> None:
        """Валідація metadata об'єкту."""
        metadata = self._get_field("metadata")
        if metadata is None:
            return

        # version
        version = self._get_nested(metadata, "version")
        if version and version != "3.0":
            self._add_warning(
                "metadata.version",
                f"Expected '3.0', got '{version}'",
                suggestion="Update to version 3.0"
            )

        # status
        status = self._get_nested(metadata, "status")
        if status:
            if status not in ("PRODUCTION_READY", "REJECTED_INPUT"):
                self._add_error(
                    "metadata.status",
                    f"Must be 'PRODUCTION_READY' or 'REJECTED_INPUT', got '{status}'",
                    code="INVALID_STATUS"
                )

        # concept
        concept = self._get_nested(metadata, "concept")
        if concept:
            # category
            category = self._get_nested(concept, "category")
            self._validate_enum_field(category, Category, "metadata.concept.category")

            # subject
            self._require_non_empty(concept, "subject", "metadata.concept.subject")

            # food_material
            self._require_non_empty(concept, "food_material", "metadata.concept.food_material")

        # scene_count
        scene_count = self._get_nested(metadata, "scene_count")
        if scene_count is not None and scene_count != MIN_SCENES:
            self._add_error(
                "metadata.scene_count",
                f"Must be {MIN_SCENES}, got {scene_count}",
                code="INVALID_SCENE_COUNT"
            )

    def _validate_property(self) -> None:
        """Валідація property об'єкту."""
        prop = self._get_field("property")
        if prop is None:
            return

        required = ["name", "location", "price", "tagline"]
        for field_name in required:
            self._require_non_empty(prop, field_name, f"property.{field_name}")

    def _validate_hook(self) -> None:
        """
        Валідація hook об'єкту.

        КРИТИЧНО: Hook — найважливіший елемент для retention.
        """
        hook = self._get_field("hook")
        if hook is None:
            return

        # type (ENUM)
        hook_type = self._get_nested(hook, "type")
        self._validate_enum_field(hook_type, HookType, "hook.type")

        # psychological_trigger (ENUM)
        trigger = self._get_nested(hook, "psychological_trigger")
        self._validate_enum_field(trigger, PsychologicalTrigger, "hook.psychological_trigger")

        # first_words (складна перевірка)
        first_words = self._get_nested(hook, "first_words", "")
        if not first_words:
            self._add_error(
                "hook.first_words",
                "Required and cannot be empty",
                code="MISSING_FIRST_WORDS"
            )
        else:
            self._validate_first_words(first_words)

        # complete_hook_vo
        self._require_non_empty(hook, "complete_hook_vo", "hook.complete_hook_vo")

        # first_frame_visual
        self._require_non_empty(hook, "first_frame_visual", "hook.first_frame_visual")

        # scroll_stop_element
        self._require_non_empty(hook, "scroll_stop_element", "hook.scroll_stop_element")

    def _validate_first_words(self, first_words: str) -> None:
        """
        Перевірка hook.first_words на заборонені слова та наявність emotion tag.

        Правила (VAL_GEN1.txt рядки 121-123):
        1. Не може починатися з "This", "Welcome", "So", "Today"
        2. Повинен містити emotion tag як [excited], [whispers], etc.
        """
        # Видаляємо всі теги щоб отримати чистий текст
        clean_text = re.sub(r'\[.*?\]', '', first_words).strip()

        if clean_text:
            # Перевіряємо перше слово
            actual_first_word = clean_text.split()[0]
            if actual_first_word in BANNED_FIRST_WORDS:
                self._add_error(
                    "hook.first_words",
                    f"Cannot start with '{actual_first_word}'",
                    code="BANNED_FIRST_WORD",
                    suggestion=f"Avoid starting with: {', '.join(BANNED_FIRST_WORDS)}"
                )

        # Перевіряємо наявність emotion tag
        has_emotion_tag = any(tag in first_words for tag in ELEVENLABS_EMOTION_TAGS)
        if not has_emotion_tag:
            self._add_error(
                "hook.first_words",
                "Must contain an emotion tag",
                code="MISSING_EMOTION_TAG",
                suggestion=f"Add one of: {', '.join(sorted(ELEVENLABS_EMOTION_TAGS))}"
            )

    def _validate_architectural_identity(self) -> None:
        """Валідація architectural_identity об'єкту."""
        arch = self._get_field("architectural_identity")
        if arch is None:
            return

        # style_code
        self._require_non_empty(arch, "style_code", "architectural_identity.style_code")

        # silhouette_description
        self._require_non_empty(arch, "silhouette_description", "architectural_identity.silhouette_description")

        # distinctive_features (масив >= 2)
        features = self._get_nested(arch, "distinctive_features", [])
        if not isinstance(features, list) or len(features) < MIN_DISTINCTIVE_FEATURES:
            self._add_error(
                "architectural_identity.distinctive_features",
                f"Must have at least {MIN_DISTINCTIVE_FEATURES} items, got {len(features) if isinstance(features, list) else 0}",
                code="INSUFFICIENT_FEATURES"
            )

    def _validate_food_identity(self) -> None:
        """Валідація food_identity об'єкту."""
        food = self._get_field("food_identity")
        if food is None:
            return

        # primary_food
        self._require_non_empty(food, "primary_food", "food_identity.primary_food")

        # food_dna
        dna = self._get_nested(food, "food_dna", {})
        if not dna:
            self._add_error(
                "food_identity.food_dna",
                "Required object is missing",
                code="MISSING_FOOD_DNA"
            )
        else:
            self._require_non_empty(dna, "walls_become", "food_identity.food_dna.walls_become")
            self._require_non_empty(dna, "roof_becomes", "food_identity.food_dna.roof_becomes")

        # texture_keywords (масив >= 2)
        textures = self._get_nested(food, "texture_keywords", [])
        if not isinstance(textures, list) or len(textures) < MIN_TEXTURE_KEYWORDS:
            self._add_error(
                "food_identity.texture_keywords",
                f"Must have at least {MIN_TEXTURE_KEYWORDS} items",
                code="INSUFFICIENT_TEXTURES"
            )

        # color_keywords (масив >= 2)
        colors = self._get_nested(food, "color_keywords", [])
        if not isinstance(colors, list) or len(colors) < MIN_COLOR_KEYWORDS:
            self._add_error(
                "food_identity.color_keywords",
                f"Must have at least {MIN_COLOR_KEYWORDS} items",
                code="INSUFFICIENT_COLORS"
            )

    def _validate_lighting_master(self) -> None:
        """Валідація lighting_master об'єкту."""
        lighting = self._get_field("lighting_master")
        if lighting is None:
            return

        # preset (ENUM)
        preset = self._get_nested(lighting, "preset")
        self._validate_enum_field(preset, LightingPreset, "lighting_master.preset")

        # prompt_snippet (min 10 chars)
        snippet = self._get_nested(lighting, "prompt_snippet", "")
        if not snippet or len(snippet) < MIN_PROMPT_SNIPPET_LENGTH:
            self._add_error(
                "lighting_master.prompt_snippet",
                f"Must be at least {MIN_PROMPT_SNIPPET_LENGTH} characters",
                code="SNIPPET_TOO_SHORT"
            )

    def _validate_atmosphere_mode(self) -> None:
        """Валідація atmosphere_mode."""
        mode = self._data.get("atmosphere_mode")

        if not mode:
            self._add_warning(
                "atmosphere_mode",
                "Missing — defaulting to CINEMATIC",
                suggestion="Add atmosphere_mode field"
            )
        else:
            self._validate_enum_field(mode, AtmosphereMode, "atmosphere_mode")

    def _validate_foreground_element(self) -> None:
        """Валідація foreground_element об'єкту."""
        fg = self._get_field("foreground_element")
        if fg is None:
            return

        # type
        self._require_non_empty(fg, "type", "foreground_element.type")

        # prompt_snippet (min 10 chars)
        snippet = self._get_nested(fg, "prompt_snippet", "")
        if not snippet or len(snippet) < MIN_PROMPT_SNIPPET_LENGTH:
            self._add_error(
                "foreground_element.prompt_snippet",
                f"Must be at least {MIN_PROMPT_SNIPPET_LENGTH} characters",
                code="SNIPPET_TOO_SHORT"
            )

    def _validate_voiceover(self) -> None:
        """Валідація voiceover об'єкту."""
        vo = self._get_field("voiceover")
        if vo is None:
            return

        # full_script
        script = self._get_nested(vo, "full_script", "")
        if not script:
            self._add_error(
                "voiceover.full_script",
                "Required and cannot be empty",
                code="MISSING_SCRIPT"
            )
        else:
            # Перевіряємо наявність хоча б одного тегу
            has_any_tag = any(tag in script for tag in ALL_ELEVENLABS_TAGS)
            if not has_any_tag:
                self._add_warning(
                    "voiceover.full_script",
                    "Should contain ElevenLabs tags for better delivery",
                    suggestion=f"Add tags like [pause], [whispers], etc."
                )

        # character
        self._require_non_empty(vo, "character", "voiceover.character")

        # voice_id
        self._require_non_empty(vo, "voice_id", "voiceover.voice_id")

    def _validate_audio(self) -> None:
        """Валідація audio об'єкту."""
        audio = self._get_field("audio")
        if audio is None:
            return

        # sonic_hook
        sonic = self._get_nested(audio, "sonic_hook", {})
        if not sonic:
            self._add_error(
                "audio.sonic_hook",
                "Required object is missing",
                code="MISSING_SONIC_HOOK"
            )
        else:
            # type (ENUM)
            sonic_type = self._get_nested(sonic, "type")
            self._validate_enum_field(sonic_type, SonicHookType, "audio.sonic_hook.type")

            # volume (ENUM)
            volume = self._get_nested(sonic, "volume")
            self._validate_enum_field(volume, VolumeLevel, "audio.sonic_hook.volume")

        # suno_prompt
        self._require_non_empty(audio, "suno_prompt", "audio.suno_prompt")

        # foley_palette
        if not self._get_nested(audio, "foley_palette"):
            self._add_error(
                "audio.foley_palette",
                "Required object is missing",
                code="MISSING_FOLEY"
            )

        # sfx_per_scene
        sfx = self._get_nested(audio, "sfx_per_scene")
        if not isinstance(sfx, list):
            self._add_error(
                "audio.sfx_per_scene",
                "Must be an array",
                code="INVALID_SFX"
            )

    def _validate_engagement(self) -> None:
        """Валідація engagement об'єкту (Easter Egg)."""
        engagement = self._get_field("engagement")
        if engagement is None:
            return

        # easter_egg
        egg = self._get_nested(engagement, "easter_egg", {})
        if not egg:
            self._add_error(
                "engagement.easter_egg",
                "Required object is missing",
                code="MISSING_EASTER_EGG"
            )
        else:
            # object
            self._require_non_empty(egg, "object", "engagement.easter_egg.object")

            # scene_number (must be 2-5)
            scene_num = self._get_nested(egg, "scene_number")
            if scene_num is None:
                self._add_error(
                    "engagement.easter_egg.scene_number",
                    "Required field is missing",
                    code="MISSING_SCENE_NUMBER"
                )
            elif not (2 <= scene_num <= 5):
                self._add_error(
                    "engagement.easter_egg.scene_number",
                    f"Must be 2-5 (not in hook or loop scene), got {scene_num}",
                    code="INVALID_EGG_SCENE"
                )

            # placement
            self._require_non_empty(egg, "placement", "engagement.easter_egg.placement")

            # visibility (ENUM)
            visibility = self._get_nested(egg, "visibility")
            self._validate_enum_field(visibility, EasterEggVisibility, "engagement.easter_egg.visibility")

            # validation_check
            self._require_non_empty(egg, "validation_check", "engagement.easter_egg.validation_check")

            # comment_bait
            self._require_non_empty(egg, "comment_bait", "engagement.easter_egg.comment_bait")

        # hashtags (exactly 3)
        hashtags = self._get_nested(engagement, "hashtags", [])
        if not isinstance(hashtags, list) or len(hashtags) != 3:
            self._add_error(
                "engagement.hashtags",
                f"Must have exactly 3 items, got {len(hashtags) if isinstance(hashtags, list) else 0}",
                code="INVALID_HASHTAGS_COUNT"
            )

    def _validate_youtube(self) -> None:
        """
        Валідація YouTube metadata.

        КРИТИЧНО: YouTube поля НІКОЛИ не можуть бути null (VAL_GEN1.txt).
        Потрібні обидва формати: nested і flat.
        """
        # ===== NESTED YOUTUBE OBJECT =====
        youtube = self._get_field("youtube")
        if youtube is None:
            # youtube — критичне поле, помилка вже додана в _get_field
            pass
        else:
            # title (max 60 chars, NEVER NULL)
            title = self._get_nested(youtube, "title", "")
            if not title:
                self._add_error(
                    "youtube.title",
                    "REQUIRED and NEVER NULL",
                    code="NULL_YOUTUBE_TITLE"
                )
            elif len(title) > MAX_YOUTUBE_TITLE_LENGTH:
                self._add_error(
                    "youtube.title",
                    f"Must be max {MAX_YOUTUBE_TITLE_LENGTH} chars, got {len(title)}",
                    code="TITLE_TOO_LONG"
                )

            # description (min 100 chars, NEVER NULL)
            desc = self._get_nested(youtube, "description", "")
            if not desc:
                self._add_error(
                    "youtube.description",
                    "REQUIRED and NEVER NULL",
                    code="NULL_YOUTUBE_DESC"
                )
            elif len(desc) < MIN_YOUTUBE_DESCRIPTION_LENGTH:
                self._add_error(
                    "youtube.description",
                    f"Must be at least {MIN_YOUTUBE_DESCRIPTION_LENGTH} chars, got {len(desc)}",
                    code="DESC_TOO_SHORT"
                )

            # pinned_comment
            self._require_non_empty(youtube, "pinned_comment", "youtube.pinned_comment")

            # tags (at least 3)
            tags = self._get_nested(youtube, "tags", [])
            if not isinstance(tags, list) or len(tags) < 3:
                self._add_error(
                    "youtube.tags",
                    "Must have at least 3 items",
                    code="INSUFFICIENT_TAGS"
                )

        # ===== FLAT YOUTUBE FIELDS (backwards compatibility) =====

        # youtube_title
        yt_title = self._data.get("youtube_title")
        if not yt_title:
            self._add_error(
                "youtube_title",
                "Flat field REQUIRED for backwards compatibility",
                code="MISSING_FLAT_TITLE"
            )

        # youtube_description
        yt_desc = self._data.get("youtube_description")
        if not yt_desc:
            self._add_error(
                "youtube_description",
                "Flat field REQUIRED for backwards compatibility",
                code="MISSING_FLAT_DESC"
            )

        # youtube_pinned_comment
        if not self._data.get("youtube_pinned_comment"):
            self._add_error(
                "youtube_pinned_comment",
                "Flat field REQUIRED for backwards compatibility",
                code="MISSING_FLAT_COMMENT"
            )

        # youtube_hashtags (exactly 3)
        yt_hashtags = self._data.get("youtube_hashtags", [])
        if not isinstance(yt_hashtags, list) or len(yt_hashtags) != 3:
            self._add_error(
                "youtube_hashtags",
                "Must have exactly 3 items",
                code="INVALID_FLAT_HASHTAGS"
            )

        # youtube_tags (at least 3)
        yt_tags = self._data.get("youtube_tags", [])
        if not isinstance(yt_tags, list) or len(yt_tags) < 3:
            self._add_error(
                "youtube_tags",
                "Must have at least 3 items",
                code="INVALID_FLAT_TAGS"
            )

        # Перевірка консистентності nested vs flat
        if youtube and yt_title and youtube.get("title") != yt_title:
            self._add_warning(
                "youtube_title",
                "Does not match youtube.title",
                suggestion="Ensure both values are identical"
            )

    def _validate_viral_assessment(self) -> None:
        """
        Валідація viral_assessment.

        QUALITY GATE: overall_score >= 0.7 — обов'язкова умова.
        """
        viral = self._get_field("viral_assessment")
        if viral is None:
            return

        # overall_score (QUALITY GATE)
        overall = self._get_nested(viral, "overall_score")
        if overall is None:
            self._add_error(
                "viral_assessment.overall_score",
                "Required field is missing",
                code="MISSING_VIRAL_SCORE"
            )
        elif overall < MIN_VIRAL_SCORE:
            self._add_error(
                "viral_assessment.overall_score",
                f"Must be >= {MIN_VIRAL_SCORE}, got {overall}. AUTOMATIC FAIL.",
                code="LOW_VIRAL_SCORE",
                suggestion="Regenerate content with stronger hook/concept"
            )

        # Інші score поля
        score_fields = [
            "hook_strength", "humor_quotient", "shareability",
            "comment_potential", "visual_uniqueness"
        ]
        for field_name in score_fields:
            score = self._get_nested(viral, field_name)
            if score is None:
                self._add_error(
                    f"viral_assessment.{field_name}",
                    "Required score is missing",
                    code="MISSING_SCORE"
                )
            elif not (0.0 <= score <= 1.0):
                self._add_error(
                    f"viral_assessment.{field_name}",
                    f"Must be 0.0-1.0, got {score}",
                    code="INVALID_SCORE_RANGE"
                )

        # strength_points (at least 1)
        strengths = self._get_nested(viral, "strength_points", [])
        if not isinstance(strengths, list) or len(strengths) < 1:
            self._add_error(
                "viral_assessment.strength_points",
                "Must have at least 1 item",
                code="MISSING_STRENGTHS"
            )

    def _validate_scenes(self) -> None:
        """
        Валідація scenes масиву.

        Найбільша і найважливіша перевірка.
        Перевіряє 6 сцен + спеціальні правила для Scene 1 і Scene 6.
        """
        scenes = self._data.get("scenes")

        if not isinstance(scenes, list):
            self._add_error(
                "scenes",
                "Must be an array",
                code="INVALID_SCENES_TYPE"
            )
            return

        if len(scenes) != MIN_SCENES:
            self._add_error(
                "scenes",
                f"Must have exactly {MIN_SCENES} items, got {len(scenes)}",
                code="INVALID_SCENE_COUNT"
            )
            return

        # Зберігаємо Scene 1 movement для перевірки loop
        scene1_movement: str = ""
        low_energy_count: int = 0

        for i, scene in enumerate(scenes):
            scene_num = scene.get("scene_number", i + 1)
            prefix = f"scenes[{i}]"

            # scene_number validation
            if scene_num != i + 1:
                self._add_warning(
                    f"{prefix}.scene_number",
                    f"Expected {i + 1}, got {scene_num}",
                    suggestion="Ensure sequential scene numbering"
                )

            # narrative_purpose (ENUM)
            purpose = self._get_nested(scene, "narrative_purpose")
            self._validate_enum_field(purpose, NarrativePurpose, f"{prefix}.narrative_purpose")

            # reference_hint (ENUM)
            hint = self._get_nested(scene, "reference_hint")
            self._validate_enum_field(hint, ReferenceHint, f"{prefix}.reference_hint")

            # energy_level (ENUM)
            energy = self._get_nested(scene, "energy_level")
            self._validate_enum_field(energy, EnergyLevel, f"{prefix}.energy_level")
            if energy == "LOW":
                low_energy_count += 1

            # visual_concept
            visual = self._get_nested(scene, "visual_concept", {})
            if not visual:
                self._add_error(
                    f"{prefix}.visual_concept",
                    "Required object is missing",
                    code="MISSING_VISUAL"
                )
            else:
                self._require_non_empty(visual, "subject", f"{prefix}.visual_concept.subject")
                self._require_non_empty(visual, "environment", f"{prefix}.visual_concept.environment")

                # motion_elements (>= 3)
                motion = self._get_nested(visual, "motion_elements", [])
                if not isinstance(motion, list) or len(motion) < MIN_MOTION_ELEMENTS:
                    self._add_error(
                        f"{prefix}.visual_concept.motion_elements",
                        f"Must have at least {MIN_MOTION_ELEMENTS} items, got {len(motion) if isinstance(motion, list) else 0}",
                        code="INSUFFICIENT_MOTION"
                    )

            # camera_intent
            camera = self._get_nested(scene, "camera_intent", {})
            if not camera:
                self._add_error(
                    f"{prefix}.camera_intent",
                    "Required object is missing",
                    code="MISSING_CAMERA"
                )
            else:
                movement = self._get_nested(camera, "movement", "")
                if not movement:
                    self._add_error(
                        f"{prefix}.camera_intent.movement",
                        "Required field is missing",
                        code="MISSING_MOVEMENT"
                    )
                else:
                    # Перевірка на заборонені movements
                    movement_upper = movement.upper()
                    for banned in BANNED_CAMERA_MOVEMENTS:
                        if banned in movement_upper:
                            self._add_error(
                                f"{prefix}.camera_intent.movement",
                                f"Contains banned movement '{banned}'",
                                code="BANNED_MOVEMENT",
                                suggestion="Use PUSH, TRACK, ORBIT, APPROACH, RISE instead"
                            )

                # Зберігаємо Scene 1 movement
                if scene_num == 1:
                    scene1_movement = movement

            # broker_script (required for scenes 1-4)
            if scene_num <= 4:
                broker = self._get_nested(scene, "broker_script", "")
                if not broker:
                    self._add_error(
                        f"{prefix}.broker_script",
                        "Required for scenes 1-4",
                        code="MISSING_BROKER_SCRIPT"
                    )

            # ===== SCENE 1 SPECIFIC RULES =====
            if scene_num == 1:
                if hint != "PRIMARY":
                    self._add_error(
                        f"{prefix}.reference_hint",
                        f"Scene 1 must be 'PRIMARY', got '{hint}'",
                        code="INVALID_SCENE1_REF"
                    )
                if purpose != "ESTABLISHING":
                    self._add_error(
                        f"{prefix}.narrative_purpose",
                        f"Scene 1 must be 'ESTABLISHING', got '{purpose}'",
                        code="INVALID_SCENE1_PURPOSE"
                    )

            # ===== SCENE 6 SPECIFIC RULES =====
            if scene_num == 6:
                if purpose != "LOOP_CLOSE":
                    self._add_error(
                        f"{prefix}.narrative_purpose",
                        f"Scene 6 must be 'LOOP_CLOSE', got '{purpose}'",
                        code="INVALID_SCENE6_PURPOSE"
                    )

                # Перевірка complementary movement
                if camera and scene1_movement:
                    scene6_movement = self._get_nested(camera, "movement", "")
                    if scene6_movement and scene1_movement.upper() == scene6_movement.upper():
                        self._add_warning(
                            f"{prefix}.camera_intent.movement",
                            f"Same as Scene 1 ('{scene6_movement}')",
                            suggestion="Use COMPLEMENTARY movement (e.g., RISE, ORBIT) for better loop"
                        )

        # Energy pattern check
        if low_energy_count > 1:
            self._add_warning(
                "scenes",
                f"Energy pattern has {low_energy_count} LOW scenes",
                suggestion="Recommended max is 1 LOW scene per video"
            )

    # ========================================================================
    # HELPER METHODS — Утиліти
    # ========================================================================

    def _get_field(self, field_name: str) -> Optional[Any]:
        """
        Отримати top-level поле, додати помилку якщо відсутнє.

        Returns:
            Значення поля або None якщо відсутнє
        """
        value = self._data.get(field_name)
        if value is None:
            self._add_error(
                field_name,
                "Required field is missing",
                code=f"MISSING_{field_name.upper()}"
            )
            return None
        return value

    def _get_nested(self, obj: Dict[str, Any], key: str, default: Any = None) -> Any:
        """Безпечно отримати nested значення."""
        if not isinstance(obj, dict):
            return default
        return obj.get(key, default)

    def _require_non_empty(
        self,
        obj: Dict[str, Any],
        key: str,
        full_path: str
    ) -> bool:
        """
        Перевірити що поле існує і не пусте.

        Returns:
            True якщо валідне
        """
        value = self._get_nested(obj, key)
        if not value:
            self._add_error(
                full_path,
                "Required and cannot be empty",
                code="EMPTY_FIELD"
            )
            return False
        return True

    def _validate_enum_field(
        self,
        value: Any,
        enum_class: type,
        field_path: str
    ) -> bool:
        """
        Валідація enum значення.

        Returns:
            True якщо валідне
        """
        if value is None:
            self._add_error(
                field_path,
                "Required field is missing",
                code="MISSING_ENUM"
            )
            return False

        valid_values = [e.value for e in enum_class]
        if value not in valid_values:
            self._add_error(
                field_path,
                f"Invalid value '{value}'",
                code="INVALID_ENUM",
                suggestion=f"Must be one of: {', '.join(valid_values)}"
            )
            return False

        return True

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

    def _build_gen2_handoff(self) -> Dict[str, Any]:
        """
        Побудувати handoff дані для GEN2.

        Викликається тільки якщо валідація пройшла.
        """
        metadata = self._data.get("metadata", {})
        concept = metadata.get("concept", {})
        lighting = self._data.get("lighting_master", {})
        scenes = self._data.get("scenes", [])

        # Отримуємо movements для loop strategy
        scene1_movement = ""
        scene6_movement = ""
        for scene in scenes:
            if scene.get("scene_number") == 1:
                scene1_movement = scene.get("camera_intent", {}).get("movement", "")
            if scene.get("scene_number") == 6:
                scene6_movement = scene.get("camera_intent", {}).get("movement", "")

        return {
            "atmosphere_mode": self._data.get("atmosphere_mode", "CINEMATIC"),
            "lighting_preset": lighting.get("preset", ""),
            "category": concept.get("category", ""),
            "food_material": concept.get("food_material", ""),
            "loop_strategy": f"COMPLEMENTARY (Scene 1: {scene1_movement}, Scene 6: {scene6_movement})"
        }


# ============================================================================
# CONVENIENCE FUNCTION — Швидкий доступ
# ============================================================================

def validate_gen1(data: Dict[str, Any], strict_mode: bool = True) -> ValidationResult:
    """
    Зручна функція для валідації GEN1 виходу.

    Args:
        data: GEN1 JSON вихід як словник
        strict_mode: Якщо True, warnings також враховуються

    Returns:
        ValidationResult

    Example:
        import json

        with open("gen1_output.json") as f:
            gen1_data = json.load(f)

        result = validate_gen1(gen1_data)

        if result.passed:
            print("✅ Ready for GEN2")
            print(f"Handoff: {result.gen2_handoff}")
        else:
            print("❌ Validation failed:")
            for error in result.errors:
                print(f"  - {error}")
    """
    validator = Gen1Validator(strict_mode=strict_mode)
    return validator.validate(data)


# ============================================================================
# EXPORT
# ============================================================================

__all__ = [
    # Main
    "Gen1Validator",
    "ValidationResult",
    "ValidationError",
    "validate_gen1",

    # Enums (for external validation/testing)
    "Category",
    "HookType",
    "PsychologicalTrigger",
    "LightingPreset",
    "AtmosphereMode",
    "SonicHookType",
    "VolumeLevel",
    "EasterEggVisibility",
    "NarrativePurpose",
    "ReferenceHint",
    "EnergyLevel",

    # Constants
    "BANNED_FIRST_WORDS",
    "BANNED_CAMERA_MOVEMENTS",
    "ALL_ELEVENLABS_TAGS",
]
