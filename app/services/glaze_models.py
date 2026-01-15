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
    """Food DNA - маппинг їжі на архітектурні елементи - ALL FIELDS REQUIRED."""
    walls_become: str = Field(..., description="Що стає стінами - REQUIRED")
    roof_becomes: str = Field(..., description="Що стає дахом - REQUIRED")
    windows_become: str = Field(..., description="Що стає вікнами - REQUIRED")
    door_becomes: str = Field(..., description="Що стає дверима - REQUIRED")
    doors_become: str = Field(..., description="Що стає дверима (alias) - REQUIRED")
    floors_become: str = Field(..., description="Що стає підлогою - REQUIRED")
    columns_become: str = Field(..., description="Що стає колонами - REQUIRED")
    furniture_becomes: str = Field(..., description="Що стає меблями - REQUIRED")
    chimney_becomes: str = Field(..., description="Що стає димоходом - REQUIRED")
    stairs_become: str = Field(..., description="Що стає сходами - REQUIRED")
    fence_becomes: str = Field(..., description="Що стає огорожею - REQUIRED")
    landscaping_becomes: str = Field(..., description="Що стає ландшафтом - REQUIRED")

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
    """Матриця доступних стилів хуків - ALL FIELDS REQUIRED."""
    selected_style: str = Field(..., description="Обраний стиль - REQUIRED")
    style_reason: str = Field(..., description="Чому обрано цей стиль - REQUIRED")
    avoid_styles: List[str] = Field(..., description="Стилі яких уникати (для variety) - REQUIRED")


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
    """Інформація про нерухомість - ALL FIELDS REQUIRED."""
    name: str = Field(..., alias="name", description="Назва нерухомості - REQUIRED")
    location: str = Field(..., description="Район в Glaze City - REQUIRED")
    price: str = Field(..., description="Ціна як текст - REQUIRED")
    price_numeric: Union[int, float] = Field(..., description="Ціна як число - REQUIRED")
    food_material: Union[FoodMaterial, str] = Field(..., description="Харчові матеріали - REQUIRED")
    specs: Union[PropertySpecs, str] = Field(..., description="Характеристики - REQUIRED")

    class Config:
        populate_by_name = True


# ============================================================================
# HOOK - Стратегія хуку
# ============================================================================

class HookStrategy(BaseModel):
    """Стратегія хуку для залучення - ALL FIELDS REQUIRED."""
    type: str = Field(..., description="Тип хука (THE_IMPOSSIBLE, THE_ABSURD_LOGIC, etc) - REQUIRED")
    psychological_trigger: str = Field(..., description="Психологічний тригер - REQUIRED")
    first_frame_visual: str = Field(..., description="Візуал першого кадру - REQUIRED")
    first_words: str = Field(..., description="Перші слова VO - REQUIRED")
    complete_hook_vo: str = Field(..., description="Повний hook voiceover - REQUIRED")
    scroll_stop_element: str = Field(..., description="Елемент що зупиняє скрол - REQUIRED")
    opening_line: str = Field(..., description="Початкова фраза (legacy) - REQUIRED")
    visual_hook: str = Field(..., description="Візуальний хук (legacy) - REQUIRED")
    audio_hook: str = Field(..., description="Аудіо хук (legacy) - REQUIRED")

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
    """Психологічні тригери - ALL FIELDS REQUIRED."""
    triggers: List[str] = Field(..., description="Список тригерів - REQUIRED")
    reasoning: str = Field(..., description="Обґрунтування - REQUIRED")


# ============================================================================
# EASTER EGG - Схований елемент
# ============================================================================

class EasterEgg(BaseModel):
    """Схований елемент для коментарів - ALL FIELDS REQUIRED."""
    object: str = Field(..., description="Об'єкт - REQUIRED")
    scene_number: int = Field(..., description="Номер сцени (2-5) - REQUIRED")
    placement: str = Field(..., description="Розташування з координатами - REQUIRED")
    visibility: str = Field(..., description="FINDABLE або HIDDEN - REQUIRED")
    comment_bait: str = Field(..., description="Фраза для коментарів - REQUIRED")
    validation_check: str = Field(..., description="Опис для верифікації - REQUIRED")
    safe_zone_position: str = Field(..., description="Позиція в Safe Zone (legacy) - REQUIRED")
    visibility_score: float = Field(..., ge=0.0, le=1.0, description="Видимість 0.0-1.0 (legacy) - REQUIRED")

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
            if not data.get('comment_bait'):
                raise ValueError("easter_egg.comment_bait is REQUIRED per GEN1 OUTPUT CONTRACT")
            if not data.get('placement'):
                raise ValueError("easter_egg.placement is REQUIRED per GEN1 OUTPUT CONTRACT")
        return data


# ============================================================================
# LOOP - Налаштування циклу
# ============================================================================

class LoopConfig(BaseModel):
    """Налаштування циклу відео - ALL FIELDS REQUIRED."""
    last_line: str = Field(..., description="Остання фраза - REQUIRED")
    first_line: str = Field(..., description="Перша фраза - REQUIRED")
    connection: str = Field(..., description="Опис з'єднання - REQUIRED")


# ============================================================================
# SCENE - Дані сцени
# ============================================================================

class GlazeScene(BaseModel):
    """Повні дані однієї сцени - ALL FIELDS REQUIRED."""

    scene_number: int = Field(..., description="Номер сцени - REQUIRED")
    scene_name: str = Field(..., description="Назва сцени - REQUIRED")
    timestamp: str = Field(..., description="Таймстемп (0:00 формат) - REQUIRED")
    duration_seconds: float = Field(..., description="Тривалість в секундах - REQUIRED")

    # Script & Text - REQUIRED
    voiceover: str = Field(..., description="Текст озвучки з маркерами - REQUIRED")
    voiceover_segment: str = Field(..., description="Сегмент VO (alias) - REQUIRED")
    on_screen_text: str = Field(..., description="Текст на екрані - REQUIRED")
    narrative_purpose: str = Field(..., description="ESTABLISHING/STORY/LOOP_CLOSE - REQUIRED")
    energy_level: str = Field(..., description="HIGH/MEDIUM/LOW/EXPLOSIVE - REQUIRED")

    # Visual - REQUIRED
    visual_description: str = Field(..., description="Опис візуалу - REQUIRED")
    camera_movement: str = Field(..., description="Рух камери - REQUIRED")
    motion_elements: List[str] = Field(..., description="3+ motion elements - REQUIRED")

    # Audio - REQUIRED
    audio_sfx: str = Field(..., description="Звукові ефекти - REQUIRED")
    audio_moment: str = Field(..., description="Ключовий аудіо момент - REQUIRED")

    # AI Prompts - REQUIRED per GEN2 OUTPUT CONTRACT
    image_prompt: str = Field(..., description="Промпт Nano Banana Pro - REQUIRED")
    video_prompt: str = Field(..., description="Промпт Kling/Veo/Wan - REQUIRED")
    video_tool: str = Field(..., description="KLING/VEO/WAN - REQUIRED")
    reference_type: str = Field(..., description="PRIMARY | REQUIRES_REF | INDEPENDENT - REQUIRED")
    reference_hint: str = Field(..., description="Підказка для референсу (GEN1) - REQUIRED")

    # Processing status (додаткові поля для автоматизації)
    image_path: Optional[Path] = Field(default=None, description="Шлях до зображення")
    video_path: Optional[Path] = Field(default=None, description="Шлях до відео")
    status: str = Field(..., description="Статус обробки - REQUIRED")

    @model_validator(mode='before')
    @classmethod
    def validate_gen2_fields(cls, data: Any) -> Any:
        """
        Validate GEN2 OUTPUT CONTRACT requirements.
        Note: image_prompt and video_prompt are added by GEN2, so they may be empty
        in GEN1 output. Validation happens when full brief is used.
        """
        if isinstance(data, dict):
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
    """Налаштування ElevenLabs - ALL FIELDS REQUIRED."""
    voice_id: str = Field(..., description="Voice ID - REQUIRED")
    stability: float = Field(..., description="Stability - REQUIRED")
    similarity_boost: float = Field(..., description="Similarity boost - REQUIRED")
    style: float = Field(..., description="Style - REQUIRED")
    speaker_boost: bool = Field(..., description="Speaker boost - REQUIRED")


class VoiceoverConfig(BaseModel):
    """Повна конфігурація озвучки - ALL FIELDS REQUIRED."""
    settings: VoiceoverSettings = Field(..., description="Налаштування - REQUIRED")
    full_script: str = Field(..., description="Повний текст з маркерами - REQUIRED")
    character: str = Field(..., description="broker | announcer | guide - REQUIRED")
    model: str = Field(..., description="ElevenLabs model - REQUIRED")
    total_duration_seconds: float = Field(..., description="Загальна тривалість - REQUIRED")

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
    """Конфігурація фонової музики - ALL FIELDS REQUIRED."""
    genre: str = Field(..., description="Жанр - REQUIRED")
    style: str = Field(..., description="Стиль - REQUIRED")
    bpm: int = Field(..., description="BPM - REQUIRED")
    mood: str = Field(..., description="Настрій - REQUIRED")
    duration_seconds: int = Field(..., description="Тривалість - REQUIRED")
    reference: str = Field(..., description="Референс - REQUIRED")


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
    """Повна аудіо конфігурація - ALL FIELDS REQUIRED."""
    background_music: BackgroundMusic = Field(..., description="Фонова музика - REQUIRED")
    sfx: List[SFXItem] = Field(..., description="SFX - REQUIRED")


# ============================================================================
# YOUTUBE METADATA - Метадані для публікації
# ============================================================================

class PostingTime(BaseModel):
    """Оптимальний час публікації - ALL FIELDS REQUIRED."""
    day: str = Field(..., description="День - REQUIRED")
    time: str = Field(..., description="Час - REQUIRED")
    timezone: str = Field(..., description="Timezone - REQUIRED")


class ViralMetadata(BaseModel):
    """Метадані для YouTube - NEVER NULL per GEN1 OUTPUT CONTRACT - ALL FIELDS REQUIRED."""
    title: str = Field(..., description="Заголовок (max 60 chars) - NEVER NULL - REQUIRED")
    description: str = Field(..., description="Опис (min 100 chars) - NEVER NULL - REQUIRED")
    pinned_comment: str = Field(..., description="Закріплений коментар - REQUIRED")
    title_char_count: int = Field(..., description="Кількість символів в заголовку - REQUIRED")
    hashtags: List[str] = Field(..., description="Хештеги - REQUIRED")
    tags: List[str] = Field(..., description="SEO теги - REQUIRED")
    posting_time: Union[PostingTime, str] = Field(..., description="Час публікації - REQUIRED")

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
    """Повний аудит вірусності - ALL FIELDS REQUIRED."""
    scores: ViralAuditScores = Field(..., description="Оцінки - REQUIRED")
    total_score: int = Field(..., description="Загальна оцінка - REQUIRED")
    max_score: int = Field(..., description="Максимальна оцінка - REQUIRED")
    viral_probability: str = Field(..., description="LOW/MEDIUM/HIGH - REQUIRED")
    viral_reasoning: str = Field(..., description="Обґрунтування - REQUIRED")

    # Backward compatibility properties
    @property
    def hook_strength(self) -> int:
        return self.scores.hook_strength.score

    @property
    def retention_architecture(self) -> int:
        return self.scores.retention_architecture.score

    @property
    def loop_quality(self) -> int:
        return self.scores.loop_quality.score


# ============================================================================
# SERIES - Серія та сиквели
# ============================================================================

class SeriesInfo(BaseModel):
    """Інформація про серію - ALL FIELDS REQUIRED."""
    category: str = Field(..., description="Категорія (Mansions/Motors/etc) - REQUIRED")
    sequel_ideas: List[str] = Field(..., description="Ідеї для сиквелів - REQUIRED")


# ============================================================================
# META - Метаінформація
# ============================================================================

class ProjectMeta(BaseModel):
    """Метаінформація проекту - ALL FIELDS REQUIRED."""
    total_scenes: int = Field(..., description="Кількість сцен - REQUIRED")
    total_duration_seconds: float = Field(..., description="Загальна тривалість - REQUIRED")
    content_pillar: str = Field(..., description="Контент категорія - REQUIRED")
    generated_at: str = Field(..., description="Час генерації - REQUIRED")


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

    # v7.4: Atmosphere & Hook Matrix - ALL REQUIRED
    atmosphere_mode: str = Field(
        ..., description="Режим атмосфери (CINEMATIC/VIBRANT/PLAYFUL) - REQUIRED"
    )
    hook_matrix: HookMatrix = Field(
        ..., description="Матриця хуків v7.4 - REQUIRED"
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
