"""
Biometrics module for human-like behavior simulation.

Provides:
- BimodalDelay: Bimodal delays matching human cognitive patterns (fast/slow modes)
- GaussianDelay: Simple Gaussian delays (legacy, use BimodalDelay for new code)
- HumanMouse: Bezier curves + Fitts' Law + micro-tremor + overshoot + spiral
- HumanKeyboard: Rhythmic typing with 5 error types and corrections
- HumanScroll: Natural wheel scrolling with device-specific normalization
- ScrollNormalizer: Device-specific scroll delta normalization
- DistractedState: Simulates user distraction (blur/focus)
- TypoType: Enum for keyboard error types
- ActionMode: Enum for bimodal delay modes (automatic/deliberate)
"""

# New bimodal delay system (recommended)
from .bimodal_delay import (
    BimodalDelay,
    BimodalConfig,
    ActionMode,
    short_pause,
    medium_pause,
    long_pause,
    page_load_pause,
    reading_pause,
)

# Legacy Gaussian delay (kept for backwards compatibility)
from .gaussian_delay import GaussianDelay

# Input simulation
from .mouse import HumanMouse
from .keyboard import HumanKeyboard, TypoType
from .scroll import HumanScroll, ScrollNormalizer

# State simulation
from .distraction import DistractedState

__all__ = [
    # Delays
    "BimodalDelay",
    "BimodalConfig",
    "ActionMode",
    "GaussianDelay",  # Legacy

    # Convenience delay functions
    "short_pause",
    "medium_pause",
    "long_pause",
    "page_load_pause",
    "reading_pause",

    # Input
    "HumanMouse",
    "HumanKeyboard",
    "TypoType",
    "HumanScroll",
    "ScrollNormalizer",

    # State
    "DistractedState",
]
