"""
WebSocket Event Types

Defines all event types for communication between server and clients.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Any, Dict
from datetime import datetime
from enum import Enum


class Events:
    """
    All WebSocket event types.

    Naming convention:
    - Use snake_case for event names
    - Prefix with category (project_, scene_, etc.)
    """

    # Connection events
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    PING = "ping"
    PONG = "pong"
    ERROR = "error"

    # Project lifecycle
    PROJECT_CREATED = "project_created"
    PROJECT_STARTED = "project_started"
    PROJECT_PAUSED = "project_paused"
    PROJECT_RESUMED = "project_resumed"
    PROJECT_COMPLETED = "project_completed"
    PROJECT_FAILED = "project_failed"

    # Pipeline lifecycle
    PIPELINE_STARTED = "pipeline_started"
    PIPELINE_RESUMED = "pipeline_resumed"
    PIPELINE_COMPLETED = "pipeline_completed"
    PIPELINE_FAILED = "pipeline_failed"

    # Stage changes
    STAGE_CHANGED = "stage_changed"
    STAGE_COMPLETED = "stage_completed"
    STAGE_FAILED = "stage_failed"

    # Scene events
    SCENE_UPDATED = "scene_updated"
    SCENE_IMAGE_READY = "scene_image_ready"
    SCENE_VIDEO_READY = "scene_video_ready"
    SCENE_APPROVED = "scene_approved"
    SCENE_REJECTED = "scene_rejected"

    # PRIMARY scene (requires user selection)
    PRIMARY_CANDIDATES_READY = "primary_candidates_ready"
    PRIMARY_SELECTION_REQUIRED = "primary_selection_required"
    PRIMARY_SELECTED = "primary_selected"

    # Approval requests
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_RECEIVED = "approval_received"

    # Validation
    VALIDATION_STARTED = "validation_started"
    VALIDATION_PASSED = "validation_passed"
    VALIDATION_FAILED = "validation_failed"

    # Post-processing
    VOICEOVER_STARTED = "voiceover_started"
    VOICEOVER_COMPLETED = "voiceover_completed"
    ASSEMBLY_STARTED = "assembly_started"
    ASSEMBLY_COMPLETED = "assembly_completed"
    TOPAZ_STARTED = "topaz_started"
    TOPAZ_PROGRESS = "topaz_progress"
    TOPAZ_COMPLETED = "topaz_completed"

    # Progress updates
    PROGRESS = "progress"
    LOG = "log"


@dataclass
class EventData:
    """
    Base class for event payloads.

    All event data should inherit from this and add specific fields.
    """
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    project_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class ProjectEvent(EventData):
    """Project-level event data"""
    status: Optional[str] = None
    stage: Optional[str] = None
    title: Optional[str] = None
    topic: Optional[str] = None
    total_scenes: int = 0
    completed_scenes: int = 0
    error_message: Optional[str] = None


@dataclass
class SceneEvent(EventData):
    """Scene-level event data"""
    scene_number: int = 0
    status: Optional[str] = None
    image_path: Optional[str] = None
    video_path: Optional[str] = None
    image_url: Optional[str] = None  # For web preview
    video_url: Optional[str] = None  # For web preview
    validation_score: Optional[float] = None
    validation_feedback: Optional[str] = None
    rejection_reason: Optional[str] = None


@dataclass
class PrimaryCandidatesEvent(EventData):
    """PRIMARY scene candidates ready for selection"""
    scene_number: int = 1
    candidates: List[Dict[str, str]] = field(default_factory=list)  # [{path, url}, ...]
    scenario_summary: Optional[str] = None
    scene_description: Optional[str] = None
    is_regeneration: bool = False
    attempt: int = 1
    max_attempts: int = 5


@dataclass
class ApprovalEvent(EventData):
    """Approval request event data"""
    scene_number: int = 0
    approval_type: str = "scene"  # "scene" | "primary" | "video"
    image_url: Optional[str] = None
    video_url: Optional[str] = None
    prompt: Optional[str] = None
    options: List[str] = field(default_factory=lambda: ["approve", "reject", "regenerate"])


@dataclass
class ProgressEvent(EventData):
    """Progress update event data"""
    stage: Optional[str] = None
    scene_number: Optional[int] = None
    progress_percent: float = 0
    message: Optional[str] = None
    eta_seconds: Optional[int] = None


@dataclass
class LogEvent(EventData):
    """Log message event data"""
    level: str = "info"  # debug, info, warning, error, success
    message: str = ""
    source: Optional[str] = None


# ============================================================================
# CLIENT ACTIONS (messages from client to server)
# ============================================================================

class ClientActions:
    """
    Actions that clients can send to the server.
    """
    # Selection
    SELECT_PRIMARY = "select_primary"      # {image_idx: 1-4}
    REJECT_SCENARIO = "reject_scenario"    # {}

    # Approval
    APPROVE_SCENE = "approve_scene"        # {scene_number: int}
    REJECT_SCENE = "reject_scene"          # {scene_number: int}
    REGENERATE_SCENE = "regenerate_scene"  # {scene_number: int, new_prompt?: str}

    # Pipeline control
    PAUSE_PIPELINE = "pause_pipeline"      # {}
    RESUME_PIPELINE = "resume_pipeline"    # {}
    CANCEL_PROJECT = "cancel_project"      # {}

    # Misc
    REQUEST_STATUS = "request_status"      # {}
    PONG = "pong"                          # {}
