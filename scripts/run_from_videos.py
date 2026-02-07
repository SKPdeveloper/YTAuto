"""
Run pipeline from raw videos stage onwards.

Assumes raw videos are already in scene_N/video.mp4 folders.
Follows the exact control_pipeline workflow:
  Audio -> Validate Audio Artifacts -> GEN3a -> GEN3b -> PostProcess (ManifestRenderer)

Usage:
    python scripts/run_from_videos.py proj_63328bc192cc
    python scripts/run_from_videos.py proj_63328bc192cc --skip-audio   # if audio already exists
    python scripts/run_from_videos.py proj_63328bc192cc --render-only  # only re-render (skip audio/gen3a/gen3b)
"""

import sys
import asyncio
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "config" / ".env")

from app.pipeline.audio_stage import AudioStage
from app.pipeline.gen3_stages import Gen3aStage, Gen3bStage
from app.pipeline.postprocess_stage import PostProcessStage
from app.api.schemas import ProjectData, SceneData
from app.core.config import settings
from loguru import logger
import json


def build_project(project_id: str) -> ProjectData | None:
    """Build ProjectData from project_brief.json on disk."""

    project_dir = Path(settings.PROJECTS_DIR) / project_id

    if not project_dir.exists():
        logger.error(f"Project not found: {project_dir}")
        return None

    brief_path = project_dir / "project_brief.json"
    if not brief_path.exists():
        logger.error(f"project_brief.json not found in {project_dir}")
        return None

    with open(brief_path, "r", encoding="utf-8") as f:
        brief = json.load(f)

    scenes = []
    brief_scenes = brief.get("scenes", [])
    for i in range(1, len(brief_scenes) + 1):
        scene_dir = project_dir / f"scene_{i}"
        video_path = scene_dir / "video.mp4"
        image_path = scene_dir / "image.png"

        scene_brief = brief_scenes[i - 1] if i - 1 < len(brief_scenes) else {}

        scenes.append(SceneData(
            scene_number=i,
            project_id=project_id,
            description=scene_brief.get("visual_description", f"Scene {i}"),
            image_prompt=scene_brief.get("image_prompt", ""),
            audio_prompt=scene_brief.get("voiceover_segment", ""),
            video_path=str(video_path) if video_path.exists() else None,
            image_path=str(image_path) if image_path.exists() else None,
        ))

    return ProjectData(
        project_id=project_id,
        topic=brief.get("property", {}).get("name", "Unknown"),
        num_scenes=len(brief_scenes),
        project_dir=str(project_dir),
        scenes=scenes,
    )


async def run_stage(name: str, stage, project_dir: Path) -> bool:
    """Run a single pipeline stage. Returns True on success."""

    logger.info("")
    logger.info("=" * 60)
    logger.info(f"  STAGE: {name}")
    logger.info("=" * 60)

    can_run = await stage.can_run()
    logger.info(f"Can run: {can_run}")

    if not can_run:
        logger.warning(f"{name} - can_run=False, skipping (output may already exist)")
        return True

    start = datetime.now()
    result = await stage.execute()
    elapsed = datetime.now() - start

    if result.success:
        logger.success(f"{name} completed in {elapsed}")
        if result.data:
            for k, v in result.data.items():
                logger.info(f"  {k}: {v}")
        return True
    else:
        logger.error(f"{name} FAILED: {result.message}")
        return False


def validate_audio_artifacts(project_dir: Path):
    """Validate audio artifacts exist before GEN3a/GEN3b.

    Mirrors control_pipeline._validate_audio_artifacts() exactly.
    """
    required_files = {
        "voiceover.mp3": "ElevenLabs voiceover audio",
        "vo_alignment.json": "Character-level timestamps for word-by-word subtitles",
        "voiceover_timing.json": "Scene-level timing for Gen3b manifest",
        "subtitles.ass": "Word-by-word subtitle file",
    }

    logger.info("")
    logger.info("=" * 60)
    logger.info("  VALIDATE: Audio Artifacts")
    logger.info("=" * 60)

    problems = []
    for filename, description in required_files.items():
        path = project_dir / filename
        if not path.exists():
            problems.append(f"  - {filename}: MISSING ({description})")
            logger.error(f"  {filename}: MISSING")
        elif path.stat().st_size == 0:
            problems.append(f"  - {filename}: EMPTY (0 bytes)")
            logger.error(f"  {filename}: EMPTY")
        else:
            logger.info(f"  {filename}: OK ({path.stat().st_size / 1024:.1f} KB)")

    if problems:
        msg = "Audio artifacts incomplete:\n" + "\n".join(problems)
        logger.error(msg)
        raise FileNotFoundError(msg)

    logger.success("All audio artifacts validated")


async def main(project_id: str, skip_audio: bool = False, render_only: bool = False):
    project = build_project(project_id)
    if not project:
        return

    project_dir = Path(settings.PROJECTS_DIR) / project_id

    # Pre-flight check
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"  PIPELINE FROM VIDEOS: {project_id}")
    logger.info("=" * 60)
    logger.info(f"Project dir: {project_dir}")
    logger.info("")

    missing_videos = []
    for i in range(1, project.num_scenes + 1):
        vp = project_dir / f"scene_{i}" / "video.mp4"
        status = "OK" if vp.exists() else "MISSING"
        logger.info(f"  scene_{i}/video.mp4: {status}")
        if not vp.exists():
            missing_videos.append(i)

    vo = project_dir / "voiceover.mp3"
    music_dir = project_dir / "music"
    logger.info(f"  voiceover.mp3: {'OK' if vo.exists() else 'MISSING'}")
    logger.info(f"  music/: {'OK' if music_dir.exists() else 'MISSING'}")

    if missing_videos:
        logger.error(f"Missing videos for scenes: {missing_videos}. Aborting.")
        return

    pipeline_start = datetime.now()

    # --- Stage 6.5: Audio (voiceover + music) ---
    # (matches control_pipeline._generate_audio)
    if skip_audio or render_only:
        logger.info("\n-- Skipping audio stage --")
    else:
        stage = AudioStage(project=project)
        if not await run_stage("Audio (Voiceover + Music)", stage, project_dir):
            logger.error("Audio stage failed. Aborting.")
            return

    # --- Validate audio artifacts ---
    # (matches control_pipeline._validate_audio_artifacts)
    if not render_only:
        validate_audio_artifacts(project_dir)

    # --- Stage 7: GEN3a (Video Analysis via Gemini) ---
    # (matches control_pipeline._run_gen3a_analysis)
    if render_only:
        logger.info("\n-- Skipping GEN3a (--render-only) --")
    else:
        stage = Gen3aStage(project=project)
        if not await run_stage("GEN3a (Video Analysis)", stage, project_dir):
            logger.error("GEN3a failed. Aborting.")
            return

    # --- Stage 8: GEN3b (FFmpeg Manifest) ---
    # (matches control_pipeline._run_gen3b_manifest)
    if render_only:
        logger.info("\n-- Skipping GEN3b (--render-only) --")
    else:
        stage = Gen3bStage(project=project)
        if not await run_stage("GEN3b (Manifest Generation)", stage, project_dir):
            logger.error("GEN3b failed. Aborting.")
            return

    # --- Stage 9: Assemble final video ---
    # (matches control_pipeline._assemble_final → ManifestRenderer)
    # Remove old output to force fresh render
    for old_file in ["final.mp4", "final_video.mp4"]:
        old_path = project_dir / old_file
        if old_path.exists():
            logger.warning(f"Removing old {old_file} for fresh render")
            old_path.unlink()

    stage = PostProcessStage(project=project)
    if not await run_stage("PostProcess (Final Render)", stage, project_dir):
        logger.error("PostProcess failed.")
        return

    elapsed = datetime.now() - pipeline_start
    logger.info("")
    logger.info("=" * 60)
    logger.success(f"  ALL DONE in {elapsed}")
    logger.info("=" * 60)
    logger.info(f"Check output in: {project_dir}")


if __name__ == "__main__":
    skip_audio = "--skip-audio" in sys.argv
    render_only = "--render-only" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    if not args:
        print("Usage: python scripts/run_from_videos.py <project_id> [--skip-audio] [--render-only]")
        print()
        print("  --skip-audio   Skip audio generation (use existing voiceover/music)")
        print("  --render-only  Skip audio/GEN3a/GEN3b, only re-render final video")
        sys.exit(1)

    project_id = args[0]
    asyncio.run(main(project_id, skip_audio=skip_audio, render_only=render_only))
