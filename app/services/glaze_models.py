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
    """Архітектурна ідентичність нерухомості."""
    style_code: str = Field(..., description="Код стилю (JAPANESE_MINIMALIST, BRUTALIST_GOTHIC, etc)")
    style_description: str = Field(..., description="Опис стилю")
    stories: int = Field(default=1, description="Кількість поверхів")
    distinctive_features: List[str] = Field(default_factory=list, description="Відмінні риси")
    silhouette_description: str = Field(default="", description="Опис силуету")
    interior_style: str = Field(default="", description="Стиль інтер'єру")

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
    walls_become: str = Field(..., description="Що стає стінами")
    roof_becomes: str = Field(..., description="Що стає дахом")
    windows_become: str = Field(..., description="Що стає вікнами")
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
    """Повна харчова ідентичність нерухомості."""
    primary_food: str = Field(..., description="Основна їжа")
    food_dna: FoodDNA = Field(..., description="Food DNA маппинг")
    texture_keywords: List[str] = Field(default_factory=list, description="Ключові слова текстури")
    color_keywords: List[str] = Field(default_factory=list, description="Ключові слова кольору")
    atmosphere: str = Field(default="", description="Атмосфера")

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
    """Master налаштування освітлення."""
    preset: str = Field(..., description="Пресет освітлення")
    mood_reason: str = Field(default="", description="Чому обрано цей настрій")
    prompt_snippet: str = Field(..., description="Фрагмент промпту для освітлення")

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
    """Елемент переднього плану для Scene 1."""
    type: str = Field(default="NONE", description="Тип (STEAM, GLAZE_DRIP, FALLING_INGREDIENT, NONE)")
    prompt_snippet: str = Field(default="", description="Фрагмент промпту")


# ============================================================================
# FIRST FRAME COMPOSITION - Композиція першого кадру v7.4
# ============================================================================

class FirstFrameComposition(BaseModel):
    """Композиція першого кадру для hook."""
    hero_subject: str = Field(default="", description="Головний об'єкт")
    hero_position: str = Field(default="upper_center", description="Позиція (upper_center, center_left, etc)")
    foreground_element: str = Field(default="", description="Елемент переднього плану")
    background_depth: str = Field(default="", description="Глибина фону")
    lighting_direction: str = Field(default="", description="Напрям освітлення")
    hook_element: str = Field(default="", description="Hook елемент")
    safe_zone_compliance: bool = Field(default=True, description="Відповідність Safe Zone")


# ============================================================================
# HOOK MATRIX - Матриця хуків v7.4
# ============================================================================

class HookStyleDefinition(BaseModel):
    """Визначення стилю хуку."""
    duration: float = Field(default=0.3, description="Тривалість в секундах")
    effects: List[Dict[str, Any]] = Field(default_factory=list, description="Список ефектів")
    sfx: str = Field(default="", description="Звуковий ефект")


class HookMatrix(BaseModel):
    """Матриця доступних стилів хуків."""
    selected_style: str = Field(default="CLASSIC", description="Обраний стиль")
    style_reason: str = Field(default="", description="Чому обрано цей стиль")
    avoid_styles: List[str] = Field(default_factory=list, description="Стилі яких уникати (для variety)")


# ============================================================================
# PROPERTY - Інформація про нерухомість
# ============================================================================

class FoodMaterial(BaseModel):
    """Харчові матеріали нерухомості."""
    primary: str = Field(..., description="Основний матеріал")
    secondary: List[str] = Field(default_factory=list, description="Додаткові матеріали")


class PropertySpecs(BaseModel):
    """Характеристики нерухомості."""
    bedrooms: int = Field(default=0)
    bathrooms: int = Field(default=0)
    sqft: int = Field(default=0)
    unique_feature: str = Field(default="", description="Унікальна фіча")


class PropertyBrief(BaseModel):
    """Інформація про нерухомість."""
    name: str = Field(..., alias="name", description="Назва нерухомості")
    location: str = Field(default="", description="Район в Glaze City")
    price: str = Field(default="", description="Ціна як текст")
    price_numeric: Union[int, float] = Field(default=0, description="Ціна як число")
    food_material: Union[FoodMaterial, str] = Field(default="", description="Харчові матеріали")
    specs: Union[PropertySpecs, str] = Field(default="", description="Характеристики")

    class Config:
        populate_by_name = True


# ============================================================================
# HOOK - Стратегія хуку
# ============================================================================

class HookStrategy(BaseModel):
    """Стратегія хуку для залучення."""
    type: str = Field(..., description="Тип хука (THE_IMPOSSIBLE, THE_ABSURD_LOGIC, etc)")
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
    """Психологічні тригери."""
    triggers: List[str] = Field(default_factory=list, description="Список тригерів")
    reasoning: str = Field(default="", description="Обґрунтування")


# ============================================================================
# EASTER EGG - Схований елемент
# ============================================================================

class EasterEgg(BaseModel):
    """Схований елемент для коментарів."""
    object: str = Field(..., description="Об'єкт")
    scene_number: int = Field(..., description="Номер сцени (2-5)")
    placement: str = Field(default="", description="Розташування з координатами")
    visibility: str = Field(default="FINDABLE", description="FINDABLE або HIDDEN")
    comment_bait: str = Field(..., description="Фраза для коментарів")
    validation_check: str = Field(default="", description="Опис для верифікації")
    safe_zone_position: str = Field(default="", description="Позиція в Safe Zone (legacy)")
    visibility_score: float = Field(default=0.7, ge=0.0, le=1.0, description="Видимість 0.0-1.0 (legacy)")

    @model_validator(mode='before')
    @classmethod
    def validate_required_fields(cls, data: Any) -> Any:
        """Validate easter egg has required content and set defaults."""
        if isinstance(data, dict):
            if not data.get('object'):
                raise ValueError("easter_egg.object is REQUIRED per GEN1 OUTPUT CONTRACT")
            scene_num = data.get('scene_number', 0)
            if not scene_num or scene_num < 2 or scene_num > 5:
                raise ValueError("easter_egg.scene_number must be 2-5 per GEN1 OUTPUT CONTRACT")
            # Set default comment_bait if missing
            if not data.get('comment_bait'):
                obj_name = data.get('object', 'something')
                data['comment_bait'] = f"Did you spot the tiny {obj_name}? First to find it wins!"
            # Set default placement if missing
            if not data.get('placement'):
                data['placement'] = "bottom-center, 5% of frame, near main subject"
        return data


# ============================================================================
# LOOP - Налаштування циклу
# ============================================================================

class LoopConfig(BaseModel):
    """Налаштування циклу відео."""
    last_line: str = Field(default="", description="Остання фраза")
    first_line: str = Field(default="", description="Перша фраза")
    connection: str = Field(default="", description="Опис з'єднання")


# ============================================================================
# SCENE - Дані сцени
# ============================================================================

class GlazeScene(BaseModel):
    """Повні дані однієї сцени."""

    scene_number: int = Field(..., description="Номер сцени")
    scene_name: str = Field(default="", description="Назва сцени")
    timestamp: str = Field(default="0:00", description="Таймстемп (0:00 формат)")
    duration_seconds: float = Field(default=2.0, description="Тривалість в секундах")

    # Script & Text
    voiceover: str = Field(default="", description="Текст озвучки з маркерами")
    voiceover_segment: str = Field(default="", description="Сегмент VO (alias)")
    on_screen_text: Optional[str] = Field(default=None, description="Текст на екрані")
    narrative_purpose: str = Field(default="", description="ESTABLISHING/STORY/LOOP_CLOSE")
    energy_level: str = Field(default="MEDIUM", description="HIGH/MEDIUM/LOW/EXPLOSIVE")

    # Visual
    visual_description: str = Field(default="", description="Опис візуалу")
    camera_movement: str = Field(default="", description="Рух камери")
    motion_elements: List[str] = Field(default_factory=list, description="3+ motion elements")

    # Audio
    audio_sfx: str = Field(default="", description="Звукові ефекти")
    audio_moment: str = Field(default="", description="Ключовий аудіо момент")

    # AI Prompts - REQUIRED per GEN2 OUTPUT CONTRACT
    image_prompt: str = Field(default="", description="Промпт Nano Banana Pro")
    video_prompt: str = Field(default="", description="Промпт Kling/Veo/Wan")
    video_tool: str = Field(default="KLING", description="KLING/VEO/WAN")
    reference_type: str = Field(default="INDEPENDENT", description="PRIMARY | REQUIRES_REF | INDEPENDENT")
    reference_hint: str = Field(default="", description="Підказка для референсу (GEN1)")

    # Processing status (додаткові поля для автоматизації)
    image_path: Optional[Path] = Field(default=None, description="Шлях до зображення")
    video_path: Optional[Path] = Field(default=None, description="Шлях до відео")
    status: str = Field(default="pending", description="Статус обробки")

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
    """Налаштування ElevenLabs."""
    voice_id: str = Field(default="Adam")
    stability: float = Field(default=0.50)
    similarity_boost: float = Field(default=0.75)
    style: float = Field(default=0.30)
    speaker_boost: bool = Field(default=True)


class VoiceoverConfig(BaseModel):
    """Повна конфігурація озвучки."""
    settings: VoiceoverSettings = Field(default_factory=VoiceoverSettings)
    full_script: str = Field(..., description="Повний текст з маркерами - REQUIRED")
    character: str = Field(default="broker", description="broker | announcer | guide")
    model: str = Field(default="eleven_v3", description="ElevenLabs model")
    total_duration_seconds: float = Field(default=0, description="Загальна тривалість")

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
    """Конфігурація фонової музики."""
    genre: str = Field(default="")
    style: str = Field(default="")
    bpm: int = Field(default=120)
    mood: str = Field(default="")
    duration_seconds: int = Field(default=30)
    reference: str = Field(default="")


class SFXItem(BaseModel):
    """Один звуковий ефект."""
    timestamp: str = Field(..., description="Час (0:02 формат)")
    effect: str = Field(..., description="Назва ефекту")
    description: str = Field(default="", description="Опис")

    # Alias for backward compatibility
    @property
    def sound_effect(self) -> str:
        return self.effect


class AudioConfig(BaseModel):
    """Повна аудіо конфігурація."""
    background_music: BackgroundMusic = Field(default_factory=BackgroundMusic)
    sfx: List[SFXItem] = Field(default_factory=list)


# ============================================================================
# YOUTUBE METADATA - Метадані для публікації
# ============================================================================

class PostingTime(BaseModel):
    """Оптимальний час публікації."""
    day: str = Field(default="")
    time: str = Field(default="")
    timezone: str = Field(default="EST")


class ViralMetadata(BaseModel):
    """Метадані для YouTube - NEVER NULL per GEN1 OUTPUT CONTRACT."""
    title: str = Field(..., description="Заголовок (max 60 chars) - NEVER NULL")
    description: str = Field(..., description="Опис (min 100 chars) - NEVER NULL")
    pinned_comment: str = Field(default="", description="Закріплений коментар")
    title_char_count: int = Field(default=0)
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
    """Один показник аудиту."""
    score: int = Field(default=0, ge=0, le=10)
    reason: str = Field(default="")


class ViralAuditScores(BaseModel):
    """Всі показники аудиту."""
    hook_strength: AuditScore = Field(default_factory=AuditScore)
    retention_architecture: AuditScore = Field(default_factory=AuditScore)
    loop_quality: AuditScore = Field(default_factory=AuditScore)
    psychological_triggers: AuditScore = Field(default_factory=AuditScore)
    easter_egg_appeal: AuditScore = Field(default_factory=AuditScore)
    brand_fit: AuditScore = Field(default_factory=AuditScore)


class ViralAudit(BaseModel):
    """Повний аудит вірусності."""
    scores: ViralAuditScores = Field(default_factory=ViralAuditScores)
    total_score: int = Field(default=0)
    max_score: int = Field(default=60)
    viral_probability: str = Field(default="", description="LOW/MEDIUM/HIGH")
    viral_reasoning: str = Field(default="")

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
    """Інформація про серію."""
    category: str = Field(default="", description="Категорія (Mansions/Motors/etc)")
    sequel_ideas: List[str] = Field(default_factory=list)


# ============================================================================
# META - Метаінформація
# ============================================================================

class ProjectMeta(BaseModel):
    """Метаінформація проекту."""
    total_scenes: int = Field(default=0)
    total_duration_seconds: float = Field(default=0)
    content_pillar: str = Field(default="")
    generated_at: str = Field(default="auto")


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

    # v7.4: Atmosphere & Hook Matrix
    atmosphere_mode: str = Field(
        default="CINEMATIC", description="Режим атмосфери (CINEMATIC/VIBRANT/PLAYFUL)"
    )
    hook_matrix: Optional[HookMatrix] = Field(
        default=None, description="Матриця хуків v7.4"
    )

    # Hook & Psychology - REQUIRED
    hook: HookStrategy = Field(default_factory=HookStrategy)
    psychology: Psychology = Field(default_factory=Psychology)

    # Easter Egg & Loop - REQUIRED
    easter_egg: EasterEgg = Field(default_factory=EasterEgg)
    loop: LoopConfig = Field(default_factory=LoopConfig)

    # Scenes - REQUIRED (6 scenes)
    scenes: List[GlazeScene] = Field(default_factory=list)

    # Voiceover & Audio - REQUIRED
    voiceover: VoiceoverConfig = Field(default_factory=VoiceoverConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)

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

    # Audit
    viral_audit: ViralAudit = Field(default_factory=ViralAudit)

    # Series
    series: SeriesInfo = Field(default_factory=SeriesInfo)

    # Meta
    meta: ProjectMeta = Field(default_factory=ProjectMeta)

    # Processing fields (not from JSON)
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
