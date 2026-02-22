"""
Shared fixtures for rendering pipeline tests.
"""

import json
import pytest
from pathlib import Path
from typing import List, Optional
from unittest.mock import patch

from app.services.gen_models import (
    SpeedSegment,
    ManifestScene,
    ManifestEffect,
    ManifestSubtitle,
    Gen3bManifest,
    HookSection,
    ManifestAudioLayers,
)
from app.services.manifest_renderer import ManifestRenderer, RenderConfig
from app.services.audio_engine import (
    AudioMixer,
    AudioMixConfig,
    AudioLayerConfig,
    AudioLayer,
    SFXEvent,
)


# ── Minimal ASS header ──────────────────────────────────────────────

MINIMAL_ASS_HEADER = """\
[Script Info]
Title: Test Subtitles
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Bottom,Montserrat Black,76,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,3,0,2,50,50,350,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


# ── Factories ────────────────────────────────────────────────────────

@pytest.fixture
def make_speed_segment():
    """Factory for SpeedSegment with sensible defaults."""
    def _factory(
        source_start: float = 0.0,
        source_end: float = 4.0,
        speed: float = 1.0,
        output_duration: float = None,
        reason: str = "test",
        motion_density: str = "MEDIUM",
        technique: str = "NORMAL",
    ) -> SpeedSegment:
        if output_duration is None:
            output_duration = (source_end - source_start) / speed
        return SpeedSegment(
            source_start=source_start,
            source_end=source_end,
            speed=speed,
            output_duration=output_duration,
            reason=reason,
            motion_density=motion_density,
            technique=technique,
        )
    return _factory


@pytest.fixture
def make_manifest_scene(make_speed_segment):
    """Factory for ManifestScene with sensible defaults."""
    def _factory(
        scene_number: int = 1,
        source_file: str = "scene_1.mp4",
        timeline_start: float = 0.0,
        timeline_end: float = 4.0,
        speed_segments: List[SpeedSegment] = None,
        source_duration: float = 10.0,
        special_flags: List[str] = None,
    ) -> ManifestScene:
        return ManifestScene(
            scene_number=scene_number,
            source_file=source_file,
            timeline_start=timeline_start,
            timeline_end=timeline_end,
            speed_segments=speed_segments or [],
            source_duration=source_duration,
            special_flags=special_flags or [],
        )
    return _factory


@pytest.fixture
def make_manifest(make_manifest_scene):
    """Factory for Gen3bManifest with N scenes."""
    def _factory(
        n_scenes: int = 3,
        scene_dur: float = 2.0,
        hook_dur: float = 0.3,
        speed_segments_per_scene: List[SpeedSegment] = None,
    ) -> Gen3bManifest:
        scenes = []
        cumulative = 0.0
        for i in range(1, n_scenes + 1):
            scenes.append(make_manifest_scene(
                scene_number=i,
                source_file=f"scene_{i}.mp4",
                timeline_start=cumulative,
                timeline_end=cumulative + scene_dur,
                speed_segments=speed_segments_per_scene,
            ))
            cumulative += scene_dur
        return Gen3bManifest(
            total_duration=cumulative,
            hook=HookSection(style="CLASSIC", duration=hook_dur),
            scenes=scenes,
        )
    return _factory


@pytest.fixture
def renderer():
    """ManifestRenderer with codec detection bypassed."""
    with patch.object(ManifestRenderer, '__init__', lambda self, config=None: None):
        r = ManifestRenderer.__new__(ManifestRenderer)
        r.config = RenderConfig()
        r.audio_mixer = AudioMixer.__new__(AudioMixer)
        r._codec_detected = True
        r.ffmpeg_path = "ffmpeg"
        return r


@pytest.fixture
def audio_mixer():
    """AudioMixer without logger noise."""
    with patch("app.services.audio_engine.logger"):
        return AudioMixer()


@pytest.fixture
def project_dir_with_timing(tmp_path):
    """Factory that writes voiceover_timing.json and project_brief.json."""
    def _factory(
        scenes: List[dict] = None,
        vo_segments: List[dict] = None,
    ) -> Path:
        project_dir = tmp_path / "proj_test"
        project_dir.mkdir(exist_ok=True)

        if scenes is not None:
            brief = {"scenes": scenes}
            (project_dir / "project_brief.json").write_text(
                json.dumps(brief), encoding="utf-8"
            )

        if vo_segments is not None:
            vo_timing = {"segments": vo_segments}
            (project_dir / "voiceover_timing.json").write_text(
                json.dumps(vo_timing), encoding="utf-8"
            )

        return project_dir
    return _factory


@pytest.fixture
def ass_content():
    """Factory that generates valid ASS content with given Dialogue lines."""
    def _factory(dialogues: List[str] = None) -> str:
        lines = MINIMAL_ASS_HEADER.rstrip("\n")
        if dialogues:
            lines += "\n" + "\n".join(dialogues)
        return lines
    return _factory
