"""
Project Manager

Handles project creation, loading, saving, and state management.
"""

import uuid
import json
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

from loguru import logger

from app.core.config import settings
from app.core.state_manager import state_manager
from app.core.paths import (
    PROJECTS_DIR,
    get_project_path,
    get_scene_path,
    get_project_brief_path,
    get_project_logs_path,
    ensure_project_structure,
)
from app.utils.logger import setup_project_logger
from app.api.schemas import (
    ProjectData,
    SceneData,
    ProjectStatus,
    SceneStatus,
    PipelineStage,
)


class ProjectManager:
    """
    Manages project lifecycle: create, load, save, resume.

    All state is persisted to SQLite and project files.

    Usage:
        manager = ProjectManager()

        # Create new project
        project = await manager.create("Chocolate Castle", num_scenes=6)

        # Load existing project
        project = await manager.load("proj_abc123")

        # Save state
        await manager.save(project)

        # Load from disk (for resume)
        project = await manager.load_from_disk("proj_abc123")
    """

    def __init__(self):
        self._active_projects: Dict[str, ProjectData] = {}

    async def create(
        self,
        topic: str,
        num_scenes: int = 6,
        style: str = "educational",
        target_audience: str = "general"
    ) -> ProjectData:
        """
        Create a new project.

        Args:
            topic: Video topic (or "FREE_TOPIC" for AI choice)
            num_scenes: Number of scenes (always 6 per GEN1/GEN2 contract)
            style: Video style
            target_audience: Target audience

        Returns:
            ProjectData object
        """
        # Enforce 6 scenes (GEN1/GEN2 contract)
        if num_scenes != 6:
            logger.warning(f"num_scenes={num_scenes} overridden to 6 (GEN1/GEN2 contract)")
            num_scenes = 6

        # Ensure database is initialized
        await state_manager.initialize()

        # Generate unique project ID
        project_id = f"proj_{uuid.uuid4().hex[:12]}"

        # Create project directory structure
        ensure_project_structure(project_id, num_scenes)

        # Setup project-specific logging
        setup_project_logger(project_id, get_project_logs_path(project_id))

        # Create project data
        project = ProjectData(
            project_id=project_id,
            topic=topic,
            num_scenes=num_scenes,
            style=style,
            target_audience=target_audience,
            total_scenes=num_scenes,
            project_dir=get_project_path(project_id),
            status=ProjectStatus.CREATED,
            current_stage=PipelineStage.CREATED,
        )

        # Save to memory and database
        self._active_projects[project_id] = project
        await self.save(project)

        logger.success(f"Project created: {project_id}")
        logger.info(f"  Topic: {topic}")
        logger.info(f"  Scenes: {num_scenes}")
        logger.info(f"  Directory: {project.project_dir}")

        return project

    async def load(self, project_id: str) -> Optional[ProjectData]:
        """
        Load project from memory or database.

        Args:
            project_id: Project ID

        Returns:
            ProjectData if found, None otherwise
        """
        # Check memory first
        if project_id in self._active_projects:
            return self._active_projects[project_id]

        # Load from database
        project_dict = await state_manager.get_state(f"project:{project_id}")
        if not project_dict:
            logger.warning(f"Project not found in database: {project_id}")
            return None

        # Convert to ProjectData
        project = ProjectData(**project_dict)
        self._active_projects[project_id] = project

        logger.info(f"Loaded project from database: {project_id}")
        return project

    async def load_from_disk(self, project_id: str) -> Optional[ProjectData]:
        """
        Load project from disk files (for resume after restart).

        Reads project_brief.json and scans scene directories.

        Args:
            project_id: Project ID

        Returns:
            ProjectData if found, None otherwise
        """
        project_dir = get_project_path(project_id)

        if not project_dir.exists():
            logger.error(f"Project directory not found: {project_dir}")
            return None

        brief_path = get_project_brief_path(project_id)
        if not brief_path.exists():
            logger.error(f"project_brief.json not found: {brief_path}")
            return None

        logger.info(f"Loading project from disk: {project_id}")

        # Setup project-specific logging
        setup_project_logger(project_id, get_project_logs_path(project_id))

        # Read project_brief.json
        with open(brief_path, "r", encoding="utf-8") as f:
            brief = json.load(f)

        # Create ProjectData
        project = ProjectData(
            project_id=project_id,
            topic=brief.get("property", {}).get("name", "Unknown"),
            title=brief.get("property", {}).get("name", ""),
            num_scenes=len(brief.get("scenes", [])),
            total_scenes=len(brief.get("scenes", [])),
            project_dir=project_dir,
            status=ProjectStatus.PROCESSING_SCENES,
            current_stage=PipelineStage.REMAINING_SCENES,
        )

        # Scan scene directories and determine status
        scenes_data = brief.get("scenes", [])
        for scene_brief in scenes_data:
            scene_num = scene_brief.get("scene_number", 0)
            scene_dir = get_scene_path(project_id, scene_num)

            # Determine scene status based on files
            has_image = (scene_dir / "image.png").exists()
            has_video = (scene_dir / "video.mp4").exists()

            if has_video:
                status = SceneStatus.APPROVED
            elif has_image:
                status = SceneStatus.AWAITING_APPROVAL
            else:
                status = SceneStatus.PENDING

            # Get reference type from brief
            ref_type = scene_brief.get("reference_type", "INDEPENDENT")

            scene_data = SceneData(
                scene_number=scene_num,
                project_id=project_id,
                description=scene_brief.get("visual_description", ""),
                image_prompt=scene_brief.get("image_prompt", ""),
                motion_prompt=scene_brief.get("video_prompt", ""),
                audio_prompt=scene_brief.get("voiceover", ""),
                status=status,
                reference_type=ref_type,
                is_primary_scene=(scene_num == 1),
                image_path=scene_dir / "image.png" if has_image else None,
                video_path=scene_dir / "video.mp4" if has_video else None,
            )
            project.scenes.append(scene_data)

        # Count statuses
        status_counts = {}
        for scene in project.scenes:
            s = str(scene.status)
            status_counts[s] = status_counts.get(s, 0) + 1

        logger.success(f"Loaded project {project_id} from disk:")
        logger.info(f"  Title: {project.title}")
        logger.info(f"  Scenes: {len(project.scenes)}")
        logger.info(f"  Status breakdown: {status_counts}")

        # Save to memory
        self._active_projects[project_id] = project

        return project

    async def save(self, project: ProjectData) -> None:
        """
        Save project state to database.

        Args:
            project: ProjectData to save
        """
        project.updated_at = datetime.now()

        # Convert to dict for JSON serialization
        project_dict = project.model_dump(mode='json')

        await state_manager.save_state(
            key=f"project:{project.project_id}",
            data=project_dict
        )

        # Keep in memory
        self._active_projects[project.project_id] = project

    async def update_status(
        self,
        project: ProjectData,
        status: ProjectStatus
    ) -> None:
        """Update project status and save"""
        project.status = status
        await self.save(project)
        logger.info(f"[{project.project_id}] Status: {status}")

    async def update_stage(
        self,
        project: ProjectData,
        stage: str,
        scene_number: Optional[int] = None
    ) -> None:
        """Update current pipeline stage and save"""
        project.current_stage = stage
        await self.save(project)
        logger.info(f"[{project.project_id}] Stage -> {stage}" +
                   (f" (scene {scene_number})" if scene_number else ""))

    async def mark_stage_complete(
        self,
        project: ProjectData,
        stage: str
    ) -> None:
        """Mark stage as successfully completed"""
        project.last_successful_stage = stage
        await self.save(project)
        logger.success(f"[{project.project_id}] Stage completed: {stage}")

    async def handle_error(
        self,
        project: ProjectData,
        stage: str,
        error: Exception,
        scene_number: Optional[int] = None,
        is_resumable: bool = True
    ) -> None:
        """Handle stage error and update project state"""
        error_message = str(error)

        project.status = ProjectStatus.PAUSED if is_resumable else ProjectStatus.FAILED
        project.last_error_stage = stage
        project.last_error_scene = scene_number
        project.last_error_message = error_message
        project.last_error_at = datetime.now()
        project.is_resumable = is_resumable
        project.error_message = error_message

        await self.save(project)
        logger.error(f"[{project.project_id}] Error at stage {stage}: {error_message}")

    def get_active_project(self, project_id: str) -> Optional[ProjectData]:
        """Get project from memory (no database lookup)"""
        return self._active_projects.get(project_id)

    def get_all_active_projects(self) -> Dict[str, ProjectData]:
        """Get all active projects in memory"""
        return self._active_projects.copy()


# Singleton instance
_manager: Optional[ProjectManager] = None


def get_project_manager() -> ProjectManager:
    """Get the global ProjectManager instance"""
    global _manager
    if _manager is None:
        _manager = ProjectManager()
    return _manager
