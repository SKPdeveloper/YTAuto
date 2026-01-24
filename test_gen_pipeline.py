"""
Test GEN1 -> GEN2 -> Merge Pipeline
Only script generation, no images/videos
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from app.core.config import settings
from app.services.prompt_router import PromptRouter
from app.utils.logger import logger


async def test_gen_pipeline():
    """Run GEN1 -> GEN2 -> merge test"""

    print("\n" + "=" * 70)
    print("TEST: GEN1 -> GEN2 -> MERGE PIPELINE")
    print("=" * 70)

    # Check API key
    if not settings.GOOGLE_GEMINI_API_KEY:
        print("ERROR: GOOGLE_GEMINI_API_KEY not set!")
        return

    print(f"\nModel: {settings.CONTENTBRAIN_MODEL}")
    print(f"Temperature: {settings.GEMINI_TEMPERATURE}")
    print(f"max_output_tokens: 65536 (Gemini 3 Pro max)")

    # Create router
    router = PromptRouter()

    project_id = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    print(f"\nProject ID: {project_id}")
    print(f"Topic: FREE (AI choice)")
    print(f"Scenes: 6")

    print("\n" + "-" * 70)
    print("Starting pipeline...")
    print("-" * 70 + "\n")

    try:
        # Run full generation (GEN1 -> GEN2 -> merge)
        project = await router.generate_full_project(
            topic=None,  # Free topic
            num_scenes=6,
            style="cinematic food fantasy",
            target_audience="YouTube Shorts viewers",
            duration_seconds=10,
            project_id=project_id,
            skip_validation=False,  # Run validations
        )

        if project:
            print("\n" + "=" * 70)
            print("SUCCESS! Project generated")
            print("=" * 70)

            print(f"\nTitle: {project.property.name}")
            print(f"Project ID: {project.project_id}")
            print(f"Scenes: {len(project.scenes)}")

            print("\n--- SCENES ---")
            for scene in project.scenes:
                print(f"\n[Scene {scene.scene_number}]")
                print(f"  Name: {scene.scene_name}")
                print(f"  Voiceover: {scene.voiceover[:100]}..." if len(scene.voiceover) > 100 else f"  Voiceover: {scene.voiceover}")
                print(f"  Reference Type: {scene.reference_type}")
                if scene.image_prompt:
                    print(f"  Image Prompt: {scene.image_prompt[:80]}..." if len(scene.image_prompt) > 80 else f"  Image Prompt: {scene.image_prompt}")
                if scene.video_prompt:
                    print(f"  Video Prompt: {scene.video_prompt[:80]}..." if len(scene.video_prompt) > 80 else f"  Video Prompt: {scene.video_prompt}")

            # Save project JSON
            output_dir = Path("projects") / project_id
            output_dir.mkdir(parents=True, exist_ok=True)

            output_file = output_dir / "project_data.json"
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(project.model_dump_json(indent=2))

            print(f"\nSaved to: {output_file}")

        else:
            print("\n" + "=" * 70)
            print("FAILED! No project generated")
            print("=" * 70)

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_gen_pipeline())
