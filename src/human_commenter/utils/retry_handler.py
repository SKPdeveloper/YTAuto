"""
Human-Like Retry Handler

Implements natural recovery patterns when actions fail.
Real humans don't retry instantly - they wait, try different approaches,
and give up after reasonable attempts.

Features:
- Exponential backoff with jitter
- Multiple recovery strategies (wait, refresh, scroll)
- Human-like timing variations
- Decorator for easy use
"""

import asyncio
import random
import logging
from typing import Callable, TypeVar, List, Optional, Any
from functools import wraps

T = TypeVar('T')

logger = logging.getLogger(__name__)


class RetryError(Exception):
    """Raised when all retry attempts are exhausted."""

    def __init__(self, message: str, last_error: Exception, attempts: int):
        super().__init__(message)
        self.last_error = last_error
        self.attempts = attempts


class RetryHandler:
    """
    Retry with human-like delays and recovery actions.

    Real users don't retry instantly - they:
    - Wait a moment after failure
    - Try different approaches (refresh, scroll)
    - Give up after reasonable attempts

    This handler simulates that behavior with:
    - Exponential backoff (increasing delays)
    - Jitter (randomized timing)
    - Recovery strategies
    """

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 2.0,
        max_delay: float = 30.0,
        exponential_base: float = 2.0,
        jitter: float = 0.2
    ):
        """
        Initialize retry handler.

        Args:
            max_attempts: Maximum number of attempts before giving up
            base_delay: Initial delay after first failure (seconds)
            max_delay: Maximum delay between retries (seconds)
            exponential_base: Base for exponential backoff
            jitter: Random variation factor (0.2 = ±20%)
        """
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter

    async def execute(
        self,
        action: Callable[[], Any],
        recovery_strategies: Optional[List[str]] = None,
        page: Any = None,
        on_retry: Optional[Callable[[int, Exception], None]] = None
    ) -> T:
        """
        Execute action with retries.

        Args:
            action: Async function to execute
            recovery_strategies: List of strategies to use between retries
                                 Options: 'wait', 'refresh', 'scroll', 'click_away'
            page: Playwright page for recovery actions (optional)
            on_retry: Callback called on each retry with (attempt, exception)

        Returns:
            Result of successful action

        Raises:
            RetryError: If all attempts fail
        """
        recovery_strategies = recovery_strategies or ['wait', 'refresh', 'scroll']
        last_error = None

        for attempt in range(self.max_attempts):
            try:
                return await action()

            except Exception as e:
                last_error = e
                logger.warning(f"Attempt {attempt + 1}/{self.max_attempts} failed: {e}")

                # Call retry callback if provided
                if on_retry:
                    on_retry(attempt + 1, e)

                # Don't retry after last attempt
                if attempt >= self.max_attempts - 1:
                    break

                # Perform recovery
                await self._recover(attempt, recovery_strategies, page)

        raise RetryError(
            f"All {self.max_attempts} attempts failed",
            last_error,
            self.max_attempts
        )

    async def _recover(
        self,
        attempt: int,
        strategies: List[str],
        page: Any
    ) -> None:
        """
        Perform recovery action between retries.

        Args:
            attempt: Current attempt number (0-based)
            strategies: Available recovery strategies
            page: Playwright page (may be None)
        """
        # Calculate delay with exponential backoff and jitter
        delay = min(
            self.base_delay * (self.exponential_base ** attempt),
            self.max_delay
        )
        delay *= random.uniform(1 - self.jitter, 1 + self.jitter)

        # Select recovery strategy
        strategy = random.choice(strategies)
        logger.debug(f"Recovery strategy: {strategy}, delay: {delay:.2f}s")

        if strategy == 'wait':
            # Just wait (human thinking/frustration pause)
            await asyncio.sleep(delay)

        elif strategy == 'refresh' and page:
            # Refresh the page (common human recovery)
            await asyncio.sleep(delay * 0.3)
            try:
                await page.reload(wait_until="domcontentloaded")
            except Exception:
                pass  # Refresh failed, continue anyway
            await asyncio.sleep(delay * 0.7)

        elif strategy == 'scroll' and page:
            # Scroll a bit (sometimes helps with lazy-loaded elements)
            await asyncio.sleep(delay * 0.2)
            try:
                scroll_amount = random.choice([-200, -100, 100, 200])
                await page.mouse.wheel(0, scroll_amount)
            except Exception:
                pass
            await asyncio.sleep(delay * 0.8)

        elif strategy == 'click_away' and page:
            # Click somewhere neutral (deselect, close popups)
            await asyncio.sleep(delay * 0.3)
            try:
                viewport = page.viewport_size
                if viewport:
                    # Click in a neutral area (top-left corner area)
                    x = random.randint(50, 150)
                    y = random.randint(50, 150)
                    await page.mouse.click(x, y)
            except Exception:
                pass
            await asyncio.sleep(delay * 0.7)

        else:
            # Fallback: just wait
            await asyncio.sleep(delay)

    def calculate_delay(self, attempt: int) -> float:
        """
        Calculate delay for a given attempt number.

        Useful for previewing retry timing.

        Args:
            attempt: Attempt number (0-based)

        Returns:
            Delay in seconds
        """
        delay = min(
            self.base_delay * (self.exponential_base ** attempt),
            self.max_delay
        )
        return delay * random.uniform(1 - self.jitter, 1 + self.jitter)


def with_retry(
    max_attempts: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
    recovery_strategies: Optional[List[str]] = None
):
    """
    Decorator for adding retry behavior to async methods.

    Usage:
        class MyClass:
            @with_retry(max_attempts=3, base_delay=1.0)
            async def flaky_operation(self):
                # This will be retried up to 3 times
                ...

    Args:
        max_attempts: Maximum retry attempts
        base_delay: Initial delay after failure
        max_delay: Maximum delay between retries
        recovery_strategies: List of recovery strategies

    Returns:
        Decorated function
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            handler = RetryHandler(
                max_attempts=max_attempts,
                base_delay=base_delay,
                max_delay=max_delay
            )

            async def action():
                return await func(self, *args, **kwargs)

            # Try to get page from self for recovery actions
            page = getattr(self, 'page', None)
            strategies = recovery_strategies or ['wait', 'scroll']

            try:
                return await handler.execute(
                    action,
                    recovery_strategies=strategies,
                    page=page
                )
            except RetryError as e:
                # Re-raise the original error
                raise e.last_error from e

        return wrapper
    return decorator


def with_simple_retry(max_attempts: int = 3, delay: float = 1.0):
    """
    Simple retry decorator without recovery strategies.

    Just retries with fixed delay, no fancy recovery.

    Args:
        max_attempts: Maximum retry attempts
        delay: Fixed delay between retries

    Returns:
        Decorated function
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_error = None

            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(delay * random.uniform(0.8, 1.2))

            raise last_error

        return wrapper
    return decorator


class RetryContext:
    """
    Context manager for retry operations.

    Usage:
        async with RetryContext(max_attempts=3) as retry:
            while retry.should_continue():
                try:
                    result = await flaky_operation()
                    break
                except Exception as e:
                    await retry.handle_failure(e)
    """

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 2.0,
        page: Any = None
    ):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.page = page
        self._attempt = 0
        self._last_error: Optional[Exception] = None
        self._handler = RetryHandler(max_attempts=max_attempts, base_delay=base_delay)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    def should_continue(self) -> bool:
        """Check if we should continue retrying."""
        return self._attempt < self.max_attempts

    async def handle_failure(self, error: Exception) -> None:
        """
        Handle a failure and prepare for retry.

        Args:
            error: The exception that occurred

        Raises:
            RetryError: If no more attempts remaining
        """
        self._last_error = error
        self._attempt += 1

        logger.warning(f"Attempt {self._attempt}/{self.max_attempts} failed: {error}")

        if self._attempt >= self.max_attempts:
            raise RetryError(
                f"All {self.max_attempts} attempts failed",
                error,
                self.max_attempts
            )

        # Wait before next attempt
        await self._handler._recover(
            self._attempt - 1,
            ['wait', 'scroll'],
            self.page
        )

    @property
    def attempt(self) -> int:
        """Current attempt number (1-based)."""
        return self._attempt + 1

    @property
    def last_error(self) -> Optional[Exception]:
        """The last error that occurred."""
        return self._last_error
