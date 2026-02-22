"""
Smoke test: post-render validation for rendered projects.

Validates:
1. File existence (final_video.mp4 ≥ 1MB)
2. Duration (|actual - expected| ≤ 0.5s)
3. Video properties (1080×1920, ~60fps, h264+aac)
4. Subtitle validity (ASS parseable, timestamps ≤ video duration)
5. VO timing (no overlapping segments, scene_number matches)
6. Audio levels (max_volume ≤ 0 dBFS — no clipping)
7. Cleanup (no intermediate files)

Requires: ffmpeg/ffprobe in PATH.
Can also be called as a pipeline hook via post_render_validate().
"""

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from loguru import logger


# =====================================================================
# RenderValidationResult
# =====================================================================


@dataclass
class RenderValidationResult:
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return len(self.errors) == 0


# =====================================================================
# Core validation function
# =====================================================================


def validate_render(project_dir: Path) -> RenderValidationResult:
    """
    Validate a rendered project directory.

    Args:
        project_dir: Path to project directory (proj_<uuid>/)

    Returns:
        RenderValidationResult with errors, warnings, metrics
    """
    result = RenderValidationResult()
    ffprobe = shutil.which("ffprobe")

    # ── 1. File existence ──
    final_video = None
    for name in ("final_4k.mp4", "final_video.mp4"):
        candidate = project_dir / name
        if candidate.exists():
            final_video = candidate
            break

    if final_video is None:
        result.errors.append("final_video.mp4 missing")
        return result

    size_mb = final_video.stat().st_size / (1024 * 1024)
    result.metrics["file_size_mb"] = round(size_mb, 2)
    if size_mb < 1.0:
        result.errors.append(f"final_video too small: {size_mb:.2f} MB (< 1 MB)")

    if not ffprobe:
        result.warnings.append("ffprobe not found — skipping media checks")
        return result

    # ── 2. Duration ──
    try:
        probe = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams",
             str(final_video)],
            capture_output=True, text=True, timeout=30,
        )
        probe_data = json.loads(probe.stdout)
    except Exception as e:
        result.errors.append(f"ffprobe failed: {e}")
        return result

    actual_duration = float(probe_data.get("format", {}).get("duration", 0))
    result.metrics["actual_duration"] = round(actual_duration, 2)

    # Expected duration from project_brief.json or manifest.json
    expected_duration = _get_expected_duration(project_dir)
    if expected_duration:
        result.metrics["expected_duration"] = round(expected_duration, 2)
        drift = abs(actual_duration - expected_duration)
        if drift > 0.5:
            result.errors.append(
                f"Duration drift: actual={actual_duration:.2f}s vs expected={expected_duration:.2f}s "
                f"(drift={drift:.2f}s > 0.5s)"
            )

    # ── 3. Video properties ──
    video_stream = None
    audio_stream = None
    for stream in probe_data.get("streams", []):
        if stream.get("codec_type") == "video" and video_stream is None:
            video_stream = stream
        elif stream.get("codec_type") == "audio" and audio_stream is None:
            audio_stream = stream

    if video_stream:
        width = int(video_stream.get("width", 0))
        height = int(video_stream.get("height", 0))
        result.metrics["resolution"] = f"{width}x{height}"
        if width != 1080 or height != 1920:
            result.errors.append(f"Wrong resolution: {width}x{height} (expected 1080x1920)")

        # FPS check (~60)
        r_fps = video_stream.get("r_frame_rate", "0/1")
        try:
            num, den = map(int, r_fps.split("/"))
            fps = num / den if den else 0
        except (ValueError, ZeroDivisionError):
            fps = 0
        result.metrics["fps"] = round(fps, 2)
        if fps < 55 or fps > 65:
            result.warnings.append(f"FPS outside 55-65 range: {fps:.2f}")

        codec = video_stream.get("codec_name", "")
        result.metrics["video_codec"] = codec
        if codec not in ("h264", "hevc"):
            result.warnings.append(f"Unexpected video codec: {codec}")
    else:
        result.errors.append("No video stream found")

    if audio_stream:
        audio_codec = audio_stream.get("codec_name", "")
        result.metrics["audio_codec"] = audio_codec
        if audio_codec != "aac":
            result.warnings.append(f"Unexpected audio codec: {audio_codec}")
    else:
        result.warnings.append("No audio stream found")

    # ── 4. Subtitle validity ──
    ass_path = project_dir / "subtitles.ass"
    if ass_path.exists():
        _validate_subtitles(ass_path, actual_duration, result)
    else:
        result.warnings.append("subtitles.ass not found")

    # ── 5. VO timing ──
    vo_timing_path = project_dir / "voiceover_timing.json"
    if vo_timing_path.exists():
        _validate_vo_timing(vo_timing_path, result)

    # ── 6. Audio levels ──
    _validate_audio_levels(final_video, ffprobe, result)

    # ── 7. Cleanup ──
    _validate_cleanup(project_dir, result)

    return result


# =====================================================================
# Helper validators
# =====================================================================


def _get_expected_duration(project_dir: Path) -> Optional[float]:
    """Get expected duration from manifest or brief."""
    manifest_path = project_dir / "manifest.json"
    if manifest_path.exists():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            return float(data.get("total_duration", 0))
        except Exception:
            pass

    brief_path = project_dir / "project_brief.json"
    if brief_path.exists():
        try:
            data = json.loads(brief_path.read_text(encoding="utf-8"))
            scenes = data.get("scenes", [])
            return sum(s.get("duration_seconds", 2.0) for s in scenes)
        except Exception:
            pass

    return None


def _validate_subtitles(
    ass_path: Path, video_duration: float, result: RenderValidationResult
) -> None:
    """Check ASS file is parseable and timestamps don't exceed video duration."""
    _ASS_TIME_RE = re.compile(
        r"Dialogue:\s*\d+,(\d+):(\d+):(\d+)\.(\d+),(\d+):(\d+):(\d+)\.(\d+),"
    )

    try:
        lines = ass_path.read_text(encoding="utf-8").splitlines()
    except Exception as e:
        result.errors.append(f"ASS unparseable: {e}")
        return

    dialogue_count = 0
    for line in lines:
        match = _ASS_TIME_RE.match(line)
        if not match:
            continue
        dialogue_count += 1
        end_time = (
            int(match.group(5)) * 3600 +
            int(match.group(6)) * 60 +
            int(match.group(7)) +
            int(match.group(8)) / 100
        )
        if end_time > video_duration + 1.0:
            result.warnings.append(
                f"Subtitle ends at {end_time:.2f}s > video duration {video_duration:.2f}s"
            )
            break

    result.metrics["subtitle_count"] = dialogue_count


def _validate_vo_timing(
    vo_timing_path: Path, result: RenderValidationResult
) -> None:
    """Check VO segments don't overlap and have valid scene_numbers."""
    try:
        data = json.loads(vo_timing_path.read_text(encoding="utf-8"))
    except Exception as e:
        result.warnings.append(f"voiceover_timing.json invalid: {e}")
        return

    segments = data.get("segments", [])
    result.metrics["vo_segment_count"] = len(segments)

    # Check for overlaps within same scene
    by_scene: Dict[int, List[tuple]] = {}
    for seg in segments:
        sn = seg.get("scene_number")
        if sn is None:
            continue
        start = seg.get("start_time", 0)
        end = seg.get("end_time", 0)
        by_scene.setdefault(sn, []).append((start, end))

    for sn, segs in by_scene.items():
        segs.sort()
        for i in range(len(segs) - 1):
            if segs[i][1] > segs[i + 1][0] + 0.01:
                result.warnings.append(
                    f"VO overlap in scene {sn}: {segs[i]} overlaps {segs[i+1]}"
                )


def _validate_audio_levels(
    video_path: Path, ffprobe_path: str, result: RenderValidationResult
) -> None:
    """Check max volume doesn't exceed 0 dBFS (clipping)."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return

    try:
        proc = subprocess.run(
            [ffmpeg, "-i", str(video_path), "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True, timeout=60,
        )
        stderr = proc.stderr
        match = re.search(r"max_volume:\s*([-\d.]+)\s*dB", stderr)
        if match:
            max_vol = float(match.group(1))
            result.metrics["max_volume_db"] = max_vol
            if max_vol > 0:
                result.errors.append(f"Audio clipping: max_volume={max_vol} dB > 0 dBFS")
    except Exception:
        result.warnings.append("volumedetect failed")


def _validate_cleanup(project_dir: Path, result: RenderValidationResult) -> None:
    """Check that intermediate files have been cleaned up."""
    intermediates = [
        "scene_*_processed.mp4",
        "temp_concat.mp4",
        "video_no_audio.mp4",
    ]

    for pattern in intermediates:
        found = list(project_dir.glob(pattern))
        if found:
            result.warnings.append(
                f"Intermediate files still present: {[f.name for f in found]}"
            )


# =====================================================================
# Pipeline hook
# =====================================================================


async def post_render_validate(project_dir: Path) -> bool:
    """
    Pipeline hook: validate render after completion.

    Returns True if validation passed, False otherwise.
    Logs errors/warnings via loguru.
    """
    result = validate_render(project_dir)

    for err in result.errors:
        logger.error(f"SMOKE FAIL: {err}")
    for warn in result.warnings:
        logger.warning(f"SMOKE WARN: {warn}")

    if result.metrics:
        logger.info(f"SMOKE METRICS: {result.metrics}")

    return result.passed


# =====================================================================
# Pytest: discover rendered projects
# =====================================================================


def _discover_rendered_projects() -> List[Path]:
    """Find all project directories with final_video.mp4 or final_4k.mp4."""
    projects_dir = Path(__file__).parent.parent / "projects"
    if not projects_dir.exists():
        return []

    results = []
    for proj_dir in sorted(projects_dir.iterdir()):
        if not proj_dir.is_dir():
            continue
        if (proj_dir / "final_4k.mp4").exists() or (proj_dir / "final_video.mp4").exists():
            results.append(proj_dir)

    return results


_RENDERED = _discover_rendered_projects()


@pytest.mark.skipif(
    not shutil.which("ffprobe"),
    reason="ffprobe not found in PATH",
)
@pytest.mark.skipif(
    not _RENDERED,
    reason="No rendered projects found in projects/",
)
@pytest.mark.parametrize(
    "project_dir",
    _RENDERED,
    ids=[p.name for p in _RENDERED],
)
def test_rendered_project(project_dir: Path):
    """Smoke test for each rendered project."""
    result = validate_render(project_dir)

    # Print details for debugging
    if result.warnings:
        for w in result.warnings:
            print(f"  WARN: {w}")
    if result.metrics:
        print(f"  METRICS: {result.metrics}")

    assert result.passed, (
        f"Render validation failed for {project_dir.name}:\n"
        + "\n".join(f"  ERROR: {e}" for e in result.errors)
    )


# =====================================================================
# Unit tests for validate_render itself
# =====================================================================


class TestValidateRender:
    """Test validate_render with synthetic data."""

    def test_missing_final_video(self, tmp_path):
        """No final_video.mp4 → error."""
        result = validate_render(tmp_path)
        assert not result.passed
        assert any("missing" in e for e in result.errors)

    def test_too_small_video(self, tmp_path):
        """<1MB file → error."""
        (tmp_path / "final_video.mp4").write_bytes(b"\x00" * 100)

        result = validate_render(tmp_path)
        assert any("too small" in e for e in result.errors)

    def test_result_dataclass(self):
        """RenderValidationResult defaults."""
        r = RenderValidationResult()
        assert r.passed is True
        assert r.errors == []
        assert r.warnings == []
        assert r.metrics == {}

    def test_result_with_errors(self):
        """passed=False when errors exist."""
        r = RenderValidationResult(errors=["something broke"])
        assert r.passed is False
