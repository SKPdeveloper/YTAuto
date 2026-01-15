"""
File Manager для Edible House Automator
Async функції для роботи з файлами (завантаження, збереження, очищення)
"""

import aiofiles
import httpx
from pathlib import Path
from typing import Optional
from app.core.config import settings
from app.utils.logger import logger


# ============================================================================
# DOWNLOAD FILES
# ============================================================================

async def download_file(
    url: str,
    destination: Path,
    timeout: int = 300
) -> Path:
    """
    Асинхронно завантажує файл з URL

    Args:
        url: URL файлу для завантаження
        destination: Шлях куди зберегти файл
        timeout: Timeout в секундах

    Returns:
        Path до збереженого файлу

    Raises:
        httpx.HTTPError: Помилка завантаження
        IOError: Помилка збереження
    """
    logger.debug(f"Downloading file from {url} to {destination}")

    try:
        # Створюємо директорію якщо не існує
        destination.parent.mkdir(parents=True, exist_ok=True)

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
            response.raise_for_status()

            # Зберігаємо файл
            async with aiofiles.open(destination, "wb") as f:
                await f.write(response.content)

        logger.success(f"File downloaded successfully: {destination}")
        return destination

    except httpx.HTTPError as e:
        logger.error(f"HTTP error downloading {url}: {e}")
        raise
    except Exception as e:
        logger.error(f"Error downloading {url}: {e}")
        raise


async def download_multiple_files(
    urls: list[str],
    destination_dir: Path,
    filename_template: str = "file_{index}.jpg"
) -> list[Path]:
    """
    Завантажує декілька файлів паралельно

    Args:
        urls: Список URLs
        destination_dir: Директорія для збереження
        filename_template: Шаблон імені файлу ({index} буде замінено на індекс)

    Returns:
        Список Path до збережених файлів
    """
    import asyncio

    logger.info(f"Downloading {len(urls)} files to {destination_dir}")

    tasks = [
        download_file(
            url,
            destination_dir / filename_template.format(index=i)
        )
        for i, url in enumerate(urls)
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Фільтруємо помилки
    successful = [r for r in results if isinstance(r, Path)]
    failed = [r for r in results if isinstance(r, Exception)]

    if failed:
        logger.warning(f"{len(failed)} files failed to download")

    logger.success(f"{len(successful)} files downloaded successfully")
    return successful


# ============================================================================
# SAVE FILES
# ============================================================================

async def save_text_file(
    content: str,
    destination: Path,
    encoding: str = "utf-8"
) -> Path:
    """
    Асинхронно зберігає текстовий файл

    Args:
        content: Текст для збереження
        destination: Шлях до файлу
        encoding: Кодування файлу

    Returns:
        Path до збереженого файлу
    """
    logger.debug(f"Saving text file: {destination}")

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)

        async with aiofiles.open(destination, "w", encoding=encoding) as f:
            await f.write(content)

        logger.debug(f"Text file saved: {destination}")
        return destination

    except Exception as e:
        logger.error(f"Error saving text file {destination}: {e}")
        raise


async def save_binary_file(
    content: bytes,
    destination: Path
) -> Path:
    """
    Асинхронно зберігає бінарний файл

    Args:
        content: Bytes для збереження
        destination: Шлях до файлу

    Returns:
        Path до збереженого файлу
    """
    logger.debug(f"Saving binary file: {destination}")

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)

        async with aiofiles.open(destination, "wb") as f:
            await f.write(content)

        logger.debug(f"Binary file saved: {destination}")
        return destination

    except Exception as e:
        logger.error(f"Error saving binary file {destination}: {e}")
        raise


async def save_json(
    data: dict,
    destination: Path,
    indent: int = 2
) -> Path:
    """
    Асинхронно зберігає JSON файл

    Args:
        data: Dict для збереження
        destination: Шлях до файлу
        indent: Кількість пробілів для форматування (default: 2)

    Returns:
        Path до збереженого файлу
    """
    import json

    logger.debug(f"Saving JSON file: {destination}")

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)

        json_content = json.dumps(data, indent=indent, ensure_ascii=False)

        async with aiofiles.open(destination, "w", encoding="utf-8") as f:
            await f.write(json_content)

        logger.debug(f"JSON file saved: {destination}")
        return destination

    except Exception as e:
        logger.error(f"Error saving JSON file {destination}: {e}")
        raise


# ============================================================================
# READ FILES
# ============================================================================

async def read_text_file(
    file_path: Path,
    encoding: str = "utf-8"
) -> str:
    """
    Асинхронно читає текстовий файл

    Args:
        file_path: Шлях до файлу
        encoding: Кодування файлу

    Returns:
        Вміст файлу як строка
    """
    logger.debug(f"Reading text file: {file_path}")

    try:
        async with aiofiles.open(file_path, "r", encoding=encoding) as f:
            content = await f.read()

        return content

    except Exception as e:
        logger.error(f"Error reading text file {file_path}: {e}")
        raise


async def read_binary_file(file_path: Path) -> bytes:
    """
    Асинхронно читає бінарний файл

    Args:
        file_path: Шлях до файлу

    Returns:
        Вміст файлу як bytes
    """
    logger.debug(f"Reading binary file: {file_path}")

    try:
        async with aiofiles.open(file_path, "rb") as f:
            content = await f.read()

        return content

    except Exception as e:
        logger.error(f"Error reading binary file {file_path}: {e}")
        raise


# ============================================================================
# FILE MANAGEMENT
# ============================================================================

def ensure_dir(directory: Path) -> Path:
    """
    Створює директорію якщо вона не існує

    Args:
        directory: Path до директорії

    Returns:
        Path до директорії
    """
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def get_file_size(file_path: Path) -> int:
    """
    Повертає розмір файлу в bytes

    Args:
        file_path: Path до файлу

    Returns:
        Розмір файлу в bytes
    """
    return file_path.stat().st_size


def format_file_size(size_bytes: int) -> str:
    """
    Форматує розмір файлу в читабельний вигляд

    Args:
        size_bytes: Розмір в bytes

    Returns:
        Форматований рядок (наприклад, "1.5 MB")
    """
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} TB"


async def cleanup_directory(
    directory: Path,
    pattern: str = "*",
    keep_last_n: Optional[int] = None
) -> int:
    """
    Очищає директорію (видаляє файли)

    Args:
        directory: Директорія для очищення
        pattern: Glob pattern (наприклад, "*.tmp")
        keep_last_n: Залишити останні N файлів (за датою модифікації)

    Returns:
        Кількість видалених файлів
    """
    import asyncio

    if not directory.exists():
        return 0

    files = sorted(
        directory.glob(pattern),
        key=lambda f: f.stat().st_mtime,
        reverse=True
    )

    if keep_last_n is not None:
        files_to_delete = files[keep_last_n:]
    else:
        files_to_delete = files

    deleted_count = 0

    for file in files_to_delete:
        try:
            file.unlink()
            deleted_count += 1
            logger.debug(f"Deleted file: {file}")
        except Exception as e:
            logger.warning(f"Could not delete {file}: {e}")

    if deleted_count > 0:
        logger.info(f"Cleaned up {deleted_count} files from {directory}")

    return deleted_count


# ============================================================================
# PROJECT-SPECIFIC HELPERS
# ============================================================================

def get_scene_images_dir(project_id: str, scene_number: int) -> Path:
    """Повертає директорію для зображень сцени"""
    scene_dir = settings.get_scene_dir(project_id, scene_number)
    images_dir = scene_dir / "images"
    return ensure_dir(images_dir)


def get_scene_video_path(
    project_id: str,
    scene_number: int,
    video_type: str = "raw"
) -> Path:
    """
    Повертає шлях до відео файлу сцени

    Args:
        project_id: ID проєкту
        scene_number: Номер сцени
        video_type: raw | upscaled

    Returns:
        Path до відео файлу
    """
    scene_dir = settings.get_scene_dir(project_id, scene_number)

    if video_type == "raw":
        return scene_dir / "raw_video.mp4"
    elif video_type == "upscaled":
        return scene_dir / "upscaled.mp4"
    else:
        raise ValueError(f"Unknown video_type: {video_type}")


def get_final_video_path(project_id: str) -> Path:
    """Повертає шлях до фінального відео"""
    final_dir = settings.get_project_dir(project_id) / "final"
    ensure_dir(final_dir)
    return final_dir / "merged_video.mp4"


# ============================================================================
# EXPORT
# ============================================================================

__all__ = [
    "download_file",
    "download_multiple_files",
    "save_text_file",
    "save_binary_file",
    "save_json",
    "read_text_file",
    "read_binary_file",
    "ensure_dir",
    "get_file_size",
    "format_file_size",
    "cleanup_directory",
    "get_scene_images_dir",
    "get_scene_video_path",
    "get_final_video_path",
]
