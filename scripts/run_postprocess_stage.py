"""
Run ManifestRenderer directly for a specific project.

This replicates exactly what control_pipeline._assemble_final() does:
loads gen3b_manifest.json and renders the final video.

Usage:
    python scripts/run_postprocess_stage.py proj_be5f50fa8bd1
    python scripts/run_postprocess_stage.py proj_be5f50fa8bd1 --simple   # simple render (no effects)
"""

import sys
import asyncio
import json
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "config" / ".env")

from app.core.config import settings
from loguru import logger


async def run_render(project_id: str, simple: bool = False):
    """Run ManifestRenderer for a project (same as control_pipeline._assemble_final)."""

    project_dir = Path(settings.PROJECTS_DIR) / project_id

    if not project_dir.exists():
        logger.error(f"Project not found: {project_dir}")
        return

    # Check for gen3b_manifest.json (the actual manifest file)
    manifest_path = project_dir / "gen3b_manifest.json"
    if not manifest_path.exists():
        logger.error(f"gen3b_manifest.json not found in {project_dir}")
        logger.info("Run GEN3b stage first, or check if the file exists with a different name")
        return

    # Check inputs
    logger.info("=" * 60)
    logger.info(f"ManifestRenderer Test: {project_id}")
    logger.info(f"Project dir: {project_dir}")
    logger.info("=" * 60)
    logger.info("Checking inputs:")
    logger.info(f"  gen3b_manifest.json: OK")
    logger.info(f"  subtitles.ass:  {'OK' if (project_dir / 'subtitles.ass').exists() else 'MISSING (will skip subtitles)'}")
    logger.info(f"  voiceover.mp3:  {'OK' if (project_dir / 'voiceover.mp3').exists() else 'MISSING'}")
    logger.info(f"  music:          {'OK' if (project_dir / 'music.mp3').exists() or (project_dir / 'music' / 'background.mp3').exists() else 'MISSING'}")
    logger.info(f"  voiceover_timing.json: {'OK' if (project_dir / 'voiceover_timing.json').exists() else 'MISSING (no VO ducking)'}")

    for i in range(1, 7):
        video_path = project_dir / f"scene_{i}" / "video.mp4"
        logger.info(f"  scene_{i}/video.mp4: {'OK' if video_path.exists() else 'MISSING'}")

    # Remove old output if exists (force re-render)
    for old_file in ["final.mp4", "final_video.mp4"]:
        old_path = project_dir / old_file
        if old_path.exists():
            logger.warning(f"  Removing old {old_file} for fresh render")
            old_path.unlink()

    # Load manifest
    logger.info("=" * 60)
    logger.info("Loading manifest...")

    from app.services.gen_models import Gen3bManifest
    from app.services.manifest_renderer import ManifestRenderer

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest_data = json.load(f)

    manifest = Gen3bManifest(**manifest_data)

    logger.info(f"  Total duration: {manifest.total_duration}s")
    logger.info(f"  Scenes: {len(manifest.scenes)}")
    logger.info(f"  Subtitles: {len(manifest.subtitles)}")
    logger.info(f"  Hook: {manifest.hook.style} ({manifest.hook.duration}s)")

    # Render
    renderer = ManifestRenderer()

    if simple:
        logger.info("Using SIMPLE render (no effects, no subtitles)")
        result = await renderer.render_simple(
            manifest=manifest,
            project_dir=project_dir,
            output_filename="final_video.mp4",
        )
    else:
        logger.info("Using FULL render (effects + subtitles + audio mix)")
        result = await renderer.render(
            manifest=manifest,
            project_dir=project_dir,
            output_filename="final_video.mp4",
        )

    logger.success("=" * 60)
    logger.success(f"Render complete: {result}")
    logger.success(f"Size: {result.stat().st_size / 1024 / 1024:.1f} MB")
    logger.success("=" * 60)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/run_postprocess_stage.py <project_id> [--simple]")
        print("Example: python scripts/run_postprocess_stage.py proj_be5f50fa8bd1")
        sys.exit(1)

    project_id = sys.argv[1]
    simple = "--simple" in sys.argv

    asyncio.run(run_render(project_id, simple=simple))
