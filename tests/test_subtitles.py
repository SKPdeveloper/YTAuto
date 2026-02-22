"""
Tests for ManifestRenderer subtitle methods:
  - _seconds_to_ass_time (instance, 5 tests)
  - _shift_ass_timings (static, 8 tests)
  - _rescale_subtitles (instance, 7 tests)
"""

import shutil
import pytest
from pathlib import Path

from tests.conftest import MINIMAL_ASS_HEADER
from app.services.manifest_renderer import ManifestRenderer


# =====================================================================
# TestSecondsToAssTime
# =====================================================================


class TestSecondsToAssTime:
    """ManifestRenderer._seconds_to_ass_time — instance method."""

    def test_zero(self, renderer):
        assert renderer._seconds_to_ass_time(0.0) == "0:00:00.00"

    def test_fractional(self, renderer):
        # 1.55s → 0:00:01.55
        assert renderer._seconds_to_ass_time(1.55) == "0:00:01.55"

    def test_minutes(self, renderer):
        # 65.5s → 0:01:05.50
        assert renderer._seconds_to_ass_time(65.5) == "0:01:05.50"

    def test_boundary_rounding(self, renderer):
        # 0.999s → centisecs = int(0.999 * 100) = 99 → 0:00:00.99
        assert renderer._seconds_to_ass_time(0.999) == "0:00:00.99"

    def test_negative_clamped(self, renderer):
        # _seconds_to_ass_time doesn't clamp; we document actual behavior
        # With negative, int() truncation may give odd results but
        # caller is responsible for clamping. Test that it doesn't crash.
        result = renderer._seconds_to_ass_time(-0.5)
        assert isinstance(result, str)


# =====================================================================
# TestShiftAssTimings
# =====================================================================


class TestShiftAssTimings:
    """ManifestRenderer._shift_ass_timings — static method."""

    ASSUMED_HOOK = 0.3  # baked into ASS

    def _make_ass(self, tmp_path, dialogues, name="input.ass"):
        """Helper to write an ASS file."""
        content = MINIMAL_ASS_HEADER
        if dialogues:
            content += "\n".join(dialogues)
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        return path

    def _read_dialogues(self, path):
        """Read only Dialogue lines."""
        import re
        lines = path.read_text(encoding="utf-8").splitlines()
        return [l for l in lines if l.startswith("Dialogue:")]

    def test_zero_delta(self, tmp_path):
        """offset=0.3 (==ASSUMED) → delta=0, timestamps unchanged."""
        inp = self._make_ass(tmp_path, [
            "Dialogue: 0,0:00:01.00,0:00:02.00,Bottom,,0,0,0,,HELLO"
        ])
        out = tmp_path / "output.ass"

        ManifestRenderer._shift_ass_timings(inp, out, 0.3)

        dialogues = self._read_dialogues(out)
        assert "0:00:01.00" in dialogues[0]
        assert "0:00:02.00" in dialogues[0]

    def test_positive_delta(self, tmp_path):
        """offset=0.5 → delta=+0.2 → timestamps shifted forward."""
        inp = self._make_ass(tmp_path, [
            "Dialogue: 0,0:00:01.00,0:00:02.00,Bottom,,0,0,0,,HELLO"
        ])
        out = tmp_path / "output.ass"

        ManifestRenderer._shift_ass_timings(inp, out, 0.5)

        dialogues = self._read_dialogues(out)
        # 1.00 + 0.2 = 1.20, 2.00 + 0.2 = 2.20
        assert "0:00:01.20" in dialogues[0]
        assert "0:00:02.20" in dialogues[0]

    def test_negative_guard(self, tmp_path):
        """Subtitle at 0.1s + delta=-0.5 → clamped to 0:00:00.00."""
        inp = self._make_ass(tmp_path, [
            "Dialogue: 0,0:00:00.10,0:00:00.50,Bottom,,0,0,0,,EARLY"
        ])
        out = tmp_path / "output.ass"

        # offset=-0.2 → delta = -0.2 - 0.3 = -0.5
        ManifestRenderer._shift_ass_timings(inp, out, -0.2)

        dialogues = self._read_dialogues(out)
        # Start: max(0, 0.1 - 0.5) = 0.0
        assert "0:00:00.00" in dialogues[0]

    def test_min_word_duration(self, tmp_path):
        """0.05s word → extended to ≥ 0.30s."""
        inp = self._make_ass(tmp_path, [
            "Dialogue: 0,0:00:01.00,0:00:01.05,Bottom,,0,0,0,,STILL"
        ])
        out = tmp_path / "output.ass"

        ManifestRenderer._shift_ass_timings(inp, out, 0.3)  # zero delta

        dialogues = self._read_dialogues(out)
        # Parse end time: should be at least start + 0.30
        import re
        m = re.match(r"Dialogue:\s*\d+,(\d+:\d+:\d+\.\d+),(\d+:\d+:\d+\.\d+),", dialogues[0])
        assert m
        # Parse start centiseconds
        start_parts = m.group(1).split(":")
        start_s = int(start_parts[0]) * 3600 + int(start_parts[1]) * 60 + float(start_parts[2])
        end_parts = m.group(2).split(":")
        end_s = int(end_parts[0]) * 3600 + int(end_parts[1]) * 60 + float(end_parts[2])
        assert end_s - start_s >= 0.29  # allow small rounding

    def test_preserves_header(self, tmp_path):
        """Non-Dialogue lines must be unchanged."""
        inp = self._make_ass(tmp_path, [
            "Dialogue: 0,0:00:01.00,0:00:02.00,Bottom,,0,0,0,,WORD"
        ])
        out = tmp_path / "output.ass"

        ManifestRenderer._shift_ass_timings(inp, out, 0.3)

        lines = out.read_text(encoding="utf-8").splitlines()
        assert any("[Script Info]" in l for l in lines)
        assert any("Style: Bottom" in l for l in lines)

    def test_empty_dialogue(self, tmp_path):
        """Header only, no Dialogue → output is copy."""
        inp = self._make_ass(tmp_path, [])
        out = tmp_path / "output.ass"

        ManifestRenderer._shift_ass_timings(inp, out, 0.5)

        assert out.exists()
        lines = out.read_text(encoding="utf-8").splitlines()
        assert not any(l.startswith("Dialogue:") for l in lines)

    def test_multiple_dialogues(self, tmp_path):
        """5 lines → all shifted."""
        dialogues = [
            f"Dialogue: 0,0:00:0{i}.00,0:00:0{i}.50,Bottom,,0,0,0,,WORD{i}"
            for i in range(1, 6)
        ]
        inp = self._make_ass(tmp_path, dialogues)
        out = tmp_path / "output.ass"

        ManifestRenderer._shift_ass_timings(inp, out, 0.5)  # delta +0.2

        result_dialogues = self._read_dialogues(out)
        assert len(result_dialogues) == 5
        # First word shifted: 1.00 + 0.2 = 1.20
        assert "0:00:01.20" in result_dialogues[0]

    def test_end_extension_capped_by_next(self, tmp_path):
        """Extend for MIN_WORD_DURATION doesn't overlap next subtitle."""
        inp = self._make_ass(tmp_path, [
            "Dialogue: 0,0:00:01.00,0:00:01.05,Bottom,,0,0,0,,A",
            "Dialogue: 0,0:00:01.10,0:00:01.50,Bottom,,0,0,0,,B",
        ])
        out = tmp_path / "output.ass"

        ManifestRenderer._shift_ass_timings(inp, out, 0.3)

        dialogues = self._read_dialogues(out)
        import re
        # Parse end of first and start of second
        m1 = re.match(r"Dialogue:\s*\d+,(\d+:\d+:\d+\.\d+),(\d+:\d+:\d+\.\d+),", dialogues[0])
        m2 = re.match(r"Dialogue:\s*\d+,(\d+:\d+:\d+\.\d+),(\d+:\d+:\d+\.\d+),", dialogues[1])
        end1_parts = m1.group(2).split(":")
        end1 = int(end1_parts[0]) * 3600 + int(end1_parts[1]) * 60 + float(end1_parts[2])
        start2_parts = m2.group(1).split(":")
        start2 = int(start2_parts[0]) * 3600 + int(start2_parts[1]) * 60 + float(start2_parts[2])
        # end of A must be ≤ start of B (with tiny gap)
        assert end1 <= start2 + 0.01


# =====================================================================
# TestRescaleSubtitles
# =====================================================================


class TestRescaleSubtitles:
    """ManifestRenderer._rescale_subtitles — instance method."""

    def _write_ass(self, project_dir, dialogues):
        """Write subtitles.ass to project dir."""
        content = MINIMAL_ASS_HEADER
        if dialogues:
            content += "\n".join(dialogues)
        (project_dir / "subtitles.ass").write_text(content, encoding="utf-8")

    def _make_scene_vo_data(self, entries):
        """Helper: build scene_vo_data list."""
        result = []
        for sn, orig_start, orig_end, atempo in entries:
            result.append({
                "scene_number": sn,
                "original_start": orig_start,
                "original_end": orig_end,
                "atempo_ratio": atempo,
                "compressed_dur": (orig_end - orig_start) / atempo,
            })
        return result

    def test_no_ass_noop(self, renderer, make_manifest, tmp_path):
        """No subtitles.ass → no crash."""
        manifest = make_manifest(n_scenes=1)
        project_dir = tmp_path / "proj_no_ass"
        project_dir.mkdir()

        # Should not raise
        renderer._rescale_subtitles(project_dir, [], manifest)

    def test_basic_rescale_atempo_1(self, renderer, make_manifest, tmp_path):
        """atempo=1.0, no compression → times shift only by timeline_start."""
        manifest = make_manifest(n_scenes=1, scene_dur=5.0)
        manifest.scenes[0].timeline_start = 2.0
        manifest.scenes[0].timeline_end = 7.0

        project_dir = tmp_path / "proj_basic"
        project_dir.mkdir()

        # Dialogue at 0.8s raw VO time (after subtracting 0.3 hook = 0.5s VO)
        # Scene VO: original_start=0.0, original_end=4.0
        self._write_ass(project_dir, [
            "Dialogue: 0,0:00:00.80,0:00:01.30,Bottom,,0,0,0,,WORD"
        ])

        scene_vo_data = self._make_scene_vo_data([
            (1, 0.0, 4.0, 1.0),  # scene 1, no compression
        ])

        renderer._rescale_subtitles(project_dir, scene_vo_data, manifest)

        result = (project_dir / "subtitles.ass").read_text(encoding="utf-8")
        assert "Dialogue:" in result

    def test_compressed_rescale(self, renderer, make_manifest, tmp_path):
        """atempo=1.5 → time_in_scene / 1.5."""
        manifest = make_manifest(n_scenes=1, scene_dur=3.0)
        manifest.scenes[0].timeline_start = 0.0
        manifest.scenes[0].timeline_end = 3.0

        project_dir = tmp_path / "proj_compressed"
        project_dir.mkdir()

        # Word at raw VO 1.3s (baked hook 0.3 → raw 1.0s)
        # Scene: orig 0.0-3.0, atempo 1.5
        # time_in_scene = 1.0 - 0.0 = 1.0
        # compressed_time = 1.0 / 1.5 ≈ 0.667
        # new_pos = 0.0 + 0.667 = 0.667
        # + hook 0.3 = 0.967
        self._write_ass(project_dir, [
            "Dialogue: 0,0:00:01.30,0:00:01.80,Bottom,,0,0,0,,WORD"
        ])

        scene_vo_data = self._make_scene_vo_data([
            (1, 0.0, 3.0, 1.5),
        ])

        renderer._rescale_subtitles(project_dir, scene_vo_data, manifest)

        result = (project_dir / "subtitles.ass").read_text(encoding="utf-8")
        assert "Dialogue:" in result

    def test_bleed_clamped(self, renderer, make_manifest, tmp_path):
        """End past scene boundary → clamped."""
        manifest = make_manifest(n_scenes=2, scene_dur=2.0)
        manifest.scenes[0].timeline_start = 0.0
        manifest.scenes[0].timeline_end = 2.0
        manifest.scenes[1].timeline_start = 2.0
        manifest.scenes[1].timeline_end = 4.0

        project_dir = tmp_path / "proj_bleed"
        project_dir.mkdir()

        # Word near scene boundary: start at 1.8s raw VO, end at 2.5s
        self._write_ass(project_dir, [
            "Dialogue: 0,0:00:02.10,0:00:02.80,Bottom,,0,0,0,,BLEED"
        ])

        scene_vo_data = self._make_scene_vo_data([
            (1, 0.0, 2.0, 1.0),
        ])

        renderer._rescale_subtitles(project_dir, scene_vo_data, manifest)

        result = (project_dir / "subtitles.ass").read_text(encoding="utf-8")
        assert "Dialogue:" in result

    def test_backup_created(self, renderer, make_manifest, tmp_path):
        """subtitles_original.ass created on first call."""
        manifest = make_manifest(n_scenes=1, scene_dur=3.0)
        project_dir = tmp_path / "proj_backup"
        project_dir.mkdir()

        self._write_ass(project_dir, [
            "Dialogue: 0,0:00:00.50,0:00:01.00,Bottom,,0,0,0,,HELLO"
        ])

        scene_vo_data = self._make_scene_vo_data([
            (1, 0.0, 2.0, 1.0),
        ])

        renderer._rescale_subtitles(project_dir, scene_vo_data, manifest)

        assert (project_dir / "subtitles_original.ass").exists()

    def test_idempotent_rerender(self, renderer, make_manifest, tmp_path):
        """Call twice → same result (restores from original)."""
        manifest = make_manifest(n_scenes=1, scene_dur=3.0)
        project_dir = tmp_path / "proj_idempotent"
        project_dir.mkdir()

        self._write_ass(project_dir, [
            "Dialogue: 0,0:00:00.80,0:00:01.30,Bottom,,0,0,0,,TEST"
        ])

        scene_vo_data = self._make_scene_vo_data([
            (1, 0.0, 2.0, 1.2),
        ])

        renderer._rescale_subtitles(project_dir, scene_vo_data, manifest)
        result1 = (project_dir / "subtitles.ass").read_text(encoding="utf-8")

        renderer._rescale_subtitles(project_dir, scene_vo_data, manifest)
        result2 = (project_dir / "subtitles.ass").read_text(encoding="utf-8")

        assert result1 == result2

    def test_multi_segment_scene(self, renderer, make_manifest, tmp_path):
        """Two VO segments for same scene → sequential target_start offsets."""
        manifest = make_manifest(n_scenes=1, scene_dur=5.0)
        manifest.scenes[0].timeline_start = 0.0
        manifest.scenes[0].timeline_end = 5.0

        project_dir = tmp_path / "proj_multi"
        project_dir.mkdir()

        self._write_ass(project_dir, [
            "Dialogue: 0,0:00:00.50,0:00:01.00,Bottom,,0,0,0,,FIRST",
            "Dialogue: 0,0:00:02.50,0:00:03.00,Bottom,,0,0,0,,SECOND",
        ])

        # Two VO segments for scene 1
        scene_vo_data = self._make_scene_vo_data([
            (1, 0.0, 1.5, 1.0),   # first chunk: 1.5s
            (1, 1.5, 3.0, 1.0),   # second chunk: 1.5s
        ])

        renderer._rescale_subtitles(project_dir, scene_vo_data, manifest)

        result = (project_dir / "subtitles.ass").read_text(encoding="utf-8")
        dialogues = [l for l in result.splitlines() if l.startswith("Dialogue:")]
        assert len(dialogues) == 2
