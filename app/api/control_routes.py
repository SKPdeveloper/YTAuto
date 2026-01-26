"""
Control Panel API Routes.

Handles:
- Pipeline start/stop
- Daily schedule management
- Image approval workflow
- Scene kick/regenerate
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional
from pathlib import Path

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from app.core.config import settings
from app.server.websocket import ConnectionManager
from app.utils.logger import logger

router = APIRouter(prefix="/api/control", tags=["control"])

# ============================================================================
# STATE MANAGEMENT
# ============================================================================

class ControlState:
    """Global state for control panel."""

    def __init__(self):
        self.schedule_time: str = "09:00"
        self.schedule_enabled: bool = True
        self.pipeline_running: bool = False
        self.current_project_id: Optional[str] = None
        self.current_stage: str = ""
        self.progress: int = 0

        # Approval state
        self.awaiting_approval: bool = False
        self.approval_type: str = ""  # 'primary' or 'scenes'
        self.candidate_images: list = []
        self.scene_images: list = []
        self.approved_scenes: set = set()  # Manually approved scene numbers

        # Approval events for async coordination
        self.approval_event: Optional[asyncio.Event] = None
        self.selected_image_index: Optional[int] = None
        self.rejected_all: bool = False

        # Video approval (pre-Topaz)
        self.awaiting_video_approval: bool = False
        self.video_approval_data: dict = {}
        self.video_approval_result: Optional[str] = None
        self.video_approval_project_id: Optional[str] = None
        self.kicked_scenes: list = []  # Queue of scenes to regenerate
        self.scenes_confirmed: bool = False

        # Video Approval state (pre-upscale)
        self.awaiting_video_approval: bool = False
        self.video_approval_project_id: Optional[str] = None
        self.video_approval_result: Optional[str] = None  # 'approved', 'rejected', 'skip_upscale'
        self.video_approval_event: Optional[asyncio.Event] = None

        # WebSocket manager reference
        self.ws_manager: Optional[ConnectionManager] = None

        # Scheduler task
        self.scheduler_task: Optional[asyncio.Task] = None

        # Video paths for UI restoration
        self.final_video_path: Optional[str] = None
        self.topaz_video_path: Optional[str] = None

# Global state instance
state = ControlState()


def get_state() -> ControlState:
    """Get control state instance."""
    return state


def get_control_state() -> ControlState:
    """Alias for get_state - used by VideoApprovalStage."""
    return state


def set_ws_manager(manager: ConnectionManager):
    """Set WebSocket manager for broadcasting."""
    state.ws_manager = manager


# ============================================================================
# MODELS
# ============================================================================

class ScheduleRequest(BaseModel):
    time: str  # HH:MM format
    enabled: bool


class ApproveRequest(BaseModel):
    image_index: int
    approval_type: str


class KickRequest(BaseModel):
    scene_num: int


# ============================================================================
# SCHEDULE ENDPOINTS
# ============================================================================

@router.get("/schedule")
async def get_schedule():
    """Get current schedule settings."""
    next_run = calculate_next_run(state.schedule_time) if state.schedule_enabled else None
    return {
        "time": state.schedule_time,
        "enabled": state.schedule_enabled,
        "next_run": next_run.strftime("%Y-%m-%d %H:%M") if next_run else None
    }


@router.post("/schedule")
async def set_schedule(request: ScheduleRequest):
    """Update schedule settings."""
    state.schedule_time = request.time
    state.schedule_enabled = request.enabled

    # Restart scheduler if needed
    if state.scheduler_task:
        state.scheduler_task.cancel()

    if state.schedule_enabled:
        state.scheduler_task = asyncio.create_task(scheduler_loop())

    next_run = calculate_next_run(state.schedule_time) if state.schedule_enabled else None

    logger.info(f"Schedule updated: {request.time}, enabled: {request.enabled}")

    return {
        "status": "ok",
        "time": state.schedule_time,
        "enabled": state.schedule_enabled,
        "next_run": next_run.strftime("%Y-%m-%d %H:%M") if next_run else None
    }


def calculate_next_run(time_str: str) -> datetime:
    """Calculate next run datetime from time string."""
    hour, minute = map(int, time_str.split(":"))
    now = datetime.now()
    next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if next_run <= now:
        next_run += timedelta(days=1)

    return next_run


async def scheduler_loop():
    """Background scheduler loop."""
    logger.info("Scheduler started")

    while state.schedule_enabled:
        next_run = calculate_next_run(state.schedule_time)
        wait_seconds = (next_run - datetime.now()).total_seconds()

        logger.info(f"Scheduler: next run in {wait_seconds:.0f} seconds at {next_run}")

        try:
            await asyncio.sleep(wait_seconds)

            if state.schedule_enabled and not state.pipeline_running:
                logger.info("Scheduled pipeline start triggered")
                await start_pipeline_internal()

        except asyncio.CancelledError:
            logger.info("Scheduler cancelled")
            break
        except Exception as e:
            logger.error(f"Scheduler error: {e}")
            await asyncio.sleep(60)  # Wait before retry


# ============================================================================
# PIPELINE CONTROL
# ============================================================================

@router.get("/current-state")
async def get_current_state():
    """Get current control state for page refresh."""
    return {
        "pipeline_running": state.pipeline_running,
        "current_stage": state.current_stage,
        "progress": state.progress,
        "awaiting_approval": state.awaiting_approval,
        "approval_type": state.approval_type,
        "candidate_images": state.candidate_images,
        "scene_images": state.scene_images,
        "project_id": state.current_project_id,
        "final_video_path": state.final_video_path,
        "topaz_video_path": state.topaz_video_path,
        # Video approval (pre-upscale)
        "awaiting_video_approval": state.awaiting_video_approval,
        "video_approval_project_id": state.video_approval_project_id,
    }


@router.post("/start")
async def start_pipeline():
    """Start pipeline manually."""
    if state.pipeline_running:
        raise HTTPException(status_code=400, detail="Pipeline already running")

    # Start pipeline in background
    asyncio.create_task(start_pipeline_internal())

    return {"status": "started", "project_id": "pending"}


async def start_pipeline_internal():
    """Internal pipeline start logic."""
    from app.pipeline.control_pipeline import ControlPipeline

    state.pipeline_running = True
    state.progress = 0
    state.current_stage = "INITIALIZING"
    state.kicked_scenes.clear()  # Clear any pending kicks from previous run

    await broadcast_event("pipeline_started", {"project_id": "new"})

    try:
        # Create control pipeline
        pipeline = ControlPipeline()

        # Set callbacks for control panel
        pipeline.on_stage_change = on_stage_change
        pipeline.on_approval_required = on_approval_required
        pipeline.on_scene_updated = on_scene_updated

        # Run pipeline with approval callbacks
        project_id = await pipeline.run()

        state.current_project_id = project_id
        state.pipeline_running = False
        state.progress = 100
        state.final_video_path = f"/projects/{project_id}/final.mp4"

        await broadcast_event("pipeline_completed", {
            "project_id": project_id,
            "video_path": f"/projects/{project_id}/final.mp4"
        })

    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        import traceback
        traceback.print_exc()
        state.pipeline_running = False
        await broadcast_event("pipeline_error", {"message": str(e)})


# ============================================================================
# APPROVAL ENDPOINTS
# ============================================================================

@router.post("/approve")
async def approve_image(request: ApproveRequest):
    """Approve selected image."""
    if not state.awaiting_approval:
        raise HTTPException(status_code=400, detail="No approval pending")

    state.selected_image_index = request.image_index
    state.rejected_all = False

    # Signal the waiting pipeline
    if state.approval_event:
        state.approval_event.set()

    logger.info(f"Image {request.image_index} approved for {request.approval_type}")

    return {"status": "approved", "image_index": request.image_index}


@router.post("/reject-all")
async def reject_all_images():
    """Reject all images and regenerate."""
    if not state.awaiting_approval:
        raise HTTPException(status_code=400, detail="No approval pending")

    state.rejected_all = True
    state.selected_image_index = None

    # Signal the waiting pipeline
    if state.approval_event:
        state.approval_event.set()

    logger.info("All images rejected, regenerating")

    return {"status": "rejected"}


@router.post("/kick")
async def kick_scene(request: KickRequest):
    """Kick scene image and regenerate."""
    # Add to queue if not already there
    if request.scene_num not in state.kicked_scenes:
        state.kicked_scenes.append(request.scene_num)

    # Signal if waiting for scenes approval
    if state.approval_event:
        state.approval_event.set()

    logger.info(f"Scene {request.scene_num} kicked (queue: {state.kicked_scenes})")

    return {"status": "kicked", "scene_num": request.scene_num}


@router.post("/approve-scene")
async def approve_scene(request: KickRequest):
    """Manually approve a scene."""
    state.approved_scenes.add(request.scene_num)
    
    # Update scene_images status
    for scene in state.scene_images:
        if scene.get('scene_num') == request.scene_num:
            scene['status'] = 'approved'
            break
    
    logger.info(f"Scene {request.scene_num} manually approved")
    return {"status": "approved", "scene_num": request.scene_num}


@router.post("/confirm-scenes")
async def confirm_scenes():
    """Confirm all scenes and proceed to video."""
    state.scenes_confirmed = True
    state.kicked_scenes.clear()  # Clear pending kicks

    # Signal the waiting pipeline
    if state.approval_event:
        state.approval_event.set()

    logger.info("All scenes confirmed")

    return {"status": "confirmed"}


# ============================================================================
# VIDEO APPROVAL (pre-Topaz)
# ============================================================================

class VideoApprovalRequest(BaseModel):
    action: str  # 'approved', 'skip_upscale', 'rejected'


@router.post("/video-approval")
async def video_approval(request: VideoApprovalRequest):
    """Approve/reject video before Topaz upscaling."""
    if not state.awaiting_video_approval:
        raise HTTPException(status_code=400, detail="No video approval pending")

    state.video_approval_result = request.action

    # Signal the waiting pipeline
    if state.approval_event:
        state.approval_event.set()

    logger.info(f"Video approval: {request.action}")

    return {"status": request.action}


class TopazRequest(BaseModel):
    project_id: str


@router.post("/topaz")
async def start_topaz_processing(request: TopazRequest):
    """Start Topaz Video AI post-processing."""
    from app.modules.topaz_queue import TopazQueue

    project_dir = settings.PROJECTS_DIR / request.project_id
    input_video = project_dir / "final.mp4"

    if not input_video.exists():
        raise HTTPException(status_code=404, detail="Final video not found")

    output_video = project_dir / "final_enhanced.mp4"

    # Start Topaz in background
    asyncio.create_task(run_topaz_processing(request.project_id, input_video, output_video))

    return {"status": "started", "project_id": request.project_id}


async def run_topaz_processing(project_id: str, input_path: Path, output_path: Path):
    """Run Topaz processing in background."""
    from app.modules.topaz_queue import TopazQueue

    try:
        await broadcast_event("topaz_progress", {"message": "Initializing Topaz..."})

        queue = TopazQueue()

        # Start the worker
        await queue.start()

        await broadcast_event("topaz_progress", {"message": "Adding to Topaz queue..."})

        # Add task for FPS interpolation + 4K upscaling
        project_dir = settings.PROJECTS_DIR / project_id
        task = await queue.add_task(
            project_id=project_id,
            scene_number=0,  # 0 = final video
            input_path=input_path,
            output_dir=project_dir,
            metadata={"type": "final_enhancement"}
        )

        await broadcast_event("topaz_progress", {"message": "Processing video (this may take 15-30 min)..."})

        # Wait for completion
        completed = await queue.wait_for_completion(timeout=3600)  # 1 hour timeout

        # Stop the worker
        await queue.stop()

        # Check result
        final_4k = project_dir / "scene_0_4k.mp4"
        if completed and final_4k.exists():
            rel_path = f"/projects/{project_id}/scene_0_4k.mp4"
            state.topaz_video_path = rel_path
            await broadcast_event("topaz_completed", {"video_path": rel_path})
            logger.success(f"Topaz processing completed: {final_4k}")
        else:
            await broadcast_event("pipeline_error", {"message": "Topaz processing failed or timed out"})

    except Exception as e:
        logger.error(f"Topaz error: {e}")
        await broadcast_event("pipeline_error", {"message": f"Topaz error: {str(e)}"})


# ============================================================================
# VIDEO PREVIEW & DOWNLOAD
# ============================================================================

class VideoDownloadRequest(BaseModel):
    scene_num: int
    video_url: str
    project_id: str


@router.post("/download-video")
async def download_video(request: VideoDownloadRequest):
    """Download video from URL to project folder."""
    import httpx

    project_dir = settings.PROJECTS_DIR / request.project_id
    scene_dir = project_dir / f"scene_{request.scene_num}"
    scene_dir.mkdir(parents=True, exist_ok=True)

    output_path = scene_dir / "video.mp4"

    try:
        logger.info(f"[Scene {request.scene_num}] Downloading video...")

        async with httpx.AsyncClient() as client:
            response = await client.get(request.video_url, timeout=120)
            response.raise_for_status()

            content = response.content
            if len(content) < 10000:
                raise HTTPException(status_code=400, detail="Video file too small")

            output_path.write_bytes(content)

        logger.success(f"[Scene {request.scene_num}] Video saved: {output_path}")

        return {
            "status": "downloaded",
            "scene_num": request.scene_num,
            "path": str(output_path)
        }

    except Exception as e:
        logger.error(f"Download failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class VideoApproveRequest(BaseModel):
    scene_num: int
    project_id: str


@router.post("/approve-video")
async def approve_video(request: VideoApproveRequest):
    """Approve video for scene."""
    logger.info(f"[Scene {request.scene_num}] Video approved")
    return {"status": "approved", "scene_num": request.scene_num}


@router.post("/reject-video")
async def reject_video(request: VideoApproveRequest):
    """Reject video and trigger regeneration."""
    logger.info(f"[Scene {request.scene_num}] Video rejected, regenerating...")

    # TODO: Trigger video regeneration
    await broadcast_event("video_regenerating", {"scene_num": request.scene_num})

    return {"status": "regenerating", "scene_num": request.scene_num}


# ============================================================================
# VIDEO APPROVAL (PRE-UPSCALE)
# ============================================================================

class VideoApprovalDecision(BaseModel):
    """Request body for video approval decision."""
    decision: str  # 'approved', 'rejected', 'skip_upscale'
    project_id: Optional[str] = None


@router.get("/video-approval-status")
async def get_video_approval_status():
    """Get current video approval status."""
    return {
        "awaiting": state.awaiting_video_approval,
        "project_id": state.video_approval_project_id,
    }


@router.post("/video-approval")
async def submit_video_approval(request: VideoApprovalDecision):
    """
    Submit video approval decision.

    Decisions:
    - approved: Continue to Topaz upscaling
    - rejected: Stop pipeline, user will fix manually
    - skip_upscale: Mark complete without upscaling
    """
    if not state.awaiting_video_approval:
        raise HTTPException(status_code=400, detail="No video approval pending")

    if request.decision not in ('approved', 'rejected', 'skip_upscale'):
        raise HTTPException(status_code=400, detail="Invalid decision. Use: approved, rejected, skip_upscale")

    state.video_approval_result = request.decision

    # Signal the waiting VideoApprovalStage
    if state.video_approval_event:
        state.video_approval_event.set()

    logger.info(f"Video approval decision: {request.decision}")

    await broadcast_event("video_approval_decision", {
        "decision": request.decision,
        "project_id": state.video_approval_project_id
    })

    return {
        "status": "ok",
        "decision": request.decision,
        "project_id": state.video_approval_project_id
    }


# ============================================================================
# CALLBACK FUNCTIONS FOR ORCHESTRATOR
# ============================================================================

async def on_stage_change(stage: str, progress: int):
    """Called when pipeline stage changes."""
    state.current_stage = stage
    state.progress = progress
    await broadcast_event("stage_changed", {"stage": stage, "progress": progress})


async def on_approval_required(approval_type: str, data: dict):
    """
    Called when approval is required.

    Args:
        approval_type: 'primary' for Scene 1, 'scenes' for scenes 2-6, 'video_approval' for pre-upscale
        data: images or scenes or video data
    """
    # SIMPLIFIED UI: Only primary selection requires user interaction
    # Scenes 2-6 are auto-confirmed
    if approval_type == 'scenes':
        logger.info("Auto-confirming scenes 2-6 (simplified UI mode)")
        # Update scene_images for display purposes
        state.scene_images = data.get('scenes', [])
        await broadcast_event("scene_updated", {"scenes": state.scene_images})
        return {"action": "confirm"}

    # VIDEO APPROVAL - wait for user before Topaz
    if approval_type == 'video_approval':
        logger.info("Waiting for video approval before Topaz...")

        state.awaiting_video_approval = True
        state.video_approval_data = data
        state.approval_event = asyncio.Event()
        state.video_approval_result = None

        await broadcast_event("video_approval_required", {
            "type": "video_approval",
            **data
        })

        # Wait for user action
        await state.approval_event.wait()

        state.awaiting_video_approval = False

        result = state.video_approval_result or "approved"
        logger.info(f"Video approval result: {result}")
        return {"action": result}

    # YOUTUBE UPLOAD - wait for user confirmation
    if approval_type == 'youtube_upload':
        logger.info("Waiting for YouTube upload confirmation...")

        state.approval_event = asyncio.Event()
        state.video_approval_result = None

        await broadcast_event("youtube_upload_required", {
            "type": "youtube_upload",
            **data
        })

        # Wait for user action
        await state.approval_event.wait()

        result = state.video_approval_result or "skip"
        logger.info(f"YouTube upload result: {result}")
        return {"action": result}

    # Primary image selection - wait for user
    state.awaiting_approval = True
    state.approval_type = approval_type
    state.approval_event = asyncio.Event()
    state.selected_image_index = None
    state.rejected_all = False

    state.candidate_images = data.get('images', [])

    await broadcast_event("approval_required", {
        "type": approval_type,
        **data
    })

    # Wait for user action
    await state.approval_event.wait()

    state.awaiting_approval = False

    # Return the result
    if state.rejected_all:
        return {"action": "reject_all"}
    return {"action": "approve", "image_index": state.selected_image_index}


async def on_scene_updated(scene_num: int, data: dict):
    """Called when a scene is updated."""
    # Update local state
    for i, scene in enumerate(state.scene_images):
        if scene.get('scene_num') == scene_num:
            state.scene_images[i] = data
            break

    await broadcast_event("scene_updated", data)


# ============================================================================
# BROADCAST HELPER
# ============================================================================

async def broadcast_event(event: str, data: dict):
    """Broadcast event to all connected clients."""
    if state.ws_manager:
        await state.ws_manager.broadcast(event, data)
    else:
        logger.warning(f"No WebSocket manager set, cannot broadcast: {event}")


# ============================================================================
# PAGE ROUTE
# ============================================================================

@router.get("/page")
async def control_page():
    """Redirect to control page."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/control")
