"""
Run post-processing pipeline for a project.
Simulates the flow after videos are downloaded from Hegsfield.
"""
import asyncio
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.core.orchestrator import ProjectOrchestrator
from app.api.schemas import ProjectStatus, PipelineStage
from app.utils.logger import logger


async def run_post_processing(project_id: str):
    """Run the full post-processing pipeline for a project."""
    logger.info("=" * 70)
    logger.info(f"STARTING POST-PROCESSING PIPELINE FOR: {project_id}")
    logger.info("=" * 70)

    orchestrator = ProjectOrchestrator()

    # Load project from disk
    project = await orchestrator.resume_from_disk(project_id)

    if not project:
        logger.error(f"Project {project_id} not found!")
        return None

    logger.info(f"Project loaded: {project.project_id}")
    logger.info(f"  Status: {project.status}")
    logger.info(f"  Stage: {project.current_stage}")
    logger.info(f"  Scenes: {len(project.scenes)}")

    # Check if pipeline needs to run
    if project.current_stage in [PipelineStage.AWAITING_RENDER_APPROVAL, PipelineStage.COMPLETED]:
        logger.info(f"\nPipeline already completed! Final video at:")
        logger.info(f"  {project.project_dir / 'final.mp4'}")
        return project

    # Force status to trigger post-processing
    project.status = ProjectStatus.POST_PROCESSING
    project.current_stage = PipelineStage.VOICEOVER

    # Run the post-processing pipeline
    logger.info("\nRunning post-processing pipeline v7.5...")
    await orchestrator._run_post_processing(project)

    logger.success("=" * 70)
    logger.success("POST-PROCESSING COMPLETE!")
    logger.success("=" * 70)

    return project


if __name__ == "__main__":
    project_id = sys.argv[1] if len(sys.argv) > 1 else "proj_de28aebfbe30"
    asyncio.run(run_post_processing(project_id))
