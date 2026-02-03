"""
Gaussian Delay Generator

Provides human-like delays using Gaussian (normal) distribution.
"""

import asyncio
import random
from typing import Tuple, Optional

from ..config import DelayConfig


class GaussianDelay:
    """
    Generates random delays following a Gaussian distribution.

    Human reaction times and pauses follow normal distributions,
    making this more realistic than uniform random delays.
    """

    def __init__(
        self,
        mean: float,
        std_dev: float,
        min_bound: float,
        max_bound: float
    ):
        """
        Initialize delay generator.

        Args:
            mean: Mean delay in seconds (center of distribution)
            std_dev: Standard deviation (spread of distribution)
            min_bound: Minimum delay (clamp floor)
            max_bound: Maximum delay (clamp ceiling)
        """
        self.mean = mean
        self.std_dev = std_dev
        self.min_bound = min_bound
        self.max_bound = max_bound

    @classmethod
    def from_config(cls, config: DelayConfig) -> "GaussianDelay":
        """Create from DelayConfig"""
        return cls(
            mean=config.mean,
            std_dev=config.std_dev,
            min_bound=config.min_bound,
            max_bound=config.max_bound,
        )

    @classmethod
    def from_tuple(cls, params: Tuple[float, float, float, float]) -> "GaussianDelay":
        """Create from tuple (mean, std_dev, min_bound, max_bound)"""
        return cls(
            mean=params[0],
            std_dev=params[1],
            min_bound=params[2],
            max_bound=params[3],
        )

    def sample(self) -> float:
        """
        Sample a random delay from the Gaussian distribution.

        Returns:
            Delay in seconds, clamped to [min_bound, max_bound]
        """
        delay = random.gauss(self.mean, self.std_dev)
        return max(self.min_bound, min(self.max_bound, delay))

    async def wait(self) -> float:
        """
        Wait for a random delay sampled from the distribution.

        Returns:
            The actual delay that was waited (in seconds)
        """
        delay = self.sample()
        await asyncio.sleep(delay)
        return delay

    def __repr__(self) -> str:
        return (
            f"GaussianDelay(mean={self.mean}, std_dev={self.std_dev}, "
            f"min={self.min_bound}, max={self.max_bound})"
        )


# Convenience functions for common delay patterns

async def short_pause() -> float:
    """Quick reaction pause (100-300ms)"""
    delay = GaussianDelay(mean=0.2, std_dev=0.05, min_bound=0.1, max_bound=0.3)
    return await delay.wait()


async def medium_pause() -> float:
    """Medium thinking pause (500-1500ms)"""
    delay = GaussianDelay(mean=1.0, std_dev=0.25, min_bound=0.5, max_bound=1.5)
    return await delay.wait()


async def long_pause() -> float:
    """Long contemplation pause (2-5s)"""
    delay = GaussianDelay(mean=3.0, std_dev=0.8, min_bound=2.0, max_bound=5.0)
    return await delay.wait()


async def page_load_pause() -> float:
    """Wait after page loads (1-4s)"""
    delay = GaussianDelay(mean=2.5, std_dev=0.8, min_bound=1.0, max_bound=4.0)
    return await delay.wait()


async def reading_pause(word_count: int, wpm: float = 200.0) -> float:
    """
    Pause based on content length (simulating reading).

    Args:
        word_count: Approximate number of words to "read"
        wpm: Reading speed (words per minute), with variance

    Returns:
        Time waited in seconds
    """
    # Add variance to reading speed (some people read faster/slower)
    actual_wpm = random.gauss(wpm, wpm * 0.2)
    actual_wpm = max(100, min(400, actual_wpm))  # Clamp to reasonable range

    base_time = (word_count / actual_wpm) * 60  # Convert to seconds

    # Add small random variance
    delay = GaussianDelay(
        mean=base_time,
        std_dev=base_time * 0.15,
        min_bound=base_time * 0.5,
        max_bound=base_time * 2.0
    )
    return await delay.wait()
