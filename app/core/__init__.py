"""Core functionality - configuration, orchestration, state management

Use lazy imports to avoid circular import issues:
    from app.core.config import settings
    from app.core.state_manager import state_manager
    from app.core.orchestrator import ProjectOrchestrator
"""

# Only import config directly (needed for logger)
from app.core.config import settings

# Lazy imports for heavy modules
__all__ = [
    "settings",
    "state_manager",
    "ProjectOrchestrator",
]
