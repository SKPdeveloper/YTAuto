"""
Configuration module for human-like automation.

Provides:
- CommenterConfig: Main configuration model (Pydantic-based)
- ProfileSeedGenerator: Multi-factor seed generation for profile consistency
- ViewportPool: Realistic viewport distribution based on market data

All legacy imports from the original config.py are preserved for backwards compatibility:
    from human_commenter.config import CommenterConfig  # Still works!
"""

# Legacy config models (re-exported for backwards compatibility)
from .models import (
    DelayConfig,
    MouseConfig,
    KeyboardConfig,
    ScrollConfig,
    WorkflowConfig,
    ViewportConfig,
    SafetyConfig,
    CommenterConfig,
)

# New Phase 2 modules
from .seed_generator import ProfileSeedGenerator
from .viewport_pool import ViewportPool, ViewportEntry

__all__ = [
    # Legacy config models
    "DelayConfig",
    "MouseConfig",
    "KeyboardConfig",
    "ScrollConfig",
    "WorkflowConfig",
    "ViewportConfig",
    "SafetyConfig",
    "CommenterConfig",

    # New modules
    "ProfileSeedGenerator",
    "ViewportPool",
    "ViewportEntry",
]
