"""
Safe Logging Module

Provides logging that automatically redacts sensitive data like
video IDs, profile IDs, and personal information.
"""

import re
import logging
from typing import Any, Optional, Dict
from functools import wraps

from loguru import logger as loguru_logger


# Patterns to redact
REDACTION_PATTERNS = [
    # YouTube video IDs (11 characters)
    (r'\b[A-Za-z0-9_-]{11}\b', '[VIDEO_ID]'),
    # AdsPower profile IDs
    (r'\b[a-z0-9]{8}\b', '[PROFILE_ID]'),
    # IP addresses
    (r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '[IP_ADDR]'),
    # Email-like patterns
    (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL]'),
]


class SafeLogger:
    """
    Logger wrapper that redacts sensitive information.

    When log_sensitive=False (default), sensitive data patterns
    are replaced with placeholders before logging.
    """

    def __init__(self, name: str, log_sensitive: bool = False):
        self.name = name
        self.log_sensitive = log_sensitive
        self._logger = loguru_logger.bind(module=name)

    def _redact(self, message: str) -> str:
        """Redact sensitive patterns from message"""
        if self.log_sensitive:
            return message

        result = message
        for pattern, replacement in REDACTION_PATTERNS:
            result = re.sub(pattern, replacement, result)
        return result

    def _format_message(self, message: str, *args, **kwargs) -> str:
        """Format message with arguments, then redact"""
        if args:
            try:
                formatted = message % args
            except (TypeError, ValueError):
                formatted = f"{message} {args}"
        elif kwargs:
            try:
                formatted = message.format(**kwargs)
            except (KeyError, ValueError):
                formatted = f"{message} {kwargs}"
        else:
            formatted = message

        return self._redact(formatted)

    def debug(self, message: str, *args, **kwargs) -> None:
        """Log debug message with redaction"""
        self._logger.debug(self._format_message(message, *args, **kwargs))

    def info(self, message: str, *args, **kwargs) -> None:
        """Log info message with redaction"""
        self._logger.info(self._format_message(message, *args, **kwargs))

    def warning(self, message: str, *args, **kwargs) -> None:
        """Log warning message with redaction"""
        self._logger.warning(self._format_message(message, *args, **kwargs))

    def error(self, message: str, *args, **kwargs) -> None:
        """Log error message with redaction"""
        self._logger.error(self._format_message(message, *args, **kwargs))

    def success(self, message: str, *args, **kwargs) -> None:
        """Log success message with redaction"""
        self._logger.success(self._format_message(message, *args, **kwargs))

    def exception(self, message: str, *args, **kwargs) -> None:
        """Log exception with redaction"""
        self._logger.exception(self._format_message(message, *args, **kwargs))

    def bind(self, **kwargs) -> "SafeLogger":
        """Create a child logger with bound context"""
        new_logger = SafeLogger(self.name, self.log_sensitive)
        new_logger._logger = self._logger.bind(**kwargs)
        return new_logger


# Module-level loggers cache
_loggers: Dict[str, SafeLogger] = {}
_log_sensitive: bool = False


def configure_logging(log_sensitive: bool = False) -> None:
    """
    Configure global logging settings.

    Args:
        log_sensitive: If True, don't redact sensitive data
    """
    global _log_sensitive
    _log_sensitive = log_sensitive


def get_logger(name: str) -> SafeLogger:
    """
    Get a SafeLogger instance for a module.

    Args:
        name: Module name (typically __name__)

    Returns:
        SafeLogger instance
    """
    if name not in _loggers:
        _loggers[name] = SafeLogger(name, _log_sensitive)
    return _loggers[name]


def log_action(action_name: str):
    """
    Decorator to log function entry/exit.

    Usage:
        @log_action("clicking element")
        async def click_element(self, selector):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            logger = get_logger(func.__module__)
            logger.debug(f"Starting: {action_name}")
            try:
                result = await func(*args, **kwargs)
                logger.debug(f"Completed: {action_name}")
                return result
            except Exception as e:
                logger.error(f"Failed: {action_name} - {e}")
                raise
        return wrapper
    return decorator
