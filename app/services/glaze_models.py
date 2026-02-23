"""
GLAZE CITY Data Models (JSON Format) v7.4

Pydantic моделі для парсингу JSON виводу GLAZE CITY VIRAL ENGINE.
Підтримує повний pipeline: GEN1 → GEN2 → GEN3a → GEN3b

IMPORTANT: Ці моделі відповідають формату виводу з
PROTECTED файлів: config/GEN1.txt, GEN2.txt, GEN3a.txt, GEN3b.txt
"""

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import List, Optional, Dict, Any, Union, Literal
from pathlib import Path
from datetime import datetime
from enum import Enum


# ============================================================================
# ENUMS - Режими та стилі v7.4
# ============================================================================

class AtmosphereMode(str, Enum):
    """Режим атмосфери відео (synced with gen1_validator.AtmosphereMode)."""
    CINEMATIC = "CINEMATIC"
    VIBRANT = "VIBRANT"
    PLAYFUL = "PLAYFUL"
    GOLDEN_WARM = "GOLDEN_WARM"
    TROPICAL = "TROPICAL"
    ETHEREAL = "ETHEREAL"
    NOIR = "NOIR"
    HAUNTED = "HAUNTED"


class HookStyleType(str, Enum):
    """Типи стилів хуку."""
    CLASSIC = "CLASSIC"
    IMPACT = "IMPACT"
    GLITCH = "GLITCH"
    ELEGANT = "ELEGANT"
    DRAMATIC = "DRAMATIC"


class VisualType(str, Enum):
    """Типи візуального контенту для класифікації."""
    MACRO_DETAIL = "MACRO_DETAIL"
    EPIC_WIDE = "EPIC_WIDE"
    AERIAL = "AERIAL"
    INTERIOR = "INTERIOR"
    ACTION = "ACTION"
    REVEAL = "REVEAL"
    PORTRAIT = "PORTRAIT"
    TRANSITION = "TRANSITION"


class EffectPalette(str, Enum):
    """Палітри ефектів."""
    SUBTLE = "SUBTLE"
    DRAMATIC = "DRAMATIC"
    SMOOTH = "SMOOTH"
    WARM = "WARM"
    ENERGETIC = "ENERGETIC"


class SubtitleStyle(str, Enum):
    """Стилі субтитрів."""
    WHISPER = "WHISPER"
    NORMAL = "NORMAL"
    EXCITED = "EXCITED"
    DRAMATIC = "DRAMATIC"
    SARCASTIC = "SARCASTIC"


# ============================================================================
# ARCHITECTURAL IDENTITY - Стиль архітектури v7.4
# ============================================================================

class ArchitecturalIdentity(BaseModel):
    """Архітектурна ідентичність нерухомості - ALL FIELDS REQUIRED."""
    style_code: str = Field(..., description="Код стилю - REQUIRED")
    style_description: str = Field(..., description="Опис стилю - REQUIRED")
    stories: int = Field(..., description="Кількість поверхів - REQUIRED")
    distinctive_features: List[str] = Field(..., description="Відмінні риси - REQUIRED")
    silhouette_description: str = Field(..., description="Опис силуету - REQUIRED")
    interior_style: str = Field(..., description="Стиль інтер'єру - REQUIRED")

    @model_validator(mode='before')
    @classmethod
    def validate_required_fields(cls, data: Any) -> Any:
        """Validate that critical fields are not empty."""
        if isinstance(data, dict):
            if not data.get('style_code'):
                raise ValueError("architectural_identity.style_code is required")
            if not data.get('style_description'):
                raise ValueError("architectural_identity.style_description is required")
        return data


# ============================================================================
# FOOD DNA - Маппинг їжі на архітектурні елементи v7.4
# ============================================================================

class FoodDNA(BaseModel):
    """Food DNA - маппинг їжі на архітектурні елементи."""
    walls_become: str = Field(..., description="Що стає стінами - REQUIRED")
    roof_becomes: str = Field(..., description="Що стає дахом - REQUIRED")
    windows_become: str = Field(default="", description="Що стає вікнами")
    door_becomes: str = Field(default="", description="Що стає дверима")
    doors_become: str = Field(default="", description="Що стає дверима (alias)")
    floors_become: str = Field(default="", description="Що стає підлогою")
    columns_become: str = Field(default="", description="Що стає колонами")
    furniture_becomes: str = Field(default="", description="Що стає меблями")
    chimney_becomes: str = Field(default="", description="Що стає димоходом")
    stairs_become: str = Field(default="", description="Що стає сходами")
    fence_becomes: str = Field(default="", description="Що стає огорожею")
    landscaping_becomes: str = Field(default="", description="Що стає ландшафтом")

    @model_validator(mode='before')
    @classmethod
    def normalize_and_validate(cls, data: Any) -> Any:
        """Normalize field names and validate required fields."""
        if isinstance(data, dict):
            # Handle door_becomes vs doors_become
            if 'doors_become' in data and 'door_becomes' not in data:
                data['door_becomes'] = data.get('doors_become', '')
            # Validate required
            if not data.get('walls_become'):
                raise ValueError("food_dna.walls_become is required")
            if not data.get('roof_becomes'):
                raise ValueError("food_dna.roof_becomes is required")
        return data


class FoodIdentity(BaseModel):
    """Повна харчова ідентичність нерухомості - ALL FIELDS REQUIRED."""
    primary_food: str = Field(..., description="Основна їжа - REQUIRED")
    food_dna: FoodDNA = Field(..., description="Food DNA маппинг - REQUIRED")
    texture_keywords: List[str] = Field(..., description="Ключові слова текстури - REQUIRED")
    color_keywords: List[str] = Field(..., description="Ключові слова кольору - REQUIRED")
    atmosphere: str = Field(..., description="Атмосфера - REQUIRED")

    @model_validator(mode='before')
    @classmethod
    def validate_required_fields(cls, data: Any) -> Any:
        """Validate that critical fields are not empty."""
        if isinstance(data, dict):
            if not data.get('primary_food'):
                raise ValueError("food_identity.primary_food is required")
            if not data.get('food_dna'):
                raise ValueError("food_identity.food_dna is required")
        return data


# ============================================================================
# LIGHTING MASTER - Освітлення v7.4
# ============================================================================

class LightingMaster(BaseModel):
    """Master налаштування освітлення - ALL FIELDS REQUIRED."""
    preset: str = Field(..., description="Пресет освітлення - REQUIRED")
    mood_reason: str = Field(..., description="Чому обрано цей настрій - REQUIRED")
    prompt_snippet: str = Field(..., description="Фрагмент промпту для освітлення - REQUIRED")

    @model_validator(mode='before')
    @classmethod
    def validate_required_fields(cls, data: Any) -> Any:
        """Validate that critical fields are not empty."""
        if isinstance(data, dict):
            if not data.get('preset'):
                raise ValueError("lighting_master.preset is required")
            if not data.get('prompt_snippet'):
                raise ValueError("lighting_master.prompt_snippet is required")
        return data


# ============================================================================
# FOREGROUND ELEMENT - Елемент переднього плану v7.4
# ============================================================================

class ForegroundElement(BaseModel):
    """Елемент переднього плану для Scene 1 - ALL FIELDS REQUIRED."""
    type: str = Field(..., description="Тип (STEAM, GLAZE_DRIP, FALLING_INGREDIENT, NONE) - REQUIRED")
    prompt_snippet: str = Field(..., description="Фрагмент промпту - REQUIRED")


# ============================================================================
# FIRST FRAME COMPOSITION - Композиція першого кадру v7.4
# ============================================================================

class FirstFrameComposition(BaseModel):
    """Композиція першого кадру для hook - ALL FIELDS REQUIRED."""
    hero_subject: str = Field(..., description="Головний об'єкт - REQUIRED")
    hero_position: str = Field(..., description="Позиція (upper_center, center_left, etc) - REQUIRED")
    foreground_element: str = Field(..., description="Елемент переднього плану - REQUIRED")
    background_depth: str = Field(..., description="Глибина фону - REQUIRED")
    lighting_direction: str = Field(..., description="Напрям освітлення - REQUIRED")
    hook_element: str = Field(..., description="Hook елемент - REQUIRED")
    safe_zone_compliance: bool = Field(..., description="Відповідність Safe Zone - REQUIRED")


# ============================================================================
# HOOK MATRIX - Матриця хуків v7.4
# ============================================================================

class HookStyleDefinition(BaseModel):
    """Визначення стилю хуку - ALL FIELDS REQUIRED."""
    duration: float = Field(..., description="Тривалість в секундах - REQUIRED")
    effects: List[Dict[str, Any]] = Field(..., description="Список ефектів - REQUIRED")
    sfx: str = Field(..., description="Звуковий ефект - REQUIRED")


class HookMatrix(BaseModel):
    """Матриця доступних стилів хуків - all fields have defaults."""
    selected_style: str = Field(default="CLASSIC", description="Обраний стиль")
    style_reason: str = Field(default="", description="Чому обрано цей стиль")
    avoid_styles: List[str] = Field(default_factory=list, description="Стилі яких уникати (для variety)")


# ============================================================================
# PROPERTY - Інформація про нерухомість
# ============================================================================

class FoodMaterial(BaseModel):
    """Харчові матеріали нерухомості - ALL FIELDS REQUIRED."""
    primary: str = Field(..., description="Основний матеріал - REQUIRED")
    secondary: List[str] = Field(..., description="Додаткові матеріали - REQUIRED")


class PropertySpecs(BaseModel):
    """Характеристики нерухомості - ALL FIELDS REQUIRED."""
    bedrooms: int = Field(..., description="Кількість спалень - REQUIRED")
    bathrooms: int = Field(..., description="Кількість ванних - REQUIRED")
    sqft: int = Field(..., description="Площа - REQUIRED")
    unique_feature: str = Field(..., description="Унікальна фіча - REQUIRED")


class PropertyBrief(BaseModel):
    """Інформація про нерухомість - only name is required."""
    name: str = Field(..., alias="name", description="Назва нерухомості - REQUIRED")
    location: str = Field(default="Glaze City", description="Район в Glaze City")
    price: str = Field(default="$0", description="Ціна як текст")
    price_numeric: Union[int, float] = Field(default=0, description="Ціна як число")
    food_material: Union[FoodMaterial, str] = Field(default="", description="Харчові матеріали")
    specs: Union[PropertySpecs, str] = Field(default="", description="Характеристики")

    model_config = ConfigDict(populate_by_name=True)


# ============================================================================
# HOOK - Стратегія хуку
# ============================================================================

class HookStrategy(BaseModel):
    """Стратегія хуку для залучення - only type is required."""
    type: str = Field(..., description="Тип хука (THE_IMPOSSIBLE, THE_ABSURD_LOGIC, etc) - REQUIRED")
    psychological_trigger: str = Field(default="", description="Психологічний тригер")
    first_frame_visual: str = Field(default="", description="Візуал першого кадру")
    first_words: str = Field(default="", description="Перші слова VO")
    complete_hook_vo: str = Field(default="", description="Повний hook voiceover")
    scroll_stop_element: str = Field(default="", description="Елемент що зупиняє скрол")
    opening_line: str = Field(default="", description="Початкова фраза (legacy)")
    visual_hook: str = Field(default="", description="Візуальний хук (legacy)")
    audio_hook: str = Field(default="", description="Аудіо хук (legacy)")
    scene_1_entry_type: str = Field(default="MACRO_ENTRY", description="MACRO_ENTRY | SCALE_SHOCK")
    body_trigger: Optional[str] = Field(default=None, description="SKIN | MOUTH | NOSE | EARS | STOMACH")

    @model_validator(mode='before')
    @classmethod
    def validate_required_fields(cls, data: Any) -> Any:
        """Validate hook has required content."""
        if isinstance(data, dict):
            if not data.get('type'):
                raise ValueError("hook.type is REQUIRED per GEN1 OUTPUT CONTRACT")
        return data


# ============================================================================
# PSYCHOLOGY - Психологічні тригери
# ============================================================================

class Psychology(BaseModel):
    """Психологічні тригери - triggers required."""
    triggers: List[str] = Field(..., description="Список тригерів - REQUIRED")
    reasoning: str = Field(default="", description="Обґрунтування")


# ============================================================================
# SHARE TRIGGER - Тригер для шерингу
# ============================================================================

class ShareTrigger(BaseModel):
    """Тригер для шерингу з GEN1."""
    text: str = Field(..., description="Текст для шерингу")
    placement: str = Field(default="description_end", description="Місце розміщення")


# ============================================================================
# EASTER EGG INTEGRATION - Інтеграція пасхалки з GEN2
# ============================================================================

class EasterEggIntegration(BaseModel):
    """Інтеграція Easter Egg в промпт з GEN2."""
    object: str = Field(default="", description="Об'єкт")
    placement_in_prompt: str = Field(default="", description="Позиція в промпті")
    visibility_check: str = Field(default="", description="Перевірка видимості")
    integrated_in_image_prompt: bool = Field(default=True, description="Чи інтегровано в промпт")


# ============================================================================
# EASTER EGG - Схований елемент
# ============================================================================

class EasterEgg(BaseModel):
    """Схований елемент для коментарів - object and scene_number required (unless AUDIO_ONLY)."""
    object: str = Field(default="", description="Об'єкт - REQUIRED for VISUAL format")
    scene_number: int = Field(default=0, description="Номер сцени (2 to N-1)")
    placement: str = Field(default="center", description="Розташування з координатами")
    visibility: str = Field(default="FINDABLE", description="FINDABLE або HIDDEN")
    comment_bait: str = Field(default="", description="Фраза для коментарів")
    validation_check: str = Field(default="", description="Опис для верифікації")
    safe_zone_position: str = Field(default="center-left", description="Позиція в Safe Zone (legacy)")
    visibility_score: float = Field(default=0.7, ge=0.0, le=1.0, description="Видимість 0.0-1.0 (legacy)")
    format: str = Field(default="VISUAL", description="VISUAL or AUDIO_ONLY")
    audio_hint: str = Field(default="", description="Audio hint for AUDIO_ONLY format")

    @model_validator(mode='before')
    @classmethod
    def validate_required_fields(cls, data: Any) -> Any:
        """Validate easter egg fields based on format (VISUAL or AUDIO_ONLY).

        When GEN1 v8.0.0 uses replay_hooks instead of easter_egg,
        the merge may pass empty object/scene_number — gracefully fallback.
        """
        if isinstance(data, dict):
            egg_format = (data.get('format') or 'VISUAL').upper()
            if egg_format == 'AUDIO_ONLY':
                data.setdefault('object', 'audio_easter_egg')
                data.setdefault('scene_number', 0)
                data.setdefault('placement', 'AUDIO_ONLY')
            else:
                # VISUAL: if object is empty, silently downgrade to placeholder
                if not data.get('object'):
                    data['object'] = 'none'
                    data.setdefault('scene_number', 0)
                    data.setdefault('placement', 'none')
                    data['format'] = 'NONE'
                else:
                    scene_num = data.get('scene_number', 0)
                    if not scene_num or scene_num < 2:
                        data['scene_number'] = max(scene_num or 0, 2)
        return data


# ============================================================================
# LOOP - Налаштування циклу
# ============================================================================

class LoopConfig(BaseModel):
    """Налаштування циклу відео - connection required, others have defaults."""
    last_line: str = Field(default="", description="Вихід останньої сцени (scene_n_exit)")
    first_line: str = Field(default="", description="Вхід першої сцени (scene_1_entry)")
    connection: str = Field(..., description="Техніка переходу (technique)")
    bridge_sfx: str = Field(default="", description="SFX для переходу між loop")


# ============================================================================
# GEN1 SCENE DATA - Дані сцени з GEN1 (збережені при merge)
# ============================================================================

class VisualConcept(BaseModel):
    """Visual concept from GEN1 - creative direction for the scene."""
    subject: str = Field(default="", description="Main subject of the scene")
    environment: str = Field(default="", description="Environment/setting")
    mood: str = Field(default="", description="Emotional quality")
    key_elements: List[str] = Field(default_factory=list, description="Key visual elements")
    lighting_note: str = Field(default="", description="Specific lighting for this scene")
    motion_elements: List[str] = Field(default_factory=list, description="What should move in the scene (from GEN1)")


class CameraIntent(BaseModel):
    """Camera intent from GEN1 - full camera direction."""
    movement: str = Field(default="APPROACH", description="APPROACH | RETREAT | ORBIT | etc.")
    combo: Optional[str] = Field(default=None, description="Movement combination (e.g., APPROACH + RISE)")
    framing: str = Field(default="Wide", description="Wide | Medium | Close | Extreme Close")
    special: Optional[str] = Field(default=None, description="Special technique (e.g., 'Low angle looking up')")


# ============================================================================
# GEN2 SCENE METADATA - Метадані сцени з GEN2
# ============================================================================

class SceneInheritance(BaseModel):
    """Наслідування від батьківської сцени (GEN2)."""
    parent_scene: int = Field(..., description="Номер батьківської сцени")
    inherited_elements: List[str] = Field(default_factory=list, description="Успадковані елементи")
    modified_elements: List[str] = Field(default_factory=list, description="Змінені елементи")


class PostProductionNotes(BaseModel):
    """Нотатки для постпродакшну (GEN2)."""
    speed_ramp: str = Field(default="None", description="Speed ramp")
    color_grade: str = Field(default="Match Scene 1", description="Корекція кольору")
    loop_match: str = Field(default="N/A", description="Відповідність циклу")


class FirstFrameCompositionGEN2(BaseModel):
    """Композиція першого кадру з GEN2 (більш детальна)."""
    hook_element: str = Field(default="", description="Hook елемент")
    entry_type: str = Field(default="MACRO_ENTRY", description="MACRO_ENTRY or SCALE_SHOCK")
    focal_point: str = Field(default="", description="Фокусна точка")
    foreground: str = Field(default="", description="Передній план")
    background: str = Field(default="", description="Задній план")
    scale_proof: str = Field(default="", description="Доказ масштабу")
    color_anchor: str = Field(default="", description="Кольоровий якір")
    temperature_mood: str = Field(default="", description="Warm/cold contrast description")
    body_trigger_visual: str = Field(default="", description="Body trigger emphasis for GEN3a")
    safe_zone: str = Field(default="", description="Safe zone")
    motion_visible: str = Field(default="", description="Видимий рух")
    scroll_stop: str = Field(default="", description="Scroll stop елемент")


class ScalesTechniques(BaseModel):
    """Техніки масштабу з GEN2."""
    camera_angle: str = Field(default="", description="Кут камери")
    atmospheric_depth: str = Field(default="", description="Атмосферна глибина")
    scale_indicators: str = Field(default="", description="Індикатори масштабу")


# ============================================================================
# GEN2 VISUAL SUMMARY - Загальний огляд візуалів
# ============================================================================

class LoopVerification(BaseModel):
    """Верифікація циклу з GEN2."""
    scene1_camera_movement: str = Field(default="", description="Рух камери Scene 1")
    sceneN_camera_movement: str = Field(default="", description="Рух камери last scene")
    movements_are_different: bool = Field(default=True, description="Рухи різні")
    sceneN_after_reverse: str = Field(default="", description="Last scene після реверсу")
    scene1_foreground: str = Field(default="", description="Передній план Scene 1")
    sceneN_foreground: str = Field(default="", description="Передній план last scene")
    foreground_match: bool = Field(default=True, description="Передній план співпадає")
    scene1_lighting: str = Field(default="", description="Освітлення Scene 1")
    sceneN_lighting: str = Field(default="", description="Освітлення last scene")
    lighting_match: bool = Field(default=True, description="Освітлення співпадає")
    same_reference_image: bool = Field(default=True, description="Той самий reference image")
    loop_ready: bool = Field(default=True, description="Готовий до циклу")

    @model_validator(mode='before')
    @classmethod
    def migrate_scene6_fields(cls, data: Any) -> Any:
        """Map old scene6_* field names to sceneN_* for backwards compat."""
        if isinstance(data, dict):
            mapping = {
                'scene6_camera_movement': 'sceneN_camera_movement',
                'scene6_after_reverse': 'sceneN_after_reverse',
                'scene6_foreground': 'sceneN_foreground',
                'scene6_lighting': 'sceneN_lighting',
            }
            for old_key, new_key in mapping.items():
                if old_key in data and new_key not in data:
                    data[new_key] = data.pop(old_key)
        return data


class VisualSummary(BaseModel):
    """Загальний огляд візуалів з GEN2."""
    total_scenes: int = Field(default=0, description="Кількість сцен (6-10), 0=auto from len(scenes)")
    gigantism_protocol: str = Field(default="APPLIED", description="Протокол гігантизму")
    reference_breakdown: Dict[str, int] = Field(default_factory=dict, description="Розбивка референсів")
    scale_techniques_used: List[str] = Field(default_factory=list, description="Використані техніки масштабу")
    lighting_continuity: str = Field(default="", description="Безперервність освітлення")
    foreground_scenes: List[int] = Field(default_factory=list, description="Сцени з переднім планом")
    motion_summary: str = Field(default="", description="Резюме руху")
    energy_pattern: str = Field(default="", description="Патерн енергії")
    motion_enforcement: str = Field(default="", description="Застосування руху")
    loop_verified: bool = Field(default=True, description="Цикл верифіковано")
    banned_words_checked: bool = Field(default=True, description="Заборонені слова перевірено")
    loop_verification: Optional[LoopVerification] = Field(default=None, description="Деталі верифікації циклу")


# ============================================================================
# SCENE - Дані сцени
# ============================================================================

class GlazeScene(BaseModel):
    """Повні дані однієї сцени - Fields with defaults can be populated later."""
    model_config = ConfigDict(extra='allow')

    scene_number: int = Field(..., description="Номер сцени - REQUIRED")
    scene_name: str = Field(default="", description="Назва сцени")
    timestamp: str = Field(default="0:00", description="Таймстемп (0:00 формат)")
    duration_seconds: float = Field(default=2.0, description="Тривалість в секундах")

    # Script & Text - with defaults for GEN2-only creation
    voiceover: str = Field(default="", description="Текст озвучки з маркерами")
    voiceover_segment: str = Field(default="", description="Сегмент VO (alias)")
    on_screen_text: str = Field(default="", description="Текст на екрані")
    narrative_purpose: str = Field(default="ESTABLISHING", description="ESTABLISHING/STORY/LOOP_CLOSE")
    energy_level: str = Field(default="HIGH", description="HIGH/MEDIUM/LOW/EXPLOSIVE")

    # Visual - with defaults
    visual_description: str = Field(default="", description="Опис візуалу (subject з visual_concept)")
    camera_movement: str = Field(default="PUSH", description="Рух камери (movement з camera_intent)")
    motion_elements: List[str] = Field(default_factory=list, description="3+ motion elements")

    # GEN1 full data (preserved during merge)
    broker_script: str = Field(default="", description="Broker script (short VO version)")
    visual_concept: Optional[VisualConcept] = Field(default=None, description="Full visual concept from GEN1")
    camera_intent: Optional[CameraIntent] = Field(default=None, description="Full camera intent from GEN1")

    # Audio - with defaults
    audio_sfx: str = Field(default="", description="Звукові ефекти")
    audio_moment: str = Field(default="", description="Ключовий аудіо момент")

    # AI Prompts - REQUIRED per GEN2 OUTPUT CONTRACT
    image_prompt: str = Field(..., description="Промпт Nano Banana Pro - REQUIRED")
    video_prompt: str = Field(..., description="Промпт Kling/Veo/Wan - REQUIRED")
    video_tool: str = Field(default="KLING", description="KLING/VEO/WAN")
    reference_type: str = Field(default="INDEPENDENT", description="PRIMARY | REQUIRES_REF | INDEPENDENT | LOOP_CLOSE")

    # Processing status (додаткові поля для автоматизації)
    image_path: Optional[Path] = Field(default=None, description="Шлях до зображення")
    video_path: Optional[Path] = Field(default=None, description="Шлях до відео")
    status: str = Field(default="PENDING", description="Статус обробки")

    # GEN2 tier system fields
    visual_tier: Optional[str] = Field(default=None, description="TIER_1_MONEY_SHOT | TIER_2_HIGH_APPETITE | TIER_3_BALANCED | TIER_4_ARCHITECTURE")
    motion_intensity: Optional[int] = Field(default=None, description="Motion intensity 1-10")

    # GEN1 sensory fields (preserved through pipeline)
    sensory_pressure: Optional[int] = Field(default=None, ge=1, le=10, description="Sensory pressure 1-10")
    money_shot: Optional[Dict[str, Any]] = Field(default=None, description="Money shot info {is_money_shot, still_image_description}")
    snap_moment: Optional[Dict[str, Any]] = Field(default=None, description="Snap moment timing envelope for money_shot scenes (v8.4.0)")
    temperature_contrast: Optional[Dict[str, str]] = Field(default=None, description="Color/mood {subject_temp, background_temp, contrast_method}")
    food_visual_ratio: Optional[str] = Field(default=None, description="FOOD_DOMINANT | BALANCED | ARCHITECTURE_DOMINANT (v8.5.0)")

    # GEN2 metadata fields
    inheritance: Optional[SceneInheritance] = Field(default=None, description="Наслідування від батьківської сцени")
    post_production_notes: Optional[PostProductionNotes] = Field(default=None, description="Нотатки для постпродакшну")
    first_frame_composition: Optional[FirstFrameCompositionGEN2] = Field(default=None, description="Композиція першого кадру (Scene 1)")
    scale_techniques: Optional[ScalesTechniques] = Field(default=None, description="Техніки масштабу")
    visual_punctuation: Optional[str] = Field(default=None, description="Візуальна пунктуація")
    easter_egg_integration: Optional[EasterEggIntegration] = Field(default=None, description="Інтеграція Easter Egg (якщо є)")

    @model_validator(mode='before')
    @classmethod
    def validate_gen2_fields(cls, data: Any) -> Any:
        """
        Validate GEN2 OUTPUT CONTRACT requirements.
        Convert None values to empty strings for optional text fields.
        """
        if isinstance(data, dict):
            # Convert None to empty string for text fields
            text_fields = ['on_screen_text', 'voiceover', 'voiceover_segment', 'scene_name',
                          'visual_description', 'audio_sfx', 'audio_moment', 'narrative_purpose',
                          'energy_level', 'reference_type', 'camera_movement', 'broker_script']
            for field in text_fields:
                if data.get(field) is None:
                    data[field] = ""

            # Normalize voiceover fields
            if data.get('voiceover_segment') and not data.get('voiceover'):
                data['voiceover'] = data['voiceover_segment']
            if data.get('broker_script') and not data.get('voiceover'):
                data['voiceover'] = data['broker_script']
        return data

    # Computed properties for backward compatibility
    @property
    def duration(self) -> float:
        return self.duration_seconds


# ============================================================================
# VOICEOVER - Налаштування озвучки
# ============================================================================

class VoiceoverSettings(BaseModel):
    """Налаштування ElevenLabs - voice_id required, others have defaults."""
    voice_id: str = Field(default="fdph4PvCSJPBv95E9UZF", description="Voice ID - defaults to Sensory Witness")
    stability: float = Field(default=0.60, description="Stability")
    similarity_boost: float = Field(default=0.75, description="Similarity boost")
    style: float = Field(default=0.30, description="Style")
    speaker_boost: bool = Field(default=True, description="Speaker boost")
    speed: float = Field(default=1.0, ge=0.7, le=1.2, description="TTS speech speed (0.7=slow, 1.2=fast)")


class VoiceoverConfig(BaseModel):
    """Повна конфігурація озвучки - settings and full_script required."""
    settings: VoiceoverSettings = Field(..., description="Налаштування - REQUIRED")
    full_script: str = Field(..., description="Повний текст з маркерами - REQUIRED")
    character: str = Field(default="sensory_witness", description="sensory_witness | announcer | guide")
    model: str = Field(default="eleven_v3", description="ElevenLabs model")
    total_duration_seconds: float = Field(default=60.0, description="Загальна тривалість")

    @model_validator(mode='before')
    @classmethod
    def validate_required_fields(cls, data: Any) -> Any:
        """Validate voiceover has required content."""
        if isinstance(data, dict):
            if not data.get('full_script'):
                raise ValueError("voiceover.full_script is REQUIRED per GEN1 OUTPUT CONTRACT")
        return data

    # Backward compatibility
    @property
    def voice_id(self) -> str:
        return self.settings.voice_id

    @property
    def stability(self) -> float:
        return self.settings.stability

    @property
    def similarity_boost(self) -> float:
        return self.settings.similarity_boost


# ============================================================================
# AUDIO - Фонова музика та SFX
# ============================================================================

class SonicHook(BaseModel):
    """Звуковий хук - ALL FIELDS from GEN1."""
    type: str = Field(..., description="Тип (THE_BOOM, THE_SIZZLE, etc) - REQUIRED")
    timing: str = Field(default="0.0s", description="Час запуску")
    description: str = Field(..., description="Опис звуку - REQUIRED")
    volume: str = Field(default="LOUD", description="Гучність (LOUD, CRISP, MEDIUM)")


class FoleyPalette(BaseModel):
    """Палітра Foley звуків з GEN1."""
    primary_sounds: List[str] = Field(default_factory=list, description="Основні звуки")
    search_terms: List[str] = Field(default_factory=list, description="Терміни для пошуку")
    scene_assignments: Dict[str, List[str]] = Field(default_factory=dict, description="Призначення по сценах")


class SceneSFX(BaseModel):
    """SFX для однієї сцени."""
    type: str = Field(..., description="Тип (IMPACT, TEXTURE, AMBIENCE)")
    timing: str = Field(default="0.0s", description="Час")
    description: str = Field(..., description="Опис")
    volume: str = Field(default="MEDIUM", description="Гучність")


class SceneSFXAssignment(BaseModel):
    """Призначення SFX для сцени."""
    scene: int = Field(..., description="Номер сцени")
    sfx: List[SceneSFX] = Field(default_factory=list, description="Список SFX")


class BackgroundMusic(BaseModel):
    """Конфігурація фонової музики - genre, mood, bpm required."""
    genre: str = Field(..., description="Жанр - REQUIRED")
    style: str = Field(default="cinematic", description="Стиль")
    bpm: int = Field(..., description="BPM - REQUIRED")
    mood: str = Field(..., description="Настрій - REQUIRED")
    duration_seconds: int = Field(default=60, description="Тривалість")
    reference: str = Field(default="", description="Референс")


class SFXItem(BaseModel):
    """Один звуковий ефект - ALL FIELDS REQUIRED."""
    timestamp: str = Field(..., description="Час (0:02 формат) - REQUIRED")
    effect: str = Field(..., description="Назва ефекту - REQUIRED")
    description: str = Field(..., description="Опис - REQUIRED")

    # Alias for backward compatibility
    @property
    def sound_effect(self) -> str:
        return self.effect


class AudioConfig(BaseModel):
    """Повна аудіо конфігурація - background_music required."""
    background_music: BackgroundMusic = Field(..., description="Фонова музика - REQUIRED")
    suno_prompt: str = Field(default="", description="GEN1 music prompt for Suno/Udio generation")
    sfx: List[SFXItem] = Field(default_factory=list, description="SFX legacy format")
    # New fields from GEN1
    sonic_hook: Optional[SonicHook] = Field(default=None, description="Звуковий хук з GEN1")
    foley_palette: Optional[FoleyPalette] = Field(default=None, description="Foley палітра з GEN1")
    sfx_per_scene: List[SceneSFXAssignment] = Field(default_factory=list, description="SFX по сценах з GEN1")


# ============================================================================
# PUBLISH CONFIG - Конфігурація публікації
# ============================================================================

class PublishConfig(BaseModel):
    """Конфігурація публікації для мультиканальної підтримки."""
    target_channel: str = Field(default="glaze_city", description="Ідентифікатор цільового YouTube каналу")
    auto_schedule: bool = Field(default=True, description="Автоматичне планування на перший вільний слот")


# ============================================================================
# YOUTUBE METADATA - Метадані для публікації
# ============================================================================

class PostingTime(BaseModel):
    """Оптимальний час публікації - ALL FIELDS REQUIRED."""
    day: str = Field(..., description="День - REQUIRED")
    time: str = Field(..., description="Час - REQUIRED")
    timezone: str = Field(..., description="Timezone - REQUIRED")


class ViralMetadata(BaseModel):
    """Метадані для YouTube - title and description required, others have defaults."""
    title: str = Field(..., description="Заголовок (max 60 chars) - NEVER NULL - REQUIRED")
    description: str = Field(..., description="Опис (min 100 chars) - NEVER NULL - REQUIRED")
    pinned_comment: str = Field(default="", description="Закріплений коментар")
    title_char_count: int = Field(default=0, description="Кількість символів в заголовку")
    hashtags: List[str] = Field(default_factory=list, description="Хештеги")
    tags: List[str] = Field(default_factory=list, description="SEO теги")
    posting_time: Union[PostingTime, str] = Field(default="", description="Час публікації")

    @model_validator(mode='before')
    @classmethod
    def validate_required_fields(cls, data: Any) -> Any:
        """Validate youtube metadata - provide defaults if missing."""
        if isinstance(data, dict):
            if not data.get('title'):
                data['title'] = "Glaze City Property"
            if not data.get('description'):
                data['description'] = data.get('title', 'Glaze City Property')
        return data

    # Backward compatibility
    @property
    def youtube_tags(self) -> List[str]:
        return self.tags


# ============================================================================
# VIRAL AUDIT - Аудит вірусності
# ============================================================================

class AuditScore(BaseModel):
    """Один показник аудиту - ALL FIELDS REQUIRED."""
    score: int = Field(..., ge=0, le=10, description="Оцінка - REQUIRED")
    reason: str = Field(..., description="Причина - REQUIRED")


class ViralAuditScores(BaseModel):
    """Всі показники аудиту - ALL FIELDS REQUIRED."""
    hook_strength: AuditScore = Field(..., description="Сила хуку - REQUIRED")
    retention_architecture: AuditScore = Field(..., description="Архітектура утримання - REQUIRED")
    loop_quality: AuditScore = Field(..., description="Якість циклу - REQUIRED")
    psychological_triggers: AuditScore = Field(..., description="Психологічні тригери - REQUIRED")
    easter_egg_appeal: AuditScore = Field(..., description="Привабливість Easter Egg - REQUIRED")
    brand_fit: AuditScore = Field(..., description="Відповідність бренду - REQUIRED")
    # v8.3.0 additional metrics
    mute_test: Optional[AuditScore] = Field(default=None, description="Mute test score")
    categorization_clarity: Optional[AuditScore] = Field(default=None, description="YouTube NLP classification clarity")
    niche_alignment: Optional[AuditScore] = Field(default=None, description="Alignment with existing large niches")


class ViralAudit(BaseModel):
    """Повний аудит вірусності - all fields have defaults."""
    scores: Optional[ViralAuditScores] = Field(default=None, description="Оцінки")
    total_score: int = Field(default=0, description="Загальна оцінка")
    max_score: int = Field(default=100, description="Максимальна оцінка")
    viral_probability: str = Field(default="MEDIUM", description="LOW/MEDIUM/HIGH")
    viral_reasoning: str = Field(default="", description="Обґрунтування")
    weak_points: List[str] = Field(default_factory=list, description="Слабкі сторони з GEN1")
    strength_points: List[str] = Field(default_factory=list, description="Сильні сторони з GEN1")

    # Backward compatibility properties
    @property
    def hook_strength(self) -> int:
        return self.scores.hook_strength.score if self.scores else 0

    @property
    def retention_architecture(self) -> int:
        return self.scores.retention_architecture.score if self.scores else 0

    @property
    def loop_quality(self) -> int:
        return self.scores.loop_quality.score if self.scores else 0


# ============================================================================
# SERIES - Серія та сиквели
# ============================================================================

class SeriesInfo(BaseModel):
    """Інформація про серію - all fields have defaults."""
    category: str = Field(default="", description="Категорія (Mansions/Motors/etc)")
    sequel_ideas: List[str] = Field(default_factory=list, description="Ідеї для сиквелів")


# ============================================================================
# META - Метаінформація
# ============================================================================

class ProjectConcept(BaseModel):
    """Концепція проекту з GEN1 metadata."""
    category: str = Field(default="", description="Категорія контенту (LUXURY_LISTINGS, etc)")
    subject: str = Field(default="", description="Основний об'єкт")
    food_material: str = Field(default="", description="Харчовий матеріал")
    architectural_style: str = Field(default="", description="Архітектурний стиль")
    originality_note: str = Field(default="", description="Що робить унікальним")


class ProjectMetadata(BaseModel):
    """Метадані проекту з GEN1 (version, status, title, concept)."""
    version: str = Field(default="3.0", description="Версія схеми")
    status: str = Field(default="PRODUCTION_READY", description="Статус виводу")
    title: str = Field(default="", description="Короткий заголовок")
    concept: Optional[ProjectConcept] = Field(default=None, description="Концепція проекту")
    target_duration_seconds: int = Field(default=10, description="Цільова тривалість")
    scene_count: int = Field(default=8, description="Кількість сцен (6-10)")


class ProjectMeta(BaseModel):
    """Метаінформація проекту - most fields have defaults."""
    total_scenes: int = Field(default=0, description="Кількість сцен (6-10), 0=auto from len(scenes)")
    total_duration_seconds: float = Field(default=60.0, description="Загальна тривалість")
    content_pillar: str = Field(default="", description="Контент категорія")
    generated_at: str = Field(default="", description="Час генерації")


# ============================================================================
# GLAZE CITY PROJECT - Головна модель
# ============================================================================

class GlazeCityProject(BaseModel):
    """
    Повний проект GLAZE CITY (JSON формат) v7.4.
    Підтримує повний pipeline: GEN1 → GEN2 → GEN3a → GEN3b

    VALIDATION: Per GEN1.txt OUTPUT CONTRACT, the following are REQUIRED:
    - property (name, location, price)
    - architectural_identity (style_code, style_description)
    - food_identity (primary_food, food_dna)
    - lighting_master (preset, prompt_snippet)
    - hook (type, opening_line)
    - voiceover (full_script)
    - youtube (title, description) - NEVER NULL
    - scenes (6-10 scenes)
    """
    model_config = ConfigDict(extra='allow')

    # Property - REQUIRED
    property: PropertyBrief

    # v7.4: Architectural & Food Identity - REQUIRED per GEN1 OUTPUT CONTRACT
    architectural_identity: ArchitecturalIdentity = Field(
        ..., description="Архітектурна ідентичність v7.4 - REQUIRED"
    )
    food_identity: FoodIdentity = Field(
        ..., description="Харчова ідентичність v7.4 - REQUIRED"
    )

    # v7.4: Lighting & Foreground - Lighting REQUIRED, Foreground optional
    lighting_master: LightingMaster = Field(
        ..., description="Master освітлення v7.4 - REQUIRED"
    )
    foreground_element: Optional[ForegroundElement] = Field(
        default=None, description="Елемент переднього плану v7.4"
    )

    # v7.4: Atmosphere & Hook Matrix - have defaults
    atmosphere_mode: str = Field(
        default="CINEMATIC", description="Режим атмосфери (CINEMATIC/VIBRANT/PLAYFUL)"
    )
    hook_matrix: Optional[HookMatrix] = Field(
        default=None, description="Матриця хуків v7.4"
    )

    # Hook & Psychology - REQUIRED
    hook: HookStrategy = Field(..., description="Стратегія хуку - REQUIRED")
    psychology: Psychology = Field(..., description="Психологія - REQUIRED")

    # Warning Line — catchy warning for AERIAL (N-1) scene
    warning_line: str = Field(default="", description="Memorable warning for AERIAL scene, 3-8 words")

    # --- GEN1 extra fields (zero-loss merge) ---
    humor: Optional[List[Dict[str, Any]]] = Field(default=None, description="Standalone humor captions per scene")
    asmr_scenes: Optional[List[int]] = Field(default=None, description="Scene numbers with ASMR treatment")
    controversy_seed: Optional[Dict[str, Any]] = Field(default=None, description="Controversy engagement strategy")
    duration_config: Optional[Dict[str, Any]] = Field(default=None, description="Duration breakdown: hook/exploration/escalation/climax zones")
    completion_bait: Optional[Dict[str, Any]] = Field(default=None, description="Verbal open loop for retention")
    first_frame_composition_gen1: Optional[Dict[str, Any]] = Field(default=None, description="GEN1 top-level first frame (pareidolia, text_overlay, etc.)")
    temperature_contrast_global: Optional[Dict[str, Any]] = Field(default=None, description="GEN1 top-level warm/cold contrast strategy")
    series_identity: Optional[Dict[str, Any]] = Field(default=None, description="Full series config: recurring_character, watermark, sfx, series_hook")
    save_trigger: Optional[str] = Field(default=None, description="CTA for viewers to save the video")

    # Easter Egg & Loop - REQUIRED
    easter_egg: EasterEgg = Field(..., description="Easter Egg - REQUIRED")
    loop: LoopConfig = Field(..., description="Конфігурація циклу - REQUIRED")

    # Replay Hooks (v8.0.0+) — alternative to easter_egg
    replay_hooks: List[Dict[str, Any]] = Field(default_factory=list, description="Replay hooks for re-engagement (GEN1 v8.0.0+)")

    # Metadata Variants (v8.2.0+) — A/B/C/D rotation for YouTube
    metadata_variants: Optional[Dict[str, Any]] = Field(default=None, description="A/B/C/D metadata variants for YouTube rotation")

    # Share Trigger - from GEN1
    share_trigger: Optional[ShareTrigger] = Field(default=None, description="Тригер для шерингу з GEN1")

    # Visual Summary - from GEN2
    visual_summary: Optional[VisualSummary] = Field(default=None, description="Огляд візуалів з GEN2")

    # Scenes - REQUIRED (6-10 scenes)
    scenes: List[GlazeScene] = Field(..., description="Сцени (6-10) - REQUIRED")

    # Voiceover & Audio - REQUIRED
    voiceover: VoiceoverConfig = Field(..., description="Озвучка - REQUIRED")
    audio: AudioConfig = Field(..., description="Аудіо - REQUIRED")

    # Publish Config - for multi-channel support
    publish_config: Optional[PublishConfig] = Field(default=None, description="Конфігурація публікації для мультиканалів")

    # YouTube - REQUIRED, NEVER NULL
    youtube: ViralMetadata

    # GEN1 Metadata (version, status, title, concept) - for brief completeness
    gen1_metadata: Optional[ProjectMetadata] = Field(default=None, description="Метадані з GEN1 (version, status, title, concept)")

    # GEN2 Global Settings - negative_prompt is CRITICAL for image generation
    negative_prompt: str = Field(
        default="tilt-shift, miniature, diorama, toy, cartoon, anime, illustration, drawing, painting, sketch",
        description="Глобальний negative prompt з GEN2 - CRITICAL для якості зображень"
    )

    @model_validator(mode='before')
    @classmethod
    def validate_gen1_contract(cls, data: Any) -> Any:
        """
        Validate GEN1 OUTPUT CONTRACT requirements.
        Critical fields must be present and non-empty.
        """
        if isinstance(data, dict):
            errors = []

            # Check required top-level objects
            if not data.get('architectural_identity'):
                errors.append("architectural_identity is REQUIRED per GEN1 OUTPUT CONTRACT")
            if not data.get('food_identity'):
                errors.append("food_identity is REQUIRED per GEN1 OUTPUT CONTRACT")
            if not data.get('lighting_master'):
                errors.append("lighting_master is REQUIRED per GEN1 OUTPUT CONTRACT")

            # Check youtube (NEVER NULL per GEN1)
            youtube = data.get('youtube', {})
            if not youtube:
                errors.append("youtube is REQUIRED and NEVER NULL per GEN1 OUTPUT CONTRACT")
            elif isinstance(youtube, dict):
                if not youtube.get('title'):
                    errors.append("youtube.title is REQUIRED and NEVER NULL")
                if not youtube.get('description'):
                    errors.append("youtube.description is REQUIRED and NEVER NULL")

            # Check scenes count (6-10)
            scenes = data.get('scenes', [])
            if len(scenes) < 6 or len(scenes) > 10:
                errors.append(f"scenes must have 6-10 items, got {len(scenes)}")

            # Check hook has content
            hook = data.get('hook', {})
            if isinstance(hook, dict) and not hook.get('type') and not hook.get('opening_line'):
                errors.append("hook.type or hook.opening_line is required")

            # Raise all errors together
            if errors:
                raise ValueError(f"GEN1 OUTPUT CONTRACT validation failed:\n- " + "\n- ".join(errors))

        return data

    # Audit - REQUIRED
    viral_audit: ViralAudit = Field(..., description="Аудит вірусності - REQUIRED")

    # Series - REQUIRED
    series: SeriesInfo = Field(..., description="Інформація про серію - REQUIRED")

    # Meta - REQUIRED
    meta: ProjectMeta = Field(..., description="Метаінформація - REQUIRED")

    # Processing fields (not from JSON) - Optional runtime fields
    project_id: str = Field(default="", description="Унікальний ID проекту")
    created_at: datetime = Field(default_factory=datetime.now)
    raw_output: str = Field(default="", description="Оригінальний JSON")
    project_dir: Optional[Path] = Field(default=None, description="Папка проекту")

    # =====================================================================
    # RAW PRESERVATION - Повні оригінали GEN1/GEN2 без втрат
    # =====================================================================
    gen1_raw: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Повний вихід GEN1 як dict - SINGLE SOURCE OF TRUTH. Якщо поле загубилось при merge, воно тут."
    )
    gen2_raw: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Повний вихід GEN2 як dict - SINGLE SOURCE OF TRUTH. Якщо поле загубилось при merge, воно тут."
    )

    # =====================================================================
    # BACKWARD COMPATIBILITY PROPERTIES
    # =====================================================================

    @property
    def total_scenes(self) -> int:
        return self.meta.total_scenes or len(self.scenes)

    @property
    def total_duration(self) -> int:
        return self.meta.total_duration_seconds or sum(s.duration_seconds for s in self.scenes)

    @property
    def metadata(self) -> ViralMetadata:
        """Alias for youtube field."""
        return self.youtube

    @property
    def audit(self) -> ViralAudit:
        """Alias for viral_audit field."""
        return self.viral_audit

    @property
    def background_audio(self) -> BackgroundMusic:
        """Alias for audio.background_music."""
        return self.audio.background_music

    @property
    def sfx_list(self) -> List[SFXItem]:
        """Alias for audio.sfx."""
        return self.audio.sfx

    @property
    def sequel_ideas(self) -> List[str]:
        """Alias for series.sequel_ideas."""
        return self.series.sequel_ideas

    # =====================================================================
    # HELPER METHODS
    # =====================================================================

    def get_scene(self, scene_number: int) -> Optional[GlazeScene]:
        """Отримати сцену за номером."""
        for scene in self.scenes:
            if scene.scene_number == scene_number:
                return scene
        return None

    def get_pending_scenes(self) -> List[GlazeScene]:
        """Отримати сцени що очікують обробки."""
        return [s for s in self.scenes if s.status == "pending"]

    def get_image_prompts(self) -> List[dict]:
        """Отримати всі промпти для зображень."""
        return [
            {"scene": s.scene_number, "prompt": s.image_prompt}
            for s in self.scenes if s.image_prompt
        ]

    def get_video_prompts(self) -> List[dict]:
        """Отримати всі промпти для відео."""
        return [
            {"scene": s.scene_number, "prompt": s.video_prompt, "tool": s.video_tool}
            for s in self.scenes if s.video_prompt
        ]


# ============================================================================
# EXPORT
# ============================================================================

__all__ = [
    # Enums v7.4
    "AtmosphereMode",
    "HookStyleType",
    "VisualType",
    "EffectPalette",
    "SubtitleStyle",
    # v7.4 Identity models
    "ArchitecturalIdentity",
    "FoodDNA",
    "FoodIdentity",
    "LightingMaster",
    "ForegroundElement",
    "FirstFrameComposition",
    "HookStyleDefinition",
    "HookMatrix",
    # Property
    "FoodMaterial",
    "PropertySpecs",
    "PropertyBrief",
    "HookStrategy",
    "Psychology",
    # Share Trigger
    "ShareTrigger",
    # Easter Egg
    "EasterEggIntegration",
    "EasterEgg",
    "LoopConfig",
    # GEN2 Scene Metadata
    "SceneInheritance",
    "PostProductionNotes",
    "FirstFrameCompositionGEN2",
    "ScalesTechniques",
    "LoopVerification",
    "VisualSummary",
    # Scene
    "GlazeScene",
    # Voiceover
    "VoiceoverSettings",
    "VoiceoverConfig",
    # Audio
    "SonicHook",
    "FoleyPalette",
    "SceneSFX",
    "SceneSFXAssignment",
    "BackgroundMusic",
    "SFXItem",
    "AudioConfig",
    # YouTube
    "PostingTime",
    "ViralMetadata",
    # Viral Audit
    "AuditScore",
    "ViralAuditScores",
    "ViralAudit",
    # Series & Meta
    "SeriesInfo",
    "ProjectConcept",
    "ProjectMetadata",
    "ProjectMeta",
    # Main
    "GlazeCityProject",
]
