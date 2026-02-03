"""
Human-Like YouTube Commenter Module

Provides advanced human behavior simulation for YouTube comment automation.

Main entry points:
- HumanCommenter: YouTube-specific comment automation workflow
- HumanBrowser: Generic browser automation with human behavior

Features:
- Bimodal delays matching human cognitive patterns (70% fast / 30% slow)
- Bezier curve mouse movements with Fitts' Law timing
- 5 types of typing errors with natural corrections
- Device-specific scroll normalization (mouse, touchpad)
- Profile-specific behavior "fingerprints"
- Session state persistence
"""

# Main entry points
from .commenter import HumanCommenter
from .core import HumanBrowser, HumanBrowserConfig

# Configuration
from .config import (
    CommenterConfig,
    ProfileSeedGenerator,
    ViewportPool,
)

# Workflow
from .workflow.state_machine import WorkflowResult, WorkflowState

# State management
from .state import SessionState

# Biometrics (for advanced usage)
from .biometrics import (
    BimodalDelay,
    ActionMode,
    HumanMouse,
    HumanKeyboard,
    HumanScroll,
    ScrollNormalizer,
    TypoType,
)

# Utilities
from .utils import RetryHandler, RetryError, with_retry

__all__ = [
    # Main entry points
    "HumanCommenter",
    "HumanBrowser",
    "HumanBrowserConfig",

    # Configuration
    "CommenterConfig",
    "ProfileSeedGenerator",
    "ViewportPool",

    # Workflow
    "WorkflowResult",
    "WorkflowState",

    # State
    "SessionState",

    # Biometrics
    "BimodalDelay",
    "ActionMode",
    "HumanMouse",
    "HumanKeyboard",
    "HumanScroll",
    "ScrollNormalizer",
    "TypoType",

    # Utilities
    "RetryHandler",
    "RetryError",
    "with_retry",
]

__version__ = "2.0.0"
