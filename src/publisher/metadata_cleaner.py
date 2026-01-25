"""
Metadata Cleaner for YTAutoPublisher

Uses FFmpeg to remove metadata from video files before upload.
This helps avoid any tracking or identification issues.
"""

import subprocess
import shutil
from pathlib import Path
from typing import Optional, Tuple
import tempfile

from loguru import logger


class MetadataCleaner:
    """
    Cleans video metadata using FFmpeg.

    Removes all metadata from video files to ensure privacy
    and avoid any tracking or fingerprinting.
    """

    def __init__(self, ffmpeg_path: str = "ffmpeg"):
        """
        Initialize metadata cleaner.

        Args:
            ffmpeg_path: Path to ffmpeg executable
        """
        self.ffmpeg_path = ffmpeg_path
        self._ffmpeg_available: Optional[bool] = None

    def is_ffmpeg_available(self) -> bool:
        """Check if FFmpeg is available"""
        if self._ffmpeg_available is not None:
            return self._ffmpeg_available

        try:
            result = subprocess.run(
                [self.ffmpeg_path, "-version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self._ffmpeg_available = result.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError):
            self._ffmpeg_available = False

        return self._ffmpeg_available

    def get_ffmpeg_version(self) -> Optional[str]:
        """Get FFmpeg version string"""
        try:
            result = subprocess.run(
                [self.ffmpeg_path, "-version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                # First line contains version
                return result.stdout.split("\n")[0]
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

        return None

    def clean_metadata(
        self,
        input_path: Path,
        output_path: Optional[Path] = None,
        keep_original: bool = True,
    ) -> Tuple[bool, Path, Optional[str]]:
        """
        Remove all metadata from video file.

        Args:
            input_path: Path to input video
            output_path: Path for cleaned video (default: same name with _clean suffix)
            keep_original: Whether to keep original file

        Returns:
            Tuple of (success, output_path, error_message)
        """
        if not self.is_ffmpeg_available():
            return False, input_path, "FFmpeg not available"

        if not input_path.exists():
            return False, input_path, f"Input file not found: {input_path}"

        # Determine output path
        if output_path is None:
            output_path = input_path.parent / f"{input_path.stem}_clean{input_path.suffix}"

        # Use temp file first, then move
        temp_output = Path(tempfile.mktemp(suffix=input_path.suffix))

        try:
            # FFmpeg command to remove all metadata
            cmd = [
                self.ffmpeg_path,
                "-i", str(input_path),
                "-map_metadata", "-1",  # Remove all metadata
                "-c:v", "copy",         # Copy video stream (no re-encoding)
                "-c:a", "copy",         # Copy audio stream (no re-encoding)
                "-y",                   # Overwrite output
                str(temp_output),
            ]

            logger.info(f"Cleaning metadata: {input_path.name}")
            logger.debug(f"Command: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            if result.returncode != 0:
                error_msg = result.stderr or "Unknown FFmpeg error"
                logger.error(f"FFmpeg failed: {error_msg}")
                return False, input_path, error_msg

            # Verify output exists and has content
            if not temp_output.exists():
                return False, input_path, "FFmpeg produced no output"

            if temp_output.stat().st_size < 1000:
                return False, input_path, "FFmpeg output too small"

            # Move temp to final destination
            shutil.move(str(temp_output), str(output_path))

            # Remove original if requested
            if not keep_original and output_path != input_path:
                input_path.unlink()

            logger.success(f"Metadata cleaned: {output_path.name}")
            return True, output_path, None

        except subprocess.TimeoutExpired:
            logger.error("FFmpeg timeout")
            return False, input_path, "FFmpeg timeout"

        except Exception as e:
            logger.error(f"Metadata cleaning error: {e}")
            return False, input_path, str(e)

        finally:
            # Cleanup temp file if exists
            if temp_output.exists():
                try:
                    temp_output.unlink()
                except OSError:
                    pass

    def clean_in_place(self, video_path: Path) -> Tuple[bool, Optional[str]]:
        """
        Clean metadata and replace original file.

        Args:
            video_path: Path to video file

        Returns:
            Tuple of (success, error_message)
        """
        # Create temp output
        temp_path = video_path.parent / f"{video_path.stem}_temp{video_path.suffix}"

        success, output_path, error = self.clean_metadata(
            input_path=video_path,
            output_path=temp_path,
            keep_original=True,
        )

        if not success:
            # Cleanup temp
            if temp_path.exists():
                temp_path.unlink()
            return False, error

        try:
            # Replace original with cleaned version
            video_path.unlink()
            shutil.move(str(temp_path), str(video_path))
            return True, None

        except Exception as e:
            # Try to restore original
            if temp_path.exists():
                temp_path.unlink()
            return False, str(e)

    def verify_no_metadata(self, video_path: Path) -> Tuple[bool, dict]:
        """
        Verify that video has no metadata.

        Args:
            video_path: Path to video file

        Returns:
            Tuple of (is_clean, metadata_dict)
        """
        if not self.is_ffmpeg_available():
            return False, {"error": "FFmpeg not available"}

        try:
            # Use ffprobe to check metadata
            cmd = [
                self.ffmpeg_path.replace("ffmpeg", "ffprobe"),
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                str(video_path),
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                return False, {"error": "ffprobe failed"}

            import json
            data = json.loads(result.stdout)

            # Check for metadata in format section
            format_info = data.get("format", {})
            tags = format_info.get("tags", {})

            # Filter out basic/harmless fields
            suspicious_keys = [
                k for k in tags.keys()
                if k.lower() not in ("encoder", "major_brand", "minor_version", "compatible_brands")
            ]

            is_clean = len(suspicious_keys) == 0
            return is_clean, {"tags": tags, "suspicious": suspicious_keys}

        except Exception as e:
            return False, {"error": str(e)}


# Singleton instance
_cleaner: Optional[MetadataCleaner] = None


def get_metadata_cleaner(ffmpeg_path: str = "ffmpeg") -> MetadataCleaner:
    """Get global MetadataCleaner instance"""
    global _cleaner

    if _cleaner is None:
        _cleaner = MetadataCleaner(ffmpeg_path)

    return _cleaner
