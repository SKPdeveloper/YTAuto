"""
Session State Manager

Persists state between automation runs for continuity.
Real users remember where they were on pages, what they've seen, etc.

Features:
- Scroll position memory (with natural drift)
- Visited page tracking
- Last visit timestamps
- Custom state storage
"""

import json
import random
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class SessionState:
    """
    Manages persistent state for a profile.

    Stores:
    - Scroll positions (remembered for 24h with drift)
    - Visited pages (recent 100)
    - Last visit timestamps
    - Custom key-value data

    This helps simulate user memory:
    - Returning to a page near where you left off
    - Recognizing previously visited pages
    - Maintaining context across sessions
    """

    def __init__(self, profile_id: str, data_dir: Optional[Path] = None):
        """
        Initialize session state for a profile.

        Args:
            profile_id: Unique profile identifier
            data_dir: Base directory for state files (default: ~/.human_commenter)
        """
        self.profile_id = profile_id

        # Setup data directory
        if data_dir is None:
            data_dir = Path.home() / ".human_commenter"
        self._data_dir = data_dir

        self.state_file = self._data_dir / "state" / f"{profile_id}.json"
        self._state = self._load()

    def _load(self) -> Dict[str, Any]:
        """Load state from disk."""
        try:
            if self.state_file.exists():
                data = json.loads(self.state_file.read_text(encoding='utf-8'))
                logger.debug(f"Loaded state for profile {self.profile_id}")
                return data
        except Exception as e:
            logger.warning(f"Failed to load state: {e}")

        # Default state structure
        return {
            'scroll_positions': {},
            'visited_pages': [],
            'last_visits': {},
            'custom_data': {},
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat(),
        }

    def _save(self) -> None:
        """Save state to disk."""
        try:
            self._state['updated_at'] = datetime.now().isoformat()
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(
                json.dumps(self._state, indent=2, ensure_ascii=False),
                encoding='utf-8'
            )
            logger.debug(f"Saved state for profile {self.profile_id}")
        except Exception as e:
            logger.warning(f"Failed to save state: {e}")

    # === Scroll Position Memory ===

    def get_scroll_position(
        self,
        page_id: str,
        max_age_hours: int = 24,
        add_drift: bool = True
    ) -> Optional[int]:
        """
        Get remembered scroll position for a page.

        Args:
            page_id: Page identifier (URL or custom ID)
            max_age_hours: Maximum age of remembered position
            add_drift: Add small random drift (human memory isn't perfect)

        Returns:
            Scroll position in pixels, or None if not remembered
        """
        positions = self._state.get('scroll_positions', {})

        if page_id not in positions:
            return None

        data = positions[page_id]
        saved_time = datetime.fromisoformat(data['timestamp'])

        # Check if position is too old
        if datetime.now() - saved_time > timedelta(hours=max_age_hours):
            # Memory expired, remove it
            del positions[page_id]
            self._save()
            return None

        position = data['position']

        # Add natural drift (humans don't remember exactly)
        if add_drift:
            drift = random.randint(-100, 100)
            position = max(0, position + drift)

        return position

    def save_scroll_position(self, page_id: str, position: int) -> None:
        """
        Remember scroll position for a page.

        Args:
            page_id: Page identifier
            position: Scroll position in pixels
        """
        if 'scroll_positions' not in self._state:
            self._state['scroll_positions'] = {}

        self._state['scroll_positions'][page_id] = {
            'position': position,
            'timestamp': datetime.now().isoformat()
        }
        self._save()

    def clear_scroll_position(self, page_id: str) -> None:
        """Clear remembered scroll position for a page."""
        positions = self._state.get('scroll_positions', {})
        if page_id in positions:
            del positions[page_id]
            self._save()

    # === Visited Pages Tracking ===

    def add_visited(self, page_id: str) -> None:
        """
        Record a page visit.

        Args:
            page_id: Page identifier
        """
        visited = self._state.get('visited_pages', [])

        # Remove if already in list (will be re-added at front)
        if page_id in visited:
            visited.remove(page_id)

        # Add to front of list
        visited.insert(0, page_id)

        # Keep only recent pages
        visited = visited[:100]

        self._state['visited_pages'] = visited

        # Also update last visit time
        if 'last_visits' not in self._state:
            self._state['last_visits'] = {}
        self._state['last_visits'][page_id] = datetime.now().isoformat()

        self._save()

    def was_recently_visited(self, page_id: str, recent_count: int = 20) -> bool:
        """
        Check if page was visited recently.

        Args:
            page_id: Page identifier
            recent_count: Number of recent pages to check

        Returns:
            True if page is in recent visits
        """
        visited = self._state.get('visited_pages', [])
        return page_id in visited[:recent_count]

    def was_ever_visited(self, page_id: str) -> bool:
        """
        Check if page was ever visited (in tracked history).

        Args:
            page_id: Page identifier

        Returns:
            True if page is in visit history
        """
        return page_id in self._state.get('visited_pages', [])

    def get_last_visit(self, page_id: str) -> Optional[datetime]:
        """
        Get timestamp of last visit to a page.

        Args:
            page_id: Page identifier

        Returns:
            Datetime of last visit, or None
        """
        last_visits = self._state.get('last_visits', {})
        if page_id in last_visits:
            return datetime.fromisoformat(last_visits[page_id])
        return None

    def get_recent_pages(self, count: int = 10) -> List[str]:
        """
        Get list of recently visited pages.

        Args:
            count: Number of pages to return

        Returns:
            List of page IDs, most recent first
        """
        return self._state.get('visited_pages', [])[:count]

    # === Custom Data Storage ===

    def set(self, key: str, value: Any) -> None:
        """
        Store custom data.

        Args:
            key: Data key
            value: Data value (must be JSON-serializable)
        """
        if 'custom_data' not in self._state:
            self._state['custom_data'] = {}

        self._state['custom_data'][key] = {
            'value': value,
            'timestamp': datetime.now().isoformat()
        }
        self._save()

    def get(self, key: str, default: Any = None) -> Any:
        """
        Retrieve custom data.

        Args:
            key: Data key
            default: Default value if key not found

        Returns:
            Stored value or default
        """
        custom_data = self._state.get('custom_data', {})
        if key in custom_data:
            return custom_data[key]['value']
        return default

    def delete(self, key: str) -> None:
        """
        Delete custom data.

        Args:
            key: Data key
        """
        custom_data = self._state.get('custom_data', {})
        if key in custom_data:
            del custom_data[key]
            self._save()

    def has(self, key: str) -> bool:
        """
        Check if custom data key exists.

        Args:
            key: Data key

        Returns:
            True if key exists
        """
        return key in self._state.get('custom_data', {})

    # === State Management ===

    def clear_all(self) -> None:
        """Clear all state data."""
        self._state = {
            'scroll_positions': {},
            'visited_pages': [],
            'last_visits': {},
            'custom_data': {},
            'created_at': self._state.get('created_at', datetime.now().isoformat()),
            'updated_at': datetime.now().isoformat(),
        }
        self._save()

    def clear_old_data(self, max_age_days: int = 7) -> int:
        """
        Clear data older than specified age.

        Args:
            max_age_days: Maximum age in days

        Returns:
            Number of items cleared
        """
        cutoff = datetime.now() - timedelta(days=max_age_days)
        cleared = 0

        # Clear old scroll positions
        positions = self._state.get('scroll_positions', {})
        old_positions = [
            page_id for page_id, data in positions.items()
            if datetime.fromisoformat(data['timestamp']) < cutoff
        ]
        for page_id in old_positions:
            del positions[page_id]
            cleared += 1

        # Clear old custom data
        custom_data = self._state.get('custom_data', {})
        old_keys = [
            key for key, data in custom_data.items()
            if datetime.fromisoformat(data['timestamp']) < cutoff
        ]
        for key in old_keys:
            del custom_data[key]
            cleared += 1

        if cleared > 0:
            self._save()

        return cleared

    def get_stats(self) -> dict:
        """
        Get statistics about stored state.

        Returns:
            Dict with state statistics
        """
        return {
            'profile_id': self.profile_id,
            'scroll_positions_count': len(self._state.get('scroll_positions', {})),
            'visited_pages_count': len(self._state.get('visited_pages', [])),
            'custom_data_count': len(self._state.get('custom_data', {})),
            'created_at': self._state.get('created_at'),
            'updated_at': self._state.get('updated_at'),
        }

    def __repr__(self) -> str:
        stats = self.get_stats()
        return (
            f"SessionState(profile_id={self.profile_id!r}, "
            f"pages={stats['visited_pages_count']}, "
            f"positions={stats['scroll_positions_count']})"
        )
