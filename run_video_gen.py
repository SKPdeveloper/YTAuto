"""
Universal Video Generation Script

Usage:
    python run_video_gen.py <project_id>
    python run_video_gen.py proj_0f379e1a24ff
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from loguru import logger
from app.clients.adspower_client import AdsPowerClient, AdsPowerConfig
from app.clients.higgsfield_video_simple import SimpleVideoGenerator, get_pending_scenes
from app.core.config import settings


async def main(project_id: str):
    """Запустить генерацию видео для проекта."""

    # Проверить сколько сцен нужно сгенерировать
    pending = get_pending_scenes(project_id)
    if not pending:
        logger.info(f"Project {project_id}: No scenes to generate")
        return

    logger.info(f"Project {project_id}: {len(pending)} scenes to generate")
    for s in pending:
        logger.info(f"  Scene {s['scene_num']}: {s['prompt'][:50]}...")

    # Подключить браузер
    config = AdsPowerConfig(
        api_key=settings.ADSPOWER_API_KEY,
        profile_id=settings.ADSPOWER_PROFILE_ID,
        base_url=settings.ADSPOWER_BASE_URL,
    )

    browser = AdsPowerClient(config)
    await browser.start_browser()

    # Генерировать видео
    generator = SimpleVideoGenerator(browser)
    results = await generator.generate_project(project_id)

    # Итоговый отчет
    logger.info("")
    logger.info("=" * 50)
    logger.info("RESULTS:")
    for r in sorted(results, key=lambda x: x.scene_num):
        status = "OK" if r.success else f"FAIL: {r.error}"
        logger.info(f"  Scene {r.scene_num}: {status}")

    success = sum(1 for r in results if r.success)
    logger.info(f"Total: {success}/{len(results)} successful")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_video_gen.py <project_id>")
        print("Example: python run_video_gen.py proj_0f379e1a24ff")
        sys.exit(1)

    project_id = sys.argv[1]
    asyncio.run(main(project_id))
