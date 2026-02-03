"""
Bimodal Delay Generator

Generates realistic human-like delays based on cognitive psychology research.
Uses bimodal distribution matching real human response patterns.

Research basis: Card, Moran & Newell (1983) "The Psychology of Human-Computer Interaction"
- Fast mode (70%): Automatic/reflexive actions (~0.1s)
- Slow mode (30%): Deliberate/thinking actions (~0.5s)

Single Gaussian distribution is unrealistic for human behavior simulation.
"""

import asyncio
import random
from typing import Tuple, List, Optional
from enum import Enum
from dataclasses import dataclass


class ActionMode(Enum):
    """Human cognitive action modes."""
    AUTOMATIC = "automatic"  # Fast, reflexive actions
    DELIBERATE = "deliberate"  # Slow, thinking actions


@dataclass
class BimodalConfig:
    """Configuration for bimodal delay distribution."""
    fast_mean: float = 0.08
    fast_std: float = 0.025
    slow_mean: float = 0.35
    slow_std: float = 0.12
    fast_probability: float = 0.70
    min_bound: float = 0.03
    max_bound: float = 2.0


class BimodalDelay:
    """
    Generates delays with bimodal distribution matching human patterns.

    Unlike simple Gaussian delays, this creates two distinct modes:
    - Fast mode: Quick reflexive actions (majority of actions)
    - Slow mode: Deliberate thinking actions

    This better matches real human behavior where people alternate
    between "autopilot" mode and conscious decision-making.
    """

    def __init__(self, config: BimodalConfig = None):
        """
        Initialize bimodal delay generator.

        Args:
            config: Configuration for the distribution. Uses defaults if None.
        """
        self.config = config or BimodalConfig()
        self._mode_history: List[ActionMode] = []
        self._max_consecutive = 6  # Prevent unrealistic streaks
        self._stats = {"automatic": 0, "deliberate": 0}  # Track mode distribution

    @classmethod
    def for_typing(cls) -> "BimodalDelay":
        """
        Optimized for inter-keystroke intervals.

        Typing has faster base speed with occasional pauses
        when thinking about the next word.
        """
        return cls(BimodalConfig(
            fast_mean=0.07,
            fast_std=0.02,
            slow_mean=0.22,
            slow_std=0.06,
            fast_probability=0.75,
            min_bound=0.03,
            max_bound=0.6
        ))

    @classmethod
    def for_clicks(cls) -> "BimodalDelay":
        """
        Optimized for between-click intervals.

        Clicks have more deliberation - users often pause
        before clicking important buttons.
        """
        return cls(BimodalConfig(
            fast_mean=0.15,
            fast_std=0.05,
            slow_mean=0.50,
            slow_std=0.15,
            fast_probability=0.65,
            min_bound=0.08,
            max_bound=1.5
        ))

    @classmethod
    def for_navigation(cls) -> "BimodalDelay":
        """
        Optimized for page navigation decisions.

        Navigation involves more thinking - deciding where to go,
        reading content, processing information.
        """
        return cls(BimodalConfig(
            fast_mean=0.8,
            fast_std=0.2,
            slow_mean=2.5,
            slow_std=0.8,
            fast_probability=0.60,
            min_bound=0.3,
            max_bound=5.0
        ))

    @classmethod
    def for_reading(cls) -> "BimodalDelay":
        """
        Optimized for reading/scanning content.

        Reading alternates between quick scanning and
        slower careful reading of interesting content.
        """
        return cls(BimodalConfig(
            fast_mean=0.5,
            fast_std=0.15,
            slow_mean=1.8,
            slow_std=0.5,
            fast_probability=0.55,
            min_bound=0.2,
            max_bound=4.0
        ))

    def _should_use_fast(self) -> bool:
        """
        Determine mode with rhythm awareness to prevent unrealistic streaks.

        Real humans don't have 10+ consecutive fast or slow actions.
        This adds natural rhythm variation.
        """
        if len(self._mode_history) >= self._max_consecutive:
            recent = self._mode_history[-self._max_consecutive:]
            # Force mode switch if too many consecutive same-mode actions
            if all(m == ActionMode.AUTOMATIC for m in recent):
                return False
            if all(m == ActionMode.DELIBERATE for m in recent):
                return True

        return random.random() < self.config.fast_probability

    def sample(self, logger=None) -> Tuple[float, ActionMode]:
        """
        Sample delay value and mode.

        Args:
            logger: Optional analytics logger for stats logging

        Returns:
            Tuple of (delay_seconds, action_mode)
        """
        use_fast = self._should_use_fast()

        if use_fast:
            delay = random.gauss(self.config.fast_mean, self.config.fast_std)
            mode = ActionMode.AUTOMATIC
        else:
            delay = random.gauss(self.config.slow_mean, self.config.slow_std)
            mode = ActionMode.DELIBERATE

        # Clamp to bounds
        delay = max(self.config.min_bound, min(self.config.max_bound, delay))

        # Update history for rhythm awareness
        self._mode_history.append(mode)
        if len(self._mode_history) > 20:
            self._mode_history.pop(0)

        # Track stats
        self._stats[mode.value] += 1

        # Log running stats every 10 samples
        total = sum(self._stats.values())
        if total % 10 == 0 and total > 0:
            try:
                from ..safety.analytics_logger import get_analytics, EventType
                analytics = logger or get_analytics()
                if analytics:
                    auto_pct = self._stats["automatic"] / total
                    analytics.log(EventType.BIMODAL_STATS, {
                        "total_samples": total,
                        "automatic_count": self._stats["automatic"],
                        "automatic_pct": round(auto_pct, 3),
                        "expected_pct": self.config.fast_probability
                    })
            except ImportError:
                pass

        return (delay, mode)

    def get_stats(self) -> dict:
        """
        Get mode distribution statistics.

        Returns:
            dict with automatic_ratio, deliberate_ratio, total samples
        """
        total = sum(self._stats.values())
        if total == 0:
            return {
                "automatic_ratio": 0.0,
                "deliberate_ratio": 0.0,
                "total": 0,
                "config_fast_probability": self.config.fast_probability
            }

        return {
            "automatic_ratio": round(self._stats["automatic"] / total, 3),
            "deliberate_ratio": round(self._stats["deliberate"] / total, 3),
            "total": total,
            "config_fast_probability": self.config.fast_probability
        }

    def reset_stats(self) -> None:
        """Reset mode distribution statistics."""
        self._stats = {"automatic": 0, "deliberate": 0}

    def sample_value(self) -> float:
        """
        Sample just the delay value.

        Returns:
            Delay in seconds
        """
        return self.sample()[0]

    async def wait(self, category: Optional[str] = None) -> float:
        """
        Wait for sampled delay duration.

        Args:
            category: Optional category for logging (e.g., "typing", "click", "navigation")

        Returns:
            The actual delay that was waited (in seconds)
        """
        delay, mode = self.sample()
        await asyncio.sleep(delay)

        # Log bimodal delay (lazy import to avoid circular dependency)
        try:
            from ..safety.analytics_logger import get_analytics
            analytics = get_analytics()
            if analytics:
                analytics.log_bimodal_delay(delay * 1000, mode.value, category or "general")
        except ImportError:
            pass

        return delay

    def reset_history(self) -> None:
        """Reset mode history (useful between distinct action sequences)."""
        self._mode_history.clear()

    def get_stats(self) -> dict:
        """
        Get statistics about recent mode distribution.

        Returns:
            Dict with mode counts and percentages
        """
        if not self._mode_history:
            return {"automatic": 0, "deliberate": 0, "total": 0}

        auto_count = sum(1 for m in self._mode_history if m == ActionMode.AUTOMATIC)
        delib_count = len(self._mode_history) - auto_count
        total = len(self._mode_history)

        return {
            "automatic": auto_count,
            "deliberate": delib_count,
            "total": total,
            "automatic_pct": auto_count / total * 100,
            "deliberate_pct": delib_count / total * 100,
        }

    def __repr__(self) -> str:
        return (
            f"BimodalDelay(fast={self.config.fast_mean:.2f}s/{self.config.fast_probability:.0%}, "
            f"slow={self.config.slow_mean:.2f}s/{1-self.config.fast_probability:.0%})"
        )


# Convenience functions for common delay patterns

async def short_pause() -> float:
    """Quick reaction pause (bimodal: 80-250ms)."""
    delay = BimodalDelay(BimodalConfig(
        fast_mean=0.10,
        fast_std=0.03,
        slow_mean=0.25,
        slow_std=0.08,
        fast_probability=0.70,
        min_bound=0.05,
        max_bound=0.5
    ))
    return await delay.wait(category="short_pause")


async def medium_pause() -> float:
    """Medium thinking pause (bimodal: 400ms-1.2s)."""
    delay = BimodalDelay(BimodalConfig(
        fast_mean=0.4,
        fast_std=0.1,
        slow_mean=1.2,
        slow_std=0.3,
        fast_probability=0.65,
        min_bound=0.2,
        max_bound=2.0
    ))
    return await delay.wait(category="medium_pause")


async def long_pause() -> float:
    """Long contemplation pause (bimodal: 1.5-4s)."""
    delay = BimodalDelay(BimodalConfig(
        fast_mean=1.5,
        fast_std=0.4,
        slow_mean=4.0,
        slow_std=1.0,
        fast_probability=0.55,
        min_bound=0.8,
        max_bound=6.0
    ))
    return await delay.wait(category="long_pause")


async def page_load_pause() -> float:
    """Wait after page loads (bimodal: 1-4s)."""
    delay = BimodalDelay(BimodalConfig(
        fast_mean=1.5,
        fast_std=0.5,
        slow_mean=3.5,
        slow_std=0.8,
        fast_probability=0.60,
        min_bound=0.8,
        max_bound=5.0
    ))
    return await delay.wait(category="page_load")


async def reading_pause(word_count: int, wpm: float = 200.0) -> float:
    """
    Pause based on content length (simulating reading).

    Uses bimodal distribution to simulate alternating between
    scanning (fast) and careful reading (slow).

    Args:
        word_count: Approximate number of words to "read"
        wpm: Base reading speed (words per minute)

    Returns:
        Time waited in seconds
    """
    # Calculate base reading time
    base_time = (word_count / wpm) * 60  # Convert to seconds

    # Create bimodal delay scaled to content length
    delay = BimodalDelay(BimodalConfig(
        fast_mean=base_time * 0.7,
        fast_std=base_time * 0.15,
        slow_mean=base_time * 1.5,
        slow_std=base_time * 0.3,
        fast_probability=0.60,
        min_bound=base_time * 0.3,
        max_bound=base_time * 3.0
    ))
    return await delay.wait(category="reading")
