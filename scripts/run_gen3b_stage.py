"""
Run GEN3b Stage (FFmpeg Manifest Generator) for a specific project.

Usage:
    python scripts/run_gen3b_stage.py proj_b99d6de73b2b
"""

import sys
import asyncio
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "config" / ".env")

from app.pipeline.gen3_stages import Gen3bStage
from app.api.schemas import ProjectData, SceneData
from app.core.config import settings
from loguru import logger
import json


async def run_gen3b_stage(project_id: str):
    """Run GEN3b Stage for a project."""

    project_dir = Path(settings.PROJECTS_DIR) / project_id

    if not project_dir.exists():
        logger.error(f"Project not found: {project_dir}")
        return

    # Check if gen3a_analysis.json exists
    gen3a_path = project_dir / "gen3a_analysis.json"
    if not gen3a_path.exists():
        logger.error(f"gen3a_analysis.json not found - run GEN3a first!")
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
    for i in range(1, 7):
        scene_dir = project_dir / f"scene_{i}"
        video_path = scene_dir / "video.mp4"
        image_path = scene_dir / "image.png"

        scene_brief = brief_scenes[i-1] if i-1 < len(brief_scenes) else {}

        scenes.append(SceneData(
            scene_number=i,
            project_id=project_id,
            description=scene_brief.get("visual_description", f"Scene {i}"),
            image_prompt=scene_brief.get("image_prompt", ""),
            audio_prompt=scene_brief.get("voiceover_segment", ""),
            video_path=str(video_path) if video_path.exists() else None,
            image_path=str(image_path) if image_path.exists() else None,
        ))

    project = ProjectData(
        project_id=project_id,
        topic=brief.get("property", {}).get("name", "Unknown"),
        num_scenes=6,
        project_dir=str(project_dir),
        scenes=scenes,
    )

    logger.info("=" * 60)
    logger.info(f"Running GEN3b Stage for: {project_id}")
    logger.info(f"Project dir: {project_dir}")
    logger.info("=" * 60)

    # Check inputs
    logger.info("Checking inputs:")
    logger.info(f"  gen3a_analysis.json: OK")
    logger.info(f"  project_brief.json: OK")

    # Create and run GEN3b Stage
    stage = Gen3bStage(project=project)

    # Check if can run
    can_run = await stage.can_run()
    logger.info(f"Can run: {can_run}")

    if not can_run:
        manifest_path = project_dir / "manifest.json"
        if manifest_path.exists():
            logger.info("manifest.json already exists!")
            return

    # Execute
    result = await stage.execute()

    if result.success:
        logger.success("GEN3b Stage completed!")
        logger.success(f"Output: {project_dir / 'manifest.json'}")
    else:
        logger.error(f"GEN3b Stage failed: {result.message}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        project_id = "proj_b99d6de73b2b"
    else:
        project_id = sys.argv[1]

    asyncio.run(run_gen3b_stage(project_id))
