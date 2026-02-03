"""
Pipeline Orchestrator

Thin coordinator that runs pipeline stages in sequence.
Handles state management, error recovery, and notifications.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime

from loguru import logger

from app.pipeline.base import BasePipelineStage, StageResult, StageStatus
from app.pipeline.project import ProjectManager, get_project_manager
from app.pipeline.script_stage import ScriptStage
from app.pipeline.image_stage import ImageStage
from app.pipeline.validation_stage import ValidationStage
from app.pipeline.video_stage import VideoStage
from app.pipeline.audio_stage import AudioStage
from app.pipeline.gen3_stages import Gen3aStage, Gen3bStage
from app.pipeline.postprocess_stage import PostProcessStage
from app.pipeline.video_approval_stage import VideoApprovalStage
from app.pipeline.cleanup_stage import CleanupStage
from app.pipeline.publish_stage import PublishStage
from app.api.schemas import ProjectData, ProjectStatus, PipelineStage
from app.server.notifications import NotificationService, get_notification_service


class PipelineOrchestrator:
    """
    Orchestrates the video generation pipeline.

    Pipeline stages (in order):
    1. ScriptStage - Generate script via GEN1 + GEN2
    2. ImageStage - Generate images (PRIMARY + remaining)
    3. ValidationStage - Validate images via VAL_IMG
    4. VideoStage - Generate videos for all scenes
    5. AudioStage - Generate voiceover, music, ambient (BEFORE GEN3a!)
    6. Gen3aStage - Video analysis with audio preprocessing
    7. Gen3bStage - Manifest generation
    8. PostProcessStage - FFmpeg rendering, assembly
    9. VideoApprovalStage - User approval before upscaling (web interface)
    10. CleanupStage - Topaz upscale, import SFX, cleanup
    11. PublishStage - Upload to YouTube (якщо target_channel вказано)

    Each stage is independent and can be resumed after failure.

    Usage:
        orchestrator = PipelineOrchestrator()

        # Create and run new project
        project = await orchestrator.create_project("Chocolate Castle")
        await orchestrator.run(project.project_id)

        # Resume failed project
        await orchestrator.resume(project_id)
    """

    # Stage classes in execution order
    STAGES = [
        ScriptStage,
        ImageStage,
        ValidationStage,
        VideoStage,
        AudioStage,         # Generate audio BEFORE GEN3a analysis
        Gen3aStage,         # Video analysis (uses audio for beat sync)
        Gen3bStage,         # Manifest generation
        PostProcessStage,   # FFmpeg rendering, assembly
        VideoApprovalStage, # User approval before upscaling
        CleanupStage,       # Topaz upscale, import SFX, cleanup
        PublishStage,       # Upload to YouTube (if target_channel configured)
    ]

    def __init__(self, notifier: Optional[NotificationService] = None):
        """
        Initialize orchestrator.

        Args:
            notifier: WebSocket notification service
        """
        self.manager = get_project_manager()
        self.notifier = notifier or get_notification_service()
        self._current_project: Optional[ProjectData] = None
        self._current_stage: Optional[BasePipelineStage] = None

    async def create_project(
        self,
        topic: str,
        num_scenes: int = 6,
        style: str = "cinematic food fantasy",
        target_audience: str = "YouTube Shorts viewers"
    ) -> ProjectData:
        """
        Create a new project.

        Args:
            topic: Video topic (or "FREE_TOPIC" for AI choice)
            num_scenes: Number of scenes (always 6)
            style: Video style
            target_audience: Target audience

        Returns:
            Created ProjectData
        """
        project = await self.manager.create(
            topic=topic,
            num_scenes=num_scenes,
            style=style,
            target_audience=target_audience
        )

        # Notify clients
        await self.notifier.send_project_created(
            project_id=project.project_id,
            topic=topic
        )

        return project

    async def run(self, project_id: str) -> bool:
        """
        Run the full pipeline for a project.

        Args:
            project_id: Project ID to run

        Returns:
            True if pipeline completed successfully
        """
        # Load project
        project = await self.manager.load(project_id)
        if not project:
            logger.error(f"Project not found: {project_id}")
            return False

        self._current_project = project

        logger.info(f"[{project_id}] Starting pipeline...")
        logger.info(f"  Topic: {project.topic}")
        logger.info(f"  Scenes: {project.num_scenes}")

        # Update status
        await self.manager.update_status(project, ProjectStatus.GENERATING_SCRIPT)

        # Notify clients
        await self.notifier.send_pipeline_started(
            project_id=project_id,
            total_stages=len(self.STAGES)
        )

        # Run stages
        for stage_class in self.STAGES:
            stage = stage_class(project, notifier=self.notifier)
            self._current_stage = stage

            logger.info(f"[{project_id}] Stage: {stage.name}")

            result = await stage.run()

            if not result.success and result.status != StageStatus.SKIPPED:
                # Stage failed
                await self.manager.handle_error(
                    project=project,
                    stage=stage.name,
                    error=result.error or Exception(result.message),
                    is_resumable=await stage.can_resume()
                )

                logger.error(f"[{project_id}] Pipeline failed at {stage.name}")
                return False

            # Stage succeeded
            await self.manager.mark_stage_complete(project, stage.name)

        # Pipeline completed
        await self.manager.update_status(project, ProjectStatus.COMPLETED)

        logger.success(f"[{project_id}] Pipeline completed!")

        # Notify clients
        await self.notifier.send_pipeline_completed(project_id=project_id)

        return True

    async def resume(self, project_id: str) -> bool:
        """
        Resume a paused/failed project.

        Loads project state and continues from last successful stage.

        Args:
            project_id: Project ID to resume

        Returns:
            True if pipeline completed successfully
        """
        # Try loading from database first, then disk
        project = await self.manager.load(project_id)
        if not project:
            project = await self.manager.load_from_disk(project_id)

        if not project:
            logger.error(f"Cannot resume: project not found: {project_id}")
            return False

        self._current_project = project

        # Determine resume point
        last_stage = project.last_successful_stage
        resume_from_index = 0

        if last_stage:
            for i, stage_class in enumerate(self.STAGES):
                if stage_class(project).name == last_stage:
                    resume_from_index = i + 1
                    break

        logger.info(f"[{project_id}] Resuming from stage index {resume_from_index}")
        logger.info(f"  Last successful: {last_stage or 'None'}")

        # Reset error state
        project.status = ProjectStatus.PROCESSING
        project.error_message = None
        await self.manager.save(project)

        # Notify clients
        await self.notifier.send_pipeline_resumed(
            project_id=project_id,
            resume_stage=self.STAGES[resume_from_index](project).name if resume_from_index < len(self.STAGES) else "complete"
        )

        # Run remaining stages
        for stage_class in self.STAGES[resume_from_index:]:
            stage = stage_class(project, notifier=self.notifier)
            self._current_stage = stage

            logger.info(f"[{project_id}] Stage: {stage.name}")

            result = await stage.run()

            if not result.success and result.status != StageStatus.SKIPPED:
                await self.manager.handle_error(
                    project=project,
                    stage=stage.name,
                    error=result.error or Exception(result.message),
                    is_resumable=await stage.can_resume()
                )
                return False

            await self.manager.mark_stage_complete(project, stage.name)

        # Completed
        await self.manager.update_status(project, ProjectStatus.COMPLETED)
        await self.notifier.send_pipeline_completed(project_id=project_id)

        logger.success(f"[{project_id}] Pipeline completed after resume!")
        return True

    async def run_stage(
        self,
        project_id: str,
        stage_name: str
    ) -> StageResult:
        """
        Run a specific stage manually.

        Useful for retrying a single stage without re-running the whole pipeline.

        Args:
            project_id: Project ID
            stage_name: Name of stage to run

        Returns:
            StageResult
        """
        project = await self.manager.load(project_id)
        if not project:
            return StageResult(
                success=False,
                stage_name=stage_name,
                status=StageStatus.FAILED,
                message="Project not found"
            )

        # Find stage class
        stage_class = None
        for sc in self.STAGES:
            if sc(project).name == stage_name:
                stage_class = sc
                break

        if not stage_class:
            return StageResult(
                success=False,
                stage_name=stage_name,
                status=StageStatus.FAILED,
                message=f"Unknown stage: {stage_name}"
            )

        stage = stage_class(project, notifier=self.notifier)
        return await stage.run()

    async def get_status(self, project_id: str) -> Optional[Dict[str, Any]]:
        """
        Get current project status.

        Returns:
            Status dict with project info and stage states
        """
        project = await self.manager.load(project_id)
        if not project:
            return None

        # Calculate stage states
        stages_status = []
        for stage_class in self.STAGES:
            stage = stage_class(project)
            can_run = await stage.can_run()

            if project.last_successful_stage and stage.name == project.last_successful_stage:
                status = "completed"
            elif self._current_stage and stage.name == self._current_stage.name:
                status = "running"
            elif not can_run:
                status = "pending"
            else:
                status = "ready"

            stages_status.append({
                "name": stage.name,
                "description": stage.description,
                "status": status
            })

        return {
            "project_id": project.project_id,
            "topic": project.topic,
            "title": project.title,
            "status": project.status,
            "current_stage": project.current_stage,
            "last_successful_stage": project.last_successful_stage,
            "error_message": project.error_message,
            "is_resumable": project.is_resumable,
            "scenes_count": len(project.scenes),
            "stages": stages_status,
            "created_at": project.created_at.isoformat() if project.created_at else None,
            "updated_at": project.updated_at.isoformat() if project.updated_at else None,
        }

    def get_current_project(self) -> Optional[ProjectData]:
        """Get currently running project"""
        return self._current_project


# Singleton instance
_orchestrator: Optional[PipelineOrchestrator] = None


def get_orchestrator() -> PipelineOrchestrator:
    """Get the global PipelineOrchestrator instance"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = PipelineOrchestrator()
    return _orchestrator
