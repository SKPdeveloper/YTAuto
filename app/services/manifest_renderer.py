"""
ManifestRenderer - FFmpeg Video Renderer v1.0

Takes Gen3bManifest and renders the final video using FFmpeg.

Features:
- Video concatenation with speed changes
- Effects application (zoom, shake, glow, etc.)
- Hook insertion (0.3s visual impact)
- Subtitle overlay with animations
- 5-layer audio mixing
- Loop engineering compliance
- 9:16 vertical format output

Workflow:
1. Parse Gen3bManifest
2. Process each scene with speed segments and effects
3. Apply hook at the beginning
4. Overlay subtitles
5. Mix 5-layer audio
6. Export final video

Output: final_video.mp4 (9:16, 25s, 60fps)
"""

import json
import subprocess
import asyncio
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

from app.utils.logger import logger
from app.core.config import settings
from app.services.gen_models import (
    Gen3bManifest,
    ManifestScene,
    ManifestEffect,
    ManifestSubtitle,
    SpeedSegment,
)
from app.services.audio_engine import (
    AudioMixer,
    AudioMixConfig,
    AudioLayer,
)


@dataclass
class RenderConfig:
    """Configuration for video rendering."""
    output_width: int = 1080
    output_height: int = 1920  # 9:16 vertical
    fps: int = 60
    # Topaz FFmpeg не має libx264, використовуємо NVIDIA NVENC (GPU)
    # Fallback: h264_mf (MediaFoundation) якщо немає NVIDIA
    video_codec: str = "h264_nvenc"
    audio_codec: str = "aac"
    video_bitrate: str = "8M"
    audio_bitrate: str = "192k"
    preset: str = "p4"  # NVENC presets: p1-p7 (p4=medium)
    crf: int = 23  # NVENC CQ mode (18-28 recommended)


class ManifestRenderer:
    """
    FFmpeg Video Renderer for Glaze City Pipeline

    Takes Gen3bManifest and renders the final video with:
    - Scene concatenation with speed changes
    - Effect application
    - Hook at the beginning
    - Subtitle overlays
    - 5-layer audio mixing

    Output: 9:16 vertical, 25s, 60fps
    """

    def __init__(self, config: Optional[RenderConfig] = None):
        """Initialize ManifestRenderer with optional config."""
        self.config = config or RenderConfig()
        self.audio_mixer = AudioMixer()
        # Використовуємо повний FFmpeg (має ass/subtitles фільтри та libx264)
        # Topaz FFmpeg не має цих фільтрів!
        if hasattr(settings, 'FFMPEG_PATH') and settings.FFMPEG_PATH and settings.FFMPEG_PATH.exists():
            self.ffmpeg_path = str(settings.FFMPEG_PATH)
        elif settings.TOPAZ_FFMPEG_PATH and settings.TOPAZ_FFMPEG_PATH.exists():
            self.ffmpeg_path = str(settings.TOPAZ_FFMPEG_PATH)
        else:
            self.ffmpeg_path = "ffmpeg"

        logger.info("ManifestRenderer initialized:")
        logger.info(f"  FFmpeg: {self.ffmpeg_path}")
        logger.info(f"  Output: {self.config.output_width}x{self.config.output_height}")
        logger.info(f"  FPS: {self.config.fps}")
        logger.info(f"  Codec: {self.config.video_codec}")

    def _get_encoder_params(self) -> List[str]:
        """Повертає параметри кодека в залежності від типу.

        NVENC (h264_nvenc): використовує -preset p1-p7, -cq або -b:v
        libx264: використовує -preset, -crf
        h264_mf: використовує тільки -b:v
        """
        codec = self.config.video_codec

        if "nvenc" in codec:
            # NVIDIA NVENC: preset p1-p7, constant quality mode
            return ["-preset", "p4", "-rc", "constqp", "-qp", "23"]
        elif "qsv" in codec:
            # Intel Quick Sync
            return ["-preset", "medium", "-global_quality", "23"]
        elif "mf" in codec:
            # MediaFoundation: тільки bitrate
            return ["-b:v", self.config.video_bitrate]
        elif "amf" in codec:
            # AMD AMF
            return ["-quality", "balanced", "-rc", "cqp", "-qp_i", "23", "-qp_p", "23"]
        else:
            # libx264 та інші software encoders
            return ["-preset", self.config.preset, "-crf", str(self.config.crf)]

    async def render(
        self,
        manifest: Gen3bManifest,
        project_dir: Path,
        output_filename: str = "final_video.mp4",
    ) -> Path:
        """
        Render final video from manifest.

        Args:
            manifest: Gen3bManifest with all rendering instructions
            project_dir: Project directory containing source files
            output_filename: Output video filename

        Returns:
            Path to rendered video

        Raises:
            Exception: If rendering fails
        """
        logger.info("=" * 60)
        logger.info("ManifestRenderer: Starting Render")
        logger.info("=" * 60)
        logger.info(f"  Total duration: {manifest.total_duration}s")
        logger.info(f"  Scenes: {len(manifest.scenes)}")
        logger.info(f"  Subtitles: {len(manifest.subtitles)}")
        logger.info(f"  Hook style: {manifest.hook.style}")

        output_path = project_dir / output_filename

        try:
            # Step 1: Process scenes with speed changes
            processed_scenes = await self._process_scenes(manifest.scenes, project_dir)

            # Step 2: Create hook video
            hook_path = await self._create_hook(manifest, project_dir, processed_scenes)

            # Step 3: Concatenate all clips
            concat_path = await self._concatenate_clips(
                hook_path, processed_scenes, project_dir
            )

            # Step 4: Apply global effects
            effects_path = await self._apply_global_effects(
                concat_path, manifest.global_effects, project_dir
            )

            # Step 5: Add subtitles
            subtitled_path = await self._add_subtitles(
                effects_path, manifest.subtitles, project_dir
            )

            # Step 6: Mix 5-layer audio
            final_path = await self._mix_audio(
                subtitled_path, manifest, project_dir, output_path
            )

            logger.success("=" * 60)
            logger.success("ManifestRenderer: Render Complete")
            logger.success(f"  Output: {final_path}")
            logger.success("=" * 60)

            return final_path

        except Exception as e:
            logger.error(f"Render failed: {e}")
            raise

    def _resolve_source_path(self, project_dir: Path, source_file: str) -> Path:
        """
        Resolve source file path, handling both relative and absolute paths.

        Fixes path duplication when LLM returns full paths like
        'projects/proj_.../scene_1/video.mp4' instead of relative 'scene_1/video.mp4'.
        Also checks gen3a_work/ folder for preprocessed scene files.
        """
        source_path = Path(source_file)

        # If it's an absolute path and exists, use it directly
        if source_path.is_absolute() and source_path.exists():
            return source_path

        # Check if source_file contains the project directory name (duplication case)
        project_name = project_dir.name
        if project_name in source_file:
            # Try to extract just the relative part after project name
            # e.g., "projects/proj_xxx/scene_1/video.mp4" -> "scene_1/video.mp4"
            parts = source_file.replace("\\", "/").split(project_name)
            if len(parts) > 1:
                relative_part = parts[-1].lstrip("/")
                resolved = project_dir / relative_part
                if resolved.exists():
                    return resolved

        # Standard case: join with project_dir
        direct_path = project_dir / source_file
        if direct_path.exists():
            return direct_path

        # Fallback: check gen3a_work/ folder (preprocessed scene files)
        gen3a_path = project_dir / "gen3a_work" / source_file
        if gen3a_path.exists():
            return gen3a_path

        # Fallback: check scene_N/video.mp4 pattern
        # If source_file is like "1.mp4", try "scene_1/video.mp4"
        if source_file.endswith(".mp4"):
            scene_num = source_file.replace(".mp4", "")
            if scene_num.isdigit():
                scene_path = project_dir / f"scene_{scene_num}" / "video.mp4"
                if scene_path.exists():
                    return scene_path

        # Return the direct path (may not exist, caller will handle)
        return direct_path

    async def _process_scenes(
        self,
        scenes: List[ManifestScene],
        project_dir: Path,
    ) -> List[Path]:
        """
        Process each scene with speed changes and effects.

        Returns:
            List of paths to processed scene videos
        """
        processed = []

        for scene in scenes:
            source_path = self._resolve_source_path(project_dir, scene.source_file)

            if not source_path.exists():
                logger.warning(f"Scene {scene.scene_number} source not found: {source_path}")
                continue

            # Process speed segments
            output_path = project_dir / f"processed_scene_{scene.scene_number}.mp4"

            if scene.speed_segments:
                await self._apply_speed_map(source_path, scene.speed_segments, output_path)
            else:
                # Copy without speed changes
                output_path = source_path

            # Apply scene-specific effects
            if scene.effects:
                effects_output = project_dir / f"effects_scene_{scene.scene_number}.mp4"
                await self._apply_effects(output_path, scene.effects, effects_output)
                output_path = effects_output

            processed.append(output_path)
            logger.info(f"  Processed scene {scene.scene_number}")

        return processed

    async def _apply_speed_map(
        self,
        input_path: Path,
        speed_segments: List[SpeedSegment],
        output_path: Path,
    ) -> None:
        """
        Apply speed changes to video based on speed map.

        Обробляє кожен сегмент окремо:
        1. Trim до потрібного часового діапазону
        2. Застосувати швидкість (setpts)
        3. Concat всі сегменти
        """
        if not speed_segments:
            # Просто копіюємо якщо немає сегментів
            import shutil
            shutil.copy(input_path, output_path)
            return

        # Якщо один сегмент - простіша обробка
        if len(speed_segments) == 1:
            seg = speed_segments[0]
            pts_factor = 1 / seg.speed
            cmd = [
                self.ffmpeg_path, "-y",
                "-i", str(input_path),
                "-ss", str(seg.source_start),
                "-t", str(seg.source_end - seg.source_start),
                "-filter:v", f"setpts={pts_factor}*PTS",
                "-an",
                "-c:v", self.config.video_codec,
                *self._get_encoder_params(),
                str(output_path)
            ]
            await self._run_ffmpeg(cmd)
            return

        # Багато сегментів - складний filter_complex
        # Формат: trim+setpts для кожного сегмента, потім concat
        temp_dir = output_path.parent / "temp_segments"
        temp_dir.mkdir(exist_ok=True)

        segment_files = []
        for i, seg in enumerate(speed_segments):
            seg_output = temp_dir / f"seg_{i}.mp4"
            pts_factor = 1 / seg.speed

            cmd = [
                self.ffmpeg_path, "-y",
                "-i", str(input_path),
                "-ss", str(seg.source_start),
                "-t", str(seg.source_end - seg.source_start),
                "-filter:v", f"setpts={pts_factor}*PTS",
                "-an",
                "-c:v", self.config.video_codec,
                *self._get_encoder_params(),
                str(seg_output)
            ]
            await self._run_ffmpeg(cmd)

            if seg_output.exists():
                segment_files.append(seg_output)

        # Concat всі сегменти
        if segment_files:
            concat_file = temp_dir / "concat.txt"
            with open(concat_file, 'w') as f:
                for seg_file in segment_files:
                    f.write(f"file '{str(seg_file).replace(chr(92), '/')}'\n")

            cmd = [
                self.ffmpeg_path, "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file),
                "-c", "copy",
                str(output_path)
            ]
            await self._run_ffmpeg(cmd)

            # Cleanup temp files
            for seg_file in segment_files:
                seg_file.unlink(missing_ok=True)
            concat_file.unlink(missing_ok=True)
            try:
                temp_dir.rmdir()
            except:
                pass

        logger.info(f"  Applied {len(speed_segments)} speed segments")

    async def _apply_effects(
        self,
        input_path: Path,
        effects: List[ManifestEffect],
        output_path: Path,
    ) -> None:
        """Apply visual effects to video."""
        filters = []

        for effect in effects:
            effect_filter = self._get_effect_filter(effect)
            if effect_filter:
                filters.append(effect_filter)

        if not filters:
            # No effects, just copy
            import shutil
            shutil.copy(input_path, output_path)
            return

        filter_chain = ",".join(filters)

        cmd = [
            self.ffmpeg_path, "-y",
            "-i", str(input_path),
            "-vf", filter_chain,
            "-c:v", self.config.video_codec,
            *self._get_encoder_params(),
            "-c:a", "copy",
            str(output_path)
        ]

        await self._run_ffmpeg(cmd)

    def _get_effect_filter(self, effect: ManifestEffect) -> Optional[str]:
        """Convert ManifestEffect to FFmpeg filter string."""
        effect_type = effect.type.upper()
        params = effect.params or {}

        # Handle None values for timing (global effects may not have timing)
        start = effect.output_start if effect.output_start is not None else 0.0
        end = effect.output_end if effect.output_end is not None else 1.0
        duration = end - start

        # Map effect types to FFmpeg filters
        # Note: zoompan requires explicit size (s=WxH) and fps
        w, h = self.config.output_width, self.config.output_height
        fps = self.config.fps
        # FFmpeg фільтри для ефектів:
        # brightness -> eq=brightness=X або exposure=exposure=X
        # contrast -> eq=contrast=X
        # saturation -> eq=saturation=X або hue=s=X
        effect_map = {
            "ZOOM_IN": f"zoompan=z='min(zoom+0.0015,1.5)':d={int(duration * fps)}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={fps}",
            "ZOOM_OUT": f"zoompan=z='max(1.5-zoom*0.0015,1)':d={int(duration * fps)}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={fps}",
            "ZOOM_PUNCH": f"scale={w}:{h},eq=brightness=0.05:contrast=1.1",
            "CAMERA_SHAKE": f"crop=iw-20:ih-20:x='10+random(0)*10':y='10+random(0)*10',scale={w}:{h}",
            "SHAKE": f"crop=iw-20:ih-20:x='10+random(0)*10':y='10+random(0)*10',scale={w}:{h}",
            "GLOW": "eq=brightness=0.06:saturation=1.3",
            "FLASH": f"fade=t=in:st={start}:d=0.1,fade=t=out:st={start + 0.1}:d=0.1",
            "VIGNETTE": "vignette=PI/4",
            "RGB_SPLIT": "rgbashift=rh=-3:bh=3",
            "CHROMATIC_ABERRATION": "rgbashift=rh=-3:bh=3",
            "GLITCH": "noise=alls=20:allf=t+u",
            "LETTERBOX": "drawbox=x=0:y=0:w=iw:h=ih*0.1:c=black:t=fill,drawbox=x=0:y=ih*0.9:w=iw:h=ih*0.1:c=black:t=fill",
            "COLOR_BOOST": "eq=saturation=1.3:contrast=1.1",
            "WARM": "colorbalance=rs=0.1:gs=0.05:bs=-0.1",
            "COOL": "colorbalance=rs=-0.1:gs=0:bs=0.1",
        }

        return effect_map.get(effect_type)

    async def _create_hook(
        self,
        manifest: Gen3bManifest,
        project_dir: Path,
        processed_scenes: List[Path],
    ) -> Optional[Path]:
        """Create hook video from first scene."""
        if not processed_scenes:
            return None

        hook = manifest.hook
        hook_path = project_dir / "hook.mp4"

        # Extract first frames based on hook duration
        first_scene = processed_scenes[0]

        # Apply hook effects
        hook_filters = []

        # Add hook style effects
        style_effects = self._get_hook_style_filters(hook.style)
        hook_filters.extend(style_effects)

        # Add any specified effects
        for effect in hook.effects:
            ef = self._get_effect_filter(effect)
            if ef:
                hook_filters.append(ef)

        filter_chain = ",".join(hook_filters) if hook_filters else "null"

        cmd = [
            self.ffmpeg_path, "-y",
            "-i", str(first_scene),
            "-t", str(hook.duration),
            "-vf", filter_chain,
            "-c:v", self.config.video_codec,
            *self._get_encoder_params(),
            "-an",
            str(hook_path)
        ]

        await self._run_ffmpeg(cmd)
        logger.info(f"  Created hook ({hook.style}, {hook.duration}s)")

        return hook_path

    def _get_hook_style_filters(self, style: str) -> List[str]:
        """Get FFmpeg filters for hook style."""
        style = style.upper()

        # FFmpeg фільтри для стилів хука:
        # eq=brightness=X:contrast=X:saturation=X
        style_filters = {
            "CLASSIC": [
                "eq=brightness=0.1:saturation=1.2",
            ],
            "IMPACT": [
                "eq=brightness=0.15:contrast=1.3",
                "unsharp=5:5:1.5:5:5:0.0",
            ],
            "GLITCH": [
                "noise=alls=30:allf=t",
                "rgbashift=rh=-5:bh=5",
            ],
            "ELEGANT": [
                "curves=preset=lighter",
                "vignette=PI/5",
            ],
            "DRAMATIC": [
                "eq=contrast=1.4:brightness=-0.05",
                "vignette=PI/3",
            ],
        }

        return style_filters.get(style, [])

    async def _concatenate_clips(
        self,
        hook_path: Optional[Path],
        scene_paths: List[Path],
        project_dir: Path,
    ) -> Path:
        """Concatenate hook and all scenes using filter_complex."""
        output_path = project_dir / "concatenated.mp4"

        # Збираємо всі файли для конкатенації
        input_files = []
        if hook_path and hook_path.exists():
            input_files.append(hook_path)
        for path in scene_paths:
            if path.exists():
                input_files.append(path)

        if not input_files:
            raise Exception("No input files for concatenation")

        # Зберігаємо список для інформації
        concat_file = project_dir / "concat_list.txt"
        with open(concat_file, "w") as f:
            for path in input_files:
                f.write(f"file '{path}'\n")

        w, h = self.config.output_width, self.config.output_height
        fps = self.config.fps

        # Будуємо команду з filter_complex для нормалізації розмірів
        cmd = [self.ffmpeg_path, "-y"]

        # Додаємо всі вхідні файли
        for path in input_files:
            cmd.extend(["-i", str(path)])

        # Будуємо filter_complex: scale кожен вхід до однакового розміру, потім concat
        n = len(input_files)
        filter_parts = []
        concat_inputs = []

        for i in range(n):
            # Нормалізуємо кожен вхід
            filter_parts.append(f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=disable,fps={fps},format=yuv420p,setsar=1[v{i}]")
            concat_inputs.append(f"[v{i}]")

        # Конкатенуємо всі нормалізовані потоки
        filter_parts.append(f"{''.join(concat_inputs)}concat=n={n}:v=1:a=0[outv]")

        filter_complex = ";".join(filter_parts)

        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-c:v", self.config.video_codec,
            *self._get_encoder_params(),
            str(output_path)
        ])

        await self._run_ffmpeg(cmd)
        logger.info("  Concatenated all clips")

        return output_path

    async def _apply_global_effects(
        self,
        input_path: Path,
        effects: List[ManifestEffect],
        project_dir: Path,
    ) -> Path:
        """Apply global effects to concatenated video."""
        if not effects:
            return input_path

        output_path = project_dir / "global_effects.mp4"
        await self._apply_effects(input_path, effects, output_path)
        logger.info(f"  Applied {len(effects)} global effects")

        return output_path

    async def _add_subtitles(
        self,
        input_path: Path,
        subtitles: List[ManifestSubtitle],
        project_dir: Path,
    ) -> Path:
        """Add subtitles to video."""
        if not subtitles:
            return input_path

        output_path = project_dir / "subtitled.mp4"

        # Create ASS subtitle file
        ass_path = project_dir / "subtitles.ass"
        self._create_ass_file(subtitles, ass_path)

        # FFmpeg filter requires escaped path on Windows
        # Replace backslashes with forward slashes and escape colons
        ass_path_escaped = str(ass_path).replace("\\", "/").replace(":", "\\:")

        cmd = [
            self.ffmpeg_path, "-y",
            "-i", str(input_path),
            "-vf", f"ass='{ass_path_escaped}'",
            "-c:v", self.config.video_codec,
            *self._get_encoder_params(),
            "-c:a", "copy",
            str(output_path)
        ]

        await self._run_ffmpeg(cmd)
        logger.info(f"  Added {len(subtitles)} subtitles")

        return output_path

    def _create_ass_file(
        self,
        subtitles: List[ManifestSubtitle],
        output_path: Path,
    ) -> None:
        """Create ASS subtitle file from manifest subtitles."""
        # ASS header for 9:16 vertical video
        # Alignment: 2 = bottom center, positioned higher with MarginV=400 to avoid safe zone
        # Font size 70 for good readability on mobile
        header = """[Script Info]
Title: Glaze City Subtitles
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,70,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,4,2,2,50,50,400,1
Style: NORMAL,Arial,70,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,4,2,2,50,50,400,1
Style: EXCITED,Arial,70,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,4,2,2,50,50,400,1
Style: DRAMATIC,Arial,70,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,4,2,2,50,50,400,1
Style: WHISPER,Arial,70,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,4,2,2,50,50,400,1
Style: Impact,Arial,70,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,4,2,2,50,50,400,1
Style: Elegant,Arial,70,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,4,2,2,50,50,400,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

        lines = [header]

        for sub in subtitles:
            start = self._seconds_to_ass_time(sub.output_start)
            end = self._seconds_to_ass_time(sub.output_end)
            # Map style names (Gemini uses NORMAL, WHISPER, EXCITED, DRAMATIC, etc.)
            style_map = {
                "NORMAL": "NORMAL",
                "WHISPER": "WHISPER",
                "EXCITED": "EXCITED",
                "DRAMATIC": "DRAMATIC",
                "IMPACT": "Impact",
                "ELEGANT": "Elegant",
            }
            style = style_map.get(sub.style.upper(), "Default")
            text = sub.text.replace("\n", "\\N")

            # Apply animation effects - handle various Gemini animation names
            anim = sub.animation.upper() if sub.animation else ""
            effects = ""
            if "FADE" in anim:
                effects = "{\\fad(200,200)}"
            elif anim == "BOUNCE" or anim == "POP":
                effects = "{\\t(0,100,\\fscx110\\fscy110)\\t(100,200,\\fscx100\\fscy100)}"
            elif anim == "SLIDE":
                effects = "{\\move(540,1520,540,1420,0,200)}"

            lines.append(f"Dialogue: 0,{start},{end},{style},,0,0,0,,{effects}{text}")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def _seconds_to_ass_time(self, seconds: float) -> str:
        """Convert seconds to ASS time format (H:MM:SS.cc)."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        centisecs = int((seconds % 1) * 100)
        return f"{hours}:{minutes:02d}:{secs:02d}.{centisecs:02d}"

    async def _mix_audio(
        self,
        video_path: Path,
        manifest: Gen3bManifest,
        project_dir: Path,
        output_path: Path,
    ) -> Path:
        """Mix 5-layer audio and combine with video."""
        # Get actual video duration (may differ from manifest due to speed processing)
        import subprocess
        # Використовуємо ffprobe з тієї ж директорії що і ffmpeg
        ffprobe_path = Path(self.ffmpeg_path).parent / "ffprobe.exe"
        if not ffprobe_path.exists():
            ffprobe_path = "ffprobe"  # Fallback до системного
        result = subprocess.run([
            str(ffprobe_path), "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path)
        ], capture_output=True, text=True)
        actual_duration = float(result.stdout.strip()) if result.returncode == 0 else manifest.total_duration
        logger.info(f"  Video duration: {actual_duration:.2f}s (manifest: {manifest.total_duration}s)")

        # Create audio mix configuration with actual video duration
        audio_config = self.audio_mixer.create_default_config(
            total_duration=actual_duration,
            vo_path=project_dir / "voiceover.mp3",
            music_path=project_dir / "music.mp3",
            bed_path=project_dir / "ambient.mp3" if (project_dir / "ambient.mp3").exists() else None,
        )

        # Add SFX events from manifest
        audio_layers = manifest.audio_layers
        for sfx in audio_layers.sfx_events:
            sfx_path = project_dir / "sfx" / sfx.file
            if sfx_path.exists():
                self.audio_mixer.add_sfx_event(
                    audio_config,
                    sfx.timestamp,
                    sfx_path,
                    sfx.volume,
                    sfx.reason,
                )

        # AUTO-SFX: If no SFX from manifest, auto-discover SFX files
        if not audio_layers.sfx_events:
            await self._auto_add_sfx(audio_config, manifest, project_dir)

        # Add FOLEY events
        for foley in audio_layers.foley_events:
            foley_path = project_dir / "foley" / foley.file
            if foley_path.exists():
                self.audio_mixer.add_foley_event(
                    audio_config,
                    foley.timestamp,
                    foley_path,
                    foley.volume,
                    foley.reason,
                )

        # Add VO segments for ducking
        for vo_seg in manifest.vo_segments if hasattr(manifest, 'vo_segments') else []:
            self.audio_mixer.add_vo_segment(
                audio_config,
                vo_seg.get("start", 0),
                vo_seg.get("end", 0),
            )

        # Log configuration
        self.audio_mixer.log_config(audio_config)

        # Build FFmpeg command with audio mixing
        input_files = self.audio_mixer.get_input_files(audio_config)
        filter_complex = self.audio_mixer.generate_ffmpeg_filter(audio_config)

        # Build full command
        cmd = [self.ffmpeg_path, "-y", "-i", str(video_path)]

        # Add audio inputs
        for _, path in input_files:
            cmd.extend(["-i", str(path)])

        # Add filter complex and output
        if filter_complex:
            cmd.extend([
                "-filter_complex", filter_complex,
                "-map", "0:v",
                "-map", "[aout]",
            ])
        else:
            cmd.extend(["-map", "0:v"])
            if input_files:
                cmd.extend(["-map", "1:a"])

        # Do NOT use -shortest as it trims to voiceover length, losing video scenes
        # Audio will be trimmed/padded to match video length automatically
        cmd.extend([
            "-c:v", "copy",
            "-c:a", self.config.audio_codec,
            "-b:a", self.config.audio_bitrate,
            str(output_path)
        ])

        await self._run_ffmpeg(cmd)
        logger.info("  Mixed 5-layer audio")

        return output_path

    async def _run_ffmpeg(self, cmd: List[str]) -> None:
        """Run FFmpeg command asynchronously."""
        logger.debug(f"FFmpeg command: {' '.join(str(x) for x in cmd)}")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            # Extract the actual error from stderr (last few lines usually contain the error)
            error_lines = error_msg.strip().split('\n')
            # Get last 10 lines which typically contain the actual error
            relevant_error = '\n'.join(error_lines[-10:]) if len(error_lines) > 10 else error_msg
            logger.error(f"FFmpeg command failed: {' '.join(str(x) for x in cmd[:15])}...")
            logger.error(f"FFmpeg error:\n{relevant_error}")
            raise Exception(f"FFmpeg failed: {relevant_error}")

    async def _auto_add_sfx(
        self,
        audio_config,
        manifest: Gen3bManifest,
        project_dir: Path,
    ) -> None:
        """
        Auto-discover and add SFX files when manifest doesn't specify them.

        Uses GEN3a action_peaks for timing when available, otherwise uses scene midpoint.

        Looks for:
        - sonic_hook.mp3 -> plays at 0.0s (hook impact)
        - scene_N_sfx.mp3 -> plays at action_peak or scene midpoint
        """
        sfx_dir = project_dir / "sfx"
        logger.info(f"  Auto-SFX: Checking {sfx_dir}")

        # Load GEN3a analysis for action_peaks timing
        gen3a_path = project_dir / "gen3a_analysis.json"
        action_peaks_by_scene = {}
        if gen3a_path.exists():
            import json
            with open(gen3a_path, "r", encoding="utf-8") as f:
                gen3a_data = json.load(f)
            for scene_data in gen3a_data.get("scenes", []):
                scene_num = scene_data.get("scene_number")
                peaks = scene_data.get("action_peaks", [])
                if peaks:
                    # Get the first/most intense action peak
                    peak = peaks[0]
                    action_peaks_by_scene[scene_num] = peak.get("source_timestamp", 0)

        # Add sonic hook at the beginning
        hook_sfx = sfx_dir / "sonic_hook.mp3"
        if hook_sfx.exists():
            self.audio_mixer.add_sfx_event(
                audio_config,
                timestamp=0.0,
                sfx_path=hook_sfx,
                volume=0.8,
                reason="hook_impact",
            )
            logger.info(f"  Auto-added SFX: sonic_hook.mp3 @ 0.0s")

        # Add per-scene SFX at action peaks (or scene midpoint as fallback)
        for scene in manifest.scenes:
            sfx_file = sfx_dir / f"scene_{scene.scene_number}_sfx.mp3"
            if sfx_file.exists():
                # Calculate SFX timestamp
                if scene.scene_number in action_peaks_by_scene:
                    # Transform source_timestamp to output_timestamp using speed_map
                    source_time = action_peaks_by_scene[scene.scene_number]
                    output_time = self._transform_source_to_output(source_time, scene)
                    timestamp = scene.timeline_start + output_time
                    reason = f"scene_{scene.scene_number}_action_peak"
                else:
                    # Fallback: use scene midpoint
                    scene_duration = scene.timeline_end - scene.timeline_start
                    timestamp = scene.timeline_start + (scene_duration / 2)
                    reason = f"scene_{scene.scene_number}_midpoint"

                self.audio_mixer.add_sfx_event(
                    audio_config,
                    timestamp=timestamp,
                    sfx_path=sfx_file,
                    volume=0.6,
                    reason=reason,
                )
                logger.info(f"  Auto-added SFX: scene_{scene.scene_number}_sfx.mp3 @ {timestamp:.1f}s ({reason})")

    def _transform_source_to_output(self, source_time: float, scene) -> float:
        """Transform a source video timestamp to output time using scene's speed_map."""
        if not scene.speed_segments:
            return source_time

        output_time = 0.0
        for segment in scene.speed_segments:
            seg_start = segment.source_start
            seg_end = segment.source_end
            speed = segment.speed or 1.0

            if source_time < seg_start:
                # Before this segment
                break
            elif source_time <= seg_end:
                # Within this segment
                time_in_segment = source_time - seg_start
                output_time += time_in_segment / speed
                break
            else:
                # Past this segment - add full segment duration
                segment_duration = (seg_end - seg_start) / speed
                output_time += segment_duration

        return output_time

    async def render_simple(
        self,
        manifest: Gen3bManifest,
        project_dir: Path,
        output_filename: str = "final_video.mp4",
    ) -> Path:
        """
        Simple render without complex processing (for testing).

        Just concatenates scenes and adds basic audio.
        """
        logger.info("ManifestRenderer: Simple render mode")

        output_path = project_dir / output_filename

        # Find scene videos
        scene_paths = []
        for scene in manifest.scenes:
            source_path = self._resolve_source_path(project_dir, scene.source_file)
            if source_path.exists():
                scene_paths.append(source_path)

        if not scene_paths:
            raise Exception("No scene videos found for rendering")

        # Create concat file
        concat_file = project_dir / "concat_list.txt"
        with open(concat_file, "w") as f:
            for path in scene_paths:
                f.write(f"file '{path}'\n")

        # Simple concat with VO
        vo_path = project_dir / "voiceover.mp3"
        music_path = project_dir / "music.mp3"

        cmd = [self.ffmpeg_path, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file)]

        # Add audio if available
        audio_inputs = []
        if vo_path.exists():
            cmd.extend(["-i", str(vo_path)])
            audio_inputs.append("vo")
        if music_path.exists():
            cmd.extend(["-i", str(music_path)])
            audio_inputs.append("music")

        # Output settings
        cmd.extend([
            "-c:v", self.config.video_codec,
            "-preset", "fast",
            "-crf", "23",
        ])

        if audio_inputs:
            cmd.extend(["-c:a", self.config.audio_codec, "-b:a", "192k"])

        cmd.append(str(output_path))

        await self._run_ffmpeg(cmd)

        logger.success(f"Simple render complete: {output_path}")
        return output_path


# ============================================================================
# EXPORT
# ============================================================================

__all__ = ["ManifestRenderer", "RenderConfig"]
