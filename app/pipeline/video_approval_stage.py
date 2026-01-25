"""
Video Approval Stage

Pauses pipeline after video assembly to allow user approval via web interface
before proceeding to Topaz upscaling.
"""

import asyncio
from pathlib import Path
from typing import Optional
from datetime import datetime

from loguru import logger

from app.pipeline.base import BasePipelineStage, StageResult, StageStatus
from app.api.schemas import ProjectData, ProjectStatus
from app.core.paths import get_project_path


class VideoApprovalStage(BasePipelineStage):
    """
    Stage: Video Approval (after PostProcess, before Upscale)

    This stage pauses the pipeline to allow user to review the assembled video
    before it goes to Topaz upscaling (which is expensive and time-consuming).

    User can:
    - Approve: Continue to upscaling
    - Reject: Stop pipeline, fix issues manually
    - Skip Upscale: Mark as complete without upscaling
    """

    name = "video_approval"
    description = "Awaiting approval before upscaling"

    # How long to wait for approval before auto-approving (in seconds)
    # Set to 0 to disable auto-approval
    AUTO_APPROVAL_TIMEOUT = 0  # Disabled by default - wait indefinitely

    async def can_run(self) -> bool:
        """
        Check if video approval stage should run.

        Conditions:
        - PostProcess stage completed
        - Assembled video exists
        - Auto-approve not enabled for this project
        """
        # Check if auto_approve is enabled
        if getattr(self.project, 'auto_approve', False):
            logger.info(f"[{self.name}] Auto-approve enabled, skipping approval stage")
            return False

        # Check if assembled video exists
        project_dir = get_project_path(self.project.project_id)
        assembled_video = project_dir / "assembled_video.mp4"

        if not assembled_video.exists():
            # Try alternative names
            for alt_name in ["final_raw.mp4", "video_assembled.mp4"]:
                alt_path = project_dir / alt_name
                if alt_path.exists():
                    return True

            logger.warning(f"[{self.name}] No assembled video found, skipping approval")
            return False

        return True

    async def can_resume(self) -> bool:
        """Approval stage can always be resumed"""
        return True

    async def execute(self) -> StageResult:
        """Request user approval for assembled video"""

        await self.notify_progress(0, "Preparing video for approval...")

        try:
            # Find the assembled video
            project_dir = get_project_path(self.project.project_id)
            video_path = self._find_assembled_video(project_dir)

            if not video_path:
                return StageResult(
                    success=False,
                    stage_name=self.name,
                    status=StageStatus.FAILED,
                    message="No assembled video found for approval"
                )

            # Get video info
            video_size_mb = video_path.stat().st_size / (1024 * 1024)

            await self.notify_log(f"📹 Відео готове до перегляду: {video_path.name}", "info")
            await self.notify_log(f"📊 Розмір: {video_size_mb:.1f} MB", "info")

            # Send approval request to web clients
            await self.notify_progress(10, "Awaiting approval...")
            await self._request_approval(video_path)

            # Wait for approval
            approval_result = await self._wait_for_approval()

            if approval_result == "approved":
                await self.notify_log("✅ Відео затверджено! Продовжуємо до upscaling...", "success")
                await self.notify_progress(100, "Approved - proceeding to upscale")

                return StageResult(
                    success=True,
                    stage_name=self.name,
                    message="Video approved for upscaling",
                    data={"action": "approved", "video_path": str(video_path)}
                )

            elif approval_result == "skip_upscale":
                await self.notify_log("⏭️ Upscaling пропущено за запитом користувача", "warning")
                await self.notify_progress(100, "Skipping upscale")

                # Copy assembled to final
                final_path = project_dir / "final_video.mp4"
                if not final_path.exists():
                    import shutil
                    shutil.copy2(video_path, final_path)

                return StageResult(
                    success=True,
                    stage_name=self.name,
                    message="Upscaling skipped by user",
                    data={"action": "skip_upscale", "video_path": str(video_path)}
                )

            else:  # rejected
                await self.notify_log("❌ Відео відхилено користувачем", "error")

                return StageResult(
                    success=False,
                    stage_name=self.name,
                    status=StageStatus.FAILED,
                    message="Video rejected by user",
                    data={"action": "rejected"}
                )

        except Exception as e:
            logger.error(f"[{self.name}] Error: {e}")
            return StageResult(
                success=False,
                stage_name=self.name,
                status=StageStatus.FAILED,
                message=str(e),
                error=e
            )

    def _find_assembled_video(self, project_dir: Path) -> Optional[Path]:
        """Find the assembled video file"""
        possible_names = [
            "assembled_video.mp4",
            "final_raw.mp4",
            "video_assembled.mp4",
            "rendered_video.mp4",
        ]

        for name in possible_names:
            path = project_dir / name
            if path.exists():
                return path

        return None

    async def _request_approval(self, video_path: Path) -> None:
        """Send approval request via WebSocket"""

        # Build video URL for web preview
        project_id = self.project.project_id
        video_url = f"/projects/{project_id}/{video_path.name}"

        # Send approval required event
        await self.notifier.send_approval_required(
            project_id=project_id,
            scene_number=0,  # 0 = full video, not a scene
            approval_type="video_pre_upscale",
            video_url=video_url,
            prompt="Review assembled video before upscaling"
        )

        # Also send push notification
        await self.notifier.push_info(
            title="Video Ready for Review",
            message=f"Project {self.project.title or project_id} is ready for approval before upscaling",
            project_id=project_id
        )

        logger.info(f"[{self.name}] Approval request sent for {video_path.name}")

    async def _wait_for_approval(self) -> str:
        """
        Wait for user approval decision.

        Returns:
            "approved" | "rejected" | "skip_upscale"
        """
        from app.api.control_routes import get_control_state

        state = get_control_state()

        # Set up approval waiting
        state.awaiting_video_approval = True
        state.video_approval_project_id = self.project.project_id
        state.video_approval_result = None

        # Create event for waiting
        if not hasattr(state, 'video_approval_event'):
            state.video_approval_event = asyncio.Event()
        else:
            state.video_approval_event.clear()

        try:
            # Wait for approval (with optional timeout)
            if self.AUTO_APPROVAL_TIMEOUT > 0:
                try:
                    await asyncio.wait_for(
                        state.video_approval_event.wait(),
                        timeout=self.AUTO_APPROVAL_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"[{self.name}] Approval timeout - auto-approving")
                    return "approved"
            else:
                # Wait indefinitely
                await state.video_approval_event.wait()

            # Get result
            result = state.video_approval_result or "approved"
            return result

        finally:
            # Cleanup
            state.awaiting_video_approval = False
            state.video_approval_project_id = None
