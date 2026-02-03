"""
Profile Seed Generator

Generates reproducible but unpredictable seeds for profile-specific variations.
Uses multi-factor approach combining profile ID, session, entropy, and time.

This ensures:
- Same profile always behaves consistently (behavior_seed)
- Daily variation for some behaviors (daily_seed)
- Session-unique randomness (session_seed)
- Action-level uniqueness (action_seed)
"""

import hashlib
import secrets
import os
import time
import platform
from pathlib import Path
from datetime import datetime
from typing import Optional


class ProfileSeedGenerator:
    """
    Multi-factor seed generation for consistent profile behavior.

    Combines multiple entropy sources:
    - Profile ID: Base consistency across all sessions
    - Profile Entropy: Unique per-profile secret stored on disk
    - Session ID: Per-session variance
    - Date: Daily rotation for some behaviors
    - Action Counter: Per-action uniqueness

    This creates a "fingerprint" for each profile that is:
    - Consistent across sessions (same profile = same base behaviors)
    - Unique per profile (different profiles behave differently)
    - Unpredictable (can't guess another profile's behavior)
    """

    def __init__(self, profile_id: str, data_dir: Optional[Path] = None):
        """
        Initialize seed generator for a profile.

        Args:
            profile_id: Unique profile identifier (e.g., AdsPower profile ID)
            data_dir: Base directory for storing entropy files (default: ~/.human_commenter)
        """
        self.profile_id = profile_id
        self.session_id = secrets.token_hex(8)
        self.date_str = datetime.now().strftime("%Y-%m-%d")
        self._action_counter = 0

        # Setup data directory
        if data_dir is None:
            data_dir = Path.home() / ".human_commenter"
        self._data_dir = data_dir

        # Get or create profile entropy
        self.profile_entropy = self._get_profile_entropy()

    def _get_profile_entropy(self) -> str:
        """
        Get or create unique entropy for this profile.

        Entropy is stored on disk so the same profile always
        gets the same base behavior patterns.
        """
        entropy_dir = self._data_dir / "entropy" / self.profile_id
        entropy_file = entropy_dir / ".entropy"

        try:
            if entropy_file.exists():
                return entropy_file.read_text().strip()

            # Create new entropy from multiple sources
            entropy_parts = [
                secrets.token_hex(32),
                str(os.getpid()),
                str(time.time_ns()),
                platform.node(),
                platform.system(),
                platform.machine(),
                self.profile_id,
            ]

            entropy = hashlib.sha256("|".join(entropy_parts).encode()).hexdigest()

            # Save to disk
            entropy_dir.mkdir(parents=True, exist_ok=True)
            entropy_file.write_text(entropy)

            # Restrict permissions (Unix-like systems)
            try:
                entropy_file.chmod(0o600)
            except (OSError, AttributeError):
                pass  # Windows doesn't support chmod the same way

            return entropy

        except Exception:
            # Fallback to random entropy if file operations fail
            return secrets.token_hex(32)

    def get_behavior_seed(self, component: str) -> int:
        """
        Get seed for consistent behavior across sessions.

        Use for:
        - Mouse movement style weights
        - Keyboard typo patterns
        - Scroll device selection
        - Any behavior that should be consistent for this profile

        Args:
            component: Component name (e.g., "mouse", "keyboard", "scroll")

        Returns:
            Integer seed for random.Random(seed)
        """
        seed_input = f"{self.profile_id}:{component}:{self.profile_entropy}"
        return int(hashlib.sha256(seed_input.encode()).hexdigest()[:16], 16)

    def get_daily_seed(self, component: str) -> int:
        """
        Get seed that changes daily.

        Use for:
        - Daily behavior variations
        - Content preferences that might change
        - Anything that should vary day-to-day but be consistent within a day

        Args:
            component: Component name

        Returns:
            Integer seed
        """
        seed_input = f"{self.profile_id}:{component}:{self.profile_entropy}:{self.date_str}"
        return int(hashlib.sha256(seed_input.encode()).hexdigest()[:16], 16)

    def get_session_seed(self, component: str) -> int:
        """
        Get seed unique to this session.

        Use for:
        - Session-specific randomness
        - Behaviors that should vary each time the bot runs
        - But remain consistent within a single run

        Args:
            component: Component name

        Returns:
            Integer seed
        """
        seed_input = f"{self.profile_id}:{component}:{self.session_id}"
        return int(hashlib.sha256(seed_input.encode()).hexdigest()[:16], 16)

    def get_action_seed(self, component: str) -> int:
        """
        Get unique seed for each action.

        Use for:
        - Per-action randomness
        - When you need truly unique values each time

        Args:
            component: Component name

        Returns:
            Integer seed (unique each call)
        """
        self._action_counter += 1
        seed_input = f"{self.session_id}:{component}:{self._action_counter}:{time.time_ns()}"
        return int(hashlib.sha256(seed_input.encode()).hexdigest()[:16], 16)

    def get_float(self, component: str, seed_type: str = "behavior") -> float:
        """
        Get a reproducible float [0.0, 1.0) for a component.

        Convenience method for getting a normalized random value.

        Args:
            component: Component name
            seed_type: One of "behavior", "daily", "session", "action"

        Returns:
            Float between 0.0 and 1.0
        """
        if seed_type == "behavior":
            seed = self.get_behavior_seed(component)
        elif seed_type == "daily":
            seed = self.get_daily_seed(component)
        elif seed_type == "session":
            seed = self.get_session_seed(component)
        elif seed_type == "action":
            seed = self.get_action_seed(component)
        else:
            raise ValueError(f"Unknown seed_type: {seed_type}")

        # Normalize to [0.0, 1.0)
        return (seed % 1000000) / 1000000.0

    def get_variation(
        self,
        component: str,
        base_value: float,
        variation_pct: float = 0.2,
        seed_type: str = "behavior"
    ) -> float:
        """
        Get a varied value based on a base value.

        Useful for creating profile-specific variations of default values.

        Args:
            component: Component name
            base_value: The base value to vary
            variation_pct: Maximum variation percentage (0.2 = ±20%)
            seed_type: Type of seed to use

        Returns:
            Varied value
        """
        rand_float = self.get_float(component, seed_type)
        # Map [0, 1) to [-variation_pct, +variation_pct]
        multiplier = 1.0 + (rand_float * 2 - 1) * variation_pct
        return base_value * multiplier

    def get_info(self) -> dict:
        """
        Get information about this seed generator.

        Useful for debugging and logging.
        """
        return {
            "profile_id": self.profile_id,
            "session_id": self.session_id,
            "date": self.date_str,
            "action_count": self._action_counter,
            "entropy_preview": self.profile_entropy[:16] + "...",
        }

    def __repr__(self) -> str:
        return f"ProfileSeedGenerator(profile_id={self.profile_id!r}, session={self.session_id[:8]}...)"
