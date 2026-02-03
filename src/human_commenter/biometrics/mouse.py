"""
Human-Like Mouse Movement

Implements realistic mouse behavior using:
- Bezier curves for smooth, natural paths
- Fitts' Law for movement timing
- Micro-tremor during hovering
- Jitter on click positions
- Target overshoot and correction
- Spiral approach to targets
- Dynamic hover radius for menu triggers
"""

import asyncio
import math
import random
from dataclasses import dataclass
from enum import Enum
from typing import List, Tuple, Optional

from playwright.async_api import Page, ElementHandle

from ..config import CommenterConfig, MouseConfig
from ..safety.logger import get_logger
from ..safety.analytics_logger import get_analytics

logger = get_logger(__name__)


class MovementType(Enum):
    """Types of mouse movement paths."""
    BEZIER_SMOOTH = "bezier_smooth"  # Smooth curved path
    BEZIER_SHARP = "bezier_sharp"    # More angular curved path
    DIRECT = "direct"                 # Nearly straight line with slight noise
    S_CURVE = "s_curve"              # S-shaped path
    HESITANT = "hesitant"            # Path with micro-pauses/corrections


@dataclass
class Point:
    """2D point with x, y coordinates"""
    x: float
    y: float

    def distance_to(self, other: "Point") -> float:
        """Calculate Euclidean distance to another point"""
        return math.sqrt((self.x - other.x) ** 2 + (self.y - other.y) ** 2)

    def __add__(self, other: "Point") -> "Point":
        return Point(self.x + other.x, self.y + other.y)

    def __sub__(self, other: "Point") -> "Point":
        return Point(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar: float) -> "Point":
        return Point(self.x * scalar, self.y * scalar)


class HumanMouse:
    """
    Simulates human mouse movements with natural paths and timing.

    Features:
    - Bezier curve paths (not straight lines)
    - Fitts' Law timing (larger/closer targets = faster)
    - Speed profile (accelerate -> cruise -> decelerate)
    - Micro-tremor during hover (subtle jitter)
    - Click position jitter
    - Target overshoot and correction (profile-specific 5-25% chance)
    - Spiral approach to precise targets
    - Dynamic hover radius for CSS hover triggers
    - Click hold duration logging
    """

    def __init__(self, page: Page, config: CommenterConfig, profile_seed: int = None):
        self.page = page
        self.config = config
        self.mouse_config: MouseConfig = config.mouse
        self._current_pos: Point = Point(0, 0)

        # Profile-specific RNG for consistent behavior per profile
        if profile_seed:
            self._rng = random.Random(profile_seed)
        else:
            self._rng = random.Random()

        # Randomize overshoot parameters per profile (or use config if set)
        if self.mouse_config.overshoot_chance is not None:
            self._overshoot_chance = self.mouse_config.overshoot_chance
        else:
            # Profile-specific: 5-25% chance (precise vs clumsy users)
            self._overshoot_chance = self._rng.uniform(0.05, 0.25)

        if self.mouse_config.overshoot_distance_ratio is not None:
            self._overshoot_distance_ratio = self.mouse_config.overshoot_distance_ratio
        else:
            # Profile-specific: 4-15% of movement distance
            self._overshoot_distance_ratio = self._rng.uniform(0.04, 0.15)

        if self.mouse_config.spiral_chance is not None:
            self._spiral_chance = self.mouse_config.spiral_chance
        else:
            # Profile-specific: 15-35% chance
            self._spiral_chance = self._rng.uniform(0.15, 0.35)

        self._spiral_radius: float = 8.0  # Max spiral radius in pixels
        self._hover_wait_for_css: float = 0.7  # Wait time for CSS hover triggers

        # Profile-specific movement type weights
        # Adjusted for better hesitant representation (~10-20% of moves)
        self._movement_weights = {
            MovementType.BEZIER_SMOOTH: 28 + self._rng.randint(-6, 6),   # 22-34
            MovementType.BEZIER_SHARP: 18 + self._rng.randint(-5, 5),    # 13-23
            MovementType.DIRECT: 22 + self._rng.randint(-6, 8),          # 16-30
            MovementType.S_CURVE: 18 + self._rng.randint(-5, 5),         # 13-23
            MovementType.HESITANT: 14 + self._rng.randint(-4, 6),        # 10-20
        }

        # Log profile characteristics
        logger.debug(
            f"Mouse profile: overshoot_chance={self._overshoot_chance:.2%}, "
            f"overshoot_ratio={self._overshoot_distance_ratio:.2%}, "
            f"spiral_chance={self._spiral_chance:.2%}"
        )
        logger.debug(f"Movement weights: {self.get_movement_weights()}")

    async def move_to(
        self,
        x: float,
        y: float,
        target_width: float = 50.0,
        target_height: float = 50.0,
        movement_type: MovementType = None,
        apply_overshoot: bool = True
    ) -> dict:
        """
        Move mouse to target position using various path types.

        Args:
            x: Target X coordinate
            y: Target Y coordinate
            target_width: Width of target element (for Fitts' Law)
            target_height: Height of target element (for Fitts' Law)
            movement_type: Force specific movement type (None = auto-select)
            apply_overshoot: Whether to apply overshoot behavior

        Returns:
            dict with movement metadata
        """
        start = self._current_pos
        end = Point(x, y)
        distance = start.distance_to(end)
        analytics = get_analytics()

        # Auto-select movement type if not specified
        if movement_type is None:
            movement_type = self._select_movement_type(distance)

        # Log move start
        if analytics:
            analytics.log_mouse_move_start(
                start.x, start.y, x, y, target_width, target_height,
                movement_type=movement_type.value
            )

        # Check for overshoot (only for longer movements)
        did_overshoot = False
        overshoot_px = 0
        correction_px = 0
        pause_ms = 0

        # DEBUG: Log overshoot decision
        should_check_overshoot = apply_overshoot and distance > 80
        overshoot_roll = random.random()
        will_overshoot = should_check_overshoot and overshoot_roll < self._overshoot_chance

        if analytics:
            analytics.log_mouse_overshoot_debug(
                distance=distance,
                overshoot_chance=self._overshoot_chance,
                should_check=should_check_overshoot,
                roll=overshoot_roll,
                will_overshoot=will_overshoot
            )

        if will_overshoot:
            # Calculate overshoot point
            overshoot_point = self._calculate_overshoot_point(start, end)
            overshoot_px = end.distance_to(overshoot_point)

            # Move to overshoot point first
            await self._execute_path(start, overshoot_point, movement_type, analytics)

            # Brief pause (realizing the overshoot)
            pause = random.uniform(0.06, 0.18)
            pause_ms = pause * 1000
            await asyncio.sleep(pause)

            # Correction movement back to target (always direct)
            await self._execute_path(overshoot_point, end, MovementType.DIRECT, analytics)

            # Calculate actual correction distance
            correction_px = overshoot_point.distance_to(end)

            did_overshoot = True
            self._current_pos = end

            # Log overshoot with correction details
            if analytics:
                analytics.log_mouse_overshoot(
                    x, y, overshoot_px,
                    correction_px=correction_px,
                    pause_ms=pause_ms
                )

            logger.debug(
                f"Mouse moved to ({x:.0f}, {y:.0f}) with overshoot {overshoot_px:.1f}px, "
                f"correction {correction_px:.1f}px, pause {pause_ms:.0f}ms"
            )
        else:
            # Normal movement
            total_delay = await self._execute_path(start, end, movement_type, analytics)
            self._current_pos = end

            logger.debug(f"Mouse moved to ({x:.0f}, {y:.0f}) type={movement_type.value}")

        # Log move end
        if analytics:
            analytics.log_mouse_move_end(x, y, 0, 0, movement_type=movement_type.value)

        return {
            "x": x,
            "y": y,
            "distance": round(distance, 1),
            "movement_type": movement_type.value,
            "did_overshoot": did_overshoot,
            "overshoot_px": round(overshoot_px, 1) if did_overshoot else 0
        }

    def _calculate_overshoot_point(self, start: Point, end: Point) -> Point:
        """Calculate overshoot point beyond target."""
        distance = start.distance_to(end)

        # Overshoot distance with variance
        overshoot_dist = distance * self._overshoot_distance_ratio
        overshoot_dist *= random.uniform(0.7, 1.4)
        overshoot_dist = max(2.0, min(15.0, overshoot_dist))

        # Direction vector
        dx = (end.x - start.x) / distance
        dy = (end.y - start.y) / distance

        # Add slight angle deviation
        angle_deviation = random.gauss(0, 0.1)
        cos_d, sin_d = math.cos(angle_deviation), math.sin(angle_deviation)
        dx_new = dx * cos_d - dy * sin_d
        dy_new = dx * sin_d + dy * cos_d

        return Point(
            end.x + dx_new * overshoot_dist,
            end.y + dy_new * overshoot_dist
        )

    async def _execute_path(
        self,
        start: Point,
        end: Point,
        movement_type: MovementType,
        analytics
    ) -> float:
        """Execute a movement path of the given type."""
        distance = start.distance_to(end)

        if distance < 3:
            await self.page.mouse.move(end.x, end.y)
            return 0

        # Generate path based on type
        path = self._generate_path(start, end, movement_type)

        if not path:
            await self.page.mouse.move(end.x, end.y)
            return 0

        # Calculate movement time using Fitts' Law
        target_size = 50.0
        movement_time = self._calculate_movement_time(distance, target_size)

        # Generate speed profile
        speed_profile = self._get_speed_profile(len(path))

        # Move along path
        total_delay = 0
        for i, point in enumerate(path):
            base_delay = movement_time / len(path)
            adjusted_delay = base_delay / speed_profile[i] if speed_profile[i] > 0 else base_delay

            await self.page.mouse.move(point.x, point.y)
            await asyncio.sleep(adjusted_delay)
            total_delay += adjusted_delay

            if analytics:
                analytics.log_mouse_move_point(point.x, point.y, i, adjusted_delay * 1000)

        return total_delay

    def _generate_path(
        self,
        start: Point,
        end: Point,
        movement_type: MovementType
    ) -> List[Point]:
        """Generate path based on movement type."""
        if movement_type == MovementType.DIRECT:
            return self._generate_direct_path(start, end)
        elif movement_type == MovementType.S_CURVE:
            return self._generate_s_curve_path(start, end)
        elif movement_type == MovementType.HESITANT:
            return self._generate_hesitant_path(start, end)
        elif movement_type == MovementType.BEZIER_SHARP:
            return self._generate_bezier_path(start, end, sharp=True)
        else:  # BEZIER_SMOOTH
            return self._generate_bezier_path(start, end, sharp=False)

    async def click_at(
        self,
        x: float,
        y: float,
        jitter_radius: Optional[float] = None,
        button: str = "left",
        use_overshoot: bool = True,
        use_spiral: bool = False,
        click_style: Optional[str] = None
    ) -> dict:
        """
        Click at position with natural jitter, overshoot, and optional spiral approach.

        Uses mouse.down/up for realistic hold duration tracking.

        Args:
            x: Target X coordinate
            y: Target Y coordinate
            jitter_radius: Random offset radius (default from config)
            button: Mouse button ("left", "right", "middle")
            use_overshoot: Enable target overshoot behavior
            use_spiral: Enable spiral approach to target
            click_style: Force click style ("tap", "normal", "deliberate") or None for random

        Returns:
            dict with click metadata (hold_ms, click_style, etc.)
        """
        import time

        if jitter_radius is None:
            jitter_radius = self.mouse_config.click_jitter_radius

        # Add random jitter to click position
        jitter_x = random.uniform(-jitter_radius, jitter_radius)
        jitter_y = random.uniform(-jitter_radius, jitter_radius)

        click_x = x + jitter_x
        click_y = y + jitter_y

        # Move to position first (with overshoot if enabled)
        move_result = await self.move_to(click_x, click_y, apply_overshoot=use_overshoot)
        did_overshoot = move_result.get("did_overshoot", False)

        # Apply spiral approach if enabled (for precise targets)
        did_spiral = False
        if use_spiral and random.random() < self._spiral_chance:
            await self._spiral_approach(click_x, click_y)
            did_spiral = True

        # Small pause before click (human hesitation)
        await asyncio.sleep(random.uniform(0.05, 0.15))

        # Select click style if not specified
        if click_style is None:
            click_style = random.choices(
                ['tap', 'normal', 'deliberate'],
                weights=[25, 55, 20]
            )[0]

        # Calculate hold duration based on style
        if click_style == 'tap':
            hold_duration = random.uniform(
                self.mouse_config.tap_hold_min / 1000,
                self.mouse_config.tap_hold_max / 1000
            )
        elif click_style == 'deliberate':
            hold_duration = random.uniform(
                self.mouse_config.deliberate_hold_min / 1000,
                self.mouse_config.deliberate_hold_max / 1000
            )
        else:  # normal
            hold_duration = random.uniform(
                self.mouse_config.normal_hold_min / 1000,
                self.mouse_config.normal_hold_max / 1000
            )

        # Perform click with measured timing
        mousedown_time = time.perf_counter()
        await self.page.mouse.down(button=button)
        await asyncio.sleep(hold_duration)
        await self.page.mouse.up(button=button)
        mouseup_time = time.perf_counter()

        actual_hold_ms = (mouseup_time - mousedown_time) * 1000

        # Log click with full metadata
        analytics = get_analytics()
        if analytics:
            analytics.log_mouse_click(
                click_x, click_y, button, jitter_x, jitter_y,
                hold_ms=actual_hold_ms,
                click_style=click_style
            )

        # Small pause after click
        await asyncio.sleep(random.uniform(0.05, 0.1))

        logger.debug(
            f"Clicked at ({click_x:.0f}, {click_y:.0f}) "
            f"style={click_style}, hold={actual_hold_ms:.1f}ms"
        )

        # Return metadata
        return {
            "x": click_x,
            "y": click_y,
            "jitter_x": jitter_x,
            "jitter_y": jitter_y,
            "hold_ms": round(actual_hold_ms, 2),
            "click_style": click_style,
            "button": button,
            "did_overshoot": did_overshoot,
            "did_spiral": did_spiral
        }

    async def click_element(
        self,
        selector: str,
        jitter_radius: Optional[float] = None
    ) -> bool:
        """
        Click on an element by selector with human-like behavior.

        Args:
            selector: CSS selector or XPath
            jitter_radius: Random offset radius

        Returns:
            True if element was found and clicked
        """
        try:
            element = await self.page.wait_for_selector(selector, timeout=5000)
            if not element:
                return False

            # Get element bounding box
            box = await element.bounding_box()
            if not box:
                return False

            # Calculate center with random offset within element
            center_x = box["x"] + box["width"] / 2
            center_y = box["y"] + box["height"] / 2

            # Add slight offset within element bounds (humans don't always hit dead center)
            offset_x = random.uniform(-box["width"] * 0.2, box["width"] * 0.2)
            offset_y = random.uniform(-box["height"] * 0.2, box["height"] * 0.2)

            await self.click_at(
                center_x + offset_x,
                center_y + offset_y,
                jitter_radius=jitter_radius
            )
            return True

        except Exception as e:
            logger.warning(f"Failed to click element {selector}: {e}")
            return False

    async def hover_with_tremor(
        self,
        x: float,
        y: float,
        duration: float,
        amplitude: Optional[float] = None
    ) -> None:
        """
        Hover at position with micro-tremor (simulates hand tremor).

        When humans hold their hand still, there's always slight movement.
        This simulates that natural tremor at 8-12 Hz.

        Args:
            x: Center X coordinate
            y: Center Y coordinate
            duration: How long to hover in seconds
            amplitude: Tremor amplitude in pixels (default from config)
        """
        if amplitude is None:
            amplitude = self.mouse_config.tremor_amplitude

        analytics = get_analytics()

        # Move to position first
        await self.move_to(x, y)

        # Log hover start
        if analytics:
            analytics.log_mouse_hover(x, y, duration * 1000)

        start_time = asyncio.get_event_loop().time()
        freq_min = self.mouse_config.tremor_frequency_min
        freq_max = self.mouse_config.tremor_frequency_max

        while asyncio.get_event_loop().time() - start_time < duration:
            # Random micro-movement
            tremor_x = random.gauss(0, amplitude)
            tremor_y = random.gauss(0, amplitude)

            # Clamp tremor
            tremor_x = max(-amplitude * 2, min(amplitude * 2, tremor_x))
            tremor_y = max(-amplitude * 2, min(amplitude * 2, tremor_y))

            await self.page.mouse.move(x + tremor_x, y + tremor_y)

            # Log tremor movement
            if analytics:
                analytics.log_mouse_tremor(x, y, tremor_x, tremor_y)

            # Delay based on tremor frequency
            frequency = random.uniform(freq_min, freq_max)
            await asyncio.sleep(1.0 / frequency)

        # Return to center
        await self.page.mouse.move(x, y)
        self._current_pos = Point(x, y)

    async def double_click_at(self, x: float, y: float) -> None:
        """Double-click at position"""
        await self.move_to(x, y)
        await self.page.mouse.dblclick(x, y)

    def _generate_bezier_path(
        self,
        start: Point,
        end: Point,
        num_points: int = 50,
        sharp: bool = False
    ) -> List[Point]:
        """
        Generate a cubic Bezier curve path between two points.

        Args:
            start: Starting point
            end: Ending point
            num_points: Number of points along the path
            sharp: If True, use more angular control points

        Returns:
            List of points along the Bezier curve
        """
        distance = start.distance_to(end)

        if distance < 5:
            return [end]

        # Calculate control points with random variance
        # Sharp curves have higher variance
        base_variance = self.mouse_config.bezier_control_variance
        variance = base_variance * (1.8 if sharp else 1.0)

        dx = end.x - start.x
        dy = end.y - start.y

        # Control point positions differ for sharp vs smooth
        if sharp:
            ctrl1_t = random.uniform(0.15, 0.35)
            ctrl2_t = random.uniform(0.65, 0.85)
        else:
            ctrl1_t = random.uniform(0.25, 0.45)
            ctrl2_t = random.uniform(0.55, 0.75)

        ctrl1_perp = random.uniform(-variance, variance) * distance
        ctrl1 = Point(
            start.x + dx * ctrl1_t + dy * ctrl1_perp / distance if distance > 0 else start.x,
            start.y + dy * ctrl1_t - dx * ctrl1_perp / distance if distance > 0 else start.y
        )

        ctrl2_perp = random.uniform(-variance, variance) * distance
        ctrl2 = Point(
            start.x + dx * ctrl2_t + dy * ctrl2_perp / distance if distance > 0 else end.x,
            start.y + dy * ctrl2_t - dx * ctrl2_perp / distance if distance > 0 else end.y
        )

        # Generate points along cubic Bezier
        path = []
        for i in range(num_points):
            t = i / (num_points - 1)
            t2 = t * t
            t3 = t2 * t
            mt = 1 - t
            mt2 = mt * mt
            mt3 = mt2 * mt

            x = mt3 * start.x + 3 * mt2 * t * ctrl1.x + 3 * mt * t2 * ctrl2.x + t3 * end.x
            y = mt3 * start.y + 3 * mt2 * t * ctrl1.y + 3 * mt * t2 * ctrl2.y + t3 * end.y

            path.append(Point(x, y))

        return path

    def _generate_direct_path(
        self,
        start: Point,
        end: Point,
        num_points: int = 25
    ) -> List[Point]:
        """
        Generate nearly straight path with slight noise.

        Real humans can't move in perfectly straight lines.
        """
        distance = start.distance_to(end)

        if distance < 5:
            return [end]

        path = []
        for i in range(num_points):
            t = i / (num_points - 1)

            # Linear interpolation
            x = start.x + (end.x - start.x) * t
            y = start.y + (end.y - start.y) * t

            # Add slight perpendicular noise (decreases near endpoints)
            edge_factor = 4 * t * (1 - t)  # Peaks at t=0.5
            noise_amplitude = min(3.0, distance * 0.02) * edge_factor
            noise_x = random.gauss(0, noise_amplitude)
            noise_y = random.gauss(0, noise_amplitude)

            path.append(Point(x + noise_x, y + noise_y))

        return path

    def _generate_s_curve_path(
        self,
        start: Point,
        end: Point,
        num_points: int = 50
    ) -> List[Point]:
        """
        Generate S-shaped path.

        Creates an elegant S-curve by using control points on opposite sides.
        """
        distance = start.distance_to(end)

        if distance < 5:
            return [end]

        dx = end.x - start.x
        dy = end.y - start.y

        # Perpendicular direction
        perp_x = -dy / distance if distance > 0 else 0
        perp_y = dx / distance if distance > 0 else 0

        # S-curve offset (one side then the other)
        offset = distance * random.uniform(0.15, 0.30)

        # Control point 1: offset to one side
        ctrl1 = Point(
            start.x + dx * 0.33 + perp_x * offset,
            start.y + dy * 0.33 + perp_y * offset
        )

        # Control point 2: offset to other side
        ctrl2 = Point(
            start.x + dx * 0.67 - perp_x * offset,
            start.y + dy * 0.67 - perp_y * offset
        )

        # Generate cubic Bezier with S-curve control points
        path = []
        for i in range(num_points):
            t = i / (num_points - 1)
            t2 = t * t
            t3 = t2 * t
            mt = 1 - t
            mt2 = mt * mt
            mt3 = mt2 * mt

            x = mt3 * start.x + 3 * mt2 * t * ctrl1.x + 3 * mt * t2 * ctrl2.x + t3 * end.x
            y = mt3 * start.y + 3 * mt2 * t * ctrl1.y + 3 * mt * t2 * ctrl2.y + t3 * end.y

            path.append(Point(x, y))

        return path

    def _generate_hesitant_path(
        self,
        start: Point,
        end: Point,
        num_points: int = 60
    ) -> List[Point]:
        """
        Generate path with micro-corrections/hesitations.

        Simulates uncertain movement with small backtracking.
        """
        distance = start.distance_to(end)

        if distance < 5:
            return [end]

        # First generate base bezier path
        base_path = self._generate_bezier_path(start, end, num_points=40)

        # Insert hesitation points
        path = []
        hesitation_points = random.randint(2, 4)
        hesitation_indices = sorted(random.sample(range(10, 35), hesitation_points))

        for i, point in enumerate(base_path):
            path.append(point)

            if i in hesitation_indices:
                # Add small backtrack
                backtrack_dist = random.uniform(1.5, 4.0)
                # Random direction (mostly backward)
                angle = random.uniform(2.5, 3.8)  # ~150-220 degrees
                bx = point.x + backtrack_dist * math.cos(angle)
                by = point.y + backtrack_dist * math.sin(angle)
                path.append(Point(bx, by))
                # Return near original
                path.append(Point(
                    point.x + random.uniform(-0.5, 0.5),
                    point.y + random.uniform(-0.5, 0.5)
                ))

        return path

    def _calculate_movement_time(self, distance: float, target_width: float) -> float:
        """
        Calculate movement time using Fitts' Law.

        Fitts' Law: MT = a + b * log2(2D/W)

        Where:
        - MT = movement time
        - D = distance to target
        - W = target width
        - a, b = empirical constants

        Args:
            distance: Distance to target in pixels
            target_width: Width of target element in pixels

        Returns:
            Movement time in seconds
        """
        if distance < 1:
            return self.mouse_config.min_movement_time

        # Fitts' Law calculation
        if target_width < 1:
            target_width = 1

        index_of_difficulty = math.log2(2 * distance / target_width)
        movement_time = self.mouse_config.fitts_a + self.mouse_config.fitts_b * index_of_difficulty

        # Add some random variance (humans aren't perfectly consistent)
        movement_time *= random.uniform(0.8, 1.2)

        # Clamp to reasonable bounds
        return max(
            self.mouse_config.min_movement_time,
            min(self.mouse_config.max_movement_time, movement_time)
        )

    def _get_speed_profile(self, num_points: int) -> List[float]:
        """
        Generate a speed profile for mouse movement.

        Human mouse movements follow a pattern:
        1. Start slow (acceleration)
        2. Peak speed in the middle (cruise)
        3. Slow down at the end (deceleration)

        This creates a bell-curve-like speed profile.

        Args:
            num_points: Number of points in the path

        Returns:
            List of speed multipliers (higher = faster)
        """
        if num_points < 3:
            return [1.0] * num_points

        profile = []
        for i in range(num_points):
            # Normalized position (0 to 1)
            t = i / (num_points - 1)

            # Bell curve using sine: sin(pi * t) peaks at 0.5
            # Add baseline so we never stop completely
            speed = 0.3 + 0.7 * math.sin(math.pi * t)

            # Add slight random variance
            speed *= random.uniform(0.9, 1.1)

            profile.append(speed)

        return profile

    async def get_current_position(self) -> Point:
        """Get the current mouse position"""
        return self._current_pos

    async def set_position(self, x: float, y: float) -> None:
        """Set current position without moving (for initialization)"""
        self._current_pos = Point(x, y)

    def get_profile_characteristics(self) -> dict:
        """
        Get profile-specific mouse characteristics for logging/debugging.

        Returns:
            dict with overshoot_chance, overshoot_ratio, spiral_chance, movement_weights
        """
        return {
            "overshoot_chance": round(self._overshoot_chance, 3),
            "overshoot_distance_ratio": round(self._overshoot_distance_ratio, 3),
            "spiral_chance": round(self._spiral_chance, 3),
            "movement_weights": self.get_movement_weights()
        }

    def get_movement_weights(self) -> dict:
        """Get movement type weights for logging."""
        return {k.value: v for k, v in self._movement_weights.items()}

    def _select_movement_type(self, distance: float) -> MovementType:
        """
        Select movement type based on distance and profile weights.

        Short distances favor DIRECT.
        Long distances favor BEZIER_SMOOTH and HESITANT.
        Medium distances keep normal distribution.
        """
        weights = self._movement_weights.copy()

        # Adjust weights based on distance
        if distance < 100:
            # Short distance: more direct movements, less hesitation
            weights[MovementType.DIRECT] *= 1.8
            weights[MovementType.S_CURVE] *= 0.6
            weights[MovementType.HESITANT] *= 0.5  # Still possible, just less likely
        elif distance > 500:
            # Long distance: more curves and hesitation
            weights[MovementType.BEZIER_SMOOTH] *= 1.4
            weights[MovementType.HESITANT] *= 1.3  # More hesitation on long moves
            weights[MovementType.DIRECT] *= 0.7
        # Medium distance (100-500): keep normal weights

        # Ensure no weight goes to zero (all types remain possible)
        for k in weights:
            weights[k] = max(weights[k], 2.0)

        # Weighted random selection
        types = list(weights.keys())
        type_weights = [weights[t] for t in types]

        return random.choices(types, weights=type_weights, k=1)[0]


    async def _spiral_approach(
        self,
        target_x: float,
        target_y: float,
        revolutions: float = 0.75
    ) -> None:
        """
        Approach target with a micro-spiral movement.

        Creates a subtle spiral pattern as cursor approaches the target,
        simulating the fine motor control adjustments humans make.

        Args:
            target_x: Target X coordinate
            target_y: Target Y coordinate
            revolutions: Number of spiral revolutions (0.5-1.0 recommended)
        """
        num_points = int(15 * revolutions)  # Points in spiral
        start_radius = self._spiral_radius

        for i in range(num_points):
            # Progress through spiral (0 to 1)
            progress = i / (num_points - 1)

            # Decreasing radius
            radius = start_radius * (1 - progress)

            # Angle increases with progress
            angle = progress * revolutions * 2 * math.pi

            # Calculate spiral point
            offset_x = radius * math.cos(angle)
            offset_y = radius * math.sin(angle)

            spiral_x = target_x + offset_x
            spiral_y = target_y + offset_y

            await self.page.mouse.move(spiral_x, spiral_y)
            await asyncio.sleep(random.uniform(0.01, 0.025))

        # Final move to exact target
        await self.page.mouse.move(target_x, target_y)
        self._current_pos = Point(target_x, target_y)

        # Log spiral
        analytics = get_analytics()
        if analytics:
            analytics.log_mouse_spiral(target_x, target_y, revolutions)

        logger.debug("Applied spiral approach to target")

    async def hover_for_menu(
        self,
        container_element: ElementHandle,
        menu_area_ratio: float = 0.85,
        wait_for_css: Optional[float] = None
    ) -> bool:
        """
        Hover over element to trigger CSS hover menu (like YouTube 3-dot menu).

        This method implements a two-phase hover:
        1. First hover in the general container area
        2. Wait for CSS hover effect to trigger
        3. Then move towards the menu button area

        Args:
            container_element: The container element (e.g., comment thread)
            menu_area_ratio: Horizontal ratio where menu appears (0.85 = 85% from left)
            wait_for_css: Time to wait for CSS hover trigger (default 0.7s)

        Returns:
            True if hover was successful
        """
        if wait_for_css is None:
            wait_for_css = self._hover_wait_for_css

        try:
            box = await container_element.bounding_box()
            if not box:
                return False

            # Phase 1: Enter the container area (not directly at menu)
            # Enter from the left/center area first
            entry_x = box["x"] + box["width"] * random.uniform(0.3, 0.6)
            entry_y = box["y"] + box["height"] * random.uniform(0.3, 0.5)

            await self.move_to(entry_x, entry_y, target_width=box["width"], target_height=box["height"])

            # Phase 2: Wait for CSS hover to trigger (YouTube needs ~0.7s)
            logger.debug(f"Waiting {wait_for_css:.1f}s for CSS hover trigger")
            await self.hover_with_tremor(entry_x, entry_y, duration=wait_for_css, amplitude=1.0)

            # Phase 3: Move towards menu area (right side)
            menu_x = box["x"] + box["width"] * menu_area_ratio
            menu_y = box["y"] + box["height"] * random.uniform(0.2, 0.4)

            await self.move_to(menu_x, menu_y, target_width=30, target_height=30)

            # Small hover at menu position
            await self.hover_with_tremor(menu_x, menu_y, duration=random.uniform(0.3, 0.5))

            return True

        except Exception as e:
            logger.warning(f"Hover for menu failed: {e}")
            return False

    async def click_with_aiming(
        self,
        x: float,
        y: float,
        target_width: float = 30,
        target_height: float = 30
    ) -> None:
        """
        Click with "aiming" behavior - approach, slight adjust, then click.

        Combines overshoot, spiral, and precision clicking for small targets
        like menu buttons.

        Args:
            x: Target X coordinate
            y: Target Y coordinate
            target_width: Target element width
            target_height: Target element height
        """
        # Move to general area
        await self.move_to(x, y, target_width=target_width, target_height=target_height)

        # For small targets, apply spiral approach
        if target_width < 50 and target_height < 50:
            if random.random() < 0.4:
                await self._spiral_approach(x, y, revolutions=0.5)

        # Apply overshoot and correction
        if random.random() < self._overshoot_chance:
            await self._apply_overshoot(x, y)

        # Brief pause (aiming hesitation)
        await asyncio.sleep(random.uniform(0.08, 0.18))

        # Click
        await self.page.mouse.click(x, y)

        logger.debug(f"Clicked with aiming at ({x:.0f}, {y:.0f})")

    async def move_outside_viewport(self, duration: float = 0.5) -> None:
        """
        Move cursor outside the visible viewport area.

        Used for simulating distraction/focus loss states where
        the cursor leaves the active area.

        Args:
            duration: How long to spend moving outside
        """
        viewport = self.page.viewport_size
        if not viewport:
            return

        # Choose random edge to exit from
        edge = random.choice(["top", "bottom", "left", "right"])

        if edge == "top":
            target_x = random.uniform(100, viewport["width"] - 100)
            target_y = -50  # Above viewport
        elif edge == "bottom":
            target_x = random.uniform(100, viewport["width"] - 100)
            target_y = viewport["height"] + 50  # Below viewport
        elif edge == "left":
            target_x = -50  # Left of viewport
            target_y = random.uniform(100, viewport["height"] - 100)
        else:  # right
            target_x = viewport["width"] + 50  # Right of viewport
            target_y = random.uniform(100, viewport["height"] - 100)

        await self.move_to(target_x, target_y)
        logger.debug(f"Cursor moved outside viewport ({edge} edge)")
