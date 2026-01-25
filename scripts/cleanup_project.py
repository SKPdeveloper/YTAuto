#!/usr/bin/env python3
"""
Manual Project Cleanup Script

Run cleanup on existing projects that were completed before CleanupStage was added.

Usage:
    python scripts/cleanup_project.py proj_xxx
    python scripts/cleanup_project.py proj_xxx proj_yyy proj_zzz
    python scripts/cleanup_project.py --all

Options:
    --all       Cleanup all projects in projects/ directory
    --dry-run   Show what would be deleted without actually deleting
    --no-sfx    Skip SFX import to library
"""

import sys
import asyncio
import argparse
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from app.pipeline.cleanup_stage import CleanupStage
from app.services.sfx_library import get_sfx_library
from app.core.config import settings


class MockProject:
    """Mock project data for running cleanup on existing projects"""
    def __init__(self, project_id: str, project_dir: Path):
        self.project_id = project_id
        self.project_dir = str(project_dir)
        self.scenes = []


class MockNotifier:
    """Mock notifier that just logs"""
    async def send_stage_changed(self, **kwargs):
        pass

    async def send_stage_completed(self, **kwargs):
        pass

    async def send_error(self, **kwargs):
        pass

    async def send_progress(self, **kwargs):
        pass

    async def send_log(self, **kwargs):
        pass

    async def push_success(self, **kwargs):
        logger.success(f"[PUSH] {kwargs.get('title')}: {kwargs.get('message')}")

    async def push_error(self, **kwargs):
        logger.error(f"[PUSH] {kwargs.get('title')}: {kwargs.get('message')}")

    async def push_info(self, **kwargs):
        logger.info(f"[PUSH] {kwargs.get('title')}: {kwargs.get('message')}")


async def cleanup_project(project_id: str, dry_run: bool = False, skip_sfx: bool = False) -> bool:
    """
    Run cleanup on a single project.

    Args:
        project_id: Project ID to cleanup
        dry_run: If True, only show what would be deleted
        skip_sfx: If True, skip SFX import

    Returns:
        True if successful
    """
    projects_dir = Path(settings.PROJECTS_DIR)
    project_dir = projects_dir / project_id

    if not project_dir.exists():
        logger.error(f"Project not found: {project_id}")
        return False

    # Check if project has final video (is complete)
    final_video = project_dir / "final_video.mp4"
    upscaled_4k = list((project_dir / "upscaled").glob("*4k*.mp4")) if (project_dir / "upscaled").exists() else []

    if not final_video.exists() and not upscaled_4k:
        logger.warning(f"[{project_id}] No final video found - project may not be complete")
        return False

    # Check if already cleaned
    scene_folders = [d for d in project_dir.iterdir() if d.is_dir() and d.name.startswith("scene_")]
    if not scene_folders:
        logger.info(f"[{project_id}] Already cleaned (no scene folders)")
        return True

    if dry_run:
        logger.info(f"\n{'='*60}")
        logger.info(f"[DRY RUN] Project: {project_id}")
        logger.info(f"{'='*60}")

        # Show what would be deleted
        await show_dry_run(project_dir, skip_sfx)
        return True

    # Create mock project and notifier
    mock_project = MockProject(project_id, project_dir)
    mock_notifier = MockNotifier()

    # Create and run cleanup stage
    stage = CleanupStage(mock_project, notifier=mock_notifier)

    # Override SFX import if requested
    if skip_sfx:
        async def skip_import(*args, **kwargs):
            return 0
        stage._import_sfx_to_library = skip_import

    result = await stage.run()

    if result.success:
        logger.success(f"[{project_id}] Cleanup complete!")
        return True
    else:
        logger.error(f"[{project_id}] Cleanup failed: {result.message}")
        return False


async def show_dry_run(project_dir: Path, skip_sfx: bool) -> None:
    """Show what would be deleted in dry run mode"""

    # Scene directories
    scene_dirs = [d for d in project_dir.iterdir() if d.is_dir() and d.name.startswith("scene_")]
    if scene_dirs:
        logger.info("\n[DELETE] Scene directories:")
        for d in scene_dirs:
            size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
            logger.info(f"  - {d.name}/ ({size / 1024 / 1024:.1f} MB)")

    # Intermediate files
    delete_patterns = [
        "processed_scene_*.mp4", "effects_scene_*.mp4",
        "hook.mp4", "concatenated.mp4", "global_effects.mp4", "subtitled.mp4",
        "vo_segment_*.mp3", "music.mp3", "ambient.mp3", "voiceover.mp3",
        "concat_list.txt", "vo_concat_list.txt", "nul"
    ]

    logger.info("\n[DELETE] Intermediate files:")
    for pattern in delete_patterns:
        for f in project_dir.glob(pattern):
            size = f.stat().st_size / 1024 / 1024
            logger.info(f"  - {f.name} ({size:.1f} MB)")

    # gen3a_work videos
    gen3a_dir = project_dir / "gen3a_work"
    if gen3a_dir.exists():
        logger.info("\n[DELETE] gen3a_work videos:")
        for f in gen3a_dir.glob("*.mp4"):
            size = f.stat().st_size / 1024 / 1024
            logger.info(f"  - gen3a_work/{f.name} ({size:.1f} MB)")

    # upscaled 60fps
    upscaled_dir = project_dir / "upscaled"
    if upscaled_dir.exists():
        logger.info("\n[DELETE] Upscaled intermediate:")
        for f in upscaled_dir.glob("*60fps*.mp4"):
            size = f.stat().st_size / 1024 / 1024
            logger.info(f"  - upscaled/{f.name} ({size:.1f} MB)")

    # SFX
    sfx_dir = project_dir / "sfx"
    if sfx_dir.exists() and not skip_sfx:
        logger.info("\n[IMPORT] SFX to library:")
        for f in sfx_dir.glob("*.mp3"):
            logger.info(f"  - {f.name}")

    # Files to keep
    keep_files = [
        "project_brief.json", "manifest.json", "final_video.mp4",
        "thumbnail.png", "voiceover_timing.json", "subtitles.ass",
        "gen3a_analysis.json", "gen3b_raw_response.json"
    ]

    logger.info("\n[KEEP] Files:")
    for name in keep_files:
        f = project_dir / name
        if f.exists():
            size = f.stat().st_size / 1024
            logger.info(f"  - {name} ({size:.1f} KB)")

    # Keep upscaled 4K
    if upscaled_dir.exists():
        for f in upscaled_dir.glob("*4k*.mp4"):
            size = f.stat().st_size / 1024 / 1024
            logger.info(f"  - upscaled/{f.name} ({size:.1f} MB)")

    # Keep gen3a_work JSONs
    if gen3a_dir.exists():
        for f in gen3a_dir.glob("*.json"):
            size = f.stat().st_size / 1024
            logger.info(f"  - gen3a_work/{f.name} ({size:.1f} KB)")


async def cleanup_all(dry_run: bool = False, skip_sfx: bool = False) -> None:
    """Cleanup all projects"""
    projects_dir = Path(settings.PROJECTS_DIR)

    if not projects_dir.exists():
        logger.error(f"Projects directory not found: {projects_dir}")
        return

    project_dirs = [d for d in projects_dir.iterdir() if d.is_dir() and d.name.startswith("proj_")]

    logger.info(f"Found {len(project_dirs)} projects")

    success_count = 0
    for project_dir in project_dirs:
        project_id = project_dir.name
        if await cleanup_project(project_id, dry_run, skip_sfx):
            success_count += 1

    logger.info(f"\nCompleted: {success_count}/{len(project_dirs)} projects cleaned")


def main():
    parser = argparse.ArgumentParser(
        description="Cleanup project directories after pipeline completion"
    )
    parser.add_argument(
        "projects",
        nargs="*",
        help="Project IDs to cleanup (e.g., proj_xxx proj_yyy)"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Cleanup all projects in projects/ directory"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting"
    )
    parser.add_argument(
        "--no-sfx",
        action="store_true",
        help="Skip SFX import to library"
    )

    args = parser.parse_args()

    if not args.projects and not args.all:
        parser.print_help()
        sys.exit(1)

    # Configure logger
    logger.remove()
    logger.add(
        sys.stderr,
        format="<level>{level: <8}</level> | {message}",
        level="INFO"
    )

    if args.all:
        asyncio.run(cleanup_all(args.dry_run, args.no_sfx))
    else:
        for project_id in args.projects:
            asyncio.run(cleanup_project(project_id, args.dry_run, args.no_sfx))


if __name__ == "__main__":
    main()
