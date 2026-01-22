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
from app.utils.logger import logger


async def run_script_only(topic: str = "FREE_TOPIC", num_scenes: int = 6):
    """Generate script only (GEN1 + GEN2 + MERGE) without visual generation."""

    print("\n" + "=" * 70)
    print("SCRIPT-ONLY PIPELINE")
    print("=" * 70)
    print(f"Topic: {topic}")
    print(f"Scenes: {num_scenes}")
    print("=" * 70 + "\n")

    # Generate project ID
    project_id = f"script_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # Create project directory
    project_dir = Path(__file__).parent / "projects" / project_id
    project_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"[1/3] Initializing PromptRouter...")
    router = PromptRouter()

    logger.info(f"[2/3] Running GEN1 + GEN2 pipeline...")
    logger.info(f"  This will generate creative brief with {num_scenes} scenes")

    try:
        # Run the two-stage pipeline
        project = await router.generate_full_project(
            topic=topic,
            num_scenes=num_scenes,
            style="cinematic food fantasy",
            target_audience="YouTube Shorts viewers",
            project_id=project_id,
        )

        if not project:
            logger.error("Pipeline failed - no project generated")
            return None

        # Save brief to project directory
        brief_path = project_dir / "project_brief.json"
        brief_dict = project.model_dump(mode='json')
        brief_path.write_text(json.dumps(brief_dict, indent=2, ensure_ascii=False), encoding='utf-8')

        logger.success(f"[3/3] Brief generated successfully!")

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
