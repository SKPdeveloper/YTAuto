"""
Post-Processing Stage v7.4

Final stage: manifest-based rendering with 5-layer audio.

v7.4 Features:
- ManifestRenderer for FFmpeg-based rendering
- 5-layer audio mixing (BED, MUSIC, SFX, FOLEY, VO)
- Hook insertion with variety styles
- Speed map application
- Effect processing
- Subtitle overlay
"""

import json
from pathlib import Path
from typing import Optional, List

from loguru import logger

from app.pipeline.base import BasePipelineStage, StageResult, StageStatus
from app.api.schemas import ProjectData, SceneData, SceneStatus, PipelineStage
from app.services.audio_engine import AudioEngine
from app.services.manifest_renderer import ManifestRenderer, RenderConfig
from app.services.music_generator import MusicGenerator
from app.core.paths import get_project_path, get_scene_path
from app.core.config import settings


class PostProcessStage(BasePipelineStage):
    """
    Stage 7: Post-Processing (v7.4)

    Manifest-based video rendering:
    1. Load manifest.json from GEN3b
    2. Process scenes with speed maps and effects
    3. Apply hook at beginning
    4. Add subtitles
    5. Mix 5-layer audio
    6. Optional: Topaz AI enhancement
    7. Generate thumbnail

    Output:
    - {project_dir}/final_video.mp4
    - {project_dir}/thumbnail.png
    """

    name = "post_processing"
    description = "Manifest rendering with 5-layer audio"

    def __init__(self, project: ProjectData, **kwargs):
        super().__init__(project, **kwargs)
        self.audio_engine = AudioEngine()
        self.renderer = ManifestRenderer()
        self.music_generator = MusicGenerator()

    async def can_run(self) -> bool:
        """Check if post-processing should run"""
        project_dir = Path(self.project.project_dir) if hasattr(self.project, 'project_dir') else get_project_path(self.project_id)

        # v7.4: Check for manifest.json from GEN3b
        manifest_path = project_dir / "manifest.json"
        has_manifest = manifest_path.exists()

        # Fallback: check if all scenes have videos
        has_videos = all(
            scene.video_path and Path(scene.video_path).exists()
            for scene in self.project.scenes
            if scene.scene_number <= 6
        )

        # Check if final video already exists
        final_path = project_dir / "final_video.mp4"
        already_rendered = final_path.exists()

        return (has_manifest or has_videos) and not already_rendered

    async def can_resume(self) -> bool:
        """Post-processing can be resumed"""
        return True

    async def execute(self) -> StageResult:
        """Execute post-processing pipeline (v7.4 manifest-based)"""

        await self.notify_progress(0, "Starting post-processing (v7.4)...")

        project_dir = Path(self.project.project_dir) if hasattr(self.project, 'project_dir') else get_project_path(self.project_id)

        try:
            # Check for manifest.json
            manifest_path = project_dir / "manifest.json"

            if manifest_path.exists():
                # v7.4: Manifest-based rendering
                return await self._execute_manifest_render(project_dir, manifest_path)
            else:
                # Fallback: Legacy assembly
                logger.warning(f"[{self.project_id}] No manifest found, using legacy assembly")
                return await self._execute_legacy_render(project_dir)

        except Exception as e:
            logger.error(f"[{self.project_id}] Post-processing failed: {e}")

            await self.notifier.push_error(
                title="Rendering Error",
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

    async def _execute_manifest_render(
        self,
        project_dir: Path,
        manifest_path: Path
    ) -> StageResult:
        """Execute v7.4 manifest-based rendering."""

        await self.notify_progress(10, "Loading manifest...")

        # Load manifest
        from app.services.gen_models import Gen3bManifest
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest_data = json.load(f)
        manifest = Gen3bManifest.model_validate(manifest_data)

        logger.info(f"[{self.project_id}] Loaded manifest: {manifest.total_duration}s, {len(manifest.scenes)} scenes")

        # Generate music (MUSIC layer) if not exists
        await self.notify_progress(15, "Generating background music...")
        await self._generate_music(project_dir, manifest.total_duration)

        # Generate ambient bed (BED layer) if not exists
        await self.notify_progress(20, "Generating ambient bed...")
        await self._generate_ambient_bed(project_dir, manifest.total_duration)

        await self.notify_progress(25, "Rendering video from manifest...")

        # PUSH: Start notification
        await self.notifier.push_info(
            title="Rendering Started",
            message=f"Rendering {manifest.total_duration:.1f}s video with {len(manifest.scenes)} scenes...",
            project_id=self.project_id
        )

        # Render video
        final_path = await self.renderer.render(
            manifest=manifest,
            project_dir=project_dir,
            output_filename="final_video.mp4"
        )

        await self.notify_progress(80, "Video rendered successfully")

        # Optional Topaz enhancement
        if settings.TOPAZ_ENABLED:
            await self.notify_progress(85, "Enhancing with Topaz AI...")
            enhanced_path = await self._enhance_with_topaz(final_path)
            if enhanced_path:
                final_path = enhanced_path

        # Generate thumbnail
        await self.notify_progress(95, "Generating thumbnail...")
        thumbnail_path = await self._generate_thumbnail(final_path)

        # Update project
        self.project.final_video_path = str(final_path)
        self.project.thumbnail_path = str(thumbnail_path) if thumbnail_path else None
        self.project.status = "completed"

        await self.notify_progress(100, "Post-processing complete!")

        # Notify clients
        await self.notifier.send_project_completed(
            project_id=self.project_id,
            video_path=final_path,
            thumbnail_path=thumbnail_path
        )

        # PUSH: Success notification
        await self.notifier.push_success(
            title="Video Complete!",
            message=f"Final video rendered: {self._get_video_duration(final_path):.1f}s",
            project_id=self.project_id
        )

        return StageResult(
            success=True,
            stage_name=self.name,
            message="Video rendered successfully (v7.4)",
            data={
                "final_video": str(final_path),
                "thumbnail": str(thumbnail_path) if thumbnail_path else None,
                "duration_seconds": self._get_video_duration(final_path),
                "hook_style": manifest.hook.style,
                "scenes_count": len(manifest.scenes),
            }
        )

    async def _execute_legacy_render(self, project_dir: Path) -> StageResult:
        """Execute legacy rendering (fallback when no manifest)."""

        await self.notify_progress(10, "Generating voiceover...")
        audio_paths = await self._generate_voiceover()

        await self.notify_progress(40, "Assembling video (legacy mode)...")

        # Collect video paths
        video_paths = []
        for scene in self.project.scenes:
            if scene.video_path and Path(scene.video_path).exists():
                video_paths.append(Path(scene.video_path))

        if not video_paths:
            return StageResult(
                success=False,
                stage_name=self.name,
                status=StageStatus.FAILED,
                message="No videos to assemble"
            )

        # Simple concatenation
        output_path = project_dir / "final_video.mp4"

        # Create concat file
        concat_file = project_dir / "concat_list.txt"
        with open(concat_file, "w") as f:
            for path in video_paths:
                f.write(f"file '{path}'\n")

        import subprocess
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "18",
            str(output_path)
        ]

        process = subprocess.run(cmd, capture_output=True, text=True)
        if process.returncode != 0:
            return StageResult(
                success=False,
                stage_name=self.name,
                status=StageStatus.FAILED,
                message=f"FFmpeg failed: {process.stderr[:200]}"
            )

        final_path = output_path

        # Optional Topaz
        if settings.TOPAZ_ENABLED:
            await self.notify_progress(70, "Enhancing with Topaz AI...")
            enhanced_path = await self._enhance_with_topaz(output_path)
            if enhanced_path:
                final_path = enhanced_path

        # Thumbnail
        await self.notify_progress(90, "Generating thumbnail...")
        thumbnail_path = await self._generate_thumbnail(final_path)

        # Update project
        self.project.final_video_path = str(final_path)
        self.project.thumbnail_path = str(thumbnail_path) if thumbnail_path else None
        self.project.status = "completed"

        await self.notify_progress(100, "Post-processing complete!")

        await self.notifier.send_project_completed(
            project_id=self.project_id,
            video_path=final_path,
            thumbnail_path=thumbnail_path
        )

        return StageResult(
            success=True,
            stage_name=self.name,
            message="Video assembled (legacy mode)",
            data={
                "final_video": str(final_path),
                "thumbnail": str(thumbnail_path) if thumbnail_path else None,
                "duration_seconds": self._get_video_duration(final_path)
            }
        )

    async def _generate_voiceover(self) -> List[Path]:
        """Generate voiceover audio for each scene (legacy support)"""
        audio_paths = []

        for scene in self.project.scenes:
            if not scene.audio_prompt:
                logger.warning(f"[Scene {scene.scene_number}] No voiceover text")
                continue

            scene_dir = get_scene_path(self.project_id, scene.scene_number)
            audio_path = scene_dir / "voiceover.mp3"

            if audio_path.exists():
                logger.info(f"[Scene {scene.scene_number}] Voiceover already exists")
                audio_paths.append(audio_path)
                continue

            try:
                # Use generate_and_save_voiceover from AudioEngine
                generated_path = await self.audio_engine.generate_and_save_voiceover(
                    text=scene.audio_prompt,
                    output_path=audio_path,
                )

                if generated_path:
                    audio_paths.append(generated_path)
                    logger.success(f"[Scene {scene.scene_number}] Voiceover generated")

            except Exception as e:
                logger.error(f"[Scene {scene.scene_number}] Voiceover failed: {e}")

        return audio_paths

    async def _generate_music(self, project_dir: Path, duration: float) -> Optional[Path]:
        """Generate background music for MUSIC layer using Replicate Stable Audio"""
        music_path = project_dir / "music.mp3"

        if music_path.exists():
            logger.info(f"[{self.project_id}] Background music already exists")
            return music_path

        try:
            # Determine atmosphere from project name or default to cinematic
            atmosphere = "cinematic"
            if hasattr(self.project, 'concept') and self.project.concept:
                concept_lower = self.project.concept.lower()
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

            if result.success:
                logger.success(f"[{self.project_id}] Background music generated: {atmosphere}")
                return result.file_path
            else:
                logger.warning(f"[{self.project_id}] Music generation failed: {result.error}")

        except Exception as e:
            logger.error(f"[{self.project_id}] Music generation error: {e}")

        return None

    async def _generate_ambient_bed(self, project_dir: Path, duration: float) -> Optional[Path]:
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

            if result.success:
                logger.success(f"[{self.project_id}] Ambient bed generated")
                return result.file_path
            else:
                logger.warning(f"[{self.project_id}] Ambient bed generation failed: {result.error}")

        except Exception as e:
            logger.error(f"[{self.project_id}] Ambient bed generation error: {e}")

        return None

    async def _enhance_with_topaz(self, video_path: Path) -> Optional[Path]:
        """Enhance video using Topaz Video AI"""
        try:
            # Import here to avoid dependency if Topaz not installed
            from app.services.topaz_enhancer import TopazEnhancer

            enhancer = TopazEnhancer()
            enhanced_path = video_path.parent / "final_video_enhanced.mp4"

            success = await enhancer.enhance(
                input_path=video_path,
                output_path=enhanced_path
            )

            if success:
                logger.success(f"[{self.project_id}] Topaz enhancement complete")
                return enhanced_path

        except ImportError:
            logger.warning("Topaz enhancer not available")
        except Exception as e:
            logger.error(f"[{self.project_id}] Topaz enhancement failed: {e}")

        return None

    async def _generate_thumbnail(self, video_path: Path) -> Optional[Path]:
        """Generate thumbnail from video using FFmpeg"""
        thumbnail_path = video_path.parent / "thumbnail.png"

        try:
            import subprocess

            # Extract frame at 1 second using FFmpeg
            cmd = [
                "ffmpeg", "-y",
                "-ss", "1.0",
                "-i", str(video_path),
                "-vframes", "1",
                "-q:v", "2",
                str(thumbnail_path)
            ]

            process = subprocess.run(cmd, capture_output=True, text=True)

            if process.returncode == 0 and thumbnail_path.exists():
                logger.success(f"[{self.project_id}] Thumbnail generated")
                return thumbnail_path
            else:
                logger.warning(f"[{self.project_id}] Thumbnail extraction failed: {process.stderr[:200]}")

        except Exception as e:
            logger.error(f"[{self.project_id}] Thumbnail generation failed: {e}")

        return None

    def _get_video_duration(self, video_path: Path) -> Optional[float]:
        """Get video duration in seconds"""
        try:
            import subprocess
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(video_path)
                ],
                capture_output=True,
                text=True
            )
            return float(result.stdout.strip())
        except Exception:
            return None
