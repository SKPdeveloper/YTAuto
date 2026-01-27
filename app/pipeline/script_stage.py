"""
Script Generation Stage v2.0

Generates video script using GEN1 (Creative Director) + GEN2 (Visual Director).
Now with detailed logging of GEN1/GEN2 outputs and merge analysis for web client.
"""

import json
from typing import Optional, Dict, Any, List
from pathlib import Path

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
        """Generate script via PromptRouter with detailed logging and retry on validation failure"""

        MAX_RETRIES = 7
        await self.notify_progress(0, "Starting script generation...")

        try:
            # Use PromptRouter for two-stage generation
            router = PromptRouter()

            # ================================================================
            # STAGE 1: GEN1 with validation and retry
            # ================================================================
            await self.notify_progress(5, "🎬 Запуск GEN1 (Creative Director)...")
            await self.notify_log("═══ ЕТАП 1: GEN1 (Creative Director) ═══", "info")

            gen1_output = None
            gen1_validated = False
            last_retry_guidance = None

            for attempt in range(1, MAX_RETRIES + 1):
                await self.notify_log(f"[GEN1] Спроба {attempt}/{MAX_RETRIES}...", "info")

                # Run GEN1
                gen1_output = await router.run_gen1(
                    topic=self.project.topic,
                    num_scenes=self.project.num_scenes,
                    style=self.project.style or "cinematic food fantasy",
                    target_audience=self.project.target_audience or "YouTube Shorts viewers",
                    project_id=self.project.project_id,
                    retry_guidance=last_retry_guidance,
                )

                if not gen1_output:
                    await self.notify_log(f"❌ GEN1 повернув порожній результат (спроба {attempt})", "error")
                    if attempt < MAX_RETRIES:
                        await self.notify_log("🔄 Retry GEN1...", "warning")
                    continue

                # Validate GEN1 output
                await self.notify_log(f"[VAL_GEN1] Валідація GEN1 (спроба {attempt})...", "info")
                val_result = await router.validate_gen1(
                    gen1_output=gen1_output,
                    original_topic=self.project.topic or "",
                    project_id=self.project.project_id,
                )

                if val_result and val_result.passed:
                    await self.notify_log(f"✅ GEN1 валідація PASSED (спроба {attempt})", "success")
                    gen1_validated = True
                    break
                else:
                    await self.notify_log(f"⚠️ GEN1 валідація FAILED (спроба {attempt})", "warning")
                    if val_result and val_result.retry_guidance:
                        last_retry_guidance = val_result.retry_guidance.fixes_needed
                        for fix in last_retry_guidance[:3]:
                            await self.notify_log(f"  → {fix}", "warning")
                    if attempt < MAX_RETRIES:
                        await self.notify_log(f"🔄 Retry GEN1 з feedback...", "warning")

            if not gen1_output or not gen1_validated:
                await self.notify_log(f"❌ GEN1 FAILED після {MAX_RETRIES} спроб", "error")
                return StageResult(
                    success=False,
                    stage_name=self.name,
                    status=StageStatus.FAILED,
                    message=f"GEN1 validation failed after {MAX_RETRIES} attempts"
                )

            # Log GEN1 output details to client
            await self._log_gen1_output_to_client(gen1_output)

            # ================================================================
            # STAGE 2: GEN2 with validation and retry
            # ================================================================
            await self.notify_progress(30, "✅ GEN1 завершено. Запуск GEN2...")
            await self.notify_log("═══ ЕТАП 2: GEN2 (Visual Director) ═══", "info")

            # Create delivery payload
            delivery_payload = router.create_delivery_payload(gen1_output, self.project.project_id)

            gen2_output = None
            gen2_validated = False
            last_gen2_retry_guidance = None

            for attempt in range(1, MAX_RETRIES + 1):
                await self.notify_log(f"[GEN2] Спроба {attempt}/{MAX_RETRIES}...", "info")

                # Run GEN2
                gen2_output = await router.run_gen2(
                    payload=delivery_payload,
                    project_id=self.project.project_id,
                    retry_guidance=last_gen2_retry_guidance,
                )

                if not gen2_output:
                    await self.notify_log(f"❌ GEN2 повернув порожній результат (спроба {attempt})", "error")
                    if attempt < MAX_RETRIES:
                        await self.notify_log("🔄 Retry GEN2...", "warning")
                    continue

                # Validate GEN2 output
                await self.notify_log(f"[VAL_GEN2] Валідація GEN2 (спроба {attempt})...", "info")
                val_result = await router.validate_gen2(
                    gen2_output=gen2_output,
                    gen1_output=gen1_output,
                    project_id=self.project.project_id,
                )

                if val_result and val_result.passed:
                    await self.notify_log(f"✅ GEN2 валідація PASSED (спроба {attempt})", "success")
                    gen2_validated = True
                    break
                else:
                    await self.notify_log(f"⚠️ GEN2 валідація FAILED (спроба {attempt})", "warning")
                    if val_result and val_result.retry_guidance:
                        last_gen2_retry_guidance = val_result.retry_guidance.fixes_needed
                        for fix in last_gen2_retry_guidance[:3]:
                            await self.notify_log(f"  → {fix}", "warning")
                    if attempt < MAX_RETRIES:
                        await self.notify_log(f"🔄 Retry GEN2 з feedback...", "warning")

            if not gen2_output or not gen2_validated:
                await self.notify_log(f"❌ GEN2 FAILED після {MAX_RETRIES} спроб", "error")
                return StageResult(
                    success=False,
                    stage_name=self.name,
                    status=StageStatus.FAILED,
                    message=f"GEN2 validation failed after {MAX_RETRIES} attempts"
                )

            # Log GEN2 output details to client
            await self._log_gen2_output_to_client(gen2_output)

            await self.notify_progress(55, "✅ GEN2 завершено. Об'єднання результатів...")
            await self.notify_log("═══ ЕТАП 3: MERGE (Об'єднання) ═══", "info")

            # ================================================================
            # MERGE with validation and retry
            # If any field is missing after merge, retry GEN1+GEN2 generation
            # ================================================================
            MAX_MERGE_RETRIES = 3
            glaze_project = None
            merge_valid = False

            for merge_attempt in range(1, MAX_MERGE_RETRIES + 1):
                await self.notify_log(f"[MERGE] Спроба {merge_attempt}/{MAX_MERGE_RETRIES}...", "info")

                # Merge GEN1 + GEN2 into GlazeProject
                glaze_project = router.merge_outputs(gen1_output, gen2_output, self.project.project_id)

                if not glaze_project:
                    await self.notify_log(f"❌ Помилка об'єднання GEN1 + GEN2 (спроба {merge_attempt})", "error")
                    if merge_attempt < MAX_MERGE_RETRIES:
                        await self.notify_log("🔄 Regenerating GEN1+GEN2...", "warning")
                        # Regenerate GEN1
                        gen1_output = await router.run_gen1(
                            topic=self.project.topic,
                            num_scenes=self.project.num_scenes,
                            style=self.project.style or "cinematic food fantasy",
                            target_audience=self.project.target_audience or "YouTube Shorts viewers",
                            project_id=self.project.project_id,
                        )
                        if gen1_output:
                            delivery_payload = router.create_delivery_payload(gen1_output, self.project.project_id)
                            gen2_output = await router.run_gen2(
                                payload=delivery_payload,
                                project_id=self.project.project_id,
                            )
                    continue

                # Validate merged brief for ALL required fields
                is_valid, missing_fields = router.validate_merged_brief(glaze_project)

                # Send merge status to websocket
                await self._notify_merge_status(
                    attempt=merge_attempt,
                    is_valid=is_valid,
                    missing_fields=missing_fields,
                    total_fields=214  # Approximate total fields in merged brief
                )

                if is_valid:
                    await self.notify_log(f"✅ MERGE валідація PASSED (спроба {merge_attempt})", "success")
                    merge_valid = True
                    break
                else:
                    await self.notify_log(f"⚠️ MERGE валідація FAILED (спроба {merge_attempt})", "warning")
                    await self.notify_log(f"❌ Відсутні поля: {len(missing_fields)}", "warning")
                    for field in missing_fields[:5]:  # Show first 5 missing fields
                        await self.notify_log(f"  → {field}", "warning")
                    if len(missing_fields) > 5:
                        await self.notify_log(f"  → ... та ще {len(missing_fields) - 5} полів", "warning")

                    if merge_attempt < MAX_MERGE_RETRIES:
                        await self.notify_log("🔄 Regenerating GEN1+GEN2 to fix missing fields...", "warning")
                        # Regenerate GEN1
                        gen1_output = await router.run_gen1(
                            topic=self.project.topic,
                            num_scenes=self.project.num_scenes,
                            style=self.project.style or "cinematic food fantasy",
                            target_audience=self.project.target_audience or "YouTube Shorts viewers",
                            project_id=self.project.project_id,
                        )
                        if gen1_output:
                            delivery_payload = router.create_delivery_payload(gen1_output, self.project.project_id)
                            gen2_output = await router.run_gen2(
                                payload=delivery_payload,
                                project_id=self.project.project_id,
                            )

            if not glaze_project or not merge_valid:
                await self.notify_log(f"❌ MERGE FAILED після {MAX_MERGE_RETRIES} спроб", "error")
                return StageResult(
                    success=False,
                    stage_name=self.name,
                    status=StageStatus.FAILED,
                    message=f"Merge validation failed after {MAX_MERGE_RETRIES} attempts - missing required fields"
                )

            # Log merge analysis to client
            await self._log_merge_analysis_to_client(gen1_output, gen2_output, glaze_project)

            await self.notify_progress(70, "Processing merged output...")

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

            # Also save GEN1 and GEN2 outputs separately for debugging
            await self._save_gen_outputs(project_dir, gen1_output, gen2_output)

            await self.notify_progress(100, "✅ Script generation complete")

            # Final summary log
            await self.notify_log(f"🎉 Генерація завершена: {self.project.title}", "success")
            await self.notify_log(f"📝 Сцен: {len(self.project.scenes)}", "info")
            await self.notify_log(f"🎯 Reference types: {[s.reference_type for s in self.project.scenes]}", "info")

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
            await self.notify_log(f"❌ Помилка: {str(e)}", "error")
            return StageResult(
                success=False,
                stage_name=self.name,
                status=StageStatus.FAILED,
                message=str(e),
                error=e
            )

    async def _log_gen1_output_to_client(self, gen1) -> None:
        """Log GEN1 output details to web client"""
        await self.notify_log(f"📋 Назва: {gen1.metadata.title}", "info")
        await self.notify_log(f"🏠 Об'єкт: {gen1.property.name}", "info")
        await self.notify_log(f"🍕 Їжа: {gen1.food_identity.primary_food}", "info")
        await self.notify_log(f"🏛️ Архітектура: {gen1.architectural_identity.style_code}", "info")
        await self.notify_log(f"💡 Освітлення: {gen1.lighting_master.preset}", "info")
        await self.notify_log(f"🎣 Hook: {gen1.hook.type} ({gen1.hook.psychological_trigger})", "info")

        # Log scenes summary
        await self.notify_log(f"📹 Сцен: {len(gen1.scenes)}", "info")
        for scene in gen1.scenes:
            await self.notify_log(
                f"  Scene {scene.scene_number}: {scene.scene_name} | {scene.narrative_purpose} | {scene.energy_level}",
                "info"
            )

        # Log audio config
        await self.notify_log(f"🎵 Музика: {gen1.audio.suno_prompt[:80]}...", "info")
        await self.notify_log(f"🥚 Easter Egg: Scene {gen1.engagement.easter_egg.scene_number} - {gen1.engagement.easter_egg.object}", "info")

    async def _log_gen2_output_to_client(self, gen2) -> None:
        """Log GEN2 output details to web client"""
        await self.notify_log(f"🎨 Генеровано visual prompts для {len(gen2.scenes)} сцен", "info")

        # Reference type breakdown
        ref_counts = {}
        for scene in gen2.scenes:
            ref_type = scene.reference_type
            ref_counts[ref_type] = ref_counts.get(ref_type, 0) + 1
        await self.notify_log(f"🔗 Reference breakdown: {ref_counts}", "info")

        # Log each scene's prompts (shortened)
        for scene in gen2.scenes:
            img_short = scene.image_prompt[:60] + "..." if len(scene.image_prompt) > 60 else scene.image_prompt
            vid_short = scene.video_prompt[:60] + "..." if len(scene.video_prompt) > 60 else scene.video_prompt
            await self.notify_log(
                f"  Scene {scene.scene_number} [{scene.reference_type}]:",
                "info"
            )
            await self.notify_log(f"    Image: {img_short}", "info")
            await self.notify_log(f"    Motion: {scene.motion_elements}", "info")

        # Visual summary
        if gen2.visual_summary:
            await self.notify_log(f"🎯 Loop verified: {gen2.visual_summary.loop_verified}", "info")
            await self.notify_log(f"🦣 Gigantism protocol: {gen2.visual_summary.gigantism_protocol}", "info")

    async def _log_merge_analysis_to_client(self, gen1, gen2, merged) -> None:
        """Log merge analysis to web client"""
        await self.notify_log("🔄 Аналіз об'єднання GEN1 + GEN2:", "info")

        # Check what was merged for each scene
        for i, scene in enumerate(merged.scenes):
            gen1_scene = gen1.scenes[i] if i < len(gen1.scenes) else None
            gen2_scene = gen2.scenes[i] if i < len(gen2.scenes) else None

            merge_info = []
            if gen1_scene:
                merge_info.append(f"GEN1: {gen1_scene.scene_name}")
            if gen2_scene:
                merge_info.append(f"GEN2: {gen2_scene.reference_type}")

            await self.notify_log(
                f"  Scene {scene.scene_number}: {' + '.join(merge_info)} → Merged ✓",
                "success"
            )

        # Summary
        await self.notify_log(f"✅ Об'єднано: voiceover, image_prompt, video_prompt, reference_type", "success")
        await self.notify_log(f"✅ Збережено: architectural_identity, food_identity, lighting, audio", "success")

    async def _save_gen_outputs(self, project_dir: Path, gen1, gen2) -> None:
        """Save GEN1 and GEN2 outputs separately for debugging"""
        try:
            # Save GEN1
            gen1_path = project_dir / "gen1_output.json"
            with open(gen1_path, "w", encoding="utf-8") as f:
                f.write(gen1.model_dump_json(indent=2))

            # Save GEN2
            gen2_path = project_dir / "gen2_output.json"
            with open(gen2_path, "w", encoding="utf-8") as f:
                f.write(gen2.model_dump_json(indent=2))

            logger.info(f"[{self.project_id}] Saved gen1_output.json and gen2_output.json")
        except Exception as e:
            logger.warning(f"[{self.project_id}] Failed to save GEN outputs: {e}")

    async def _notify_merge_status(self, attempt: int, is_valid: bool, missing_fields: list, total_fields: int) -> None:
        """Send merge status to websocket for UI display."""
        try:
            from app.server.websocket import broadcast_event
            await broadcast_event("merge_status", {
                "total_attempts": attempt,
                "success": is_valid,
                "fields_ok": total_fields - len(missing_fields),
                "fields_total": total_fields,
                "missing_fields": missing_fields[:5] if missing_fields else []  # First 5 only
            })
        except Exception as e:
            logger.warning(f"Failed to send merge status notification: {e}")
