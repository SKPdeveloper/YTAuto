"""
GLAZE CITY Data Models (JSON Format) v7.4

Pydantic моделі для парсингу JSON виводу GLAZE CITY VIRAL ENGINE.
Підтримує повний pipeline: GEN1 → GEN2 → GEN3a → GEN3b

IMPORTANT: Ці моделі відповідають формату виводу з
PROTECTED файлів: config/GEN1.txt, GEN2.txt, GEN3a.txt, GEN3b.txt
"""

from pydantic import BaseModel, Field, model_validator
from typing import List, Optional, Dict, Any, Union, Literal
from pathlib import Path
from datetime import datetime
from enum import Enum


# ============================================================================
# ENUMS - Режими та стилі v7.4
# ============================================================================

class AtmosphereMode(str, Enum):
    """Режим атмосфери відео."""
    CINEMATIC = "CINEMATIC"
    VIBRANT = "VIBRANT"
    PLAYFUL = "PLAYFUL"


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

    class Config:
        populate_by_name = True


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
# EASTER EGG - Схований елемент
# ============================================================================

class EasterEgg(BaseModel):
    """Схований елемент для коментарів - object and scene_number required."""
    object: str = Field(..., description="Об'єкт - REQUIRED")
    scene_number: int = Field(default=3, description="Номер сцени (2-5)")
    placement: str = Field(default="center", description="Розташування з координатами")
    visibility: str = Field(default="FINDABLE", description="FINDABLE або HIDDEN")
    comment_bait: str = Field(default="", description="Фраза для коментарів")
    validation_check: str = Field(default="", description="Опис для верифікації")
    safe_zone_position: str = Field(default="center-left", description="Позиція в Safe Zone (legacy)")
    visibility_score: float = Field(default=0.7, ge=0.0, le=1.0, description="Видимість 0.0-1.0 (legacy)")

    @model_validator(mode='before')
    @classmethod
    def validate_required_fields(cls, data: Any) -> Any:
        """Validate easter egg has all required fields per GEN1 OUTPUT CONTRACT."""
        if isinstance(data, dict):
            if not data.get('object'):
                raise ValueError("easter_egg.object is REQUIRED per GEN1 OUTPUT CONTRACT")
            scene_num = data.get('scene_number', 0)
            if not scene_num or scene_num < 2 or scene_num > 5:
                raise ValueError("easter_egg.scene_number must be 2-5 per GEN1 OUTPUT CONTRACT")
            # comment_bait and placement have defaults, not strictly required
        return data


# ============================================================================
# LOOP - Налаштування циклу
# ============================================================================

class LoopConfig(BaseModel):
    """Налаштування циклу відео - connection required, others have defaults."""
    last_line: str = Field(default="", description="Остання фраза")
    first_line: str = Field(default="", description="Перша фраза")
    connection: str = Field(..., description="Опис з'єднання - REQUIRED")


# ============================================================================
# SCENE - Дані сцени
# ============================================================================

class GlazeScene(BaseModel):
    """Повні дані однієї сцени - Fields with defaults can be populated later."""

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
    visual_description: str = Field(default="", description="Опис візуалу")
    camera_movement: str = Field(default="PUSH", description="Рух камери")
    motion_elements: List[str] = Field(default_factory=list, description="3+ motion elements")

    # Audio - with defaults
    audio_sfx: str = Field(default="", description="Звукові ефекти")
    audio_moment: str = Field(default="", description="Ключовий аудіо момент")

    # AI Prompts - REQUIRED per GEN2 OUTPUT CONTRACT
    image_prompt: str = Field(..., description="Промпт Nano Banana Pro - REQUIRED")
    video_prompt: str = Field(..., description="Промпт Kling/Veo/Wan - REQUIRED")
    video_tool: str = Field(default="KLING", description="KLING/VEO/WAN")
    reference_type: str = Field(default="INDEPENDENT", description="PRIMARY | REQUIRES_REF | INDEPENDENT")
    reference_hint: str = Field(default="INDEPENDENT", description="Підказка для референсу (GEN1)")

    # Processing status (додаткові поля для автоматизації)
    image_path: Optional[Path] = Field(default=None, description="Шлях до зображення")
    video_path: Optional[Path] = Field(default=None, description="Шлях до відео")
    status: str = Field(default="PENDING", description="Статус обробки")

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
                          'energy_level', 'reference_hint', 'reference_type', 'camera_movement']
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

    @property
    def broker_script(self) -> str:
        return self.voiceover


# ============================================================================
# VOICEOVER - Налаштування озвучки
# ============================================================================

class VoiceoverSettings(BaseModel):
    """Налаштування ElevenLabs - voice_id required, others have defaults."""
    voice_id: str = Field(..., description="Voice ID - REQUIRED")
    stability: float = Field(default=0.5, description="Stability")
    similarity_boost: float = Field(default=0.75, description="Similarity boost")
    style: float = Field(default=0.0, description="Style")
    speaker_boost: bool = Field(default=True, description="Speaker boost")


class VoiceoverConfig(BaseModel):
    """Повна конфігурація озвучки - settings and full_script required."""
    settings: VoiceoverSettings = Field(..., description="Налаштування - REQUIRED")
    full_script: str = Field(..., description="Повний текст з маркерами - REQUIRED")
    character: str = Field(default="announcer", description="broker | announcer | guide")
    model: str = Field(default="eleven_multilingual_v2", description="ElevenLabs model")
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
    sfx: List[SFXItem] = Field(default_factory=list, description="SFX")


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
        """Validate youtube metadata - NEVER NULL per GEN1 OUTPUT CONTRACT."""
        if isinstance(data, dict):
            if not data.get('title'):
                raise ValueError("youtube.title is REQUIRED and NEVER NULL per GEN1 OUTPUT CONTRACT")
            if not data.get('description'):
                raise ValueError("youtube.description is REQUIRED and NEVER NULL per GEN1 OUTPUT CONTRACT")
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


class ViralAudit(BaseModel):
    """Повний аудит вірусності - all fields have defaults."""
    scores: Optional[ViralAuditScores] = Field(default=None, description="Оцінки")
    total_score: int = Field(default=0, description="Загальна оцінка")
    max_score: int = Field(default=100, description="Максимальна оцінка")
    viral_probability: str = Field(default="MEDIUM", description="LOW/MEDIUM/HIGH")
    viral_reasoning: str = Field(default="", description="Обґрунтування")

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

class ProjectMeta(BaseModel):
    """Метаінформація проекту - most fields have defaults."""
    total_scenes: int = Field(default=6, description="Кількість сцен")
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
    - scenes (6 scenes)
    """

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

    # Easter Egg & Loop - REQUIRED
    easter_egg: EasterEgg = Field(..., description="Easter Egg - REQUIRED")
    loop: LoopConfig = Field(..., description="Конфігурація циклу - REQUIRED")

    # Scenes - REQUIRED (6 scenes)
    scenes: List[GlazeScene] = Field(..., description="Сцени (6 штук) - REQUIRED")

    # Voiceover & Audio - REQUIRED
    voiceover: VoiceoverConfig = Field(..., description="Озвучка - REQUIRED")
    audio: AudioConfig = Field(..., description="Аудіо - REQUIRED")

    # YouTube - REQUIRED, NEVER NULL
    youtube: ViralMetadata

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

            # Check scenes count
            scenes = data.get('scenes', [])
            if len(scenes) < 6:
                errors.append(f"scenes must have 6 items, got {len(scenes)}")

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
    "EasterEgg",
    "LoopConfig",
    "GlazeScene",
    "VoiceoverSettings",
    "VoiceoverConfig",
    "BackgroundMusic",
    "SFXItem",
    "AudioConfig",
    "PostingTime",
    "ViralMetadata",
    "AuditScore",
    "ViralAuditScores",
    "ViralAudit",
    "SeriesInfo",
    "ProjectMeta",
    "GlazeCityProject",
]
