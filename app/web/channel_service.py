"""
Channel Service - Business logic for channels and projects.
Bridges Web UI with existing Orchestrator.

Updated for new GEN1/GEN2 pipeline with:
- Auto-approve mode support
- New scene statuses (IMAGE_READY, VIDEO_READY, APPROVED)
- Post-processing stages (music, voiceover, assembly, Topaz)
"""

import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

from app.core.config import settings
from app.utils.logger import logger
from app.web.database import (
    get_project,
    update_project_status,
    update_project_stage,
    add_log,
    create_scene,
    update_scene_status,
    get_project_scenes,
)

# Orchestrator singleton (lazy initialization)
_orchestrator_instance = None


def get_orchestrator():
    """Get or create orchestrator singleton."""
    global _orchestrator_instance
    if _orchestrator_instance is None:
        try:
            from app.core.orchestrator import ProjectOrchestrator
            _orchestrator_instance = ProjectOrchestrator()
            logger.info("ProjectOrchestrator initialized for Web UI")
        except Exception as e:
            logger.error(f"Failed to initialize orchestrator: {e}")
            return None
    return _orchestrator_instance


class ChannelService:
    """
    Service layer for channel operations.
    Handles business logic between Web UI and Orchestrator.

    Pipeline Flow:
    1. create_project() - GEN1/GEN2 script generation
    2. start_pipeline() - Scene processing:
       - PRIMARY scene: generate 4 candidates, user selects
       - Remaining scenes: generate with reference, validate
       - Video generation for all scenes
    3. Post-processing:
       - Music generation
       - Voiceover generation
       - Video assembly
       - Topaz FPS/upscaling
    """

    def __init__(self):
        self.active_tasks: Dict[int, asyncio.Task] = {}
        self._project_mappings: Dict[int, str] = {}

    async def start_project_pipeline(
        self,
        web_project_id: int,
        channel_folder: str,
        topic: str,
        selected_script: str,
        format: str,
        duration_seconds: int,
        engine: str,
        auto_approve: bool = False,
    ) -> bool:
        """
        Start the project pipeline in background.

        This bridges the Web UI project with the existing orchestrator:
        1. Creates an orchestrator project (GEN1/GEN2)
        2. Starts the pipeline (scenes, videos)
        3. Runs post-processing (music, voiceover, assembly, Topaz)
        4. Syncs status back to web database

        Args:
            web_project_id: ID in web_projects table
            channel_folder: Path to channel folder
            topic: Video topic
            selected_script: The chosen script (JSON from GEN1)
            format: Video format (9:16, 1:1, 16:9)
            duration_seconds: Video duration
            engine: Generation engine (higgsfield, comfyui)
            auto_approve: If True, automatically approve all scenes

        Returns:
            True if started successfully
        """
        try:
            await add_log(web_project_id, "Starting project pipeline...", "info")

            if auto_approve:
                await add_log(web_project_id, "Auto-approve mode ENABLED", "info")

            # Check engine - only higgsfield is supported now
            if engine != "higgsfield":
                await add_log(
                    web_project_id,
                    f"Engine '{engine}' is not yet supported. Only 'higgsfield' is available.",
                    "error"
                )
                await update_project_status(web_project_id, "failed")
                return False

            # Get orchestrator
            orchestrator = get_orchestrator()
            if not orchestrator:
                await add_log(
                    web_project_id,
                    "Failed to initialize orchestrator. Check API keys in .env",
                    "error"
                )
                await update_project_status(web_project_id, "failed")
                return False

            # Calculate number of scenes from duration (10s per scene)
            num_scenes = max(3, duration_seconds // 10)
            await add_log(
                web_project_id,
                f"Project will have {num_scenes} scenes ({duration_seconds}s / 10s per scene)",
                "info"
            )

            # Create scenes in web database
            for i in range(1, num_scenes + 1):
                await create_scene(web_project_id, i)

            # Start pipeline in background task
            task = asyncio.create_task(
                self._run_pipeline(
                    web_project_id=web_project_id,
                    orchestrator=orchestrator,
                    topic=topic,
                    selected_script=selected_script,
                    num_scenes=num_scenes,
                    auto_approve=auto_approve,
                )
            )
            self.active_tasks[web_project_id] = task

            await add_log(web_project_id, "Pipeline started in background", "success")
            return True

        except Exception as e:
            logger.error(f"Error starting pipeline for project {web_project_id}: {e}")
            await add_log(web_project_id, f"Failed to start pipeline: {str(e)}", "error")
            await update_project_status(web_project_id, "failed")
            return False

    async def _run_pipeline(
        self,
        web_project_id: int,
        orchestrator,
        topic: str,
        selected_script: str,
        num_scenes: int,
        auto_approve: bool = False,
    ):
        """
        Run the actual pipeline (background task).

        Pipeline stages:
        1. SCRIPT_GENERATION - GEN1/GEN2 (already done before this)
        2. PRIMARY_IMAGE - Generate PRIMARY scene image
        3. PRIMARY_VIDEO - Generate PRIMARY scene video
        4. REMAINING_SCENES - Generate images/videos for scenes 2-N
        5. POST_PROCESSING - Music, voiceover, assembly
        6. TOPAZ_FPS - FPS interpolation
        7. TOPAZ_UPSCALE - 4K upscaling

        This method syncs status from orchestrator back to web database.
        """
        orchestrator_project_id = None

        try:
            await update_project_status(web_project_id, "generating", progress=5)
            await update_project_stage(web_project_id, "script_generation")
            await add_log(web_project_id, "Creating orchestrator project...", "info")

            # Create project in orchestrator
            project_data = await orchestrator.create_project(
                topic=topic,
                num_scenes=num_scenes,
                style="cinematic food fantasy",
                target_audience="YouTube Shorts viewers"
            )

            if not project_data:
                await add_log(web_project_id, "Failed to create orchestrator project", "error")
                await update_project_status(web_project_id, "failed")
                return

            orchestrator_project_id = project_data.project_id
            await add_log(
                web_project_id,
                f"Project created: {orchestrator_project_id}",
                "success"
            )
            await add_log(
                web_project_id,
                f"Title: {project_data.title}",
                "info"
            )

            # Store mapping for status sync
            self._project_mappings[web_project_id] = orchestrator_project_id

            # Update web scenes with prompts from orchestrator
            await self._update_scene_prompts(web_project_id, project_data)

            # Start the pipeline
            await update_project_status(web_project_id, "generating", progress=15)
            await update_project_stage(web_project_id, "primary_image")
            await add_log(web_project_id, "Starting scene generation...", "info")

            # Start status sync task
            sync_task = asyncio.create_task(
                self._sync_status_loop(web_project_id, orchestrator_project_id)
            )

            try:
                # Run the pipeline with auto_approve flag
                result = await orchestrator.start_pipeline(
                    orchestrator_project_id,
                    auto_approve=auto_approve
                )

                if result:
                    await add_log(web_project_id, "Pipeline completed successfully!", "success")
                    await update_project_status(web_project_id, "ready", progress=100)
                    await update_project_stage(web_project_id, "completed")
                else:
                    await add_log(web_project_id, "Pipeline completed with errors", "warning")
                    await update_project_status(web_project_id, "failed")
            finally:
                # Stop sync task
                sync_task.cancel()
                try:
                    await sync_task
                except asyncio.CancelledError:
                    pass

            # Final sync
            await self.sync_scene_status(web_project_id, orchestrator_project_id)

        except asyncio.CancelledError:
            await add_log(web_project_id, "Pipeline was cancelled", "warning")
            await update_project_status(web_project_id, "paused")
        except Exception as e:
            logger.error(f"Pipeline error for project {web_project_id}: {e}")
            import traceback
            traceback.print_exc()
            await add_log(web_project_id, f"Pipeline error: {str(e)}", "error")
            await update_project_status(web_project_id, "failed")
        finally:
            # Cleanup
            if web_project_id in self.active_tasks:
                del self.active_tasks[web_project_id]

    async def _update_scene_prompts(self, web_project_id: int, project_data):
        """Update web scenes with prompts from orchestrator project."""
        try:
            web_scenes = await get_project_scenes(web_project_id)
            for scene_data in project_data.scenes:
                matching = [s for s in web_scenes if s['scene_number'] == scene_data.scene_number]
                if matching:
                    web_scene = matching[0]
                    prompt = scene_data.image_prompt or ""
                    await update_scene_status(
                        scene_id=web_scene['id'],
                        status="pending",
                        prompt=prompt[:200] if prompt else None
                    )
        except Exception as e:
            logger.warning(f"Failed to update scene prompts: {e}")

    async def _sync_status_loop(self, web_project_id: int, orchestrator_project_id: str):
        """Periodically sync scene status from orchestrator to web database."""
        try:
            while True:
                await asyncio.sleep(3)  # Sync every 3 seconds
                await self.sync_scene_status(web_project_id, orchestrator_project_id)
        except asyncio.CancelledError:
            pass

    async def pause_project(self, web_project_id: int) -> bool:
        """Pause a running project."""
        try:
            if web_project_id in self.active_tasks:
                task = self.active_tasks[web_project_id]
                task.cancel()
                await add_log(web_project_id, "Project paused by user", "warning")
                return True
            return False
        except Exception as e:
            logger.error(f"Error pausing project {web_project_id}: {e}")
            return False

    async def cancel_project(self, web_project_id: int) -> bool:
        """Cancel a running project."""
        try:
            if web_project_id in self.active_tasks:
                task = self.active_tasks[web_project_id]
                task.cancel()
            await add_log(web_project_id, "Project cancelled by user", "error")
            await update_project_status(web_project_id, "failed")
            return True
        except Exception as e:
            logger.error(f"Error cancelling project {web_project_id}: {e}")
            return False

    async def sync_scene_status(
        self,
        web_project_id: int,
        orchestrator_project_id: str,
    ):
        """
        Sync scene statuses from orchestrator to web database.
        Called periodically to update the web UI.

        Maps orchestrator SceneStatus to web UI status:
        - PENDING -> pending
        - IMAGE_READY -> image_ready
        - VIDEO_READY -> video_ready
        - APPROVED -> approved
        - AWAITING_APPROVAL -> awaiting_approval
        """
        try:
            orchestrator = get_orchestrator()
            if not orchestrator:
                return

            # Get orchestrator project data
            project_data = orchestrator.active_projects.get(orchestrator_project_id)
            if not project_data:
                return

            # Get web scenes
            web_scenes = await get_project_scenes(web_project_id)

            # Calculate progress based on scenes
            total_scenes = len(project_data.scenes)
            completed = sum(1 for s in project_data.scenes if s.status.value in ['approved', 'video_ready'])
            progress = int(15 + (completed / total_scenes * 70)) if total_scenes > 0 else 15

            # Update project progress
            await update_project_status(web_project_id, "generating", progress=progress)

            # Update project stage based on orchestrator stage
            if hasattr(project_data, 'stage') and project_data.stage:
                stage_value = project_data.stage.value if hasattr(project_data.stage, 'value') else str(project_data.stage)
                await update_project_stage(web_project_id, stage_value)

            # Update each scene
            for scene_data in project_data.scenes:
                matching = [s for s in web_scenes if s['scene_number'] == scene_data.scene_number]
                if matching:
                    web_scene = matching[0]

                    # Map status
                    status = scene_data.status.value if hasattr(scene_data.status, 'value') else str(scene_data.status)

                    await update_scene_status(
                        scene_id=web_scene['id'],
                        status=status,
                        image_path=str(scene_data.image_path) if scene_data.image_path else None,
                        video_path=str(scene_data.video_path) if scene_data.video_path else None,
                        upscaled_path=str(scene_data.upscaled_path) if scene_data.upscaled_path else None,
                    )

        except Exception as e:
            logger.error(f"Error syncing scene status: {e}")


# Singleton service instance
_channel_service: Optional[ChannelService] = None


def get_channel_service() -> ChannelService:
    """Get or create channel service singleton."""
    global _channel_service
    if _channel_service is None:
        _channel_service = ChannelService()
    return _channel_service
