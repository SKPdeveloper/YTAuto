"""
Run AudioStage for a specific project.

Usage:
    python scripts/run_audio_stage.py proj_b99d6de73b2b
"""

import sys
import asyncio
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "config" / ".env")

from app.pipeline.audio_stage import AudioStage
from app.api.schemas import ProjectData, SceneData
from app.core.config import settings
from loguru import logger
import json


async def run_audio_stage(project_id: str):
    """Run AudioStage for a project."""

    project_dir = Path(settings.PROJECTS_DIR) / project_id

    if not project_dir.exists():
        logger.error(f"Project not found: {project_dir}")
        return

    # Load project brief
    brief_path = project_dir / "project_brief.json"
    if not brief_path.exists():
        logger.error(f"project_brief.json not found in {project_dir}")
        return

    with open(brief_path, "r", encoding="utf-8") as f:
        brief = json.load(f)

    # Build ProjectData from brief
    scenes = []
    brief_scenes = brief.get("scenes", [])
    for i in range(1, len(brief_scenes) + 1):
        scene_dir = project_dir / f"scene_{i}"
        video_path = scene_dir / "video.mp4"

        # Get scene info from brief
        scene_brief = brief_scenes[i-1] if i-1 < len(brief_scenes) else {}

        scenes.append(SceneData(
            scene_number=i,
            project_id=project_id,
            description=scene_brief.get("visual_description", f"Scene {i}"),
            image_prompt=scene_brief.get("image_prompt", ""),
            audio_prompt=scene_brief.get("voiceover_segment", ""),
            video_path=str(video_path) if video_path.exists() else None,
        ))

    project = ProjectData(
        project_id=project_id,
        topic=brief.get("property", {}).get("name", "Unknown"),
        num_scenes=len(brief_scenes),
        project_dir=str(project_dir),
        scenes=scenes,
    )

    logger.info(f"=" * 60)
    logger.info(f"Running AudioStage for: {project_id}")
    logger.info(f"Project dir: {project_dir}")
    logger.info(f"=" * 60)

    # Create and run AudioStage
    stage = AudioStage(project=project)

    # Check if can run
    can_run = await stage.can_run()
    logger.info(f"Can run: {can_run}")

    if not can_run:
        # Check what exists
        voiceover_exists = (project_dir / "voiceover.mp3").exists()
        music_exists = (project_dir / "music.mp3").exists()
        logger.info(f"voiceover.mp3 exists: {voiceover_exists}")
        logger.info(f"music.mp3 exists: {music_exists}")

        if voiceover_exists and music_exists:
            logger.success("Audio files already exist!")
            return

    # Execute
    result = await stage.execute()

    if result.success:
        logger.success(f"AudioStage completed!")
        logger.success(f"Result: {result.data}")
    else:
        logger.error(f"AudioStage failed: {result.message}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        project_id = "proj_b99d6de73b2b"
    else:
        project_id = sys.argv[1]

    asyncio.run(run_audio_stage(project_id))
