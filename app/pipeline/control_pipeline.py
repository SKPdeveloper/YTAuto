"""
Control Pipeline Runner

Wraps the ProjectOrchestrator with Control Panel approval workflow.
Used by control_routes.py to run pipeline with user approvals.
"""

import asyncio
import json
import shutil
import time
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

        # URL выбранной референсной картинки (для поиска в галерее HiggsField)
        self.selected_reference_url: Optional[str] = None

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

            # Notify UI about project_id immediately (for "new topic" feature)
            from app.api.control_routes import state, broadcast_event
            state.current_project_id = project_id
            await broadcast_event("project_created", {"project_id": project_id})

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

            # Stage 6.5: Generate audio (voiceover + music) - REQUIRED for Gen3a
            await self._generate_audio()

            # Stage 7: Gen3a Video Analysis
            await self._run_gen3a_analysis()

            # Stage 8: Gen3b Manifest Generation
            await self._run_gen3b_manifest()

            # Stage 9: Assemble final video
            await self._assemble_final()

            # Clear forms at the end
            logger.info("[PIPELINE] Clearing forms at end...")
            await self.orchestrator.visual_engine._client.clear_all_forms()

            # Stage 10: Video Approval (перед Topaz)
            approval_result = await self._video_approval()

            if approval_result in ("rejected", "needs_editing"):
                await self._notify_stage("REJECTED", 0)
                logger.warning(f"[PIPELINE] Video {approval_result} by user")
                return project_id

            # Stage 11: Topaz upscaling (если approved)
            if approval_result == "approved":
                await self._run_topaz_upscale()

            # Stage 12: YouTube upload (optional)
            await self._upload_to_youtube()

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
            import time
            cache_bust = int(time.time() * 1000)
            candidates_data = []
            for i, path in enumerate(self.primary_candidates):
                # Get relative URL for serving via /projects/
                rel_path = str(path).replace(str(settings.PROJECTS_DIR), "").replace("\\", "/")
                if rel_path.startswith("/"):
                    rel_path = rel_path[1:]

                candidates_data.append({
                    "index": i,
                    "url": f"/projects/{rel_path}?t={cache_bust}",
                    "score": 85 - i * 5,  # Mock scores for now
                    "grade": "A" if i == 0 else "B"
                })

            # Wait for user approval
            await self._notify_stage("AWAITING_PRIMARY_SELECTION", 25)

            result = await self._request_approval("primary", {
                "images": candidates_data
            })

            if result.get("action") == "abort":
                logger.info("Pipeline aborted by user (new topic requested)")
                raise Exception("Pipeline aborted - new topic requested")

            if result.get("action") == "reject_all":
                logger.info("User rejected all PRIMARY candidates, regenerating...")
                continue

            if result.get("action") == "approve":
                selected_index = result.get("image_index", 0)
                await self._select_primary_candidate(selected_index)
                logger.success(f"PRIMARY selected: candidate {selected_index + 1}")
                break

    async def _select_primary_candidate(self, index: int):
        """Copy selected candidate as main image and save reference URL."""
        if not self.project or not self.primary_candidates:
            return

        primary_scene = self.project.scenes[0]
        scene_dir = settings.get_scene_dir(self.project.project_id, 1)

        # Copy selected candidate
        selected_path = scene_dir / "image.png"
        shutil.copy(self.primary_candidates[index], selected_path)

        # Read URL from metadata file (index is 0-based, candidate files are 1-based)
        metadata_path = scene_dir / f"candidate_{index + 1}_metadata.json"
        if metadata_path.exists():
            try:
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                    self.selected_reference_url = metadata.get('image_url')
                    if self.selected_reference_url:
                        logger.info(f"[PRIMARY] Saved reference URL: {self.selected_reference_url[:60]}...")
            except Exception as e:
                logger.warning(f"Failed to read metadata for reference URL: {e}")

        primary_scene.image_path = str(selected_path)
        primary_scene.status = SceneStatus.IMAGE_READY
        primary_scene.validation_approved = True

        # Notify UI about primary scene image
        await self._notify_scene_update(1, {
            "scene_num": 1,
            "image_url": f"/projects/{self.project.project_id}/scene_1/image.png",
            "status": "image_ready"
        })

        await self.orchestrator._save_project_state(self.project)

    async def _process_remaining_scenes(self):
        """Generate and validate images for scenes 2-6 with retry logic."""

        if not self.project:
            return

        await self._notify_stage("GENERATING_SCENES", 35)

        # Get reference from PRIMARY
        primary_scene = self.project.scenes[0]
        reference_image = primary_scene.image_path

        # ================================================================
        # SCENE 6 (LOOP_CLOSE): Copy Scene 1 image instead of generating
        # Scene 6 should be IDENTICAL to Scene 1 for seamless loop
        # ================================================================
        scene_6 = next((s for s in self.project.scenes if s.scene_number == 6), None)
        if scene_6 and scene_6.reference_type == "LOOP_CLOSE":
            scene_1_dir = settings.get_scene_dir(self.project.project_id, 1)
            scene_6_dir = settings.get_scene_dir(self.project.project_id, 6)
            scene_1_image = scene_1_dir / "image.png"
            scene_6_image = scene_6_dir / "image.png"

            if scene_1_image.exists() and not scene_6_image.exists():
                scene_6_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy(scene_1_image, scene_6_image)
                scene_6.image_path = str(scene_6_image)
                scene_6.status = SceneStatus.IMAGE_READY
                scene_6.validation_approved = True  # No validation needed - identical to approved Scene 1
                logger.success(f"[Scene 6] ✅ Copied from Scene 1 (LOOP_CLOSE)")

                # Notify UI
                cache_bust = int(time.time())
                await self._notify_scene_update(6, {
                    "scene_num": 6,
                    "image_url": f"/projects/{self.project.project_id}/scene_6/image.png?t={cache_bust}",
                    "status": "image_ready"
                })

        max_batch_retries = 2

        for batch_attempt in range(1, max_batch_retries + 1):
            # Collect scenes WITHOUT images (excluding LOOP_CLOSE which was copied)
            scenes_to_generate = []
            for scene in self.project.scenes[1:]:
                # Skip LOOP_CLOSE - already copied from Scene 1
                if scene.reference_type == "LOOP_CLOSE":
                    continue
                scene_dir = settings.get_scene_dir(self.project.project_id, scene.scene_number)
                if not (scene_dir / "image.png").exists():
                    scenes_to_generate.append(scene)

            if not scenes_to_generate:
                logger.success("[PIPELINE] All scenes have images!")
                break

            logger.info(f"[PIPELINE] Batch attempt {batch_attempt}/{max_batch_retries}: {len(scenes_to_generate)} scenes need images")

            # Prepare scenes data
            scenes_data = [{
                'scene_number': s.scene_number,
                'image_prompt': s.image_prompt,
                'reference_type': s.reference_type
            } for s in scenes_to_generate]

            logger.info(f"Generating {len(scenes_data)} scene images...")
            if self.selected_reference_url:
                logger.info(f"Using reference URL: {self.selected_reference_url[:60]}...")

            # Generate all images in parallel
            try:
                image_paths = await self.orchestrator.visual_engine.generate_all_images_parallel(
                    scenes=scenes_data,
                    project_id=self.project.project_id,
                    reference_image=Path(reference_image) if reference_image else None,
                    reference_url=self.selected_reference_url
                )

                # Assign paths
                generated_count = 0
                for i, path in enumerate(image_paths):
                    if path and i < len(scenes_to_generate):
                        scene = scenes_to_generate[i]
                        scene.image_path = path
                        scene.status = SceneStatus.IMAGE_READY
                        generated_count += 1
                        logger.success(f"[Scene {scene.scene_number}] Image generated")

                        # Notify UI about new image
                        await self._notify_scene_update(scene.scene_number, {
                            "scene_num": scene.scene_number,
                            "image_url": f"/projects/{self.project.project_id}/scene_{scene.scene_number}/image.png",
                            "status": "image_ready"
                        })

                logger.info(f"[PIPELINE] Generated {generated_count}/{len(scenes_to_generate)} images in batch {batch_attempt}")

                # Check if all scenes got images
                missing_scenes = [s for s in self.project.scenes[1:] if not s.image_path]
                if missing_scenes:
                    logger.warning(f"[PIPELINE] Missing images for scenes: {[s.scene_number for s in missing_scenes]}")
                    if batch_attempt < max_batch_retries:
                        logger.info("[PIPELINE] Retrying missing scenes...")
                        await asyncio.sleep(5)
                else:
                    break

            except Exception as e:
                logger.error(f"[PIPELINE] Batch generation failed: {e}")
                if batch_attempt < max_batch_retries:
                    logger.info("[PIPELINE] Retrying entire batch...")
                    await asyncio.sleep(10)
                else:
                    raise

        # ================================================================
        # CRITICAL: ALL 6 IMAGES MUST EXIST BEFORE PROCEEDING
        # INFINITE RETRY - keep generating until ALL images are ready
        # ================================================================
        retry_round = 0

        while True:
            retry_round += 1

            # Check which scenes are missing images
            missing_scenes = []
            for scene in self.project.scenes:
                has_image = scene.image_path and Path(scene.image_path).exists()
                if not has_image:
                    missing_scenes.append(scene)

            # All images present - proceed
            if not missing_scenes:
                logger.success(f"[PIPELINE] ✅ ALL {len(self.project.scenes)} IMAGES READY!")
                break

            logger.warning(f"[PIPELINE] Round {retry_round}: Missing {len(missing_scenes)} images: {[s.scene_number for s in missing_scenes]}")
            await self.notify_log(f"🔄 Round {retry_round}: Generating {len(missing_scenes)} missing images...", "warning")
            await self._notify_image_retry(retry_round, missing_scenes)

            # Generate missing images individually
            for scene in missing_scenes:
                # LOOP_CLOSE (Scene 6): Copy from Scene 1 instead of generating
                if scene.reference_type == "LOOP_CLOSE":
                    scene_1_dir = settings.get_scene_dir(self.project.project_id, 1)
                    scene_dir = settings.get_scene_dir(self.project.project_id, scene.scene_number)
                    scene_1_image = scene_1_dir / "image.png"

                    if scene_1_image.exists():
                        scene_dir.mkdir(parents=True, exist_ok=True)
                        dest_image = scene_dir / "image.png"
                        shutil.copy(scene_1_image, dest_image)
                        scene.image_path = str(dest_image)
                        scene.status = SceneStatus.IMAGE_READY
                        scene.validation_approved = True
                        logger.success(f"[Scene {scene.scene_number}] ✅ Copied from Scene 1 (LOOP_CLOSE)")

                        cache_bust = int(time.time())
                        await self._notify_scene_update(scene.scene_number, {
                            "scene_num": scene.scene_number,
                            "image_url": f"/projects/{self.project.project_id}/scene_{scene.scene_number}/image.png?t={cache_bust}",
                            "status": "image_ready"
                        })
                    continue

                logger.info(f"[PIPELINE] Generating scene {scene.scene_number} (round {retry_round})...")
                try:
                    ref_image = Path(reference_image) if reference_image else None
                    image_path = await self.orchestrator.visual_engine.generate_scene_image(
                        prompt=scene.image_prompt,
                        scene_number=scene.scene_number,
                        project_id=self.project.project_id,
                        reference_image=ref_image,
                        reference_type=scene.reference_type,
                    )
                    if image_path:
                        scene.image_path = str(image_path)
                        scene.status = SceneStatus.IMAGE_READY
                        logger.success(f"[Scene {scene.scene_number}] ✅ Image generated: {image_path}")

                        # Notify UI immediately (with cache-bust for retries)
                        cache_bust = int(time.time())
                        await self._notify_scene_update(scene.scene_number, {
                            "scene_num": scene.scene_number,
                            "image_url": f"/projects/{self.project.project_id}/scene_{scene.scene_number}/image.png?t={cache_bust}",
                            "status": "image_ready"
                        })
                except Exception as e:
                    logger.error(f"[Scene {scene.scene_number}] Generation failed: {e}, will retry...")

            await asyncio.sleep(5)

        # Notify UI about all scenes
        await self._notify_all_scenes()

        # Validate images
        await self._notify_stage("VALIDATING_IMAGES", 50)
        await self._validate_scenes()

        await self.orchestrator._save_project_state(self.project)

    async def _validate_scenes(self):
        """Run VAL_IMG validation on all scenes with regeneration on failure."""

        if not self.project:
            return

        max_validation_retries = 3
        primary_scene = self.project.scenes[0] if self.project.scenes else None

        for scene in self.project.scenes[1:]:
            if scene.status != SceneStatus.IMAGE_READY:
                continue

            if not scene.image_path or not Path(scene.image_path).exists():
                continue

            # Skip validation for LOOP_CLOSE scenes (Scene 6) - they mirror Scene 1
            # which was already approved by user. Validating against LOOP_CLOSE prompt
            # is illogical since it should match the user-selected Scene 1.
            if scene.reference_type == "LOOP_CLOSE":
                logger.info(f"[Scene {scene.scene_number}] Skipping validation (LOOP_CLOSE mirrors user-approved Scene 1)")
                scene.status = SceneStatus.APPROVED
                scene.validation_approved = True
                continue

            validation_passed = False

            for attempt in range(1, max_validation_retries + 1):
                logger.info(f"[Scene {scene.scene_number}] Validating (attempt {attempt}/{max_validation_retries})...")

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
                        scene.status = SceneStatus.APPROVED
                        scene.validation_approved = True
                        validation_passed = True
                        logger.success(f"[Scene {scene.scene_number}] Validation PASSED (attempt {attempt})")
                        break
                    else:
                        issues_str = ', '.join(result.issues[:3]) if result.issues else result.feedback
                        logger.warning(f"[Scene {scene.scene_number}] Validation FAILED: {issues_str}")

                        if attempt < max_validation_retries:
                            # Regenerate the image
                            logger.info(f"[Scene {scene.scene_number}] Regenerating image (keeping existing reference)...")
                            scene.retry_count = getattr(scene, 'retry_count', 0) + 1

                            try:
                                # DON'T pass reference_image - it's already on the page!
                                # Passing it would cause upload of wrong image from gallery
                                new_image = await self.orchestrator.visual_engine.generate_scene_image(
                                    prompt=scene.image_prompt,
                                    scene_number=scene.scene_number,
                                    project_id=self.project.project_id,
                                    reference_image=None,  # Already set on page!
                                    reference_type=scene.reference_type
                                )
                                scene.image_path = str(new_image)
                                logger.success(f"[Scene {scene.scene_number}] New image generated")
                                await self.orchestrator._save_project_state(self.project)
                            except Exception as e:
                                logger.error(f"[Scene {scene.scene_number}] Regeneration failed: {e}")
                                break  # Can't continue without new image

                except Exception as e:
                    logger.error(f"[Scene {scene.scene_number}] Validation error: {e}")
                    break

            # If all attempts failed, approve anyway but mark as not validated
            if not validation_passed:
                logger.warning(f"[Scene {scene.scene_number}] All {max_validation_retries} attempts failed - approving anyway")
                scene.status = SceneStatus.APPROVED
                scene.validation_approved = False

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
                "image_url": f"/projects/{rel_path}",
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
        """Regenerate a single scene (reference already set, just change prompt)."""

        if not self.project:
            return

        scene = next((s for s in self.project.scenes if s.scene_number == scene_num), None)
        if not scene:
            return

        logger.info(f"[Scene {scene_num}] Regenerating (keeping existing reference)...")

        # Notify UI
        await self._notify_scene_update(scene_num, {"status": "regenerating"})

        # Regenerate using simple method - NO reference upload!
        # Reference is already on the page from initial batch generation
        try:
            # Use HiggsField image generator directly for simple regeneration
            image_gen = self.orchestrator.visual_engine._client._image_generator

            # Just clear prompt, enter new prompt, generate
            scene_dir = settings.get_scene_dir(self.project.project_id, scene.scene_number)
            scene_dir.mkdir(parents=True, exist_ok=True)

            # Generate single image (reference already set on page)
            result = await image_gen.generate_scene_image(
                prompt=scene.image_prompt,
                reference_image=None,  # DON'T upload reference - it's already there!
                reference_type=scene.reference_type
            )

            if result and result.path:
                # Copy to scene directory (overwrites existing)
                final_path = scene_dir / "image.png"

                # Remove old file first to ensure fresh copy
                if final_path.exists():
                    final_path.unlink()

                shutil.copy(result.path, final_path)

                scene.image_path = str(final_path)
                scene.status = SceneStatus.AWAITING_APPROVAL
                scene.validation_approved = True

                # Add timestamp to URL for cache busting
                cache_bust = int(time.time())
                await self._notify_scene_update(scene_num, {
                    "status": "approved",
                    "image_url": f"/projects/{self.project.project_id}/scene_{scene_num}/image.png?t={cache_bust}"
                })

                logger.success(f"[Scene {scene_num}] Regenerated: {final_path}")

        except Exception as e:
            logger.error(f"[Scene {scene_num}] Regeneration failed: {e}")

    async def _generate_videos(self):
        """Generate videos for all scenes using SimpleVideoGenerator."""

        if not self.project:
            return

        # ================================================================
        # ALL 6 images MUST exist before we start generating videos
        # ================================================================
        await self._notify_stage("GENERATING_VIDEOS", 70)
        logger.info("Generating videos for all scenes (SimpleVideoGenerator)...")

        # ================================================================
        # INFINITE RETRY - keep generating until ALL 6 videos are ready
        # FALLBACK: If scene 6 fails, use reversed scene 1
        # ================================================================
        retry_round = 0
        scene_6_fallback_used = False

        while True:
            retry_round += 1

            # Check which scenes need videos
            scenes_needing_video = []
            for scene in self.project.scenes:
                scene_dir = settings.PROJECTS_DIR / self.project.project_id / f"scene_{scene.scene_number}"
                video_path = scene_dir / "video.mp4"
                has_video = video_path.exists()

                if not has_video:
                    if scene.image_path and Path(scene.image_path).exists():
                        scenes_needing_video.append(scene)
                    else:
                        logger.error(f"[Scene {scene.scene_number}] No image! Cannot generate video.")

            # All videos present - proceed
            if not scenes_needing_video:
                logger.success(f"[PIPELINE] ✅ ALL {len(self.project.scenes)} VIDEOS READY!")
                await self._notify_all_scenes()
                break

            # FALLBACK: After 3 rounds, if only scene 6 is missing - use reversed scene 1
            scene_6_missing = any(s.scene_number == 6 for s in scenes_needing_video)
            only_scene_6_missing = len(scenes_needing_video) == 1 and scene_6_missing

            if retry_round > 3 and scene_6_missing and not scene_6_fallback_used:
                logger.warning(f"[PIPELINE] Scene 6 failed {retry_round} times - using FALLBACK: reversed Scene 1")
                await self.notify_log("🔄 Scene 6 fallback: creating from reversed Scene 1", "warning")

                fallback_success = await self._create_scene6_from_reversed_scene1()
                if fallback_success:
                    scene_6_fallback_used = True
                    # Update scene 6 status
                    scene_6 = next((s for s in self.project.scenes if s.scene_number == 6), None)
                    if scene_6:
                        scene_6_dir = settings.PROJECTS_DIR / self.project.project_id / "scene_6"
                        scene_6.video_path = str(scene_6_dir / "video.mp4")
                        scene_6.status = SceneStatus.VIDEO_READY
                    continue

            # If only scene 6 missing and fallback already used, something went wrong
            if only_scene_6_missing and scene_6_fallback_used:
                logger.error("[PIPELINE] Scene 6 fallback was used but video still missing!")
                break

            logger.warning(f"[PIPELINE] Video round {retry_round}: Missing {len(scenes_needing_video)} videos: {[s.scene_number for s in scenes_needing_video]}")
            await self.notify_log(f"🔄 Video round {retry_round}: Generating {len(scenes_needing_video)} videos...", "warning")
            await self._notify_video_retry(retry_round, scenes_needing_video)

            # Generate missing videos (exclude scene 6 if fallback will be used)
            scenes_to_generate = scenes_needing_video
            if retry_round > 3 and scene_6_missing:
                scenes_to_generate = [s for s in scenes_needing_video if s.scene_number != 6]

            if scenes_to_generate:
                scenes_data = [{
                    'scene_number': s.scene_number,
                    'image_path': s.image_path,
                    'video_prompt': s.motion_prompt,
                } for s in scenes_to_generate]

                try:
                    video_paths = await self.orchestrator.visual_engine.generate_all_videos_parallel(
                        scenes=scenes_data,
                        project_id=self.project.project_id,
                    )

                    # Update scene statuses and notify UI
                    for i, path in enumerate(video_paths):
                        if path and i < len(scenes_to_generate):
                            scene = scenes_to_generate[i]
                            scene.video_path = str(path)
                            scene.status = SceneStatus.VIDEO_READY
                            logger.success(f"[Scene {scene.scene_number}] Video ready: {path}")

                            # Notify UI immediately when each video is ready
                            from app.server.websocket import broadcast_event
                            video_cache_bust = int(time.time())
                            await broadcast_event("scene_video_ready", {
                                "project_id": self.project.project_id,
                                "scene_number": scene.scene_number,
                                "video_path": str(path),
                                "video_url": f"/projects/{self.project.project_id}/scene_{scene.scene_number}/video.mp4?t={video_cache_bust}"
                            })

                except Exception as e:
                    logger.error(f"Video generation failed: {e}, will retry...")

            await self.orchestrator._save_project_state(self.project)
            await asyncio.sleep(5)

    async def _create_scene6_from_reversed_scene1(self) -> bool:
        """
        FALLBACK: Create scene 6 video by reversing scene 1.
        Scene 6 is LOOP_CLOSE - it should mirror scene 1 for seamless loop.
        """
        try:
            project_dir = settings.PROJECTS_DIR / self.project.project_id
            scene_1_video = project_dir / "scene_1" / "video.mp4"
            scene_6_dir = project_dir / "scene_6"
            scene_6_video = scene_6_dir / "video.mp4"

            if not scene_1_video.exists():
                logger.error("[FALLBACK] Scene 1 video not found!")
                return False

            scene_6_dir.mkdir(parents=True, exist_ok=True)

            # Use ffmpeg to reverse video
            from app.core.config import settings as app_settings
            ffmpeg_path = app_settings.FFMPEG_PATH or "ffmpeg"

            import subprocess
            cmd = [
                str(ffmpeg_path), "-y",
                "-i", str(scene_1_video),
                "-vf", "reverse",
                "-af", "areverse",
                str(scene_6_video)
            ]

            logger.info(f"[FALLBACK] Reversing scene 1: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            if result.returncode == 0 and scene_6_video.exists():
                logger.success(f"[FALLBACK] ✅ Scene 6 created from reversed Scene 1: {scene_6_video}")
                return True
            else:
                logger.error(f"[FALLBACK] FFmpeg failed: {result.stderr}")
                return False

        except Exception as e:
            logger.error(f"[FALLBACK] Error creating scene 6: {e}")
            return False

    async def _assemble_final(self):
        """Assemble final video from scenes with audio."""

        if not self.project:
            return

        await self._notify_stage("ASSEMBLING_VIDEO", 90)

        project_dir = settings.PROJECTS_DIR / self.project.project_id
        manifest_path = project_dir / "gen3b_manifest.json"

        # ManifestRenderer - повноцінний монтаж з ефектами, субтитрами та аудіо
        if not manifest_path.exists():
            raise FileNotFoundError(f"Gen3b manifest not found: {manifest_path}")

        from app.services.manifest_renderer import ManifestRenderer
        from app.services.gen_models import Gen3bManifest

        logger.info("[PIPELINE] Using ManifestRenderer for full montage...")
        await self.notify_log("🎬 Rendering with effects, subtitles & audio mixing...", "info")

        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest_data = json.load(f)

        manifest = Gen3bManifest(**manifest_data)
        renderer = ManifestRenderer()

        result = await renderer.render(
            manifest=manifest,
            project_dir=project_dir,
            output_filename="final.mp4"
        )

        logger.success(f"[PIPELINE] Full montage rendered: {result}")

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

    async def notify_log(self, message: str, level: str = "info"):
        """Send log message to websocket clients."""
        from app.server.websocket import broadcast_event
        await broadcast_event("log", {
            "message": message,
            "level": level,
            "source": "control_pipeline"
        })

    async def _notify_merge_status(self, attempt: int, is_valid: bool, missing_fields: list, total_fields: int):
        """Notify about merge GEN1+GEN2 status."""
        from app.server.websocket import broadcast_event
        await broadcast_event("merge_status", {
            "total_attempts": attempt,
            "success": is_valid,
            "fields_ok": total_fields - len(missing_fields),
            "fields_total": total_fields,
            "missing_fields": missing_fields[:5]  # First 5 only
        })

    async def _notify_image_retry(self, attempt: int, missing_scenes: list):
        """Notify about image generation retry."""
        from app.server.websocket import broadcast_event
        from app.api.control_routes import get_state
        state = get_state()
        state.image_retry_count = attempt
        await broadcast_event("image_retry", {
            "attempt": attempt,
            "missing": [s.scene_number for s in missing_scenes]
        })

    async def _notify_video_retry(self, attempt: int, missing_scenes: list):
        """Notify about video generation retry."""
        from app.server.websocket import broadcast_event
        from app.api.control_routes import get_state
        state = get_state()
        state.video_retry_count = attempt
        await broadcast_event("video_retry", {
            "attempt": attempt,
            "missing": [s.scene_number for s in missing_scenes]
        })

    async def _notify_all_scenes(self):
        """Send full update of all scenes with image/video paths."""
        if not self.project:
            return
        from app.server.websocket import broadcast_event
        from app.api.control_routes import get_state
        state = get_state()
        scenes_data = []
        cache_bust = int(time.time())
        for scene in self.project.scenes:
            scene_dir = settings.PROJECTS_DIR / self.project.project_id / f"scene_{scene.scene_number}"
            image_url = f"/projects/{self.project.project_id}/scene_{scene.scene_number}/image.png?t={cache_bust}" if scene.image_path else None
            video_url = f"/projects/{self.project.project_id}/scene_{scene.scene_number}/video.mp4?t={cache_bust}" if (scene_dir / "video.mp4").exists() else None
            scenes_data.append({
                "scene_num": scene.scene_number,
                "image_url": image_url,
                "video_url": video_url,
                "reference_type": scene.reference_type,
                "status": scene.status.value if hasattr(scene.status, 'value') else str(scene.status)
            })
        state.all_scenes = scenes_data  # Update state for persistence
        await broadcast_event("all_scenes_update", {"scenes": scenes_data})

    # ========================================================================
    # VIDEO APPROVAL & TOPAZ
    # ========================================================================

    async def _video_approval(self) -> str:
        """
        Show assembled video and wait for user approval.

        Returns:
            'approved' - continue to Topaz
            'skip_upscale' - skip Topaz, mark as complete
            'rejected' - stop pipeline
        """
        if not self.project:
            return "approved"

        await self._notify_stage("AWAITING_VIDEO_APPROVAL", 92)

        project_dir = settings.PROJECTS_DIR / self.project.project_id

        # Find assembled video
        video_path = None
        for name in ["final.mp4", "assembled_video.mp4", "final_raw.mp4"]:
            path = project_dir / name
            if path.exists():
                video_path = path
                break

        if not video_path:
            logger.warning("[PIPELINE] No assembled video found, auto-approving")
            return "approved"

        # Get video info
        video_size_mb = video_path.stat().st_size / (1024 * 1024)
        video_url = f"/projects/{self.project.project_id}/{video_path.name}"

        logger.info(f"[PIPELINE] Video ready for approval: {video_path.name} ({video_size_mb:.1f} MB)")

        # Request approval from UI
        result = await self._request_approval("video_approval", {
            "video_url": video_url,
            "video_size_mb": round(video_size_mb, 1),
            "project_title": self.project.title,
            "message": "Review video before Topaz upscaling"
        })

        action = result.get("action", "approved")

        if action == "abort":
            logger.info("Pipeline aborted by user (new topic requested)")
            raise Exception("Pipeline aborted - new topic requested")

        logger.info(f"[PIPELINE] Video approval result: {action}")

        return action

    async def _generate_audio(self):
        """Generate voiceover and music for the project."""
        if not self.project:
            return

        await self._notify_stage("GENERATING_AUDIO", 72)

        project_dir = settings.PROJECTS_DIR / self.project.project_id
        voiceover_path = project_dir / "voiceover.mp3"
        music_dir = project_dir / "music"
        music_path = music_dir / "background.mp3"

        # Load project brief
        brief_path = project_dir / "project_brief.json"
        if not brief_path.exists():
            logger.warning("[PIPELINE] No project_brief.json for audio generation")
            return

        with open(brief_path, 'r', encoding='utf-8') as f:
            project_brief = json.load(f)

        # ==========================================
        # STEP 1: Generate Voiceover (ElevenLabs)
        # ==========================================
        if not voiceover_path.exists():
            try:
                from app.services.audio_engine import AudioEngine

                logger.info("[PIPELINE] Generating voiceover...")
                await self.notify_log("🎙️ Generating voiceover...", "info")

                audio_engine = AudioEngine()

                # Get full voiceover script
                voiceover_config = project_brief.get("voiceover", {})
                full_script = voiceover_config.get("full_script", "")

                if not full_script:
                    # Fallback: combine scene voiceovers
                    scenes = project_brief.get("scenes", [])
                    full_script = " ".join(
                        s.get("voiceover_segment", s.get("voiceover", ""))
                        for s in scenes
                    )

                if full_script:
                    # Get voice settings
                    voice_settings = voiceover_config.get("settings", {})
                    voice_id = voice_settings.get("voice_id", "Adam")

                    result_path = await audio_engine.generate_and_save_voiceover(
                        text=full_script,
                        output_path=voiceover_path,
                        voice_id=voice_id,
                    )

                    if result_path and result_path.exists():
                        logger.success(f"[PIPELINE] Voiceover generated: {result_path}")
                    else:
                        logger.warning("[PIPELINE] Voiceover generation returned no file")
                else:
                    logger.warning("[PIPELINE] No voiceover script found in brief")

            except Exception as e:
                logger.error(f"[PIPELINE] Voiceover generation failed: {e}")
        else:
            logger.info(f"[PIPELINE] Voiceover already exists: {voiceover_path}")

        # ==========================================
        # STEP 2: Generate Music (if MusicGenerator available)
        # ==========================================
        if not music_path.exists():
            try:
                from app.services.music_generator import MusicGenerator

                logger.info("[PIPELINE] Generating background music...")
                await self.notify_log("🎵 Generating background music...", "info")

                music_dir.mkdir(parents=True, exist_ok=True)
                music_generator = MusicGenerator()

                # Get music config from brief
                audio_config = project_brief.get("audio", {})
                bg_music = audio_config.get("background_music", {})

                prompt = bg_music.get("reference", f"{bg_music.get('genre', 'cinematic')} {bg_music.get('style', 'orchestral')} background music")
                duration = bg_music.get("duration_seconds", 60)

                result = await music_generator.generate(
                    prompt=prompt,
                    duration=duration,
                    output_path=music_path,
                )

                if result.success and result.file_path and result.file_path.exists():
                    logger.success(f"[PIPELINE] Music generated: {result.file_path}")
                else:
                    logger.warning(f"[PIPELINE] Music generation failed: {result.error if hasattr(result, 'error') else 'unknown'}")

            except ImportError:
                logger.warning("[PIPELINE] MusicGenerator not available, skipping music")
            except Exception as e:
                logger.error(f"[PIPELINE] Music generation failed: {e}")
        else:
            logger.info(f"[PIPELINE] Music already exists: {music_path}")

        logger.success("[PIPELINE] Audio generation complete")

    async def _run_gen3a_analysis(self):
        """Run Gen3a video analysis (Gemini Vision)."""
        if not self.project:
            return

        await self._notify_stage("GEN3A_ANALYSIS", 75)

        from app.services.gen3a_service import Gen3aService

        project_dir = settings.PROJECTS_DIR / self.project.project_id

        # Collect video paths
        video_paths = []
        for scene in sorted(self.project.scenes, key=lambda s: s.scene_number):
            if scene.video_path and Path(scene.video_path).exists():
                video_paths.append(Path(scene.video_path))

        if not video_paths:
            logger.warning("[PIPELINE] No videos found for Gen3a analysis, skipping")
            return

        logger.info(f"[PIPELINE] Running Gen3a analysis on {len(video_paths)} videos...")

        try:
            service = Gen3aService()

            # Load briefs
            project_brief = None
            brief_path = project_dir / "project_brief.json"
            if brief_path.exists():
                with open(brief_path, 'r', encoding='utf-8') as f:
                    project_brief = json.load(f)

            # Find music and voiceover paths
            music_path = project_dir / "music" / "background.mp3"
            if not music_path.exists():
                music_path = None

            voiceover_path = project_dir / "voiceover.mp3"
            if not voiceover_path.exists():
                voiceover_path = None

            # Run analysis
            analysis = await service.analyze_videos(
                video_paths=video_paths,
                gen1_brief=project_brief,
                gen2_brief=project_brief,
                music_path=music_path,
                voiceover_path=voiceover_path,
                project_dir=project_dir
            )

            if analysis:
                # Save analysis
                output_path = project_dir / "gen3a_analysis.json"
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(analysis.model_dump() if hasattr(analysis, 'model_dump') else analysis, f, indent=2, ensure_ascii=False)

                logger.success(f"[PIPELINE] Gen3a analysis saved: {output_path}")
            else:
                logger.warning("[PIPELINE] Gen3a analysis returned empty result")

        except Exception as e:
            logger.error(f"[PIPELINE] Gen3a analysis failed: {e}")
            # Don't raise - continue without analysis

    async def _run_gen3b_manifest(self):
        """Run Gen3b manifest generation."""
        if not self.project:
            return

        await self._notify_stage("GEN3B_MANIFEST", 80)

        from app.services.gen3b_service import Gen3bService

        project_dir = settings.PROJECTS_DIR / self.project.project_id

        # Check if Gen3a analysis exists
        gen3a_path = project_dir / "gen3a_analysis.json"
        if not gen3a_path.exists():
            logger.warning("[PIPELINE] No Gen3a analysis found, skipping Gen3b")
            return

        logger.info("[PIPELINE] Running Gen3b manifest generation...")

        try:
            service = Gen3bService()

            # Load Gen3a analysis
            with open(gen3a_path, 'r', encoding='utf-8') as f:
                gen3a_data = json.load(f)

            # Load project brief
            project_brief = None
            brief_path = project_dir / "project_brief.json"
            if brief_path.exists():
                with open(brief_path, 'r', encoding='utf-8') as f:
                    project_brief = json.load(f)

            # Convert dict to Gen3aOutput if needed
            from app.services.gen_models import Gen3aOutput
            if isinstance(gen3a_data, dict):
                gen3a_analysis = Gen3aOutput(**gen3a_data)
            else:
                gen3a_analysis = gen3a_data

            # Generate manifest
            manifest = await service.generate_manifest(
                gen3a_analysis=gen3a_analysis,
                gen1_brief=project_brief or {},
                gen2_brief=project_brief or {}
            )

            if manifest:
                # Save manifest
                output_path = project_dir / "gen3b_manifest.json"
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(manifest.model_dump() if hasattr(manifest, 'model_dump') else manifest, f, indent=2, ensure_ascii=False)

                logger.success(f"[PIPELINE] Gen3b manifest saved: {output_path}")
            else:
                logger.warning("[PIPELINE] Gen3b manifest generation returned empty result")

        except Exception as e:
            logger.error(f"[PIPELINE] Gen3b manifest generation failed: {e}")
            # Don't raise - continue without manifest

    async def _run_topaz_upscale(self):
        """Run Topaz Video AI upscaling."""
        if not self.project:
            return

        await self._notify_stage("TOPAZ_UPSCALING", 95)

        from app.modules.topaz_queue import TopazQueue

        project_dir = settings.PROJECTS_DIR / self.project.project_id

        # Search multiple possible video names (user may have edited/renamed)
        input_video = None
        for name in ["final.mp4", "final_video.mp4", "assembled_video.mp4", "final_raw.mp4"]:
            path = project_dir / name
            if path.exists() and path.stat().st_size > 0:
                input_video = path
                break

        if not input_video:
            logger.warning("[PIPELINE] No final video found for Topaz, skipping")
            return

        output_video = project_dir / "final_4k.mp4"

        logger.info(f"[PIPELINE] Starting Topaz upscaling: {input_video}")

        try:
            queue = TopazQueue()

            # Check if Topaz is available
            if not queue.is_topaz_available:
                logger.warning("[PIPELINE] Topaz not available, skipping upscaling")
                return

            # Start worker
            await queue.start()

            # Add task for final video (scene_number=0 for final)
            task = await queue.add_task(
                project_id=self.project.project_id,
                scene_number=0,  # 0 = final video
                input_path=input_video,
                output_dir=project_dir,
            )

            logger.info(f"[PIPELINE] Topaz task added: {task.task_id}")

            # Wait for completion (30 min timeout)
            completed = await queue.wait_for_completion(timeout=1800)

            if completed:
                # Check if output exists
                if output_video.exists():
                    logger.success(f"[PIPELINE] Topaz upscaling complete: {output_video}")
                else:
                    logger.warning("[PIPELINE] Topaz completed but no output file found")
            else:
                logger.error("[PIPELINE] Topaz processing timed out or failed")

            # Stop worker
            await queue.stop()

        except Exception as e:
            logger.error(f"[PIPELINE] Topaz error: {e}")
            # Don't raise - continue without upscaling

    async def _upload_to_youtube(self):
        """Upload final video to YouTube."""
        if not self.project:
            return

        await self._notify_stage("YOUTUBE_UPLOAD", 98)

        project_dir = settings.PROJECTS_DIR / self.project.project_id

        # Find best available video (prefer 4K)
        video_path = None
        for name in ["final_4k.mp4", "final.mp4"]:
            path = project_dir / name
            if path.exists():
                video_path = path
                break

        if not video_path:
            logger.warning("[PIPELINE] No video found for YouTube upload")
            return

        # Load project brief for metadata
        brief_path = project_dir / "project_brief.json"
        if not brief_path.exists():
            logger.warning("[PIPELINE] No project_brief.json for YouTube metadata")
            return

        with open(brief_path, 'r', encoding='utf-8') as f:
            brief = json.load(f)

        # Extract YouTube metadata
        youtube_data = brief.get('youtube', {})
        title = youtube_data.get('title', self.project.title or 'Untitled')
        description = youtube_data.get('description', '')
        tags = youtube_data.get('tags', [])

        logger.info(f"[PIPELINE] Preparing YouTube upload...")
        logger.info(f"  Title: {title}")
        logger.info(f"  Video: {video_path.name} ({video_path.stat().st_size / 1024 / 1024:.1f} MB)")

        # Request upload approval from UI
        result = await self._request_approval("youtube_upload", {
            "title": title,
            "description": description[:200] + "..." if len(description) > 200 else description,
            "video_path": str(video_path),
            "video_size_mb": round(video_path.stat().st_size / 1024 / 1024, 1),
        })

        action = result.get("action", "skip")
        if action == "skip":
            logger.info("[PIPELINE] YouTube upload skipped by user")
            return

        if action != "upload":
            logger.info(f"[PIPELINE] YouTube upload cancelled: {action}")
            return

        try:
            # Import YouTube API
            import sys
            sys.path.insert(0, str(settings.BASE_DIR / "src"))
            from publisher.youtube_api import YouTubeAPI
            from publisher.models import ChannelConfig, PrivacyStatus

            # Load channel config
            channels_dir = settings.BASE_DIR / "config" / "channels"
            default_channel = channels_dir / "default"

            if not default_channel.exists():
                logger.warning("[PIPELINE] No default YouTube channel configured")
                return

            # Load channel config
            channel_config_path = default_channel / "channel.json"
            token_path = default_channel / "token.json"
            secrets_path = settings.BASE_DIR / "config" / "client_secrets.json"

            if not all(p.exists() for p in [channel_config_path, secrets_path]):
                logger.warning("[PIPELINE] YouTube channel not fully configured")
                return

            with open(channel_config_path, 'r', encoding='utf-8') as f:
                channel_data = json.load(f)

            channel_config = ChannelConfig(**channel_data)

            # Initialize YouTube API
            api = YouTubeAPI(
                channel_config=channel_config,
                client_secrets_path=secrets_path,
                token_path=token_path
            )

            # Authenticate
            if not api.authenticate():
                logger.error("[PIPELINE] YouTube authentication failed")
                return

            # Upload video
            logger.info("[PIPELINE] Uploading to YouTube...")
            success, video_id, error = api.upload_video(
                video_path=video_path,
                title=title,
                description=description,
                tags=tags,
                privacy_status=PrivacyStatus.PUBLIC,
            )

            if success and video_id:
                video_url = f"https://youtube.com/watch?v={video_id}"
                logger.success(f"[PIPELINE] YouTube upload complete: {video_url}")

                # Notify UI
                await broadcast_youtube_success(video_url)
            else:
                logger.error(f"[PIPELINE] YouTube upload failed: {error}")

        except ImportError as e:
            logger.warning(f"[PIPELINE] YouTube module not available: {e}")
        except Exception as e:
            logger.error(f"[PIPELINE] YouTube upload error: {e}")
            # Don't raise - pipeline is essentially complete


async def broadcast_youtube_success(video_url: str):
    """Broadcast YouTube upload success to WebSocket clients."""
    try:
        from app.api.control_routes import broadcast_event
        await broadcast_event("youtube_uploaded", {"video_url": video_url})
    except Exception:
        pass
