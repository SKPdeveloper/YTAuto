"""
Audio Stage - Pre-generation audio assets

Generates all audio assets BEFORE GEN3a analysis:
- voiceover.mp3 - ElevenLabs TTS from project_brief.json
- music.mp3 - Replicate Stable Audio background music
- ambient.mp3 - Optional ambient bed

This ensures GEN3a preprocessing has audio files for beat sync analysis.
"""

import json
from pathlib import Path
from typing import Optional, List

from loguru import logger

from app.pipeline.base import BasePipelineStage, StageResult, StageStatus
from app.api.schemas import ProjectData
from app.services.audio_engine import AudioEngine
from app.services.music_generator import MusicGenerator
from app.core.config import settings


class AudioStage(BasePipelineStage):
    """
    Stage 5: Audio Generation

    Generates all audio assets before GEN3a analysis.

    Process:
    1. Load project_brief.json for voiceover text
    2. Generate voiceover.mp3 via ElevenLabs
    3. Generate music.mp3 via Replicate Stable Audio
    4. Generate ambient.mp3 (optional)

    Output:
    - {project_dir}/voiceover.mp3
    - {project_dir}/music.mp3
    - {project_dir}/ambient.mp3 (optional)
    """

    name = "audio_generation"
    description = "Generate voiceover, music, and ambient audio"

    def __init__(self, project: ProjectData, **kwargs):
        super().__init__(project, **kwargs)
        self.audio_engine = AudioEngine()
        self.music_generator = MusicGenerator()

    async def can_run(self) -> bool:
        """Check if audio generation should run"""
        project_dir = Path(self.project.project_dir) if hasattr(self.project, 'project_dir') else Path(settings.PROJECTS_DIR) / self.project_id

        # Check if videos exist by scanning disk (more reliable than self.project.scenes)
        # VideoStage may not update scene.video_path, so we check actual files
        total_scenes = getattr(self.project, 'total_scenes', 0) or len(getattr(self.project, 'scenes', []))
        if total_scenes < 6:
            total_scenes = 10  # scan up to max if unknown
        video_count = 0
        for scene_num in range(1, total_scenes + 1):
            scene_dir = project_dir / f"scene_{scene_num}"
            video_path = scene_dir / "video.mp4"
            if video_path.exists():
                video_count += 1

        # Need at least half the videos to proceed (allow some flexibility)
        min_videos = max(3, total_scenes // 2)
        has_videos = video_count >= min_videos
        if not has_videos:
            logger.debug(f"[{self.project_id}] AudioStage: Only {video_count}/{total_scenes} videos found, skipping")

        # Check if audio files already exist (check multiple possible locations)
        # IMPORTANT: voiceover requires BOTH mp3 AND alignment for word-by-word subtitles
        voiceover_mp3_exists = (project_dir / "voiceover.mp3").exists()
        voiceover_alignment_exists = (project_dir / "vo_alignment.json").exists()
        voiceover_complete = voiceover_mp3_exists and voiceover_alignment_exists

        music_exists = (
            (project_dir / "music.mp3").exists() or
            (project_dir / "music" / "background.mp3").exists()
        )

        # Check if SFX exist (at least sonic_hook or scene SFX)
        sfx_dir = project_dir / "sfx"
        sfx_exists = sfx_dir.exists() and any(sfx_dir.glob("*.mp3"))

        # Run if we have videos but missing any audio asset
        # NOTE: voiceover_complete requires BOTH mp3 and alignment - no fallback!
        should_run = has_videos and (not voiceover_complete or not music_exists or not sfx_exists)

        if has_videos and not should_run:
            logger.debug(f"[{self.project_id}] AudioStage: All audio exists (vo={voiceover_complete}, music={music_exists}, sfx={sfx_exists})")
        elif has_videos and voiceover_mp3_exists and not voiceover_alignment_exists:
            logger.warning(f"[{self.project_id}] AudioStage: voiceover.mp3 exists but vo_alignment.json missing - will regenerate with timestamps")

        return should_run

    async def can_resume(self) -> bool:
        """Audio generation can be resumed"""
        return True

    async def execute(self) -> StageResult:
        """Generate all audio assets"""

        await self.notify_progress(0, "Starting audio generation...")

        project_dir = Path(self.project.project_dir) if hasattr(self.project, 'project_dir') else Path(settings.PROJECTS_DIR) / self.project_id

        try:
            # Load project brief for voiceover text
            brief_path = project_dir / "project_brief.json"
            if not brief_path.exists():
                return StageResult(
                    success=False,
                    stage_name=self.name,
                    status=StageStatus.FAILED,
                    message="project_brief.json not found"
                )

            with open(brief_path, "r", encoding="utf-8") as f:
                project_brief = json.load(f)

            # Calculate estimated video duration based on scene count
            total = getattr(self.project, 'total_scenes', 0) or len(getattr(self.project, 'scenes', []))
            estimated_duration = max(total, 6) * 10.0  # ~10s per scene

            # PUSH: Start notification
            await self.notifier.push_info(
                title="Audio Generation Started",
                message="Generating voiceover and background music...",
                project_id=self.project_id
            )

            # Step 1: Generate voiceover
            await self.notify_progress(10, "Generating voiceover...")
            voiceover_path = await self._generate_voiceover(project_dir, project_brief)

            # Step 2: Generate music
            await self.notify_progress(40, "Generating background music...")
            music_path = await self._generate_music(project_dir, project_brief, estimated_duration)

            # Step 3: Generate ambient bed (optional)
            await self.notify_progress(55, "Generating ambient bed...")
            ambient_path = await self._generate_ambient_bed(project_dir, estimated_duration)

            # Step 4: Generate SFX for each scene
            await self.notify_progress(70, "Generating sound effects...")
            sfx_paths = await self._generate_sfx(project_dir, project_brief)

            await self.notify_progress(100, "Audio generation complete!")

            # Build result data
            result_data = {
                "voiceover": str(voiceover_path) if voiceover_path else None,
                "music": str(music_path) if music_path else None,
                "ambient": str(ambient_path) if ambient_path else None,
                "sfx": {k: str(v) for k, v in sfx_paths.items()} if sfx_paths else None,
            }

            # PUSH: Success notification
            sfx_count = len(sfx_paths) if sfx_paths else 0
            await self.notifier.push_success(
                title="Audio Ready",
                message=f"Generated voiceover, music, ambient, and {sfx_count} SFX",
                project_id=self.project_id
            )

            return StageResult(
                success=True,
                stage_name=self.name,
                message="Audio assets generated successfully",
                data=result_data
            )

        except Exception as e:
            logger.error(f"[{self.project_id}] Audio generation failed: {e}")

            await self.notifier.push_error(
                title="Audio Generation Error",
                message=str(e)[:100],
                project_id=self.project_id,
                is_critical=False  # Not critical - can continue without audio
            )

            return StageResult(
                success=False,
                stage_name=self.name,
                status=StageStatus.FAILED,
                message=str(e),
                error=e
            )

    async def _generate_voiceover(
        self,
        project_dir: Path,
        project_brief: dict
    ) -> Optional[Path]:
        """
        Generate voiceover with character-level timestamps for perfect subtitle sync.

        Uses ElevenLabs convert_with_timestamps API for character-level alignment.
        Saves:
        - voiceover.mp3: Combined audio
        - vo_alignment.json: Character-level timestamps (for word-by-word subtitles)
        - voiceover_timing.json: Scene-level timing (for GEN3b)
        - subtitles.ass: Netflix-style word-by-word subtitles
        """
        import json

        voiceover_path = project_dir / "voiceover.mp3"
        alignment_path = project_dir / "vo_alignment.json"
        timing_path = project_dir / "voiceover_timing.json"
        subtitles_path = project_dir / "subtitles.ass"

        # Check if voiceover with alignment already exists (BOTH required)
        if voiceover_path.exists() and alignment_path.exists():
            logger.info(f"[{self.project_id}] Voiceover with alignment already exists")
            return voiceover_path

        # If only voiceover exists without alignment, delete it to force regeneration
        if voiceover_path.exists() and not alignment_path.exists():
            logger.warning(f"[{self.project_id}] voiceover.mp3 exists without vo_alignment.json - deleting to regenerate with timestamps")
            voiceover_path.unlink()

        # Try to use full_script from voiceover config (preferred - single call with timestamps)
        voiceover_config = project_brief.get("voiceover", {})
        full_script = voiceover_config.get("full_script", "")

        if full_script:
            # Use unified generation with character-level timestamps
            try:
                from app.services.glaze_models import VoiceoverSettings, VoiceoverConfig

                settings_data = voiceover_config.get("settings", {})
                vo_config = VoiceoverConfig(
                    settings=VoiceoverSettings(**settings_data) if settings_data else VoiceoverSettings(),
                    full_script=full_script,
                    total_duration_seconds=voiceover_config.get("total_duration_seconds", 30),
                )

                logger.info(f"[{self.project_id}] Generating voiceover with ElevenLabs timestamps...")

                # Generate with timestamps - this saves all required files
                result_vo, result_align, result_subs, result_timing = await self.audio_engine.generate_voiceover_and_subtitles(
                    voiceover_config=vo_config,
                    project_dir=project_dir,
                    hook_offset=0.3,  # Standard hook offset
                )

                logger.success(f"[{self.project_id}] Voiceover generated with character-level alignment")
                logger.info(f"[{self.project_id}]   Audio: {result_vo}")
                logger.info(f"[{self.project_id}]   Alignment: {result_align}")
                logger.info(f"[{self.project_id}]   Subtitles: {result_subs}")
                logger.info(f"[{self.project_id}]   Timing: {result_timing}")

                return result_vo

            except Exception as e:
                # NO FALLBACK - voiceover with timestamps is required for word-by-word subtitles
                logger.error(f"[{self.project_id}] Voiceover generation with timestamps FAILED: {e}")
                logger.error(f"[{self.project_id}] This is a critical error - word-by-word subtitles require ElevenLabs timestamps")
                raise RuntimeError(f"Voiceover generation failed: {e}. ElevenLabs timestamps are required for word-by-word subtitles.")

        # No full_script in voiceover config - this is an error
        logger.error(f"[{self.project_id}] No full_script found in voiceover config - cannot generate voiceover")
        raise ValueError("No full_script found in project_brief.voiceover - voiceover generation requires full_script")

    async def _generate_music(
        self,
        project_dir: Path,
        project_brief: dict,
        duration: float
    ) -> Optional[Path]:
        """Generate background music using Replicate Stable Audio"""

        music_path = project_dir / "music.mp3"

        if music_path.exists():
            logger.info(f"[{self.project_id}] Background music already exists")
            return music_path

        try:
            # Determine atmosphere from project concept
            atmosphere = "cinematic"
            concept = project_brief.get("concept", "") or project_brief.get("title", "")
            if concept:
                concept_lower = concept.lower()
                if any(word in concept_lower for word in ["mystery", "dark", "scary"]):
                    atmosphere = "mysterious"
                elif any(word in concept_lower for word in ["fun", "party", "celebration"]):
                    atmosphere = "upbeat"
                elif any(word in concept_lower for word in ["epic", "grand", "massive"]):
                    atmosphere = "epic"
                elif any(word in concept_lower for word in ["chill", "relax", "peaceful"]):
                    atmosphere = "chill"

            result = await self.music_generator.generate_for_project(
                project_dir=project_dir,
                atmosphere=atmosphere,
                duration=min(duration, 47.0),  # Stable Audio max 47s
            )

            if result.success and result.file_path:
                logger.success(f"[{self.project_id}] Background music generated: {atmosphere}")
                return result.file_path
            else:
                logger.warning(f"[{self.project_id}] Music generation failed: {result.error}")

        except Exception as e:
            logger.error(f"[{self.project_id}] Music generation error: {e}")

        return None

    async def _generate_ambient_bed(
        self,
        project_dir: Path,
        duration: float
    ) -> Optional[Path]:
        """Generate ambient bed audio for BED layer"""

        ambient_path = project_dir / "ambient.mp3"

        if ambient_path.exists():
            logger.info(f"[{self.project_id}] Ambient bed already exists")
            return ambient_path

        try:
            result = await self.music_generator.generate_ambient_bed(
                project_dir=project_dir,
                duration=min(duration, 47.0),
            )

            if result.success and result.file_path:
                logger.success(f"[{self.project_id}] Ambient bed generated")
                return result.file_path
            else:
                logger.warning(f"[{self.project_id}] Ambient bed generation failed: {result.error}")

        except Exception as e:
            logger.error(f"[{self.project_id}] Ambient bed generation error: {e}")

        return None

    async def _generate_sfx(
        self,
        project_dir: Path,
        project_brief: dict
    ) -> Optional[dict]:
        """
        Generate SFX for each scene using ElevenLabs Sound Effects API.

        Reads audio_sfx from each scene and generates corresponding sound effects.
        Also generates sonic_hook if defined.

        Returns:
            Dictionary mapping sfx names to file paths
        """
        sfx_dir = project_dir / "sfx"
        sfx_dir.mkdir(parents=True, exist_ok=True)

        sfx_paths = {}

        try:
            # Generate sonic hook (intro sound)
            sonic_hook = project_brief.get("audio", {}).get("sonic_hook", {})
            if sonic_hook and sonic_hook.get("description"):
                hook_path = sfx_dir / "sonic_hook.mp3"
                if not hook_path.exists():
                    logger.info(f"[{self.project_id}] Generating sonic hook: {sonic_hook['description'][:40]}...")
                    await self.audio_engine.generate_and_save_sfx(
                        text=sonic_hook["description"],
                        output_path=hook_path,
                        duration_seconds=2.0,  # Short impact sound
                        prompt_influence=0.5,
                    )
                sfx_paths["sonic_hook"] = hook_path

            # Generate SFX for each scene
            scenes = project_brief.get("scenes", [])
            for scene in scenes:
                scene_num = scene.get("scene_number", 0)

                # Get SFX description from scene
                sfx_desc = (
                    scene.get("audio_sfx") or
                    scene.get("audio_moment") or
                    ""
                )

                if not sfx_desc or sfx_desc.lower() in ["", "none", "n/a"]:
                    continue

                sfx_path = sfx_dir / f"scene_{scene_num}_sfx.mp3"

                if sfx_path.exists():
                    logger.info(f"[{self.project_id}] Scene {scene_num} SFX already exists")
                    sfx_paths[f"scene_{scene_num}"] = sfx_path
                    continue

                logger.info(f"[{self.project_id}] Generating SFX for scene {scene_num}: {sfx_desc[:40]}...")

                try:
                    await self.audio_engine.generate_and_save_sfx(
                        text=sfx_desc,
                        output_path=sfx_path,
                        duration_seconds=3.0,  # Short scene SFX
                        prompt_influence=0.4,
                    )
                    sfx_paths[f"scene_{scene_num}"] = sfx_path

                except Exception as e:
                    logger.warning(f"[{self.project_id}] Failed to generate SFX for scene {scene_num}: {e}")
                    continue

            logger.success(f"[{self.project_id}] Generated {len(sfx_paths)} SFX files")
            return sfx_paths

        except Exception as e:
            logger.error(f"[{self.project_id}] SFX generation error: {e}")
            return sfx_paths if sfx_paths else None


# ============================================================================
# EXPORT
# ============================================================================

__all__ = ["AudioStage"]
