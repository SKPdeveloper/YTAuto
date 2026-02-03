"""
Utility module for human-like automation.

Provides:
- RetryHandler: Human-like retry with recovery strategies
- with_retry: Decorator for adding retry behavior
- with_simple_retry: Simple retry decorator
- RetryContext: Context manager for manual retry control
- RetryError: Exception raised when retries are exhausted
"""

from .retry_handler import (
    RetryHandler,
    RetryError,
    RetryContext,
    with_retry,
    with_simple_retry,
)

__all__ = [
    "RetryHandler",
    "RetryError",
    "RetryContext",
    "with_retry",
    "with_simple_retry",
]
