"""
Image Generation Stage

Generates images for all scenes:
1. PRIMARY scene (Scene 1) - 4 candidates for user selection
2. Remaining scenes (2-N) - Parallel batch generation with reference
"""

from pathlib import Path
from typing import Optional, List

from loguru import logger

from app.pipeline.base import BasePipelineStage, StageResult, StageStatus
from app.api.schemas import ProjectData, SceneData, SceneStatus, PipelineStage
from app.services.visual_engine_web import create_visual_engine
from app.core.paths import get_scene_path


class ImageStage(BasePipelineStage):
    """
    Stage 2: Image Generation

    Two phases:
    1. PRIMARY (Scene 1): Generate 4 candidates, wait for user selection
    2. REMAINING (Scenes 2-N): Parallel batch generation with reference

    Uses VisualEngine (HiggsFieldWebAdapter) for generation.
    """

    name = "image_generation"
    description = "Generate images for all scenes"

    def __init__(self, project: ProjectData, **kwargs):
        super().__init__(project, **kwargs)
        self.visual_engine = None
        self._primary_candidates: List[Path] = []

    async def can_run(self) -> bool:
        """Check if image generation should run"""
        # Run if any scenes need images
        for scene in self.project.scenes:
            if scene.status == SceneStatus.PENDING:
                return True
        return False

    async def can_resume(self) -> bool:
        """Image generation can be resumed"""
        return True

    async def execute(self) -> StageResult:
        """Generate images for all scenes"""

        await self.notify_progress(0, "Initializing image generation...")

        try:
            # Create visual engine
            self.visual_engine = create_visual_engine()

            # Get PRIMARY scene
            primary_scene = self.project.scenes[0] if self.project.scenes else None

            if not primary_scene:
                return StageResult(
                    success=False,
                    stage_name=self.name,
                    status=StageStatus.FAILED,
                    message="No scenes found"
                )

            # Phase 1: PRIMARY scene candidates
            if primary_scene.status == SceneStatus.PENDING:
                await self._generate_primary_candidates(primary_scene)

            # Auto-select first candidate (WebSocket selection not yet implemented)
            if primary_scene.status == SceneStatus.PENDING:
                await self._auto_select_primary(primary_scene)

            # Phase 2: Remaining scenes (parallel batch)
            remaining = [s for s in self.project.scenes[1:] if s.status == SceneStatus.PENDING]

            if remaining:
                await self._generate_remaining_scenes(remaining, primary_scene)

            # Count results
            images_generated = sum(
                1 for s in self.project.scenes
                if s.image_path and Path(s.image_path).exists()
            )

            await self.notify_progress(100, f"Generated {images_generated} images")

            return StageResult(
                success=True,
                stage_name=self.name,
                message=f"Generated {images_generated} images",
                data={"images_generated": images_generated}
            )

        except Exception as e:
            logger.error(f"[{self.project_id}] Image generation failed: {e}")
            return StageResult(
                success=False,
                stage_name=self.name,
                status=StageStatus.FAILED,
                message=str(e),
                error=e
            )

    async def _generate_primary_candidates(self, scene: SceneData) -> None:
        """Generate 4 candidates for PRIMARY scene"""

        await self.notify_progress(10, "Generating PRIMARY candidates...")

        scene.status = SceneStatus.GENERATING_IMAGE

        candidates = await self.visual_engine.generate_primary_scene_candidates(
            prompt=scene.image_prompt,
            scene_number=scene.scene_number,
            project_id=self.project_id,
            num_candidates=4
        )

        self._primary_candidates = candidates
        logger.success(f"[Scene 1] Generated {len(candidates)} candidates")

        # Notify WebSocket clients (for future user selection)
        await self.notifier.send_primary_candidates_ready(
            project_id=self.project_id,
            scene_number=scene.scene_number,
            candidate_paths=candidates,
            scenario_summary=self.project.title or self.project.topic,
            scene_description=scene.description or f"Scene {scene.scene_number}",
        )

    async def _auto_select_primary(self, scene: SceneData) -> None:
        """Auto-select first candidate (temporary until WebSocket selection)"""
        import shutil

        if not self._primary_candidates:
            logger.warning("[Scene 1] No candidates to select from")
            return

        scene_dir = get_scene_path(self.project_id, scene.scene_number)

        # Copy first candidate as main image
        selected_path = scene_dir / "image.png"
        shutil.copy(self._primary_candidates[0], selected_path)
        scene.image_path = selected_path
        scene.status = SceneStatus.IMAGE_READY
        scene.validation_approved = True  # User-selected = approved

        logger.info(f"[Scene 1] Auto-selected candidate 1")

    async def _generate_remaining_scenes(
        self,
        scenes: List[SceneData],
        primary_scene: SceneData
    ) -> None:
        """Generate images for remaining scenes in parallel batch"""

        await self.notify_progress(130, f"Generating {len(scenes)} remaining images...")

        # Get reference from PRIMARY
        logger.info(f"[REF_DEBUG] primary_scene.image_path = {primary_scene.image_path}")
        logger.info(f"[REF_DEBUG] primary_scene.image_path type = {type(primary_scene.image_path)}")

        reference_image = Path(primary_scene.image_path) if primary_scene.image_path else None

        if reference_image:
            logger.info(f"[REF_DEBUG] reference_image = {reference_image}")
            logger.info(f"[REF_DEBUG] reference_image.exists() = {reference_image.exists()}")
            logger.info(f"Using PRIMARY reference: {reference_image.name}")

        # Prepare scenes data for batch
        scenes_data = []
        for scene in scenes:
            scenes_data.append({
                'scene_number': scene.scene_number,
                'image_prompt': scene.image_prompt,
                'reference_type': scene.reference_type
            })
            logger.info(f"  Scene {scene.scene_number}: {scene.reference_type}")

        # Parallel batch generation
        image_paths = await self.visual_engine.generate_all_images_parallel(
            scenes=scenes_data,
            project_id=self.project_id,
            reference_image=reference_image
        )

        # Assign paths to scenes
        for i, path in enumerate(image_paths):
            if i < len(scenes):
                scene = scenes[i]
                scene.image_path = str(path)
                scene.status = SceneStatus.IMAGE_READY
                logger.success(f"[Scene {scene.scene_number}] Image generated")

                # Notify clients
                await self.notifier.send_scene_image_ready(
                    project_id=self.project_id,
                    scene_number=scene.scene_number,
                    image_path=path
                )

        await self.notify_progress(80, f"Generated {len(image_paths)} images")
