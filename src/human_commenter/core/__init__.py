"""
Core module for human-like browser automation.

Provides:
- HumanBrowser: Unified interface combining all human-like interaction modules
- HumanBrowserConfig: Configuration for HumanBrowser
"""

from .human_browser import HumanBrowser, HumanBrowserConfig

__all__ = [
    "HumanBrowser",
    "HumanBrowserConfig",
]
