"""
State management module for human-like automation.

Provides:
- SessionState: Persistent state storage for profile continuity
"""

from .session_state import SessionState

__all__ = [
    "SessionState",
]
