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

        # Check if SFX exist (at least sonic_hook or scene SFX)
        sfx_dir = project_dir / "sfx"
        sfx_exists = sfx_dir.exists() and any(sfx_dir.glob("*.mp3"))

        # Run if we have videos but missing any audio asset
        return has_videos and (not voiceover_exists or not music_exists or not sfx_exists)

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
        Generate combined voiceover from all scene audio_prompts.

        Generates each segment separately to track timing, then concatenates.
        Saves timing metadata to voiceover_timing.json for subtitle sync.
        """
        import subprocess
        import json

        voiceover_path = project_dir / "voiceover.mp3"
        timing_path = project_dir / "voiceover_timing.json"

        if voiceover_path.exists() and timing_path.exists():
            logger.info(f"[{self.project_id}] Voiceover already exists with timing")
            return voiceover_path

        # Collect all scene voiceover texts with scene numbers
        scenes = project_brief.get("scenes", [])
        voiceover_segments = []

        for i, scene in enumerate(scenes):
            scene_num = scene.get("scene_number", i + 1)
            audio_prompt = (
                scene.get("voiceover_segment") or
                scene.get("voiceover") or
                scene.get("audio_prompt") or
                scene.get("voiceover_text", "")
            )
            # Skip empty or placeholder texts
            if audio_prompt and audio_prompt.lower().strip() not in ["tagline", "(can be empty)", ""]:
                voiceover_segments.append({
                    "scene_number": scene_num,
                    "text": audio_prompt,
                })

        if not voiceover_segments:
            logger.warning(f"[{self.project_id}] No voiceover text found in project brief")
            return None

        # Generate each segment separately and track timing
        segment_files = []
        timing_data = {
            "segments": [],
            "total_duration": 0.0,
        }
        current_time = 0.0
        gap_duration = 0.3  # 300ms gap between segments

        try:
            for seg in voiceover_segments:
                scene_num = seg["scene_number"]
                text = seg["text"]

                # Generate individual segment
                segment_path = project_dir / f"vo_segment_{scene_num}.mp3"

                if not segment_path.exists():
                    generated = await self.audio_engine.generate_and_save_voiceover(
                        text=text,
                        output_path=segment_path,
                    )
                    if not generated or not generated.exists():
                        logger.warning(f"[{self.project_id}] Failed to generate VO segment {scene_num}")
                        continue

                # Get segment duration using ffprobe
                result = subprocess.run([
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(segment_path)
                ], capture_output=True, text=True)

                if result.returncode == 0:
                    duration = float(result.stdout.strip())
                else:
                    duration = 2.0  # Fallback

                segment_files.append(segment_path)

                # Record timing
                timing_data["segments"].append({
                    "scene_number": scene_num,
                    "text": text,
                    "start_time": round(current_time, 3),
                    "end_time": round(current_time + duration, 3),
                    "duration": round(duration, 3),
                    "file": segment_path.name,
                })

                logger.info(f"[{self.project_id}] VO segment {scene_num}: {duration:.2f}s @ {current_time:.2f}s")
                current_time += duration + gap_duration

            timing_data["total_duration"] = round(current_time - gap_duration, 3)

            # Concatenate all segments using FFmpeg
            if segment_files:
                # Create concat list file
                concat_list_path = project_dir / "vo_concat_list.txt"
                with open(concat_list_path, "w") as f:
                    for seg_file in segment_files:
                        f.write(f"file '{seg_file.name}'\n")

                # Concatenate with FFmpeg
                concat_cmd = [
                    "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(concat_list_path),
                    "-c", "copy", str(voiceover_path)
                ]
                subprocess.run(concat_cmd, capture_output=True)

                # Save timing metadata
                with open(timing_path, "w", encoding="utf-8") as f:
                    json.dump(timing_data, f, indent=2, ensure_ascii=False)

                logger.success(f"[{self.project_id}] Voiceover generated: {voiceover_path}")
                logger.info(f"[{self.project_id}] Timing saved: {timing_path}")

                # Cleanup concat list
                concat_list_path.unlink(missing_ok=True)

                return voiceover_path

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
