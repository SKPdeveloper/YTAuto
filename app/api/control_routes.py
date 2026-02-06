"""
Control Panel API Routes.

Handles:
- Pipeline start/stop
- Daily schedule management
- Image approval workflow
- Scene kick/regenerate
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Optional
from pathlib import Path

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
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

        # All 6 scenes with image/video pairs
        self.all_scenes: list = []
        self.image_retry_count: int = 0
        self.video_retry_count: int = 0

        # Approval events for async coordination
        self.approval_event: Optional[asyncio.Event] = None
        self.selected_image_index: Optional[int] = None
        self.rejected_all: bool = False
        self.abort_pipeline: bool = False  # Signal to abort current pipeline

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


def find_final_video(project_id: str) -> tuple[Optional[Path], Optional[str]]:
    """
    Find the final video file in the project directory.
    Searches multiple possible names. Returns (absolute_path, relative_url) or (None, None).
    """
    project_dir = settings.PROJECTS_DIR / project_id
    if not project_dir.exists():
        return None, None

    # Search in priority order
    candidates = [
        "final.mp4",
        "final_video.mp4",
        "assembled_video.mp4",
        "final_raw.mp4",
    ]

    for name in candidates:
        path = project_dir / name
        if path.exists() and path.stat().st_size > 0:
            return path, f"/projects/{project_id}/{name}"

    return None, None


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
    # Always resolve video path from disk (user may have replaced the file)
    final_video_path = state.final_video_path
    if state.current_project_id:
        _, fresh_url = find_final_video(state.current_project_id)
        if fresh_url:
            final_video_path = fresh_url

    return {
        "pipeline_running": state.pipeline_running,
        "current_stage": state.current_stage,
        "progress": state.progress,
        "awaiting_approval": state.awaiting_approval,
        "approval_type": state.approval_type,
        "candidate_images": state.candidate_images,
        "scene_images": state.scene_images,
        "project_id": state.current_project_id,
        "final_video_path": final_video_path,
        "topaz_video_path": state.topaz_video_path,
        # Video approval (pre-upscale)
        "awaiting_video_approval": state.awaiting_video_approval,
        "video_approval_project_id": state.video_approval_project_id,
        # All scenes with image/video pairs
        "all_scenes": state.all_scenes,
        "image_retry_count": state.image_retry_count,
        "video_retry_count": state.video_retry_count,
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


class NewTopicRequest(BaseModel):
    project_id: Optional[str] = None  # Client can pass current project_id


@router.post("/new-topic")
async def start_new_topic(request: NewTopicRequest = None):
    """
    Cancel current project and start pipeline with a new topic.
    Archives current project as 'test' before restarting.
    """
    # Use client-provided project_id if server state is empty
    old_project_id = state.current_project_id
    if not old_project_id and request and request.project_id:
        old_project_id = request.project_id

    # Signal abort to current pipeline
    state.abort_pipeline = True
    state.rejected_all = True
    state.selected_image_index = None

    # Release any waiting approval events
    if state.approval_event:
        state.approval_event.set()
    if state.video_approval_event:
        state.video_approval_event.set()

    # Wait a moment for pipeline to see abort flag
    await asyncio.sleep(0.2)

    # Archive current project if it exists
    if old_project_id:
        try:
            from scripts.publish_archive import archive_project
            archive_result = archive_project(old_project_id, category="test")
            logger.info(f"Archived {old_project_id} as test: {archive_result.get('status')}")
        except Exception as e:
            logger.warning(f"Failed to archive {old_project_id}: {e}")

    # Reset state completely
    state.awaiting_approval = False
    state.approval_type = ""
    state.candidate_images = []
    state.scene_images = []
    state.all_scenes = []
    state.approved_scenes = set()
    state.kicked_scenes = []
    state.current_project_id = None
    state.pipeline_running = False
    state.current_stage = ""
    state.progress = 0
    state.awaiting_video_approval = False
    state.final_video_path = None
    state.topaz_video_path = None
    state.image_retry_count = 0
    state.video_retry_count = 0

    # Clear abort flag before starting new pipeline
    state.abort_pipeline = False

    # Start new pipeline
    asyncio.create_task(start_pipeline_internal())

    # Broadcast state reset to all clients
    await broadcast_event("pipeline_reset", {"old_project_id": old_project_id})

    logger.info(f"New topic requested, archived {old_project_id}, starting fresh pipeline")

    return {
        "status": "ok",
        "old_project_id": old_project_id,
        "new_project_id": "pending"
    }


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

# VideoApprovalRequest removed - use VideoApprovalDecision at /video-approval instead


class TopazRequest(BaseModel):
    project_id: str


@router.post("/topaz")
async def start_topaz_processing(request: TopazRequest):
    """Start Topaz Video AI post-processing."""
    from app.modules.topaz_queue import TopazQueue

    video_path, _ = find_final_video(request.project_id)
    if not video_path:
        raise HTTPException(status_code=404, detail="Final video not found")

    project_dir = settings.PROJECTS_DIR / request.project_id
    output_video = project_dir / "final_enhanced.mp4"

    # Start Topaz in background
    asyncio.create_task(run_topaz_processing(request.project_id, video_path, output_video))

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
    decision: str  # 'approved', 'rejected', 'skip_upscale', 'needs_editing'
    project_id: Optional[str] = None


@router.get("/video-approval-status")
async def get_video_approval_status():
    """Get current video approval status."""
    return {
        "awaiting": state.awaiting_video_approval,
        "project_id": state.video_approval_project_id,
    }


@router.get("/refresh-video")
async def refresh_video():
    """Re-scan project directory for the current final video file."""
    project_id = state.video_approval_project_id or state.current_project_id
    if not project_id:
        raise HTTPException(status_code=400, detail="No active project")

    video_path, video_url = find_final_video(project_id)
    if not video_path:
        raise HTTPException(status_code=404, detail="No final video found in project directory")

    state.final_video_path = video_url
    logger.info(f"Video refreshed from disk: {video_path.name} ({video_path.stat().st_size / (1024*1024):.1f} MB)")

    return {
        "video_url": video_url,
        "filename": video_path.name,
        "size_mb": round(video_path.stat().st_size / (1024 * 1024), 1),
    }


@router.post("/video-approval")
async def submit_video_approval(request: VideoApprovalDecision):
    """
    Submit video approval decision.

    Decisions:
    - approved: Continue to Topaz upscaling
    - rejected: Stop pipeline, user will fix manually
    - skip_upscale: Mark complete without upscaling
    - needs_editing: Stop pipeline + rename folder with _ДОМОНТУВАТИ suffix
    """
    if not state.awaiting_video_approval:
        raise HTTPException(status_code=400, detail="No video approval pending")

    valid = ('approved', 'rejected', 'skip_upscale', 'needs_editing')
    if request.decision not in valid:
        raise HTTPException(status_code=400, detail=f"Invalid decision. Use: {', '.join(valid)}")

    # Resolve the current video from disk (user may have replaced/renamed it)
    project_id = state.video_approval_project_id or state.current_project_id
    if project_id and request.decision in ('approved', 'skip_upscale'):
        video_path, video_url = find_final_video(project_id)
        if video_path:
            state.final_video_path = video_url
            logger.info(f"Resolved final video from disk: {video_path.name}")
        else:
            logger.warning(f"No final video found in project {project_id}")

    # needs_editing → pipeline treats as rejected, then we rename the folder
    effective_decision = "rejected" if request.decision == "needs_editing" else request.decision
    state.video_approval_result = effective_decision

    # Signal the waiting pipeline
    if state.video_approval_event:
        state.video_approval_event.set()

    logger.info(f"Video approval decision: {request.decision}")

    renamed_to = None
    if request.decision == "needs_editing" and project_id:
        renamed_to = _rename_project_for_editing(project_id)

    await broadcast_event("video_approval_decision", {
        "decision": request.decision,
        "project_id": project_id,
        "renamed_to": renamed_to,
    })

    return {
        "status": "ok",
        "decision": request.decision,
        "project_id": project_id,
        "renamed_to": renamed_to,
    }


def _save_session_state(project_id: str, project_dir: Path) -> None:
    """
    Save current session state to session.json for later resumption.
    """
    session_data = {
        "project_id": project_id,
        "saved_at": datetime.now().isoformat(),
        "stage": state.current_stage,
        "progress": state.progress,
        "final_video_path": state.final_video_path,
        "topaz_video_path": state.topaz_video_path,
        "all_scenes": state.all_scenes,
        "status": "needs_editing"
    }

    session_path = project_dir / "session.json"
    try:
        with open(session_path, 'w', encoding='utf-8') as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)
        logger.info(f"Session saved: {session_path}")
    except Exception as e:
        logger.error(f"Failed to save session: {e}")


def _rename_project_for_editing(project_id: str) -> Optional[str]:
    """
    Rename project folder by appending _ДОМОНТУВАТИ suffix.
    Creates a TOPAZ.bat script inside for one-click upscaling after manual edit.
    Saves session state for later resumption.
    Returns the new folder name, or None if rename failed.
    """
    project_dir = settings.PROJECTS_DIR / project_id
    if not project_dir.exists():
        logger.warning(f"Cannot rename: folder not found {project_dir}")
        return None

    # Save session state BEFORE rename
    _save_session_state(project_id, project_dir)

    # Create TOPAZ.bat BEFORE rename (folder still accessible by old name)
    _create_topaz_bat(project_dir)

    # Strip existing suffix if re-marking
    base_name = project_id.replace("_ДОМОНТУВАТИ", "")
    new_name = f"{base_name}_ДОМОНТУВАТИ"
    new_dir = settings.PROJECTS_DIR / new_name

    if new_dir.exists():
        logger.info(f"Folder already marked: {new_name}")
        return new_name

    try:
        project_dir.rename(new_dir)
        logger.info(f"Project renamed: {project_id} → {new_name}")
        return new_name
    except Exception as e:
        logger.error(f"Failed to rename project folder: {e}")
        return None


def _create_topaz_bat(project_dir: Path) -> None:
    """
    Create TOPAZ.bat in the project folder.
    Two-stage pipeline: FPS interpolation → 4K upscaling.
    """
    topaz_ffmpeg = str(settings.TOPAZ_FFMPEG_PATH).replace("/", "\\")
    topaz_dir = str(settings.TOPAZ_FFMPEG_PATH.parent).replace("/", "\\")
    model_dir = r"C:\ProgramData\Topaz Labs LLC\Topaz Video AI\models"

    fps_model = settings.TOPAZ_FPS_MODEL
    target_fps = settings.TOPAZ_TARGET_FPS
    upscale_model = settings.TOPAZ_UPSCALE_MODEL
    out_w = settings.TOPAZ_OUTPUT_WIDTH
    out_h = settings.TOPAZ_OUTPUT_HEIGHT
    codec = settings.TOPAZ_CODEC
    bitrate = settings.TOPAZ_BITRATE

    bat_content = f'''@echo off
chcp 65001 >nul
title TOPAZ - Interpolation + Upscale
cd /d "%~dp0"

echo ============================================
echo   TOPAZ VIDEO AI - Post-Edit Pipeline
echo ============================================
echo.

set "TVAI_MODEL_DIR={model_dir}"
set "TVAI_MODEL_DATA_DIR={model_dir}"

:: --- Find input video ---
set "INPUT="
if exist "final.mp4" set "INPUT=final.mp4"
if exist "final_video.mp4" set "INPUT=final_video.mp4"
if exist "assembled_video.mp4" set "INPUT=assembled_video.mp4"

if "%INPUT%"=="" (
    echo [ERROR] No video found! Place final.mp4 or final_video.mp4 in this folder.
    pause
    exit /b 1
)

echo [INPUT]  %INPUT%
echo.

:: --- Stage 1: FPS Interpolation ---
echo [STAGE 1/2] FPS Interpolation ^({fps_model}, {target_fps}fps^)
echo -------------------------------------------

"{topaz_ffmpeg}" ^
    -hide_banner -nostdin -y ^
    -hwaccel auto ^
    -i "%INPUT%" ^
    -vf "tvai_fi=model={fps_model}:fps={target_fps}/1:device=0" ^
    -c:v {codec} ^
    -b:v {bitrate} ^
    -pix_fmt yuv420p ^
    -c:a copy ^
    "final_60fps.mp4"

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] FPS Interpolation failed!
    pause
    exit /b 1
)

echo.
echo [OK] FPS Interpolation complete: final_60fps.mp4
echo.

:: --- Stage 2: 4K Upscaling ---
echo [STAGE 2/2] 4K Upscaling ^({upscale_model}, {out_w}x{out_h}^)
echo -------------------------------------------

"{topaz_ffmpeg}" ^
    -hide_banner -nostdin -y ^
    -hwaccel auto ^
    -i "final_60fps.mp4" ^
    -vf "tvai_up=model={upscale_model}:scale=0:w={out_w}:h={out_h}:device=0,scale={out_w}:{out_h}" ^
    -c:v {codec} ^
    -b:v {bitrate} ^
    -pix_fmt yuv420p ^
    -c:a copy ^
    "final_4k.mp4"

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Upscaling failed!
    pause
    exit /b 1
)

echo.
echo ============================================
echo   DONE! Output: final_4k.mp4
echo ============================================
echo.

:: --- Cleanup intermediate ---
del "final_60fps.mp4" 2>nul
echo [CLEANUP] Deleted intermediate final_60fps.mp4

echo.
pause
'''

    bat_path = project_dir / "TOPAZ.bat"
    try:
        bat_path.write_text(bat_content, encoding="utf-8")
        logger.info(f"Created TOPAZ.bat in {project_dir}")
    except Exception as e:
        logger.error(f"Failed to create TOPAZ.bat: {e}")


# ============================================================================
# ARCHIVE ENDPOINT
# ============================================================================

class ArchiveRequest(BaseModel):
    project_id: str
    category: str = "published"  # published, failed, test


@router.post("/archive-project")
async def archive_project_endpoint(request: ArchiveRequest):
    """
    Archive a project: cleanup intermediates (if published) + move to archive/.

    Categories:
    - published: cleanup + move to archive/published/
    - failed: move as-is to archive/failed/
    - test: move as-is to archive/test/
    """
    from scripts.publish_archive import archive_project

    if request.category not in ("published", "failed", "test"):
        raise HTTPException(status_code=400, detail=f"Invalid category: {request.category}")

    result = archive_project(
        project_id=request.project_id,
        category=request.category,
    )

    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])

    logger.info(f"Project archived: {request.project_id} -> {request.category}")

    return result


# ============================================================================
# RE-RENDER ENDPOINT
# ============================================================================

@router.post("/render/{project_id}")
async def render_project(project_id: str, background_tasks: BackgroundTasks):
    """
    Re-render a project using ManifestRenderer.
    Requires gen3b_manifest.json to exist.
    """
    from app.services.manifest_renderer import ManifestRenderer
    from app.services.gen_models import Gen3bManifest

    project_dir = settings.PROJECTS_DIR / project_id
    manifest_path = project_dir / "gen3b_manifest.json"

    if not project_dir.exists():
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    if not manifest_path.exists():
        raise HTTPException(status_code=400, detail=f"Gen3b manifest not found for {project_id}")

    async def do_render():
        try:
            logger.info(f"[RENDER] Starting render for {project_id}...")

            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest_data = json.load(f)

            manifest = Gen3bManifest(**manifest_data)
            renderer = ManifestRenderer()

            result = await renderer.render(
                manifest=manifest,
                project_dir=project_dir,
                output_filename="final.mp4"
            )

            logger.success(f"[RENDER] ✅ {project_id} rendered: {result}")
            await broadcast_event("render_complete", {"project_id": project_id, "path": str(result)})

        except Exception as e:
            logger.error(f"[RENDER] ❌ {project_id} failed: {e}")
            await broadcast_event("render_failed", {"project_id": project_id, "error": str(e)})

    background_tasks.add_task(do_render)

    return {"status": "rendering", "project_id": project_id}


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
        state.video_approval_event = asyncio.Event()  # Use video_approval_event to match submit_video_approval
        state.video_approval_result = None

        await broadcast_event("video_approval_required", {
            "type": "video_approval",
            **data
        })

        # Send Telegram notification
        try:
            from app.services.telegram_notifier import get_telegram_notifier
            telegram = get_telegram_notifier()
            await telegram.send_approval_required(
                project_id=state.current_project_id or "unknown",
                approval_type="video",
                count=1,
            )
        except Exception as e:
            logger.warning(f"Telegram notification failed: {e}")

        # Wait for user action
        await state.video_approval_event.wait()

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

    # Send Telegram notification (works even when phone is locked)
    try:
        from app.services.telegram_notifier import get_telegram_notifier
        telegram = get_telegram_notifier()
        await telegram.send_approval_required(
            project_id=state.current_project_id or "unknown",
            approval_type=approval_type,
            count=len(state.candidate_images),
        )
    except Exception as e:
        logger.warning(f"Telegram notification failed: {e}")

    # Wait for user action
    await state.approval_event.wait()

    state.awaiting_approval = False

    # Check if pipeline was aborted (new topic requested)
    if state.abort_pipeline:
        return {"action": "abort"}

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
# SESSION RECOVERY
# ============================================================================

@router.get("/recoverable-sessions")
async def get_recoverable_sessions():
    """
    Get list of projects that can be recovered (with session.json or _ДОМОНТУВАТИ suffix).
    """
    recoverable = []

    if not settings.PROJECTS_DIR.exists():
        return {"sessions": []}

    for project_dir in settings.PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue

        session_path = project_dir / "session.json"
        if session_path.exists():
            try:
                with open(session_path, 'r', encoding='utf-8') as f:
                    session_data = json.load(f)

                # Check if final video exists
                final_video = None
                for name in ["final.mp4", "final_video.mp4", "assembled_video.mp4"]:
                    if (project_dir / name).exists():
                        final_video = f"/projects/{project_dir.name}/{name}"
                        break

                recoverable.append({
                    "project_id": project_dir.name,
                    "original_id": session_data.get("project_id", project_dir.name),
                    "saved_at": session_data.get("saved_at"),
                    "stage": session_data.get("stage"),
                    "status": session_data.get("status", "unknown"),
                    "final_video": final_video,
                    "needs_editing": "_ДОМОНТУВАТИ" in project_dir.name
                })
            except Exception as e:
                logger.warning(f"Failed to read session from {session_path}: {e}")

    # Sort by saved_at descending
    recoverable.sort(key=lambda x: x.get("saved_at", ""), reverse=True)

    return {"sessions": recoverable}


class ResumeSessionRequest(BaseModel):
    project_id: str


@router.post("/resume-session")
async def resume_session(request: ResumeSessionRequest):
    """
    Resume a saved session. Loads session state and prepares for continuation.
    """
    project_dir = settings.PROJECTS_DIR / request.project_id
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail=f"Project not found: {request.project_id}")

    session_path = project_dir / "session.json"
    if not session_path.exists():
        raise HTTPException(status_code=404, detail="No session.json found")

    try:
        with open(session_path, 'r', encoding='utf-8') as f:
            session_data = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read session: {e}")

    # Restore state
    state.current_project_id = request.project_id
    state.current_stage = session_data.get("stage", "RESUMED")
    state.progress = session_data.get("progress", 0)
    state.all_scenes = session_data.get("all_scenes", [])

    # Find final video
    video_path, video_url = find_final_video(request.project_id)
    if video_url:
        state.final_video_path = video_url

    state.topaz_video_path = session_data.get("topaz_video_path")
    state.pipeline_running = False
    state.awaiting_approval = False
    state.awaiting_video_approval = False

    logger.info(f"Session resumed: {request.project_id}")

    # Broadcast state restoration
    await broadcast_event("session_resumed", {
        "project_id": request.project_id,
        "stage": state.current_stage,
        "final_video": video_url
    })

    return {
        "status": "resumed",
        "project_id": request.project_id,
        "stage": state.current_stage,
        "final_video": video_url,
        "all_scenes": state.all_scenes
    }


@router.post("/continue-to-topaz")
async def continue_to_topaz():
    """
    Continue a resumed session to Topaz processing.
    Called after user manually edited the video and wants to proceed.
    """
    if not state.current_project_id:
        raise HTTPException(status_code=400, detail="No active project")

    # Find the current video file
    video_path, video_url = find_final_video(state.current_project_id)
    if not video_path:
        raise HTTPException(status_code=404, detail="No final video found")

    state.final_video_path = video_url

    # Start Topaz processing
    project_dir = settings.PROJECTS_DIR / state.current_project_id
    output_video = project_dir / "final_enhanced.mp4"

    asyncio.create_task(run_topaz_processing(state.current_project_id, video_path, output_video))

    return {
        "status": "started",
        "project_id": state.current_project_id,
        "video_path": video_url
    }


# ============================================================================
# PAGE ROUTE
# ============================================================================

@router.get("/page")
async def control_page():
    """Redirect to control page."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/control")
