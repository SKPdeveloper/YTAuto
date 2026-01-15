"""
Logging setup для Edible House Automator
Використовує loguru для покращеного логування з rotation
"""

import sys
from pathlib import Path
from typing import Dict, Optional
from loguru import logger
from app.core.config import settings


# ============================================================================
# LOGGER CONFIGURATION
# ============================================================================

def setup_logger() -> None:
    """
    Налаштовує loguru logger з:
    - Console output (кольоровий, форматований)
    - File output з rotation (app.log, telegram.log, topaz.log)
    - Різні рівні логування для різних модулів
    """

    # Видаляємо дефолтний handler
    logger.remove()

    # ========================================================================
    # CONSOLE OUTPUT (для розробки та debugging)
    # ========================================================================

    logger.add(
        sys.stdout,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        level=settings.LOG_LEVEL,
        colorize=True,
        backtrace=True,
        diagnose=True,
    )

    # ========================================================================
    # FILE OUTPUT - Main App Log
    # ========================================================================

    logger.add(
        settings.LOGS_DIR / "app.log",
        format=(
            "{time:YYYY-MM-DD HH:mm:ss} | "
            "{level: <8} | "
            "{name}:{function}:{line} | "
            "{message}"
        ),
        level=settings.LOG_LEVEL,
        rotation=settings.LOG_ROTATION,
        retention=settings.LOG_RETENTION,
        compression="zip",
        encoding="utf-8",
        backtrace=True,
        diagnose=True,
    )

    # ========================================================================
    # FILE OUTPUT - Telegram Bot Log
    # ========================================================================

    logger.add(
        settings.LOGS_DIR / "telegram.log",
        format=(
            "{time:YYYY-MM-DD HH:mm:ss} | "
            "{level: <8} | "
            "{message}"
        ),
        level="INFO",
        rotation=settings.LOG_ROTATION,
        retention=settings.LOG_RETENTION,
        compression="zip",
        encoding="utf-8",
        filter=lambda record: "telegram" in record["name"].lower(),
    )

    # ========================================================================
    # FILE OUTPUT - Topaz Queue Log
    # ========================================================================

    logger.add(
        settings.LOGS_DIR / "topaz.log",
        format=(
            "{time:YYYY-MM-DD HH:mm:ss} | "
            "{level: <8} | "
            "{message}"
        ),
        level="INFO",
        rotation=settings.LOG_ROTATION,
        retention=settings.LOG_RETENTION,
        compression="zip",
        encoding="utf-8",
        filter=lambda record: "topaz" in record["name"].lower(),
    )

    # ========================================================================
    # FILE OUTPUT - API Calls Log (Higgsfield, Gemini)
    # ========================================================================

    logger.add(
        settings.LOGS_DIR / "api.log",
        format=(
            "{time:YYYY-MM-DD HH:mm:ss} | "
            "{level: <8} | "
            "{name} | "
            "{message}"
        ),
        level="DEBUG",
        rotation=settings.LOG_ROTATION,
        retention=settings.LOG_RETENTION,
        compression="zip",
        encoding="utf-8",
        filter=lambda record: any(
            keyword in record["name"].lower()
            for keyword in ["higgsfield", "gemini", "claude", "visual", "validator", "content"]
        ),
    )

    logger.info("Logger initialized successfully")
    logger.debug(f"Log directory: {settings.LOGS_DIR}")
    logger.debug(f"Log level: {settings.LOG_LEVEL}")


# ============================================================================
# MODULE-SPECIFIC LOGGERS
# ============================================================================

def get_module_logger(module_name: str):
    """
    Створює logger для конкретного модуля

    Args:
        module_name: Назва модуля (наприклад, "visual_engine", "telegram_bot")

    Returns:
        logger instance з правильним контекстом

    Usage:
        logger = get_module_logger(__name__)
        logger.info("Message from module")
    """
    return logger.bind(module=module_name)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def log_api_call(
    service: str,
    endpoint: str,
    method: str = "POST",
    status: str = "started",
    **kwargs
) -> None:
    """
    Логує API виклик з деталями

    Args:
        service: Назва сервісу (Higgsfield, Gemini, Claude)
        endpoint: API endpoint
        method: HTTP method
        status: started | success | failed
        **kwargs: Додаткові параметри для логування
    """
    extra_info = " | ".join(f"{k}={v}" for k, v in kwargs.items())
    log_msg = f"[{service}] {method} {endpoint} - {status.upper()}"

    if extra_info:
        log_msg += f" | {extra_info}"

    if status == "failed":
        logger.error(log_msg)
    elif status == "success":
        logger.success(log_msg)
    else:
        logger.info(log_msg)


def log_scene_progress(
    project_id: str,
    scene_num: int,
    status: str,
    details: str = ""
) -> None:
    """
    Логує прогрес обробки сцени

    Args:
        project_id: ID проєкту
        scene_num: Номер сцени
        status: Поточний статус
        details: Додаткові деталі
    """
    msg = f"[Project {project_id}] Scene #{scene_num} - {status}"
    if details:
        msg += f" | {details}"

    logger.info(msg)


# ============================================================================
# PROJECT-SPECIFIC LOGGER
# ============================================================================

# Хранилище handler_id для каждого проекта
_project_handlers: Dict[str, int] = {}


def setup_project_logger(project_id: str, logs_dir: Path) -> None:
    """
    Настроить логирование в папку конкретного проекта.

    Создаёт отдельный лог-файл для проекта в projects/{project_id}/logs/

    Args:
        project_id: ID проекта
        logs_dir: Путь к директории логов проекта

    Usage:
        from app.core.paths import get_project_logs_path

        logs_dir = get_project_logs_path(project_id)
        setup_project_logger(project_id, logs_dir)
    """
    # Если логгер для этого проекта уже существует, пропускаем
    if project_id in _project_handlers:
        logger.debug(f"Project logger already exists for {project_id}")
        return

    # Создаём директорию если не существует
    logs_dir.mkdir(parents=True, exist_ok=True)

    log_file = logs_dir / "pipeline.log"

    # Добавляем handler для этого проекта
    handler_id = logger.add(
        log_file,
        format=(
            "{time:YYYY-MM-DD HH:mm:ss} | "
            "{level: <8} | "
            "{name}:{function}:{line} | "
            "{message}"
        ),
        level="DEBUG",
        rotation="10 MB",
        retention="7 days",
        compression="zip",
        encoding="utf-8",
        backtrace=True,
        diagnose=True,
        # Фильтруем только сообщения, содержащие project_id
        filter=lambda record: project_id in record["message"] or
                             record["extra"].get("project_id") == project_id,
    )

    _project_handlers[project_id] = handler_id
    logger.info(f"Project logger initialized: {log_file}")


def get_project_logger(project_id: str):
    """
    Получить logger с привязкой к конкретному проекту.

    Args:
        project_id: ID проекта

    Returns:
        Logger instance с контекстом project_id

    Usage:
        plog = get_project_logger("proj_abc123")
        plog.info("Processing started")  # Автоматически попадёт в лог проекта
    """
    return logger.bind(project_id=project_id)


def remove_project_logger(project_id: str) -> None:
    """
    Удалить logger для проекта (после завершения обработки).

    Args:
        project_id: ID проекта
    """
    if project_id in _project_handlers:
        handler_id = _project_handlers.pop(project_id)
        logger.remove(handler_id)
        logger.debug(f"Project logger removed for {project_id}")


# ============================================================================
# AUTO-INITIALIZATION
# ============================================================================

# Автоматично налаштовуємо logger при імпорті модуля
setup_logger()


# ============================================================================
# EXPORT
# ============================================================================

__all__ = [
    "logger",
    "setup_logger",
    "get_module_logger",
    "log_api_call",
    "log_scene_progress",
    "setup_project_logger",
    "get_project_logger",
    "remove_project_logger",
]
