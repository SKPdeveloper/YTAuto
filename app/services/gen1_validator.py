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
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from loguru import logger


# ============================================================================
# BANLIST LOADER — Динамічне завантаження банлисту
# ============================================================================

def _load_banlist_from_file(banlist_path: Optional[Path] = None) -> Dict[str, Set[str]]:
    """
    Завантажує та парсить ban_list.txt.

    Формат файлу:
    - Рядки що починаються з # — заголовки секцій (ігноруються як коментарі)
    - Пусті рядки — роздільники
    - Інші рядки — заборонені слова/фрази

    Returns:
        Dict з категоріями:
        - "first_words": Заборонені перші слова хука
        - "first_phrases": Заборонені початкові фрази
        - "commands": Команди (викликають захисну реакцію)
        - "fillers": Філери (мертвий ефір)
        - "ai_markers": ШІ-маркери (КРИТИЧНО)
        - "overused_adjectives": Перевикористані прикметники
        - "generic_luxury": Generic luxury слова
    """
    if banlist_path is None:
        banlist_path = Path(__file__).parent.parent.parent / "config" / "ban_list.txt"

    result: Dict[str, Set[str]] = {
        "first_words": set(),
        "first_phrases": set(),
        "commands": set(),
        "fillers": set(),
        "ai_markers": set(),
        "overused_adjectives": set(),
        "generic_luxury": set(),
    }

    if not banlist_path.exists():
        logger.warning(f"Banlist file not found: {banlist_path}. Using empty banlist.")
        return result

    try:
        with open(banlist_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        logger.error(f"Failed to read banlist: {e}")
        return result

    # Парсинг секцій
    current_section: Optional[str] = None
    section_map = {
        "заборонені перші слова": "first_words",
        "заборонені початкові фрази": "first_phrases",
        "команди": "commands",
        "філери": "fillers",
        "ші-маркери": "ai_markers",
        "перевикористані прикметники": "overused_adjectives",
        "generic luxury": "generic_luxury",
    }

    for line in content.split("\n"):
        line = line.strip()

        # Пуста лінія
        if not line:
            continue

        # Заголовок секції (коментар)
        if line.startswith("#"):
            header = line.lstrip("#").strip().lower()
            for key, section_name in section_map.items():
                if key in header:
                    current_section = section_name
                    break
            continue

        # Додаємо слово/фразу до поточної секції
        if current_section and line:
            result[current_section].add(line.lower())

    # Логуємо результат
    total = sum(len(v) for v in result.values())
    logger.debug(
        f"Loaded banlist: {total} items "
        f"(first_words: {len(result['first_words'])}, "
        f"ai_markers: {len(result['ai_markers'])}, "
        f"fillers: {len(result['fillers'])})"
    )

    return result


# Глобальний кеш банлисту (завантажується один раз)
_BANLIST_CACHE: Optional[Dict[str, Set[str]]] = None


def get_banlist() -> Dict[str, Set[str]]:
    """Отримати банліст (з кешуванням)."""
    global _BANLIST_CACHE
    if _BANLIST_CACHE is None:
        _BANLIST_CACHE = _load_banlist_from_file()
    return _BANLIST_CACHE


def reload_banlist() -> Dict[str, Set[str]]:
    """Перезавантажити банліст (скидає кеш)."""
    global _BANLIST_CACHE
    _BANLIST_CACHE = _load_banlist_from_file()
    return _BANLIST_CACHE


# ============================================================================
# ENUMS — Дозволені значення згідно GEN1.txt / VAL_GEN1.txt
# ============================================================================

class Category(str, Enum):
    """Категорії контенту з GEN1.txt v8.0.0."""
    GRAND_STRUCTURES = "GRAND_STRUCTURES"
    VEHICLES = "VEHICLES"
    ENTERTAINMENT = "ENTERTAINMENT"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    RESIDENTIAL = "RESIDENTIAL"
    NATURE_FORMATIONS = "NATURE_FORMATIONS"
    # Legacy categories (backwards compatibility)
    LUXURY_LISTINGS = "LUXURY_LISTINGS"
    TRANSIT = "TRANSIT"
    LANDMARKS = "LANDMARKS"
    COMMERCIAL = "COMMERCIAL"
    NEIGHBORHOODS = "NEIGHBORHOODS"
    NATURE = "NATURE"
    FREESTYLE = "FREESTYLE"
    # Gemini creative variations
    INDUSTRIAL = "INDUSTRIAL"
    MILITARY = "MILITARY"
    SPECIALIZED = "SPECIALIZED"
    HOSPITALITY = "HOSPITALITY"


class HookType(str, Enum):
    """Типи хуків з GEN1.txt v8.0.0 HOOK MATRIX."""
    THE_IMPOSSIBLE = "THE_IMPOSSIBLE"
    THE_ABSURD_LOGIC = "THE_ABSURD_LOGIC"
    THE_SCALE_SHOCK = "THE_SCALE_SHOCK"
    THE_SENSORY_ATTACK = "THE_SENSORY_ATTACK"
    THE_WHISPER = "THE_WHISPER"
    THE_SOUND_FIRST = "THE_SOUND_FIRST"
    THE_TEXTURE_ZOOM = "THE_TEXTURE_ZOOM"


class PsychologicalTrigger(str, Enum):
    """Психологічні тригери з GEN1.txt v8.0.0."""
    DISBELIEF = "DISBELIEF"
    PATTERN_BREAK = "PATTERN_BREAK"
    AWE = "AWE"
    SENSORY = "SENSORY"
    CONTRAST_HOOK = "CONTRAST_HOOK"
    AUDIO_PRIME = "AUDIO_PRIME"
    CURIOSITY_GAP = "CURIOSITY_GAP"


class LightingPreset(str, Enum):
    """Пресети освітлення з GEN1 v6 LIGHTING SYSTEM."""
    MORNING_GOLDEN = "MORNING_GOLDEN"
    SUNSET_DRAMATIC = "SUNSET_DRAMATIC"
    BLUE_HOUR = "BLUE_HOUR"
    NIGHT_NEON = "NIGHT_NEON"
    TWILIGHT_PURPLE = "TWILIGHT_PURPLE"
    OVERCAST_SOFT = "OVERCAST_SOFT"
    CANDLELIT_WARM = "CANDLELIT_WARM"
    MOONLIT_SILVER = "MOONLIT_SILVER"
    # Legacy presets kept for backwards compat
    AFTERNOON_WARM = "AFTERNOON_WARM"
    MIDDAY_BRIGHT = "MIDDAY_BRIGHT"
    HARSH_INDUSTRIAL = "HARSH_INDUSTRIAL"
    FOGGY_DIFFUSED = "FOGGY_DIFFUSED"
    STORMY_DRAMATIC = "STORMY_DRAMATIC"
    FLUORESCENT_COLD = "FLUORESCENT_COLD"


class AtmosphereMode(str, Enum):
    """Режими атмосфери з GEN1.txt v8.0.0."""
    CINEMATIC = "CINEMATIC"
    VIBRANT = "VIBRANT"
    PLAYFUL = "PLAYFUL"
    GOLDEN_WARM = "GOLDEN_WARM"
    TROPICAL = "TROPICAL"
    ETHEREAL = "ETHEREAL"
    NOIR = "NOIR"
    HAUNTED = "HAUNTED"


class SonicHookType(str, Enum):
    """Типи sonic hook з GEN1.txt v8.0.0 AUDIO SYSTEM."""
    THE_BOOM = "THE_BOOM"
    THE_SIZZLE = "THE_SIZZLE"
    THE_WHOOSH = "THE_WHOOSH"
    THE_CHIME = "THE_CHIME"
    THE_DROP = "THE_DROP"
    THE_CRUNCH = "THE_CRUNCH"
    THE_GLITCH = "THE_GLITCH"
    THE_SILENCE = "THE_SILENCE"


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
    """Narrative purpose сцени з GEN1 v6 SCENE STRUCTURE."""
    ESTABLISHING = "ESTABLISHING"
    EXTERIOR_ANGLE = "EXTERIOR_ANGLE"
    AERIAL = "AERIAL"
    INTERIOR = "INTERIOR"
    DETAIL = "DETAIL"
    FEATURE = "FEATURE"
    LOOP_CLOSE = "LOOP_CLOSE"
    STRUCTURAL_DETAIL = "STRUCTURAL_DETAIL"
    THEMATIC_INTERIOR = "THEMATIC_INTERIOR"
    CONTEXTUAL_ENVIRONMENT = "CONTEXTUAL_ENVIRONMENT"
    DYNAMIC_ACTION = "DYNAMIC_ACTION"
    FEATURE_HIGHLIGHT = "FEATURE_HIGHLIGHT"
    AERIAL_WOW = "AERIAL_WOW"
    AERIAL_REVEAL = "AERIAL_REVEAL"


class ReferenceHint(str, Enum):
    """Reference hint з GEN1.txt v8.0.0."""
    PRIMARY = "PRIMARY"
    REQUIRES_REF = "REQUIRES_REF"
    INDEPENDENT = "INDEPENDENT"
    LOOP_CLOSE = "LOOP_CLOSE"


class EnergyLevel(str, Enum):
    """Рівні енергії сцени з GEN1.txt."""
    EXPLOSIVE = "EXPLOSIVE"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


# ============================================================================
# CONSTANTS — Правила валідації з VAL_GEN1.txt + ban_list.txt
# ============================================================================

# Заборонені перші слова для hook.first_words — ДИНАМІЧНО з ban_list.txt
# Fallback значення якщо банліст не завантажено
BANNED_FIRST_WORDS_FALLBACK: Set[str] = {"welcome", "so", "today", "hello", "hi", "hey", "this", "let", "here"}

def get_banned_first_words() -> Set[str]:
    """Отримати заборонені перші слова з банлисту."""
    banlist = get_banlist()
    words = banlist.get("first_words", set())
    return words if words else BANNED_FIRST_WORDS_FALLBACK

def get_banned_first_phrases() -> Set[str]:
    """Отримати заборонені початкові фрази з банлисту."""
    return get_banlist().get("first_phrases", set())

def get_ai_markers() -> Set[str]:
    """Отримати заборонені AI маркери з банлисту."""
    return get_banlist().get("ai_markers", set())

def get_fillers() -> Set[str]:
    """Отримати заборонені філери з банлисту."""
    return get_banlist().get("fillers", set())

def get_overused_adjectives() -> Set[str]:
    """Отримати перевикористані прикметники з банлисту."""
    return get_banlist().get("overused_adjectives", set())

def get_generic_luxury() -> Set[str]:
    """Отримати generic luxury слова з банлисту."""
    return get_banlist().get("generic_luxury", set())

# Legacy alias for backwards compatibility
BANNED_FIRST_WORDS: Set[str] = BANNED_FIRST_WORDS_FALLBACK

# Дозволені camera movements
VALID_CAMERA_MOVEMENTS: Set[str] = {
    "APPROACH", "RETREAT", "ORBIT", "RISE", "DESCEND",
    "RUSH", "REVEAL", "TRACK", "PUNCH", "PUSH",
}

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

# Scene count range
MIN_SCENES: int = 6
MAX_SCENES: int = 10
MIN_YOUTUBE_DESCRIPTION_LENGTH: int = 100
MAX_YOUTUBE_TITLE_LENGTH: int = 60
MIN_VIRAL_SCORE: float = 0.7
MIN_MOTION_ELEMENTS: int = 2  # GEN1.txt: "2+ items — first = start, second = change"
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

        # Визначаємо результат (strict_mode: warnings also block)
        passed = len(self._errors) == 0
        if self.strict_mode and self._warnings:
            passed = False

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

        # 9b. Warning Line (AERIAL scene signature)
        self._validate_warning_line()

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
        valid_versions = ("3.0", "3.1", "6.0.0", "6.0.1", "8.0.0")
        if version and version not in valid_versions:
            self._add_warning(
                "metadata.version",
                f"Expected one of {valid_versions}, got '{version}'",
                suggestion="Update to a supported version"
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
        if scene_count is not None and (scene_count < MIN_SCENES or scene_count > MAX_SCENES):
            self._add_error(
                "metadata.scene_count",
                f"Must be {MIN_SCENES}-{MAX_SCENES}, got {scene_count}",
                code="INVALID_SCENE_COUNT"
            )

    def _validate_property(self) -> None:
        """Валідація property об'єкту."""
        prop = self._get_field("property")
        if prop is None:
            return

        required = ["name", "location", "tagline"]
        for field_name in required:
            self._require_non_empty(prop, field_name, f"property.{field_name}")
        # price is optional (not all concepts have a price)

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

        # psychological_trigger — accept any non-empty value (GEN1 prompt says "Create your OWN variations")
        trigger = self._get_nested(hook, "psychological_trigger")
        if not trigger:
            self._add_error("hook.psychological_trigger", "Required field is missing or empty")

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

        Правила (з ban_list.txt):
        1. Не може починатися із заборонених слів (welcome, hello, so, today, etc.)
        2. Не може починатися із заборонених фраз (in this video, did you know, etc.)
        3. Повинен містити emotion tag як [excited], [whispers], etc.
        """
        # Видаляємо всі теги щоб отримати чистий текст
        clean_text = re.sub(r'\[.*?\]', '', first_words).strip()
        clean_text_lower = clean_text.lower()

        # Отримуємо актуальні банлисти
        banned_words = get_banned_first_words()
        banned_phrases = get_banned_first_phrases()

        if clean_text:
            # Перевіряємо перше слово
            actual_first_word = clean_text.split()[0].lower()
            if actual_first_word in banned_words:
                self._add_warning(
                    "hook.first_words",
                    f"Starts with '{actual_first_word}' (weak first word)",
                    suggestion="Use IMPACT words: numbers, sensory words, warnings, food nouns"
                )

            # Перевіряємо заборонені фрази
            for phrase in banned_phrases:
                if clean_text_lower.startswith(phrase):
                    self._add_warning(
                        "hook.first_words",
                        f"Starts with generic phrase '{phrase}'",
                        suggestion="Avoid generic YouTube opener phrases"
                    )
                    break

        # Перевіряємо наявність emotion tag
        # GEN1 v6: emotion tag is required in complete_hook_vo (full voiceover text).
        # first_words is the impact opener — tag there is optional.
        hook = self._get_field("hook")
        complete_vo = self._get_nested(hook, "complete_hook_vo", "") if hook else ""
        has_emotion_in_first = any(tag in first_words for tag in ELEVENLABS_EMOTION_TAGS)
        has_emotion_in_vo = any(tag in complete_vo for tag in ELEVENLABS_EMOTION_TAGS)

        if not has_emotion_in_first and not has_emotion_in_vo:
            # No emotion tag anywhere — this is an error
            self._add_error(
                "hook.complete_hook_vo",
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

            # === BANLIST CHECKS ===
            script_lower = script.lower()

            # Перевірка на AI маркери (КРИТИЧНО — YouTube детектить)
            ai_markers = get_ai_markers()
            found_ai_markers = [m for m in ai_markers if re.search(r'\b' + re.escape(m) + r'\b', script_lower)]
            if found_ai_markers:
                self._add_error(
                    "voiceover.full_script",
                    f"Contains AI markers: {', '.join(found_ai_markers[:5])}{'...' if len(found_ai_markers) > 5 else ''}",
                    code="AI_MARKERS_DETECTED",
                    suggestion="Remove AI-sounding words like 'delve', 'nestled', 'tapestry', etc."
                )

            # Перевірка на перевикористані прикметники
            overused = get_overused_adjectives()
            found_overused = [w for w in overused if w in script_lower]
            if found_overused:
                self._add_warning(
                    "voiceover.full_script",
                    f"Contains overused adjectives: {', '.join(found_overused[:3])}",
                    suggestion="Use more specific, unique descriptors"
                )

            # Перевірка на generic luxury слова
            generic = get_generic_luxury()
            found_generic = [w for w in generic if w in script_lower]
            if len(found_generic) >= 2:
                self._add_warning(
                    "voiceover.full_script",
                    f"Contains multiple generic luxury words: {', '.join(found_generic[:3])}",
                    suggestion="Be more specific and creative with descriptions"
                )

        # character
        self._require_non_empty(vo, "character", "voiceover.character")

        # voice_id
        self._require_non_empty(vo, "voice_id", "voiceover.voice_id")

    def _validate_warning_line(self) -> None:
        """Validate warning_line — catchy warning for AERIAL (N-1) scene."""
        warning = self._data.get("warning_line")

        # Check if Scene N-1 is actually AERIAL
        scenes = self._data.get("scenes", [])
        penultimate_is_aerial = True  # assume true by default
        if len(scenes) >= 2:
            penultimate = scenes[-2]
            purpose = self._get_nested(penultimate, "narrative_purpose", "")
            penultimate_is_aerial = purpose in ("AERIAL", "AERIAL_WOW", "AERIAL_REVEAL")

        # Must exist and be a non-empty string
        if not warning or not isinstance(warning, str) or not warning.strip():
            if penultimate_is_aerial:
                self._add_error(
                    "warning_line",
                    "Missing or empty warning_line",
                    code="MISSING_WARNING_LINE",
                    suggestion="Add a 3-8 word catchy warning for the AERIAL scene"
                )
            else:
                self._add_warning(
                    "warning_line",
                    "Missing warning_line (Scene N-1 is not AERIAL, so warning is optional)",
                    suggestion="Consider adding a warning_line if Scene N-1 has a dramatic reveal"
                )
            return

        warning = warning.strip()
        # Strip ElevenLabs SSML-like tags before counting words (e.g. [excited], [whispers], [pause])
        warning_clean = re.sub(r'\[[\w\s]+\]', '', warning).strip()
        word_count = len(warning_clean.split()) if warning_clean else 0

        if word_count < 2 or word_count > 10:
            self._add_error(
                "warning_line",
                f"warning_line has {word_count} words (expected 2-10)",
                code="WARNING_LINE_LENGTH",
                suggestion="Keep warning_line punchy: 3-8 words ideal"
            )

        # Cross-check: warning_line should appear in voiceover.full_script
        vo = self._data.get("voiceover")
        if isinstance(vo, dict):
            full_script = vo.get("full_script", "")
            if isinstance(full_script, str) and warning.lower() not in full_script.lower():
                self._add_warning(
                    "warning_line",
                    f"warning_line '{warning}' not found in voiceover.full_script",
                    suggestion="The warning should appear in the AERIAL scene voiceover"
                )

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
        """Валідація engagement об'єкту (Easter Egg / Replay Hooks)."""
        engagement = self._get_field("engagement")
        if engagement is None:
            return

        # easter_egg — optional in v8.0.0 (replaced by replay_hooks)
        egg = self._get_nested(engagement, "easter_egg", {})
        if not egg:
            # v8.0.0: easter_egg no longer required, check for replay_hooks instead
            replay_hooks = self._get_nested(engagement, "replay_hooks", [])
            if not replay_hooks:
                self._add_warning(
                    "engagement",
                    "Neither easter_egg nor replay_hooks found — engagement may be weak",
                    suggestion="Add replay_hooks (v8.0.0+) or easter_egg for viewer engagement"
                )
        else:
            # GEN1 v6: AUDIO_ONLY easter eggs don't require visual fields
            egg_format = self._get_nested(egg, "format", "VISUAL")
            is_audio_only = (egg_format == "AUDIO_ONLY")

            if is_audio_only:
                # AUDIO_ONLY: requires audio_hint and comment_bait
                self._require_non_empty(egg, "audio_hint", "engagement.easter_egg.audio_hint")
                self._require_non_empty(egg, "comment_bait", "engagement.easter_egg.comment_bait")
            else:
                # VISUAL: requires object, scene_number, placement, visibility, validation_check
                self._require_non_empty(egg, "object", "engagement.easter_egg.object")

                # scene_number (must be 2 to N-1)
                scene_num = self._get_nested(egg, "scene_number")
                scenes_list = self._data.get("scenes", [])
                total_scenes = len(scenes_list) if scenes_list else self._data.get("metadata", {}).get("scene_count", 8)
                if scene_num is None:
                    self._add_error(
                        "engagement.easter_egg.scene_number",
                        "Required field is missing",
                        code="MISSING_SCENE_NUMBER"
                    )
                elif not (2 <= scene_num <= total_scenes - 1):
                    self._add_error(
                        "engagement.easter_egg.scene_number",
                        f"Must be 2-{total_scenes - 1} (not in hook or loop scene), got {scene_num}",
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

        # hashtags — optional in v6 (may be embedded in youtube.description instead)
        # v8.2.0: hashtags increased from 3 to 6-8 for algorithm discovery
        hashtags = self._get_nested(engagement, "hashtags", [])
        if isinstance(hashtags, list) and hashtags and not (3 <= len(hashtags) <= 10):
            self._add_warning(
                "engagement.hashtags",
                f"Expected 3-10 items, got {len(hashtags)}",
                suggestion="Provide 6-8 hashtags for optimal discovery (min 3, max 10)"
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

            # Description hashtag validation (v8.3.0)
            if desc:
                hashtags_in_desc = re.findall(r'#[\w\-]+', desc.lower())
                if len(hashtags_in_desc) < 6:
                    self._add_warning(
                        "youtube.description",
                        f"Only {len(hashtags_in_desc)} hashtags — minimum 6 recommended",
                        suggestion="Add more discovery hashtags"
                    )
                if '#glazecity' in hashtags_in_desc:
                    self._add_error(
                        "youtube.description",
                        "Contains #glazecity — banned brand hashtag (0 search volume for <10k sub channel)",
                        code="BANNED_HASHTAG_GLAZECITY",
                        suggestion="Replace with #shorts or #dreamcore"
                    )

            # Validate description_variants for same hashtag rules
            desc_variants = self._data.get("youtube", {}).get("description_variants") if isinstance(self._data.get("youtube"), dict) else None
            if not desc_variants:
                desc_variants = self._data.get("metadata_variants", {})
                if isinstance(desc_variants, dict):
                    desc_variants = [v.get("description", "") for v in desc_variants.values() if isinstance(v, dict) and v.get("description")]
            if isinstance(desc_variants, list):
                for vi, variant_desc in enumerate(desc_variants):
                    if isinstance(variant_desc, str) and variant_desc:
                        variant_hashtags = re.findall(r'#[\w\-]+', variant_desc.lower())
                        if '#glazecity' in variant_hashtags:
                            self._add_error(
                                f"description_variant[{vi}]",
                                "Contains #glazecity — banned brand hashtag",
                                code="BANNED_HASHTAG_GLAZECITY",
                                suggestion="Replace with #shorts or #dreamcore"
                            )

            # pinned_comment
            # pinned_comment — optional in v6 (can be null)
            pinned = self._get_nested(youtube, "pinned_comment")
            if pinned is not None and not isinstance(pinned, str):
                self._add_warning(
                    "youtube.pinned_comment",
                    "Should be a string or null",
                    suggestion="Provide a string value or null"
                )

            # Pinned comment ↔ easter egg consistency (v8.3.0)
            if pinned and isinstance(pinned, str):
                engagement = self._data.get("engagement", {})
                egg = engagement.get("easter_egg") if isinstance(engagement, dict) else None

                is_audio_only = egg and isinstance(egg, dict) and egg.get("format") == "AUDIO_ONLY"
                has_real_egg = (
                    is_audio_only
                    or (
                        egg and isinstance(egg, dict)
                        and egg.get("object") and egg.get("object") != "none"
                        and egg.get("scene_number", 0) > 0
                    )
                )

                # Check if pinned references an object ("spotted the X", "find the X", etc.)
                reference_patterns = ["spot", "find", "hidden", "spotted", "hiding", "secret"]
                looks_like_egg_hunt = any(p in pinned.lower() for p in reference_patterns)

                if looks_like_egg_hunt and not has_real_egg:
                    self._add_error(
                        "youtube.pinned_comment",
                        "References easter egg hunt but no real easter egg exists (object='none' or scene_number=0)",
                        code="FAKE_EASTER_EGG_REFERENCE",
                        suggestion="Use generic CTA instead, or add a real easter egg to engagement.easter_egg"
                    )

            # tags (5-8 per-video, expanded from 3 in v8.3.0)
            tags = self._get_nested(youtube, "tags", [])
            if not isinstance(tags, list) or len(tags) < 3:
                self._add_error(
                    "youtube.tags",
                    "Must have at least 3 items (5-8 recommended)",
                    code="INSUFFICIENT_TAGS"
                )
            elif len(tags) < 5:
                self._add_warning(
                    "youtube.tags",
                    f"Only {len(tags)} tags — 5-8 recommended for better discovery",
                    suggestion="Add more specific tags"
                )

            # Banned tags check (v8.3.0)
            _BANNED_TAGS = {
                "glaze city", "ai art", "blender 3d", "midjourney", "kling",
                "yumestate", "edible architecture", "weirdcore", "visual asmr",
                "food art", "satisfying", "shorts",
            }
            if isinstance(tags, list):
                for tag in tags:
                    if isinstance(tag, str) and tag.lower().strip() in _BANNED_TAGS:
                        self._add_warning(
                            "youtube.tags",
                            f"Tag '{tag}' is banned or a channel default (merged at upload)",
                            suggestion="Replace with a video-specific search term"
                        )

        # ===== FLAT YOUTUBE FIELDS (backwards compatibility — now OPTIONAL) =====
        # GEN1 v6 only requires nested youtube object; flat fields are optional fallbacks

        yt_title = self._data.get("youtube_title")
        yt_desc = self._data.get("youtube_description")

        # If no nested youtube AND no flat fields, that's an error
        if not youtube:
            if not yt_title:
                self._add_error(
                    "youtube_title",
                    "Either youtube.title or youtube_title must exist",
                    code="MISSING_FLAT_TITLE"
                )
            if not yt_desc:
                self._add_error(
                    "youtube_description",
                    "Either youtube.description or youtube_description must exist",
                    code="MISSING_FLAT_DESC"
                )

        # Validate flat fields only if they are present
        # v8.2.0: hashtags increased from 3 to 6-8 for algorithm discovery
        yt_hashtags = self._data.get("youtube_hashtags", [])
        if yt_hashtags and isinstance(yt_hashtags, list) and (len(yt_hashtags) < 3 or len(yt_hashtags) > 10):
            self._add_warning(
                "youtube_hashtags",
                f"Expected 3-10 items, got {len(yt_hashtags)}",
                suggestion="Provide 6-8 hashtags for optimal discovery (min 3, max 10)"
            )

        yt_tags = self._data.get("youtube_tags", [])
        if yt_tags and isinstance(yt_tags, list) and len(yt_tags) < 3:
            self._add_warning(
                "youtube_tags",
                f"Expected at least 3 items, got {len(yt_tags)}",
                suggestion="Provide at least 3 tags"
            )

        # Validate title_variants if present
        if youtube:
            title_variants = youtube.get("title_variants")
            if title_variants is not None and not isinstance(title_variants, list):
                self._add_warning(
                    "youtube.title_variants",
                    "Must be an array of strings",
                    suggestion="Provide a list of title variants"
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

        GEN1 v5: Uses numeric scores (overall_score, hook_strength, etc.)
        GEN1 v6: Uses verdict strings (hook_verdict, retention_verdict, share_verdict)
        Both formats are accepted.
        """
        viral = self._get_field("viral_assessment")
        if viral is None:
            return

        # Detect format: v6 uses verdict strings, v5 uses numeric scores
        has_verdicts = any(
            self._get_nested(viral, f) is not None
            for f in ("hook_verdict", "retention_verdict", "share_verdict")
        )
        has_scores = self._get_nested(viral, "overall_score") is not None

        if has_verdicts:
            # GEN1 v6 format: validate verdict strings
            verdict_fields = ["hook_verdict", "retention_verdict", "share_verdict"]
            for field_name in verdict_fields:
                verdict = self._get_nested(viral, field_name)
                if verdict is not None and not isinstance(verdict, str):
                    self._add_warning(
                        f"viral_assessment.{field_name}",
                        "Should be a string",
                        suggestion="Provide a verdict string"
                    )
        elif has_scores:
            # GEN1 v5 format: validate numeric scores
            overall = self._get_nested(viral, "overall_score")
            if isinstance(overall, (int, float)) and overall < MIN_VIRAL_SCORE:
                self._add_error(
                    "viral_assessment.overall_score",
                    f"Must be >= {MIN_VIRAL_SCORE}, got {overall}. AUTOMATIC FAIL.",
                    code="LOW_VIRAL_SCORE",
                    suggestion="Regenerate content with stronger hook/concept"
                )

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
        else:
            # Neither format present
            self._add_error(
                "viral_assessment",
                "Must contain either verdict strings (v6) or numeric scores (v5)",
                code="MISSING_VIRAL_DATA"
            )

        # v8.3.0 verdict fields (optional — validate type if present)
        for v83_field in ("mute_test_verdict", "categorization_verdict", "niche_alignment_verdict"):
            v83_val = self._get_nested(viral, v83_field)
            if v83_val is not None and not isinstance(v83_val, str):
                self._add_warning(
                    f"viral_assessment.{v83_field}",
                    "Should be a string",
                    suggestion="Provide a verdict string"
                )

        # strength_points (at least 1) — common to both formats
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
        Перевіряє 6-10 сцен + спеціальні правила для Scene 1 і last scene.
        """
        scenes = self._data.get("scenes")

        if not isinstance(scenes, list):
            self._add_error(
                "scenes",
                "Must be an array",
                code="INVALID_SCENES_TYPE"
            )
            return

        if len(scenes) < MIN_SCENES or len(scenes) > MAX_SCENES:
            self._add_error(
                "scenes",
                f"Must have {MIN_SCENES}-{MAX_SCENES} items, got {len(scenes)}",
                code="INVALID_SCENE_COUNT"
            )
            return

        total_scenes = len(scenes)

        # Cross-validate metadata.scene_count vs actual scenes
        metadata = self._data.get("metadata")
        if isinstance(metadata, dict):
            declared_count = metadata.get("scene_count")
            if declared_count is not None and declared_count != total_scenes:
                self._add_warning(
                    "metadata.scene_count",
                    f"metadata.scene_count={declared_count} but actual scenes={total_scenes}",
                    suggestion="Ensure metadata.scene_count matches the number of scenes in the array"
                )

        # Check for duplicate scene_numbers upfront
        seen_scene_nums: set = set()
        for i, scene in enumerate(scenes):
            sn = scene.get("scene_number")
            if sn is not None:
                if sn in seen_scene_nums:
                    self._add_error(
                        f"scenes[{i}].scene_number",
                        f"Duplicate scene_number {sn}",
                        code="DUPLICATE_SCENE_NUMBER",
                        suggestion="Each scene must have a unique scene_number"
                    )
                seen_scene_nums.add(sn)

        # Зберігаємо Scene 1 movement для перевірки loop
        scene1_movement: str = ""
        low_energy_count: int = 0

        for i, scene in enumerate(scenes):
            scene_num = scene.get("scene_number", i + 1)
            prefix = f"scenes[{i}]"

            # scene_number validation — must be sequential
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
                if scene_num <= 3:
                    self._add_error(
                        f"{prefix}.energy_level",
                        f"Scene {scene_num} cannot have LOW energy — Scenes 1-3 must be HIGH or MEDIUM",
                        code="FORBIDDEN_EARLY_LOW_ENERGY"
                    )

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

                # motion_elements: error if <2, warning if 2 for HIGH/EXPLOSIVE
                motion = self._get_nested(visual, "motion_elements", [])
                motion_count = len(motion) if isinstance(motion, list) else 0
                if motion_count < MIN_MOTION_ELEMENTS:
                    self._add_error(
                        f"{prefix}.visual_concept.motion_elements",
                        f"Must have at least {MIN_MOTION_ELEMENTS} items, got {motion_count}",
                        code="INSUFFICIENT_MOTION"
                    )
                elif motion_count == 2 and energy in ("HIGH", "EXPLOSIVE"):
                    self._add_warning(
                        f"{prefix}.visual_concept.motion_elements",
                        f"{energy} scene has only 2 motion_elements — 3+ recommended for better dynamics",
                        suggestion="Add a third motion element for richer video movement"
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

                    # Validate movement against valid list
                    if movement_upper not in VALID_CAMERA_MOVEMENTS:
                        self._add_warning(
                            f"{prefix}.camera_intent.movement",
                            f"Non-standard movement '{movement_upper}'",
                            suggestion=f"Standard: {', '.join(sorted(VALID_CAMERA_MOVEMENTS))}"
                        )

                # Зберігаємо Scene 1 movement
                if scene_num == 1:
                    scene1_movement = movement

            # VO text (v8.0.0 uses narrator_script / voiceover_segment, legacy used broker_script)
            if scene_num <= 4:
                vo_text = (
                    self._get_nested(scene, "voiceover_segment", "")
                    or self._get_nested(scene, "narrator_script", "")
                    or self._get_nested(scene, "broker_script", "")
                )
                if not vo_text:
                    # ASMR scenes (typically scene 4) may have empty VO intentionally
                    purpose = self._get_nested(scene, "narrative_purpose", "")
                    if purpose != "STRUCTURAL_DETAIL":
                        self._add_warning(
                            f"{prefix}.voiceover_segment",
                            "No VO text for early scene (1-4) — may reduce retention",
                            suggestion="Add voiceover to early scenes for better viewer retention"
                        )
                else:
                    # Check for AI markers
                    vo_lower = vo_text.lower()
                    ai_markers = get_ai_markers()
                    found_ai = [m for m in ai_markers if m in vo_lower]
                    if found_ai:
                        self._add_error(
                            f"{prefix}.voiceover_segment",
                            f"Contains AI markers: {', '.join(found_ai[:3])}",
                            code="AI_MARKERS_IN_SCENE",
                            suggestion="Remove AI-sounding words"
                        )

            # voiceover_segment - check for AI markers (skip scenes 1-4, already checked above)
            if scene_num > 4:
                vo_segment = self._get_nested(scene, "voiceover_segment", "")
                if vo_segment:
                    vo_lower = vo_segment.lower()
                    ai_markers = get_ai_markers()
                    found_ai = [m for m in ai_markers if m in vo_lower]
                    if found_ai:
                        self._add_error(
                            f"{prefix}.voiceover_segment",
                            f"Contains AI markers: {', '.join(found_ai[:3])}",
                            code="AI_MARKERS_IN_SCENE",
                            suggestion="Remove AI-sounding words"
                        )

            # ===== ON-SCREEN TEXT VALIDATION (v8.3.0) =====
            on_screen = self._get_nested(scene, "on_screen_text", "")
            if scene_num == total_scenes:
                # LOOP_CLOSE — empty is acceptable (warning only)
                pass
            elif not on_screen or not on_screen.strip():
                self._add_error(
                    f"{prefix}.on_screen_text",
                    "REQUIRED — mute viewers need headline text",
                    code="MISSING_ON_SCREEN_TEXT"
                )
            else:
                words = on_screen.strip().split()
                if len(words) > 6:
                    self._add_warning(
                        f"{prefix}.on_screen_text",
                        f"Too long ({len(words)} words) — max 6 recommended for Shorts",
                        suggestion="Shorten to 3-6 word headline"
                    )
                # Scene 1: must contain food name (critical for mute Shorts viewers)
                if scene_num == 1:
                    food = self._get_food_name()
                    if food and food.lower() not in on_screen.lower():
                        self._add_error(
                            f"{prefix}.on_screen_text",
                            f"Scene 1 MUST contain food name '{food}' for mute recognition — "
                            f"Shorts viewers see text before audio loads",
                            code="SCENE1_MISSING_FOOD_NAME"
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

            # ===== LAST SCENE SPECIFIC RULES (LOOP_CLOSE) =====
            if scene_num == total_scenes:
                if purpose != "LOOP_CLOSE":
                    self._add_error(
                        f"{prefix}.narrative_purpose",
                        f"Last scene (Scene {total_scenes}) must be 'LOOP_CLOSE', got '{purpose}'",
                        code="INVALID_LAST_SCENE_PURPOSE"
                    )

                # Перевірка complementary movement
                if camera and scene1_movement:
                    last_scene_movement = self._get_nested(camera, "movement", "")
                    if last_scene_movement and scene1_movement.upper() == last_scene_movement.upper():
                        self._add_warning(
                            f"{prefix}.camera_intent.movement",
                            f"Same as Scene 1 ('{last_scene_movement}')",
                            suggestion="Use COMPLEMENTARY movement (e.g., RISE, ORBIT) for better loop"
                        )

            # ===== PENULTIMATE SCENE RULES (AERIAL) =====
            if scene_num == total_scenes - 1:
                if purpose not in ("AERIAL", "AERIAL_WOW", "AERIAL_REVEAL"):
                    self._add_error(
                        f"{prefix}.narrative_purpose",
                        f"Scene {total_scenes - 1} MUST be AERIAL/AERIAL_WOW/AERIAL_REVEAL, got '{purpose}'",
                        code="INVALID_PENULTIMATE_PURPOSE"
                    )

                # Cross-validate: warning_line should appear in Scene N-1 voiceover_segment
                warning = self._data.get("warning_line")
                if warning and isinstance(warning, str):
                    vo_segment = self._get_nested(scene, "voiceover_segment", "")
                    if isinstance(vo_segment, str) and warning.strip().lower() not in vo_segment.lower():
                        self._add_warning(
                            f"{prefix}.voiceover_segment",
                            f"warning_line '{warning.strip()}' not found in Scene {scene_num} voiceover_segment",
                            suggestion="AERIAL scene should deliver the warning_line"
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

    def _get_food_name(self) -> Optional[str]:
        """Extract primary food name from food_identity.primary_food."""
        food_identity = self._data.get("food_identity")
        if isinstance(food_identity, dict):
            primary = food_identity.get("primary_food", "")
            if isinstance(primary, str) and primary.strip():
                return primary.strip()
        return None

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

    # Enum fields that should only warn (not error) when Gemini uses creative values
    _SOFT_ENUM_FIELDS = {"metadata.concept.category", "lighting_master.preset", "atmosphere_mode", "audio.sonic_hook.type"}

    def _validate_enum_field(
        self,
        value: Any,
        enum_class: type,
        field_path: str
    ) -> bool:
        """
        Валідація enum значення.
        Soft enums (category, lighting, atmosphere) produce warnings, not errors.

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
            if field_path in self._SOFT_ENUM_FIELDS:
                # Gemini is creative — accept non-standard values with warning
                self._add_warning(
                    field_path,
                    f"Non-standard value '{value}' (accepted)",
                    suggestion=f"Standard values: {', '.join(valid_values[:5])}..."
                )
                return True  # Accept it
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
        last_scene_movement = ""
        last_scene_num = len(scenes)
        for scene in scenes:
            sn = scene.get("scene_number", 0)
            if sn == 1:
                scene1_movement = scene.get("camera_intent", {}).get("movement", "")
            if sn == last_scene_num:
                last_scene_movement = scene.get("camera_intent", {}).get("movement", "")

        return {
            "atmosphere_mode": self._data.get("atmosphere_mode", "CINEMATIC"),
            "lighting_preset": lighting.get("preset", ""),
            "category": concept.get("category", ""),
            "food_material": concept.get("food_material", ""),
            "scene_count": last_scene_num,
            "loop_strategy": f"COMPLEMENTARY (Scene 1: {scene1_movement}, Scene {last_scene_num}: {last_scene_movement})"
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

    # Banlist functions
    "get_banlist",
    "reload_banlist",
    "get_banned_first_words",
    "get_ai_markers",
    "get_fillers",
]
