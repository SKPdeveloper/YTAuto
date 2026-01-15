"""
Base Pipeline Stage

Abstract base class for all pipeline stages.
Each stage is independent and can be resumed after failure.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Any, Dict
from datetime import datetime
from enum import Enum

from loguru import logger

from app.api.schemas import ProjectData, SceneData
from app.server.notifications import NotificationService, get_notification_service


class StageStatus(str, Enum):
    """Status of a pipeline stage"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StageResult:
    """Result of a pipeline stage execution"""
    success: bool
    stage_name: str
    status: StageStatus = StageStatus.COMPLETED
    message: Optional[str] = None
    error: Optional[Exception] = None
    data: Dict[str, Any] = field(default_factory=dict)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @property
    def duration_seconds(self) -> Optional[float]:
        """Calculate stage duration in seconds"""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "success": self.success,
            "stage_name": self.stage_name,
            "status": self.status.value,
            "message": self.message,
            "error": str(self.error) if self.error else None,
            "data": self.data,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
        }


class BasePipelineStage(ABC):
    """
    Abstract base class for pipeline stages.

    Each stage:
    - Has a unique name
    - Can check if it should run (can_run)
    - Can check if it can be resumed (can_resume)
    - Executes its logic (execute)
    - Reports progress via NotificationService

    Usage:
        class MyStage(BasePipelineStage):
            name = "my_stage"

            async def execute(self) -> StageResult:
                # Do work
                return StageResult(success=True, stage_name=self.name)
    """

    # Stage name - must be unique
    name: str = "base_stage"

    # Human-readable description
    description: str = "Base pipeline stage"

    def __init__(
        self,
        project: ProjectData,
        notifier: Optional[NotificationService] = None
    ):
        """
        Initialize stage with project data.

        Args:
            project: ProjectData object
            notifier: Optional NotificationService for WebSocket updates
        """
        self.project = project
        self.notifier = notifier or get_notification_service()
        self._started_at: Optional[datetime] = None

    @abstractmethod
    async def execute(self) -> StageResult:
        """
        Execute the stage logic.

        Returns:
            StageResult with success/failure status
        """
        pass

    async def can_run(self) -> bool:
        """
        Check if this stage should run.

        Override to add preconditions (e.g., previous stage completed).

        Returns:
            True if stage can run, False to skip
        """
        return True

    async def can_resume(self) -> bool:
        """
        Check if this stage can be resumed after failure.

        Override to check for partial completion state.

        Returns:
            True if stage can be resumed
        """
        return True

    async def run(self) -> StageResult:
        """
        Run the stage with logging and notifications.

        Handles:
        - Pre-flight checks (can_run)
        - Logging and timing
        - Error handling
        - Notifications

        Returns:
            StageResult
        """
        # Check if stage should run
        if not await self.can_run():
            logger.info(f"[{self.name}] Skipping - preconditions not met")
            return StageResult(
                success=True,
                stage_name=self.name,
                status=StageStatus.SKIPPED,
                message="Stage skipped - preconditions not met"
            )

        # Start timing
        self._started_at = datetime.now()

        logger.info(f"[{self.name}] Starting...")

        # Notify stage start
        await self.notifier.send_stage_changed(
            project_id=self.project.project_id,
            stage=self.name
        )

        try:
            # Execute stage logic
            result = await self.execute()
            result.started_at = self._started_at
            result.completed_at = datetime.now()

            if result.success:
                logger.success(f"[{self.name}] Completed in {result.duration_seconds:.1f}s")

                # Notify stage completion
                await self.notifier.send_stage_completed(
                    project_id=self.project.project_id,
                    stage=self.name
                )
            else:
                logger.error(f"[{self.name}] Failed: {result.message}")

            return result

        except Exception as e:
            logger.error(f"[{self.name}] Error: {e}")

            # Notify error
            await self.notifier.send_error(
                project_id=self.project.project_id,
                stage=self.name,
                error_message=str(e),
                is_resumable=await self.can_resume()
            )

            return StageResult(
                success=False,
                stage_name=self.name,
                status=StageStatus.FAILED,
                message=str(e),
                error=e,
                started_at=self._started_at,
                completed_at=datetime.now()
            )

    # ========================================================================
    # HELPER METHODS
    # ========================================================================

    async def notify_progress(
        self,
        progress_percent: float,
        message: Optional[str] = None
    ) -> None:
        """Send progress update to clients"""
        await self.notifier.send_progress(
            project_id=self.project.project_id,
            stage=self.name,
            progress_percent=progress_percent,
            message=message
        )

    async def notify_log(
        self,
        message: str,
        level: str = "info"
    ) -> None:
        """Send log message to clients"""
        await self.notifier.send_log(
            message=message,
            level=level,
            project_id=self.project.project_id,
            source=self.name
        )

    def get_scene(self, scene_number: int) -> Optional[SceneData]:
        """Get scene by number"""
        for scene in self.project.scenes:
            if scene.scene_number == scene_number:
                return scene
        return None

    @property
    def project_id(self) -> str:
        """Shortcut for project ID"""
        return self.project.project_id
