"""
Notification Service

High-level notification methods for the pipeline.
Replaces Telegram notification methods with WebSocket broadcasts.
"""

import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
from loguru import logger

from app.server.websocket import ConnectionManager, get_connection_manager
from app.server.events import (
    Events,
    ProjectEvent,
    SceneEvent,
    PrimaryCandidatesEvent,
    ApprovalEvent,
    ProgressEvent,
    LogEvent,
)


class NotificationService:
    """
    Sends notifications to connected web clients via WebSocket.

    Provides similar interface to the old Telegram methods for easy migration.

    Usage:
        notifier = NotificationService()
        await notifier.send_scene_ready(project_id, scene_number, image_path)
    """

    def __init__(self, manager: Optional[ConnectionManager] = None):
        self.manager = manager or get_connection_manager()

    # ========================================================================
    # PROJECT NOTIFICATIONS
    # ========================================================================

    async def send_project_created(
        self,
        project_id: str,
        topic: str,
        num_scenes: int = 8
    ) -> None:
        """Notify that a new project was created"""
        await self.manager.broadcast(Events.PROJECT_CREATED, ProjectEvent(
            project_id=project_id,
            topic=topic,
            total_scenes=num_scenes,
            status="created"
        ).to_dict())

    async def send_project_started(self, project_id: str, title: str) -> None:
        """Notify that pipeline started for a project"""
        await self.manager.broadcast(Events.PROJECT_STARTED, ProjectEvent(
            project_id=project_id,
            title=title,
            status="processing"
        ).to_dict())

    async def send_project_completed(
        self,
        project_id: str,
        title: str,
        final_video_path: Optional[Path] = None
    ) -> None:
        """Notify that project completed successfully"""
        data = ProjectEvent(
            project_id=project_id,
            title=title,
            status="completed"
        ).to_dict()

        if final_video_path:
            data["final_video"] = str(final_video_path)
            # Add URL for web preview
            data["final_video_url"] = f"/api/projects/{project_id}/final"

        await self.manager.broadcast(Events.PROJECT_COMPLETED, data)

    async def send_project_failed(
        self,
        project_id: str,
        error_message: str,
        stage: Optional[str] = None
    ) -> None:
        """Notify that project failed"""
        await self.manager.broadcast(Events.PROJECT_FAILED, ProjectEvent(
            project_id=project_id,
            status="failed",
            stage=stage,
            error_message=error_message
        ).to_dict())

    async def send_pipeline_started(
        self,
        project_id: str,
        total_stages: int = 5
    ) -> None:
        """Notify that pipeline started"""
        await self.manager.broadcast(Events.PIPELINE_STARTED, {
            "project_id": project_id,
            "total_stages": total_stages,
        })

    async def send_pipeline_resumed(
        self,
        project_id: str,
        resume_stage: str
    ) -> None:
        """Notify that pipeline resumed"""
        await self.manager.broadcast(Events.PIPELINE_RESUMED, {
            "project_id": project_id,
            "resume_stage": resume_stage,
        })

    async def send_pipeline_completed(self, project_id: str) -> None:
        """Notify that pipeline completed"""
        await self.manager.broadcast(Events.PIPELINE_COMPLETED, {
            "project_id": project_id,
        })

    # ========================================================================
    # STAGE NOTIFICATIONS
    # ========================================================================

    async def send_stage_changed(
        self,
        project_id: str,
        stage: str,
        scene_number: Optional[int] = None
    ) -> None:
        """Notify that pipeline stage changed"""
        await self.manager.broadcast(Events.STAGE_CHANGED, {
            "project_id": project_id,
            "stage": stage,
            "scene_number": scene_number,
        })

    async def send_stage_completed(self, project_id: str, stage: str) -> None:
        """Notify that a stage completed successfully"""
        await self.manager.broadcast(Events.STAGE_COMPLETED, {
            "project_id": project_id,
            "stage": stage,
        })

    # ========================================================================
    # SCENE NOTIFICATIONS
    # ========================================================================

    async def send_scene_updated(
        self,
        project_id: str,
        scene_number: int,
        status: str,
        **kwargs
    ) -> None:
        """Generic scene update notification"""
        data = SceneEvent(
            project_id=project_id,
            scene_number=scene_number,
            status=status,
        ).to_dict()
        data.update(kwargs)
        await self.manager.broadcast(Events.SCENE_UPDATED, data)

    async def send_scene_image_ready(
        self,
        project_id: str,
        scene_number: int,
        image_path: Path
    ) -> None:
        """Notify that scene image is ready"""
        await self.manager.broadcast(Events.SCENE_IMAGE_READY, SceneEvent(
            project_id=project_id,
            scene_number=scene_number,
            status="image_ready",
            image_path=str(image_path),
            image_url=f"/api/projects/{project_id}/scenes/{scene_number}/image"
        ).to_dict())

    async def send_scene_video_ready(
        self,
        project_id: str,
        scene_number: int,
        video_path: Path
    ) -> None:
        """Notify that scene video is ready"""
        import time
        cache_bust = int(time.time())
        await self.manager.broadcast(Events.SCENE_VIDEO_READY, SceneEvent(
            project_id=project_id,
            scene_number=scene_number,
            status="video_ready",
            video_path=str(video_path),
            video_url=f"/projects/{project_id}/scene_{scene_number}/video.mp4?t={cache_bust}"
        ).to_dict())

    async def send_scene_rejected(
        self,
        project_id: str,
        scene_number: int,
        reason: str
    ) -> None:
        """Notify that scene was rejected and needs regeneration"""
        await self.manager.broadcast(Events.SCENE_REJECTED, SceneEvent(
            project_id=project_id,
            scene_number=scene_number,
            status="rejected",
            rejection_reason=reason
        ).to_dict())

    # ========================================================================
    # PRIMARY SCENE (User Selection Required)
    # ========================================================================

    async def send_primary_candidates_ready(
        self,
        project_id: str,
        scene_number: int,
        candidate_paths: List[Path],
        scenario_summary: str,
        scene_description: str,
        is_regeneration: bool = False,
        attempt: int = 1,
        max_attempts: int = 5
    ) -> None:
        """
        Send PRIMARY scene candidates for user selection.

        This is a critical notification that requires user action.
        """
        candidates = []
        for i, path in enumerate(candidate_paths, 1):
            candidates.append({
                "index": i,
                "path": str(path),
                "url": f"/api/projects/{project_id}/scenes/{scene_number}/candidate/{i}"
            })

        await self.manager.broadcast(Events.PRIMARY_CANDIDATES_READY, PrimaryCandidatesEvent(
            project_id=project_id,
            scene_number=scene_number,
            candidates=candidates,
            scenario_summary=scenario_summary,
            scene_description=scene_description,
            is_regeneration=is_regeneration,
            attempt=attempt,
            max_attempts=max_attempts
        ).to_dict())

        logger.info(f"[WS] PRIMARY candidates sent for approval (attempt {attempt}/{max_attempts})")

    # ========================================================================
    # APPROVAL REQUESTS
    # ========================================================================

    async def send_approval_required(
        self,
        project_id: str,
        scene_number: int,
        approval_type: str = "scene",
        image_url: Optional[str] = None,
        video_url: Optional[str] = None,
        prompt: Optional[str] = None
    ) -> None:
        """
        Request user approval for a scene.

        Args:
            approval_type: "scene" | "primary" | "video"
        """
        await self.manager.broadcast(Events.APPROVAL_REQUIRED, ApprovalEvent(
            project_id=project_id,
            scene_number=scene_number,
            approval_type=approval_type,
            image_url=image_url or f"/api/projects/{project_id}/scenes/{scene_number}/image",
            video_url=video_url or f"/api/projects/{project_id}/scenes/{scene_number}/video",
            prompt=prompt
        ).to_dict())

    # ========================================================================
    # VALIDATION NOTIFICATIONS
    # ========================================================================

    async def send_validation_started(
        self,
        project_id: str,
        scene_number: int
    ) -> None:
        """Notify that image validation started"""
        await self.manager.broadcast(Events.VALIDATION_STARTED, {
            "project_id": project_id,
            "scene_number": scene_number,
        })

    async def send_validation_result(
        self,
        project_id: str,
        scene_number: int,
        passed: bool,
        score: float,
        feedback: str,
        attempt: int = 1
    ) -> None:
        """Send validation result"""
        event = Events.VALIDATION_PASSED if passed else Events.VALIDATION_FAILED
        await self.manager.broadcast(event, SceneEvent(
            project_id=project_id,
            scene_number=scene_number,
            status="validated" if passed else "validation_failed",
            validation_score=score,
            validation_feedback=feedback
        ).to_dict() | {"attempt": attempt})

    # ========================================================================
    # POST-PROCESSING NOTIFICATIONS
    # ========================================================================

    async def send_post_processing_update(
        self,
        project_id: str,
        stage: str,
        status: str,
        progress_percent: float = 0,
        message: Optional[str] = None
    ) -> None:
        """Send post-processing progress update"""
        event_map = {
            "voiceover": Events.VOICEOVER_STARTED if status == "started" else Events.VOICEOVER_COMPLETED,
            "assembly": Events.ASSEMBLY_STARTED if status == "started" else Events.ASSEMBLY_COMPLETED,
            "topaz": Events.TOPAZ_STARTED if status == "started" else Events.TOPAZ_COMPLETED,
        }

        event = event_map.get(stage, Events.PROGRESS)

        await self.manager.broadcast(event, ProgressEvent(
            project_id=project_id,
            stage=stage,
            progress_percent=progress_percent,
            message=message or f"{stage} {status}"
        ).to_dict())

    async def send_topaz_progress(
        self,
        project_id: str,
        stage: str,
        progress_percent: float,
        message: str,
        scene_number: int = 0
    ) -> None:
        """Send Topaz processing progress"""
        await self.manager.broadcast(Events.TOPAZ_PROGRESS, ProgressEvent(
            project_id=project_id,
            stage=stage,
            scene_number=scene_number,
            progress_percent=progress_percent,
            message=message
        ).to_dict())

    # ========================================================================
    # ERROR NOTIFICATIONS
    # ========================================================================

    async def send_error(
        self,
        project_id: str,
        stage: str,
        error_message: str,
        scene_number: Optional[int] = None,
        is_resumable: bool = True
    ) -> None:
        """Send error notification"""
        await self.manager.broadcast(Events.ERROR, {
            "project_id": project_id,
            "stage": stage,
            "scene_number": scene_number,
            "error_message": error_message,
            "is_resumable": is_resumable,
        })

    # ========================================================================
    # LOG MESSAGES
    # ========================================================================

    async def send_log(
        self,
        message: str,
        level: str = "info",
        project_id: Optional[str] = None,
        source: Optional[str] = None
    ) -> None:
        """Send log message to clients"""
        await self.manager.broadcast(Events.LOG, LogEvent(
            project_id=project_id,
            level=level,
            message=message,
            source=source
        ).to_dict())

    # ========================================================================
    # PUSH NOTIFICATIONS (Warnings/Errors/Info)
    # ========================================================================

    async def push_warning(
        self,
        title: str,
        message: str,
        project_id: Optional[str] = None,
        scene_number: Optional[int] = None,
        action_required: bool = False
    ) -> None:
        """
        Send WARNING push notification to UI.
        Yellow alert - something needs attention but pipeline continues.
        """
        await self.manager.broadcast("push_notification", {
            "type": "warning",
            "title": title,
            "message": message,
            "project_id": project_id,
            "scene_number": scene_number,
            "action_required": action_required,
            "timestamp": datetime.now().isoformat()
        })
        logger.warning(f"[PUSH] {title}: {message}")

    async def push_error(
        self,
        title: str,
        message: str,
        project_id: Optional[str] = None,
        scene_number: Optional[int] = None,
        is_critical: bool = False
    ) -> None:
        """
        Send ERROR push notification to UI.
        Red alert - something went wrong.
        """
        await self.manager.broadcast("push_notification", {
            "type": "error",
            "title": title,
            "message": message,
            "project_id": project_id,
            "scene_number": scene_number,
            "is_critical": is_critical,
            "timestamp": datetime.now().isoformat()
        })
        logger.error(f"[PUSH ERROR] {title}: {message}")

    async def push_info(
        self,
        title: str,
        message: str,
        project_id: Optional[str] = None,
        scene_number: Optional[int] = None
    ) -> None:
        """
        Send INFO push notification to UI.
        Blue info - general status update.
        """
        await self.manager.broadcast("push_notification", {
            "type": "info",
            "title": title,
            "message": message,
            "project_id": project_id,
            "scene_number": scene_number
        })
        logger.info(f"[PUSH] {title}: {message}")

    async def push_success(
        self,
        title: str,
        message: str,
        project_id: Optional[str] = None,
        scene_number: Optional[int] = None
    ) -> None:
        """
        Send SUCCESS push notification to UI.
        Green success - milestone achieved.
        """
        await self.manager.broadcast("push_notification", {
            "type": "success",
            "title": title,
            "message": message,
            "project_id": project_id,
            "scene_number": scene_number
        })
        logger.success(f"[PUSH] {title}: {message}")

    # ========================================================================
    # PROGRESS UPDATES
    # ========================================================================

    async def send_progress(
        self,
        project_id: str,
        stage: str,
        progress_percent: float,
        message: Optional[str] = None,
        eta_seconds: Optional[int] = None
    ) -> None:
        """Send generic progress update"""
        await self.manager.broadcast(Events.PROGRESS, ProgressEvent(
            project_id=project_id,
            stage=stage,
            progress_percent=progress_percent,
            message=message,
            eta_seconds=eta_seconds
        ).to_dict())


# Singleton instance
_notifier: Optional[NotificationService] = None


def get_notification_service() -> NotificationService:
    """Get the global NotificationService instance"""
    global _notifier
    if _notifier is None:
        _notifier = NotificationService()
    return _notifier
