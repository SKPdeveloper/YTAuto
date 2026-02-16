"""
Test script: GEN1 → GEN2 → merge (v8.3.0 validation)

Runs only the prompt generation pipeline (no image/video generation).
Outputs project_brief.json to projects/<project_id>/.
"""

import asyncio
import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from app.core.config import settings
from app.services.prompt_router import PromptRouter
from app.utils.logger import logger


async def main():
    logger.info("=" * 70)
    logger.info("TEST: GEN1 → GEN2 → merge (v8.3.0)")
    logger.info("=" * 70)

    # Initialize PromptRouter
    router = PromptRouter()

    project_id = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    project_dir = settings.PROJECTS_DIR / project_id
    project_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Project ID: {project_id}")
    logger.info(f"Project dir: {project_dir}")

    # Run the full GEN1 → GEN2 → merge pipeline
    result = await router.generate_full_project(
        topic=None,  # Free topic — AI chooses
        num_scenes=8,
        project_id=project_id,
    )

    if result is None:
        logger.error("Pipeline returned None — generation failed")
        return

    # Save project_brief.json
    brief_path = project_dir / "project_brief.json"
    brief_data = result.model_dump(mode="json")
    with open(brief_path, "w", encoding="utf-8") as f:
        json.dump(brief_data, f, indent=2, ensure_ascii=False)

    logger.success(f"project_brief.json saved: {brief_path}")
    logger.success(f"  Scenes: {len(result.scenes)}")
    logger.success(f"  Title: {result.youtube.title if result.youtube else 'N/A'}")

    # Check new v8.3.0 fields
    logger.info("\n--- v8.3.0 field check ---")

    # on_screen_text
    for scene in result.scenes:
        ost = getattr(scene, "on_screen_text", "")
        logger.info(f"  Scene {scene.scene_number} on_screen_text: {ost!r}")

    # viral assessment
    if result.viral_audit and result.viral_audit.scores:
        scores = result.viral_audit.scores
        logger.info(f"  mute_test: {scores.mute_test}")
        logger.info(f"  categorization_clarity: {scores.categorization_clarity}")
        logger.info(f"  niche_alignment: {scores.niche_alignment}")

    # tags
    if result.youtube:
        logger.info(f"  Tags: {result.youtube.tags}")
        desc = result.youtube.description or ""
        hashtags = [w for w in desc.split() if w.startswith("#")]
        logger.info(f"  Description hashtags: {hashtags}")
        if "#glazecity" in desc.lower():
            logger.error("  FAIL: #glazecity found in description!")
        else:
            logger.success("  PASS: No #glazecity in description")

    logger.info("=" * 70)
    logger.info("DONE")
    logger.info("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
