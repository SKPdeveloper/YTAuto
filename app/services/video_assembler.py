"""
Video Assembler - FFmpeg-based video assembly for final output

This module combines scene videos with voiceover audio to create
the final video output using FFmpeg.

Features:
- Concatenate multiple video clips in order
- Add voiceover audio track
- Sync audio with video timing
- Support for on-screen text overlays (optional)
- Async subprocess execution

Requirements:
- FFmpeg installed (uses Topaz FFmpeg by default)
"""

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any

from app.core.config import settings
from app.utils.logger import logger


class VideoAssembler:
    """
    Assembles final video from scene clips and audio tracks using FFmpeg.

    Workflow:
    1. Load project_brief.json for scene order and timing
    2. Find all scene videos (scene_N/video.mp4)
    3. Create concat filter for video concatenation
    4. Add voiceover audio track
    5. Export final.mp4

    Example:
        >>> assembler = VideoAssembler()
        >>> final_path = await assembler.assemble_project(
        ...     project_dir=Path("projects/my_project")
        ... )
    """

    def __init__(self, ffmpeg_path: Optional[Path] = None):
        """
        Initialize VideoAssembler with FFmpeg path.

        Args:
            ffmpeg_path: Path to FFmpeg executable. Uses Topaz FFmpeg by default.
        """
        self.ffmpeg_path = ffmpeg_path or settings.TOPAZ_FFMPEG_PATH

        if not self.ffmpeg_path.exists():
            logger.warning(f"FFmpeg not found at: {self.ffmpeg_path}")
            # Try system FFmpeg as fallback
            self.ffmpeg_path = Path("ffmpeg")
            logger.info("Falling back to system FFmpeg")

        logger.info(f"VideoAssembler initialized:")
        logger.info(f"  FFmpeg: {self.ffmpeg_path}")

    async def assemble_project(
        self,
        project_dir: Path,
        output_filename: str = "final.mp4",
        include_voiceover: bool = True,
        video_codec: str = "libx264",
        audio_codec: str = "aac",
        video_bitrate: str = "25M",  # Increased for 4K quality
        audio_bitrate: str = "320k",  # High quality audio
        crf: int = 15,  # Lower = better quality
    ) -> Path:
        """
        Assemble final video from project scenes and voiceover.

        Args:
            project_dir: Path to project directory containing scenes and voiceover
            output_filename: Name of output file (default: final.mp4)
            include_voiceover: Whether to include voiceover.mp3 (default: True)
            video_codec: Video codec (default: libx264)
            audio_codec: Audio codec (default: aac)
            video_bitrate: Video bitrate (default: 8M)
            audio_bitrate: Audio bitrate (default: 192k)
            crf: Constant Rate Factor for quality (default: 18, lower = better)

        Returns:
            Path to the assembled final video

        Raises:
            FileNotFoundError: If project_brief.json or videos not found
            RuntimeError: If FFmpeg fails
        """
        logger.info("=" * 60)
        logger.info("Starting Video Assembly")
        logger.info("=" * 60)
        logger.info(f"Project: {project_dir.name}")

        # 1. Load project brief
        project_brief_path = project_dir / "project_brief.json"
        if not project_brief_path.exists():
            raise FileNotFoundError(f"project_brief.json not found: {project_brief_path}")

        with open(project_brief_path, "r", encoding="utf-8") as f:
            project_data = json.load(f)

        project_name = project_data.get("property", {}).get("name", "Unknown")
        scenes = project_data.get("scenes", [])
        logger.info(f"Project Name: {project_name}")
        logger.info(f"Total Scenes: {len(scenes)}")

        # 2. Find video files
        video_files = self._find_scene_videos(project_dir, scenes)
        if not video_files:
            raise FileNotFoundError(f"No video files found in {project_dir}")

        logger.info(f"Found {len(video_files)} video files")

        # 3. Check for voiceover
        voiceover_path = project_dir / "voiceover.mp3"
        has_voiceover = voiceover_path.exists() and include_voiceover

        if has_voiceover:
            logger.info(f"Voiceover: {voiceover_path}")
        else:
            logger.warning("No voiceover found, assembling video only")

        # 4. Build FFmpeg command
        output_path = project_dir / output_filename

        ffmpeg_cmd = self._build_ffmpeg_command(
            video_files=video_files,
            voiceover_path=voiceover_path if has_voiceover else None,
            output_path=output_path,
            video_codec=video_codec,
            audio_codec=audio_codec,
            video_bitrate=video_bitrate,
            audio_bitrate=audio_bitrate,
            crf=crf,
        )

        # 5. Execute FFmpeg
        logger.info("Running FFmpeg...")
        logger.debug(f"Command: {' '.join(str(c) for c in ffmpeg_cmd)}")

        success = await self._run_ffmpeg(ffmpeg_cmd)

        if success and output_path.exists():
            file_size = output_path.stat().st_size
            logger.success("=" * 60)
            logger.success("VIDEO ASSEMBLY COMPLETE!")
            logger.success("=" * 60)
            logger.success(f"  Output: {output_path}")
            logger.success(f"  Size: {file_size:,} bytes ({file_size / 1024 / 1024:.1f} MB)")
            return output_path
        else:
            raise RuntimeError("FFmpeg failed to create output file")

    def _find_scene_videos(
        self,
        project_dir: Path,
        scenes: List[Dict[str, Any]],
    ) -> List[Path]:
        """
        Find video files for each scene in order.

        Supports two folder structures:
        1. Old: scene_N/video.mp4
        2. New: videos/scene_N.mp4

        Args:
            project_dir: Project directory
            scenes: List of scene data from project_brief.json

        Returns:
            List of paths to video files in scene order
        """
        video_files = []
        videos_dir = project_dir / "videos"

        for scene in sorted(scenes, key=lambda s: s.get("scene_number", 0)):
            scene_num = scene.get("scene_number", 0)
            video_path = None

            # Try new structure first: videos/scene_N.mp4
            new_path = videos_dir / f"scene_{scene_num}.mp4"
            if new_path.exists():
                video_path = new_path
                logger.debug(f"  Scene {scene_num}: {video_path} (videos folder)")

            # Fallback to old structure: scene_N/video.mp4
            if not video_path:
                old_path = project_dir / f"scene_{scene_num}" / "video.mp4"
                if old_path.exists():
                    video_path = old_path
                    logger.debug(f"  Scene {scene_num}: {video_path} (scene folder)")

            if video_path:
                video_files.append(video_path)
            else:
                logger.warning(f"  Scene {scene_num}: video NOT FOUND")

        return video_files

    def _build_ffmpeg_command(
        self,
        video_files: List[Path],
        voiceover_path: Optional[Path],
        output_path: Path,
        video_codec: str,
        audio_codec: str,
        video_bitrate: str,
        audio_bitrate: str,
        crf: int,
    ) -> List[str]:
        """
        Build FFmpeg command for video assembly.

        This uses the concat demuxer method which is simpler and works well
        when all videos have the same codec/resolution.
        """
        cmd = [str(self.ffmpeg_path), "-y"]  # -y to overwrite output

        # Input files
        for video_file in video_files:
            cmd.extend(["-i", str(video_file)])

        if voiceover_path:
            cmd.extend(["-i", str(voiceover_path)])

        # Build filter complex
        n_videos = len(video_files)
        filter_parts = []

        # Concatenate all videos
        video_inputs = "".join(f"[{i}:v]" for i in range(n_videos))
        filter_parts.append(f"{video_inputs}concat=n={n_videos}:v=1:a=0[outv]")

        # Handle audio
        if voiceover_path:
            # Use voiceover as audio (it's the last input)
            voiceover_idx = n_videos
            filter_parts.append(f"[{voiceover_idx}:a]aformat=sample_rates=44100:channel_layouts=stereo[outa]")
            filter_complex = ";".join(filter_parts)
            cmd.extend(["-filter_complex", filter_complex])
            cmd.extend(["-map", "[outv]", "-map", "[outa]"])
        else:
            # Video only, no audio
            filter_complex = filter_parts[0]
            cmd.extend(["-filter_complex", filter_complex])
            cmd.extend(["-map", "[outv]"])

        # Output settings - підтримка різних кодеків
        if video_codec == "libx264":
            cmd.extend([
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", str(crf),
            ])
        elif "nvenc" in video_codec:
            # NVIDIA NVENC
            cmd.extend([
                "-c:v", video_codec,
                "-preset", "p4",
                "-rc", "constqp", "-qp", str(crf),
            ])
        elif "qsv" in video_codec:
            # Intel Quick Sync
            cmd.extend([
                "-c:v", video_codec,
                "-preset", "medium",
                "-global_quality", str(crf),
            ])
        else:
            # Інші кодеки (h264_mf, h264_amf, etc.) - тільки bitrate
            cmd.extend([
                "-c:v", video_codec,
                "-b:v", video_bitrate,
            ])

        if voiceover_path:
            cmd.extend([
                "-c:a", audio_codec,
                "-b:a", audio_bitrate,
            ])

        # Output file
        cmd.append(str(output_path))

        return cmd

    async def _run_ffmpeg(self, cmd: List[str]) -> bool:
        """
        Run FFmpeg command asynchronously.

        Args:
            cmd: FFmpeg command as list of arguments

        Returns:
            True if successful, False otherwise
        """
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                logger.info("FFmpeg completed successfully")
                return True
            else:
                logger.error(f"FFmpeg failed with code {process.returncode}")
                logger.error(f"Stderr: {stderr.decode('utf-8', errors='ignore')[-1000:]}")
                return False

        except Exception as e:
            logger.error(f"FFmpeg execution error: {e}")
            return False

    async def assemble_with_concat_file(
        self,
        project_dir: Path,
        output_filename: str = "final.mp4",
    ) -> Path:
        """
        Alternative assembly method using concat demuxer with file list.

        This method is more reliable for videos with different codecs.
        Creates a temporary file list and uses FFmpeg concat demuxer.

        Args:
            project_dir: Project directory
            output_filename: Output filename

        Returns:
            Path to assembled video
        """
        logger.info("Using concat file method...")

        # Load project brief
        project_brief_path = project_dir / "project_brief.json"
        with open(project_brief_path, "r", encoding="utf-8") as f:
            project_data = json.load(f)

        scenes = project_data.get("scenes", [])
        video_files = self._find_scene_videos(project_dir, scenes)

        if not video_files:
            raise FileNotFoundError("No video files found")

        # Create concat file
        concat_file = project_dir / "concat_list.txt"
        with open(concat_file, "w", encoding="utf-8") as f:
            for video_path in video_files:
                # Use forward slashes for FFmpeg compatibility
                safe_path = str(video_path).replace("\\", "/")
                f.write(f"file '{safe_path}'\n")

        logger.debug(f"Created concat file: {concat_file}")

        # Check for voiceover
        voiceover_path = project_dir / "voiceover.mp3"
        has_voiceover = voiceover_path.exists()

        output_path = project_dir / output_filename

        # Build command
        cmd = [
            str(self.ffmpeg_path), "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
        ]

        if has_voiceover:
            cmd.extend(["-i", str(voiceover_path)])
            cmd.extend([
                "-c:v", "copy",  # Copy video stream (fast)
                "-c:a", "aac",
                "-strict", "-2",  # Allow experimental aac encoder
                "-b:a", "192k",
                "-map", "0:v",
                "-map", "1:a",
                "-shortest",  # End when shortest stream ends
            ])
        else:
            cmd.extend(["-c", "copy"])  # Copy all streams

        cmd.append(str(output_path))

        # Run FFmpeg
        success = await self._run_ffmpeg(cmd)

        # Cleanup concat file
        if concat_file.exists():
            concat_file.unlink()

        if success and output_path.exists():
            file_size = output_path.stat().st_size
            logger.success(f"Video assembled: {output_path} ({file_size / 1024 / 1024:.1f} MB)")
            return output_path
        else:
            raise RuntimeError("FFmpeg concat failed")

    async def assemble(
        self,
        project_dir: Path,
        output_filename: str = "final.mp4",
        include_voiceover: bool = True,
    ) -> Path:
        """
        Simple video assembly - concatenates videos without re-encoding.
        
        Uses concat demuxer for fast assembly (no re-encode).
        Adds voiceover audio track if available.
        
        Args:
            project_dir: Project directory with scene folders
            output_filename: Output filename
            include_voiceover: Include voiceover.mp3 audio
            
        Returns:
            Path to assembled video
        """
        logger.info("=" * 60)
        logger.info("SIMPLE VIDEO ASSEMBLY (no re-encode)")
        logger.info("=" * 60)
        
        # Use concat file method for simple/fast assembly
        return await self.assemble_with_concat_file(
            project_dir=project_dir,
            output_filename=output_filename,
        )

    async def get_video_info(self, video_path: Path) -> Dict[str, Any]:
        """
        Get video information using FFprobe.

        Args:
            video_path: Path to video file

        Returns:
            Dictionary with video info (duration, resolution, etc.)
        """
        ffprobe_path = self.ffmpeg_path.parent / "ffprobe.exe"
        if not ffprobe_path.exists():
            ffprobe_path = Path("ffprobe")

        cmd = [
            str(ffprobe_path),
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(video_path),
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, _ = await process.communicate()

            if process.returncode == 0:
                return json.loads(stdout.decode("utf-8"))
            else:
                return {}

        except Exception as e:
            logger.error(f"FFprobe error: {e}")
            return {}


# ============================================================================
# EXPORT
# ============================================================================

__all__ = ["VideoAssembler"]
