"""
Channel Service - Business logic for channels and projects.
Bridges Web UI with existing Orchestrator.
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
    """

    def __init__(self):
        self.active_tasks: Dict[int, asyncio.Task] = {}

    async def start_project_pipeline(
        self,
        web_project_id: int,
        channel_folder: str,
        topic: str,
        selected_script: str,
        format: str,
        duration_seconds: int,
        engine: str,
    ) -> bool:
        """
        Start the project pipeline in background.

        This bridges the Web UI project with the existing orchestrator:
        1. Creates an orchestrator project
        2. Starts the pipeline
        3. Syncs status back to web database

        Args:
            web_project_id: ID in web_projects table
            channel_folder: Path to channel folder
            topic: Video topic
            selected_script: The chosen script
            format: Video format (9:16, 1:1, 16:9)
            duration_seconds: Video duration
            engine: Generation engine (higgsfield, comfyui)

        Returns:
            True if started successfully
        """
        try:
            await add_log(web_project_id, "Starting project pipeline...", "info")

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

            # Calculate number of scenes from duration
            num_scenes = max(3, duration_seconds // 5)
            await add_log(
                web_project_id,
                f"Project will have {num_scenes} scenes (based on {duration_seconds}s duration)",
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
    ):
        """
        Run the actual pipeline (background task).

        This method syncs status from orchestrator back to web database.
        """
        orchestrator_project_id = None

        try:
            await update_project_status(web_project_id, "generating", progress=10)
            await add_log(web_project_id, "Creating orchestrator project...", "info")

            # Create project in orchestrator
            # Note: This uses the existing orchestrator's create_project method
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
                f"Orchestrator project created: {orchestrator_project_id}",
                "success"
            )

            # Store mapping for status sync
            self._store_project_mapping(web_project_id, orchestrator_project_id)

            # Start the pipeline
            await update_project_status(web_project_id, "generating", progress=20)
            await add_log(web_project_id, "Starting scene generation...", "info")

            # Start status sync task
            sync_task = asyncio.create_task(
                self._sync_status_loop(web_project_id, orchestrator_project_id)
            )

            try:
                # Run the pipeline
                result = await orchestrator.start_pipeline(orchestrator_project_id)

                if result:
                    await add_log(web_project_id, "Pipeline completed successfully!", "success")
                    await update_project_status(web_project_id, "reviewing", progress=80)
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
            await add_log(web_project_id, f"Pipeline error: {str(e)}", "error")
            await update_project_status(web_project_id, "failed")
        finally:
            # Cleanup
            if web_project_id in self.active_tasks:
                del self.active_tasks[web_project_id]

    def _store_project_mapping(self, web_project_id: int, orchestrator_project_id: str):
        """Store mapping between web and orchestrator project IDs."""
        if not hasattr(self, '_project_mappings'):
            self._project_mappings = {}
        self._project_mappings[web_project_id] = orchestrator_project_id

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

            # Update each scene
            for scene_data in project_data.scenes:
                matching = [s for s in web_scenes if s['scene_number'] == scene_data.scene_number]
                if matching:
                    web_scene = matching[0]
                    await update_scene_status(
                        scene_id=web_scene['id'],
                        status=scene_data.status.value,
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
