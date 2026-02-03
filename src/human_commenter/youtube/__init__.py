"""
YouTube-specific helpers for automation.
"""

from .selectors import YouTubeSelectors
from .popup_handler import PopupHandler
from .video_player import VideoPlayer

__all__ = [
    "YouTubeSelectors",
    "PopupHandler",
    "VideoPlayer",
]
