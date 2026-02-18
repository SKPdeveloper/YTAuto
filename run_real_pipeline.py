"""
REAL PIPELINE LAUNCHER - Full End-to-End Pipeline

Запускає повний pipeline від початку до кінця:
1. GEN1 (Creative Director) + GEN2 (Visual Director)
2. PRIMARY scene selection (4 candidates -> Web UI -> User choice)
3. Remaining scenes (with/without reference based on reference_type)
4. Video generation (Kling i2v)
5. Web UI approval for each video (or auto-approve)
6. Post-processing: Voiceover (ElevenLabs) + Assembly (FFmpeg) + Topaz (FPS + 4K)

Використання:
    python run_real_pipeline.py
    python run_real_pipeline.py "Chocolate Train Station"
    python run_real_pipeline.py --free
    python run_real_pipeline.py --free -y
    python run_real_pipeline.py --free --auto-approve    # Full auto mode with post-processing
    python run_real_pipeline.py --free --full            # Same as --auto-approve
    python run_real_pipeline.py --resume proj_623ddd05d766
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

import uvicorn

from app.core.config import settings
from app.core.state_manager import state_manager
from app.core.orchestrator import ProjectOrchestrator
from app.utils.logger import logger


# ============================================================================
# BANNER
# ============================================================================

BANNER = """
========================================================================

     EDIBLE HOUSE AUTOMATOR
     AI Video Generation Pipeline

     Version: 2.0.0

========================================================================
"""


# ============================================================================
# WEB SERVER (background task in same event loop)
# ============================================================================

async def start_web_server_background() -> uvicorn.Server:
    """
    Запускає uvicorn веб-сервер як фонову asyncio задачу.

    Працює в тому ж event loop що й pipeline — вони шерять один control_state,
    тому asyncio.Event() для video approval працює коректно.

    Returns:
        uvicorn.Server instance (для graceful shutdown)
    """
    config = uvicorn.Config(
        "app.api.routes:app",
        host=settings.WEB_HOST,
        port=settings.WEB_PORT,
        log_level="warning",  # Менше шуму в консолі — pipeline логи важливіші
        install_signal_handlers=False,  # Pipeline сам обробляє Ctrl+C
    )
    server = uvicorn.Server(config)

    # Запускаємо як фонову задачу
    asyncio.create_task(server.serve())

    # Чекаємо поки сервер дійсно стартує
    for _ in range(50):  # max 5 секунд
        if server.started:
            break
        await asyncio.sleep(0.1)

    if server.started:
        logger.success(f"Web UI started: http://{settings.WEB_HOST}:{settings.WEB_PORT}")
        logger.info(f"Control panel: http://{settings.WEB_HOST}:{settings.WEB_PORT}/control")
    else:
        logger.warning("Web UI server did not start in time — approval via web may not work")

    return server


# ============================================================================
# CONFIGURATION CHECK
# ============================================================================

def check_configuration() -> bool:
    """
    Перевіряє що всі необхідні API ключі та конфігурація на місці.

    Returns:
        True якщо все OK, False якщо чогось не вистачає
    """
    logger.info("Checking configuration...")

    issues = []

    # Required API keys
    required_keys = {
        "GOOGLE_GEMINI_API_KEY": settings.GOOGLE_GEMINI_API_KEY,
        "ADSPOWER_PROFILE_ID": settings.ADSPOWER_PROFILE_ID,
    }

    # Optional but recommended
    optional_keys = {
        "ELEVENLABS_API_KEY": settings.ELEVENLABS_API_KEY,
    }

    for name, value in required_keys.items():
        if not value:
            issues.append(f"  - {name} is missing")
            logger.error(f"MISSING: {name}")
        else:
            masked = value[:4] + "..." + value[-4:] if len(value) > 8 else "***"
            logger.success(f"OK: {name} = {masked}")

    for name, value in optional_keys.items():
        if value:
            masked = value[:4] + "..." + value[-4:] if len(value) > 8 else "***"
            logger.success(f"OK: {name} = {masked}")
        else:
            logger.warning(f"OPTIONAL: {name} not set")

    # Check Topaz (optional but recommended)
    if settings.TOPAZ_FFMPEG_PATH.exists():
        logger.success(f"OK: Topaz FFmpeg found at {settings.TOPAZ_FFMPEG_PATH}")
    else:
        logger.warning(f"WARNING: Topaz FFmpeg not found at {settings.TOPAZ_FFMPEG_PATH}")
        logger.warning("  -> Topaz upscaling will be skipped")

    # Check prompt files
    prompt_files = [
        ("GEN1.txt", Path("config/GEN1.txt")),
        ("GEN2.txt", Path("config/GEN2.txt")),
        ("VAL_IMG.txt", Path("config/VAL_IMG.txt")),
    ]

    for name, path in prompt_files:
        if path.exists():
            size_kb = path.stat().st_size / 1024
            logger.success(f"OK: {name} ({size_kb:.1f} KB)")
        else:
            issues.append(f"  - {name} not found at {path}")
            logger.error(f"MISSING: {name}")

    if issues:
        logger.error("\nConfiguration issues found:")
        for issue in issues:
            logger.error(issue)
        return False

    logger.success("\nAll configuration OK!")
    return True


# ============================================================================
# PIPELINE MONITOR
# ============================================================================

class PipelineMonitor:
    """Моніторить прогрес pipeline та виводить статус."""

    def __init__(self, orchestrator: ProjectOrchestrator, project_id: str):
        self.orchestrator = orchestrator
        self.project_id = project_id
        self.start_time = datetime.now()
        self._running = True

    async def monitor(self):
        """Background task що періодично виводить статус"""
        while self._running:
            await asyncio.sleep(30)

            if not self._running:
                break

            project = self.orchestrator.active_projects.get(self.project_id)
            if not project:
                continue

            elapsed = datetime.now() - self.start_time
            elapsed_str = str(elapsed).split('.')[0]

            scene_stats = {}
            for scene in project.scenes:
                status = str(scene.status)
                scene_stats[status] = scene_stats.get(status, 0) + 1

            logger.info(f"\n{'='*50}")
            logger.info(f"PROGRESS UPDATE (elapsed: {elapsed_str})")
            logger.info(f"{'='*50}")
            logger.info(f"Stage: {project.current_stage}")
            logger.info(f"Status: {project.status}")
            logger.info(f"Scenes: {scene_stats}")
            logger.info(f"{'='*50}\n")

    def stop(self):
        """Зупиняє моніторинг"""
        self._running = False


# ============================================================================
# MAIN PIPELINE
# ============================================================================

async def run_pipeline(topic: Optional[str] = None, num_scenes: int = 8, auto_approve: bool = False):
    """
    Запускає повний pipeline.

    Args:
        topic: Тема для генерації (None = FREE TOPIC)
        num_scenes: Кількість сцен (default: 6)
        auto_approve: Автоматично апрувить всі сцени та запускає post-processing
    """

    # STEP 1: Initialize State Manager
    logger.info("\n[STEP 1] Initializing database...")
    await state_manager.initialize()
    logger.success("Database ready")

    # STEP 2: Create Orchestrator
    logger.info("\n[STEP 2] Creating Orchestrator...")
    orchestrator = ProjectOrchestrator()
    logger.success("Orchestrator ready")

    # STEP 3: Create Project
    logger.info("\n[STEP 3] Creating project...")

    if topic:
        logger.info(f"Topic: {topic}")
    else:
        logger.info("Topic: FREE (AI will choose)")

    project = await orchestrator.create_project(
        topic=topic or "FREE_TOPIC",
        num_scenes=num_scenes,
        style="educational",
        target_audience="general"
    )

    project_id = project.project_id
    logger.success(f"Project created: {project_id}")
    logger.info(f"Directory: projects/{project_id}")

    # STEP 4: Start Web Server + Background Tasks
    logger.info("\n[STEP 4] Starting web server & background tasks...")

    web_server = await start_web_server_background()

    monitor = PipelineMonitor(orchestrator, project_id)
    monitor_task = asyncio.create_task(monitor.monitor())

    # STEP 5: Start Pipeline
    logger.info("\n" + "=" * 70)
    logger.info("STARTING FULL PIPELINE")
    logger.info("=" * 70)
    logger.info("")
    logger.info("Pipeline stages:")
    logger.info("  1. Script Generation (GEN1 + GEN2)")
    logger.info("  2. PRIMARY Scene (4 candidates)")
    logger.info("  3. Remaining Scenes (parallel processing)")
    logger.info("  4. Video Generation (Kling/Seedance)")
    logger.info("  5. Post-processing (Voiceover + Assembly + Topaz)")
    logger.info("")

    try:
        await orchestrator.start_pipeline(project_id, auto_approve=auto_approve)

        logger.info("\n" + "=" * 70)
        logger.info("PIPELINE COMPLETE")
        logger.info("=" * 70)

    except KeyboardInterrupt:
        logger.info("\nReceived interrupt signal...")

    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        import traceback
        traceback.print_exc()

    finally:
        monitor.stop()
        monitor_task.cancel()

        project = orchestrator.active_projects.get(project_id)
        if project:
            logger.info("\n" + "=" * 70)
            logger.info("FINAL STATUS")
            logger.info("=" * 70)
            logger.info(f"Project: {project_id}")
            logger.info(f"Status: {project.status}")
            logger.info(f"Stage: {project.current_stage}")

            if project.scenes:
                logger.info(f"\nScenes:")
                for scene in project.scenes:
                    logger.info(f"  [{scene.scene_number}] {scene.status}")

            if project.error_message:
                logger.error(f"\nLast error: {project.error_message}")

            logger.info(f"\nProject directory: projects/{project_id}")
            logger.info("=" * 70)

        # Shutdown visual engine
        await orchestrator.shutdown_visual_engine()

        # Shutdown web server
        web_server.should_exit = True


# ============================================================================
# RESUME PIPELINE
# ============================================================================

async def resume_pipeline(project_id: str):
    """Відновлює pipeline з диску."""

    logger.info("\n[STEP 1] Initializing database...")
    await state_manager.initialize()
    logger.success("Database ready")

    logger.info("\n[STEP 2] Creating Orchestrator...")
    orchestrator = ProjectOrchestrator()
    logger.success("Orchestrator ready")

    logger.info("\n[STEP 3] Starting web server & background tasks...")
    web_server = await start_web_server_background()

    monitor = PipelineMonitor(orchestrator, project_id)
    monitor_task = asyncio.create_task(monitor.monitor())

    logger.info("\n" + "=" * 70)
    logger.info(f"RESUMING PIPELINE: {project_id}")
    logger.info("=" * 70)

    try:
        project = await orchestrator.resume_from_disk(project_id)

        if not project:
            logger.error(f"Failed to load project {project_id} from disk")
            return

        logger.info("\n" + "=" * 70)
        logger.info("PIPELINE RESUMED AND COMPLETED")
        logger.info("=" * 70)

    except KeyboardInterrupt:
        logger.info("\nPipeline interrupted by user")

    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        import traceback
        traceback.print_exc()

    finally:
        monitor.stop()
        monitor_task.cancel()

        project = orchestrator.active_projects.get(project_id)
        if project:
            logger.info("\n" + "=" * 70)
            logger.info("FINAL STATUS")
            logger.info("=" * 70)
            logger.info(f"Project: {project_id}")
            logger.info(f"Status: {project.status}")
            logger.info(f"Stage: {project.current_stage}")

            if project.scenes:
                logger.info(f"\nScenes:")
                for scene in project.scenes:
                    logger.info(f"  [{scene.scene_number}] {scene.status}")

            logger.info(f"\nProject directory: projects/{project_id}")
            logger.info("=" * 70)

        await orchestrator.shutdown_visual_engine()

        # Shutdown web server
        web_server.should_exit = True


# ============================================================================
# ENTRY POINT
# ============================================================================

async def main():
    """Main entry point"""
    print(BANNER)

    # Parse arguments
    topic = None
    num_scenes = 8
    auto_confirm = False
    auto_approve = False
    resume_project_id = None

    args = sys.argv[1:]

    if "--yes" in args or "-y" in args:
        auto_confirm = True
        args = [a for a in args if a not in ("--yes", "-y")]

    if "--auto-approve" in args or "--full" in args:
        auto_approve = True
        auto_confirm = True  # --auto-approve implies --yes
        args = [a for a in args if a not in ("--auto-approve", "--full")]

    if "--resume" in args:
        idx = args.index("--resume")
        if idx + 1 < len(args):
            resume_project_id = args[idx + 1]
            args = args[:idx] + args[idx+2:]
        else:
            logger.error("--resume requires project_id argument")
            return

    if "--free" in args:
        topic = None
        args = [a for a in args if a != "--free"]

    if "--scenes" in args:
        idx = args.index("--scenes")
        if idx + 1 < len(args):
            num_scenes = int(args[idx + 1])
            args = args[:idx] + args[idx+2:]

    if args:
        topic = " ".join(args)

    # Show usage
    logger.info("Usage:")
    logger.info('  python run_real_pipeline.py "Chocolate Train Station"')
    logger.info('  python run_real_pipeline.py --free')
    logger.info('  python run_real_pipeline.py --free -y')
    logger.info('  python run_real_pipeline.py --free --auto-approve  # Full auto mode')
    logger.info('  python run_real_pipeline.py --free --full          # Same as --auto-approve')
    logger.info('  python run_real_pipeline.py --resume proj_xxx')
    logger.info("")

    # Check configuration
    if not check_configuration():
        logger.error("\nConfiguration check failed. Please fix issues above.")
        return

    # Handle resume mode
    if resume_project_id:
        logger.info("\n" + "-" * 50)
        logger.info(f"RESUME MODE: {resume_project_id}")
        logger.info("-" * 50)

        project_dir = Path("projects") / resume_project_id
        if not project_dir.exists():
            logger.error(f"Project directory not found: {project_dir}")
            return

        if not auto_confirm:
            confirm = input("\nResume pipeline? (y/n): ").strip().lower()
            if confirm != 'y':
                logger.info("Cancelled by user")
                return

        await resume_pipeline(project_id=resume_project_id)
        return

    # Normal mode
    logger.info("\n" + "-" * 50)
    logger.info(f"Topic: {topic or 'FREE (AI will choose)'}")
    logger.info(f"Scenes: {num_scenes}")
    logger.info(f"Auto-approve: {'YES (full auto mode)' if auto_approve else 'NO (manual approval)'}")
    logger.info("-" * 50)

    if not auto_confirm:
        confirm = input("\nStart pipeline? (y/n): ").strip().lower()
        if confirm != 'y':
            logger.info("Cancelled by user")
            return

    await run_pipeline(topic=topic, num_scenes=num_scenes, auto_approve=auto_approve)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\nFatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
