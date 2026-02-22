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
import re
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
    # Codec auto-detected: h264_nvenc (NVIDIA GPU) or libx264 (CPU fallback)
    video_codec: str = "auto"  # "auto" = detect, or force specific codec
    audio_codec: str = "aac"
    video_bitrate: str = "8M"
    audio_bitrate: str = "192k"
    preset: str = "medium"  # libx264: ultrafast-veryslow, NVENC: p1-p7
    crf: int = 23  # Quality (18-28 recommended)


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
        """Initialize ManifestRenderer with optional config.

        Note: video codec auto-detection is deferred to _ensure_codec_detected()
        to avoid blocking the event loop with subprocess.run in __init__.
        """
        self.config = config or RenderConfig()
        self.audio_mixer = AudioMixer()
        self._codec_detected = False

        # Використовуємо повний FFmpeg (має ass/subtitles фільтри та libx264)
        # Topaz FFmpeg не має цих фільтрів!
        if hasattr(settings, 'FFMPEG_PATH') and settings.FFMPEG_PATH and settings.FFMPEG_PATH.exists():
            self.ffmpeg_path = str(settings.FFMPEG_PATH)
        elif settings.TOPAZ_FFMPEG_PATH and settings.TOPAZ_FFMPEG_PATH.exists():
            self.ffmpeg_path = str(settings.TOPAZ_FFMPEG_PATH)
        else:
            self.ffmpeg_path = "ffmpeg"

        logger.info("ManifestRenderer initialized (codec detection deferred):")
        logger.info(f"  FFmpeg: {self.ffmpeg_path}")
        logger.info(f"  Output: {self.config.output_width}x{self.config.output_height}")
        logger.info(f"  FPS: {self.config.fps}")

    async def _ensure_codec_detected(self):
        """Auto-detect video codec asynchronously (called once before first render)."""
        if self._codec_detected:
            return

        if self.config.video_codec == "auto":
            self.config.video_codec = await self._detect_video_codec_async()

        # Adjust preset for codec type
        if "nvenc" in self.config.video_codec and self.config.preset == "medium":
            self.config.preset = "p4"  # NVENC equivalent of "medium"

        self._codec_detected = True
        logger.info(f"  Codec: {self.config.video_codec}")

    async def _detect_video_codec_async(self) -> str:
        """
        Auto-detect best available video encoder (async, non-blocking).

        Priority:
        1. h264_nvenc (NVIDIA GPU) - fastest
        2. libx264 (CPU) - universal fallback

        Returns:
            Codec name string
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                self.ffmpeg_path, "-encoders", "-hide_banner",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)

            if proc.returncode == 0 and b"h264_nvenc" in stdout:
                # NVENC listed, but need to verify CUDA is actually working
                test_proc = await asyncio.create_subprocess_exec(
                    self.ffmpeg_path, "-y",
                    "-f", "lavfi", "-i", "nullsrc=s=64x64:d=0.1",
                    "-c:v", "h264_nvenc", "-f", "null", "-",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )
                await asyncio.wait_for(test_proc.communicate(), timeout=10)

                if test_proc.returncode == 0:
                    logger.info("  Codec auto-detect: h264_nvenc (NVIDIA GPU)")
                    return "h264_nvenc"
                else:
                    logger.warning("  NVENC listed but CUDA unavailable, using libx264")

        except asyncio.TimeoutError:
            logger.warning("  Codec detection timeout, using libx264")
        except Exception as e:
            logger.warning(f"  Codec detection failed: {e}, using libx264")

        logger.info("  Codec auto-detect: libx264 (CPU)")
        return "libx264"

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
        # Ensure codec is detected before rendering (async, non-blocking)
        await self._ensure_codec_detected()

        logger.info("=" * 60)
        logger.info("ManifestRenderer: Starting Render")
        logger.info("=" * 60)
        logger.info(f"  Total duration: {manifest.total_duration}s")
        logger.info(f"  Scenes: {len(manifest.scenes)}")
        logger.info(f"  Subtitles: {len(manifest.subtitles)}")
        logger.info(f"  Hook style: {manifest.hook.style}")

        output_path = project_dir / output_filename

        # Initialize variables for cleanup (even if render fails partway through)
        processed_scenes = []
        hook_path = None
        concat_path = None
        effects_path = None
        on_screen_path = None
        subtitled_path = None

        try:
            # Step 0: Compute deterministic scene timeline from VO + brief
            self._compute_deterministic_timeline(manifest, project_dir)

            # Step 1: Process scenes with speed changes
            processed_scenes = await self._process_scenes(manifest.scenes, project_dir)

            # Step 2: Create hook video
            hook_path = await self._create_hook(manifest, project_dir, processed_scenes)

            # Step 3: Concatenate all clips (trim scene 1 by hook duration to avoid duplicate)
            concat_path = await self._concatenate_clips(
                hook_path, processed_scenes, project_dir,
                hook_duration=manifest.hook.duration if hook_path else 0.0,
            )

            # Step 4: Apply global effects
            effects_path = await self._apply_global_effects(
                concat_path, manifest.global_effects, project_dir
            )

            # Step 4.5: Add on-screen text overlays (v8.3.0 — mute-friendly headlines)
            hook_dur = manifest.hook.duration if manifest.hook else 0.0
            on_screen_path = await self._add_on_screen_text(
                effects_path, manifest.scenes, project_dir, hook_dur
            )

            # Step 5: Add subtitles (shifted by actual hook duration)
            subtitled_path = await self._add_subtitles(
                on_screen_path, manifest.subtitles, project_dir, hook_dur
            )

            # Step 6: Mix 5-layer audio
            final_path = await self._mix_audio(
                subtitled_path, manifest, project_dir, output_path
            )

            # Step 7: Cleanup intermediate files
            self._cleanup_intermediate_files(
                project_dir, processed_scenes, hook_path,
                concat_path, effects_path, on_screen_path, subtitled_path
            )

            logger.success("=" * 60)
            logger.success("ManifestRenderer: Render Complete")
            logger.success(f"  Output: {final_path}")
            logger.success("=" * 60)

            return final_path

        except Exception as e:
            logger.error(f"Render failed: {e}")
            # Cleanup intermediate files even on failure to prevent disk bloat
            try:
                self._cleanup_intermediate_files(
                    project_dir, processed_scenes, hook_path,
                    concat_path, effects_path, on_screen_path, subtitled_path,
                )
            except Exception as cleanup_err:
                logger.warning(f"Cleanup after render failure also failed: {cleanup_err}")
            raise

    def _cleanup_intermediate_files(
        self,
        project_dir: Path,
        processed_scenes: List[Path],
        hook_path: Optional[Path],
        concat_path: Optional[Path],
        effects_path: Optional[Path],
        on_screen_path: Optional[Path] = None,
        subtitled_path: Optional[Path] = None,
    ) -> None:
        """Remove intermediate render files to save disk space."""
        cleaned = 0
        for path in processed_scenes:
            # Only delete files that were created by renderer (not original scene videos)
            if path and path.exists() and path.name.startswith(("processed_scene_", "effects_scene_")):
                path.unlink(missing_ok=True)
                cleaned += 1

        for path in [hook_path, concat_path, effects_path, on_screen_path, subtitled_path]:
            if path and path.exists() and path.name in (
                "hook.mp4", "concatenated.mp4", "global_effects.mp4", "on_screen_text.mp4", "subtitled.mp4"
            ):
                path.unlink(missing_ok=True)
                cleaned += 1

        # Also clean effects_scene_N.mp4 files that may exist
        for f in project_dir.glob("effects_scene_*.mp4"):
            f.unlink(missing_ok=True)
            cleaned += 1

        # Clean processed_scene_N.mp4 intermediates (created by speed processing,
        # consumed by effects step, but not tracked in processed_scenes list)
        for f in project_dir.glob("processed_scene_*.mp4"):
            f.unlink(missing_ok=True)
            cleaned += 1

        # Clean concat_list.txt
        concat_list = project_dir / "concat_list.txt"
        if concat_list.exists():
            concat_list.unlink(missing_ok=True)
            cleaned += 1

        if cleaned:
            logger.info(f"  Cleaned up {cleaned} intermediate files")

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

    # ------------------------------------------------------------------
    # VO–Video Alignment
    # ------------------------------------------------------------------

    def _compute_deterministic_timeline(
        self,
        manifest: Gen3bManifest,
        project_dir: Path,
    ) -> None:
        """
        Compute scene timeline from brief duration_seconds + voiceover_timing.json.

        Single source of truth.  No Gemini timeline, no beat-snap, no heuristic.
        Scene boundaries are deterministic: each scene lasts at least its brief
        duration, expanded only when VO audio physically requires more time.

        Must be called BEFORE _process_scenes() since it modifies
        speed_segments in-place.
        """
        import json as _json

        scenes = manifest.scenes
        if not scenes:
            return

        # ── Constants ──
        VO_LEAD = 0.15        # scene appears 0.15s before narration
        VO_TAIL = 0.15        # scene lingers 0.15s after narration
        MONEY_SHOT_MIN = 3.0  # minimum duration for money shot scenes
        MAX_SPEED = 4.0
        MIN_SPEED = 0.5
        DEFAULT_DUR = 2.0     # fallback if brief missing duration

        # 1. Load voiceover_timing.json → vo_map[scene_number] = (start, end)
        #    Times are raw ElevenLabs positions (no hook offset)
        vo_map: Dict[int, tuple] = {}
        vo_timing_path = project_dir / "voiceover_timing.json"
        if vo_timing_path.exists():
            try:
                with open(vo_timing_path, "r", encoding="utf-8") as f:
                    vo_data = _json.load(f)
                for seg in vo_data.get("segments", []):
                    sn = seg.get("scene_number")
                    if sn is not None:
                        vo_map[sn] = (seg["start_time"], seg["end_time"])
            except Exception as e:
                logger.warning(f"  Failed to read voiceover_timing.json: {e}")

        # 2. Load project_brief.json → brief_dur[scene_number] = duration_seconds
        brief_dur: Dict[int, float] = {}
        brief_flags: Dict[int, list] = {}
        brief_path = project_dir / "project_brief.json"
        if brief_path.exists():
            try:
                with open(brief_path, "r", encoding="utf-8") as f:
                    brief_data = _json.load(f)
                for s in brief_data.get("scenes", []):
                    sn = s.get("scene_number")
                    if sn is not None:
                        brief_dur[sn] = s.get("duration_seconds", DEFAULT_DUR)
                        brief_flags[sn] = s.get("special_flags", []) or []
            except Exception as e:
                logger.warning(f"  Failed to read project_brief.json: {e}")

        if not brief_dur and not vo_map:
            logger.info("  No brief or VO timing — using GEN3b timelines as-is")
            return

        # 3. Compute deterministic timeline
        old_total = manifest.total_duration
        cumulative = 0.0
        n = len(scenes)

        logger.info("  Deterministic Timeline:")
        for i, scene in enumerate(scenes):
            sn = scene.scene_number
            old_dur = scene.timeline_end - scene.timeline_start

            # Base duration from brief (or fallback)
            intended = brief_dur.get(sn, DEFAULT_DUR)

            # VO expansion: scene must fit VO audio + lead/tail padding
            vo_dur = 0.0
            if sn in vo_map:
                vo_start, vo_end = vo_map[sn]
                vo_dur = vo_end - vo_start

            min_for_vo = (vo_dur + VO_LEAD + VO_TAIL) if vo_dur > 0 else 0.0
            scene_dur = max(intended, min_for_vo)

            # Money shot floor
            flags = brief_flags.get(sn, []) or (scene.special_flags or [])
            if "MONEY_SHOT" in flags:
                if scene_dur < MONEY_SHOT_MIN:
                    logger.info(f"    Money shot floor: S{sn} {scene_dur:.2f}s → {MONEY_SHOT_MIN}s")
                    scene_dur = MONEY_SHOT_MIN

            # Set timeline boundaries
            scene.timeline_start = cumulative
            scene.timeline_end = cumulative + scene_dur

            # Ensure speed segments exist — without them _process_scenes()
            # copies the full source video (~10s Kling) instead of trimming.
            if not scene.speed_segments:
                src_dur = scene.source_duration if hasattr(scene, 'source_duration') and scene.source_duration else scene_dur
                if src_dur >= scene_dur:
                    # Source longer than needed — trim to first scene_dur seconds at 1x
                    seg_end = scene_dur
                    seg_speed = 1.0
                else:
                    # Source shorter — slow down to fill
                    seg_end = src_dur
                    seg_speed = max(MIN_SPEED, src_dur / scene_dur)
                scene.speed_segments = [SpeedSegment(
                    source_start=0.0,
                    source_end=seg_end,
                    speed=round(seg_speed, 4),
                    output_duration=round(scene_dur, 4),
                    reason="deterministic_trim",
                    motion_density="MEDIUM",
                    technique="NORMAL",
                )]

            # Rescale speed segments to match new duration
            self._rescale_speed_segments(scene, scene_dur, MAX_SPEED, MIN_SPEED)

            # Log
            vo_tag = f"  VO {vo_dur:.2f}s" if vo_dur > 0 else "  (no VO)"
            logger.info(
                f"    S{sn}: {cumulative:.2f}–{cumulative + scene_dur:.2f} "
                f"({scene_dur:.2f}s, was {old_dur:.2f}s){vo_tag}"
            )

            cumulative += scene_dur

        manifest.total_duration = cumulative
        logger.info(
            f"  Timeline total: {manifest.total_duration:.2f}s (was {old_total:.2f}s)"
        )

    @staticmethod
    def _rescale_speed_segments(
        scene: ManifestScene,
        new_target_duration: float,
        max_speed: float = 4.0,
        min_speed: float = 0.5,
    ) -> None:
        """
        Rescale all speed segments proportionally so the scene's total
        output duration matches *new_target_duration*.

        The source_start / source_end boundaries stay the same — only
        ``speed`` and ``output_duration`` are adjusted.
        """
        segs = scene.speed_segments
        if not segs:
            return

        current_total = sum(
            (seg.source_end - seg.source_start) / max(seg.speed, 0.01)
            for seg in segs
        )
        if current_total <= 0 or new_target_duration <= 0:
            return

        ratio = new_target_duration / current_total  # >1 means slower, <1 means faster

        for seg in segs:
            new_speed = seg.speed / ratio
            # Clamp to sane range
            new_speed = max(min_speed, min(new_speed, max_speed))
            seg.speed = round(new_speed, 4)
            seg.output_duration = round(
                (seg.source_end - seg.source_start) / seg.speed, 6
            )

    # ------------------------------------------------------------------

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

            # Apply scene-specific effects (exclude hook effects — handled by _create_hook)
            scene_effects = [e for e in scene.effects if not e.is_hook_effect]
            if scene_effects:
                effects_output = project_dir / f"effects_scene_{scene.scene_number}.mp4"
                await self._apply_effects(output_path, scene_effects, effects_output,
                                          scene_timeline_start=scene.timeline_start)
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
            pts_factor = 1 / max(seg.speed, 0.1)
            # Use filter_complex with trim for correct speed processing
            filter_str = f"[0:v]trim={seg.source_start}:{seg.source_end},setpts={pts_factor}*(PTS-STARTPTS)[v]"
            cmd = [
                self.ffmpeg_path, "-y",
                "-i", str(input_path),
                "-filter_complex", filter_str,
                "-map", "[v]",
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
            pts_factor = 1 / max(seg.speed, 0.1)

            # Use filter_complex with trim for correct speed processing
            filter_str = f"[0:v]trim={seg.source_start}:{seg.source_end},setpts={pts_factor}*(PTS-STARTPTS)[v]"
            cmd = [
                self.ffmpeg_path, "-y",
                "-i", str(input_path),
                "-filter_complex", filter_str,
                "-map", "[v]",
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
            with open(concat_file, 'w', encoding='utf-8') as f:
                for seg_file in segment_files:
                    # Use absolute path to avoid path duplication issues
                    abs_path = str(seg_file.resolve()).replace(chr(92), '/')
                    f.write(f"file '{abs_path}'\n")

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
        else:
            # All segments failed — fallback: copy source as-is
            import shutil
            logger.warning(f"  All {len(speed_segments)} speed segments failed, copying source as fallback")
            shutil.copy(input_path, output_path)

        logger.info(f"  Applied {len(speed_segments)} speed segments")

    async def _apply_effects(
        self,
        input_path: Path,
        effects: List[ManifestEffect],
        output_path: Path,
        scene_timeline_start: float = 0.0,
    ) -> None:
        """Apply visual effects to video."""
        filters = []

        for effect in effects:
            effect_filter = self._get_effect_filter(effect, scene_timeline_start=scene_timeline_start)
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

    def _get_effect_filter(self, effect: ManifestEffect, scene_timeline_start: float = 0.0) -> Optional[str]:
        """Convert ManifestEffect to FFmpeg filter string.

        Args:
            effect: The manifest effect to convert
            scene_timeline_start: Scene's absolute start time in the final timeline.
                Effect timestamps are converted to local scene time by subtracting this.
        """
        effect_type = effect.type.upper()
        params = effect.params or {}

        # Convert absolute timeline timestamps to local scene time
        abs_start = effect.output_start if effect.output_start is not None else 0.0
        abs_end = effect.output_end if effect.output_end is not None else 1.0
        start = max(0.0, abs_start - scene_timeline_start)
        end = max(start + 0.01, abs_end - scene_timeline_start)
        duration = end - start

        # Map effect types to FFmpeg filters
        # Note: zoompan requires explicit size (s=WxH) and fps
        w, h = self.config.output_width, self.config.output_height
        fps = self.config.fps
        # FFmpeg фільтри для ефектів:
        # brightness -> eq=brightness=X або exposure=exposure=X
        # contrast -> eq=contrast=X
        # saturation -> eq=saturation=X або hue=s=X
        # Safe duration divisor for time-based expressions
        dur = max(duration, 0.01)

        effect_map = {
            # --- Original effects ---
            "ZOOM_IN": f"scale={int(w*1.5)}:{int(h*1.5)},crop={w}:{h}:'(iw-{w})*min(1\\,t/{dur})':"
                       f"'(ih-{h})*min(1\\,t/{dur})'",
            "ZOOM_OUT": f"scale={int(w*1.5)}:{int(h*1.5)},crop={w}:{h}:'(iw-{w})*(1-min(1\\,t/{dur}))':"
                        f"'(ih-{h})*(1-min(1\\,t/{dur}))'",
            "ZOOM_PUNCH": f"scale={w}:{h},eq=brightness=0.05:contrast=1.1",
            "CAMERA_SHAKE": f"crop=iw-20:ih-20:x='10+random(0)*10':y='10+random(0)*10',scale={w}:{h}",
            "SHAKE": f"crop=iw-20:ih-20:x='10+random(0)*10':y='10+random(0)*10',scale={w}:{h}",
            "GLOW": "eq=brightness=0.06:saturation=1.3",
            "FLASH": f"eq=brightness=0.4:saturation=0.5:enable='between(t\\,{start}\\,{start + 0.15})'",
            "VIGNETTE": "vignette=PI/4",
            "RGB_SPLIT": "rgbashift=rh=-3:bh=3",
            "CHROMATIC_ABERRATION": "rgbashift=rh=-3:bh=3",
            "GLITCH": "noise=alls=20:allf=t+u",
            "LETTERBOX": "drawbox=x=0:y=0:w=iw:h=ih*0.1:c=black:t=fill,drawbox=x=0:y=ih*0.9:w=iw:h=ih*0.1:c=black:t=fill",
            "COLOR_BOOST": "eq=saturation=1.3:contrast=1.1",
            "WARM": "colorbalance=rs=0.1:gs=0.05:bs=-0.1",
            "COOL": "colorbalance=rs=-0.1:gs=0:bs=0.1",
            # --- Zoom variants (scale+crop, no zoompan) ---
            "SLOW_ZOOM": f"scale={int(w*1.08)}:{int(h*1.08)},crop={w}:{h}:"
                         f"'(iw-{w})/2':'(ih-{h})/2'",
            "DRAMATIC_ZOOM": f"scale={int(w*1.15)}:{int(h*1.15)},crop={w}:{h}:"
                             f"'(iw-{w})*min(1\\,t/{dur})/2':'(ih-{h})*min(1\\,t/{dur})/2'",
            "FOCUS_PULL": "gblur=sigma=2",
            # --- Glow / flash variants ---
            "SOFT_GLOW": "eq=brightness=0.04:saturation=1.15",
            "IMPACT_FLASH": f"eq=brightness=0.5:saturation=0.3:enable='between(t\\,{start}\\,{start + 0.06})'",
            "FLASH_WHITE": f"eq=brightness=0.5:saturation=0.3:enable='between(t\\,{start}\\,{start + 0.1})'",
            # --- Motion / drift (crop-based, no zoompan) ---
            "PARALLAX": f"scale={int(w*1.1)}:{int(h*1.1)},crop={w}:{h}:"
                        f"'(iw-{w})/2+(iw-{w})/2*sin(t*0.8)':'(ih-{h})/2'",
            "DRIFT": f"scale={int(w*1.08)}:{int(h*1.08)},crop={w}:{h}:"
                     f"'(iw-{w})/2+(iw-{w})/2*sin(t*0.5)':'(ih-{h})/2'",
            "GENTLE_DRIFT": f"scale={int(w*1.05)}:{int(h*1.05)},crop={w}:{h}:"
                            f"'(iw-{w})/2+(iw-{w})/2*sin(t*0.3)':'(ih-{h})/2'",
            "GENTLE_PAN": f"scale={int(w*1.08)}:{int(h*1.08)},crop={w}:{h}:"
                          f"'(iw-{w})*min(1\\,t/{dur})':'(ih-{h})/2'",
            # --- Color grading ---
            "COLOR_GRADING": "eq=saturation=1.2:contrast=1.05:brightness=0.02",
            "WARM_GRADE": "colorbalance=rs=0.08:gs=0.04:bs=-0.06",
            "LIGHT_LEAK": "colorbalance=rs=0.12:gs=0.06:bs=-0.04",
            # --- Vignette / lens ---
            "SOFT_VIGNETTE": "vignette=PI/5",
            "LENS_FLARE": "lenscorrection=k1=0.02:k2=0.02",
            # --- Film look ---
            "FILM_GRAIN": "noise=alls=8:allf=t",
            "MOTION_BLUR": "tmix=frames=5:weights='1 1 1 1 1'",
        }

        # Try built-in map first, then fall back to manifest's pre-computed ffmpeg_filter
        result = effect_map.get(effect_type)
        if result:
            return result

        # Use the ffmpeg_filter from the manifest if GEN3b computed one
        if effect.ffmpeg_filter:
            # zoompan is an image-to-video filter: on video input it produces d frames
            # PER INPUT FRAME, causing massive duration explosion (e.g. 75x longer)
            if "zoompan" in effect.ffmpeg_filter:
                logger.warning(f"  Skipping zoompan effect '{effect_type}' — not safe for video input")
                return None
            return effect.ffmpeg_filter

        logger.warning(f"  Unknown effect type '{effect_type}' with no ffmpeg_filter — skipping")
        return None

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
            "PULSE": [
                "eq=brightness=0.12:contrast=1.2",
            ],
            "ZOOM_CRASH": [
                "eq=brightness=0.2:contrast=1.4",
                "unsharp=7:7:2.0:7:7:0.0",
            ],
            "FLICKER": [
                "eq=brightness=0.05",
                "rgbashift=rh=-3:bh=3",
            ],
            "REWIND": [
                "eq=brightness=0.08:saturation=0.8",
                "rgbashift=rh=-4:bh=4",
            ],
            "MORPH_TEASE": [
                "eq=saturation=1.4:brightness=0.05",
                "vignette=PI/5",
            ],
        }

        return style_filters.get(style, [])

    async def _concatenate_clips(
        self,
        hook_path: Optional[Path],
        scene_paths: List[Path],
        project_dir: Path,
        hook_duration: float = 0.0,
    ) -> Path:
        """Concatenate hook and all scenes using filter_complex.

        When a hook is present, scene 1 is trimmed to skip the first hook_duration seconds
        to avoid duplicating footage (hook already shows the beginning of scene 1).
        """
        output_path = project_dir / "concatenated.mp4"

        # Збираємо всі файли для конкатенації
        input_files = []
        # Track which input index is scene 1 (needs trimming if hook exists)
        scene1_input_idx = -1
        if hook_path and hook_path.exists():
            input_files.append(hook_path)
        for i, path in enumerate(scene_paths):
            if path.exists():
                if i == 0 and hook_path and hook_path.exists() and hook_duration > 0:
                    scene1_input_idx = len(input_files)
                input_files.append(path)

        if not input_files:
            raise Exception("No input files for concatenation")

        # Зберігаємо список для інформації
        concat_file = project_dir / "concat_list.txt"
        with open(concat_file, "w", encoding="utf-8") as f:
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
            # Нормалізуємо кожен вхід; trim scene 1 if hook is present
            trim_filter = ""
            if i == scene1_input_idx and hook_duration > 0:
                trim_filter = f"trim=start={hook_duration},setpts=PTS-STARTPTS,"
            filter_parts.append(f"[{i}:v]{trim_filter}scale={w}:{h}:force_original_aspect_ratio=disable,fps={fps},format=yuv420p,setsar=1[v{i}]")
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

    # Regex to strip emoji characters (unsupported by Arial Bold in FFmpeg drawtext)
    _EMOJI_RE = re.compile(
        r'[\U0001F000-\U0001FFFF'    # Emoticons, Dingbats, Symbols
        r'\U00002600-\U000027BF'      # Misc symbols
        r'\U0000FE00-\U0000FE0F'      # Variation selectors
        r'\U0000200D'                 # Zero-width joiner
        r'\U0001FA00-\U0001FA6F'      # Chess, extended-A
        r'\U0001FA70-\U0001FAFF'      # Symbols extended-A
        r'\U00002702-\U000027B0'      # Dingbats
        r']+'
    )

    async def _add_on_screen_text(
        self,
        input_path: Path,
        scenes: List[ManifestScene],
        project_dir: Path,
        hook_duration: float = 0.0,
    ) -> Path:
        """
        Add on-screen text overlays (v8.3.0 — mute-friendly headlines).

        Reads on_screen_text from project_brief.json and burns large headline
        text onto each scene using FFmpeg drawtext filter.

        The text is positioned upper-center (above subtitles) for mute viewers.
        """
        # Load on_screen_text from project brief
        brief_path = project_dir / "project_brief.json"
        scene_texts: Dict[int, str] = {}

        if brief_path.exists():
            try:
                with open(brief_path, 'r', encoding='utf-8') as f:
                    brief = json.load(f)
                for s in brief.get("scenes", []):
                    if isinstance(s, dict) and s.get("on_screen_text"):
                        scene_texts[s.get("scene_number", 0)] = s["on_screen_text"]
            except Exception as e:
                logger.warning(f"  Could not load on_screen_text from brief: {e}")

        if not scene_texts:
            logger.info("  No on_screen_text found in project brief, skipping overlay")
            return input_path

        # Build drawtext filter chain — one drawtext per scene with enable=between()
        drawtext_filters = []
        for scene in scenes:
            text = scene_texts.get(scene.scene_number, "")
            if not text or not text.strip():
                continue

            # Strip emoji (render as rectangles with Arial Bold in FFmpeg)
            text = self._EMOJI_RE.sub('', text).strip()
            if not text:
                continue

            # Escape special characters for FFmpeg drawtext
            escaped = (
                text.replace("\\", "\\\\")
                .replace("'", "\u2019")  # curly apostrophe avoids FFmpeg quoting issues
                .replace(":", "\\:")
                .replace("%", "%%")
            )

            start_t = scene.timeline_start + hook_duration
            end_t = scene.timeline_end + hook_duration

            # Auto-reduce fontsize for long texts to prevent overflow
            fontsize = 56 if len(text) > 25 else 72

            # Montserrat Bold preferred, Arial Bold fallback
            # x clamped to min 10px so text never goes off-screen left
            drawtext_filters.append(
                f"drawtext=text='{escaped}'"
                f":fontfile='C\\:/Windows/Fonts/arialbd.ttf'"
                f":fontsize={fontsize}"
                f":fontcolor=white"
                f":borderw=4"
                f":bordercolor=black"
                f":x=max(10\\,(w-text_w)/2)"
                f":y=h*0.35"
                f":enable='between(t,{start_t:.2f},{end_t:.2f})'"
            )

        if not drawtext_filters:
            return input_path

        output_path = project_dir / "on_screen_text.mp4"
        vf_string = ",".join(drawtext_filters)

        cmd = [
            self.ffmpeg_path, "-y",
            "-i", str(input_path),
            "-vf", vf_string,
            "-c:v", self.config.video_codec,
            *self._get_encoder_params(),
            "-c:a", "copy",
            str(output_path)
        ]

        await self._run_ffmpeg(cmd, cwd=project_dir)
        logger.info(f"  Added on-screen text to {len(drawtext_filters)} scenes")

        return output_path

    async def _add_subtitles(
        self,
        input_path: Path,
        subtitles: List[ManifestSubtitle],
        project_dir: Path,
        hook_duration: float = 0.0,
    ) -> Path:
        """
        Add word-by-word subtitles to video.

        REQUIRES: subtitles.ass generated from vo_alignment.json (word-by-word timing)
        NO FALLBACK: Scene-level subtitles are not acceptable for viral content.

        The .ass file is generated at Stage 2 with a guessed hook_offset (0.3s).
        At render time the actual hook duration is known, so we re-shift all
        Dialogue lines to match the real offset.
        """
        if not subtitles:
            return input_path

        output_path = project_dir / "subtitled.mp4"
        ass_path = project_dir / "subtitles.ass"

        if not ass_path.exists():
            logger.warning(f"  subtitles.ass not found at {ass_path}, skipping subtitle overlay")
            return input_path

        # Re-shift subtitles to match actual hook duration.
        # The .ass was written with hook_offset=0.3 at audio generation time.
        # We parse actual timings from the file and re-write with correct offset.
        shifted_ass_path = project_dir / "subtitles_shifted.ass"
        self._shift_ass_timings(ass_path, shifted_ass_path, hook_duration)

        logger.info(f"  Using word-by-word subtitles (hook shift: {hook_duration:.2f}s)")

        # Use relative path for ASS filter to avoid Windows 'C:' colon issue.
        cmd = [
            self.ffmpeg_path, "-y",
            "-i", str(input_path),
            "-vf", f"ass={shifted_ass_path.name}",
            "-c:v", self.config.video_codec,
            *self._get_encoder_params(),
            "-c:a", "copy",
            str(output_path)
        ]

        await self._run_ffmpeg(cmd, cwd=project_dir)
        logger.info(f"  Added {len(subtitles)} subtitles")

        # Clean up shifted file
        try:
            shifted_ass_path.unlink()
        except Exception:
            pass

        return output_path

    @staticmethod
    def _shift_ass_timings(
        input_ass: Path,
        output_ass: Path,
        target_offset: float,
    ) -> None:
        """
        Re-write an ASS file so that all Dialogue lines are correctly
        offset for the actual hook duration, and enforce minimum word
        display duration.

        The .ass file is generated with hook_offset=0.3s baked into all
        timestamps.  If the actual hook duration differs, we shift by the
        DIFFERENCE (not by earliest-subtitle heuristic, which breaks sync
        when the VO has natural silence at the start).

        Also enforces MIN_WORD_DURATION so ultra-short words (e.g. "STILL"
        at 0.05s) become readable.  This runs every render, bypassing the
        subtitle cache issue.
        """
        import re

        ASSUMED_HOOK_OFFSET = 0.3   # offset baked in during audio generation
        MIN_WORD_DURATION = 0.30    # minimum display time per subtitle word

        _ASS_TIME_RE = re.compile(
            r"Dialogue:\s*\d+,(\d+):(\d+):(\d+)\.(\d+),(\d+):(\d+):(\d+)\.(\d+),"
        )

        def _parse_ass_ts(h: str, m: str, s: str, cs: str) -> float:
            return int(h) * 3600 + int(m) * 60 + int(s) + int(cs) / 100

        def _format_ass_ts(t: float) -> str:
            t = max(t, 0.0)
            h = int(t // 3600)
            t -= h * 3600
            m = int(t // 60)
            t -= m * 60
            s = int(t)
            cs = int(round((t - s) * 100))
            return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

        lines = input_ass.read_text(encoding="utf-8").splitlines()

        # Delta = difference between actual hook and assumed hook.
        # If both are 0.3, delta=0 (no shift needed).
        delta = target_offset - ASSUMED_HOOK_OFFSET

        # First pass: parse all Dialogue entries for shifting + min-duration
        dialogue_indices = []   # (line_index, start, end)
        for idx, line in enumerate(lines):
            match = _ASS_TIME_RE.match(line)
            if match:
                start = _parse_ass_ts(match.group(1), match.group(2), match.group(3), match.group(4))
                end = _parse_ass_ts(match.group(5), match.group(6), match.group(7), match.group(8))
                dialogue_indices.append((idx, start + delta, end + delta))

        if not dialogue_indices:
            output_ass.write_text(input_ass.read_text(encoding="utf-8"), encoding="utf-8")
            return

        # Enforce MIN_WORD_DURATION: bidirectional extension.
        # First extend end, then pull start earlier if still too short.
        for i in range(len(dialogue_indices)):
            line_idx, start, end = dialogue_indices[i]
            dur = end - start
            if dur < MIN_WORD_DURATION:
                # Step 1: try extending end (capped by next subtitle)
                desired_end = start + MIN_WORD_DURATION
                if i + 1 < len(dialogue_indices):
                    next_start = dialogue_indices[i + 1][1]
                    desired_end = min(desired_end, next_start - 0.02)
                end = max(end, desired_end)

                # Step 2: if still too short, pull start earlier
                remaining = MIN_WORD_DURATION - (end - start)
                if remaining > 0:
                    earliest_start = 0.0
                    if i > 0:
                        prev_end = dialogue_indices[i - 1][2]
                        earliest_start = prev_end + 0.02
                    start = max(earliest_start, start - remaining)

                dialogue_indices[i] = (line_idx, start, end)

        # Second pass: rewrite Dialogue lines with corrected times
        dialogue_map = {li: (s, e) for li, s, e in dialogue_indices}
        shifted_lines = []
        for idx, line in enumerate(lines):
            if idx in dialogue_map:
                start, end = dialogue_map[idx]
                new_start = _format_ass_ts(start)
                new_end = _format_ass_ts(end)
                parts = line.split(",", 3)  # "Dialogue: 0", "H:MM:SS.CS", "H:MM:SS.CS", rest
                parts[1] = new_start
                parts[2] = new_end
                line = ",".join(parts)
            shifted_lines.append(line)

        output_ass.write_text("\n".join(shifted_lines), encoding="utf-8")

    def _create_ass_file(
        self,
        subtitles: List[ManifestSubtitle],
        output_path: Path,
    ) -> None:
        """
        DEPRECATED: This method is no longer used.

        Word-by-word subtitles are now REQUIRED from AudioStage (vo_alignment.json).
        This method created scene-level subtitles which are not acceptable for viral content.

        Kept for reference only - DO NOT USE.
        """
        raise DeprecationWarning(
            "_create_ass_file is deprecated. Word-by-word subtitles from vo_alignment.json are required."
        )
        # Original code below for reference:
        # Viral/TikTok style ASS header
        # Montserrat Black, 76px, white text, black stroke 3px
        # YOUTUBE SAFE ZONES (1080x1920 vertical):
        # - Bottom: 350px margin (avoid like/comment/share/subscribe buttons)
        # - Top: 200px margin (avoid video title, channel name overlay)
        header = """[Script Info]
Title: Glaze City Subtitles
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Bottom,Montserrat Black,76,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,3,0,2,50,50,350,1
Style: Top,Montserrat Black,76,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,3,0,8,50,50,200,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

        lines = [header]

        for sub in subtitles:
            start = self._seconds_to_ass_time(sub.output_start)
            end = self._seconds_to_ass_time(sub.output_end)

            # Use Bottom style by default, Top for easter egg scenes
            position = sub.position.lower() if sub.position else "bottom-center"
            style = "Top" if "top" in position else "Bottom"

            # Transform text to UPPERCASE (Netflix style)
            text = sub.text.upper().replace("\n", "\\N")

            lines.append(f"Dialogue: 0,{start},{end},{style},,0,0,0,,{text}")

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
        import asyncio as _asyncio
        # Використовуємо ffprobe з тієї ж директорії що і ffmpeg
        ffprobe_path = Path(self.ffmpeg_path).parent / "ffprobe.exe"
        if not ffprobe_path.exists():
            ffprobe_path = Path(self.ffmpeg_path).parent / "ffprobe"
        if not ffprobe_path.exists():
            ffprobe_path = Path("ffprobe")  # Fallback до системного
        try:
            probe_proc = await _asyncio.create_subprocess_exec(
                str(ffprobe_path), "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path),
                stdout=_asyncio.subprocess.PIPE, stderr=_asyncio.subprocess.PIPE
            )
            probe_stdout, _ = await _asyncio.wait_for(probe_proc.communicate(), timeout=15)
            stdout_text = probe_stdout.decode().strip() if probe_stdout else ""
            actual_duration = float(stdout_text) if probe_proc.returncode == 0 and stdout_text else manifest.total_duration
        except (ValueError, AttributeError, _asyncio.TimeoutError):
            logger.warning(f"  ffprobe returned invalid duration output, using manifest value: {manifest.total_duration}s")
            actual_duration = manifest.total_duration
        logger.info(f"  Video duration: {actual_duration:.2f}s (manifest: {manifest.total_duration}s)")

        # Find music file - check multiple possible locations
        music_path = self._find_audio_file(project_dir, [
            "music.mp3",
            "music/background.mp3",
            "music/music.mp3",
        ])
        if music_path:
            logger.info(f"  Found music: {music_path.relative_to(project_dir)}")
        else:
            logger.warning("  No background music found")

        # Find ambient/bed file
        bed_path = self._find_audio_file(project_dir, [
            "ambient.mp3",
            "bed.mp3",
            "music/ambient.mp3",
        ])

        # Hook duration offset - audio starts after hook
        hook_duration = manifest.hook.duration if manifest.hook else 0.3

        # Create audio mix configuration with actual video duration
        audio_config = self.audio_mixer.create_default_config(
            total_duration=actual_duration,
            vo_path=project_dir / "voiceover.mp3",
            music_path=music_path,
            bed_path=bed_path,
            vo_delay=hook_duration,  # VO starts after hook
        )

        # Add SFX events from manifest
        audio_layers = manifest.audio_layers
        manifest_sfx_added = 0
        for sfx in audio_layers.sfx_events:
            sfx_path = project_dir / "sfx" / sfx.file
            if sfx_path.exists():
                self.audio_mixer.add_sfx_event(
                    audio_config,
                    sfx.output_timestamp,
                    sfx_path,
                    sfx.volume,
                    sfx.effect,
                )
                manifest_sfx_added += 1

        # AUTO-SFX: If no SFX were actually loaded, auto-discover from sfx/ directory
        if manifest_sfx_added == 0:
            logger.info("  No manifest SFX — triggering Auto-SFX discovery")
            await self._auto_add_sfx(audio_config, manifest, project_dir)
        else:
            logger.info(f"  Loaded {manifest_sfx_added} manifest SFX events")

        # Add FOLEY events
        for foley in audio_layers.foley_events:
            foley_path = project_dir / "foley" / foley.file
            if foley_path.exists():
                self.audio_mixer.add_foley_event(
                    audio_config,
                    foley.output_timestamp,
                    foley_path,
                    foley.volume,
                    foley.effect,
                )

        # Add VO segments for ducking (from voiceover_timing.json)
        vo_timing_path = project_dir / "voiceover_timing.json"
        if vo_timing_path.exists():
            import json as _json
            with open(vo_timing_path, "r", encoding="utf-8") as f:
                vo_timing_data = _json.load(f)
            for seg in vo_timing_data.get("segments", []):
                self.audio_mixer.add_vo_segment(
                    audio_config,
                    seg.get("start_time", 0) + hook_duration,
                    seg.get("end_time", 0) + hook_duration,
                )
            logger.info(f"  VO ducking: {len(vo_timing_data.get('segments', []))} segments loaded")
        else:
            logger.warning("  No voiceover_timing.json - VO ducking disabled")

        # Log configuration
        self.audio_mixer.log_config(audio_config)

        # Build FFmpeg command with audio mixing
        input_files = self.audio_mixer.get_input_files(audio_config)
        filter_complex = self.audio_mixer.generate_ffmpeg_filter(audio_config)

        # Build full command
        cmd = [self.ffmpeg_path, "-y", "-i", str(video_path)]

        # Add audio inputs (with -stream_loop -1 for loopable layers like music/bed)
        for layer_name, path, needs_loop in input_files:
            if needs_loop:
                cmd.extend(["-stream_loop", "-1", "-i", str(path)])
            else:
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

    def _find_audio_file(self, project_dir: Path, candidates: List[str]) -> Optional[Path]:
        """
        Find audio file from a list of candidate paths.

        Args:
            project_dir: Base project directory
            candidates: List of relative paths to check

        Returns:
            Path to first existing file, or None if none found
        """
        for candidate in candidates:
            path = project_dir / candidate
            if path.exists():
                return path
        return None

    async def _run_ffmpeg(self, cmd: List[str], timeout: int = 300, cwd: Path = None) -> None:
        """Run FFmpeg command asynchronously with timeout.

        Args:
            cmd: FFmpeg command arguments
            timeout: Maximum time in seconds (default 300s = 5 min)
            cwd: Working directory for FFmpeg process (useful for relative paths)
        """
        logger.debug(f"FFmpeg command: {' '.join(str(x) for x in cmd)}")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd) if cwd else None,
        )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            logger.error(f"FFmpeg timed out after {timeout}s: {' '.join(str(x) for x in cmd[:15])}...")
            raise Exception(f"FFmpeg timed out after {timeout}s")

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
        All scene SFX timestamps include hook offset since scenes start after hook.

        Looks for:
        - sonic_hook.mp3 -> plays at 0.0s (during hook)
        - scene_N_sfx.mp3 -> plays at action_peak or scene midpoint + hook offset
        """
        sfx_dir = project_dir / "sfx"

        if not sfx_dir.exists():
            logger.warning(f"  Auto-SFX: Directory {sfx_dir} not found — skipping")
            return

        sfx_files = list(sfx_dir.glob("*.mp3"))
        logger.info(f"  Auto-SFX: Found {len(sfx_files)} files in {sfx_dir}")

        if not sfx_files:
            logger.info("  Auto-SFX: No .mp3 files found — skipping")
            return

        added_count = 0

        # Hook duration - scene SFX need this offset
        hook_duration = manifest.hook.duration if manifest.hook else 0.3

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

        # Add sonic hook at the beginning (no offset - plays during hook)
        hook_sfx = sfx_dir / "sonic_hook.mp3"
        if hook_sfx.exists():
            self.audio_mixer.add_sfx_event(
                audio_config,
                timestamp=0.0,
                sfx_path=hook_sfx,
                volume=0.8,
                reason="hook_impact",
            )
            added_count += 1
            logger.info(f"  Auto-added SFX: sonic_hook.mp3 @ 0.0s")

        # Load snap_moment data from project_brief for money_shot scenes (Fix #5)
        snap_moment = {}
        money_shot_scenes = set()
        brief_path = project_dir / "project_brief.json"
        if brief_path.exists():
            import json as _json
            with open(brief_path, "r", encoding="utf-8") as f:
                brief_data = _json.load(f)
            # Get snap_moment config
            snap_moment = brief_data.get("audio", {}).get("snap_moment", {})
            if not snap_moment:
                snap_moment = brief_data.get("snap_moment", {})
            # Find money_shot scenes
            for s in brief_data.get("scenes", []):
                if s.get("spectacle_potential", 0) >= 9 or "MONEY_SHOT" in (s.get("special_flags", []) or []):
                    money_shot_scenes.add(s.get("scene_number"))

        # Add per-scene SFX at action peaks (or scene midpoint as fallback)
        # All scene SFX get hook offset since scenes start after hook
        for scene in manifest.scenes:
            sn = scene.scene_number
            # SFX file discovery with glob fallback (Fix #3)
            sfx_file = sfx_dir / f"scene_{sn}_sfx.mp3"
            if not sfx_file.exists():
                # Glob fallback: try various naming patterns
                candidates = list(sfx_dir.glob(f"*scene*{sn}*.*")) + list(sfx_dir.glob(f"*{sn}_sfx*.*"))
                candidates = [c for c in candidates if c.suffix.lower() in ('.mp3', '.wav', '.ogg')]
                if candidates:
                    sfx_file = candidates[0]
                    logger.info(f"  Auto-SFX: Glob fallback found {sfx_file.name} for scene {sn}")

            if sfx_file.exists():
                # Money shot + snap moment: use snap timing (Fix #5)
                if sn in money_shot_scenes and snap_moment:
                    pre_silence = snap_moment.get("pre_silence_seconds", 0.5)
                    relative_time = pre_silence
                    reason = f"scene_{sn}_snap_moment"
                    logger.info(f"  Snap moment: S{sn} SFX at +{pre_silence:.1f}s pre-silence")
                elif scene.scene_number in action_peaks_by_scene:
                    # Transform source_timestamp to output_timestamp using speed_map
                    source_time = action_peaks_by_scene[scene.scene_number]
                    output_time = self._transform_source_to_output(source_time, scene)
                    relative_time = output_time
                    reason = f"scene_{sn}_action_peak"
                else:
                    # Fallback: use scene midpoint
                    scene_duration = scene.timeline_end - scene.timeline_start
                    relative_time = scene_duration / 2
                    reason = f"scene_{sn}_midpoint"

                # Final timestamp = hook_offset + scene_start + relative_time_in_scene
                timestamp = hook_duration + scene.timeline_start + relative_time

                self.audio_mixer.add_sfx_event(
                    audio_config,
                    timestamp=timestamp,
                    sfx_path=sfx_file,
                    volume=0.6,
                    reason=reason,
                )
                added_count += 1
                logger.info(f"  Auto-added SFX: {sfx_file.name} @ {timestamp:.1f}s ({reason})")

        logger.info(f"  Auto-SFX complete: {added_count} SFX events added")

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
        await self._ensure_codec_detected()
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
        with open(concat_file, "w", encoding="utf-8") as f:
            for path in scene_paths:
                safe_path = str(path).replace("\\", "/")
                f.write(f"file '{safe_path}'\n")

        # Simple concat with VO
        vo_path = project_dir / "voiceover.mp3"
        music_path = self._find_audio_file(project_dir, [
            "music.mp3",
            "music/background.mp3",
            "music/music.mp3",
        ])

        cmd = [self.ffmpeg_path, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file)]

        # Add audio if available
        audio_inputs = []
        if vo_path.exists():
            cmd.extend(["-i", str(vo_path)])
            audio_inputs.append("vo")
        if music_path and music_path.exists():
            cmd.extend(["-i", str(music_path)])
            audio_inputs.append("music")

        # Output settings (use codec-appropriate params)
        cmd.extend([
            "-c:v", self.config.video_codec,
            *self._get_encoder_params(),
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
