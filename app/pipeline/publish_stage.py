"""
Publish Stage - Автоматична публікація відео на YouTube

11-й етап пайплайну, який запускається після CleanupStage.
Публікує фінальне відео на YouTube канал, вказаний у project_brief.json.

Функціонал:
1. Завантаження відео на YouTube через API
2. Встановлення метаданих (title, description, tags)
3. Додавання закріпленого коментаря (якщо AdsPower доступний)
4. Архівування проекту (опціонально)

Вимоги:
- project_brief.json з publish_config.target_channel
- final_video.mp4 або final_4k.mp4
- Авторизований канал у config/channels/
"""

import sys
from pathlib import Path
from typing import Optional, Tuple

from loguru import logger

from app.pipeline.base import BasePipelineStage, StageResult, StageStatus
from app.api.schemas import ProjectData, ProjectStatus

# Додаємо шлях до src для імпорту publisher
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class PublishStage(BasePipelineStage):
    """
    Stage 11: YouTube Publication

    Публікує готове відео на YouTube канал.
    Запускається після CleanupStage, коли відео повністю готове.

    Конфігурація береться з project_brief.json:
    - publish_config.target_channel - ID каналу
    - publish_config.auto_schedule - автопланування
    - youtube.title, description, tags - метадані
    """

    name = "publish"
    description = "Публікація відео на YouTube"

    async def execute(self) -> StageResult:
        """
        Виконує публікацію відео на YouTube.

        Returns:
            StageResult з результатом публікації
        """
        project_dir = Path(self.project.project_dir)
        project_id = self.project.project_id

        logger.info(f"[{project_id}] Запуск етапу публікації на YouTube...")

        # Перевіряємо наявність project_brief.json
        brief_path = project_dir / "project_brief.json"
        if not brief_path.exists():
            return StageResult(
                status=StageStatus.FAILED,
                error="project_brief.json не знайдено"
            )

        # Перевіряємо наявність фінального відео
        video_path = self._find_video_file(project_dir)
        if not video_path:
            return StageResult(
                status=StageStatus.FAILED,
                error="Фінальне відео не знайдено (final_video.mp4 або final_4k.mp4)"
            )

        logger.info(f"[{project_id}] Знайдено відео: {video_path.name}")

        try:
            # Імпортуємо Publisher (lazy import для уникнення циклічних залежностей)
            from src.publisher.publisher import Publisher
            from src.publisher.config_manager import get_config_manager

            # Перевіряємо конфігурацію каналу
            config_manager = get_config_manager()
            brief = config_manager.load_project_brief(project_id)

            if not brief:
                return StageResult(
                    status=StageStatus.FAILED,
                    error="Не вдалося завантажити project_brief.json"
                )

            if not brief.publish_config:
                return StageResult(
                    status=StageStatus.SKIPPED,
                    message="publish_config не вказано - публікація пропущена"
                )

            target_channel = brief.publish_config.target_channel
            if not target_channel:
                return StageResult(
                    status=StageStatus.SKIPPED,
                    message="target_channel не вказано - публікація пропущена"
                )

            # Перевіряємо чи канал авторизований
            if not config_manager.channel_is_authorized(target_channel):
                return StageResult(
                    status=StageStatus.FAILED,
                    error=f"Канал {target_channel} не авторизований. Запустіть: python -m src.publisher.main channel auth {target_channel}"
                )

            logger.info(f"[{project_id}] Публікація на канал: {target_channel}")

            # Публікуємо
            publisher = Publisher(config_manager=config_manager)
            success, status = publisher.publish(
                project_id=project_id,
                skip_archive=True,  # Архівування контролюється окремо
            )

            if success:
                video_url = status.video_url or f"https://youtube.com/shorts/{status.video_id}"
                logger.success(f"[{project_id}] Опубліковано: {video_url}")

                # Надсилаємо повідомлення клієнтам
                if self.notifier:
                    await self.notifier.send_stage_completed(
                        project_id=project_id,
                        stage="publish",
                        details={
                            "video_id": status.video_id,
                            "video_url": video_url,
                            "channel": target_channel,
                        }
                    )

                return StageResult(
                    status=StageStatus.COMPLETED,
                    data={
                        "video_id": status.video_id,
                        "video_url": video_url,
                        "channel_id": target_channel,
                        "comment_id": status.comment_id,
                    }
                )
            else:
                logger.error(f"[{project_id}] Помилка публікації: {status.error}")
                return StageResult(
                    status=StageStatus.FAILED,
                    error=status.error or "Невідома помилка публікації"
                )

        except ImportError as e:
            logger.error(f"[{project_id}] Модуль publisher не знайдено: {e}")
            return StageResult(
                status=StageStatus.FAILED,
                error=f"Помилка імпорту: {e}. Встановіть залежності: pip install typer rich google-api-python-client"
            )

        except Exception as e:
            logger.error(f"[{project_id}] Виняток при публікації: {e}")
            return StageResult(
                status=StageStatus.FAILED,
                error=str(e)
            )

    def _find_video_file(self, project_dir: Path) -> Optional[Path]:
        """
        Знаходить фінальне відео для завантаження.

        Пріоритет:
        1. upscaled/scene_0_4k.mp4 (4K версія)
        2. final_4k.mp4
        3. final_video.mp4

        Args:
            project_dir: Шлях до директорії проекту

        Returns:
            Path до відео або None
        """
        # Пріоритетний список файлів
        candidates = [
            project_dir / "upscaled" / "scene_0_4k.mp4",
            project_dir / "final_4k.mp4",
            project_dir / "final_video.mp4",
        ]

        for path in candidates:
            if path.exists():
                return path

        return None
