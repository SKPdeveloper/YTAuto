#!/usr/bin/env python3
"""
Post-Publish Archive Script

After uploading to YouTube, run this to:
1. Import SFX to global library
2. Delete intermediate files (keep essentials)
3. Move project to archive/{category}/

Usage:
    python scripts/publish_archive.py proj_xxx
    python scripts/publish_archive.py proj_xxx --category failed
    python scripts/publish_archive.py proj_xxx --dry-run
    python scripts/publish_archive.py --generate-bat-all

Called by:
    - _publish.bat in each project folder (double-click after YouTube upload)
    - POST /api/control/archive-project (UI button)
"""

import sys
import shutil
import asyncio
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

# Files to KEEP after publish cleanup
KEEP_FILES = {
    "project_brief.json",
    "manifest.json",
    "gen3b_manifest.json",
    "final_video.mp4",
    "thumbnail.png",
    "subtitles.ass",
    "voiceover_timing.json",
    "gen3a_analysis.json",
    "gen3b_raw_response.json",
}

# File patterns to DELETE
DELETE_FILE_PATTERNS = [
    "processed_scene_*.mp4",
    "effects_scene_*.mp4",
    "hook.mp4",
    "concatenated.mp4",
    "global_effects.mp4",
    "subtitled.mp4",
    "vo_segment_*.mp3",
    "music.mp3",
    "ambient.mp3",
    "voiceover.mp3",
    "concat_list.txt",
    "vo_concat_list.txt",
    "nul",
    "final_4k.mp4",
    "final_60fps.mp4",
    "final_fixed.mp4",
    "final_with_music.mp4",
    "vo_alignment.json",
    "test_*.mp4",
    "test_*.mp3",
    "YT.txt",
]

# Directories to DELETE completely
DELETE_DIRS = [
    "scene_1", "scene_2", "scene_3", "scene_4", "scene_5", "scene_6",
    "gen3a_work", "music", "sfx", "upscaled", "logs",
]


def cleanup_published_project(project_dir: Path, dry_run: bool = False) -> dict:
    """
    Delete intermediate files from a project, keeping only essentials.

    Returns:
        dict with files_deleted, dirs_deleted, space_freed_mb
    """
    files_deleted = 0
    dirs_deleted = 0
    space_freed = 0

    # Delete known file patterns
    for pattern in DELETE_FILE_PATTERNS:
        for file_path in project_dir.glob(pattern):
            size = file_path.stat().st_size
            if dry_run:
                logger.info(f"  [DEL] {file_path.name} ({size / 1024 / 1024:.1f} MB)")
            else:
                try:
                    file_path.unlink()
                    files_deleted += 1
                    space_freed += size
                except Exception as e:
                    logger.warning(f"  Failed to delete {file_path.name}: {e}")

    # Delete known directories
    for dir_name in DELETE_DIRS:
        dir_path = project_dir / dir_name
        if dir_path.exists() and dir_path.is_dir():
            size = sum(f.stat().st_size for f in dir_path.rglob("*") if f.is_file())
            if dry_run:
                logger.info(f"  [DEL] {dir_name}/ ({size / 1024 / 1024:.1f} MB)")
            else:
                try:
                    shutil.rmtree(dir_path)
                    dirs_deleted += 1
                    space_freed += size
                except Exception as e:
                    logger.warning(f"  Failed to remove {dir_name}/: {e}")

    # Scan for unexpected remaining files (warn but don't delete)
    remaining = []
    for item in project_dir.iterdir():
        if item.is_file() and item.name not in KEEP_FILES:
            # Skip bat files
            if item.suffix == ".bat":
                continue
            remaining.append(item.name)
        elif item.is_dir():
            remaining.append(f"{item.name}/")

    if remaining:
        logger.warning(f"  Unexpected files remaining: {', '.join(remaining)}")

    space_mb = space_freed / (1024 * 1024)

    return {
        "files_deleted": files_deleted,
        "dirs_deleted": dirs_deleted,
        "space_freed_mb": round(space_mb, 1),
    }


def move_to_archive(project_dir: Path, category: str) -> Path:
    """
    Move project directory to archive/{category}/.
    Handles name collisions with timestamp suffix.

    Returns:
        New path in archive.
    """
    from app.core.paths import ARCHIVE_DIR

    archive_category_dir = ARCHIVE_DIR / category
    archive_category_dir.mkdir(parents=True, exist_ok=True)

    dest = archive_category_dir / project_dir.name

    # Handle name collision
    if dest.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = archive_category_dir / f"{project_dir.name}_{timestamp}"

    shutil.move(str(project_dir), str(dest))
    return dest


def archive_project(
    project_id: str,
    category: str = "published",
    dry_run: bool = False,
) -> dict:
    """
    Main entry point: validate, SFX import, cleanup (if published), move to archive.

    Returns:
        Result dict with status, stats, archive_path.
    """
    from app.core.config import settings

    project_dir = Path(settings.PROJECTS_DIR) / project_id

    if not project_dir.exists():
        return {"status": "error", "message": f"Project not found: {project_id}"}

    if category not in ("published", "failed", "test"):
        return {"status": "error", "message": f"Invalid category: {category}"}

    logger.info(f"Archiving {project_id} as {category}...")

    # SFX import (for all categories — we always want to save SFX)
    sfx_imported = 0
    sfx_dir = project_dir / "sfx"
    if sfx_dir.exists() and any(sfx_dir.iterdir()):
        try:
            sfx_imported = _sync_import_sfx(project_dir, project_id)
            logger.info(f"  Imported {sfx_imported} SFX files")
        except Exception as e:
            logger.warning(f"  SFX import failed: {e}")

    # Cleanup intermediates only for published projects
    stats = {"files_deleted": 0, "dirs_deleted": 0, "space_freed_mb": 0.0}
    if category == "published":
        if dry_run:
            logger.info(f"\n[DRY RUN] Files that would be deleted from {project_id}:")
        stats = cleanup_published_project(project_dir, dry_run=dry_run)
        logger.info(
            f"  Cleanup: {stats['files_deleted']} files, "
            f"{stats['dirs_deleted']} dirs, "
            f"{stats['space_freed_mb']} MB freed"
        )

    if dry_run:
        return {
            "status": "dry_run",
            "project_id": project_id,
            "category": category,
            "sfx_imported": sfx_imported,
            **stats,
        }

    # Move to archive
    archive_path = move_to_archive(project_dir, category)
    logger.success(f"  Archived to: {archive_path}")

    # Delete _publish.bat from archive (no longer needed)
    bat_file = archive_path / "_publish.bat"
    if bat_file.exists():
        bat_file.unlink()

    return {
        "status": "ok",
        "project_id": project_id,
        "category": category,
        "sfx_imported": sfx_imported,
        "archive_path": str(archive_path),
        **stats,
    }


def _sync_import_sfx(project_dir: Path, project_id: str) -> int:
    """Synchronous wrapper around async SFX import."""
    import json
    from app.services.sfx_library import get_sfx_library

    project_brief = None
    brief_path = project_dir / "project_brief.json"
    if brief_path.exists():
        with open(brief_path, "r", encoding="utf-8") as f:
            project_brief = json.load(f)

    library = get_sfx_library()

    # Run async import in a fresh event loop
    # This function is always called from a sync context (either CLI or asyncio.to_thread)
    result = asyncio.run(
        library.import_from_project(
            project_dir=project_dir,
            project_id=project_id,
            project_brief=project_brief,
        )
    )

    return len(result)


def generate_bat_file(project_dir: Path) -> Path:
    """
    Write _publish.bat into a project folder.
    Returns path to the generated .bat file.
    """
    bat_content = r'''@echo off
chcp 65001 >nul 2>&1
title YTAuto - Archive Project

echo ================================================
echo   YTAuto - POST-PUBLISH ARCHIVE
echo ================================================
echo.

for %%I in ("%~dp0.") do set "PROJ_NAME=%%~nI"
cd /d "%~dp0..\.."

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH!
    pause
    exit /b 1
)

echo Archiving %PROJ_NAME%...
echo.
python scripts\publish_archive.py %PROJ_NAME% --category published

if errorlevel 1 (
    echo.
    echo [ERROR] Archive failed!
    pause
    exit /b 1
)

echo.
echo [OK] Project archived! Closing in 3 seconds...
timeout /t 3 >nul
'''

    bat_path = project_dir / "_publish.bat"
    bat_path.write_text(bat_content, encoding="utf-8")
    return bat_path


def generate_bat_for_all() -> int:
    """
    Generate _publish.bat in all existing projects that have final_video.mp4.
    Returns count of generated files.
    """
    from app.core.config import settings

    projects_dir = Path(settings.PROJECTS_DIR)
    if not projects_dir.exists():
        logger.error(f"Projects directory not found: {projects_dir}")
        return 0

    count = 0
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        if not project_dir.name.startswith("proj_"):
            continue

        final_video = project_dir / "final_video.mp4"
        if not final_video.exists():
            continue

        bat_path = generate_bat_file(project_dir)
        logger.info(f"  Generated: {bat_path}")
        count += 1

    return count


def main():
    parser = argparse.ArgumentParser(
        description="Archive project after YouTube publish"
    )
    parser.add_argument(
        "project_id",
        nargs="?",
        help="Project ID to archive (e.g., proj_xxx)"
    )
    parser.add_argument(
        "--category",
        choices=["published", "failed", "test"],
        default="published",
        help="Archive category (default: published)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without making changes"
    )
    parser.add_argument(
        "--generate-bat-all",
        action="store_true",
        help="Generate _publish.bat in all existing complete projects"
    )

    args = parser.parse_args()

    # Configure logger
    logger.remove()
    logger.add(
        sys.stderr,
        format="<level>{level: <8}</level> | {message}",
        level="INFO"
    )

    if args.generate_bat_all:
        count = generate_bat_for_all()
        logger.success(f"Generated _publish.bat in {count} projects")
        return

    if not args.project_id:
        parser.print_help()
        sys.exit(1)

    result = archive_project(
        project_id=args.project_id,
        category=args.category,
        dry_run=args.dry_run,
    )

    if result["status"] == "error":
        logger.error(result["message"])
        sys.exit(1)
    elif result["status"] == "dry_run":
        logger.info("\n[DRY RUN] No changes made.")
    else:
        logger.success(
            f"Archived {result['project_id']} -> {result['archive_path']} "
            f"({result['space_freed_mb']} MB freed)"
        )


if __name__ == "__main__":
    main()
