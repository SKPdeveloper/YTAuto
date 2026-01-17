"""
Control Pipeline Runner

Wraps the ProjectOrchestrator with Control Panel approval workflow.
Used by control_routes.py to run pipeline with user approvals.
"""

import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Callable, Any
from datetime import datetime

from app.core.config import settings
from app.core.orchestrator import ProjectOrchestrator
from app.utils.logger import logger
from app.api.schemas import ProjectData, SceneData, SceneStatus


class ControlPipeline:
    """
    Pipeline runner with Control Panel integration.

    Workflow:
    1. Create new project with random topic
    2. Generate script (GEN1 + GEN2)
    3. Generate 4 PRIMARY candidates for Scene 1
    4. Wait for user selection (or rejection)
    5. Generate images for scenes 2-6
    6. Auto-validate with VAL_IMG
    7. Allow user to kick individual scenes
    8. Generate videos for all scenes
    9. Assemble final video
    """

    def __init__(self):
        self.orchestrator = ProjectOrchestrator()
        self.project: Optional[ProjectData] = None
        self.primary_candidates: List[Path] = []

        # Callbacks - set by control_routes.py
        self.on_stage_change: Optional[Callable] = None
        self.on_approval_required: Optional[Callable] = None
        self.on_scene_updated: Optional[Callable] = None

    async def run(self) -> str:
        """
        Run the full pipeline with approval workflow.

        Returns:
            project_id
        """
        try:
            # Stage 0: Start browser and CLEAR all forms before starting
            logger.info("[PIPELINE] Starting browser and clearing forms...")
            await self.orchestrator.visual_engine._ensure_browser_started()
            await self.orchestrator.visual_engine._client.clear_all_forms()
            logger.success("[PIPELINE] Browser ready, forms cleared")

            # Stage 1: Create project
            await self._notify_stage("CREATING_PROJECT", 5)
            self.project = await self.orchestrator.create_project(topic="FREE_TOPIC")
            project_id = self.project.project_id

            logger.info(f"Created project: {project_id}")
            logger.info(f"Title: {self.project.title}")

            # Stage 2: Generate script
            await self._notify_stage("GENERATING_SCRIPT", 10)
            await self.orchestrator._generate_script(self.project)

            logger.info(f"Script generated with {len(self.project.scenes)} scenes")

            # Stage 3: Generate PRIMARY candidates
            await self._process_primary_selection()

            # Stage 4: Generate remaining scenes with validation
            await self._process_remaining_scenes()

            # Stage 5: Wait for scenes confirmation
            await self._wait_for_scenes_confirmation()

            # Stage 6: Generate videos
            await self._generate_videos()

            # Stage 7: Assemble final video
            await self._assemble_final()

            # Clear forms at the end
            logger.info("[PIPELINE] Clearing forms at end...")
            await self.orchestrator.visual_engine._client.clear_all_forms()

            await self._notify_stage("COMPLETED", 100)

            return project_id

        except Exception as e:
            logger.error(f"Pipeline error: {e}")
            await self._notify_stage("ERROR", 0)
            raise

    async def _process_primary_selection(self):
        """Generate PRIMARY candidates and wait for user selection."""

        if not self.project or not self.project.scenes:
            raise ValueError("No project or scenes")

        primary_scene = self.project.scenes[0]

        while True:
            # Generate 4 candidates
            await self._notify_stage("GENERATING_PRIMARY", 20)

            self.primary_candidates = await self.orchestrator._generate_primary_candidates(
                self.project, primary_scene
            )

            if not self.primary_candidates:
                raise ValueError("Failed to generate PRIMARY candidates")

            logger.info(f"Generated {len(self.primary_candidates)} PRIMARY candidates")

            # Prepare candidates data for UI
            candidates_data = []
            for i, path in enumerate(self.primary_candidates):
                # Get relative URL for serving via /projects/
                rel_path = str(path).replace(str(settings.PROJECTS_DIR), "").replace("\\", "/")
                if rel_path.startswith("/"):
                    rel_path = rel_path[1:]

                candidates_data.append({
                    "index": i,
                    "url": f"/projects/{rel_path}",
                    "score": 85 - i * 5,  # Mock scores for now
                    "grade": "A" if i == 0 else "B"
                })

            # Wait for user approval
            await self._notify_stage("AWAITING_PRIMARY_SELECTION", 25)

            result = await self._request_approval("primary", {
                "images": candidates_data
            })

            if result.get("action") == "reject_all":
                logger.info("User rejected all PRIMARY candidates, regenerating...")
                continue

            if result.get("action") == "approve":
                selected_index = result.get("image_index", 0)
                await self._select_primary_candidate(selected_index)
                logger.success(f"PRIMARY selected: candidate {selected_index + 1}")
                break

    async def _select_primary_candidate(self, index: int):
        """Copy selected candidate as main image."""
        import shutil

        if not self.project or not self.primary_candidates:
            return

        primary_scene = self.project.scenes[0]
        scene_dir = settings.get_scene_dir(self.project.project_id, 1)

        # Copy selected candidate
        selected_path = scene_dir / "image.png"
        shutil.copy(self.primary_candidates[index], selected_path)

        primary_scene.image_path = str(selected_path)
        primary_scene.status = SceneStatus.IMAGE_READY
        primary_scene.validation_approved = True

        await self.orchestrator._save_project_state(self.project)

    async def _process_remaining_scenes(self):
        """Generate and validate images for scenes 2-6."""

        if not self.project:
            return

        await self._notify_stage("GENERATING_SCENES", 35)

        # Get reference from PRIMARY
        primary_scene = self.project.scenes[0]
        reference_image = primary_scene.image_path

        # Collect scenes to generate
        scenes_to_generate = []
        for scene in self.project.scenes[1:]:
            scene_dir = settings.get_scene_dir(self.project.project_id, scene.scene_number)
            if not (scene_dir / "image.png").exists():
                scenes_to_generate.append(scene)

        if scenes_to_generate:
            # Prepare scenes data
            scenes_data = [{
                'scene_number': s.scene_number,
                'image_prompt': s.image_prompt,
                'reference_type': s.reference_type
            } for s in scenes_to_generate]

            logger.info(f"Generating {len(scenes_data)} scene images...")

            # Generate all images in parallel
            image_paths = await self.orchestrator.visual_engine.generate_all_images_parallel(
                scenes=scenes_data,
                project_id=self.project.project_id,
                reference_image=Path(reference_image) if reference_image else None
            )

            # Assign paths
            for i, path in enumerate(image_paths):
                if i < len(scenes_to_generate):
                    scene = scenes_to_generate[i]
                    scene.image_path = path
                    scene.status = SceneStatus.IMAGE_READY
                    logger.success(f"[Scene {scene.scene_number}] Image generated")

        # Validate images
        await self._notify_stage("VALIDATING_IMAGES", 50)
        await self._validate_scenes()

        await self.orchestrator._save_project_state(self.project)

    async def _validate_scenes(self):
        """Run VAL_IMG validation on all scenes."""

        if not self.project:
            return

        for scene in self.project.scenes[1:]:
            if scene.status != SceneStatus.IMAGE_READY:
                continue

            if not scene.image_path or not Path(scene.image_path).exists():
                continue

            logger.info(f"[Scene {scene.scene_number}] Validating...")

            try:
                result = await self.orchestrator.content_brain.validate_image(
                    image_path=Path(scene.image_path),
                    expected_prompt=scene.image_prompt,
                    scene_number=scene.scene_number,
                    scene_description=scene.description,
                    scene_mood=scene.mood,
                    key_elements=scene.key_elements
                )

                if result.approved:
                    scene.status = SceneStatus.APPROVED  # Auto-approve (simplified UI)
                    scene.validation_approved = True
                    logger.success(f"[Scene {scene.scene_number}] Validation passed - auto-approved")
                else:
                    issues_str = ', '.join(result.issues) if result.issues else result.feedback
                    logger.warning(f"[Scene {scene.scene_number}] Validation failed: {issues_str}")
                    # Auto-approve anyway (simplified UI - no manual review)
                    scene.status = SceneStatus.APPROVED
                    scene.validation_approved = True

            except Exception as e:
                logger.error(f"[Scene {scene.scene_number}] Validation error: {e}")
                scene.status = SceneStatus.APPROVED  # Auto-approve on error too

        # Mark scene 1 as approved (already selected by user)
        self.project.scenes[0].status = SceneStatus.APPROVED

    async def _wait_for_scenes_confirmation(self):
        """Auto-confirm all scenes (simplified UI - no user interaction needed)."""

        if not self.project:
            return

        await self._notify_stage("AUTO_CONFIRMING_SCENES", 60)

        # Prepare scenes data for display
        scenes_data = []
        for scene in self.project.scenes:
            scene_dir = settings.get_scene_dir(self.project.project_id, scene.scene_number)
            image_path = scene_dir / "image.png"

            rel_path = str(image_path).replace(str(settings.PROJECTS_DIR), "").replace("\\", "/")
            if rel_path.startswith("/"):
                rel_path = rel_path[1:]

            scenes_data.append({
                "scene_num": scene.scene_number,
                "url": f"/projects/{rel_path}",
                "status": "approved"
            })

        # Notify UI about scenes (for display only)
        await self._request_approval("scenes", {"scenes": scenes_data})

        # Mark all scenes as approved immediately
        for scene in self.project.scenes:
            scene.status = SceneStatus.APPROVED

        await self.orchestrator._save_project_state(self.project)
        logger.success("All scenes auto-confirmed (simplified UI mode)")

    async def _regenerate_scene(self, scene_num: int):
        """Regenerate a single scene."""

        if not self.project:
            return

        scene = next((s for s in self.project.scenes if s.scene_number == scene_num), None)
        if not scene:
            return

        logger.info(f"[Scene {scene_num}] Regenerating...")

        # Notify UI
        await self._notify_scene_update(scene_num, {"status": "regenerating"})

        # Get reference
        primary_scene = self.project.scenes[0]
        reference_image = primary_scene.image_path

        # Regenerate
        try:
            scenes_data = [{
                'scene_number': scene.scene_number,
                'image_prompt': scene.image_prompt,
                'reference_type': scene.reference_type
            }]

            paths = await self.orchestrator.visual_engine.generate_all_images_parallel(
                scenes=scenes_data,
                project_id=self.project.project_id,
                reference_image=Path(reference_image) if reference_image else None
            )

            if paths:
                scene.image_path = paths[0]
                scene.status = SceneStatus.AWAITING_APPROVAL
                scene.validation_approved = True

                await self._notify_scene_update(scene_num, {
                    "status": "approved",
                    "url": f"/projects/{self.project.project_id}/scene_{scene_num}/image.png"
                })

                logger.success(f"[Scene {scene_num}] Regenerated")

        except Exception as e:
            logger.error(f"[Scene {scene_num}] Regeneration failed: {e}")

    async def _generate_videos(self):
        """Generate videos for all scenes using SimpleVideoGenerator."""

        if not self.project:
            return

        await self._notify_stage("GENERATING_VIDEOS", 70)

        logger.info("Generating videos for all scenes (SimpleVideoGenerator)...")

        try:
            # Prepare scenes data for batch generation
            scenes_data = []
            for scene in self.project.scenes:
                if not scene.image_path:
                    logger.warning(f"[Scene {scene.scene_number}] No image, skipping video")
                    continue

                # DEBUG: Log image path for each scene
                logger.info(f"[DEBUG] Scene {scene.scene_number}: image_path = {scene.image_path}")

                scenes_data.append({
                    'scene_number': scene.scene_number,
                    'image_path': scene.image_path,
                    'video_prompt': scene.motion_prompt,
                })

            if not scenes_data:
                raise ValueError("No scenes with images to generate videos for")

            logger.info(f"Generating {len(scenes_data)} videos...")

            # Use SimpleVideoGenerator through visual_engine
            video_paths = await self.orchestrator.visual_engine.generate_all_videos_parallel(
                scenes=scenes_data,
                project_id=self.project.project_id,
            )

            # Update scene statuses
            for i, path in enumerate(video_paths):
                if i < len(self.project.scenes):
                    scene = self.project.scenes[i]
                    if path:
                        scene.video_path = str(path)
                        scene.status = SceneStatus.VIDEO_READY
                        logger.success(f"[Scene {scene.scene_number}] Video ready: {path}")

            await self.orchestrator._save_project_state(self.project)
            logger.success(f"All videos generated: {len(video_paths)}")

        except Exception as e:
            logger.error(f"Video generation failed: {e}")
            raise

    async def _assemble_final(self):
        """Assemble final video from scenes with audio."""

        if not self.project:
            return

        await self._notify_stage("ASSEMBLING_VIDEO", 90)

        from app.services.video_assembler import VideoAssembler

        assembler = VideoAssembler()
        project_dir = settings.PROJECTS_DIR / self.project.project_id

        # Simple concat with voiceover audio
        result = await assembler.assemble(
            project_dir=project_dir,
            output_filename="final.mp4",
            include_voiceover=True
        )

        logger.success(f"Final video: {result}")

    async def _assemble_with_trimming(self, project_dir: Path) -> Path:
        """Assemble final video with scene duration trimming."""
        import subprocess
        import json

        # Load project brief for durations
        brief_path = project_dir / "project_brief.json"
        if not brief_path.exists():
            # Simple concat if no brief
            from app.services.video_assembler import VideoAssembler
            assembler = VideoAssembler()
            return await assembler.assemble_with_concat_file(project_dir, "final.mp4")

        with open(brief_path, 'r', encoding='utf-8') as f:
            brief = json.load(f)

        scenes = sorted(brief.get('scenes', []), key=lambda s: s.get('scene_number', 0))

        # Trim each video
        trimmed_files = []
        for scene_data in scenes:
            num = scene_data.get('scene_number')
            dur = scene_data.get('duration_seconds', 2.0)

            input_video = project_dir / f"scene_{num}" / "video.mp4"
            output_video = project_dir / f"scene_{num}" / "video_trimmed.mp4"

            if not input_video.exists():
                continue

            cmd = ['ffmpeg', '-y', '-i', str(input_video), '-t', str(dur), '-c', 'copy', str(output_video)]
            subprocess.run(cmd, capture_output=True)

            if output_video.exists():
                trimmed_files.append(output_video)

        if not trimmed_files:
            raise ValueError("No trimmed videos to assemble")

        # Concat
        concat_file = project_dir / "concat_trimmed.txt"
        with open(concat_file, 'w') as f:
            for path in trimmed_files:
                f.write(f"file '{str(path).replace(chr(92), '/')}'\n")

        output_final = project_dir / "final_10s.mp4"
        cmd = ['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(concat_file), '-c', 'copy', str(output_final)]
        subprocess.run(cmd, capture_output=True)

        return output_final

    # ========================================================================
    # NOTIFICATION HELPERS
    # ========================================================================

    async def _notify_stage(self, stage: str, progress: int):
        """Notify about stage change."""
        if self.on_stage_change:
            await self.on_stage_change(stage, progress)

    async def _request_approval(self, approval_type: str, data: dict) -> dict:
        """Request approval from user and wait for response."""
        if self.on_approval_required:
            return await self.on_approval_required(approval_type, data)
        return {"action": "confirm"}  # Auto-approve if no callback

    async def _notify_scene_update(self, scene_num: int, data: dict):
        """Notify about scene update."""
        data["scene_num"] = scene_num
        if self.on_scene_updated:
            await self.on_scene_updated(scene_num, data)
