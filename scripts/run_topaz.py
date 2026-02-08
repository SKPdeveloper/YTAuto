"""
Run Topaz Video AI upscaling on a specific video file.

Usage:
    python scripts/run_topaz.py <input_video_path>
    python scripts/run_topaz.py  # defaults to final_video.mp4 in latest project
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.modules.topaz_queue import TopazQueue, TopazProgress, TopazTask
from app.modules.topaz_config import topaz_config
from app.utils.logger import logger


async def on_progress(progress: TopazProgress):
    logger.info(f"[Topaz] {progress.stage.value} — {progress.progress_percent:.1f}% | {progress.message}")


async def on_completed(task: TopazTask):
    logger.success(f"[Topaz] COMPLETED!")
    logger.success(f"  FPS output: {task.fps_output_path}")
    logger.success(f"  4K output:  {task.upscaled_output_path}")


async def on_failed(task: TopazTask):
    logger.error(f"[Topaz] FAILED: {task.error_message}")


async def main():
    if len(sys.argv) > 1:
        input_path = Path(sys.argv[1])
    else:
        print("Usage: python scripts/run_topaz.py <input_video_path>")
        sys.exit(1)

    if not input_path.exists():
        logger.error(f"Video not found: {input_path}")
        sys.exit(1)

    if not topaz_config.is_enabled:
        logger.error("Topaz Video AI not detected on this system")
        sys.exit(1)

    logger.info(f"Topaz FFmpeg: {topaz_config.ffmpeg_path}")
    logger.info(f"Topaz Models: {topaz_config.models_path}")
    logger.info(f"Input video:  {input_path}")
    logger.info(f"Output dir:   {input_path.parent}")

    queue = TopazQueue(
        on_progress=on_progress,
        on_completed=on_completed,
        on_failed=on_failed,
    )

    await queue.start()

    project_id = input_path.parent.name
    task = await queue.add_task(
        project_id=project_id,
        scene_number=0,
        input_path=input_path,
        output_dir=input_path.parent,
    )

    logger.info(f"Task queued: {task.task_id}")
    logger.info("Waiting for completion (this may take a while)...")

    completed = await queue.wait_for_completion(timeout=7200)

    if completed:
        logger.success("Topaz processing finished successfully!")
    else:
        logger.error("Topaz processing timed out or failed")

    await queue.stop()


if __name__ == "__main__":
    asyncio.run(main())
