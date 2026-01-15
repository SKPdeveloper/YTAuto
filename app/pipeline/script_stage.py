"""
Script Generation Stage

Generates video script using GEN1 (Creative Director) + GEN2 (Visual Director).
"""

from typing import Optional

from loguru import logger

from app.pipeline.base import BasePipelineStage, StageResult, StageStatus
from app.api.schemas import ProjectData, SceneData, SceneStatus, PipelineStage
from app.services.prompt_router import PromptRouter
from app.services.glaze_parser import save_project_brief
from app.core.paths import get_project_path


class ScriptStage(BasePipelineStage):
    """
    Stage 1: Script Generation

    Uses PromptRouter to generate script via:
    1. GEN1 (Creative Director) - Creates story, scenes, voiceover
    2. GEN2 (Visual Director) - Adds image_prompt, motion_prompt, reference_type

    Output:
    - project.title
    - project.summary
    - project.scenes[] with prompts
    - project_brief.json saved to disk
    """

    name = "script_generation"
    description = "Generate video script via GEN1 + GEN2"

    async def can_run(self) -> bool:
        """Check if script generation should run"""
        # Run if no scenes exist yet
        return len(self.project.scenes) == 0

    async def can_resume(self) -> bool:
        """Script generation can always be retried"""
        return True

    async def execute(self) -> StageResult:
        """Generate script via PromptRouter"""

        await self.notify_progress(0, "Starting script generation...")

        try:
            # Use PromptRouter for two-stage generation
            router = PromptRouter()

            await self.notify_progress(10, "Running GEN1 (Creative Director)...")

            glaze_project = await router.generate_full_project(
                topic=self.project.topic,
                num_scenes=self.project.num_scenes,
                style=self.project.style or "cinematic food fantasy",
                target_audience=self.project.target_audience or "YouTube Shorts viewers",
                project_id=self.project.project_id,
            )

            if not glaze_project:
                return StageResult(
                    success=False,
                    stage_name=self.name,
                    status=StageStatus.FAILED,
                    message="PromptRouter returned empty output"
                )

            await self.notify_progress(70, "Processing GEN2 output...")

            # Update project with script data
            self.project.title = glaze_project.property.name
            self.project.summary = glaze_project.youtube.description[:500] if glaze_project.youtube.description else ""
            self.project.tags = glaze_project.youtube.tags or []

            # Convert GlazeScene to SceneData
            for glaze_scene in glaze_project.scenes:
                ref_type = glaze_scene.reference_type

                # Scene 1 should always be PRIMARY
                if glaze_scene.scene_number == 1 and ref_type != "PRIMARY":
                    ref_type = "PRIMARY"

                scene_data = SceneData(
                    scene_number=glaze_scene.scene_number,
                    project_id=self.project.project_id,
                    description=glaze_scene.visual_description,
                    key_elements=[],
                    mood=glaze_scene.scene_name,
                    image_prompt=glaze_scene.image_prompt,
                    motion_prompt=glaze_scene.video_prompt,
                    audio_prompt=glaze_scene.voiceover,
                    status=SceneStatus.PENDING,
                    reference_type=ref_type,
                    is_primary_scene=(glaze_scene.scene_number == 1),
                )
                self.project.scenes.append(scene_data)

            await self.notify_progress(90, "Saving project brief...")

            # Save project_brief.json
            project_dir = get_project_path(self.project.project_id)
            project_dir.mkdir(parents=True, exist_ok=True)
            save_project_brief(glaze_project, project_dir)

            await self.notify_progress(100, "Script generation complete")

            logger.success(f"[{self.project_id}] Script generated: {self.project.title}")
            logger.info(f"  Scenes: {len(self.project.scenes)}")
            logger.info(f"  Reference types: {[s.reference_type for s in self.project.scenes]}")

            return StageResult(
                success=True,
                stage_name=self.name,
                message=f"Generated {len(self.project.scenes)} scenes",
                data={
                    "title": self.project.title,
                    "num_scenes": len(self.project.scenes),
                    "reference_types": [s.reference_type for s in self.project.scenes],
                }
            )

        except Exception as e:
            logger.error(f"[{self.project_id}] Script generation failed: {e}")
            return StageResult(
                success=False,
                stage_name=self.name,
                status=StageStatus.FAILED,
                message=str(e),
                error=e
            )
