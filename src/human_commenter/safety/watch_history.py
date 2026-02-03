"""
Watch History Tracker

Tracks watched videos to avoid repetition within a profile.
Simple file-based storage for persistence across sessions.
"""

import json
import os
import hashlib
from typing import Dict, Optional
from datetime import datetime
from pathlib import Path

from .logger import get_logger

logger = get_logger(__name__)


class WatchHistory:
    """
    Track watched videos to avoid repetition.

    Features:
    - Per-profile tracking
    - Automatic cleanup of old entries
    - Simple JSON file storage
    - URL hashing for privacy
    """

    def __init__(
        self,
        history_dir: str = "data/watch_history",
        max_per_profile: int = 500
    ):
        """
        Initialize watch history tracker.

        Args:
            history_dir: Directory to store history files
            max_per_profile: Maximum entries per profile (oldest removed)
        """
        self.history_dir = Path(history_dir)
        self.max_per_profile = max_per_profile
        self._cache: Dict[str, Dict[str, str]] = {}  # profile -> {hash: timestamp}

        # Ensure directory exists
        self.history_dir.mkdir(parents=True, exist_ok=True)

    def _get_profile_file(self, profile_id: str) -> Path:
        """Get history file path for profile."""
        safe_id = "".join(c if c.isalnum() else "_" for c in profile_id)
        return self.history_dir / f"{safe_id}.json"

    def _load_profile(self, profile_id: str) -> Dict[str, str]:
        """Load history for a profile."""
        if profile_id in self._cache:
            return self._cache[profile_id]

        history_file = self._get_profile_file(profile_id)

        if history_file.exists():
            try:
                with open(history_file, 'r') as f:
                    data = json.load(f)
                    self._cache[profile_id] = data
                    return data
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load watch history: {e}")
                return {}
        else:
            return {}

    def _save_profile(self, profile_id: str) -> None:
        """Save history for a profile."""
        if profile_id not in self._cache:
            return

        history_file = self._get_profile_file(profile_id)

        try:
            with open(history_file, 'w') as f:
                json.dump(self._cache[profile_id], f, indent=2)
        except IOError as e:
            logger.warning(f"Failed to save watch history: {e}")

    @staticmethod
    def hash_url(url: str) -> str:
        """
        Create hash from URL for dedup.

        Extracts video ID if possible, otherwise hashes full URL.

        Args:
            url: Video URL

        Returns:
            8-character hash
        """
        # Try to extract video ID from URL
        video_id = None

        # YouTube video formats:
        # - https://www.youtube.com/watch?v=VIDEO_ID
        # - https://www.youtube.com/shorts/VIDEO_ID
        # - https://youtu.be/VIDEO_ID

        if "youtube.com/watch" in url and "v=" in url:
            try:
                video_id = url.split("v=")[1].split("&")[0]
            except IndexError:
                pass
        elif "youtube.com/shorts/" in url:
            try:
                video_id = url.split("/shorts/")[1].split("?")[0]
            except IndexError:
                pass
        elif "youtu.be/" in url:
            try:
                video_id = url.split("youtu.be/")[1].split("?")[0]
            except IndexError:
                pass

        # If video_id found, use it directly (it's already unique)
        if video_id:
            return video_id[:11]  # YouTube IDs are 11 chars

        # Fallback: hash the full URL
        return hashlib.md5(url.encode()).hexdigest()[:8]

    def is_watched(self, profile_id: str, url: str) -> bool:
        """
        Check if video was watched by this profile.

        Args:
            profile_id: Profile identifier
            url: Video URL

        Returns:
            True if already watched
        """
        video_hash = self.hash_url(url)
        history = self._load_profile(profile_id)
        return video_hash in history

    def mark_watched(self, profile_id: str, url: str) -> str:
        """
        Mark video as watched.

        Args:
            profile_id: Profile identifier
            url: Video URL

        Returns:
            Video hash that was stored
        """
        video_hash = self.hash_url(url)
        history = self._load_profile(profile_id)

        if profile_id not in self._cache:
            self._cache[profile_id] = {}

        # Add with timestamp
        self._cache[profile_id][video_hash] = datetime.now().isoformat()

        # Cleanup if too many entries
        if len(self._cache[profile_id]) > self.max_per_profile:
            self._cleanup_profile(profile_id)

        self._save_profile(profile_id)

        logger.debug(f"Marked watched: {video_hash} for profile {profile_id}")
        return video_hash

    def _cleanup_profile(self, profile_id: str) -> None:
        """Remove oldest entries to stay under max."""
        if profile_id not in self._cache:
            return

        entries = self._cache[profile_id]

        # Sort by timestamp and keep newest
        sorted_entries = sorted(entries.items(), key=lambda x: x[1], reverse=True)
        self._cache[profile_id] = dict(sorted_entries[:self.max_per_profile])

        logger.debug(f"Cleaned up profile {profile_id}: kept {len(self._cache[profile_id])} entries")

    def get_watched_count(self, profile_id: str) -> int:
        """Get number of watched videos for profile."""
        history = self._load_profile(profile_id)
        return len(history)

    def clear_profile(self, profile_id: str) -> None:
        """Clear all history for a profile."""
        if profile_id in self._cache:
            del self._cache[profile_id]

        history_file = self._get_profile_file(profile_id)
        if history_file.exists():
            try:
                history_file.unlink()
                logger.info(f"Cleared watch history for profile {profile_id}")
            except IOError as e:
                logger.warning(f"Failed to clear watch history: {e}")

    def get_stats(self) -> dict:
        """
        Get overall stats across all profiles.

        Returns:
            dict with profile counts and totals
        """
        # Load all profile files
        profiles = {}
        total_videos = 0

        for history_file in self.history_dir.glob("*.json"):
            profile_id = history_file.stem
            try:
                with open(history_file, 'r') as f:
                    data = json.load(f)
                    count = len(data)
                    profiles[profile_id] = count
                    total_videos += count
            except (json.JSONDecodeError, IOError):
                continue

        return {
            "profiles": len(profiles),
            "total_videos": total_videos,
            "per_profile": profiles
        }


# Global instance (lazy initialization)
_watch_history: Optional[WatchHistory] = None


def get_watch_history() -> WatchHistory:
    """Get global watch history instance."""
    global _watch_history
    if _watch_history is None:
        _watch_history = WatchHistory()
    return _watch_history


def init_watch_history(history_dir: str = "data/watch_history", max_per_profile: int = 500) -> WatchHistory:
    """
    Initialize global watch history with custom settings.

    Args:
        history_dir: Directory for history files
        max_per_profile: Max entries per profile

    Returns:
        WatchHistory instance
    """
    global _watch_history
    _watch_history = WatchHistory(history_dir, max_per_profile)
    return _watch_history
