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

        # Check if all videos exist (audio comes after video generation)
        has_videos = all(
            scene.video_path and Path(scene.video_path).exists()
            for scene in self.project.scenes
            if scene.scene_number <= 6
        )

        # Check if audio files already exist
        voiceover_exists = (project_dir / "voiceover.mp3").exists()
        music_exists = (project_dir / "music.mp3").exists()

        # Run if we have videos but missing audio
        return has_videos and (not voiceover_exists or not music_exists)

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

            # Calculate estimated video duration (6 scenes * 10s = 60s)
            estimated_duration = 60.0

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
            await self.notify_progress(70, "Generating ambient bed...")
            ambient_path = await self._generate_ambient_bed(project_dir, estimated_duration)

            await self.notify_progress(100, "Audio generation complete!")

            # Build result data
            result_data = {
                "voiceover": str(voiceover_path) if voiceover_path else None,
                "music": str(music_path) if music_path else None,
                "ambient": str(ambient_path) if ambient_path else None,
            }

            # PUSH: Success notification
            await self.notifier.push_success(
                title="Audio Ready",
                message=f"Generated voiceover, music, and ambient tracks",
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
        """Generate combined voiceover from all scene audio_prompts"""

        voiceover_path = project_dir / "voiceover.mp3"

        if voiceover_path.exists():
            logger.info(f"[{self.project_id}] Voiceover already exists")
            return voiceover_path

        # Collect all scene voiceover texts
        scenes = project_brief.get("scenes", [])
        voiceover_texts = []

        for scene in scenes:
            audio_prompt = scene.get("audio_prompt") or scene.get("voiceover_text", "")
            if audio_prompt:
                voiceover_texts.append(audio_prompt)

        if not voiceover_texts:
            logger.warning(f"[{self.project_id}] No voiceover text found in project brief")
            return None

        # Combine all texts with brief pauses
        combined_text = " ... ".join(voiceover_texts)

        try:
            generated_path = await self.audio_engine.generate_and_save_voiceover(
                text=combined_text,
                output_path=voiceover_path,
            )

            if generated_path and generated_path.exists():
                logger.success(f"[{self.project_id}] Voiceover generated: {generated_path}")
                return generated_path

        except Exception as e:
            logger.error(f"[{self.project_id}] Voiceover generation failed: {e}")

        return None

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


# ============================================================================
# EXPORT
# ============================================================================

__all__ = ["AudioStage"]
