"""
Project Orchestrator - Головний координатор pipeline

Управляє повним життєвим циклом проекту:
1. Генерація сценарію через ContentBrain
2. Паралельна обробка сцен (до 5 одночасно)
3. Генерація зображень через VisualEngine
4. Валідація через ContentBrain
5. Генерація відео
6. Tracking прогресу в SQLite
"""

import asyncio
import uuid
from pathlib import Path
from typing import List, Optional, Dict
from datetime import datetime

from app.core.config import settings
from app.core.state_manager import state_manager
from app.core.errors import ScenarioRejectedError
from app.core.paths import get_scene_path
from app.utils.logger import logger
from app.utils import file_manager

from app.services.content_brain import ContentBrain
from app.services.visual_engine_web import create_visual_engine
from app.services.prompt_router import PromptRouter
from app.services.glaze_parser import save_project_brief

from app.api.schemas import (
    ProjectData,
    SceneData,
    ProjectStatus,
    SceneStatus,
    PipelineStage,
    PipelineEvent,
)

from app.modules.topaz_queue import (
    TopazQueue,
    TopazTask,
    TopazProgress,
    get_topaz_queue,
)

from config.timeouts import COOLDOWN, RETRY


class ProjectOrchestrator:
    """
    Головний координатор pipeline для автоматизації відео

    Workflow:
    1. create_project() - створює проект з topic
    2. start_pipeline() - запускає обробку
       ├─ generate_script() - ContentBrain (GEN1 + GEN2)
       └─ process_scenes() - обробка з PRIMARY selection flow:
           │
           ├─ STEP 1: PRIMARY Scene (Scene 1)
           │  ├─ Generate 4 candidates (no reference)
           │  ├─ Send to WebSocket for user selection
           │  ├─ Wait for user to select image
           │  └─ Generate video for PRIMARY
           │
           └─ STEP 2: Remaining Scenes (parallel)
              ├─ Generate image WITH reference from PRIMARY
              ├─ Validate image (AI)
              ├─ Generate video
              └─ Send to WebSocket for approval

    3. on_primary_image_selected() - callback коли user обрав PRIMARY image
    4. on_scene_approved() - callback після схвалення сцени
    5. on_scene_regenerate() - callback для регенерації

    State Management:
    - Весь стан зберігається в SQLite через state_manager
    - Можна відновити проект після збою
    - Tracking прогресу в реальному часі
    """

    def __init__(self):
        """Ініціалізація Orchestrator з усіма залежностями"""

        # AI модулі
        self.content_brain = ContentBrain()
        self.visual_engine = create_visual_engine()  # API або Web залежно від config

        # Topaz Queue (singleton)
        self.topaz_queue = get_topaz_queue()

        # Конфігурація
        self.concurrent_limit = settings.CONCURRENT_SCENES  # 5
        self.max_retries = settings.MAX_RETRIES  # 2

        # Runtime state
        self.active_projects: Dict[str, ProjectData] = {}
        self.semaphore = asyncio.Semaphore(self.concurrent_limit)

        # Поточний активний проект
        self.current_project_id: Optional[str] = None

        # WebSocket notifier (буде встановлено ззовні)
        self.notifier = None

        # Setup Topaz callbacks
        self._setup_topaz_callbacks()

        logger.info("ProjectOrchestrator initialized")
        logger.info(f"  Concurrent scenes limit: {self.concurrent_limit}")
        logger.info(f"  Max retries: {self.max_retries}")
        logger.info(f"  Topaz Queue ready")
        logger.info(f"  Visual Engine: {type(self.visual_engine).__name__}")

    # ========================================================================
    # VISUAL ENGINE LIFECYCLE
    # ========================================================================

    async def shutdown_visual_engine(self) -> None:
        """
        Закриває браузер HiggsFieldWebAdapter (якщо використовується).
        Викликати ТІЛЬКИ після апрува всіх анімацій в Telegram!
        """
        if hasattr(self.visual_engine, 'shutdown'):
            logger.info("Shutting down visual engine...")
            await self.visual_engine.shutdown()
            logger.success("Visual engine shutdown complete")

    async def force_shutdown_visual_engine(self) -> None:
        """Примусове закриття браузера (для error handling)"""
        if hasattr(self.visual_engine, 'force_shutdown'):
            await self.visual_engine.force_shutdown()

    def approve_visual_engine_shutdown(self) -> None:
        """
        Позначає що браузер можна закривати.
        Викликається з Telegram handler після апрува анімацій.
        """
        if hasattr(self.visual_engine, 'approve_shutdown'):
            self.visual_engine.approve_shutdown()

    async def _cleanup_forms_before_pipeline(self) -> None:
        """
        Очищує всі форми в HiggsField перед стартом pipeline.
        Гарантує чистий стан для нового проекту.
        """
        if hasattr(self.visual_engine, '_client') and self.visual_engine._client:
            try:
                logger.info("Clearing all forms before pipeline start...")
                await self.visual_engine._client.clear_all_forms()
                logger.success("Forms cleared successfully")
            except Exception as e:
                logger.warning(f"Failed to clear forms: {e}")
    
    async def _cleanup_forms_after_pipeline(self) -> None:
        """
        Очищує всі форми в HiggsField після завершення pipeline.
        Залишає чистий стан для наступного проекту.
        """
        if hasattr(self.visual_engine, '_client') and self.visual_engine._client:
            try:
                logger.info("Clearing all forms after pipeline...")
                await self.visual_engine._client.clear_all_forms()
                logger.success("Forms cleared after pipeline")
            except Exception as e:
                logger.warning(f"Failed to clear forms after pipeline: {e}")

    async def _ensure_browser_healthy(self) -> None:
        """
        Перевіряє та відновлює браузер якщо потрібно.
        Викликати перед кожною операцією генерації.
        """
        if not hasattr(self.visual_engine, 'is_browser_open'):
            return  # API клієнт, не потребує перевірки

        if not self.visual_engine.is_browser_open:
            logger.warning("Browser is not open, restarting...")
            try:
                # Спробувати force shutdown якщо щось зависло
                if hasattr(self.visual_engine, 'force_shutdown'):
                    await self.visual_engine.force_shutdown()

                # Перезапустити
                await self.visual_engine._ensure_browser_started()
                await asyncio.sleep(5)  # Дати час на ініціалізацію
                logger.success("Browser restarted successfully")

            except Exception as e:
                logger.error(f"Failed to restart browser: {e}")
                raise

    # ========================================================================
    # STAGE TRACKING & ERROR HANDLING
    # ========================================================================

    async def _update_stage(
        self,
        project: ProjectData,
        stage: str,
        scene_number: Optional[int] = None
    ):
        """
        Оновлює поточний етап pipeline (checkpoint).

        Args:
            project: ProjectData
            stage: Етап з PipelineStage
            scene_number: Номер сцени (якщо applicable)
        """
        project.current_stage = stage
        project.updated_at = datetime.now()
        await self._save_project_state(project)

        logger.info(f"[{project.project_id}] Stage -> {stage}" +
                   (f" (scene {scene_number})" if scene_number else ""))

    async def _mark_stage_complete(self, project: ProjectData, stage: str):
        """
        Позначає етап як успішно завершений.

        Args:
            project: ProjectData
            stage: Завершений етап
        """
        project.last_successful_stage = stage
        project.updated_at = datetime.now()
        await self._save_project_state(project)

        logger.success(f"[{project.project_id}] Stage completed: {stage}")

    async def _handle_stage_error(
        self,
        project: ProjectData,
        stage: str,
        error: Exception,
        scene_number: Optional[int] = None,
        is_resumable: bool = True
    ):
        """
        Обробляє помилку на етапі pipeline.
        Зберігає інформацію про помилку та надсилає Telegram notification.

        Args:
            project: ProjectData
            stage: Етап де сталася помилка
            error: Exception об'єкт
            scene_number: Номер сцени (якщо applicable)
            is_resumable: Чи можна продовжити після виправлення
        """
        error_message = str(error)

        # Оновлюємо проект
        project.status = ProjectStatus.PAUSED if is_resumable else ProjectStatus.FAILED
        project.last_error_stage = stage
        project.last_error_scene = scene_number
        project.last_error_message = error_message
        project.last_error_at = datetime.now()
        project.is_resumable = is_resumable
        project.error_message = error_message  # Legacy field

        await self._save_project_state(project)

        logger.error(f"[{project.project_id}] Error at stage {stage}: {error_message}")

        # TODO: Send WebSocket notification
        # if self.notifier:
        #     await self.notifier.send_error(project_id, stage, error_message)

    # ========================================================================
    # PROJECT LIFECYCLE
    # ========================================================================

    async def create_project(
        self,
        topic: str,
        num_scenes: int = 6,  # ALWAYS 6 per GEN1/GEN2 contract
        style: str = "educational",
        target_audience: str = "general"
    ) -> ProjectData:
        """
        Створює новий проект

        Args:
            topic: Тема відео
            num_scenes: Кількість сцен (1-20)
            style: Стиль відео
            target_audience: Цільова аудиторія

        Returns:
            ProjectData з унікальним ID
        """
        # ENFORCE 6 SCENES - GEN1/GEN2 contract requires exactly 6 scenes
        if num_scenes != 6:
            logger.warning(f"num_scenes={num_scenes} overridden to 6 (GEN1/GEN2 contract)")
            num_scenes = 6

        # Ensure database is initialized (safe to call multiple times)
        await state_manager.initialize()

        # Generate unique project ID
        project_id = f"proj_{uuid.uuid4().hex[:12]}"

        # Create project directory
        project_dir = Path("projects") / project_id
        project_dir.mkdir(parents=True, exist_ok=True)

        # Create project data
        project = ProjectData(
            project_id=project_id,
            topic=topic,
            num_scenes=num_scenes,
            style=style,
            target_audience=target_audience,
            total_scenes=num_scenes,
            project_dir=project_dir,
            concurrent_limit=self.concurrent_limit,
        )

        # Save to memory
        self.active_projects[project_id] = project

        # Save to database
        await self._save_project_state(project)

        logger.success(f"Project created: {project_id}")
        logger.info(f"  Topic: {topic}")
        logger.info(f"  Scenes: {num_scenes}")
        logger.info(f"  Directory: {project_dir}")

        return project

    async def load_project_from_disk(self, project_id: str) -> Optional[ProjectData]:
        """
        Завантажує проект з диску для resume.

        Читає project_brief.json та сканує scene директорії щоб визначити
        реальний статус кожної сцени.

        Args:
            project_id: ID проекту (напр. proj_623ddd05d766)

        Returns:
            ProjectData якщо проект знайдено, None якщо ні
        """
        import json

        project_dir = settings.PROJECTS_DIR / project_id

        if not project_dir.exists():
            logger.error(f"Project directory not found: {project_dir}")
            return None

        brief_path = project_dir / "project_brief.json"
        if not brief_path.exists():
            logger.error(f"project_brief.json not found: {brief_path}")
            return None

        logger.info(f"Loading project from disk: {project_id}")

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
            concurrent_limit=self.concurrent_limit,
        )

        # Scan scene directories and determine status
        scenes_data = brief.get("scenes", [])
        for scene_brief in scenes_data:
            scene_num = scene_brief.get("scene_number", 0)
            scene_dir = project_dir / f"scene_{scene_num}"

            # Determine scene status based on files
            has_image = (scene_dir / "image.png").exists()
            has_video = (scene_dir / "video.mp4").exists()

            if has_video:
                status = SceneStatus.APPROVED  # Has video = ready for post-processing
            elif has_image:
                status = SceneStatus.AWAITING_APPROVAL  # Has image, needs video
            else:
                status = SceneStatus.PENDING  # Nothing generated yet

            # Get reference type
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
        self.active_projects[project_id] = project
        self.current_project_id = project_id

        return project

    async def resume_from_disk(self, project_id: str) -> Optional[ProjectData]:
        """
        Відновлює pipeline з диску та продовжує виконання.

        Args:
            project_id: ID проекту

        Returns:
            ProjectData якщо успішно, None якщо помилка
        """
        # Load project from disk
        project = await self.load_project_from_disk(project_id)
        if not project:
            return None

        logger.info("=" * 70)
        logger.info(f"RESUMING PIPELINE: {project_id}")
        logger.info("=" * 70)

        # Determine what needs to be done
        pending_scenes = [s for s in project.scenes if s.status == SceneStatus.PENDING]
        awaiting_scenes = [s for s in project.scenes if s.status == SceneStatus.AWAITING_APPROVAL]
        approved_scenes = [s for s in project.scenes if s.status == SceneStatus.APPROVED]

        logger.info(f"  Pending (need image+video): {len(pending_scenes)}")
        logger.info(f"  Awaiting (need video): {len(awaiting_scenes)}")
        logger.info(f"  Approved (ready): {len(approved_scenes)}")

        # If all scenes approved - go to post-processing
        if len(approved_scenes) == len(project.scenes):
            logger.info("All scenes approved - starting post-processing")
            await self._run_post_processing(project)
            return project

        # Set PRIMARY reference if scene 1 is ready
        scene_1 = next((s for s in project.scenes if s.scene_number == 1), None)
        if scene_1 and scene_1.image_path and scene_1.image_path.exists():
            self.primary_reference_image = scene_1.image_path
            logger.info(f"PRIMARY reference set: {self.primary_reference_image}")

        # Update status and process scenes using existing method
        await self._update_project_status(project, ProjectStatus.PROCESSING_SCENES)
        await self._process_all_scenes(project)

        return project

    async def start_pipeline(self, project_id: str, auto_approve: bool = False) -> ProjectData:
        """
        Запускає повний pipeline для проекту з checkpoint/resume підтримкою.

        Workflow:
        1. Генерація сценарію (ContentBrain) - checkpoint: script_generation
        2. PRIMARY scene (4 candidates, user selection) - checkpoint: primary_*
        3. Remaining scenes processing - checkpoint: remaining_scenes
        4. Post-processing (voiceover, assembly, Topaz) - checkpoints: voiceover, assembly, topaz_*

        При помилці pipeline зупиняється (PAUSED) і чекає resume.
        При відхиленні сценарію - перезапускається з генерації нового скрипта.

        Args:
            project_id: ID проекту
            auto_approve: Якщо True - автоматично апрувить всі сцени і запускає post-processing

        Returns:
            Оновлений ProjectData
        """
        project = await self._get_project(project_id)

        # Встановлюємо поточний проект (для Telegram callbacks)
        self.current_project_id = project_id
        
        # ====================================================================
        # CLEANUP: Очищення промптів перед стартом
        # ====================================================================
        await self._cleanup_forms_before_pipeline()

        # Лічильник спроб (для логування)
        attempt = 0

        # ====================================================================
        # MAIN LOOP - перезапускається при відхиленні сценарію
        # ====================================================================
        while True:
            attempt += 1

            logger.info("=" * 70)
            logger.info(f"STARTING PIPELINE: {project_id} (attempt {attempt})")
            logger.info("=" * 70)

            # ====================================================================
            # STAGE 1: Script Generation
            # ====================================================================
            try:
                await self._update_stage(project, PipelineStage.SCRIPT_GENERATION)
                await self._update_project_status(project, ProjectStatus.GENERATING_SCRIPT)
                await self._generate_script(project)
                await self._mark_stage_complete(project, PipelineStage.SCRIPT_GENERATION)

            except Exception as e:
                await self._handle_stage_error(
                    project, PipelineStage.SCRIPT_GENERATION, e, is_resumable=True
                )
                return project  # Зупиняємо, чекаємо resume

            # ====================================================================
            # STAGE 2-3: Scene Processing (PRIMARY + Remaining)
            # ====================================================================
            try:
                await self._update_project_status(project, ProjectStatus.PROCESSING_SCENES)
                await self._process_all_scenes(project)

            except ScenarioRejectedError:
                # Користувач відхилив сценарій - перезапускаємо з нового скрипта
                logger.warning(f"[{project_id}] Restarting pipeline with new script (attempt {attempt + 1})...")

                # Очищаємо дані попереднього скрипта
                project.scenes = []
                project.title = None
                project.summary = None
                project.completed_scenes = 0
                project.total_scenes = 0
                project.status = ProjectStatus.CREATED
                project.current_stage = "created"
                project.error_message = None
                project.last_error_stage = None
                project.last_error_scene = None
                project.last_error_message = None
                await self._save_project_state(project)

                # TODO: Send WebSocket notification about restart
                logger.info(f"Scenario rejected. Generating new script... (attempt {attempt + 1})")

                # Перезапускаємо цикл
                continue

            except Exception as e:
                # Помилка буде оброблена всередині _process_all_scenes
                # з деталями про конкретну сцену
                if project.status != ProjectStatus.PAUSED:
                    await self._handle_stage_error(
                        project, PipelineStage.REMAINING_SCENES, e, is_resumable=True
                    )
                return project  # Зупиняємо, чекаємо resume

            # ====================================================================
            # Check if all scenes approved (may be awaiting user input)
            # ====================================================================
            all_approved = all(
                s.status == SceneStatus.APPROVED
                for s in project.scenes
            )

            if not all_approved:
                # AUTO-APPROVE MODE: Автоматично апрувить всі сцени та запускає post-processing
                if auto_approve:
                    logger.info(f"[{project_id}] AUTO-APPROVE MODE: Approving all scenes...")

                    for scene in project.scenes:
                        if scene.status == SceneStatus.AWAITING_APPROVAL:
                            scene.status = SceneStatus.APPROVED
                            scene.approved_at = datetime.now()
                            logger.success(f"[Scene {scene.scene_number}] Auto-approved")

                    await self._save_project_state(project)

                    # Запускаємо post-processing
                    logger.info(f"[{project_id}] All scenes auto-approved - starting post-processing...")
                    await self._run_post_processing(project)
                else:
                    logger.info(f"[{project_id}] Awaiting user approval for scenes")
                    # Pipeline буде продовжено через on_scene_approved callback
                    return project

            # ====================================================================
            # STAGE 4+: Post-processing (якщо всі сцени вже approved)
            # ====================================================================
            else:
                logger.info(f"[{project_id}] All scenes already approved - starting post-processing...")
                await self._run_post_processing(project)

            logger.info(f"[{project_id}] Pipeline completed!")
            await self._save_project_state(project)

            return project

    # ========================================================================
    # RESUME & CANCEL
    # ========================================================================

    async def resume_pipeline(self, project_id: str) -> ProjectData:
        """
        Продовжує pipeline з останнього checkpoint після помилки.

        Спочатку перевіряє чи проект в пам'яті, якщо ні — завантажує з диску.

        Args:
            project_id: ID проекту

        Returns:
            Оновлений ProjectData
        """
        # Try to get from memory first
        project = self.active_projects.get(project_id)

        # If not in memory, load from disk
        if not project:
            logger.info(f"Project {project_id} not in memory, loading from disk...")
            project = await self.load_project_from_disk(project_id)

            if not project:
                raise ValueError(f"Project {project_id} not found (neither in memory nor on disk)")

        # If still no project, error
        if not project:
            raise ValueError(f"Project {project_id} not found")

        # Встановлюємо поточний проект
        self.current_project_id = project_id

        # Збільшуємо лічильник resume
        project.resume_count += 1

        # Очищаємо помилку
        project.status = ProjectStatus.PROCESSING_SCENES
        project.last_error_message = None
        project.last_error_at = None

        await self._save_project_state(project)

        logger.info("=" * 70)
        logger.info(f"RESUMING PIPELINE: {project_id}")
        logger.info(f"  From stage: {project.current_stage}")
        logger.info(f"  Resume count: {project.resume_count}")
        logger.info("=" * 70)

        current_stage = project.current_stage

        # ====================================================================
        # Route to appropriate stage
        # ====================================================================

        if current_stage == PipelineStage.CREATED:
            # Початок - запускаємо з початку
            return await self.start_pipeline(project_id)

        elif current_stage == PipelineStage.SCRIPT_GENERATION:
            # Повторюємо генерацію скрипта
            try:
                await self._update_project_status(project, ProjectStatus.GENERATING_SCRIPT)
                await self._generate_script(project)
                await self._mark_stage_complete(project, PipelineStage.SCRIPT_GENERATION)

                # Продовжуємо до scenes
                await self._update_project_status(project, ProjectStatus.PROCESSING_SCENES)
                await self._process_all_scenes(project)

            except Exception as e:
                await self._handle_stage_error(
                    project, current_stage, e, is_resumable=True
                )
                return project

        elif current_stage in [
            PipelineStage.PRIMARY_CANDIDATES,
            PipelineStage.PRIMARY_SELECTION,
            PipelineStage.PRIMARY_VIDEO,
            PipelineStage.REMAINING_SCENES
        ]:
            # Продовжуємо обробку сцен
            try:
                await self._update_project_status(project, ProjectStatus.PROCESSING_SCENES)
                await self._process_all_scenes(project)

            except Exception as e:
                await self._handle_stage_error(
                    project, current_stage, e, is_resumable=True
                )
                return project

        elif current_stage == PipelineStage.VOICEOVER:
            # Продовжуємо з voiceover
            try:
                await self._run_post_processing(project)
            except Exception as e:
                await self._handle_stage_error(
                    project, current_stage, e, is_resumable=True
                )
                return project

        # v7.4: GEN3a - Video Analysis
        elif current_stage in [PipelineStage.VIDEO_ANALYSIS, PipelineStage.VAL_VIDEO_ANALYSIS]:
            try:
                await self._run_gen3a_analysis(project)
            except Exception as e:
                await self._handle_stage_error(
                    project, current_stage, e, is_resumable=True
                )
                return project

        # v7.4: GEN3b - Manifest Generation
        elif current_stage in [PipelineStage.MANIFEST_GENERATION, PipelineStage.VAL_MANIFEST]:
            try:
                await self._run_gen3b_manifest(project)
            except Exception as e:
                await self._handle_stage_error(
                    project, current_stage, e, is_resumable=True
                )
                return project

        # v7.4: Manifest Rendering
        elif current_stage == PipelineStage.RENDER:
            try:
                await self._run_manifest_render(project)
            except Exception as e:
                await self._handle_stage_error(
                    project, current_stage, e, is_resumable=True
                )
                return project

        elif current_stage == PipelineStage.ASSEMBLY:
            # Продовжуємо з assembly (skip voiceover) - legacy
            try:
                await self._run_post_processing(project, skip_voiceover=True)
            except Exception as e:
                await self._handle_stage_error(
                    project, current_stage, e, is_resumable=True
                )
                return project

        elif current_stage in [PipelineStage.TOPAZ_FPS, PipelineStage.TOPAZ_UPSCALE]:
            # Topaz processing - потрібно перезапустити Topaz task
            try:
                # Re-add to Topaz queue
                final_video_path = project.project_dir / "final.mp4"
                if final_video_path.exists():
                    await self._add_to_topaz_queue(project, final_video_path)
                else:
                    raise FileNotFoundError(f"Final video not found: {final_video_path}")

            except Exception as e:
                await self._handle_stage_error(
                    project, current_stage, e, is_resumable=True
                )
                return project

        elif current_stage == PipelineStage.COMPLETED:
            # Вже завершено
            logger.info(f"[{project_id}] Project already completed")
            project.status = ProjectStatus.COMPLETED
            await self._save_project_state(project)

        else:
            logger.warning(f"[{project_id}] Unknown stage: {current_stage}")
            # Спробуємо з початку
            return await self.start_pipeline(project_id)

        return project

    async def cancel_project(self, project_id: str) -> ProjectData:
        """
        Скасовує проект.

        Args:
            project_id: ID проекту

        Returns:
            Оновлений ProjectData
        """
        project = await self._get_project(project_id)

        project.status = ProjectStatus.FAILED
        project.error_message = "Cancelled by user"
        project.is_resumable = False
        project.updated_at = datetime.now()

        await self._save_project_state(project)

        logger.info(f"[{project_id}] Project cancelled by user")

        return project

    async def _add_to_topaz_queue(self, project: ProjectData, video_path: Path):
        """Додає відео до Topaz queue"""
        # Ensure Topaz queue is running
        if not self.topaz_queue.is_running:
            await self.topaz_queue.start()

        # Add to queue
        task = await self.topaz_queue.add_task(
            project_id=project.project_id,
            scene_number=0,  # 0 = final video
            input_path=video_path,
            output_dir=project.project_dir,
            metadata={
                "type": "final_video",
                "total_scenes": len(project.scenes),
            }
        )

        logger.info(f"[{project.project_id}] Added to Topaz queue: {task.task_id}")

    # ========================================================================
    # SCRIPT GENERATION
    # ========================================================================

    async def _generate_script(self, project: ProjectData):
        """Генерує сценарій через PromptRouter (GEN1 + GEN2)"""

        logger.info(f"[{project.project_id}] Generating script via PromptRouter...")

        try:
            # Use PromptRouter for two-stage generation (GEN1 + GEN2)
            router = PromptRouter()
            glaze_project = await router.generate_full_project(
                topic=project.topic,
                num_scenes=project.num_scenes,
                style=project.style or "cinematic food fantasy",
                target_audience=project.target_audience or "YouTube Shorts viewers",
                project_id=project.project_id,
            )

            if not glaze_project:
                raise Exception("PromptRouter returned empty output")

            # Update project with script data
            project.title = glaze_project.property.name
            project.summary = glaze_project.youtube.description[:500] if glaze_project.youtube.description else ""
            project.tags = glaze_project.youtube.tags or []

            # Convert GlazeScene to SceneData
            for glaze_scene in glaze_project.scenes:
                # reference_type comes directly from GEN2
                ref_type = glaze_scene.reference_type

                # Scene 1 should always be PRIMARY
                if glaze_scene.scene_number == 1 and ref_type != "PRIMARY":
                    ref_type = "PRIMARY"

                scene_data = SceneData(
                    scene_number=glaze_scene.scene_number,
                    project_id=project.project_id,
                    description=glaze_scene.visual_description,
                    key_elements=[],  # Can extract from visual_description if needed
                    mood=glaze_scene.scene_name,  # Use scene_name as mood indicator
                    image_prompt=glaze_scene.image_prompt,  # Direct from GEN2
                    motion_prompt=glaze_scene.video_prompt,  # Direct from GEN2
                    audio_prompt=glaze_scene.voiceover,
                    status=SceneStatus.PENDING,
                    reference_type=ref_type,
                    is_primary_scene=(glaze_scene.scene_number == 1),
                )
                project.scenes.append(scene_data)

            logger.success(f"[{project.project_id}] Script generated: {project.title}")
            logger.info(f"  Scenes: {len(project.scenes)}")
            logger.info(f"  Reference types: {[s.reference_type for s in project.scenes]}")

            # Save project_brief.json for post-processing (voiceover, assembly)
            project_dir = settings.PROJECTS_DIR / project.project_id
            project_dir.mkdir(parents=True, exist_ok=True)
            save_project_brief(glaze_project, project_dir)
            logger.info(f"[{project.project_id}] Saved project_brief.json")

            await self._save_project_state(project)

        except Exception as e:
            logger.error(f"[{project.project_id}] Script generation failed: {e}")
            raise

    # ========================================================================
    # SCENE PROCESSING
    # ========================================================================

    async def _process_all_scenes(self, project: ProjectData):
        """
        Обробляє всі сцени у дві фази:

        ФАЗА 1: Генерація ЗОБРАЖЕНЬ для всіх 6 сцен
        1. PRIMARY (Scene 1) -> 4 кандидати -> Telegram -> User selection
        2. Решта сцен (2-6) -> генерація зображень з референсом

        ФАЗА 2: Генерація ВІДЕО для всіх 6 сцен (паралельно)
        3. Всі 6 відео запускаються в чергу на одній сторінці
        4. Чекаємо поки всі відео згенеруються
        5. Завантажуємо всі відео
        """

        logger.info(f"[{project.project_id}] Processing {len(project.scenes)} scenes...")

        if not project.scenes:
            logger.warning(f"[{project.project_id}] No scenes to process!")
            return

        primary_scene = project.scenes[0]  # Scene 1 is always PRIMARY

        # ==================================================================
        # ФАЗА 1: ГЕНЕРАЦІЯ ЗОБРАЖЕНЬ ДЛЯ ВСІХ СЦЕН
        # ==================================================================
        logger.info("=" * 70)
        logger.info("PHASE 1: GENERATING IMAGES FOR ALL SCENES")
        logger.info("=" * 70)

        # --- STEP 1.1: PRIMARY scene (4 candidates) ---
        # Check if PRIMARY image already exists on disk (resume case)
        primary_scene_dir = settings.get_scene_dir(project.project_id, 1)
        primary_image_exists = (primary_scene_dir / "image.png").exists()

        if primary_image_exists and primary_scene.status not in [SceneStatus.APPROVED, SceneStatus.AWAITING_APPROVAL, SceneStatus.VIDEO_READY, SceneStatus.IMAGE_READY]:
            logger.info(f"[Scene 1] PRIMARY image found on disk, updating status...")
            primary_scene.status = SceneStatus.IMAGE_READY
            primary_scene.image_path = str(primary_scene_dir / "image.png")
            primary_scene.validation_approved = True
            await self._save_project_state(project)

        if primary_scene.status not in [SceneStatus.APPROVED, SceneStatus.AWAITING_APPROVAL, SceneStatus.VIDEO_READY, SceneStatus.IMAGE_READY]:
            logger.info("=" * 60)
            logger.info(f"[Scene 1] Generating PRIMARY candidates...")
            logger.info("=" * 60)

            await self._update_stage(project, PipelineStage.PRIMARY_CANDIDATES, scene_number=1)

            try:
                primary_candidates = await self._generate_primary_candidates(project, primary_scene)
            except Exception as e:
                await self._handle_stage_error(
                    project, PipelineStage.PRIMARY_CANDIDATES, e, scene_number=1, is_resumable=True
                )
                raise

            if not primary_candidates:
                error = Exception("Failed to generate PRIMARY candidates - no images returned")
                await self._handle_stage_error(
                    project, PipelineStage.PRIMARY_CANDIDATES, error, scene_number=1, is_resumable=True
                )
                raise error

            await self._mark_stage_complete(project, PipelineStage.PRIMARY_CANDIDATES)

            # --- STEP 1.2: User selection ---
            await self._update_stage(project, PipelineStage.PRIMARY_SELECTION, scene_number=1)

            self._primary_selection_event = asyncio.Event()
            self._scenario_rejected = False

            # TODO: Replace with WebSocket notification for user selection
            # For now, auto-select first candidate
            logger.info(f"[Scene 1] Auto-selecting first candidate (WebSocket not implemented yet)")
            await self._auto_select_primary(project, primary_scene, primary_candidates)

            await self._mark_stage_complete(project, PipelineStage.PRIMARY_SELECTION)

            primary_scene.validation_approved = True
            primary_scene.status = SceneStatus.IMAGE_READY
            await self._save_project_state(project)

        # --- STEP 1.3: Generate images for remaining scenes (2-6) in ONE BATCH ---
        if len(project.scenes) > 1:
            await self._update_stage(project, PipelineStage.REMAINING_SCENES)

            logger.info("=" * 60)
            logger.info(f"Generating IMAGES for scenes 2-{len(project.scenes)} in SINGLE BATCH...")
            logger.info("=" * 60)

            # Get reference from PRIMARY
            reference_image = primary_scene.image_path
            if reference_image:
                logger.info(f"Using PRIMARY reference: {Path(reference_image).name}")

            # Collect ALL scenes that need generation (both INDEPENDENT and REQUIRES_REF)
            scenes_to_generate = []

            for scene in project.scenes[1:]:
                # Skip if already has image (check both status AND file on disk)
                if scene.status in [SceneStatus.IMAGE_READY, SceneStatus.VIDEO_READY, SceneStatus.APPROVED, SceneStatus.AWAITING_APPROVAL]:
                    logger.info(f"[Scene {scene.scene_number}] Image already exists (status: {scene.status}), skipping...")
                    continue
                # Also check if image file exists on disk (resume case)
                scene_dir = settings.get_scene_dir(project.project_id, scene.scene_number)
                if (scene_dir / "image.png").exists():
                    logger.info(f"[Scene {scene.scene_number}] Image file found on disk, skipping generation...")
                    scene.status = SceneStatus.AWAITING_APPROVAL
                    scene.image_path = str(scene_dir / "image.png")
                    continue
                scenes_to_generate.append(scene)

            if scenes_to_generate:
                logger.info(f"Generating {len(scenes_to_generate)} scenes in ONE PARALLEL BATCH...")
                logger.info(f"  Reference: {Path(reference_image).name if reference_image else 'None'}")

                # Prepare scenes data for parallel generation
                scenes_data = []
                for scene in scenes_to_generate:
                    scenes_data.append({
                        'scene_number': scene.scene_number,
                        'image_prompt': scene.image_prompt,
                        'reference_type': scene.reference_type
                    })
                    logger.info(f"  Scene {scene.scene_number}: {scene.reference_type}")

                try:
                    # Use parallel image generation (ONE batch for all scenes)
                    # Reference is uploaded ONCE at start and used for all scenes
                    image_paths = await self.visual_engine.generate_all_images_parallel(
                        scenes=scenes_data,
                        project_id=project.project_id,
                        reference_image=Path(reference_image) if reference_image else None
                    )

                    # Assign paths to scenes (in order)
                    for i, path in enumerate(image_paths):
                        if i < len(scenes_to_generate):
                            scene = scenes_to_generate[i]
                            scene.image_path = path
                            scene.status = SceneStatus.IMAGE_READY
                            logger.success(f"[Scene {scene.scene_number}] Image generated!")

                except Exception as e:
                    logger.error(f"Parallel image generation failed: {e}")
                    for scene in scenes_to_generate:
                        scene.status = SceneStatus.FAILED
                        scene.error_message = str(e)

                await self._save_project_state(project)

        # ==================================================================
        # ФАЗА 1.5: ВАЛІДАЦІЯ ЗОБРАЖЕНЬ (VAL_IMG)
        # ==================================================================
        logger.info("=" * 70)
        logger.info("PHASE 1.5: VALIDATING GENERATED IMAGES (VAL_IMG)")
        logger.info("=" * 70)

        # Validate all generated images (scenes 2-6)
        # Scene 1 is validated by human via Telegram, so we skip it
        max_validation_retries = 5

        for scene in project.scenes[1:]:  # Skip scene 1 (PRIMARY - validated by human)
            # Skip scenes that are already validated or further in pipeline
            if scene.status in [SceneStatus.VIDEO_READY, SceneStatus.APPROVED]:
                logger.info(f"[Scene {scene.scene_number}] Already validated/approved, skipping...")
                continue

            # For VALIDATION_FAILED status (resume case) - reset and retry
            if scene.status == SceneStatus.VALIDATION_FAILED:
                logger.info(f"[Scene {scene.scene_number}] RESUME: Retrying validation after previous failure...")
                scene.status = SceneStatus.IMAGE_READY  # Reset status to retry

            if scene.status != SceneStatus.IMAGE_READY:
                logger.info(f"[Scene {scene.scene_number}] Status is {scene.status}, skipping validation...")
                continue

            if not scene.image_path or not Path(scene.image_path).exists():
                logger.warning(f"[Scene {scene.scene_number}] No image to validate, skipping...")
                continue

            logger.info(f"[Scene {scene.scene_number}] Validating image...")
            validation_passed = False

            current_image_path = scene.image_path  # Track current image for comparison

            for attempt in range(1, max_validation_retries + 1):
                try:
                    logger.info(f"[Scene {scene.scene_number}] Validation attempt {attempt}/{max_validation_retries}")
                    logger.info(f"[Scene {scene.scene_number}] Image path: {scene.image_path}")

                    validation_result = await self.content_brain.validate_image(
                        image_path=Path(scene.image_path) if isinstance(scene.image_path, str) else scene.image_path,
                        expected_prompt=scene.image_prompt,
                        scene_number=scene.scene_number,
                        scene_description=scene.description,
                        scene_mood=scene.mood,
                        key_elements=scene.key_elements
                    )

                    scene.validation_approved = validation_result.approved
                    scene.validation_score = validation_result.quality_score
                    scene.validation_feedback = validation_result.feedback

                    if validation_result.approved:
                        logger.success(f"[Scene {scene.scene_number}] Image APPROVED (score: {validation_result.quality_score:.0f}%)")
                        validation_passed = True
                        break  # Exit retry loop
                    else:
                        logger.warning(f"[Scene {scene.scene_number}] Image REJECTED (attempt {attempt}/{max_validation_retries})")
                        logger.warning(f"  Score: {validation_result.quality_score:.0f}%")
                        logger.warning(f"  Feedback: {validation_result.feedback}")

                        if attempt < max_validation_retries:
                            # Regenerate the image with same prompt
                            logger.info(f"[Scene {scene.scene_number}] Starting regeneration...")
                            scene.retry_count += 1

                            regeneration_success = False
                            try:
                                # Use single image generation with reference
                                # Pass reference only for REQUIRES_REF/LOOP_CLOSE
                                ref_image = None
                                if scene.reference_type in ['REQUIRES_REF', 'LOOP_CLOSE']:
                                    ref_image = Path(primary_scene.image_path) if primary_scene.image_path else None

                                new_image = await self.visual_engine.generate_scene_image(
                                    prompt=scene.image_prompt,
                                    scene_number=scene.scene_number,
                                    project_id=project.project_id,
                                    reference_image=ref_image,
                                    reference_type=scene.reference_type
                                )
                                scene.image_path = str(new_image)
                                regeneration_success = True
                                logger.success(f"[Scene {scene.scene_number}] New image generated: {new_image}")
                            except Exception as e:
                                logger.error(f"[Scene {scene.scene_number}] Regeneration FAILED: {e}")
                                regeneration_success = False

                            if not regeneration_success:
                                logger.error(f"[Scene {scene.scene_number}] Cannot continue validation - regeneration failed")
                                # Don't validate the same image again - break the loop
                                break

                            # Save state after each regeneration
                            await self._save_project_state(project)

                except Exception as e:
                    logger.error(f"[Scene {scene.scene_number}] Validation error: {e}")
                    # Save error as feedback so it's visible in final status
                    scene.validation_feedback = f"Validation error: {str(e)}"
                    scene.validation_approved = False
                    # Continue to next attempt only if it's a validation error, not regeneration

            await self._save_project_state(project)

            # If all 5 attempts failed - PAUSE pipeline and notify Telegram
            if not validation_passed:
                logger.error(f"[Scene {scene.scene_number}] VALIDATION FAILED after {max_validation_retries} attempts!")
                scene.status = SceneStatus.VALIDATION_FAILED

                error_msg = (
                    f"Image validation failed for Scene {scene.scene_number} "
                    f"after {max_validation_retries} regeneration attempts.\n"
                    f"Last feedback: {scene.validation_feedback}"
                )

                await self._handle_stage_error(
                    project=project,
                    stage=PipelineStage.REMAINING_SCENES,
                    error=Exception(error_msg),
                    scene_number=scene.scene_number,
                    is_resumable=True
                )

                # TODO: Send WebSocket notification about validation failure
                score_str = f"{scene.validation_score:.0f}%" if scene.validation_score is not None else "N/A"
                logger.error(
                    f"Image Validation Failed - Scene: {scene.scene_number}, "
                    f"Attempts: {max_validation_retries}, Score: {score_str}"
                )

                return  # Stop pipeline, wait for resume

        logger.info("Image validation complete - all images approved")

        # ==================================================================
        # ФАЗА 2: ГЕНЕРАЦІЯ ВІДЕО ДЛЯ ВСІХ СЦЕН (ПАРАЛЕЛЬНО)
        # ==================================================================
        logger.info("=" * 70)
        logger.info("PHASE 2: GENERATING VIDEOS FOR ALL SCENES (PARALLEL)")
        logger.info("=" * 70)

        await self._update_stage(project, PipelineStage.PRIMARY_VIDEO)

        # Prepare scenes data for parallel video generation
        scenes_for_video = []
        for scene in project.scenes:
            # Skip if status indicates video ready
            if scene.status in [SceneStatus.VIDEO_READY, SceneStatus.APPROVED]:
                logger.info(f"[Scene {scene.scene_number}] Video already exists (status: {scene.status}), skipping...")
                continue

            # Also check if video file exists on disk (resume case)
            scene_dir = get_scene_path(project.project_id, scene.scene_number)
            video_path = scene_dir / "video.mp4"
            if video_path.exists():
                logger.info(f"[Scene {scene.scene_number}] Video file found on disk, skipping...")
                scene.video_path = str(video_path)
                scene.status = SceneStatus.VIDEO_READY
                continue

            if not scene.image_path or not Path(scene.image_path).exists():
                logger.warning(f"[Scene {scene.scene_number}] No image, skipping video...")
                continue

            # Try to load image_url from metadata.json if not in scene object
            image_url = getattr(scene, 'image_url', None)
            if not image_url:
                # Load from metadata.json
                metadata_path = get_scene_path(project.project_id, scene.scene_number) / "metadata.json"
                if metadata_path.exists():
                    try:
                        import json
                        with open(metadata_path, 'r', encoding='utf-8') as f:
                            metadata = json.load(f)
                            image_url = metadata.get('image_url')
                            if image_url:
                                logger.info(f"[Scene {scene.scene_number}] Loaded image_url from metadata")
                    except Exception as e:
                        logger.debug(f"[Scene {scene.scene_number}] Could not load metadata: {e}")

            scenes_for_video.append({
                'scene_number': scene.scene_number,
                'image_path': scene.image_path,
                'video_prompt': scene.motion_prompt or scene.image_prompt,
                'image_url': image_url  # For FAST video mode
            })

        if scenes_for_video:
            logger.info(f"Queueing {len(scenes_for_video)} videos for parallel generation...")

            try:
                # Use the new parallel video generation method
                video_paths = await self.visual_engine.generate_all_videos_parallel(
                    scenes=scenes_for_video,
                    project_id=project.project_id
                )

                # Assign video paths to scenes
                for i, video_path in enumerate(video_paths):
                    if i < len(scenes_for_video):
                        scene_num = scenes_for_video[i]['scene_number']
                        scene = project.scenes[scene_num - 1]
                        scene.video_path = str(video_path)
                        scene.status = SceneStatus.VIDEO_READY
                        logger.success(f"[Scene {scene_num}] Video ready: {video_path.name}")

            except Exception as e:
                logger.error(f"Parallel video generation failed: {e}")
                raise

        await self._mark_stage_complete(project, PipelineStage.PRIMARY_VIDEO)

        # ==================================================================
        # ФАЗА 3: ВІДПРАВКА НА APPROVAL
        # ==================================================================
        logger.info("=" * 70)
        logger.info("PHASE 3: SENDING FOR APPROVAL")
        logger.info("=" * 70)

        for scene in project.scenes:
            if scene.status == SceneStatus.VIDEO_READY:
                scene.status = SceneStatus.AWAITING_APPROVAL
                # TODO: Send WebSocket notification for approval
                logger.info(f"[Scene {scene.scene_number}] Ready for approval")

        await self._save_project_state(project)

        logger.info(f"[{project.project_id}] All scenes processed!")
        logger.info(f"  Total: {len(project.scenes)}")
        logger.info(f"  With video: {len([s for s in project.scenes if s.video_path])}")

        await self._save_project_state(project)

    async def _generate_primary_candidates(
        self,
        project: ProjectData,
        scene: SceneData
    ) -> List[Path]:
        """Генерує 4 кандидати для PRIMARY сцени"""

        scene.status = SceneStatus.GENERATING_IMAGE
        await self._save_project_state(project)

        try:
            candidates = await self.visual_engine.generate_primary_scene_candidates(
                prompt=scene.image_prompt,
                scene_number=scene.scene_number,
                project_id=project.project_id,
                num_candidates=4
            )
            logger.success(f"[Scene {scene.scene_number}] Generated {len(candidates)} candidates")
            return candidates
        except Exception as e:
            logger.error(f"[Scene {scene.scene_number}] Failed to generate candidates: {e}")
            scene.status = SceneStatus.FAILED
            scene.error_message = str(e)
            await self._save_project_state(project)
            return []

    async def _auto_select_primary(
        self,
        project: ProjectData,
        scene: SceneData,
        candidates: List[Path]
    ):
        """Автоматично обирає перший кандидат (для тестів без Telegram)"""
        import shutil

        if not candidates:
            return

        scene_dir = settings.get_scene_dir(project.project_id, scene.scene_number)

        # Copy first candidate as main image
        selected_path = scene_dir / "image.png"
        shutil.copy(candidates[0], selected_path)
        scene.image_path = selected_path

        # Copy metadata
        candidate_metadata_path = scene_dir / "candidate_1_metadata.json"
        if candidate_metadata_path.exists():
            import json
            with open(candidate_metadata_path, 'r', encoding='utf-8') as f:
                candidate_meta = json.load(f)

            main_metadata = {
                "request_id": candidate_meta.get("request_id"),
                "image_url": candidate_meta.get("image_url"),
                "prompt": scene.image_prompt,
                "scene_number": scene.scene_number,
                "project_id": project.project_id,
                "generation_mode": "standard",
                "selected_by_human": False,
                "selected_candidate": 1,
            }
            await file_manager.save_json(main_metadata, scene_dir / "metadata.json")

        logger.info(f"[Scene {scene.scene_number}] Auto-selected candidate 1")

    async def _process_scene_with_reference(
        self,
        project: ProjectData,
        scene: SceneData,
        reference_url: Optional[str]
    ):
        """
        Обробляє сцену з референсом від PRIMARY.
        Використовується для REQUIRES_REF та LOOP_CLOSE сцен.
        """

        async with self.semaphore:
            logger.info(f"[Scene {scene.scene_number}] Processing with reference...")

            try:
                # Health check before generation
                await self._ensure_browser_healthy()

                # STEP 1: Generate image (з референсом якщо є)
                await self._generate_image_with_reference(project, scene, reference_url)

                # Cooldown after image generation
                logger.debug(f"[Scene {scene.scene_number}] Cooldown {COOLDOWN.BETWEEN_IMAGES}s after image...")
                await asyncio.sleep(COOLDOWN.BETWEEN_IMAGES)

                # STEP 2: Validate image
                await self._validate_scene_image(project, scene)

                # STEP 3: Generate video
                await self._generate_video_for_scene(project, scene)

                # Cooldown after video generation
                logger.debug(f"[Scene {scene.scene_number}] Cooldown {COOLDOWN.BETWEEN_VIDEOS}s after video...")
                await asyncio.sleep(COOLDOWN.BETWEEN_VIDEOS)

                # STEP 4: Mark as awaiting approval
                scene.status = SceneStatus.AWAITING_APPROVAL
                await self._save_project_state(project)

                # TODO: Send WebSocket notification for approval
                # For now, auto-approve
                logger.info(f"[Scene {scene.scene_number}] Auto-approving (WebSocket not implemented)")
                await self.on_scene_approved(scene.scene_number)

                logger.success(f"[Scene {scene.scene_number}] Processing completed")

            except Exception as e:
                logger.error(f"[Scene {scene.scene_number}] Processing failed: {e}")
                scene.status = SceneStatus.FAILED
                scene.error_message = str(e)
                await self._save_project_state(project)
                raise

    async def _generate_image_with_reference(
        self,
        project: ProjectData,
        scene: SceneData,
        reference_url: Optional[str]
    ):
        """Генерує зображення для сцени (з референсом тільки для REQUIRES_REF/LOOP_CLOSE)"""

        scene.status = SceneStatus.GENERATING_IMAGE
        await self._save_project_state(project)

        # Визначаємо чи потрібен референс для цієї сцени
        needs_reference = scene.reference_type in ("REQUIRES_REF", "LOOP_CLOSE")
        use_reference = reference_url and needs_reference

        logger.info(f"[Scene {scene.scene_number}] Generating image...")
        logger.info(f"  reference_type: {scene.reference_type}")
        logger.info(f"  use_reference: {use_reference}")

        try:
            if use_reference:
                # Generate with reference (REQUIRES_REF/LOOP_CLOSE - exteriors, drone shots, etc.)
                logger.info(f"[Scene {scene.scene_number}] Using reference from PRIMARY scene")
                image_path = await self.visual_engine.generate_image_with_reference(
                    prompt=scene.image_prompt,
                    reference_image_url=reference_url,
                    scene_number=scene.scene_number,
                    project_id=project.project_id
                )
            else:
                # Generate without reference (INDEPENDENT - interiors, details, etc.)
                logger.info(f"[Scene {scene.scene_number}] Generating without reference (INDEPENDENT)")
                image_path = await self.visual_engine.generate_image(
                    prompt=scene.image_prompt,
                    scene_number=scene.scene_number,
                    project_id=project.project_id
                )

            scene.image_path = image_path
            logger.success(f"[Scene {scene.scene_number}] Image generated: {image_path}")

            await self._save_project_state(project)

        except Exception as e:
            logger.error(f"[Scene {scene.scene_number}] Image generation failed: {e}")
            raise

    async def _generate_scene_image_only(
        self,
        project: ProjectData,
        scene: SceneData,
        reference_image: Optional[Path]
    ):
        """
        Генерує ТІЛЬКИ зображення для сцени (без відео).

        Args:
            project: Проект
            scene: Сцена
            reference_image: Шлях до референсного зображення (або None)
        """
        scene.status = SceneStatus.GENERATING_IMAGE
        await self._save_project_state(project)

        logger.info(f"[Scene {scene.scene_number}] Generating image...")
        logger.info(f"  Type: {scene.reference_type}")
        logger.info(f"  Reference: {reference_image.name if reference_image else 'None'}")

        try:
            # Use visual_engine's generate_scene_image method
            image_path = await self.visual_engine.generate_scene_image(
                prompt=scene.image_prompt,
                scene_number=scene.scene_number,
                project_id=project.project_id,
                reference_image=reference_image,
                reference_type=scene.reference_type
            )

            scene.image_path = str(image_path)
            logger.success(f"[Scene {scene.scene_number}] Image: {image_path.name}")
            await self._save_project_state(project)

        except Exception as e:
            logger.error(f"[Scene {scene.scene_number}] Image generation failed: {e}")
            raise

    async def _process_scene(self, project: ProjectData, scene: SceneData):
        """
        Обробляє одну сцену повністю

        Workflow:
        1. Generate image (VisualEngine)
        2. Validate image (ContentBrain Vision)
        3. Generate video (VisualEngine)
        4. Await approval (mock в тестах)
        """

        async with self.semaphore:  # Limit concurrency
            logger.info(f"[Scene {scene.scene_number}] Starting processing...")

            try:
                # STEP 1: Generate image
                await self._generate_image_for_scene(project, scene)

                # STEP 2: Validate image
                await self._validate_scene_image(project, scene)

                # STEP 3: Generate video
                await self._generate_video_for_scene(project, scene)

                # STEP 4: Mark as awaiting approval
                scene.status = SceneStatus.AWAITING_APPROVAL
                await self._save_project_state(project)

                # TODO: Send WebSocket notification for approval
                # For now, auto-approve
                logger.info(f"[Scene {scene.scene_number}] Auto-approving (WebSocket not implemented)")
                await self.on_scene_approved(scene.scene_number)

                logger.success(f"[Scene {scene.scene_number}] Processing completed")

            except Exception as e:
                logger.error(f"[Scene {scene.scene_number}] Processing failed: {e}")
                scene.status = SceneStatus.FAILED
                scene.error_message = str(e)
                await self._save_project_state(project)
                raise

    async def _generate_image_for_scene(self, project: ProjectData, scene: SceneData):
        """Генерує зображення для сцени"""

        scene.status = SceneStatus.GENERATING_IMAGE
        await self._save_project_state(project)

        logger.info(f"[Scene {scene.scene_number}] Generating image...")

        try:
            image_path = await self.visual_engine.generate_image(
                prompt=scene.image_prompt,
                scene_number=scene.scene_number,
                project_id=project.project_id
            )

            scene.image_path = image_path
            logger.success(f"[Scene {scene.scene_number}] Image generated: {image_path}")

            await self._save_project_state(project)

        except Exception as e:
            logger.error(f"[Scene {scene.scene_number}] Image generation failed: {e}")
            raise

    async def _validate_scene_image(self, project: ProjectData, scene: SceneData):
        """
        Валідує згенероване зображення через ContentBrain Vision.

        Якщо валідація не пройшла - перегенеровує зображення (до 2 спроб).
        Якщо обидві спроби невдалі - відправляє повідомлення в Telegram.
        """
        max_attempts = 2  # Максимум 2 спроби генерації

        for attempt in range(1, max_attempts + 1):
            scene.status = SceneStatus.VALIDATING
            await self._save_project_state(project)

            logger.info(f"[Scene {scene.scene_number}] Validating image (attempt {attempt}/{max_attempts})...")

            try:
                # Передаємо повний контекст сцени для валідації
                validation_result = await self.content_brain.validate_image(
                    image_path=scene.image_path,
                    expected_prompt=scene.image_prompt,
                    scene_number=scene.scene_number,
                    scene_description=scene.description,
                    scene_mood=scene.mood,
                    key_elements=scene.key_elements
                )

                # Update scene with validation results
                scene.validation_approved = validation_result.approved
                scene.validation_score = validation_result.quality_score
                scene.validation_feedback = validation_result.feedback

                if validation_result.approved:
                    logger.success(f"[Scene {scene.scene_number}] Image APPROVED (attempt {attempt})")
                    await self._save_project_state(project)
                    return  # Успіх - виходимо
                else:
                    logger.warning(f"[Scene {scene.scene_number}] Image REJECTED (attempt {attempt})")
                    logger.warning(f"  Feedback: {validation_result.feedback}")
                    for issue in validation_result.issues:
                        logger.warning(f"  - {issue}")

                    # Якщо є ще спроби - перегенеровуємо
                    if attempt < max_attempts:
                        logger.info(f"[Scene {scene.scene_number}] Regenerating image with same prompt...")
                        scene.retry_count += 1
                        await self._generate_image_for_scene(project, scene)
                    else:
                        # Обидві спроби невдалі - повідомляємо в Telegram
                        logger.error(f"[Scene {scene.scene_number}] All {max_attempts} attempts failed validation")
                        scene.validation_approved = False
                        scene.status = SceneStatus.VALIDATION_FAILED
                        await self._save_project_state(project)

                        # Відправляємо в Telegram для ручного вибору
                        await self._notify_validation_failed(project, scene, validation_result)
                        return

            except Exception as e:
                logger.error(f"[Scene {scene.scene_number}] Image validation failed: {e}")
                if attempt == max_attempts:
                    raise
                # Продовжуємо до наступної спроби

    async def _notify_validation_failed(
        self,
        project: ProjectData,
        scene: SceneData,
        validation_result
    ):
        """
        Відправляє повідомлення в Telegram про невдалу валідацію.
        Користувач може вручну схвалити або перегенерувати.
        """
        # TODO: Send WebSocket notification about validation failure
        logger.warning(
            f"[Scene {scene.scene_number}] Validation failed - "
            f"Score: {validation_result.quality_score}, Feedback: {validation_result.feedback}"
        )

    async def _generate_video_for_scene(self, project: ProjectData, scene: SceneData):
        """Генерує відео для сцени"""

        scene.status = SceneStatus.GENERATING_VIDEO
        await self._save_project_state(project)

        logger.info(f"[Scene {scene.scene_number}] Generating video...")

        try:
            video_path = await self.visual_engine.generate_video(
                image_path=Path(scene.image_path) if isinstance(scene.image_path, str) else scene.image_path,
                prompt=scene.motion_prompt,
                scene_number=scene.scene_number,
                project_id=project.project_id
            )

            scene.video_path = video_path
            logger.success(f"[Scene {scene.scene_number}] Video generated: {video_path}")

            await self._save_project_state(project)

        except Exception as e:
            logger.error(f"[Scene {scene.scene_number}] Video generation failed: {e}")
            raise

    # ========================================================================
    # CALLBACKS (для Telegram Bot)
    # ========================================================================

    async def on_scene_approved(self, scene_number: int):
        """
        Callback коли сцена схвалена користувачем.
        Після схвалення ВСІХ сцен - запускає assembly + Topaz.

        Flow:
        1. Всі сцени approved -> Assembly (FFmpeg)
        2. Assembly -> FPS Interpolation (Topaz)
        3. FPS -> Upscale 4K (Topaz)

        Args:
            scene_number: Номер сцени
        """
        if not self.current_project_id:
            raise ValueError("No active project. Start pipeline first.")

        project = await self._get_project(self.current_project_id)
        scene = self._get_scene(project, scene_number)

        logger.info(f"[Scene {scene_number}] User APPROVED")

        # Оновлюємо статус сцени
        scene.status = SceneStatus.APPROVED
        scene.approved_at = datetime.now()

        await self._save_project_state(project)

        # Перевіряємо чи всі сцени схвалені
        all_approved = all(
            s.status == SceneStatus.APPROVED
            for s in project.scenes
        )

        if all_approved:
            logger.success(f"[{project.project_id}] ALL SCENES APPROVED! Starting post-processing...")

            # TODO: Send WebSocket notification
            logger.info("Starting post-processing: Voiceover -> Assembly -> FPS -> 4K")

            # Start post-processing pipeline
            await self._run_post_processing(project)
        else:
            # Count remaining
            pending = sum(1 for s in project.scenes if s.status != SceneStatus.APPROVED)
            logger.info(f"[{project.project_id}] Waiting for {pending} more scenes to be approved")

    async def _run_post_processing(self, project: ProjectData, skip_voiceover: bool = False):
        """
        Запускає повний v7.5 пайплайн пост-обробки:

        STEP 0: Music Generation (Replicate)
        STEP 1: Beat Analysis (librosa)
        STEP 2: Voiceover + Subtitles Generation (ElevenLabs with timestamps)
        STEP 3: SFX Generation (ElevenLabs Sound Effects)
        STEP 4: GEN3a Video Analysis (Gemini)
        STEP 5: GEN3b Manifest Generation (Gemini)
        STEP 6: Proper Render with effects and audio mixing (FFmpeg)
        STEP 7: Topaz Enhancement (optional)

        Note: All audio assets (music, voiceover, subtitles, SFX) are generated
        BEFORE GEN3a so that GEN3a has all raw files available for analysis.

        Args:
            project: ProjectData з усіма схваленими сценами
            skip_voiceover: Пропустити voiceover (для resume)
        """
        from app.services.audio_engine import AudioEngine
        from app.services.music_generator import MusicGenerator
        from app.services.beat_analyzer import BeatAnalyzer

        logger.info("=" * 70)
        logger.info(f"[{project.project_id}] POST-PROCESSING PIPELINE v7.4")
        logger.info("=" * 70)

        project_dir = project.project_dir
        music_dir = project_dir / "music"
        music_dir.mkdir(exist_ok=True)

        # Load project brief for music and voiceover settings
        project_brief_path = project_dir / "project_brief.json"
        project_data = {}
        if project_brief_path.exists():
            import json
            with open(project_brief_path, 'r', encoding='utf-8') as f:
                project_data = json.load(f)

        # ====================================================================
        # STEP 0: Music Generation (Replicate)
        # ====================================================================
        background_music_path = music_dir / "background.mp3"
        if not background_music_path.exists():
            logger.info("[POST] Step 0: Generating background music...")
            try:
                music_generator = MusicGenerator()

                # Get music prompt from project brief
                audio_data = project_data.get('audio', {})
                music_prompt = audio_data.get('suno_prompt',
                    "cinematic orchestral music, epic, dramatic, film score, no vocals")

                result = await music_generator.generate(
                    prompt=music_prompt,
                    output_path=background_music_path,
                    duration=45.0,  # 45 seconds for 6 scenes
                )

                if result.success:
                    logger.success(f"[POST] Background music generated: {background_music_path}")
                else:
                    logger.warning(f"[POST] Music generation failed: {result.error}, continuing without music")
            except Exception as e:
                logger.warning(f"[POST] Music generation error: {e}, continuing without music")
        else:
            logger.info(f"[POST] Step 0: Music already exists: {background_music_path}")

        # ====================================================================
        # STEP 1: Beat Analysis (librosa)
        # ====================================================================
        beat_analysis_path = music_dir / "beat_analysis.json"
        if background_music_path.exists() and not beat_analysis_path.exists():
            logger.info("[POST] Step 1: Analyzing music beats...")
            try:
                beat_analyzer = BeatAnalyzer()
                beat_data = await beat_analyzer.analyze_music(background_music_path)

                import json
                with open(beat_analysis_path, 'w', encoding='utf-8') as f:
                    json.dump(beat_data.to_dict(), f, indent=2)

                logger.success(f"[POST] Beat analysis saved: {beat_analysis_path}")
            except Exception as e:
                logger.warning(f"[POST] Beat analysis error: {e}, continuing without beat data")
        elif beat_analysis_path.exists():
            logger.info(f"[POST] Step 1: Beat analysis already exists: {beat_analysis_path}")

        # ====================================================================
        # STEP 2: Generate voiceover + subtitles (synced from ElevenLabs timestamps)
        # ====================================================================
        if not skip_voiceover:
            await self._update_stage(project, PipelineStage.VOICEOVER)

            try:
                voiceover_path = project_dir / "voiceover.mp3"
                alignment_path = project_dir / "vo_alignment.json"
                subtitles_path = project_dir / "subtitles.ass"
                timing_path = project_dir / "voiceover_timing.json"

                # Check if we need to generate or regenerate voiceover
                # CRITICAL: We need BOTH voiceover AND alignment for proper subtitle sync
                needs_generation = not voiceover_path.exists()
                needs_alignment = voiceover_path.exists() and not alignment_path.exists()

                if (needs_generation or needs_alignment) and 'voiceover' in project_data:
                    if needs_alignment:
                        logger.warning("[POST] Step 2: Voiceover exists but NO alignment! Regenerating for sync...")
                        # Delete old files to force regeneration with timestamps
                        voiceover_path.unlink(missing_ok=True)
                        subtitles_path.unlink(missing_ok=True)
                        timing_path.unlink(missing_ok=True)
                    else:
                        logger.info("[POST] Step 2: Generating voiceover with synced subtitles...")

                    from app.services.glaze_models import VoiceoverSettings, VoiceoverConfig

                    voiceover_data = project_data['voiceover']
                    voiceover_config = VoiceoverConfig(
                        settings=VoiceoverSettings(**voiceover_data['settings']),
                        full_script=voiceover_data['full_script'],
                        total_duration_seconds=voiceover_data.get('total_duration_seconds', 30),
                    )

                    audio_engine = AudioEngine()
                    voiceover_path, alignment_path, subtitles_path, timing_path = await audio_engine.generate_voiceover_and_subtitles(
                        voiceover_config=voiceover_config,
                        project_dir=project_dir,
                        hook_offset=0.3,  # Standard hook offset
                    )
                    logger.success(f"[POST] Voiceover + subtitles generated (synced from ElevenLabs timestamps)")
                    logger.success(f"[POST]   Audio: {voiceover_path}")
                    logger.success(f"[POST]   Alignment: {alignment_path}")
                    logger.success(f"[POST]   Subtitles: {subtitles_path}")
                    logger.success(f"[POST]   Timing (for GEN3b): {timing_path}")
                elif voiceover_path.exists() and alignment_path.exists():
                    logger.info(f"[POST] Step 2: Voiceover with alignment already exists")
                    if subtitles_path.exists():
                        logger.info(f"[POST]   Subtitles: {subtitles_path}")
                    if timing_path.exists():
                        logger.info(f"[POST]   Timing: {timing_path}")
                else:
                    logger.warning("[POST] No voiceover config found, skipping")

                await self._mark_stage_complete(project, PipelineStage.VOICEOVER)

            except Exception as e:
                await self._handle_stage_error(
                    project, PipelineStage.VOICEOVER, e, is_resumable=True
                )
                raise

        # ====================================================================
        # STEP 3: Generate SFX (ElevenLabs Sound Effects)
        # ====================================================================
        sfx_dir = project_dir / "sfx"
        sfx_dir.mkdir(parents=True, exist_ok=True)

        logger.info("[POST] Step 3: Generating SFX...")
        try:
            audio_engine = AudioEngine()
            sfx_count = 0

            # Generate sonic hook (intro sound)
            sonic_hook_config = project_data.get("audio", {}).get("sonic_hook", {})
            if sonic_hook_config and sonic_hook_config.get("description"):
                hook_path = sfx_dir / "sonic_hook.mp3"
                if not hook_path.exists():
                    logger.info(f"[POST] Generating sonic hook: {sonic_hook_config['description'][:40]}...")
                    await audio_engine.generate_and_save_sfx(
                        text=sonic_hook_config["description"],
                        output_path=hook_path,
                        duration_seconds=2.0,
                        prompt_influence=0.5,
                    )
                    sfx_count += 1
                else:
                    logger.info(f"[POST] Sonic hook already exists: {hook_path}")

            # Generate SFX for each scene
            scenes = project_data.get("scenes", [])
            for scene in scenes:
                scene_num = scene.get("scene_number", 0)

                # Get SFX description from scene
                sfx_desc = (
                    scene.get("audio_sfx") or
                    scene.get("audio_moment") or
                    ""
                )

                if not sfx_desc or sfx_desc.lower() in ["", "none", "n/a"]:
                    continue

                sfx_path = sfx_dir / f"scene_{scene_num}_sfx.mp3"

                if sfx_path.exists():
                    logger.info(f"[POST] Scene {scene_num} SFX already exists")
                    continue

                logger.info(f"[POST] Generating SFX for scene {scene_num}: {sfx_desc[:40]}...")
                try:
                    await audio_engine.generate_and_save_sfx(
                        text=sfx_desc,
                        output_path=sfx_path,
                        duration_seconds=3.0,
                        prompt_influence=0.4,
                    )
                    sfx_count += 1
                except Exception as e:
                    logger.warning(f"[POST] Failed to generate SFX for scene {scene_num}: {e}")
                    continue

            logger.success(f"[POST] Generated {sfx_count} new SFX files")
        except Exception as e:
            logger.warning(f"[POST] SFX generation error: {e}, continuing without SFX")

        # ====================================================================
        # STEP 4-7: Run v7.4 Pipeline (GEN3a → GEN3b → Render → Topaz)
        # ====================================================================
        logger.info("[POST] Steps 4-7: Running v7.4 Pipeline (GEN3a → GEN3b → Render)...")

        try:
            # This runs GEN3a → GEN3b → Render chain
            await self._run_gen3a_analysis(project)
            # GEN3a calls GEN3b, which calls Render
            # After render, check for Topaz
            return  # Topaz is handled in _run_manifest_render

        except Exception as e:
            logger.error(f"[POST] v7.4 Pipeline failed: {e}")
            logger.warning("[POST] Falling back to simple assembly...")

            # Fallback to simple assembly if v7.4 fails
            await self._run_simple_assembly(project)

    async def _run_simple_assembly(self, project: ProjectData):
        """
        Fallback: простая склейка видео без GEN3a/GEN3b.
        Используется если v7.4 pipeline failed.
        """
        from app.services.video_assembler import VideoAssembler

        project_dir = project.project_dir

        await self._update_stage(project, PipelineStage.ASSEMBLY)

        try:
            logger.info("[FALLBACK] Running simple video assembly...")

            assembler = VideoAssembler()
            final_video_path = await assembler.assemble_with_concat_file(
                project_dir=project_dir,
                output_filename="final.mp4",
            )

            logger.success(f"[FALLBACK] Video assembled: {final_video_path}")
            await self._mark_stage_complete(project, PipelineStage.ASSEMBLY)

            # After assembly - wait for approval before Topaz
            if settings.TOPAZ_ENABLED and final_video_path.exists():
                await self._update_stage(project, PipelineStage.AWAITING_RENDER_APPROVAL)
                project.status = ProjectStatus.AWAITING_APPROVAL
                await self._save_project_state(project)
                logger.info(f"[FALLBACK] Assembly complete! Waiting for approval before Topaz...")
                logger.info(f"[FALLBACK] Review video at: {final_video_path}")
            else:
                await self._update_stage(project, PipelineStage.COMPLETED)
                await self._mark_stage_complete(project, PipelineStage.COMPLETED)

        except Exception as e:
            await self._handle_stage_error(
                project, PipelineStage.ASSEMBLY, e, is_resumable=True
            )
            raise

    async def _add_to_topaz_queue(self, project: ProjectData, input_path: Path):
        """Add video to Topaz queue for FPS interpolation and upscaling."""
        await self._update_stage(project, PipelineStage.TOPAZ_FPS)

        try:
            logger.info("[POST] Adding to Topaz queue (FPS + Upscale)...")

            if not self.topaz_queue.is_running:
                await self.topaz_queue.start()

            task = await self.topaz_queue.add_task(
                project_id=project.project_id,
                scene_number=0,
                input_path=input_path,
                output_dir=project.project_dir,
                metadata={
                    "type": "final_video",
                    "total_scenes": len(project.scenes),
                }
            )

            logger.info(f"[POST] Added to Topaz queue: {task.task_id}")

            project.status = ProjectStatus.POST_PROCESSING
            await self._save_project_state(project)

            logger.info("Topaz processing started (15-45 min)")
            completed = await self.topaz_queue.wait_for_completion(timeout=7200)

            if completed:
                logger.success("[POST] Topaz completed!")
                project.status = ProjectStatus.COMPLETED
                await self._save_project_state(project)
            else:
                logger.warning("[POST] Topaz timed out")

        except Exception as e:
            await self._handle_stage_error(
                project, PipelineStage.TOPAZ_FPS, e, is_resumable=True
            )
            raise

    async def on_scene_regenerate(
        self,
        scene_number: int,
        new_model: Optional[str] = None,
        new_prompt: Optional[str] = None
    ):
        """
        Callback для регенерації сцени

        Args:
            scene_number: Номер сцени
            new_model: Нова модель (kling/veo/sora, опціонально)
            new_prompt: Новий промпт (опціонально)
        """
        if not self.current_project_id:
            raise ValueError("No active project. Start pipeline first.")

        project = await self._get_project(self.current_project_id)
        scene = self._get_scene(project, scene_number)

        logger.info(f"[Scene {scene_number}] Regenerating...")

        # Update model if provided
        if new_model:
            # Note: model tracking буде додано в майбутньому
            logger.info(f"  New model: {new_model}")
            # TODO: Додати підтримку різних моделей (VEO/SORA)

        # Update prompt if provided
        if new_prompt:
            scene.image_prompt = new_prompt
            logger.info(f"  New prompt: {new_prompt[:80]}...")

        # Reset scene state
        scene.status = SceneStatus.REGENERATING
        scene.retry_count += 1
        scene.image_path = None
        scene.video_path = None

        await self._save_project_state(project)

        # Re-process scene
        await self._process_scene(project, scene)

        # TODO: Send WebSocket notification about regenerated scene
        logger.info(f"[Scene {scene_number}] Regeneration complete")

    async def on_manual_image_selected(self, scene_number: int, image_idx: int):
        """
        Callback коли користувач вручну вибрав зображення
        (Gemini Escalation - коли автоматичний вибір не вдався)

        Args:
            scene_number: Номер сцени
            image_idx: Індекс обраного зображення (0-3)
        """
        if not self.current_project_id:
            raise ValueError("No active project. Start pipeline first.")

        project = await self._get_project(self.current_project_id)
        scene = self._get_scene(project, scene_number)

        logger.info(f"[Scene {scene_number}] User manually selected image #{image_idx}")

        # Встановлюємо вибране зображення як активне
        # TODO: Реалізувати логіку вибору конкретного зображення з 4 варіантів
        # Поки що просто продовжуємо з поточним зображенням
        scene.validation_approved = True
        scene.status = SceneStatus.GENERATING_VIDEO

        await self._save_project_state(project)

        # Продовжуємо обробку сцени (генерація відео)
        await self._generate_video_for_scene(project, scene)

        # TODO: Send WebSocket notification
        logger.info(f"[Scene {scene_number}] Manual image selected, video generated")

    # ========================================================================
    # PRIMARY SCENE CALLBACKS (Human Validation)
    # ========================================================================

    async def on_primary_image_selected(self, scene_number: int, image_idx: int):
        """
        Callback коли користувач обрав зображення для PRIMARY сцени

        Args:
            scene_number: Номер сцени (зазвичай 1)
            image_idx: Індекс обраного зображення (1-4)
        """
        if not self.current_project_id:
            raise ValueError("No active project. Start pipeline first.")

        project = await self._get_project(self.current_project_id)
        scene = self._get_scene(project, scene_number)

        logger.info(f"[Scene {scene_number}] PRIMARY image #{image_idx} selected by user")

        # Копіюємо вибраний кандидат як основне зображення
        scene_dir = settings.get_scene_dir(project.project_id, scene_number)
        candidate_path = scene_dir / f"candidate_{image_idx}.png"
        selected_path = scene_dir / "image.png"

        if candidate_path.exists():
            import shutil
            shutil.copy(candidate_path, selected_path)
            scene.image_path = selected_path
            logger.info(f"[Scene {scene_number}] Copied candidate_{image_idx}.png -> image.png")

            # Копіюємо metadata кандидата для отримання image_url
            candidate_metadata_path = scene_dir / f"candidate_{image_idx}_metadata.json"
            if candidate_metadata_path.exists():
                import json
                with open(candidate_metadata_path, 'r', encoding='utf-8') as f:
                    candidate_meta = json.load(f)

                # Зберігаємо основний metadata з image_url
                main_metadata = {
                    "request_id": candidate_meta.get("request_id"),
                    "image_url": candidate_meta.get("image_url"),
                    "prompt": scene.image_prompt,
                    "scene_number": scene_number,
                    "project_id": project.project_id,
                    "generation_mode": "standard",
                    "selected_by_human": True,
                    "selected_candidate": image_idx,
                }
                metadata_path = scene_dir / "metadata.json"
                await file_manager.save_json(main_metadata, metadata_path)
                logger.info(f"[Scene {scene_number}] Saved metadata with image_url for reference")
        else:
            logger.error(f"[Scene {scene_number}] Candidate image not found: {candidate_path}")

        # Позначаємо як схвалене людиною
        scene.validation_approved = True
        scene.primary_selected_by_human = True

        await self._save_project_state(project)

        # Сигналізуємо що PRIMARY обрано (для продовження pipeline)
        if hasattr(self, '_primary_selection_event') and self._primary_selection_event:
            self._primary_selection_event.set()

        logger.success(f"[Scene {scene_number}] PRIMARY scene approved by human")

    async def on_primary_regenerate(self, scene_number: int):
        """
        Callback для перегенерації PRIMARY сцени

        Args:
            scene_number: Номер сцени
        """
        if not self.current_project_id:
            raise ValueError("No active project. Start pipeline first.")

        project = await self._get_project(self.current_project_id)
        scene = self._get_scene(project, scene_number)

        logger.info(f"[Scene {scene_number}] User requested PRIMARY scene regeneration")

        # Збільшуємо лічильник спроб
        if not hasattr(scene, 'primary_regeneration_count'):
            scene.primary_regeneration_count = 0
        scene.primary_regeneration_count += 1

        max_attempts = 5
        if scene.primary_regeneration_count >= max_attempts:
            logger.error(f"[Scene {scene_number}] Max regeneration attempts ({max_attempts}) reached")
            # TODO: Send WebSocket notification about max attempts reached
            return

        # Генеруємо нові 4 кандидати
        scene.status = SceneStatus.REGENERATING
        await self._save_project_state(project)

        logger.info(f"[Scene {scene_number}] Generating new PRIMARY candidates (attempt {scene.primary_regeneration_count + 1}/{max_attempts})...")

        try:
            # Генеруємо 4 нові кандидати
            candidate_paths = await self.visual_engine.generate_primary_scene_candidates(
                prompt=scene.image_prompt,
                scene_number=scene_number,
                project_id=project.project_id,
                num_candidates=4
            )

            # TODO: Send WebSocket notification with new candidates
            if candidate_paths:
                logger.info(f"[Scene {scene_number}] Generated {len(candidate_paths)} new candidates")
                # For now, auto-select first candidate
                await self._auto_select_primary(project, scene, candidate_paths)

        except Exception as e:
            logger.error(f"[Scene {scene_number}] PRIMARY regeneration failed: {e}")
            scene.status = SceneStatus.FAILED
            scene.error_message = str(e)
            await self._save_project_state(project)

    async def on_scenario_rejected(self, project_id: str):
        """
        Callback коли користувач відхилив весь сценарій

        Args:
            project_id: ID проекту
        """
        logger.warning(f"[{project_id}] Scenario REJECTED by user")

        try:
            project = await self._get_project(project_id)
            project.status = ProjectStatus.FAILED
            project.error_message = "Rejected by user"
            await self._save_project_state(project)

            # Сигналізуємо що сценарій відхилено
            if hasattr(self, '_primary_selection_event') and self._primary_selection_event:
                self._scenario_rejected = True
                self._primary_selection_event.set()

        except Exception as e:
            logger.error(f"[{project_id}] Error handling scenario rejection: {e}")

    def get_scene(self, scene_number: int) -> SceneData:
        """
        Отримує дані сцени для TelegramController

        Args:
            scene_number: Номер сцени

        Returns:
            SceneData об'єкт

        Raises:
            ValueError: Якщо немає активного проекту або сцени не існує
        """
        if not self.current_project_id:
            raise ValueError("No active project")

        # Синхронна версія для використання в handlers
        # (викликається з async context, але не потребує await)
        import asyncio
        loop = asyncio.get_event_loop()

        # Отримуємо проект синхронно якщо є в пам'яті
        if self.current_project_id in self.active_projects:
            project = self.active_projects[self.current_project_id]
            return self._get_scene(project, scene_number)

        raise ValueError(f"Project {self.current_project_id} not in active memory")

    # ========================================================================
    # TOPAZ QUEUE INTEGRATION
    # ========================================================================

    def _setup_topaz_callbacks(self) -> None:
        """Налаштовує callbacks для Topaz Queue"""
        self.topaz_queue.on_progress = self._on_topaz_progress
        self.topaz_queue.on_completed = self._on_topaz_completed
        self.topaz_queue.on_failed = self._on_topaz_failed

    async def _on_topaz_progress(self, progress: TopazProgress) -> None:
        """
        Callback для прогресу Topaz обробки

        Args:
            progress: TopazProgress з інформацією про прогрес
        """
        logger.info(
            f"[Scene {progress.scene_number}] Topaz progress: "
            f"{progress.progress_percent:.0f}% - {progress.message}"
        )

        # Оновлюємо статус сцени
        if self.current_project_id:
            try:
                project = await self._get_project(self.current_project_id)
                scene = self._get_scene(project, progress.scene_number)

                # Оновлюємо статус залежно від етапу
                if progress.stage.value == "fps_interpolation":
                    scene.status = SceneStatus.UPSCALING_FPS
                    # Update project stage
                    if project.current_stage != PipelineStage.TOPAZ_FPS:
                        await self._update_stage(project, PipelineStage.TOPAZ_FPS)

                elif progress.stage.value == "upscaling":
                    scene.status = SceneStatus.UPSCALING_4K
                    # Update project stage to TOPAZ_UPSCALE
                    if project.current_stage != PipelineStage.TOPAZ_UPSCALE:
                        await self._mark_stage_complete(project, PipelineStage.TOPAZ_FPS)
                        await self._update_stage(project, PipelineStage.TOPAZ_UPSCALE)

                await self._save_project_state(project)
            except Exception as e:
                logger.warning(f"Failed to update scene progress: {e}")

    async def _on_topaz_completed(self, task: TopazTask) -> None:
        """
        Callback коли Topaz обробка завершена успішно

        Args:
            task: TopazTask з результатами
        """
        logger.success(
            f"[Scene {task.scene_number}] Topaz completed! "
            f"Output: {task.upscaled_output_path}"
        )

        # Оновлюємо статус сцени
        try:
            project = await self._get_project(task.project_id)
            scene = self._get_scene(project, task.scene_number)

            scene.status = SceneStatus.UPSCALE_COMPLETED
            scene.fps_boosted_path = task.fps_output_path
            scene.upscaled_path = task.upscaled_output_path
            scene.completed_at = datetime.now()

            # Mark TOPAZ_UPSCALE as complete
            await self._mark_stage_complete(project, PipelineStage.TOPAZ_UPSCALE)

            await self._save_project_state(project)

            # TODO: Send WebSocket notification about final video
            if task.upscaled_output_path:
                logger.success(f"Final video ready: {task.upscaled_output_path}")

            # Перевіряємо чи всі сцени завершені
            await self._check_project_completion(project)

        except Exception as e:
            logger.error(f"Failed to update scene after Topaz completion: {e}")

    async def _on_topaz_failed(self, task: TopazTask) -> None:
        """
        Callback коли Topaz обробка провалилась (після всіх retry)

        Args:
            task: TopazTask з інформацією про помилку
        """
        logger.error(
            f"[Scene {task.scene_number}] Topaz FAILED after {task.retry_count} retries: "
            f"{task.error_message}"
        )

        # Оновлюємо статус сцени та проекту
        try:
            project = await self._get_project(task.project_id)
            scene = self._get_scene(project, task.scene_number)

            scene.status = SceneStatus.UPSCALE_FAILED
            scene.upscale_retry_count = task.retry_count
            scene.upscale_error_message = task.error_message

            # Determine current stage based on task progress
            current_topaz_stage = (
                PipelineStage.TOPAZ_UPSCALE
                if task.fps_output_path and task.fps_output_path.exists()
                else PipelineStage.TOPAZ_FPS
            )

            # Handle error with stage tracking
            await self._handle_stage_error(
                project=project,
                stage=current_topaz_stage,
                error=Exception(task.error_message or "Topaz processing failed"),
                scene_number=task.scene_number,
                is_resumable=True
            )

        except Exception as e:
            logger.error(f"Failed to update scene after Topaz failure: {e}")

    async def _check_project_completion(self, project: ProjectData) -> None:
        """
        Перевіряє чи всі сцени проекту завершені

        Args:
            project: ProjectData для перевірки
        """
        all_completed = all(
            scene.status in [
                SceneStatus.UPSCALE_COMPLETED,
                SceneStatus.COMPLETED,
            ]
            for scene in project.scenes
        )

        if all_completed:
            logger.success(f"[{project.project_id}] All scenes completed!")

            # Update stage to COMPLETED
            await self._update_stage(project, PipelineStage.COMPLETED)
            await self._mark_stage_complete(project, PipelineStage.COMPLETED)

            project.status = ProjectStatus.COMPLETED
            project.completed_at = datetime.now()
            project.is_resumable = False  # No need to resume completed project
            await self._save_project_state(project)

            # TODO: Send WebSocket notification about project completion
            logger.success(f"[{project.project_id}] PROJECT COMPLETED!")

            # ================================================================
            # CLEANUP: Очищення промптів після завершення pipeline
            # ================================================================
            await self._cleanup_forms_after_pipeline()

            # Закриваємо браузер HiggsFieldWebAdapter (якщо використовується)
            # Проект завершено - можна закривати
            self.approve_visual_engine_shutdown()
            await self.shutdown_visual_engine()

    async def start_topaz_queue(self) -> None:
        """Запускає Topaz Queue worker"""
        await self.topaz_queue.start()
        logger.success("Topaz Queue worker started")

    async def stop_topaz_queue(self) -> None:
        """Зупиняє Topaz Queue worker"""
        await self.topaz_queue.stop()
        logger.info("Topaz Queue worker stopped")

    def get_topaz_queue_status(self) -> dict:
        """
        Повертає статус Topaz Queue

        Returns:
            dict з інформацією про чергу
        """
        return {
            "queue_size": self.topaz_queue.get_queue_size(),
            "current_task": self.topaz_queue.get_current_task(),
            "stats": self.topaz_queue.get_stats(),
            "is_running": self.topaz_queue.is_running,
        }

    async def approve_and_run_topaz(self, project_id: str) -> bool:
        """
        Approve rendered video and start Topaz upscaling.

        Call this after reviewing final.mp4 to confirm it's ready for upscaling.
        This prevents wasting time upscaling videos with montage issues.

        Args:
            project_id: ID of the project to approve

        Returns:
            True if Topaz started successfully, False otherwise
        """
        project = self.active_projects.get(project_id)

        if not project:
            project = await self.load_project_from_disk(project_id)

        if not project:
            logger.error(f"Project {project_id} not found")
            return False

        # Check if project is in the right state
        if project.current_stage != PipelineStage.AWAITING_RENDER_APPROVAL:
            logger.warning(f"Project {project_id} is not awaiting render approval (stage: {project.current_stage})")
            return False

        # Find final video
        final_video_path = project.project_dir / "final.mp4"
        if not final_video_path.exists():
            final_video_path = project.project_dir / "final_video.mp4"

        if not final_video_path.exists():
            logger.error(f"No final video found in {project.project_dir}")
            return False

        logger.info(f"[{project_id}] Render approved! Starting Topaz upscaling...")

        # Start Topaz
        await self._add_to_topaz_queue(project, final_video_path)

        return True

    async def reject_render(self, project_id: str) -> bool:
        """
        Reject rendered video (e.g., due to montage issues).

        This marks the project as failed and allows re-running render.

        Args:
            project_id: ID of the project to reject

        Returns:
            True if rejected successfully
        """
        project = self.active_projects.get(project_id)

        if not project:
            project = await self.load_project_from_disk(project_id)

        if not project:
            logger.error(f"Project {project_id} not found")
            return False

        project.status = ProjectStatus.PAUSED
        project.current_stage = PipelineStage.RENDER
        project.error_message = "Render rejected by user - needs re-render"
        await self._save_project_state(project)

        logger.warning(f"[{project_id}] Render rejected. Project paused at RENDER stage.")
        return True

    # ========================================================================
    # STATE MANAGEMENT
    # ========================================================================

    async def _save_project_state(self, project: ProjectData):
        """Зберігає стан проекту в SQLite"""
        # Convert to dict for JSON serialization
        project_dict = project.model_dump(mode='json')

        await state_manager.save_state(
            key=f"project:{project.project_id}",
            data=project_dict
        )

    async def _get_project(self, project_id: str) -> ProjectData:
        """Отримує проект з пам'яті або БД"""

        # Try memory first
        if project_id in self.active_projects:
            return self.active_projects[project_id]

        # Load from database
        project_dict = await state_manager.get_state(f"project:{project_id}")

        if not project_dict:
            raise ValueError(f"Project not found: {project_id}")

        project = ProjectData(**project_dict)
        self.active_projects[project_id] = project

        return project

    async def _update_project_status(self, project: ProjectData, status: ProjectStatus):
        """Оновлює статус проекту"""
        project.status = status
        project.updated_at = datetime.now()
        await self._save_project_state(project)

        logger.info(f"[{project.project_id}] Status: {status}")

    def _get_scene(self, project: ProjectData, scene_number: int) -> SceneData:
        """Знаходить сцену за номером"""
        for scene in project.scenes:
            if scene.scene_number == scene_number:
                return scene

        raise ValueError(f"Scene {scene_number} not found in project {project.project_id}")

    # ========================================================================
    # v7.4 PIPELINE STAGES
    # ========================================================================

    async def _run_gen3a_analysis(self, project: ProjectData) -> None:
        """
        Run GEN3a Video Analysis stage (v7.4)

        Analyzes all generated videos using Gemini Vision:
        - Glitch detection
        - Action peaks identification
        - Speed map recommendations
        - Visual classification
        - Easter egg verification
        """
        from app.pipeline.gen3_stages import Gen3aStage

        logger.info(f"[{project.project_id}] Starting GEN3a Video Analysis...")
        await self._update_stage(project, PipelineStage.VIDEO_ANALYSIS)

        try:
            stage = Gen3aStage(project)
            result = await stage.run()

            if result.success:
                await self._mark_stage_complete(project, PipelineStage.VIDEO_ANALYSIS)
                logger.success(f"[{project.project_id}] GEN3a complete: {result.message}")

                # Continue to GEN3b
                await self._run_gen3b_manifest(project)
            else:
                raise Exception(result.message)

        except Exception as e:
            logger.error(f"[{project.project_id}] GEN3a failed: {e}")
            raise

    async def _run_gen3b_manifest(self, project: ProjectData) -> None:
        """
        Run GEN3b Manifest Generation stage (v7.4)

        Creates FFmpeg manifest with:
        - Hook style and effects
        - Scene speed segments
        - Subtitle animations
        - 5-layer audio plan
        - Global effects
        """
        from app.pipeline.gen3_stages import Gen3bStage

        logger.info(f"[{project.project_id}] Starting GEN3b Manifest Generation...")
        await self._update_stage(project, PipelineStage.MANIFEST_GENERATION)

        try:
            stage = Gen3bStage(project)
            result = await stage.run()

            if result.success:
                await self._mark_stage_complete(project, PipelineStage.MANIFEST_GENERATION)
                logger.success(f"[{project.project_id}] GEN3b complete: {result.message}")

                # Continue to rendering
                await self._run_manifest_render(project)
            else:
                raise Exception(result.message)

        except Exception as e:
            logger.error(f"[{project.project_id}] GEN3b failed: {e}")
            raise

    async def _run_manifest_render(self, project: ProjectData) -> None:
        """
        Run Manifest Rendering stage (v7.4)

        Renders final video from manifest.json using FFmpeg:
        - Scene concatenation with speed changes
        - Effect application
        - Hook insertion
        - Subtitle overlay
        - 5-layer audio mixing
        """
        from app.pipeline.postprocess_stage import PostProcessStage

        logger.info(f"[{project.project_id}] Starting Manifest Rendering...")
        await self._update_stage(project, PipelineStage.RENDER)

        try:
            stage = PostProcessStage(project)
            result = await stage.run()

            if result.success:
                await self._mark_stage_complete(project, PipelineStage.RENDER)
                logger.success(f"[{project.project_id}] Render complete: {result.message}")

                # After render - wait for approval before Topaz
                # This prevents upscaling videos with montage issues
                if settings.TOPAZ_ENABLED:
                    await self._update_stage(project, PipelineStage.AWAITING_RENDER_APPROVAL)
                    project.status = ProjectStatus.AWAITING_APPROVAL
                    await self._save_project_state(project)
                    logger.info(f"[{project.project_id}] Render complete! Waiting for approval before Topaz upscaling...")
                    logger.info(f"[{project.project_id}] Review video at: {project.project_dir / 'final.mp4'}")
                    logger.info(f"[{project.project_id}] To approve and run Topaz, use: approve_and_run_topaz('{project.project_id}')")
                else:
                    # Mark as completed (no Topaz)
                    await self._update_stage(project, PipelineStage.COMPLETED)
                    await self._mark_stage_complete(project, PipelineStage.COMPLETED)
                    project.status = ProjectStatus.COMPLETED
                    project.completed_at = datetime.now()
                    await self._save_project_state(project)
                    logger.success(f"[{project.project_id}] PROJECT COMPLETED (v7.4)!")
            else:
                raise Exception(result.message)

        except Exception as e:
            logger.error(f"[{project.project_id}] Render failed: {e}")
            raise

    async def run_v74_pipeline(self, project: ProjectData) -> None:
        """
        Run the full v7.4 pipeline after video generation.

        This runs:
        1. GEN3a - Video Analysis
        2. GEN3b - Manifest Generation
        3. Rendering - FFmpeg render from manifest

        Call this after all videos are generated.
        """
        logger.info("=" * 70)
        logger.info(f"[{project.project_id}] Starting v7.4 Pipeline")
        logger.info("=" * 70)

        try:
            # Check if we have all videos
            has_all_videos = all(
                scene.video_path and Path(scene.video_path).exists()
                for scene in project.scenes
                if scene.scene_number <= 6
            )

            if not has_all_videos:
                logger.warning(f"[{project.project_id}] Not all videos ready for v7.4 pipeline")
                return

            # Run the v7.4 stages
            await self._run_gen3a_analysis(project)

        except Exception as e:
            logger.error(f"[{project.project_id}] v7.4 Pipeline failed: {e}")
            raise


# ============================================================================
# EXPORT
# ============================================================================

__all__ = ["ProjectOrchestrator"]
