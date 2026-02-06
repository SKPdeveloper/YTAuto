"""
Централизованное управление путями проекта.

Все пути относительные от корня проекта (где лежит run_real_pipeline.py).
Используй эти константы вместо hardcoded путей.

Usage:
    from app.core.paths import PROJECTS_DIR, get_scene_path

    project_dir = get_project_path("proj_123")
    scene_dir = get_scene_path("proj_123", 1)
"""

from pathlib import Path

# ============================================================================
# BASE DIRECTORIES
# ============================================================================

# Корень проекта - директория где лежит run_real_pipeline.py
# Используем относительный путь от текущей рабочей директории
BASE_DIR = Path.cwd()

# Основные директории
PROJECTS_DIR = BASE_DIR / "projects"
DOWNLOADS_DIR = BASE_DIR / "downloads"
LOGS_DIR = BASE_DIR / "logs"
DATA_DIR = BASE_DIR / "data"
CONFIG_DIR = BASE_DIR / "config"

# Временные файлы
TEMP_DIR = BASE_DIR / "temp"

# Archive directories
ARCHIVE_DIR = BASE_DIR / "archive"
ARCHIVE_PUBLISHED_DIR = ARCHIVE_DIR / "published"
ARCHIVE_FAILED_DIR = ARCHIVE_DIR / "failed"
ARCHIVE_TEST_DIR = ARCHIVE_DIR / "test"


# ============================================================================
# PROJECT STRUCTURE
# ============================================================================

def get_project_path(project_id: str) -> Path:
    """
    Получить путь к директории проекта.

    Args:
        project_id: ID проекта (например "proj_abc123")

    Returns:
        Path к директории проекта

    Example:
        >>> get_project_path("proj_123")
        Path("projects/proj_123")
    """
    return PROJECTS_DIR / project_id


def get_scene_path(project_id: str, scene_num: int) -> Path:
    """
    Получить путь к директории сцены.

    Args:
        project_id: ID проекта
        scene_num: Номер сцены (1-6)

    Returns:
        Path к директории сцены

    Example:
        >>> get_scene_path("proj_123", 1)
        Path("projects/proj_123/scene_1")
    """
    return PROJECTS_DIR / project_id / f"scene_{scene_num}"


def get_scene_image_path(project_id: str, scene_num: int) -> Path:
    """
    Получить путь к основному изображению сцены.

    Returns:
        Path к image.png сцены
    """
    return get_scene_path(project_id, scene_num) / "image.png"


def get_scene_video_path(project_id: str, scene_num: int) -> Path:
    """
    Получить путь к видео сцены.

    Returns:
        Path к video.mp4 сцены
    """
    return get_scene_path(project_id, scene_num) / "video.mp4"


def get_candidate_path(project_id: str, scene_num: int, candidate_idx: int) -> Path:
    """
    Получить путь к кандидату PRIMARY сцены.

    Args:
        project_id: ID проекта
        scene_num: Номер сцены
        candidate_idx: Индекс кандидата (1-4)

    Returns:
        Path к candidate_{idx}.png
    """
    return get_scene_path(project_id, scene_num) / f"candidate_{candidate_idx}.png"


def get_project_brief_path(project_id: str) -> Path:
    """
    Получить путь к project_brief.json.

    Returns:
        Path к project_brief.json
    """
    return get_project_path(project_id) / "project_brief.json"


def get_final_video_path(project_id: str, upscaled: bool = False) -> Path:
    """
    Получить путь к финальному видео.

    Args:
        project_id: ID проекта
        upscaled: True для 4K версии

    Returns:
        Path к final.mp4 или final_4k.mp4
    """
    filename = "final_4k.mp4" if upscaled else "final.mp4"
    return get_project_path(project_id) / filename


def get_project_logs_path(project_id: str) -> Path:
    """
    Получить путь к директории логов проекта.

    Args:
        project_id: ID проекта

    Returns:
        Path к директории logs внутри проекта

    Example:
        >>> get_project_logs_path("proj_123")
        Path("projects/proj_123/logs")
    """
    return get_project_path(project_id) / "logs"


# ============================================================================
# CONFIG FILES
# ============================================================================

def get_prompt_path(prompt_name: str) -> Path:
    """
    Получить путь к файлу промпта.

    Args:
        prompt_name: Имя промпта (GEN1, GEN2, VAL_IMG, etc.)

    Returns:
        Path к файлу промпта

    Example:
        >>> get_prompt_path("GEN1")
        Path("config/GEN1.txt")
    """
    return CONFIG_DIR / f"{prompt_name}.txt"


# ============================================================================
# DOWNLOADS
# ============================================================================

def get_download_path(filename: str) -> Path:
    """
    Получить путь для загруженного файла.

    Args:
        filename: Имя файла

    Returns:
        Path в директории downloads
    """
    return DOWNLOADS_DIR / filename


# ============================================================================
# ENSURE DIRECTORIES
# ============================================================================

def ensure_directories() -> None:
    """
    Создать все необходимые директории если не существуют.
    Вызывается при старте приложения.
    """
    for directory in [
        PROJECTS_DIR, DOWNLOADS_DIR, LOGS_DIR, DATA_DIR, TEMP_DIR,
        ARCHIVE_PUBLISHED_DIR, ARCHIVE_FAILED_DIR, ARCHIVE_TEST_DIR,
    ]:
        directory.mkdir(parents=True, exist_ok=True)


def ensure_project_structure(project_id: str, num_scenes: int = 6) -> None:
    """
    Создать структуру директорий для проекта.

    Args:
        project_id: ID проекта
        num_scenes: Количество сцен (default: 6)
    """
    project_dir = get_project_path(project_id)
    project_dir.mkdir(parents=True, exist_ok=True)

    # Создать директорию для логов проекта
    logs_dir = get_project_logs_path(project_id)
    logs_dir.mkdir(parents=True, exist_ok=True)

    for scene_num in range(1, num_scenes + 1):
        scene_dir = get_scene_path(project_id, scene_num)
        scene_dir.mkdir(parents=True, exist_ok=True)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Directories
    "BASE_DIR",
    "PROJECTS_DIR",
    "DOWNLOADS_DIR",
    "LOGS_DIR",
    "DATA_DIR",
    "CONFIG_DIR",
    "TEMP_DIR",
    "ARCHIVE_DIR",
    "ARCHIVE_PUBLISHED_DIR",
    "ARCHIVE_FAILED_DIR",
    "ARCHIVE_TEST_DIR",

    # Project paths
    "get_project_path",
    "get_scene_path",
    "get_scene_image_path",
    "get_scene_video_path",
    "get_candidate_path",
    "get_project_brief_path",
    "get_final_video_path",
    "get_project_logs_path",

    # Config paths
    "get_prompt_path",

    # Downloads
    "get_download_path",

    # Utilities
    "ensure_directories",
    "ensure_project_structure",
]
