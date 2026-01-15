"""
API Schemas - Pydantic models для Orchestrator pipeline

Моделі для управління проектами та сценами в pipeline
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from pathlib import Path
from datetime import datetime
from enum import Enum


# ============================================================================
# ENUMS - Статуси та стани
# ============================================================================

class SceneStatus(str, Enum):
    """Статуси обробки сцени"""
    PENDING = "pending"              # Очікує обробки
    GENERATING_IMAGE = "generating_image"  # Генерація зображення
    IMAGE_READY = "image_ready"      # Зображення готове (Phase 1 завершено)
    AWAITING_PRIMARY_SELECTION = "awaiting_primary_selection"  # PRIMARY: чекає вибору людини
    VALIDATING = "validating"        # Валідація зображення
    VALIDATION_FAILED = "validation_failed"  # Валідація невдала (2 спроби)
    GENERATING_VIDEO = "generating_video"  # Генерація відео
    VIDEO_READY = "video_ready"      # Відео готове (Phase 2 завершено)
    AWAITING_APPROVAL = "awaiting_approval"  # Очікує схвалення
    APPROVED = "approved"            # Схвалено
    QUEUED_FOR_UPSCALE = "queued_for_upscale"  # В черзі на upscaling
    UPSCALING_FPS = "upscaling_fps"  # Етап 1: Підвищення FPS до 60
    UPSCALING_4K = "upscaling_4k"    # Етап 2: Upscale до 4K
    UPSCALE_COMPLETED = "upscale_completed"  # Upscaling завершено
    UPSCALE_FAILED = "upscale_failed"  # Помилка upscaling
    COMPLETED = "completed"          # Повністю завершено
    FAILED = "failed"                # Помилка
    REGENERATING = "regenerating"    # Регенерація


class ProjectStatus(str, Enum):
    """Статуси проекту"""
    CREATED = "created"              # Створено
    GENERATING_SCRIPT = "generating_script"  # Генерація сценарію
    PROCESSING_SCENES = "processing_scenes"  # Обробка сцен
    AWAITING_APPROVAL = "awaiting_approval"  # Очікує схвалення сцен
    POST_PROCESSING = "post_processing"  # Пост-обробка (voiceover, assembly, Topaz)
    COMPLETED = "completed"          # Завершено
    FAILED = "failed"                # Помилка
    PAUSED = "paused"                # Призупинено (для resume)


class PipelineStage(str, Enum):
    """
    Етапи pipeline v7.4 для checkpoint/resume системи.

    Кожен етап - це checkpoint. Якщо помилка на етапі X,
    можна продовжити з етапу X після виправлення.

    v7.4 Pipeline Flow:
    GEN1 → VAL_GEN1 → GEN2 → VAL_GEN2 → IMG_GEN → VAL_IMG →
    VID_GEN → GEN3a → VAL_GEN3a → GEN3b → VAL_GEN3b → RENDER
    """
    # Ініціалізація
    CREATED = "created"

    # Етап 1: Генерація сценарію (GEN1 + GEN2)
    SCRIPT_GENERATION = "script_generation"

    # Етап 2: PRIMARY сцена
    PRIMARY_CANDIDATES = "primary_candidates"      # Генерація 4 кандидатів
    PRIMARY_SELECTION = "primary_selection"        # Очікування вибору користувача
    PRIMARY_VIDEO = "primary_video"                # Генерація відео для PRIMARY

    # Етап 3: Обробка решти сцен
    REMAINING_SCENES = "remaining_scenes"          # Паралельна обробка сцен 2-N

    # Етап 4: Voiceover (раніше частина пост-обробки)
    VOICEOVER = "voiceover"                        # Генерація озвучки

    # Етап 5: GEN3a - Video Analysis (v7.4)
    VIDEO_ANALYSIS = "video_analysis"              # Gemini Vision аналіз відео
    VAL_VIDEO_ANALYSIS = "val_video_analysis"      # Валідація GEN3a output

    # Етап 6: GEN3b - Manifest Generation (v7.4)
    MANIFEST_GENERATION = "manifest_generation"    # Генерація FFmpeg manifest
    VAL_MANIFEST = "val_manifest"                  # Валідація manifest

    # Етап 7: Rendering (v7.4)
    RENDER = "render"                              # Manifest-based FFmpeg rendering

    # Legacy stages (for backwards compatibility)
    ASSEMBLY = "assembly"                          # Збірка фінального відео (legacy)
    TOPAZ_FPS = "topaz_fps"                        # FPS інтерполяція
    TOPAZ_UPSCALE = "topaz_upscale"                # 4K upscaling

    # Завершення
    COMPLETED = "completed"


# ============================================================================
# SCENE MODEL - Розширена модель сцени для Orchestrator
# ============================================================================

class SceneData(BaseModel):
    """
    Дані сцени для Orchestrator pipeline

    Розширює базову модель Scene з content_brain додатковими полями
    для tracking обробки та збереження результатів
    """

    # Базова інформація
    scene_number: int = Field(..., description="Номер сцени (1-based)")
    project_id: str = Field(..., description="ID проекту")

    # Опис сцени (з ContentBrain)
    description: str = Field(..., description="Опис що відбувається в сцені")
    key_elements: List[str] = Field(default_factory=list, description="Ключові елементи")
    mood: str = Field(default="neutral", description="Настрій сцени")

    # Промпти (згенеровані ContentBrain)
    image_prompt: Optional[str] = Field(None, description="Промпт для генерації зображення")
    motion_prompt: Optional[str] = Field(None, description="Промпт для відео/анімації")
    audio_prompt: Optional[str] = Field(None, description="Текст озвучки")

    # Статус обробки
    status: SceneStatus = Field(default=SceneStatus.PENDING, description="Поточний статус")

    # Шляхи до згенерованих файлів
    image_path: Optional[Path] = Field(None, description="Шлях до зображення")
    image_url: Optional[str] = Field(None, description="URL зображення на HiggsField (для FAST video)")
    video_path: Optional[Path] = Field(None, description="Шлях до сирого відео")
    fps_boosted_path: Optional[Path] = Field(None, description="Шлях до відео з 60 FPS")
    upscaled_path: Optional[Path] = Field(None, description="Шлях до 4K upscaled відео")

    # Metadata валідації
    validation_approved: bool = Field(default=False, description="Чи схвалено валідацією")
    validation_score: Optional[float] = Field(None, description="Оцінка якості (0-10)")
    validation_feedback: Optional[str] = Field(None, description="Feedback від валідатора")

    # Retry tracking
    retry_count: int = Field(default=0, description="Кількість повторних спроб")
    max_retries: int = Field(default=3, description="Максимум повторів")

    # PRIMARY scene tracking (Human Validation)
    is_primary_scene: bool = Field(default=False, description="Чи це PRIMARY сцена")
    primary_selected_by_human: bool = Field(default=False, description="Чи обрано людиною")
    primary_regeneration_count: int = Field(default=0, description="Кількість перегенерацій PRIMARY")

    # Reference system
    reference_type: Optional[str] = Field(None, description="PRIMARY|INDEPENDENT|REQUIRES_REF")
    reference_scene: Optional[int] = Field(None, description="Номер сцени-референсу")
    reference_image_url: Optional[str] = Field(None, description="URL зображення-референсу")

    # Upscaling tracking
    upscale_retry_count: int = Field(default=0, description="Кількість спроб upscaling")
    upscale_max_retries: int = Field(default=5, description="Максимум спроб upscaling")
    upscale_error_message: Optional[str] = Field(None, description="Помилка upscaling")

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    approved_at: Optional[datetime] = Field(None, description="Час схвалення користувачем")
    completed_at: Optional[datetime] = Field(None, description="Час завершення")

    # Error tracking
    error_message: Optional[str] = Field(None, description="Повідомлення про помилку")

    class Config:
        use_enum_values = True
        json_schema_extra = {
            "example": {
                "scene_number": 1,
                "project_id": "proj_abc123",
                "description": "Opening shot of kitchen with ingredients",
                "key_elements": ["kitchen", "marble counter", "ingredients"],
                "mood": "warm and inviting",
                "image_prompt": "A cozy modern kitchen...",
                "motion_prompt": "Camera pans slowly...",
                "status": "pending"
            }
        }


# ============================================================================
# PROJECT MODEL - Модель проекту
# ============================================================================

class ProjectData(BaseModel):
    """
    Дані проекту для Orchestrator

    Управляє повним lifecycle проекту від створення до завершення
    """

    # Ідентифікація
    project_id: str = Field(..., description="Унікальний ID проекту")

    # Вхідні параметри
    topic: str = Field(..., description="Тема відео")
    num_scenes: int = Field(..., ge=1, le=20, description="Кількість сцен")
    style: str = Field(default="educational", description="Стиль відео")
    target_audience: str = Field(default="general", description="Цільова аудиторія")

    # Згенерований сценарій
    title: Optional[str] = Field(None, description="Назва відео")
    summary: Optional[str] = Field(None, description="Короткий опис")
    tags: List[str] = Field(default_factory=list, description="Теги")

    # Сцени
    scenes: List[SceneData] = Field(default_factory=list, description="Список сцен")

    # Статус проекту
    status: ProjectStatus = Field(default=ProjectStatus.CREATED, description="Поточний статус")

    # =========================================================================
    # PIPELINE STAGE TRACKING (для checkpoint/resume)
    # =========================================================================
    current_stage: str = Field(
        default="created",
        description="Поточний етап pipeline (PipelineStage)"
    )
    last_successful_stage: Optional[str] = Field(
        None,
        description="Останній успішно завершений етап"
    )

    # Error tracking з деталями етапу
    last_error_stage: Optional[str] = Field(
        None,
        description="Етап на якому сталася остання помилка"
    )
    last_error_scene: Optional[int] = Field(
        None,
        description="Номер сцени де сталася помилка (якщо applicable)"
    )
    last_error_message: Optional[str] = Field(
        None,
        description="Детальне повідомлення про останню помилку"
    )
    last_error_at: Optional[datetime] = Field(
        None,
        description="Час останньої помилки"
    )

    # Resume tracking
    is_resumable: bool = Field(
        default=True,
        description="Чи можна продовжити pipeline після помилки"
    )
    resume_count: int = Field(
        default=0,
        description="Кількість resume спроб"
    )

    # =========================================================================
    # PROGRESS
    # =========================================================================
    total_scenes: int = Field(default=0, description="Всього сцен")
    completed_scenes: int = Field(default=0, description="Завершено сцен")
    failed_scenes: int = Field(default=0, description="Провалено сцен")

    # Директорії
    project_dir: Optional[Path] = Field(None, description="Шлях до директорії проекту")

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = Field(None, description="Час завершення")

    # Legacy error tracking (kept for compatibility)
    error_message: Optional[str] = Field(None, description="Повідомлення про помилку")

    # Settings
    concurrent_limit: int = Field(default=5, description="Макс. паралельних сцен")

    class Config:
        use_enum_values = True
        json_schema_extra = {
            "example": {
                "project_id": "proj_abc123",
                "topic": "How to make pasta carbonara",
                "num_scenes": 5,
                "style": "educational",
                "title": "Perfect Pasta Carbonara",
                "status": "created",
                "total_scenes": 5,
                "completed_scenes": 0
            }
        }


# ============================================================================
# VALIDATION RESULT - Результат валідації (для інтеграції)
# ============================================================================

class ImageValidationResult(BaseModel):
    """Результат валідації зображення від GeminiValidator"""

    approved: bool = Field(..., description="Чи схвалено зображення")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Впевненість (0-1)")
    quality_score: float = Field(..., ge=0.0, le=10.0, description="Оцінка якості (0-10)")
    feedback: str = Field(..., description="Детальний feedback")
    issues: List[str] = Field(default_factory=list, description="Виявлені проблеми")
    suggestions: List[str] = Field(default_factory=list, description="Пропозиції покращення")


# ============================================================================
# PIPELINE EVENTS - Події pipeline для tracking
# ============================================================================

class PipelineEvent(BaseModel):
    """Події що відбуваються в pipeline"""

    event_type: str = Field(..., description="Тип події")
    project_id: str = Field(..., description="ID проекту")
    scene_number: Optional[int] = Field(None, description="Номер сцени")
    message: str = Field(..., description="Опис події")
    metadata: Dict = Field(default_factory=dict, description="Додаткові дані")
    timestamp: datetime = Field(default_factory=datetime.now)


# ============================================================================
# EXPORT
# ============================================================================

__all__ = [
    "SceneStatus",
    "ProjectStatus",
    "PipelineStage",
    "SceneData",
    "ProjectData",
    "ImageValidationResult",
    "PipelineEvent",
]
