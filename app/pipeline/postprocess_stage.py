"""
Post-Processing Stage v7.5

Final stage: manifest-based rendering with 5-layer audio.

v7.5 Changes:
- Audio generation moved to AudioStage (runs before GEN3a)
- This stage only handles FFmpeg rendering, Topaz, thumbnail

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
from app.services.manifest_renderer import ManifestRenderer, RenderConfig
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
        self.renderer = ManifestRenderer()

    async def can_run(self) -> bool:
        """Check if post-processing should run"""
        project_dir = Path(self.project.project_dir) if hasattr(self.project, 'project_dir') else get_project_path(self.project_id)

        # v7.4: Check for manifest.json from GEN3b
        manifest_path = project_dir / "gen3b_manifest.json"
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
            manifest_path = project_dir / "gen3b_manifest.json"

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

        # Audio is now generated in AudioStage (before GEN3a)
        # Check if audio files exist
        music_path = project_dir / "music.mp3"
        voiceover_path = project_dir / "voiceover.mp3"

        if not music_path.exists():
            logger.warning(f"[{self.project_id}] music.mp3 not found - AudioStage may have failed")
        if not voiceover_path.exists():
            logger.warning(f"[{self.project_id}] voiceover.mp3 not found - AudioStage may have failed")

        await self.notify_progress(20, "Rendering video from manifest...")

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
            title=self.project.title or "Video Complete",
            final_video_path=final_path
        )

        # PUSH: Success notification
        duration = await self._get_video_duration(final_path)
        await self.notifier.push_success(
            title="Video Complete!",
            message=f"Final video rendered: {duration:.1f}s" if duration else "Final video rendered",
            project_id=self.project_id
        )

        # Generate _publish.bat for post-upload cleanup
        try:
            from scripts.publish_archive import generate_bat_file
            generate_bat_file(project_dir)
            logger.info(f"[{self.project_id}] Generated _publish.bat")
        except Exception as e:
            logger.warning(f"[{self.project_id}] Failed to generate _publish.bat: {e}")

        return StageResult(
            success=True,
            stage_name=self.name,
            message="Video rendered successfully (v7.4)",
            data={
                "final_video": str(final_path),
                "thumbnail": str(thumbnail_path) if thumbnail_path else None,
                "duration_seconds": duration,
                "hook_style": manifest.hook.style,
                "scenes_count": len(manifest.scenes),
            }
        )

    async def _execute_legacy_render(self, project_dir: Path) -> StageResult:
        """Execute legacy rendering (fallback when no manifest)."""

        await self.notify_progress(10, "Assembling video (legacy mode)...")

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
        with open(concat_file, "w", encoding="utf-8") as f:
            for path in video_paths:
                safe_path = str(path).replace("\\", "/")
                f.write(f"file '{safe_path}'\n")

        import asyncio
        if hasattr(settings, 'FFMPEG_PATH') and settings.FFMPEG_PATH and settings.FFMPEG_PATH.exists():
            ffmpeg_path = str(settings.FFMPEG_PATH)
        elif settings.TOPAZ_FFMPEG_PATH and settings.TOPAZ_FFMPEG_PATH.exists():
            ffmpeg_path = str(settings.TOPAZ_FFMPEG_PATH)
        else:
            ffmpeg_path = "ffmpeg"
        cmd = [
            ffmpeg_path, "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            str(output_path)
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return StageResult(
                success=False,
                stage_name=self.name,
                status=StageStatus.FAILED,
                message="FFmpeg legacy render timed out after 300s"
            )

        if process.returncode != 0:
            return StageResult(
                success=False,
                stage_name=self.name,
                status=StageStatus.FAILED,
                message=f"FFmpeg failed: {stderr.decode('utf-8', errors='ignore')[:200]}"
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
            title=self.project.title or "Video Complete",
            final_video_path=final_path
        )

        # Generate _publish.bat for post-upload cleanup
        try:
            from scripts.publish_archive import generate_bat_file
            generate_bat_file(project_dir)
            logger.info(f"[{self.project_id}] Generated _publish.bat")
        except Exception as e:
            logger.warning(f"[{self.project_id}] Failed to generate _publish.bat: {e}")

        return StageResult(
            success=True,
            stage_name=self.name,
            message="Video assembled (legacy mode)",
            data={
                "final_video": str(final_path),
                "thumbnail": str(thumbnail_path) if thumbnail_path else None,
                "duration_seconds": await self._get_video_duration(final_path)
            }
        )

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
            import asyncio

            # Extract frame at 1 second using FFmpeg
            cmd = [
                "ffmpeg", "-y",
                "-ss", "1.0",
                "-i", str(video_path),
                "-vframes", "1",
                "-q:v", "2",
                str(thumbnail_path)
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                logger.warning(f"[{self.project_id}] Thumbnail extraction timed out")
                return None

            if process.returncode == 0 and thumbnail_path.exists():
                logger.success(f"[{self.project_id}] Thumbnail generated")
                return thumbnail_path
            else:
                logger.warning(f"[{self.project_id}] Thumbnail extraction failed: {stderr.decode('utf-8', errors='ignore')[:200]}")

        except Exception as e:
            logger.error(f"[{self.project_id}] Thumbnail generation failed: {e}")

        return None

    async def _get_video_duration(self, video_path: Path) -> Optional[float]:
        """Get video duration in seconds"""
        try:
            import asyncio
            process = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
            return float(stdout.decode().strip())
        except Exception:
            return None
