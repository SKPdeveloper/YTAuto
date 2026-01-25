"""
Pipeline Module v7.5

Modular pipeline stages for video generation workflow.
Each stage is independent and can be resumed after failure.

v7.5 Stages:
1. ScriptStage - Generate script via GEN1 + GEN2
2. ImageStage - Generate images (PRIMARY + remaining)
3. ValidationStage - Validate images via VAL_IMG v3.0
4. VideoStage - Generate videos for all scenes
5. AudioStage - Generate voiceover, music, ambient, SFX
6. Gen3aStage - Video Analysis (Gemini Vision)
7. Gen3bStage - Manifest Generation (FFmpeg)
8. PostProcessStage - Manifest rendering with 5-layer audio
9. CleanupStage - Import SFX to library, cleanup intermediate files

Usage:
    from app.pipeline import PipelineOrchestrator, get_orchestrator

    orchestrator = get_orchestrator()
    project = await orchestrator.create_project("Chocolate Castle")
    await orchestrator.run(project.project_id)
"""

from app.pipeline.base import BasePipelineStage, StageResult, StageStatus
from app.pipeline.project import ProjectManager, get_project_manager
from app.pipeline.script_stage import ScriptStage
from app.pipeline.image_stage import ImageStage
from app.pipeline.validation_stage import ValidationStage
from app.pipeline.video_stage import VideoStage
from app.pipeline.audio_stage import AudioStage
from app.pipeline.gen3_stages import Gen3aStage, Gen3bStage
from app.pipeline.postprocess_stage import PostProcessStage
from app.pipeline.cleanup_stage import CleanupStage
from app.pipeline.orchestrator import PipelineOrchestrator, get_orchestrator

__all__ = [
    # Base
    "BasePipelineStage",
    "StageResult",
    "StageStatus",
    # Project
    "ProjectManager",
    "get_project_manager",
    # Stages
    "ScriptStage",
    "ImageStage",
    "ValidationStage",
    "VideoStage",
    "AudioStage",      # v7.5: Audio Generation
    "Gen3aStage",      # v7.4: Video Analysis
    "Gen3bStage",      # v7.4: Manifest Generation
    "PostProcessStage",
    "CleanupStage",    # v7.5: Project Cleanup
    # Orchestrator
    "PipelineOrchestrator",
    "get_orchestrator",
]
