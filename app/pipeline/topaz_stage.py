"""
Topaz Upscale Stage — 2-stage Topaz Video AI processing (FPS + 4K).

Pipeline stage between VideoApprovalStage and CleanupStage.
Non-fatal: if Topaz fails or is unavailable, the stage is SKIPPED
and the pipeline continues with the non-upscaled video.
"""

from pathlib import Path
from typing import Optional

from loguru import logger

from app.pipeline.base import BasePipelineStage, StageResult, StageStatus
from app.core.config import settings


class TopazUpscaleStage(BasePipelineStage):
    """
    Stage: Topaz Video AI Upscale (after VideoApproval, before Cleanup)

    Two-stage processing:
    1. FPS Interpolation (→ 60 fps)
    2. 4K Upscaling (→ 2160x3840)

    Non-fatal: failures result in SKIPPED status, pipeline continues.
    """

    name = "topaz_upscale"
    description = "Topaz Video AI upscaling (FPS + 4K)"

    # Max wait time for Topaz processing (30 minutes)
    TOPAZ_TIMEOUT = 1800

    async def can_run(self) -> bool:
        """
        Check if Topaz upscale should run.

        Returns False if:
        - User chose skip_upscale
        - Topaz Video AI is not installed
        - final_4k.mp4 already exists
        """
        project_dir = self._get_project_dir()
        project_id = self.project.project_id

        # Check if user chose skip_upscale (stored in stage result data)
        if self._is_skip_upscale():
            logger.warning(f"[{project_id}] Topaz: skipped — user chose skip_upscale")
            return False

        # Check if Topaz is installed
        from app.modules.topaz_config import topaz_config
        if not topaz_config.is_enabled:
            logger.warning(f"[{project_id}] Topaz: skipped — Topaz Video AI not installed")
            return False

        # Check if already upscaled
        final_4k = project_dir / "final_4k.mp4"
        if final_4k.exists() and final_4k.stat().st_size > 0:
            logger.warning(f"[{project_id}] Topaz: skipped — final_4k.mp4 already exists")
            return False

        return True

    async def can_resume(self) -> bool:
        return True

    async def execute(self) -> StageResult:
        """Run Topaz 2-stage upscale pipeline."""
        project_dir = self._get_project_dir()
        project_id = self.project.project_id

        # Find input video
        input_video = self._find_input_video(project_dir)
        if not input_video:
            logger.warning(f"[{project_id}] Topaz: skipped — no input video found")
            return StageResult(
                success=True,
                stage_name=self.name,
                status=StageStatus.SKIPPED,
                message="No input video found for upscaling",
            )

        logger.info(f"[{project_id}] Topaz: starting 2-stage upscale for {input_video.name}")

        try:
            from app.modules.topaz_queue import TopazQueue

            queue = TopazQueue()

            # Start the worker
            await queue.start()

            # Add task for full video (scene_number=0)
            task = await queue.add_task(
                project_id=project_id,
                scene_number=0,  # 0 = final video
                input_path=input_video,
                output_dir=project_dir,
                metadata={"type": "pipeline_upscale"},
            )

            logger.info(f"[{project_id}] Topaz: queue started, waiting for completion (timeout={self.TOPAZ_TIMEOUT}s)")
            await self.notify_progress(10, "Topaz processing started...")

            # Wait for completion
            completed = await queue.wait_for_completion(timeout=self.TOPAZ_TIMEOUT)

            # Stop the worker
            await queue.stop()

            # Check result
            final_4k = project_dir / "final_4k.mp4"
            if completed and final_4k.exists() and final_4k.stat().st_size > 0:
                size_mb = final_4k.stat().st_size / (1024 * 1024)
                logger.success(f"[{project_id}] Topaz: complete → {final_4k.name} ({size_mb:.1f} MB)")

                # Cleanup intermediate 60fps file
                await queue.cleanup_intermediate_files(task)

                await self.notify_progress(100, f"Topaz complete: {final_4k.name}")

                return StageResult(
                    success=True,
                    stage_name=self.name,
                    message=f"Topaz upscale complete: {final_4k.name} ({size_mb:.1f} MB)",
                    data={
                        "output_path": str(final_4k),
                        "size_mb": round(size_mb, 1),
                    },
                )
            else:
                reason = "timed out" if not completed else "output file not created"
                logger.error(f"[{project_id}] Topaz: failed — {reason}")

                # Non-fatal: return SKIPPED so pipeline continues
                return StageResult(
                    success=True,
                    stage_name=self.name,
                    status=StageStatus.SKIPPED,
                    message=f"Topaz upscale failed ({reason}), continuing without 4K",
                )

        except Exception as e:
            logger.error(f"[{project_id}] Topaz: failed — {e}")

            # Non-fatal: return SKIPPED so pipeline continues
            return StageResult(
                success=True,
                stage_name=self.name,
                status=StageStatus.SKIPPED,
                message=f"Topaz upscale failed ({e}), continuing without 4K",
            )

    def _get_project_dir(self) -> Path:
        """Get project directory path."""
        if hasattr(self.project, "project_dir") and self.project.project_dir:
            return Path(self.project.project_dir)
        return Path(settings.PROJECTS_DIR) / self.project.project_id

    def _is_skip_upscale(self) -> bool:
        """Check if user requested skip_upscale via video approval."""
        try:
            from app.api.control_routes import get_control_state
            state = get_control_state()
            return state.video_approval_result == "skip_upscale"
        except Exception:
            return False

    def _find_input_video(self, project_dir: Path) -> Optional[Path]:
        """Find the assembled video to upscale (priority order)."""
        candidates = [
            "final.mp4",
            "final_video.mp4",
            "assembled_video.mp4",
            "final_raw.mp4",
        ]
        for name in candidates:
            path = project_dir / name
            if path.exists() and path.stat().st_size > 0:
                return path
        return None


__all__ = ["TopazUpscaleStage"]
