"""
Cleanup Stage - Post-pipeline project cleanup

Final stage that runs after Topaz/Upscale to:
1. Import SFX into global library with metadata
2. Remove intermediate/temporary files
3. Keep only files needed for YouTube upload

Files KEPT after cleanup:
    - project_brief.json     (YouTube metadata)
    - manifest.json          (video structure)
    - upscaled/scene_0_4k.mp4 (4K video for YouTube)
    - final_video.mp4        (1080p preview)
    - thumbnail.png          (YouTube thumbnail)
    - voiceover_timing.json  (subtitle timing)
    - subtitles.ass          (subtitle file)
    - gen3a_analysis.json    (analysis data)
    - gen3b_raw_response.json (GEN3b response)
    - gen3a_work/*.json      (work JSONs - beats, timing, levels)

Files DELETED:
    - gen3a_work/*.mp4       (raw Kling videos)
    - scene_*/               (all scene folders)
    - processed_scene_*.mp4  (intermediate renders)
    - effects_scene_*.mp4    (intermediate renders)
    - hook.mp4               (intermediate)
    - concatenated.mp4       (intermediate)
    - global_effects.mp4     (intermediate)
    - subtitled.mp4          (intermediate)
    - upscaled/scene_0_60fps.mp4 (intermediate 60fps)
    - vo_segment_*.mp3       (voice segments)
    - music.mp3, ambient.mp3, voiceover.mp3 (already in final)
    - concat_list.txt, nul   (technical files)

SFX files are MOVED to assets/sfx/ library (not deleted).
"""

import json
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any

from loguru import logger

from app.pipeline.base import BasePipelineStage, StageResult, StageStatus
from app.api.schemas import ProjectData
from app.services.sfx_library import get_sfx_library
from app.core.config import settings


class CleanupStage(BasePipelineStage):
    """
    Stage 9: Project Cleanup

    Cleans up project directory after successful render:
    1. Imports SFX to global library
    2. Removes intermediate files
    3. Keeps only YouTube-ready files

    Runs after PostProcessStage (and Topaz if enabled).
    """

    name = "cleanup"
    description = "Import SFX to library and cleanup intermediate files"

    # Files to KEEP (relative to project_dir)
    KEEP_FILES = [
        "project_brief.json",
        "manifest.json",
        "final_video.mp4",
        "thumbnail.png",
        "voiceover_timing.json",
        "subtitles.ass",
        "gen3a_analysis.json",
        "gen3b_raw_response.json",
    ]

    # Directories to KEEP (relative to project_dir)
    KEEP_DIRS = [
        "upscaled",  # Contains 4K video
    ]

    # Files in gen3a_work to KEEP (JSONs only)
    KEEP_GEN3A_WORK_PATTERNS = [
        "*.json",  # beats.json, vo_timing.json, audio_levels.json
    ]

    # Patterns to DELETE
    DELETE_PATTERNS = [
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
    ]

    # Directories to DELETE completely
    DELETE_DIRS = [
        "scene_1", "scene_2", "scene_3", "scene_4", "scene_5", "scene_6",
    ]

    # Files in gen3a_work to DELETE
    DELETE_GEN3A_WORK_PATTERNS = [
        "*.mp4",  # Raw Kling videos
    ]

    # Files in upscaled to DELETE
    DELETE_UPSCALED_PATTERNS = [
        "*60fps*.mp4",  # Intermediate 60fps version
    ]

    async def can_run(self) -> bool:
        """Check if cleanup should run"""
        project_dir = self._get_project_dir()

        # Must have final video (either 1080p or 4K)
        final_exists = (project_dir / "final_video.mp4").exists()
        upscaled_exists = any((project_dir / "upscaled").glob("*4k*.mp4"))

        # Don't run if already cleaned (check for scene folders)
        scene_folders_exist = any(
            (project_dir / f"scene_{i}").exists()
            for i in range(1, 7)
        )

        # Run if we have final video AND scene folders still exist
        return (final_exists or upscaled_exists) and scene_folders_exist

    async def can_resume(self) -> bool:
        """Cleanup can always be resumed"""
        return True

    async def execute(self) -> StageResult:
        """Execute cleanup"""

        await self.notify_progress(0, "Starting project cleanup...")

        project_dir = self._get_project_dir()

        try:
            # Step 1: Import SFX to library
            await self.notify_progress(10, "Importing SFX to library...")
            sfx_imported = await self._import_sfx_to_library(project_dir)

            # Step 2: Delete intermediate files
            await self.notify_progress(40, "Removing intermediate files...")
            files_deleted = await self._delete_intermediate_files(project_dir)

            # Step 3: Delete scene directories
            await self.notify_progress(60, "Removing scene directories...")
            dirs_deleted = await self._delete_scene_directories(project_dir)

            # Step 4: Cleanup gen3a_work (keep JSONs, delete videos)
            await self.notify_progress(80, "Cleaning gen3a_work directory...")
            gen3a_cleaned = await self._cleanup_gen3a_work(project_dir)

            # Step 5: Cleanup upscaled directory (keep 4K, delete 60fps)
            await self.notify_progress(90, "Cleaning upscaled directory...")
            upscaled_cleaned = await self._cleanup_upscaled(project_dir)

            # Calculate space saved
            space_saved_mb = self._calculate_space_saved(
                files_deleted, dirs_deleted, gen3a_cleaned, upscaled_cleaned
            )

            await self.notify_progress(100, "Cleanup complete!")

            # Build result message
            result_msg = (
                f"Cleanup complete: {sfx_imported} SFX imported, "
                f"{files_deleted} files deleted, {dirs_deleted} dirs removed, "
                f"~{space_saved_mb:.0f} MB freed"
            )

            logger.success(f"[{self.project_id}] {result_msg}")

            # PUSH notification
            await self.notifier.push_success(
                title="Project Cleaned",
                message=f"Freed ~{space_saved_mb:.0f} MB, imported {sfx_imported} SFX",
                project_id=self.project_id
            )

            return StageResult(
                success=True,
                stage_name=self.name,
                message=result_msg,
                data={
                    "sfx_imported": sfx_imported,
                    "files_deleted": files_deleted,
                    "dirs_deleted": dirs_deleted,
                    "space_saved_mb": space_saved_mb,
                }
            )

        except Exception as e:
            logger.error(f"[{self.project_id}] Cleanup failed: {e}")

            return StageResult(
                success=False,
                stage_name=self.name,
                status=StageStatus.FAILED,
                message=str(e),
                error=e
            )

    def _get_project_dir(self) -> Path:
        """Get project directory path"""
        if hasattr(self.project, 'project_dir') and self.project.project_dir:
            return Path(self.project.project_dir)
        return Path(settings.PROJECTS_DIR) / self.project_id

    async def _import_sfx_to_library(self, project_dir: Path) -> int:
        """Import SFX files to global library"""
        sfx_dir = project_dir / "sfx"
        if not sfx_dir.exists():
            logger.info(f"[{self.project_id}] No SFX directory to import")
            return 0

        # Load project brief for descriptions
        project_brief = None
        brief_path = project_dir / "project_brief.json"
        if brief_path.exists():
            with open(brief_path, "r", encoding="utf-8") as f:
                project_brief = json.load(f)

        # Import to library
        library = get_sfx_library()
        imported = await library.import_from_project(
            project_dir=project_dir,
            project_id=self.project_id,
            project_brief=project_brief
        )

        # After import, delete the sfx directory
        if imported:
            try:
                shutil.rmtree(sfx_dir)
                logger.info(f"[{self.project_id}] Removed sfx/ after import")
            except Exception as e:
                logger.warning(f"[{self.project_id}] Failed to remove sfx/: {e}")

        return len(imported)

    async def _delete_intermediate_files(self, project_dir: Path) -> int:
        """Delete intermediate files matching patterns"""
        deleted_count = 0

        for pattern in self.DELETE_PATTERNS:
            for file_path in project_dir.glob(pattern):
                try:
                    file_path.unlink()
                    deleted_count += 1
                    logger.debug(f"[{self.project_id}] Deleted: {file_path.name}")
                except Exception as e:
                    logger.warning(f"[{self.project_id}] Failed to delete {file_path}: {e}")

        return deleted_count

    async def _delete_scene_directories(self, project_dir: Path) -> int:
        """Delete scene directories"""
        deleted_count = 0

        for dir_name in self.DELETE_DIRS:
            dir_path = project_dir / dir_name
            if dir_path.exists() and dir_path.is_dir():
                try:
                    shutil.rmtree(dir_path)
                    deleted_count += 1
                    logger.debug(f"[{self.project_id}] Removed: {dir_name}/")
                except Exception as e:
                    logger.warning(f"[{self.project_id}] Failed to remove {dir_name}/: {e}")

        return deleted_count

    async def _cleanup_gen3a_work(self, project_dir: Path) -> int:
        """Cleanup gen3a_work - keep JSONs, delete videos"""
        gen3a_dir = project_dir / "gen3a_work"
        if not gen3a_dir.exists():
            return 0

        deleted_count = 0

        for pattern in self.DELETE_GEN3A_WORK_PATTERNS:
            for file_path in gen3a_dir.glob(pattern):
                try:
                    file_path.unlink()
                    deleted_count += 1
                    logger.debug(f"[{self.project_id}] Deleted: gen3a_work/{file_path.name}")
                except Exception as e:
                    logger.warning(f"[{self.project_id}] Failed to delete {file_path}: {e}")

        return deleted_count

    async def _cleanup_upscaled(self, project_dir: Path) -> int:
        """Cleanup upscaled directory - keep 4K, delete 60fps intermediate"""
        upscaled_dir = project_dir / "upscaled"
        if not upscaled_dir.exists():
            return 0

        deleted_count = 0

        for pattern in self.DELETE_UPSCALED_PATTERNS:
            for file_path in upscaled_dir.glob(pattern):
                try:
                    file_path.unlink()
                    deleted_count += 1
                    logger.debug(f"[{self.project_id}] Deleted: upscaled/{file_path.name}")
                except Exception as e:
                    logger.warning(f"[{self.project_id}] Failed to delete {file_path}: {e}")

        return deleted_count

    def _calculate_space_saved(
        self,
        files_deleted: int,
        dirs_deleted: int,
        gen3a_cleaned: int,
        upscaled_cleaned: int
    ) -> float:
        """Estimate space saved in MB"""
        # Rough estimates based on typical file sizes
        # Scene dirs: ~50MB each (images + video)
        # Intermediate mp4s: ~5MB each
        # gen3a_work videos: ~25MB each
        # 60fps intermediate: ~188MB

        space_mb = 0.0
        space_mb += dirs_deleted * 50  # Scene directories
        space_mb += files_deleted * 5   # Various intermediate files
        space_mb += gen3a_cleaned * 25  # gen3a_work videos
        space_mb += upscaled_cleaned * 188  # 60fps intermediate

        return space_mb


__all__ = ["CleanupStage"]
