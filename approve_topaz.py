"""
Approve Render and Start Topaz Upscaling

Use this script after reviewing the rendered video (final.mp4).
Only run Topaz if you're satisfied with the montage quality.

Usage:
    python approve_topaz.py proj_de28aebfbe30
    python approve_topaz.py proj_de28aebfbe30 --reject
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.core.config import settings
from app.core.state_manager import state_manager
from app.core.orchestrator import ProjectOrchestrator
from app.utils.logger import logger


async def approve_and_run(project_id: str):
    """Approve render and start Topaz upscaling."""

    await state_manager.initialize()
    orchestrator = ProjectOrchestrator()

    project_dir = settings.PROJECTS_DIR / project_id
    final_video = project_dir / "final.mp4"

    if not final_video.exists():
        logger.error(f"Final video not found: {final_video}")
        return False

    # Show video info
    size_mb = final_video.stat().st_size / (1024 * 1024)
    logger.info(f"Video to approve: {final_video}")
    logger.info(f"Size: {size_mb:.1f} MB")

    # Approve and run Topaz
    success = await orchestrator.approve_and_run_topaz(project_id)

    if success:
        logger.success("Topaz upscaling started!")
        logger.info("This will take 15-45 minutes depending on video length.")
    else:
        logger.error("Failed to start Topaz. Check project status.")

    return success


async def reject_render(project_id: str):
    """Reject render and pause project."""

    await state_manager.initialize()
    orchestrator = ProjectOrchestrator()

    success = await orchestrator.reject_render(project_id)

    if success:
        logger.warning(f"Render rejected for {project_id}")
        logger.info("Project paused. Fix issues and re-run render.")

    return success


async def main():
    if len(sys.argv) < 2:
        print("Usage: python approve_topaz.py <project_id> [--reject]")
        print("Example: python approve_topaz.py proj_de28aebfbe30")
        return

    project_id = sys.argv[1]
    reject = "--reject" in sys.argv

    if reject:
        await reject_render(project_id)
    else:
        await approve_and_run(project_id)


if __name__ == "__main__":
    asyncio.run(main())
