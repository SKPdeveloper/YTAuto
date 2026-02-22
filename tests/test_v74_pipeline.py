"""
Unit Tests for v7.4 Pipeline Components

Tests:
- Gen Models (Pydantic validation)
- Beat Analyzer
- Music Generator (config only, no API calls)
- Manifest Renderer (config only)
- Audio Mixer
- Gen3a/Gen3b Services (initialization)
- Pipeline Stages (initialization)

Run with: pytest tests/test_v74_pipeline.py -v
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch, AsyncMock

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ============================================================================
# TEST: Gen Models
# ============================================================================

class TestGenModels:
    """Test Pydantic models for GEN3a and GEN3b."""

    def test_glitch_detection_model(self):
        """Test GlitchDetection model validation."""
        from app.services.gen_models import GlitchDetection

        glitch = GlitchDetection(
            id="S1_G1",
            type="MORPH_FAIL",
            source_start=1.5,
            source_end=2.0,
            severity="MEDIUM",
            recommended_action="CUT",
        )

        assert glitch.type == "MORPH_FAIL"
        assert glitch.source_start == 1.5
        assert glitch.source_end == 2.0
        assert glitch.severity == "MEDIUM"

    def test_speed_segment_model(self):
        """Test SpeedSegment model validation."""
        from app.services.gen_models import SpeedSegment

        segment = SpeedSegment(
            source_start=0.0,
            source_end=3.0,
            output_duration=2.0,
            speed=1.5,
            reason="Action peak",
        )

        assert segment.speed == 1.5
        assert segment.source_end == 3.0
        assert segment.output_duration == 2.0

    def test_action_peak_model(self):
        """Test ActionPeak model validation."""
        from app.services.gen_models import ActionPeak

        peak = ActionPeak(
            id="S1_AP1",
            source_timestamp=5.0,
            type="MOTION_PEAK",
            intensity=0.9,
        )

        assert peak.source_timestamp == 5.0
        assert peak.intensity == 0.9

    def test_visual_classification_model(self):
        """Test VisualClassification model validation."""
        from app.services.gen_models import VisualClassification

        vc = VisualClassification(
            primary_type="EPIC_WIDE",
            secondary_type="DETAIL_FOOD",
            confidence=0.85,
        )

        assert vc.primary_type == "EPIC_WIDE"
        assert vc.confidence == 0.85

    def test_gen3a_scene_analysis_model(self):
        """Test Gen3aSceneAnalysis model validation."""
        from app.services.gen_models import (
            Gen3aSceneAnalysis,
            GlitchDetection,
            ActionPeak,
            SpeedSegment,
            VisualClassification,
        )

        scene = Gen3aSceneAnalysis(
            scene_number=1,
            source_duration=10.0,
            output_duration=4.0,
            video_quality=0.85,
            glitches=[],
            action_peaks=[
                ActionPeak(id="S1_AP1", source_timestamp=2.0, type="MOTION_PEAK", intensity=0.9)
            ],
            dead_spots=[],
            speed_map=[
                SpeedSegment(source_start=0.0, source_end=5.0, output_duration=2.5, speed=2.0, reason="Test")
            ],
            visual_classification=VisualClassification(primary_type="EPIC_WIDE"),
        )

        assert scene.scene_number == 1
        assert scene.output_duration == 4.0
        assert len(scene.action_peaks) == 1

    def test_hook_section_model(self):
        """Test HookSection model validation."""
        from app.services.gen_models import HookSection

        hook = HookSection(
            style="IMPACT",
            duration=0.3,
            effects=[],
            sfx="impact_hit.mp3",
        )

        assert hook.style == "IMPACT"
        assert hook.duration == 0.3

    def test_manifest_scene_model(self):
        """Test ManifestScene model validation."""
        from app.services.gen_models import ManifestScene

        scene = ManifestScene(
            scene_number=1,
            source_file="scene_1/video.mp4",
            timeline_start=0.3,
            timeline_end=4.3,
            speed_segments=[],
            effects=[],
            cuts=[],
        )

        assert scene.scene_number == 1
        assert scene.timeline_start == 0.3

    def test_manifest_subtitle_model(self):
        """Test ManifestSubtitle model validation."""
        from app.services.gen_models import ManifestSubtitle

        sub = ManifestSubtitle(
            id="SUB_1",
            text="Welcome to Glaze City!",
            output_start=0.5,
            output_end=2.5,
            style="IMPACT",
            position="top_center",
            animation="fade",
        )

        assert sub.text == "Welcome to Glaze City!"
        assert sub.animation == "fade"

    def test_gen3b_manifest_model(self):
        """Test Gen3bManifest model validation."""
        from app.services.gen_models import (
            Gen3bManifest,
            HookSection,
            ManifestAudioLayers,
        )

        manifest = Gen3bManifest(
            version="1.3.1",
            project_id="test_project",
            generated_at=datetime.now().isoformat(),
            total_duration=25.0,
            target_duration=25.0,
            hook=HookSection(style="CLASSIC", duration=0.3),
            scenes=[],
            audio_layers=ManifestAudioLayers(),
            subtitles=[],
            global_effects=[],
            loop_point=0.0,
            loop_compliant=True,
        )

        assert manifest.version == "1.3.1"
        assert manifest.total_duration == 25.0


# ============================================================================
# TEST: Beat Analyzer
# ============================================================================

class TestBeatAnalyzer:
    """Test BeatAnalyzer service."""

    def test_beat_analyzer_init(self):
        """Test BeatAnalyzer initialization."""
        from app.services.beat_analyzer import BeatAnalyzer

        analyzer = BeatAnalyzer()
        assert analyzer is not None

    def test_music_beat_data_to_dict(self):
        """Test MusicBeatData serialization."""
        from app.services.beat_analyzer import MusicBeatData

        data = MusicBeatData(
            bpm=120.0,
            total_duration=30.0,
            beats=[{"timestamp": 0.5, "strength": "STRONG"}],
            strong_beats_only=[0.5, 2.5, 4.5],
        )

        d = data.to_dict()
        assert d["bpm"] == 120.0
        assert d["total_duration"] == 30.0
        assert len(d["beats"]) == 1
        assert len(d["strong_beats_only"]) == 3

    def test_default_beat_data_generation(self):
        """Test default beat data generation when librosa is not available."""
        from app.services.beat_analyzer import BeatAnalyzer

        analyzer = BeatAnalyzer()
        default_data = analyzer._get_default_beat_data(Path("test.mp3"))

        assert default_data.bpm == 120.0
        assert default_data.source == "default_fallback"
        assert len(default_data.beats) > 0
        assert len(default_data.sections) == 4


# ============================================================================
# TEST: Music Generator
# ============================================================================

class TestMusicGenerator:
    """Test MusicGenerator service."""

    def test_music_generator_init(self):
        """Test MusicGenerator initialization."""
        from app.services.music_generator import MusicGenerator

        generator = MusicGenerator()
        assert generator is not None
        assert generator.model == "meta/musicgen"

    def test_music_styles_available(self):
        """Test predefined music styles."""
        from app.services.music_generator import MusicGenerator

        generator = MusicGenerator()
        styles = generator.list_styles()

        assert "cinematic" in styles
        assert "ambient" in styles
        assert "epic" in styles
        assert "mysterious" in styles
        assert len(styles) >= 8

    def test_get_style_prompt(self):
        """Test style prompt retrieval."""
        from app.services.music_generator import MusicGenerator

        generator = MusicGenerator()

        prompt = generator.get_style_prompt("epic")
        assert "epic" in prompt.lower()
        assert "orchestral" in prompt.lower()

        # Test fallback for unknown style
        prompt = generator.get_style_prompt("unknown_style")
        assert "cinematic" in prompt.lower()

    def test_music_generation_result_model(self):
        """Test MusicGenerationResult dataclass."""
        from app.services.music_generator import MusicGenerationResult

        result = MusicGenerationResult(
            success=True,
            file_path=Path("test/music.mp3"),
            duration=30.0,
            prompt="epic orchestral",
        )

        assert result.success is True
        assert result.duration == 30.0


# ============================================================================
# TEST: Audio Engine
# ============================================================================

class TestAudioEngine:
    """Test AudioEngine and AudioMixer."""

    def test_audio_layer_enum(self):
        """Test AudioLayer enum values."""
        from app.services.audio_engine import AudioLayer

        assert AudioLayer.BED == "BED"
        assert AudioLayer.MUSIC == "MUSIC"
        assert AudioLayer.SFX == "SFX"
        assert AudioLayer.FOLEY == "FOLEY"
        assert AudioLayer.VO == "VO"

    def test_default_volumes(self):
        """Test default volume levels."""
        from app.services.audio_engine import DEFAULT_VOLUMES, AudioLayer

        assert DEFAULT_VOLUMES[AudioLayer.BED] == 0.15
        assert DEFAULT_VOLUMES[AudioLayer.MUSIC] == 0.5
        assert DEFAULT_VOLUMES[AudioLayer.SFX] == 0.7
        assert DEFAULT_VOLUMES[AudioLayer.FOLEY] == 0.5
        assert DEFAULT_VOLUMES[AudioLayer.VO] == 1.0

    def test_audio_mixer_init(self):
        """Test AudioMixer initialization."""
        from app.services.audio_engine import AudioMixer

        mixer = AudioMixer()
        assert mixer is not None

    def test_audio_mix_config_creation(self):
        """Test AudioMixConfig creation."""
        from app.services.audio_engine import AudioMixer

        mixer = AudioMixer()
        config = mixer.create_default_config(
            total_duration=25.0,
            vo_path=Path("test/vo.mp3"),
            music_path=Path("test/music.mp3"),
        )

        assert config is not None
        assert config.total_duration == 25.0

    def test_sfx_event_addition(self):
        """Test adding SFX events."""
        from app.services.audio_engine import AudioMixer

        mixer = AudioMixer()
        config = mixer.create_default_config(
            total_duration=25.0,
            vo_path=None,
            music_path=None,
        )

        mixer.add_sfx_event(
            config=config,
            timestamp=5.0,
            sfx_path=Path("sfx/impact.mp3"),
            volume=0.8,
            reason="Scene transition",
        )

        assert len(config.sfx_events) == 1
        assert config.sfx_events[0].timestamp == 5.0

    def test_vo_segment_addition(self):
        """Test adding VO segments for ducking."""
        from app.services.audio_engine import AudioMixer

        mixer = AudioMixer()
        config = mixer.create_default_config(
            total_duration=25.0,
            vo_path=Path("test/vo.mp3"),
            music_path=None,
        )

        mixer.add_vo_segment(config, start=2.0, end=5.0)
        mixer.add_vo_segment(config, start=8.0, end=12.0)

        assert len(config.vo_segments) == 2


# ============================================================================
# TEST: Manifest Renderer
# ============================================================================

class TestManifestRenderer:
    """Test ManifestRenderer service."""

    def test_render_config_defaults(self):
        """Test RenderConfig default values."""
        from app.services.manifest_renderer import RenderConfig

        config = RenderConfig()

        assert config.output_width == 1080
        assert config.output_height == 1920  # 9:16 vertical
        assert config.fps == 60
        assert config.video_codec == "auto"
        assert config.crf == 23

    def test_manifest_renderer_init(self):
        """Test ManifestRenderer initialization."""
        from app.services.manifest_renderer import ManifestRenderer, RenderConfig

        renderer = ManifestRenderer()
        assert renderer is not None
        assert renderer.config.output_height == 1920

        # Test with custom config
        custom_config = RenderConfig(fps=30, crf=23)
        renderer2 = ManifestRenderer(config=custom_config)
        assert renderer2.config.fps == 30

    def test_effect_filter_generation(self):
        """Test FFmpeg filter generation for effects."""
        from app.services.manifest_renderer import ManifestRenderer
        from app.services.gen_models import ManifestEffect

        renderer = ManifestRenderer()

        # Test zoom effect
        zoom_effect = ManifestEffect(
            type="ZOOM_IN",
            output_start=0.0,
            output_end=1.0,
        )
        filter_str = renderer._get_effect_filter(zoom_effect)
        assert filter_str is not None
        assert "scale" in filter_str or "crop" in filter_str

        # Test shake effect
        shake_effect = ManifestEffect(
            type="SHAKE",
            output_start=0.0,
            output_end=0.5,
        )
        filter_str = renderer._get_effect_filter(shake_effect)
        assert "crop" in filter_str

    def test_hook_style_filters(self):
        """Test hook style filter generation."""
        from app.services.manifest_renderer import ManifestRenderer

        renderer = ManifestRenderer()

        # Test all hook styles
        styles = ["CLASSIC", "IMPACT", "GLITCH", "ELEGANT", "DRAMATIC"]

        for style in styles:
            filters = renderer._get_hook_style_filters(style)
            assert isinstance(filters, list)
            assert len(filters) > 0

    def test_seconds_to_ass_time(self):
        """Test time conversion for subtitles."""
        from app.services.manifest_renderer import ManifestRenderer

        renderer = ManifestRenderer()

        # Test various times
        assert renderer._seconds_to_ass_time(0.0) == "0:00:00.00"
        assert renderer._seconds_to_ass_time(1.5) == "0:00:01.50"
        assert renderer._seconds_to_ass_time(65.25) == "0:01:05.25"
        # Test 1 hour 1 minute 2 seconds (avoid floating point issues)
        assert renderer._seconds_to_ass_time(3662.0) == "1:01:02.00"


# ============================================================================
# TEST: Gen3a Service
# ============================================================================

class TestGen3aService:
    """Test Gen3aService initialization and helpers."""

    def test_gen3a_service_init(self):
        """Test Gen3aService initialization."""
        from app.services.gen3a_service import Gen3aService

        service = Gen3aService()
        assert service is not None
        assert service.model_name is not None

    def test_gen3a_fallback_prompt(self):
        """Test fallback prompt generation."""
        from app.services.gen3a_service import Gen3aService

        service = Gen3aService()
        fallback = service._get_fallback_prompt()

        assert "GEN3a" in fallback
        assert "glitches" in fallback
        assert "JSON" in fallback

    def test_json_parsing(self):
        """Test JSON response parsing."""
        from app.services.gen3a_service import Gen3aService

        service = Gen3aService()

        # Test with clean JSON
        clean_json = '{"test": "value", "number": 123}'
        result = service._parse_json_response(clean_json)
        assert result["test"] == "value"

        # Test with markdown wrapper
        markdown_json = '```json\n{"test": "value"}\n```'
        result = service._parse_json_response(markdown_json)
        assert result["test"] == "value"

        # Test with extra text
        extra_text = 'Here is the JSON: {"test": "value"} That was it.'
        result = service._parse_json_response(extra_text)
        assert result["test"] == "value"


# ============================================================================
# TEST: Gen3b Service
# ============================================================================

class TestGen3bService:
    """Test Gen3bService initialization and helpers."""

    def test_gen3b_service_init(self):
        """Test Gen3bService initialization."""
        from app.services.gen3b_service import Gen3bService

        service = Gen3bService()
        assert service is not None
        assert service.model_name is not None

    def test_gen3b_fallback_prompt(self):
        """Test fallback prompt generation."""
        from app.services.gen3b_service import Gen3bService

        service = Gen3bService()
        fallback = service._get_fallback_prompt()

        assert "GEN3b" in fallback
        assert "manifest" in fallback
        assert "JSON" in fallback


# ============================================================================
# TEST: Pipeline Stages
# ============================================================================

class TestPipelineStages:
    """Test pipeline stage initialization."""

    def test_gen3a_stage_init(self):
        """Test Gen3aStage initialization."""
        from app.pipeline.gen3_stages import Gen3aStage
        from app.api.schemas import ProjectData

        # Create mock project with required fields
        project = ProjectData(
            project_id="test_123",
            topic="Chocolate Castle",
            num_scenes=6,
            project_dir=str(Path("D:/YTAuto/projects/test_123")),
            scenes=[],
        )

        stage = Gen3aStage(project)
        assert stage.name == "gen3a_video_analysis"
        assert stage.project_id == "test_123"

    def test_gen3b_stage_init(self):
        """Test Gen3bStage initialization."""
        from app.pipeline.gen3_stages import Gen3bStage
        from app.api.schemas import ProjectData

        project = ProjectData(
            project_id="test_456",
            topic="Cookie Tower",
            num_scenes=6,
            project_dir=str(Path("D:/YTAuto/projects/test_456")),
            scenes=[],
        )

        stage = Gen3bStage(project)
        assert stage.name == "gen3b_manifest_generation"
        assert stage.project_id == "test_456"


# ============================================================================
# TEST: Config
# ============================================================================

class TestConfig:
    """Test configuration settings."""

    def test_replicate_config_exists(self):
        """Test Replicate configuration exists."""
        from app.core.config import settings

        assert hasattr(settings, 'REPLICATE_API_TOKEN')
        assert hasattr(settings, 'REPLICATE_MUSIC_MODEL')
        assert hasattr(settings, 'REPLICATE_MUSIC_DURATION')
        assert hasattr(settings, 'REPLICATE_MUSIC_SAMPLE_RATE')

    def test_replicate_model_default(self):
        """Test Replicate model default value."""
        from app.core.config import settings

        assert settings.REPLICATE_MUSIC_MODEL == "meta/musicgen"

    def test_replicate_duration_range(self):
        """Test Replicate duration is within valid range."""
        from app.core.config import settings

        assert settings.REPLICATE_MUSIC_DURATION >= 1.0
        assert settings.REPLICATE_MUSIC_DURATION <= 47.0


# ============================================================================
# TEST: Imports
# ============================================================================

class TestImports:
    """Test that all modules can be imported."""

    def test_import_gen3a_service(self):
        """Test Gen3aService import."""
        from app.services.gen3a_service import Gen3aService
        assert Gen3aService is not None

    def test_import_gen3b_service(self):
        """Test Gen3bService import."""
        from app.services.gen3b_service import Gen3bService
        assert Gen3bService is not None

    def test_import_beat_analyzer(self):
        """Test BeatAnalyzer import."""
        from app.services.beat_analyzer import BeatAnalyzer, MusicBeatData
        assert BeatAnalyzer is not None
        assert MusicBeatData is not None

    def test_import_music_generator(self):
        """Test MusicGenerator import."""
        from app.services.music_generator import MusicGenerator, MusicGenerationResult
        assert MusicGenerator is not None
        assert MusicGenerationResult is not None

    def test_import_manifest_renderer(self):
        """Test ManifestRenderer import."""
        from app.services.manifest_renderer import ManifestRenderer, RenderConfig
        assert ManifestRenderer is not None
        assert RenderConfig is not None

    def test_import_audio_engine(self):
        """Test AudioEngine imports."""
        from app.services.audio_engine import (
            AudioEngine,
            AudioMixer,
            AudioLayer,
            AudioMixConfig,
            DEFAULT_VOLUMES,
        )
        assert AudioEngine is not None
        assert AudioMixer is not None

    def test_import_gen3_stages(self):
        """Test Gen3 stages import."""
        from app.pipeline.gen3_stages import Gen3aStage, Gen3bStage
        assert Gen3aStage is not None
        assert Gen3bStage is not None

    def test_import_postprocess_stage(self):
        """Test PostProcessStage import."""
        from app.pipeline.postprocess_stage import PostProcessStage
        assert PostProcessStage is not None

    def test_import_all_gen_models(self):
        """Test all Gen3a/Gen3b models can be imported."""
        from app.services.gen_models import (
            GlitchDetection,
            ActionPeak,
            DeadSpot,
            SpeedSegment,
            VisualClassification,
            EasterEggVerification,
            VOSegmentAnalysis,
            MusicAnalysis,
            MusicBeat,
            HookVarietyAnalysis,
            Gen3bHandoff,
            Gen3aSceneAnalysis,
            Gen3aOutput,
            ManifestEffect,
            ManifestCut,
            ManifestScene,
            ManifestSubtitle,
            ManifestAudioLayer,
            ManifestSFXEvent,
            ManifestAudioLayers,
            HookSection,
            Gen3bManifest,
        )
        assert Gen3aOutput is not None
        assert Gen3bManifest is not None


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
