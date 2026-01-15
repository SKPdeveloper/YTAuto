"""
FastAPI Routes for Web UI.
Page routes (HTML) and API routes (JSON/HTML partials).
"""

import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional, List
import shutil

from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.server.websocket import ConnectionManager
from app.utils.logger import logger
from app.web.channel_service import get_channel_service
from app.services.prompt_router import PromptRouter
from app.web.database import (
    init_database,
    get_all_channels,
    get_channel,
    create_channel,
    get_channel_stats,
    get_channel_projects,
    get_project,
    get_project_scenes,
    get_project_logs,
    create_project,
    update_project_status,
    add_log,
)

# ============================================================================
# APP SETUP
# ============================================================================

app = FastAPI(
    title="Edible House Automator",
    description="AI Video Generation Pipeline Web UI",
    version="1.0.0"
)

# Templates
templates_path = Path(__file__).parent.parent / "web" / "templates"
templates = Jinja2Templates(directory=str(templates_path))

# Static files
static_path = Path(__file__).parent.parent / "web" / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

# Projects static files (for serving generated images/videos)
projects_path = Path.cwd() / "projects"
if projects_path.exists():
    app.mount("/projects", StaticFiles(directory=str(projects_path)), name="projects")

# WebSocket connection manager
ws_manager = ConnectionManager()

# Import and register control routes
from app.api.control_routes import router as control_router, set_ws_manager
set_ws_manager(ws_manager)


# ============================================================================
# WEBSOCKET ENDPOINT
# ============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time updates.

    Clients connect here to receive:
    - Project status updates
    - Scene generation progress
    - Approval requests
    - Error notifications
    """
    await ws_manager.connect(websocket)
    try:
        while True:
            # Receive messages from client (for future bidirectional communication)
            data = await websocket.receive_json()

            # Handle client messages
            event = data.get("event")
            payload = data.get("data", {})

            if event == "ping":
                await websocket.send_json({"event": "pong", "data": {}})

            elif event == "subscribe":
                # Subscribe to project updates
                project_id = payload.get("project_id")
                if project_id:
                    ws_manager.subscribe(websocket, project_id)

            elif event == "unsubscribe":
                project_id = payload.get("project_id")
                if project_id:
                    ws_manager.unsubscribe(websocket, project_id)

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        ws_manager.disconnect(websocket)


def get_ws_manager() -> ConnectionManager:
    """Get WebSocket manager instance for dependency injection."""
    return ws_manager


# ============================================================================
# STARTUP / SHUTDOWN
# ============================================================================

@app.on_event("startup")
async def startup():
    """Initialize database on startup."""
    logger.info("Starting Web UI server...")
    await init_database()

    # Register control routes
    app.include_router(control_router)

    logger.info(f"Web UI available at http://{settings.WEB_HOST}:{settings.WEB_PORT}")
    logger.info(f"Control panel: http://{settings.WEB_HOST}:{settings.WEB_PORT}/control")


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown."""
    logger.info("Shutting down Web UI server...")


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

async def get_topaz_queue_size() -> int:
    """Get current Topaz queue size from orchestrator."""
    try:
        # Try to import and get from existing topaz_queue
        from app.modules.topaz_queue import get_topaz_queue
        queue = get_topaz_queue()
        return queue.get_queue_size() if queue else 0
    except Exception:
        return 0


# ============================================================================
# PAGE ROUTES (HTML)
# ============================================================================

@app.get("/control", response_class=HTMLResponse)
async def control_page(request: Request):
    """Control Panel page."""
    return templates.TemplateResponse("control.html", {"request": request})


@app.get("/", response_class=HTMLResponse)
async def homepage(request: Request):
    """Homepage - Channel list."""
    channels = await get_all_channels()

    # Calculate totals
    total_active = sum(c.get('active_projects', 0) or 0 for c in channels)
    total_ready = sum(c.get('ready_projects', 0) or 0 for c in channels)
    topaz_queue_size = await get_topaz_queue_size()

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "channels": channels,
            "total_active": total_active,
            "total_ready": total_ready,
            "topaz_queue_size": topaz_queue_size,
        }
    )


@app.get("/channel/{channel_id}", response_class=HTMLResponse)
async def channel_dashboard(
    request: Request,
    channel_id: int,
    sort: str = "date_desc"
):
    """Channel dashboard with projects list."""
    channel = await get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    stats = await get_channel_stats(channel_id)
    projects = await get_channel_projects(channel_id, sort=sort)

    return templates.TemplateResponse(
        "channel/dashboard.html",
        {
            "request": request,
            "channel": channel,
            "stats": stats,
            "projects": projects,
            "sort": sort,
        }
    )


@app.get("/channel/{channel_id}/new", response_class=HTMLResponse)
async def new_project_wizard(request: Request, channel_id: int, mode: str = "auto"):
    """
    New project creation wizard.

    Args:
        mode: 'auto' = AI generates topic, 'idea' = user provides hint
    """
    channel = await get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    return templates.TemplateResponse(
        "channel/new_project.html",
        {
            "request": request,
            "channel": channel,
            "mode": mode,
        }
    )


@app.get("/channel/{channel_id}/project/{project_id}", response_class=HTMLResponse)
async def project_detail(
    request: Request,
    channel_id: int,
    project_id: int
):
    """Project detail page with real-time updates."""
    channel = await get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    project = await get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    scenes = await get_project_scenes(project_id)
    logs = await get_project_logs(project_id, limit=50)

    return templates.TemplateResponse(
        "channel/project.html",
        {
            "request": request,
            "channel": channel,
            "project": project,
            "scenes": scenes,
            "logs": logs,
        }
    )


# ============================================================================
# MODAL ROUTES (HTML Partials)
# ============================================================================

@app.get("/api/modal/new-channel", response_class=HTMLResponse)
async def new_channel_modal(request: Request):
    """Return new channel modal HTML."""
    return templates.TemplateResponse(
        "modals/new_channel.html",
        {"request": request}
    )


# ============================================================================
# CHANNEL API ROUTES
# ============================================================================

@app.post("/api/channel/create")
async def create_channel_endpoint(
    request: Request,
    name: str = Form(...),
    folder_path: str = Form(...),
    default_format: str = Form("9:16"),
    default_engine: str = Form("higgsfield"),
    env_file: Optional[UploadFile] = File(None),
    prompt_generation_file: Optional[UploadFile] = File(None),
    prompt_validation_file: Optional[UploadFile] = File(None),
):
    """Create a new channel with file uploads."""
    try:
        # Validate folder exists
        folder = Path(folder_path)
        if not folder.exists():
            raise HTTPException(
                status_code=400,
                detail=f"Folder does not exist: {folder_path}"
            )

        # Save uploaded files to folder
        if env_file and env_file.filename:
            env_path = folder / ".env"
            content = await env_file.read()
            env_path.write_bytes(content)
            logger.info(f"Saved .env to {env_path}")

        if prompt_generation_file and prompt_generation_file.filename:
            gen_path = folder / "GEN1.txt"
            content = await prompt_generation_file.read()
            gen_path.write_bytes(content)
            logger.info(f"Saved prompt generation file to {gen_path}")

        if prompt_validation_file and prompt_validation_file.filename:
            val_path = folder / "VAL_IMG.txt"
            content = await prompt_validation_file.read()
            val_path.write_bytes(content)
            logger.info(f"Saved prompt validation file to {val_path}")

        # Create channel in database
        channel_id = await create_channel(
            name=name,
            folder_path=str(folder),
            default_format=default_format,
            default_engine=default_engine
        )

        logger.info(f"Created channel '{name}' with ID {channel_id}")

        # Redirect to homepage
        return RedirectResponse(url="/", status_code=303)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating channel: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# SCRIPT GENERATION API
# ============================================================================

@app.post("/api/channel/{channel_id}/generate-scripts", response_class=HTMLResponse)
async def generate_scripts(
    request: Request,
    channel_id: int,
    format: str = Form(...),
    duration_seconds: int = Form(...),
    engine: str = Form(...),
    topic: str = Form(...),
    generation_mode: str = Form("auto"),
):
    """
    Generate script using PromptRouter GEN1.

    If topic is '__AUTO_GENERATE__', GEN1 will create the topic automatically.
    """
    try:
        channel = await get_channel(channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")

        # Calculate scenes based on duration (2 scenes for 10 sec video)
        num_scenes = max(2, min(10, duration_seconds // 5))

        # Handle auto-generation mode
        is_auto_mode = (topic == "__AUTO_GENERATE__" or generation_mode == "auto")

        if is_auto_mode:
            logger.info(f"Generating script via PromptRouter GEN1 (AUTO MODE)...")
            logger.info(f"  Mode: AUTO - AI will generate topic")
            actual_topic = None  # GEN1 will generate topic
        else:
            logger.info(f"Generating script via PromptRouter GEN1 (IDEA MODE)...")
            logger.info(f"  User idea: {topic}")
            actual_topic = topic

        logger.info(f"  Scenes: {num_scenes}")
        logger.info(f"  Duration: {duration_seconds}s")

        # Use PromptRouter for real script generation
        router = PromptRouter()
        gen1_output = await router.run_gen1(
            topic=actual_topic,  # None = auto-generate
            num_scenes=num_scenes,
            style="cinematic food fantasy",
            target_audience="YouTube Shorts viewers",
            duration_seconds=duration_seconds,
        )

        if not gen1_output:
            raise Exception("GEN1 returned empty output")

        # Format script for display
        script_preview = f"# {gen1_output.metadata.title}\n\n"
        script_preview += f"**Hook:** {gen1_output.metadata.hook_line}\n\n"
        script_preview += f"**Summary:** {gen1_output.youtube_description[:200]}...\n\n"
        script_preview += "---\n\n"

        for scene in gen1_output.scenes:
            script_preview += f"## Scene {scene.scene_number}: {scene.scene_name}\n"
            script_preview += f"**Duration:** {scene.duration_seconds}s\n"
            script_preview += f"**Voiceover:** {scene.voiceover}\n"
            script_preview += f"**Visual:** {scene.visual_concept.subject}\n"
            script_preview += f"**Camera:** {scene.camera_intent.movement}\n\n"

        # Return single script (GEN1 output) - user can regenerate if needed
        scripts = [script_preview]

        return templates.TemplateResponse(
            "components/scripts_options.html",
            {
                "request": request,
                "scripts": scripts,
                "channel_id": channel_id,
                "enumerate": enumerate,
                "gen1_json": gen1_output.model_dump_json(),  # Store for GEN2
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating script: {e}")
        import traceback
        traceback.print_exc()
        return templates.TemplateResponse(
            "components/scripts_options.html",
            {
                "request": request,
                "error": f"Помилка генерації: {str(e)}",
                "channel_id": channel_id,
            }
        )


# ============================================================================
# PROJECT API ROUTES
# ============================================================================

@app.post("/api/channel/{channel_id}/project/create")
async def create_project_endpoint(
    request: Request,
    channel_id: int,
    format: str = Form(...),
    duration_seconds: int = Form(...),
    engine: str = Form(...),
    topic: str = Form(...),
    selected_script: str = Form(...),
    project_name: Optional[str] = Form(None),
):
    """Create and start a new project."""
    try:
        channel = await get_channel(channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")

        # Generate project name if not provided
        if not project_name:
            # Count existing projects
            projects = await get_channel_projects(channel_id)
            project_num = len(projects) + 1
            topic_short = topic[:30] + "..." if len(topic) > 30 else topic
            project_name = f"Project_{project_num:03d} - {topic_short}"

        # Create project in database
        project_id = await create_project(
            channel_id=channel_id,
            name=project_name,
            topic=topic,
            format=format,
            duration_seconds=duration_seconds,
            engine=engine,
            selected_script=selected_script,
        )

        # Add initial log
        await add_log(project_id, f"Project created: {project_name}", "success")
        await add_log(project_id, f"Engine: {engine}, Format: {format}, Duration: {duration_seconds}s", "info")

        logger.info(f"Created project '{project_name}' with ID {project_id}")

        # Start orchestrator pipeline in background
        channel_service = get_channel_service()
        pipeline_started = await channel_service.start_project_pipeline(
            web_project_id=project_id,
            channel_folder=channel.get('folder_path', ''),
            topic=topic,
            selected_script=selected_script,
            format=format,
            duration_seconds=duration_seconds,
            engine=engine,
        )

        if not pipeline_started:
            await add_log(project_id, "Warning: Pipeline failed to start", "warning")

        # Redirect to project page
        return RedirectResponse(
            url=f"/channel/{channel_id}/project/{project_id}",
            status_code=303
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating project: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# PROJECT STATUS API (HTMX Partials)
# ============================================================================

@app.get("/api/project/{project_id}/status", response_class=HTMLResponse)
async def get_project_status_partial(request: Request, project_id: int):
    """Get project status HTML partial for HTMX polling."""
    project = await get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return templates.TemplateResponse(
        "components/project_status.html",
        {"request": request, "project": project}
    )


@app.get("/api/project/{project_id}/scenes", response_class=HTMLResponse)
async def get_scenes_partial(request: Request, project_id: int):
    """Get scenes list HTML partial for HTMX polling."""
    scenes = await get_project_scenes(project_id)

    return templates.TemplateResponse(
        "components/scenes_list.html",
        {"request": request, "scenes": scenes}
    )


@app.get("/api/project/{project_id}/logs", response_class=HTMLResponse)
async def get_logs_partial(request: Request, project_id: int):
    """Get logs HTML partial for HTMX polling."""
    logs = await get_project_logs(project_id, limit=50)

    return templates.TemplateResponse(
        "components/logs_list.html",
        {"request": request, "logs": logs}
    )


# ============================================================================
# PROJECT ACTIONS
# ============================================================================

@app.post("/api/project/{project_id}/pause")
async def pause_project(project_id: int):
    """Pause project processing."""
    try:
        # Stop orchestrator task if running
        channel_service = get_channel_service()
        await channel_service.pause_project(project_id)

        await update_project_status(project_id, "paused")
        await add_log(project_id, "Project paused by user", "warning")
        return JSONResponse({"status": "paused"})
    except Exception as e:
        logger.error(f"Error pausing project: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/project/{project_id}/cancel")
async def cancel_project(project_id: int):
    """Cancel project processing."""
    try:
        # Cancel orchestrator task if running
        channel_service = get_channel_service()
        await channel_service.cancel_project(project_id)

        await update_project_status(project_id, "failed")
        await add_log(project_id, "Project cancelled by user", "error")
        return JSONResponse({"status": "cancelled"})
    except Exception as e:
        logger.error(f"Error cancelling project: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# TOPAZ QUEUE STATUS
# ============================================================================

@app.get("/api/topaz/status", response_class=HTMLResponse)
async def get_topaz_status():
    """Get Topaz queue status for navbar."""
    queue_size = await get_topaz_queue_size()

    if queue_size > 0:
        return HTMLResponse(f"Topaz: {queue_size} in queue")
    else:
        return HTMLResponse("Topaz: Idle")


# ============================================================================
# SETTINGS API
# ============================================================================

@app.get("/api/modal/settings", response_class=HTMLResponse)
async def settings_modal(request: Request):
    """Return settings modal HTML."""
    return templates.TemplateResponse(
        "modals/settings.html",
        {"request": request, "settings": settings}
    )


@app.post("/api/settings/save")
async def save_settings(
    request: Request,
    topaz_fps_model: str = Form("apf-1"),
    topaz_upscale_model: str = Form("prob-3"),
    topaz_target_fps: int = Form(60),
    topaz_scale: int = Form(2),
):
    """
    Save global settings.
    Note: This updates runtime settings. For persistent changes, edit .env file.
    """
    try:
        # Update runtime settings
        settings.TOPAZ_FPS_MODEL = topaz_fps_model
        settings.TOPAZ_UPSCALE_MODEL = topaz_upscale_model
        settings.TOPAZ_TARGET_FPS = topaz_target_fps
        settings.TOPAZ_SCALE = topaz_scale

        logger.info(f"Settings updated: Topaz FPS={topaz_target_fps}, Scale={topaz_scale}")

        # Return success response for HTMX
        return HTMLResponse(
            content='''
            <script>
                showToast('Налаштування збережено!', 'success');
                document.querySelector('.modal-backdrop').remove();
            </script>
            ''',
            status_code=200
        )

    except Exception as e:
        logger.error(f"Error saving settings: {e}")
        return HTMLResponse(
            content=f'''
            <script>
                showToast('Помилка збереження: {str(e)}', 'error');
            </script>
            ''',
            status_code=500
        )


@app.get("/api/processing/status", response_class=HTMLResponse)
async def get_processing_status():
    """Get current processing engine status for navbar."""
    return HTMLResponse(
        '''<span class="text-blue-600 flex items-center space-x-1">
            <i data-lucide="monitor" class="w-4 h-4"></i>
            <span>Topaz</span>
        </span>'''
    )


# ============================================================================
# HEALTH CHECK
# ============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0",
        "processing_engine": "topaz",
    }
