"""
Cleanup Stage - Import SFX to global library

Post-pipeline stage that imports project SFX files into the global library.
File deletion is now handled by scripts/publish_archive.py (run after YouTube upload).
"""

import asyncio
import json
import shutil
from pathlib import Path

from loguru import logger

from app.pipeline.base import BasePipelineStage, StageResult, StageStatus
from app.api.schemas import ProjectData
from app.services.sfx_library import get_sfx_library
from app.core.config import settings


class CleanupStage(BasePipelineStage):
    """
    Stage 9: SFX Import

    Imports SFX files from the project into the global library.
    Intermediate file cleanup is deferred to post-publish archiving.
    """

    name = "cleanup"
    description = "Import SFX to global library"

    async def can_run(self) -> bool:
        """Check if SFX directory exists and has files."""
        project_dir = self._get_project_dir()
        sfx_dir = project_dir / "sfx"
        return sfx_dir.exists() and any(sfx_dir.iterdir())

    async def can_resume(self) -> bool:
        return True

    async def execute(self) -> StageResult:
        """Import SFX to global library."""
        await self.notify_progress(0, "Importing SFX to library...")

        project_dir = self._get_project_dir()

        try:
            sfx_imported = await self._import_sfx_to_library(project_dir)

            await self.notify_progress(100, "SFX import complete!")

            result_msg = f"Imported {sfx_imported} SFX files to library"
            logger.success(f"[{self.project_id}] {result_msg}")

            await self.notifier.push_success(
                title="SFX Imported",
                message=f"{sfx_imported} files added to library",
                project_id=self.project_id
            )

            return StageResult(
                success=True,
                stage_name=self.name,
                message=result_msg,
                data={"sfx_imported": sfx_imported}
            )

        except Exception as e:
            logger.error(f"[{self.project_id}] SFX import failed: {e}")

            return StageResult(
                success=False,
                stage_name=self.name,
                status=StageStatus.FAILED,
                message=str(e),
                error=e
            )

    def _get_project_dir(self) -> Path:
        """Get project directory path."""
        if hasattr(self.project, 'project_dir') and self.project.project_dir:
            return Path(self.project.project_dir)
        return Path(settings.PROJECTS_DIR) / self.project_id

    async def _import_sfx_to_library(self, project_dir: Path) -> int:
        """Import SFX files to global library."""
        sfx_dir = project_dir / "sfx"
        if not sfx_dir.exists():
            logger.info(f"[{self.project_id}] No SFX directory to import")
            return 0

        project_brief = None
        brief_path = project_dir / "project_brief.json"
        if brief_path.exists():
            with open(brief_path, "r", encoding="utf-8") as f:
                project_brief = json.load(f)

        library = get_sfx_library()
        imported = await library.import_from_project(
            project_dir=project_dir,
            project_id=self.project_id,
            project_brief=project_brief
        )

        # Remove sfx/ after successful import
        if imported:
            try:
                await asyncio.to_thread(shutil.rmtree, sfx_dir)
                logger.info(f"[{self.project_id}] Removed sfx/ after import")
            except Exception as e:
                logger.warning(f"[{self.project_id}] Failed to remove sfx/: {e}")

        return len(imported)


__all__ = ["CleanupStage"]
