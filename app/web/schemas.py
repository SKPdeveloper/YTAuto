"""
Pydantic schemas for Web UI forms and API responses.
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from enum import Enum
from datetime import datetime
from pathlib import Path


class VideoFormat(str, Enum):
    """Supported video formats."""
    PORTRAIT = "9:16"
    SQUARE = "1:1"
    LANDSCAPE = "16:9"


class VideoEngine(str, Enum):
    """Supported video generation engines."""
    HIGGSFIELD = "higgsfield"
    COMFYUI = "comfyui"


class ProjectStatus(str, Enum):
    """Project statuses for UI display."""
    GENERATING = "generating"
    REVIEWING = "reviewing"
    APPROVED = "approved"
    UPSCALING = "upscaling"
    READY = "ready"
    FAILED = "failed"
    PAUSED = "paused"


class SceneStatus(str, Enum):
    """Scene statuses for UI display."""
    PENDING = "pending"
    GENERATING_IMAGES = "generating_images"
    VALIDATING = "validating"
    GENERATING_VIDEO = "generating_video"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    UPSCALING = "upscaling"
    COMPLETED = "completed"
    FAILED = "failed"


# =============================================================================
# Form Schemas (for HTMX form submissions)
# =============================================================================

class ChannelCreateForm(BaseModel):
    """Form data for creating a new channel."""
    name: str = Field(..., min_length=1, max_length=100)
    folder_path: str = Field(..., min_length=1)
    default_format: VideoFormat = VideoFormat.PORTRAIT
    default_engine: VideoEngine = VideoEngine.HIGGSFIELD

    @field_validator('folder_path')
    @classmethod
    def validate_folder_path(cls, v: str) -> str:
        """Validate that folder path exists."""
        path = Path(v)
        if not path.exists():
            raise ValueError(f"Folder does not exist: {v}")
        if not path.is_dir():
            raise ValueError(f"Path is not a folder: {v}")
        return str(path.absolute())


class GenerateScriptsRequest(BaseModel):
    """Request for generating script options."""
    format: VideoFormat
    duration_seconds: int = Field(..., ge=5, le=1800)  # 5 sec to 30 min
    engine: VideoEngine
    topic: str = Field(..., min_length=3, max_length=500)


class ProjectCreateRequest(BaseModel):
    """Request for creating a new project."""
    format: VideoFormat
    duration_seconds: int = Field(..., ge=5, le=1800)
    engine: VideoEngine
    topic: str = Field(..., min_length=3, max_length=500)
    selected_script: str = Field(..., min_length=10)
    project_name: Optional[str] = None


# =============================================================================
# Response Schemas (for JSON API responses)
# =============================================================================

class ChannelResponse(BaseModel):
    """Channel data for API response."""
    id: int
    name: str
    folder_path: str
    default_format: str
    default_engine: str
    created_at: datetime
    total_projects: int = 0
    active_projects: int = 0
    ready_projects: int = 0


class SceneResponse(BaseModel):
    """Scene data for API response."""
    id: int
    scene_number: int
    prompt: Optional[str]
    status: str
    image_path: Optional[str]
    video_path: Optional[str]
    upscaled_path: Optional[str]

    @property
    def status_icon(self) -> str:
        """Get icon for scene status."""
        icons = {
            "pending": "clock",
            "generating_images": "image",
            "validating": "search",
            "generating_video": "film",
            "awaiting_approval": "clock",
            "approved": "check",
            "upscaling": "arrow-up",
            "completed": "check-circle",
            "failed": "x-circle"
        }
        return icons.get(self.status, "circle")

    @property
    def status_color(self) -> str:
        """Get color class for scene status."""
        colors = {
            "pending": "text-gray-400",
            "generating_images": "text-blue-400",
            "validating": "text-blue-400",
            "generating_video": "text-blue-400",
            "awaiting_approval": "text-orange-400",
            "approved": "text-green-300",
            "upscaling": "text-purple-400",
            "completed": "text-green-500",
            "failed": "text-red-500"
        }
        return colors.get(self.status, "text-gray-400")


class ProjectResponse(BaseModel):
    """Project data for API response."""
    id: int
    channel_id: int
    orchestrator_project_id: Optional[str]
    name: str
    topic: Optional[str]
    format: str
    duration_seconds: int
    engine: str
    status: str
    progress: int
    created_at: datetime
    completed_at: Optional[datetime]
    scenes: List[SceneResponse] = []

    @property
    def status_icon(self) -> str:
        """Get icon for project status."""
        icons = {
            "generating": "loader",
            "reviewing": "eye",
            "approved": "check",
            "upscaling": "arrow-up",
            "ready": "check-circle",
            "failed": "x-circle",
            "paused": "pause"
        }
        return icons.get(self.status, "circle")

    @property
    def status_color(self) -> str:
        """Get color class for project status."""
        colors = {
            "generating": "text-blue-400",
            "reviewing": "text-orange-400",
            "approved": "text-green-300",
            "upscaling": "text-purple-400",
            "ready": "text-green-500",
            "failed": "text-red-500",
            "paused": "text-gray-400"
        }
        return colors.get(self.status, "text-gray-400")


class LogEntry(BaseModel):
    """Log entry for API response."""
    id: int
    timestamp: datetime
    message: str
    level: str

    @property
    def level_color(self) -> str:
        """Get color class for log level."""
        colors = {
            "info": "text-blue-400",
            "success": "text-green-400",
            "warning": "text-yellow-400",
            "error": "text-red-400"
        }
        return colors.get(self.level, "text-gray-400")

    @property
    def level_icon(self) -> str:
        """Get icon for log level."""
        icons = {
            "info": "info",
            "success": "check",
            "warning": "alert-triangle",
            "error": "x-circle"
        }
        return icons.get(self.level, "circle")


class ChannelStatsResponse(BaseModel):
    """Channel statistics for API response."""
    total_projects: int
    active_projects: int
    ready_projects: int
    weekly_projects: int
    success_rate: float
    avg_time_minutes: float
    api_cost: float


class TopazQueueStatus(BaseModel):
    """Topaz queue status for display."""
    queue_size: int
    current_task: Optional[str]
    is_processing: bool
