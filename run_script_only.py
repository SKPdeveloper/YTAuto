"""
SCRIPT-ONLY PIPELINE - Generate brief without visual generation

Запускає тільки GEN1 + GEN2 + MERGE:
1. GEN1 (Creative Director) - story, hook, structure
2. GEN2 (Visual Director) - image/video prompts
3. MERGE - combines into final brief

Після генерації виводить шляхи до файлів для аналізу.

Використання:
    python run_script_only.py --free
    python run_script_only.py "Chocolate Train Station"
"""

import asyncio
import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from app.services.prompt_router import PromptRouter, DEBUG_DIR
from app.services.glaze_parser import save_merged_project_brief
from app.utils.logger import logger


async def run_script_only(topic: str = "FREE_TOPIC", num_scenes: int = 6):
    """Generate script only (GEN1 + GEN2 + MERGE) without visual generation."""

    print("\n" + "=" * 70)
    print("SCRIPT-ONLY PIPELINE (DEEP MERGE)")
    print("=" * 70)
    print(f"Topic: {topic}")
    print(f"Scenes: {num_scenes}")
    print("=" * 70 + "\n")

    # Generate project ID
    project_id = f"script_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # Create project directory
    project_dir = Path(__file__).parent / "projects" / project_id
    project_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"[1/4] Initializing PromptRouter...")
    router = PromptRouter()

    logger.info(f"[2/4] Running GEN1...")

    try:
        # Run GEN1 separately
        gen1_output = await router.run_gen1(
            topic=topic,
            num_scenes=num_scenes,
            style="cinematic food fantasy",
            target_audience="YouTube Shorts viewers",
            project_id=project_id,
        )

        if not gen1_output:
            logger.error("GEN1 failed - no output generated")
            return None

        logger.info(f"[3/4] Running GEN2...")

        # Create delivery payload and run GEN2
        payload = router.create_delivery_payload(gen1_output, project_id)
        gen2_output = await router.run_gen2(payload, project_id)

        if not gen2_output:
            logger.error("GEN2 failed - no output generated")
            return None

        logger.info(f"[4/4] Deep merging GEN1 + GEN2...")

        # ЗАЛІЗОБЕТОННИЙ DEEP MERGE - напряму з dicts
        brief_path = save_merged_project_brief(
            gen1_dict=gen1_output.model_dump(),
            gen2_dict=gen2_output.model_dump(),
            project_id=project_id,
            output_dir=project_dir
        )

        # Also create GlazeCityProject for summary display (optional)
        project = router.merge_outputs(gen1_output, gen2_output, project_id)

        logger.success(f"Brief generated successfully with DEEP MERGE!")

        # Find GEN1 and GEN2 debug files
        gen1_files = sorted(DEBUG_DIR.glob(f"GEN1_{project_id}*.txt"), reverse=True)
        gen2_files = sorted(DEBUG_DIR.glob(f"GEN2_{project_id}*.txt"), reverse=True)
        val_gen1_files = sorted(DEBUG_DIR.glob(f"VAL_GEN1*{project_id}*.txt"), reverse=True)
        val_gen2_files = sorted(DEBUG_DIR.glob(f"VAL_GEN2*{project_id}*.txt"), reverse=True)

        print("\n" + "=" * 70)
        print("GENERATION COMPLETE - FILES FOR ANALYSIS")
        print("=" * 70)

        print(f"\n📁 Project Directory:")
        print(f"   {project_dir}")

        print(f"\n📄 Final Brief (merged GEN1+GEN2):")
        print(f"   {brief_path}")

        print(f"\n📝 Raw GEN1 Outputs ({len(gen1_files)} files):")
        for f in gen1_files[:3]:
            print(f"   {f}")

        print(f"\n📝 Raw GEN2 Outputs ({len(gen2_files)} files):")
        for f in gen2_files[:3]:
            print(f"   {f}")

        print(f"\n✅ Validation Logs:")
        for f in val_gen1_files[:2]:
            print(f"   {f}")
        for f in val_gen2_files[:2]:
            print(f"   {f}")

        print("\n" + "=" * 70)
        print("BRIEF SUMMARY")
        print("=" * 70)
        print(f"  Property: {project.property.name}")
        print(f"  Location: {project.property.location}")
        print(f"  Hook Type: {project.hook.type}")
        print(f"  Trigger: {project.hook.psychological_trigger}")
        print(f"  Scenes: {len(project.scenes)}")
        print(f"  Duration: {project.meta.total_duration_seconds}s")
        print(f"  YouTube Title: {project.youtube.title}")
        print(f"  Viral Score: {project.viral_audit.total_score}/{project.viral_audit.max_score} ({project.viral_audit.viral_probability})")
        print("=" * 70)

        print(f"\n✨ To continue with visual generation, run:")
        print(f"   python run_real_pipeline.py --resume {project_id}")

        return project

    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        import traceback
        traceback.print_exc()
        return None


async def main():
    """Main entry point."""

    # Parse arguments
    topic = "FREE_TOPIC"

    for arg in sys.argv[1:]:
        if arg == "--free":
            topic = "FREE_TOPIC"
        elif not arg.startswith("-"):
            topic = arg

    await run_script_only(topic=topic)


if __name__ == "__main__":
    asyncio.run(main())
