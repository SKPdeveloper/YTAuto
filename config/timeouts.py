"""
Centralized timeout and retry configuration for the pipeline.

All timing-related constants should be defined here for easy tuning.

Includes HumanLikeDelay for simulating natural user interaction patterns
to avoid detection and rate limiting.
"""

import random
from dataclasses import dataclass
from typing import Tuple


# ============================================================================
# HUMAN-LIKE DELAYS (Anti-detection)
# ============================================================================

@dataclass(frozen=True)
class HumanLikeDelay:
    """
    Simulates human-like interaction timing with randomization.

    Usage:
        delay = HumanLikeDelay(100, 300)  # 100-300ms
        await asyncio.sleep(delay.get())  # Random 0.1-0.3 seconds
    """
    min_ms: int
    max_ms: int

    def get(self) -> float:
        """Returns random delay in seconds"""
        return random.randint(self.min_ms, self.max_ms) / 1000

    def get_ms(self) -> int:
        """Returns random delay in milliseconds"""
        return random.randint(self.min_ms, self.max_ms)

    @property
    def range(self) -> Tuple[float, float]:
        """Returns (min, max) in seconds"""
        return (self.min_ms / 1000, self.max_ms / 1000)


@dataclass(frozen=True)
class InteractionDelays:
    """
    Human-like delays for browser interactions.
    Simulates natural typing, clicking, and navigation patterns.
    """
    # Mouse movements and clicks
    BEFORE_CLICK: HumanLikeDelay = HumanLikeDelay(100, 300)     # 0.1-0.3s before clicking
    AFTER_CLICK: HumanLikeDelay = HumanLikeDelay(200, 500)      # 0.2-0.5s after clicking

    # Typing simulation
    CHAR_TYPING: HumanLikeDelay = HumanLikeDelay(30, 80)        # 30-80ms per character
    WORD_PAUSE: HumanLikeDelay = HumanLikeDelay(100, 300)       # Pause between words
    FIELD_SWITCH: HumanLikeDelay = HumanLikeDelay(500, 1500)    # Between form fields

    # Page navigation
    PAGE_THINK: HumanLikeDelay = HumanLikeDelay(1000, 3000)     # 1-3s "thinking" after load
    SCROLL_PAUSE: HumanLikeDelay = HumanLikeDelay(300, 800)     # Between scroll actions

    # Operation gaps
    BETWEEN_ACTIONS: HumanLikeDelay = HumanLikeDelay(500, 1500)  # Generic action gap
    BETWEEN_UPLOADS: HumanLikeDelay = HumanLikeDelay(1000, 2000) # Between file uploads


# ============================================================================
# BROWSER TIMEOUTS
# ============================================================================

@dataclass(frozen=True)
class BrowserTimeouts:
    """Browser and page interaction timeouts (seconds)"""
    BROWSER_START: int = 30          # AdsPower browser startup
    PAGE_LOAD: int = 15              # Web page navigation
    ELEMENT_WAIT: int = 10           # DOM element appearance
    UI_READY_WAIT: int = 30          # Full UI initialization after page load


# ============================================================================
# GENERATION TIMEOUTS
# ============================================================================

@dataclass(frozen=True)
class ImageTimeouts:
    """Image generation timeouts (seconds)"""
    GENERATION: int = 120            # Single image generation
    PRIMARY_GENERATION: int = 180    # 4 candidates for PRIMARY
    BATCH_GENERATION: int = 300      # Batch of remaining images (scenes 2-N)
    DOWNLOAD: int = 30               # Image download from CDN
    POLL_INTERVAL: int = 10          # Status check interval


@dataclass(frozen=True)
class VideoTimeouts:
    """Video generation timeouts (seconds)"""
    GENERATION: int = 300            # Single video generation (5 min)
    BATCH_GENERATION: int = 900      # Batch of 6-10 videos (15 min)
    DOWNLOAD: int = 60               # Video download (larger files)
    POLL_INTERVAL: int = 15          # Status check interval
    INITIAL_WAIT: int = 300          # Initial wait before polling (5 min)


# ============================================================================
# COOLDOWNS
# ============================================================================

@dataclass(frozen=True)
class CooldownTimes:
    """Cooldown periods between operations (seconds)"""
    BETWEEN_IMAGES: int = 15         # After image generation
    BETWEEN_VIDEOS: int = 15         # After video generation
    BETWEEN_SCENES: int = 30         # Full scene cooldown (image + video)
    BETWEEN_QUEUE_ITEMS: int = 15    # Between queuing items
    AFTER_ERROR: int = 60            # After error before retry
    RATE_LIMIT: float = 1.1          # AdsPower API rate limit


# ============================================================================
# USER INTERACTION (WebSocket)
# ============================================================================

@dataclass(frozen=True)
class UserTimeouts:
    """User interaction timeouts (seconds)"""
    APPROVAL_WAIT: int = 86400       # 24 hours for user to respond
    POLL_INTERVAL: int = 60          # Check for response interval
    WEBSOCKET_PING: int = 30         # WebSocket ping interval


# ============================================================================
# RETRY CONFIGURATION
# ============================================================================

@dataclass(frozen=True)
class RetryConfig:
    """Retry configuration for various operations"""
    # Image generation
    IMAGE_MAX_RETRIES: int = 3
    IMAGE_RETRY_DELAY: int = 30
    IMAGE_BACKOFF_MULTIPLIER: float = 2.0

    # Video generation
    VIDEO_MAX_RETRIES: int = 3
    VIDEO_RETRY_DELAY: int = 60
    VIDEO_BACKOFF_MULTIPLIER: float = 2.0

    # Web operations (browser interactions)
    WEB_MAX_RETRIES: int = 5
    WEB_RETRY_DELAY: int = 10

    # Validation
    VALIDATION_MAX_RETRIES: int = 5  # Increased from 2
    REGENERATE_ON_LOW_SCORE: bool = True
    MIN_ACCEPTABLE_SCORE: float = 6.0


# ============================================================================
# SINGLETON INSTANCES
# ============================================================================

BROWSER = BrowserTimeouts()
IMAGE = ImageTimeouts()
VIDEO = VideoTimeouts()
COOLDOWN = CooldownTimes()
USER = UserTimeouts()
RETRY = RetryConfig()
HUMAN = InteractionDelays()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Classes
    "HumanLikeDelay",
    "InteractionDelays",
    "BrowserTimeouts",
    "ImageTimeouts",
    "VideoTimeouts",
    "CooldownTimes",
    "UserTimeouts",
    "RetryConfig",

    # Singleton instances
    "BROWSER",
    "IMAGE",
    "VIDEO",
    "COOLDOWN",
    "USER",
    "RETRY",
    "HUMAN",
]
