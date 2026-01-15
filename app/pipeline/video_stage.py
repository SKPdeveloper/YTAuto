"""
Video Generation Stage

Generates videos for all approved scenes.
Uses HiggsField via Kling or Seedance adapters.
"""

from pathlib import Path
from typing import Optional, List

from loguru import logger

from app.pipeline.base import BasePipelineStage, StageResult, StageStatus
from app.api.schemas import ProjectData, SceneData, SceneStatus, PipelineStage
from app.services.visual_engine_web import create_visual_engine
from app.core.paths import get_scene_path


class VideoStage(BasePipelineStage):
    """
    Stage 4: Video Generation

    Generates videos for all scenes with approved images.

    Process:
    1. For each scene with IMAGE_READY or AWAITING_APPROVAL
    2. Generate video using motion_prompt
    3. Download and save to scene directory
    4. Update scene status to APPROVED
    """

    name = "video_generation"
    description = "Generate videos for all scenes"

    def __init__(self, project: ProjectData, **kwargs):
        super().__init__(project, **kwargs)
        self.visual_engine = None

    async def can_run(self) -> bool:
        """Check if video generation should run"""
        # Run if any scenes have approved images but no video
        for scene in self.project.scenes:
            if scene.status in [SceneStatus.IMAGE_READY, SceneStatus.AWAITING_APPROVAL]:
                if scene.image_path and not scene.video_path:
                    return True
        return False

    async def can_resume(self) -> bool:
        """Video generation can be resumed"""
        return True

    async def execute(self) -> StageResult:
        """Generate videos for all approved scenes"""

        await self.notify_progress(0, "Initializing video generation...")

        try:
            # Create visual engine
            self.visual_engine = create_visual_engine()

            # Get scenes needing videos
            scenes_for_video = [
                s for s in self.project.scenes
                if s.image_path and not s.video_path
                and s.status in [SceneStatus.IMAGE_READY, SceneStatus.AWAITING_APPROVAL, SceneStatus.APPROVED]
            ]

            if not scenes_for_video:
                logger.info(f"[{self.project_id}] No scenes need video generation")
                return StageResult(
                    success=True,
                    stage_name=self.name,
                    status=StageStatus.SKIPPED,
                    message="No scenes need video generation"
                )

            logger.info(f"[{self.project_id}] Generating {len(scenes_for_video)} videos")

            # PUSH: Start notification
            await self.notifier.push_info(
                title="Video Generation Started",
                message=f"Generating {len(scenes_for_video)} videos...",
                project_id=self.project_id
            )

            # Prepare scenes data
            scenes_data = []
            for scene in scenes_for_video:
                scenes_data.append({
                    'scene_number': scene.scene_number,
                    'video_prompt': scene.motion_prompt,
                    'image_path': scene.image_path
                })

            await self.notify_progress(10, f"Starting batch video generation for {len(scenes_for_video)} scenes...")

            # Parallel batch generation
            video_paths = await self.visual_engine.generate_all_videos_parallel(
                scenes=scenes_data,
                project_id=self.project_id
            )

            # Assign paths to scenes
            videos_generated = 0
            for i, path in enumerate(video_paths):
                if i < len(scenes_for_video) and path:
                    scene = scenes_for_video[i]
                    scene.video_path = str(path)
                    scene.status = SceneStatus.APPROVED
                    videos_generated += 1

                    logger.success(f"[Scene {scene.scene_number}] Video generated")

                    # Notify clients
                    await self.notifier.send_scene_video_ready(
                        project_id=self.project_id,
                        scene_number=scene.scene_number,
                        video_path=path
                    )

                    # Progress update
                    progress = int((videos_generated / len(scenes_for_video)) * 80) + 10
                    await self.notify_progress(
                        progress,
                        f"Generated {videos_generated}/{len(scenes_for_video)} videos"
                    )

            await self.notify_progress(100, f"Generated {videos_generated} videos")

            # PUSH: Result notifications
            if videos_generated == len(scenes_for_video):
                await self.notifier.push_success(
                    title="Videos Complete!",
                    message=f"All {videos_generated} videos generated successfully",
                    project_id=self.project_id
                )
            elif videos_generated > 0:
                await self.notifier.push_warning(
                    title="Partial Video Generation",
                    message=f"Generated {videos_generated}/{len(scenes_for_video)} videos",
                    project_id=self.project_id,
                    action_required=True
                )
            else:
                await self.notifier.push_error(
                    title="Video Generation Failed",
                    message="No videos were generated",
                    project_id=self.project_id
                )

            return StageResult(
                success=True,
                stage_name=self.name,
                message=f"Generated {videos_generated} videos",
                data={
                    "videos_generated": videos_generated,
                    "total_scenes": len(scenes_for_video)
                }
            )

        except Exception as e:
            logger.error(f"[{self.project_id}] Video generation failed: {e}")

            # PUSH: Critical error
            await self.notifier.push_error(
                title="Video Generation Error",
                message=str(e)[:100],
                project_id=self.project_id,
                is_critical=True
            )

            return StageResult(
                success=False,
                stage_name=self.name,
                status=StageStatus.FAILED,
                message=str(e),
                error=e
            )

    async def generate_single_video(self, scene_number: int) -> Optional[Path]:
        """
        Generate video for a single scene.

        Used for manual regeneration or retries.

        Args:
            scene_number: Scene number to generate video for

        Returns:
            Path to generated video or None
        """
        scene = self.get_scene(scene_number)
        if not scene:
            logger.error(f"Scene {scene_number} not found")
            return None

        if not scene.image_path:
            logger.error(f"Scene {scene_number} has no image")
            return None

        if not self.visual_engine:
            self.visual_engine = create_visual_engine()

        try:
            logger.info(f"[Scene {scene_number}] Generating video...")

            video_path = await self.visual_engine.generate_video(
                image_path=Path(scene.image_path),
                motion_prompt=scene.motion_prompt,
                scene_number=scene_number,
                project_id=self.project_id
            )

            if video_path:
                scene.video_path = str(video_path)
                scene.status = SceneStatus.APPROVED
                logger.success(f"[Scene {scene_number}] Video generated: {video_path}")

                await self.notifier.send_scene_video_ready(
                    project_id=self.project_id,
                    scene_number=scene_number,
                    video_path=video_path
                )

            return video_path

        except Exception as e:
            logger.error(f"[Scene {scene_number}] Video generation failed: {e}")
            return None
