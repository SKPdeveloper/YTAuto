"""
Viewport Pool Configuration

Provides realistic viewport distribution based on actual market data.
Each profile gets a consistent viewport that matches real-world usage patterns.

Data source: StatCounter Global Stats 2024-2025
"""

import random
import hashlib
from typing import Tuple, List, Optional
from dataclasses import dataclass


@dataclass
class ViewportEntry:
    """A viewport resolution with its market share weight."""
    width: int
    height: int
    weight: float  # Market share percentage


class ViewportPool:
    """
    Pool of viewports based on StatCounter 2024-2025 market share data.

    Features:
    - Realistic distribution matching actual user demographics
    - Consistent viewport per profile (same profile = same resolution)
    - Physical screen constraint support
    - Small random variation to avoid exact matches
    """

    # Viewport resolutions with market share weights
    # Based on StatCounter Global Stats for desktop screens
    VIEWPORTS: List[ViewportEntry] = [
        ViewportEntry(1920, 1080, 22.5),   # Full HD - most common
        ViewportEntry(1366, 768, 14.8),    # HD - laptops
        ViewportEntry(1536, 864, 10.2),    # Scaled Full HD
        ViewportEntry(2560, 1440, 8.5),    # QHD
        ViewportEntry(1440, 900, 6.5),     # MacBook older
        ViewportEntry(1280, 720, 5.2),     # HD
        ViewportEntry(1600, 900, 3.5),     # HD+
        ViewportEntry(1360, 768, 3.8),     # Similar to 1366
        ViewportEntry(1680, 1050, 2.8),    # WSXGA+
        ViewportEntry(3840, 2160, 2.5),    # 4K
        ViewportEntry(1280, 800, 2.1),     # WXGA
        ViewportEntry(1920, 1200, 1.8),    # WUXGA
        ViewportEntry(1280, 1024, 1.5),    # SXGA (older 5:4)
        ViewportEntry(2560, 1080, 1.2),    # Ultrawide
        ViewportEntry(1024, 768, 1.0),     # XGA (very old)
        ViewportEntry(1440, 1080, 0.8),    # Non-standard
    ]

    @classmethod
    def get_for_profile(
        cls,
        profile_id: str,
        max_width: Optional[int] = None,
        max_height: Optional[int] = None,
        add_variation: bool = True
    ) -> Tuple[int, int]:
        """
        Get consistent viewport for a profile, constrained by screen size.

        The same profile_id will always return the same viewport (before variation),
        ensuring consistent behavior across sessions.

        Args:
            profile_id: Unique identifier for consistent selection
            max_width: Physical screen width limit (optional)
            max_height: Physical screen height limit (optional)
            add_variation: Add small random variation to avoid exact matches

        Returns:
            (width, height) tuple
        """
        # Create deterministic seed from profile_id
        seed = int(hashlib.sha256(f"{profile_id}_viewport".encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)

        # Filter by screen constraints if provided
        if max_width and max_height:
            pool = [
                v for v in cls.VIEWPORTS
                if v.width <= max_width and v.height <= max_height
            ]
            if not pool:
                # No standard viewports fit, create custom one
                width = max_width - rng.randint(20, 80)
                height = max_height - rng.randint(20, 80)
                return (width, height)
        else:
            pool = cls.VIEWPORTS

        # Weighted selection
        total_weight = sum(v.weight for v in pool)
        r = rng.uniform(0, total_weight)

        cumulative = 0
        selected = pool[0]  # Default fallback

        for viewport in pool:
            cumulative += viewport.weight
            if r <= cumulative:
                selected = viewport
                break

        width, height = selected.width, selected.height

        # Add small variation to avoid exact matches
        if add_variation:
            # Use same seed for consistent variation
            width += rng.randint(-20, 20)
            height += rng.randint(-15, 15)

            # Ensure even numbers (some browsers prefer this)
            width = width - (width % 2)
            height = height - (height % 2)

        return (width, height)

    @classmethod
    def get_random(
        cls,
        max_width: Optional[int] = None,
        max_height: Optional[int] = None
    ) -> Tuple[int, int]:
        """
        Get a random viewport (non-deterministic).

        Use when you don't need consistency across sessions.

        Args:
            max_width: Physical screen width limit
            max_height: Physical screen height limit

        Returns:
            (width, height) tuple
        """
        pool = cls.VIEWPORTS

        if max_width and max_height:
            pool = [
                v for v in cls.VIEWPORTS
                if v.width <= max_width and v.height <= max_height
            ]
            if not pool:
                return (max_width - 50, max_height - 50)

        # Weighted random selection
        total_weight = sum(v.weight for v in pool)
        r = random.uniform(0, total_weight)

        cumulative = 0
        for viewport in pool:
            cumulative += viewport.weight
            if r <= cumulative:
                return (
                    viewport.width + random.randint(-20, 20),
                    viewport.height + random.randint(-15, 15)
                )

        return (pool[0].width, pool[0].height)

    @classmethod
    def get_common_viewports(cls, top_n: int = 5) -> List[Tuple[int, int, float]]:
        """
        Get the most common viewports by market share.

        Args:
            top_n: Number of top viewports to return

        Returns:
            List of (width, height, market_share) tuples
        """
        sorted_viewports = sorted(cls.VIEWPORTS, key=lambda v: v.weight, reverse=True)
        return [(v.width, v.height, v.weight) for v in sorted_viewports[:top_n]]

    @classmethod
    def get_aspect_ratio(cls, width: int, height: int) -> str:
        """
        Get the aspect ratio category for a viewport.

        Args:
            width: Viewport width
            height: Viewport height

        Returns:
            Aspect ratio string (e.g., "16:9", "16:10", "4:3")
        """
        ratio = width / height

        if abs(ratio - 16/9) < 0.1:
            return "16:9"
        elif abs(ratio - 16/10) < 0.1:
            return "16:10"
        elif abs(ratio - 4/3) < 0.1:
            return "4:3"
        elif abs(ratio - 5/4) < 0.1:
            return "5:4"
        elif abs(ratio - 21/9) < 0.1:
            return "21:9"
        else:
            return f"{ratio:.2f}:1"

    @classmethod
    def is_mobile_viewport(cls, width: int, height: int) -> bool:
        """
        Check if viewport dimensions suggest a mobile device.

        Args:
            width: Viewport width
            height: Viewport height

        Returns:
            True if likely mobile
        """
        # Mobile viewports are typically narrow or portrait
        return width < 768 or (height > width)

    @classmethod
    def get_stats(cls) -> dict:
        """
        Get statistics about the viewport pool.

        Returns:
            Dict with pool statistics
        """
        total_weight = sum(v.weight for v in cls.VIEWPORTS)
        widths = [v.width for v in cls.VIEWPORTS]
        heights = [v.height for v in cls.VIEWPORTS]

        return {
            "total_viewports": len(cls.VIEWPORTS),
            "total_weight": total_weight,
            "width_range": (min(widths), max(widths)),
            "height_range": (min(heights), max(heights)),
            "most_common": (cls.VIEWPORTS[0].width, cls.VIEWPORTS[0].height),
        }
