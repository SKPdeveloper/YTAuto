"""
Topaz Video AI Queue - Асинхронна черга для upscaling відео

Двоетапна обробка:
1. Frame Interpolation (FPS → 60)
2. Upscaling (→ 4K Portrait)

Особливості:
- Async queue з одним worker (GPU protection)
- Retry logic (5 спроб)
- Telegram notifications
- Progress tracking
- Graceful error handling
"""

import asyncio
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable, Dict, Any
from datetime import datetime
from enum import Enum

from app.core.config import settings
from app.modules.topaz_config import topaz_config
from app.utils.logger import logger, get_module_logger

# Module-specific logger
topaz_logger = get_module_logger("topaz_queue")


# ============================================================================
# ENUMS & DATA CLASSES
# ============================================================================

class TopazStage(str, Enum):
    """Етапи обробки Topaz"""
    PENDING = "pending"
    FPS_INTERPOLATION = "fps_interpolation"
    UPSCALING = "upscaling"
    COMPLETED = "completed"
    FAILED = "failed"


class TopazTaskStatus(str, Enum):
    """Статуси завдання в черзі"""
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TopazTask:
    """
    Завдання для обробки в Topaz Queue

    Attributes:
        task_id: Унікальний ідентифікатор завдання
        project_id: ID проекту
        scene_number: Номер сцени
        input_path: Шлях до вхідного відео
        output_dir: Директорія для вихідних файлів
        fps_output_path: Шлях до відео з 60 FPS (після етапу 1)
        upscaled_output_path: Шлях до 4K відео (після етапу 2)
        current_stage: Поточний етап обробки
        status: Статус завдання
        retry_count: Кількість спроб
        error_message: Повідомлення про помилку
        created_at: Час створення
        started_at: Час початку обробки
        completed_at: Час завершення
        metadata: Додаткові дані
    """
    task_id: str
    project_id: str
    scene_number: int
    input_path: Path
    output_dir: Path

    # Output paths (generated automatically)
    fps_output_path: Optional[Path] = None
    upscaled_output_path: Optional[Path] = None

    # Status tracking
    current_stage: TopazStage = TopazStage.PENDING
    status: TopazTaskStatus = TopazTaskStatus.QUEUED
    retry_count: int = 0
    error_message: Optional[str] = None

    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Additional metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Генерує output paths якщо не вказані"""
        # scene_number=0 means final video, use "final_" prefix
        prefix = "final" if self.scene_number == 0 else f"scene_{self.scene_number}"
        if self.fps_output_path is None:
            self.fps_output_path = self.output_dir / f"{prefix}_60fps.mp4"
        if self.upscaled_output_path is None:
            self.upscaled_output_path = self.output_dir / f"{prefix}_4k.mp4"


@dataclass
class TopazProgress:
    """Прогрес обробки для callback"""
    task_id: str
    scene_number: int
    stage: TopazStage
    progress_percent: float
    eta_seconds: Optional[int] = None
    message: str = ""


# ============================================================================
# TOPAZ QUEUE CLASS
# ============================================================================

class TopazQueue:
    """
    Асинхронна черга для Topaz Video AI обробки

    Features:
    - Single worker (GPU memory protection)
    - Two-stage processing (FPS → 4K)
    - Retry logic with configurable max retries
    - Callbacks for progress and completion
    - Graceful shutdown
    """

    def __init__(
        self,
        on_progress: Optional[Callable[[TopazProgress], Awaitable[None]]] = None,
        on_completed: Optional[Callable[[TopazTask], Awaitable[None]]] = None,
        on_failed: Optional[Callable[[TopazTask], Awaitable[None]]] = None,
    ):
        """
        Ініціалізує Topaz Queue

        Args:
            on_progress: Callback для прогресу обробки
            on_completed: Callback при успішному завершенні
            on_failed: Callback при помилці (після всіх retry)
        """
        self.queue: asyncio.Queue[TopazTask] = asyncio.Queue()
        self.worker_task: Optional[asyncio.Task] = None
        self.is_running: bool = False
        self.current_task: Optional[TopazTask] = None

        # Callbacks
        self.on_progress = on_progress
        self.on_completed = on_completed
        self.on_failed = on_failed

        # Configuration from settings + auto-detection
        self.max_retries = settings.TOPAZ_MAX_RETRIES
        self.timeout = settings.TOPAZ_TIMEOUT
        
        # Use auto-detected Topaz path if available
        if topaz_config.is_enabled and topaz_config.ffmpeg_path:
            self.ffmpeg_path = topaz_config.ffmpeg_path
        else:
            self.ffmpeg_path = settings.TOPAZ_FFMPEG_PATH
        
        self.is_topaz_available = topaz_config.is_enabled

        # Statistics
        self.stats = {
            "total_processed": 0,
            "successful": 0,
            "failed": 0,
            "total_retries": 0,
        }

        topaz_logger.info("TopazQueue initialized")
        topaz_logger.info(f"  Topaz available: {self.is_topaz_available}")
        topaz_logger.info(f"  FFmpeg path: {self.ffmpeg_path}")
        topaz_logger.info(f"  Max retries: {self.max_retries}")
        topaz_logger.info(f"  Timeout: {self.timeout}s")

        # Check for models directory (auto-detected)
        self.models_dir = topaz_config.models_path or Path(r"C:\ProgramData\Topaz Labs LLC\Topaz Video AI\models")
        if not self.models_dir.exists():
            topaz_logger.warning(
                f"Topaz models directory not found at: {self.models_dir}. "
                "Please ensure Topaz Video AI is installed correctly."
            )

    # ========================================================================
    # QUEUE MANAGEMENT
    # ========================================================================

    async def start(self) -> None:
        """Запускає worker для обробки черги"""
        if self.is_running:
            topaz_logger.warning("TopazQueue already running")
            return

        self.is_running = True
        self.worker_task = asyncio.create_task(self._worker())
        topaz_logger.success("TopazQueue worker started")

    async def stop(self) -> None:
        """Зупиняє worker gracefully"""
        if not self.is_running:
            return

        topaz_logger.info("Stopping TopazQueue worker...")
        self.is_running = False

        if self.worker_task:
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass

        topaz_logger.success("TopazQueue worker stopped")

    async def add_task(
        self,
        project_id: str,
        scene_number: int,
        input_path: Path,
        output_dir: Path,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TopazTask:
        """
        Додає завдання в чергу

        Args:
            project_id: ID проекту
            scene_number: Номер сцени
            input_path: Шлях до вхідного відео
            output_dir: Директорія для вихідних файлів
            metadata: Додаткові дані

        Returns:
            TopazTask об'єкт
        """
        # Generate unique task ID
        task_id = f"topaz_{project_id}_scene{scene_number}_{datetime.now().strftime('%H%M%S')}"

        # Create output directory if needed
        output_dir.mkdir(parents=True, exist_ok=True)

        task = TopazTask(
            task_id=task_id,
            project_id=project_id,
            scene_number=scene_number,
            input_path=Path(input_path),
            output_dir=Path(output_dir),
            metadata=metadata or {},
        )

        await self.queue.put(task)

        topaz_logger.info(f"Task added to queue: {task_id}")
        topaz_logger.info(f"  Project: {project_id}, Scene: {scene_number}")
        topaz_logger.info(f"  Input: {input_path}")
        topaz_logger.info(f"  Queue size: {self.queue.qsize()}")

        return task

    def get_queue_size(self) -> int:
        """Повертає розмір черги"""
        return self.queue.qsize()

    def get_current_task(self) -> Optional[TopazTask]:
        """Повертає поточне завдання"""
        return self.current_task

    def get_stats(self) -> Dict[str, int]:
        """Повертає статистику обробки"""
        return self.stats.copy()

    async def wait_for_completion(self, timeout: Optional[float] = None) -> bool:
        """
        Чекає завершення всіх завдань у черзі.

        Args:
            timeout: Максимальний час очікування в секундах (None = без ліміту)

        Returns:
            True якщо всі завдання завершились, False якщо timeout
        """
        import time
        start_time = time.time()
        poll_interval = 5.0  # Перевіряємо кожні 5 секунд

        topaz_logger.info("Waiting for Topaz queue to complete...")

        while self.is_running:
            # Перевіряємо чи є активні завдання
            queue_empty = self.queue.empty()
            no_current_task = self.current_task is None

            if queue_empty and no_current_task:
                topaz_logger.success("All Topaz tasks completed!")
                return True

            # Перевіряємо timeout
            if timeout and (time.time() - start_time) > timeout:
                topaz_logger.warning(f"Topaz wait timeout after {timeout}s")
                return False

            # Логуємо прогрес
            if self.current_task:
                topaz_logger.info(
                    f"  Processing: {self.current_task.task_id} "
                    f"(stage: {self.current_task.current_stage.value})"
                )

            await asyncio.sleep(poll_interval)

        return True

    # ========================================================================
    # WORKER
    # ========================================================================

    async def _worker(self) -> None:
        """
        Головний worker loop.
        Обробляє завдання з черги послідовно (1 за раз).
        """
        topaz_logger.info("Worker loop started")

        while self.is_running:
            try:
                # Wait for task with timeout (allows graceful shutdown)
                try:
                    task = await asyncio.wait_for(
                        self.queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue

                self.current_task = task
                task.status = TopazTaskStatus.PROCESSING
                task.started_at = datetime.now()

                topaz_logger.info("=" * 60)
                topaz_logger.info(f"Processing task: {task.task_id}")
                topaz_logger.info("=" * 60)

                try:
                    await self._process_task(task)

                    # Success
                    task.status = TopazTaskStatus.COMPLETED
                    task.completed_at = datetime.now()
                    self.stats["successful"] += 1

                    topaz_logger.success(f"Task completed: {task.task_id}")

                    if self.on_completed:
                        await self.on_completed(task)

                except Exception as e:
                    topaz_logger.error(f"Task failed: {task.task_id} - {e}")
                    task.error_message = str(e)

                    # Retry logic
                    if task.retry_count < self.max_retries:
                        task.retry_count += 1
                        task.status = TopazTaskStatus.QUEUED
                        self.stats["total_retries"] += 1

                        topaz_logger.warning(
                            f"Retrying task {task.task_id} "
                            f"(attempt {task.retry_count}/{self.max_retries})"
                        )

                        # Re-add to queue
                        await self.queue.put(task)
                    else:
                        # All retries exhausted
                        task.status = TopazTaskStatus.FAILED
                        task.completed_at = datetime.now()
                        self.stats["failed"] += 1

                        topaz_logger.error(
                            f"Task permanently failed after {self.max_retries} retries: "
                            f"{task.task_id}"
                        )

                        if self.on_failed:
                            await self.on_failed(task)

                finally:
                    self.stats["total_processed"] += 1
                    self.current_task = None
                    self.queue.task_done()

            except asyncio.CancelledError:
                topaz_logger.info("Worker cancelled")
                break
            except Exception as e:
                topaz_logger.error(f"Unexpected worker error: {e}")
                await asyncio.sleep(1)  # Prevent tight loop on errors

        topaz_logger.info("Worker loop ended")

    # ========================================================================
    # TASK PROCESSING
    # ========================================================================

    async def _process_task(self, task: TopazTask) -> None:
        """
        Обробляє одне завдання (двоетапно)

        Stage 1: Frame Interpolation (→ 60 FPS)
        Stage 2: Upscaling (→ 4K Portrait)
        """
        # Validate input file
        if not task.input_path.exists():
            raise FileNotFoundError(f"Input file not found: {task.input_path}")

        # Stage 1: FPS Interpolation
        task.current_stage = TopazStage.FPS_INTERPOLATION
        await self._notify_progress(task, 0, "Starting FPS interpolation...")

        await self._run_fps_interpolation(task)

        await self._notify_progress(task, 50, "FPS interpolation completed")

        # Stage 2: Upscaling to 4K
        task.current_stage = TopazStage.UPSCALING
        await self._notify_progress(task, 50, "Starting 4K upscaling...")

        await self._run_upscaling(task)

        await self._notify_progress(task, 100, "Upscaling completed")

        task.current_stage = TopazStage.COMPLETED

    async def _run_fps_interpolation(self, task: TopazTask) -> None:
        """
        Етап 1: Frame Interpolation до 60 FPS

        Використовує Topaz tvai_fi filter
        """
        topaz_logger.info(f"[{task.task_id}] Stage 1: FPS Interpolation")
        topaz_logger.info(f"  Model: {settings.TOPAZ_FPS_MODEL}")
        topaz_logger.info(f"  Target FPS: {settings.TOPAZ_TARGET_FPS}")

        # Build FFmpeg command for FPS interpolation
        # Формат: tvai_fi=model=apf-1:fps=60/1:device=0 (video_rate format, GPU)
        filter_str = (
            f"tvai_fi=model={settings.TOPAZ_FPS_MODEL}:"
            f"fps={settings.TOPAZ_TARGET_FPS}/1:"
            f"device=0"
        )

        cmd = [
            str(self.ffmpeg_path),
            "-hide_banner",
            "-nostdin",
            "-y",  # Overwrite output
            "-hwaccel", "auto",
            "-i", str(task.input_path),
            "-vf", filter_str,
            "-c:v", settings.TOPAZ_CODEC,
            "-b:v", settings.TOPAZ_BITRATE,
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",  # Copy audio
            str(task.fps_output_path),
        ]

        await self._run_ffmpeg(cmd, task, "FPS Interpolation")

        # Verify output
        if not task.fps_output_path.exists():
            raise RuntimeError(f"FPS output not created: {task.fps_output_path}")

        topaz_logger.success(f"[{task.task_id}] FPS Interpolation completed")
        topaz_logger.info(f"  Output: {task.fps_output_path}")

    async def _run_upscaling(self, task: TopazTask) -> None:
        """
        Етап 2: Upscaling до 4K Portrait

        Використовує Topaz tvai_up filter
        """
        topaz_logger.info(f"[{task.task_id}] Stage 2: 4K Upscaling")
        topaz_logger.info(f"  Model: {settings.TOPAZ_UPSCALE_MODEL}")
        topaz_logger.info(f"  Output: {settings.TOPAZ_OUTPUT_WIDTH}x{settings.TOPAZ_OUTPUT_HEIGHT}")

        # Build FFmpeg command for upscaling
        # scale=0 означає що розмір визначається через w/h параметри
        # device=0 - використовувати GPU
        # Додаємо scale filter для гарантованого виходу в потрібній роздільності
        filter_str = (
            f"tvai_up=model={settings.TOPAZ_UPSCALE_MODEL}:"
            f"scale=0:"
            f"w={settings.TOPAZ_OUTPUT_WIDTH}:"
            f"h={settings.TOPAZ_OUTPUT_HEIGHT}:"
            f"device=0,"
            f"scale={settings.TOPAZ_OUTPUT_WIDTH}:{settings.TOPAZ_OUTPUT_HEIGHT}"
        )

        # Use FPS output as input for upscaling
        input_path = task.fps_output_path

        cmd = [
            str(self.ffmpeg_path),
            "-hide_banner",
            "-nostdin",
            "-y",  # Overwrite output
            "-hwaccel", "auto",
            "-i", str(input_path),
            "-vf", filter_str,
            "-c:v", settings.TOPAZ_CODEC,
            "-b:v", settings.TOPAZ_UPSCALE_BITRATE,
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",  # Copy audio
            str(task.upscaled_output_path),
        ]

        await self._run_ffmpeg(cmd, task, "4K Upscaling")

        # Verify output
        if not task.upscaled_output_path.exists():
            raise RuntimeError(f"Upscaled output not created: {task.upscaled_output_path}")

        topaz_logger.success(f"[{task.task_id}] 4K Upscaling completed")
        topaz_logger.info(f"  Output: {task.upscaled_output_path}")

    async def _run_ffmpeg(
        self,
        cmd: list,
        task: TopazTask,
        stage_name: str
    ) -> None:
        """
        Виконує FFmpeg команду асинхронно

        Args:
            cmd: FFmpeg команда як список аргументів
            task: Поточне завдання
            stage_name: Назва етапу для логування
        """
        topaz_logger.debug(f"[{task.task_id}] Running: {' '.join(cmd)}")

        # Topaz потребує запуску з директорії встановлення
        topaz_dir = self.ffmpeg_path.parent

        # Використовуємо auto-detected шлях до моделей (або fallback)
        model_dir = self.models_dir

        # Копіюємо поточне оточення і додаємо змінні Topaz
        env = os.environ.copy()
        env["TVAI_MODEL_DIR"] = str(model_dir)
        env["TVAI_MODEL_DATA_DIR"] = str(model_dir)

        topaz_logger.debug(f"[{task.task_id}] TVAI_MODEL_DIR: {model_dir}")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(topaz_dir),  # Запускаємо з директорії Topaz
                env=env,  # Передаємо оточення з шляхом до моделей
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                raise TimeoutError(
                    f"{stage_name} timed out after {self.timeout} seconds"
                )

            if process.returncode != 0:
                error_msg = stderr.decode("utf-8", errors="replace")
                # Log full error for debugging
                topaz_logger.error(f"[{task.task_id}] FFmpeg error:\n{error_msg}")
                raise RuntimeError(f"{stage_name} failed: {error_msg[:500]}")

            # Log FFmpeg output (for debugging)
            if stdout:
                topaz_logger.debug(f"[{task.task_id}] FFmpeg stdout:\n{stdout.decode('utf-8', errors='replace')}")

        except FileNotFoundError:
            raise RuntimeError(
                f"Topaz FFmpeg not found at: {self.ffmpeg_path}\n"
                f"Please verify Topaz Video AI is installed correctly."
            )

    # ========================================================================
    # PROGRESS NOTIFICATIONS
    # ========================================================================

    async def _notify_progress(
        self,
        task: TopazTask,
        percent: float,
        message: str
    ) -> None:
        """Відправляє прогрес через callback"""
        if self.on_progress:
            progress = TopazProgress(
                task_id=task.task_id,
                scene_number=task.scene_number,
                stage=task.current_stage,
                progress_percent=percent,
                message=message,
            )
            try:
                await self.on_progress(progress)
            except Exception as e:
                topaz_logger.warning(f"Progress callback error: {e}")

    # ========================================================================
    # CLEANUP
    # ========================================================================

    async def cleanup_intermediate_files(self, task: TopazTask) -> None:
        """
        Видаляє проміжні файли після успішної обробки

        Можна викликати опціонально для економії місця
        """
        if task.fps_output_path and task.fps_output_path.exists():
            try:
                task.fps_output_path.unlink()
                topaz_logger.info(f"Deleted intermediate file: {task.fps_output_path}")
            except Exception as e:
                topaz_logger.warning(f"Failed to delete intermediate file: {e}")


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

# Global instance (created on first import)
_topaz_queue_instance: Optional[TopazQueue] = None


def get_topaz_queue() -> TopazQueue:
    """
    Повертає singleton instance TopazQueue

    Returns:
        TopazQueue instance
    """
    global _topaz_queue_instance
    if _topaz_queue_instance is None:
        _topaz_queue_instance = TopazQueue()
    return _topaz_queue_instance


# ============================================================================
# EXPORT
# ============================================================================

__all__ = [
    "TopazQueue",
    "TopazTask",
    "TopazProgress",
    "TopazStage",
    "TopazTaskStatus",
    "get_topaz_queue",
]
