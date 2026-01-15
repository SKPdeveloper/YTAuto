"""
Services module v7.4 - AI generation clients and integrations

Use lazy imports to avoid circular import issues:
    from app.services.content_brain import ContentBrain
    from app.services.visual_engine import HiggsFieldClient
    from app.services.visual_engine_web import HiggsFieldWebAdapter, create_visual_engine
    from app.services.image_validator import ImageValidator
    from app.services.gen3a_service import Gen3aService
    from app.services.gen3b_service import Gen3bService
    from app.services.beat_analyzer import BeatAnalyzer
    from app.services.manifest_renderer import ManifestRenderer
    from app.services.audio_engine import AudioEngine, AudioMixer
    from app.services.music_generator import MusicGenerator
"""

# Lazy imports - import directly when needed
__all__ = [
    # Generation clients
    "HiggsFieldClient",
    "HiggsFieldWebAdapter",
    "create_visual_engine",
    "ContentBrain",
    "ImageValidator",
    # v7.4: New services
    "Gen3aService",       # Video Analyst v1.3.1
    "Gen3bService",       # FFmpeg Manifest Generator v1.3.1
    "BeatAnalyzer",       # Librosa beat detection
    "ManifestRenderer",   # FFmpeg video renderer
    "AudioEngine",        # ElevenLabs TTS
    "AudioMixer",         # 5-layer audio mixing
    "MusicGenerator",     # Replicate Stable Audio music generation
    # Models
    "Script",
    "Scene",
    "ScenePrompts",
    "ValidationResult",
    "GlazeCityProject",
    "GlazeParser",
    "ValidationResponse",
]
