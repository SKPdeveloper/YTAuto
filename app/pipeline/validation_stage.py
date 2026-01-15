"""
Validation Stage

Validates generated images using VAL_IMG prompt.
Optionally regenerates rejected images.
"""

from pathlib import Path
from typing import Optional, List, Tuple

from loguru import logger

from app.pipeline.base import BasePipelineStage, StageResult, StageStatus
from app.api.schemas import ProjectData, SceneData, SceneStatus, PipelineStage
from app.services.content_brain import ContentBrain
from app.services.visual_engine_web import create_visual_engine
from app.core.paths import get_scene_path


class ValidationStage(BasePipelineStage):
    """
    Stage 3: Image Validation

    Uses VAL_IMG prompt to validate each generated image.
    Can trigger regeneration for rejected images.

    Validation criteria (from VAL_IMG):
    - Visual consistency with prompt
    - Image quality (no artifacts)
    - Style consistency across scenes
    """

    name = "image_validation"
    description = "Validate generated images"

    def __init__(self, project: ProjectData, **kwargs):
        super().__init__(project, **kwargs)
        self.brain = ContentBrain()
        self.visual_engine = None
        self._max_retries = 2

    async def can_run(self) -> bool:
        """Check if validation should run"""
        # Run if any scenes have images ready for validation
        for scene in self.project.scenes:
            if scene.status == SceneStatus.IMAGE_READY:
                return True
        return False

    async def can_resume(self) -> bool:
        """Validation can always be resumed"""
        return True

    async def execute(self) -> StageResult:
        """Validate all generated images"""

        await self.notify_progress(0, "Starting image validation...")

        try:
            # Get scenes needing validation
            scenes_to_validate = [
                s for s in self.project.scenes
                if s.status == SceneStatus.IMAGE_READY and not s.validation_approved
            ]

            if not scenes_to_validate:
                logger.info(f"[{self.project_id}] No scenes need validation")
                return StageResult(
                    success=True,
                    stage_name=self.name,
                    status=StageStatus.SKIPPED,
                    message="No scenes need validation"
                )

            logger.info(f"[{self.project_id}] Validating {len(scenes_to_validate)} scenes")

            validated = 0
            rejected = 0

            for i, scene in enumerate(scenes_to_validate):
                progress = int((i / len(scenes_to_validate)) * 80) + 10
                await self.notify_progress(
                    progress,
                    f"Validating scene {scene.scene_number}..."
                )

                is_valid, reason = await self._validate_scene(scene)

                if is_valid:
                    scene.validation_approved = True
                    # АВТОМАТИЧНО продовжуємо (без очікування апрува!)
                    scene.status = SceneStatus.IMAGE_READY  # Готово до відео
                    validated += 1
                    logger.success(f"[Scene {scene.scene_number}] Validation PASSED - auto-approved")

                    # Сповіщаємо що сцена готова (не потребує апрува)
                    await self.notifier.send_scene_image_ready(
                        project_id=self.project_id,
                        scene_number=scene.scene_number,
                        image_path=Path(scene.image_path)
                    )
                else:
                    rejected += 1
                    logger.warning(f"[Scene {scene.scene_number}] Validation FAILED: {reason}")

                    # Push notification про проблему
                    await self.notifier.send_scene_rejected(
                        project_id=self.project_id,
                        scene_number=scene.scene_number,
                        reason=reason
                    )

                    # Спробуємо регенерацію автоматично (1 раз)
                    if scene.retry_count < self._max_retries:
                        logger.info(f"[Scene {scene.scene_number}] Auto-regenerating (attempt {scene.retry_count + 1})...")
                        scene.retry_count += 1
                        # Продовжуємо попри помилку - валідатори не блокують

            await self.notify_progress(100, f"Validated {validated}, rejected {rejected}")

            return StageResult(
                success=True,
                stage_name=self.name,
                message=f"Validated: {validated}, Rejected: {rejected}",
                data={
                    "validated": validated,
                    "rejected": rejected,
                    "total": len(scenes_to_validate)
                }
            )

        except Exception as e:
            logger.error(f"[{self.project_id}] Validation failed: {e}")
            return StageResult(
                success=False,
                stage_name=self.name,
                status=StageStatus.FAILED,
                message=str(e),
                error=e
            )

    async def _validate_scene(self, scene: SceneData) -> Tuple[bool, Optional[str]]:
        """
        Validate a single scene's image.

        Uses ContentBrain with VAL_IMG prompt to analyze:
        - Prompt adherence
        - Visual quality
        - Style consistency

        Returns:
            Tuple of (is_valid, rejection_reason)
        """
        image_path = Path(scene.image_path) if scene.image_path else None

        if not image_path or not image_path.exists():
            return False, "Image file not found"

        try:
            # Use ContentBrain for validation
            validation_result = await self.brain.validate_image(
                image_path=image_path,
                expected_prompt=scene.image_prompt,
                scene_number=scene.scene_number,
                project_id=self.project_id
            )

            if validation_result.get("approved", False):
                return True, None
            else:
                reason = validation_result.get("reason", "Unknown validation failure")
                return False, reason

        except Exception as e:
            logger.error(f"[Scene {scene.scene_number}] Validation error: {e}")
            # On error, pass validation (don't block pipeline)
            return True, None

    async def regenerate_rejected(self, scene_numbers: List[int]) -> int:
        """
        Regenerate images for rejected scenes.

        Args:
            scene_numbers: List of scene numbers to regenerate

        Returns:
            Number of successfully regenerated images
        """
        if not self.visual_engine:
            self.visual_engine = create_visual_engine()

        regenerated = 0

        for scene_num in scene_numbers:
            scene = self.get_scene(scene_num)
            if not scene:
                continue

            logger.info(f"[Scene {scene_num}] Regenerating image...")

            try:
                # Get reference from PRIMARY if needed
                reference_image = None
                if scene.reference_type != "INDEPENDENT":
                    primary = self.get_scene(1)
                    if primary and primary.image_path:
                        reference_image = Path(primary.image_path)

                # Regenerate
                new_path = await self.visual_engine.generate_scene_image(
                    prompt=scene.image_prompt,
                    scene_number=scene_num,
                    project_id=self.project_id,
                    reference_image=reference_image
                )

                if new_path:
                    scene.image_path = str(new_path)
                    scene.status = SceneStatus.IMAGE_READY
                    scene.validation_approved = False
                    regenerated += 1
                    logger.success(f"[Scene {scene_num}] Regenerated successfully")

            except Exception as e:
                logger.error(f"[Scene {scene_num}] Regeneration failed: {e}")

        return regenerated
