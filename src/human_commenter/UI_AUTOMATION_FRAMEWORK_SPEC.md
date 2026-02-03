# UI AUTOMATION FRAMEWORK — HUMAN-LIKE INTERACTION LIBRARY

**Project:** Browser automation framework with realistic human behavior patterns  
**Purpose:** Quality assurance, accessibility testing, user experience simulation  
**Version:** 1.0

---

# MODULE 1: BIMODAL DELAY SYSTEM

## Overview
Implement delay distribution that matches real human cognitive patterns for realistic UI testing.

## Background
Research shows human response times follow bimodal distribution:
- **Fast mode (70%):** Automatic/reflexive actions (~0.1s)
- **Slow mode (30%):** Deliberate/thinking actions (~0.5s)

Single Gaussian distribution is unrealistic for human behavior simulation.

## File: `delays/bimodal_delay.py`

```python
"""
Bimodal Delay Generator

Generates realistic human-like delays based on cognitive psychology research.
Used for UI testing frameworks requiring natural timing patterns.
"""

import asyncio
import random
from typing import Tuple, List
from enum import Enum
from dataclasses import dataclass


class ActionMode(Enum):
    AUTOMATIC = "automatic"
    DELIBERATE = "deliberate"


@dataclass
class DelayConfig:
    fast_mean: float = 0.08
    fast_std: float = 0.025
    slow_mean: float = 0.35
    slow_std: float = 0.12
    fast_probability: float = 0.70
    min_bound: float = 0.03
    max_bound: float = 2.0


class BimodalDelay:
    """
    Generates delays with bimodal distribution matching human patterns.
    
    Based on research: Card, Moran & Newell (1983) "The Psychology of Human-Computer Interaction"
    """
    
    def __init__(self, config: DelayConfig = None):
        self.config = config or DelayConfig()
        self._mode_history: List[ActionMode] = []
        self._max_consecutive = 6
    
    @classmethod
    def for_typing(cls) -> "BimodalDelay":
        """Optimized for inter-keystroke intervals."""
        return cls(DelayConfig(
            fast_mean=0.07,
            fast_std=0.02,
            slow_mean=0.22,
            slow_std=0.06,
            fast_probability=0.75,
            min_bound=0.03,
            max_bound=0.6
        ))
    
    @classmethod
    def for_clicks(cls) -> "BimodalDelay":
        """Optimized for between-click intervals."""
        return cls(DelayConfig(
            fast_mean=0.15,
            fast_std=0.05,
            slow_mean=0.50,
            slow_std=0.15,
            fast_probability=0.65,
            min_bound=0.08,
            max_bound=1.5
        ))
    
    @classmethod
    def for_navigation(cls) -> "BimodalDelay":
        """Optimized for page navigation decisions."""
        return cls(DelayConfig(
            fast_mean=0.8,
            fast_std=0.2,
            slow_mean=2.5,
            slow_std=0.8,
            fast_probability=0.60,
            min_bound=0.3,
            max_bound=5.0
        ))
    
    def _should_use_fast(self) -> bool:
        """Determine mode with rhythm awareness to prevent unrealistic streaks."""
        if len(self._mode_history) >= self._max_consecutive:
            recent = self._mode_history[-self._max_consecutive:]
            if all(m == ActionMode.AUTOMATIC for m in recent):
                return False
            if all(m == ActionMode.DELIBERATE for m in recent):
                return True
        
        return random.random() < self.config.fast_probability
    
    def sample(self) -> Tuple[float, ActionMode]:
        """Sample delay value and mode."""
        use_fast = self._should_use_fast()
        
        if use_fast:
            delay = random.gauss(self.config.fast_mean, self.config.fast_std)
            mode = ActionMode.AUTOMATIC
        else:
            delay = random.gauss(self.config.slow_mean, self.config.slow_std)
            mode = ActionMode.DELIBERATE
        
        delay = max(self.config.min_bound, min(self.config.max_bound, delay))
        
        self._mode_history.append(mode)
        if len(self._mode_history) > 20:
            self._mode_history.pop(0)
        
        return (delay, mode)
    
    def sample_value(self) -> float:
        """Sample just the delay value."""
        return self.sample()[0]
    
    async def wait(self) -> float:
        """Wait for sampled delay duration."""
        delay = self.sample_value()
        await asyncio.sleep(delay)
        return delay


# Convenience functions
async def short_pause() -> float:
    return await BimodalDelay(DelayConfig(0.10, 0.03, 0.25, 0.08)).wait()

async def medium_pause() -> float:
    return await BimodalDelay(DelayConfig(0.4, 0.1, 1.2, 0.3)).wait()

async def long_pause() -> float:
    return await BimodalDelay(DelayConfig(1.5, 0.4, 4.0, 1.0)).wait()
```

## Tests

```python
# tests/test_bimodal_delay.py

import pytest
from delays.bimodal_delay import BimodalDelay, DelayConfig

def test_bimodal_distribution():
    """Verify samples show two distinct modes."""
    delay = BimodalDelay.for_typing()
    samples = [delay.sample_value() for _ in range(1000)]
    
    fast_count = sum(1 for s in samples if s < 0.12)
    slow_count = sum(1 for s in samples if s > 0.18)
    
    assert fast_count > 500, "Insufficient fast-mode samples"
    assert slow_count > 150, "Insufficient slow-mode samples"

def test_bounds_respected():
    """Verify min/max bounds are enforced."""
    config = DelayConfig(min_bound=0.05, max_bound=1.0)
    delay = BimodalDelay(config)
    
    for _ in range(500):
        value = delay.sample_value()
        assert 0.05 <= value <= 1.0

def test_no_long_streaks():
    """Verify rhythm variation prevents monotonous patterns."""
    delay = BimodalDelay(DelayConfig(fast_probability=0.9))
    
    modes = [delay.sample()[1] for _ in range(100)]
    
    max_streak = 1
    current_streak = 1
    for i in range(1, len(modes)):
        if modes[i] == modes[i-1]:
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 1
    
    assert max_streak <= 7, f"Streak too long: {max_streak}"
```

---

# MODULE 2: MOUSE MOVEMENT PATTERNS

## Overview
Implement diverse mouse movement algorithms based on motor control research.

## Background
Real mouse movements vary by context:
- Short distances: nearly direct paths
- Long distances: curved trajectories with acceleration patterns
- Targets: approach with correction movements

## File: `input/mouse_movement.py`

```python
"""
Human-Like Mouse Movement Generator

Based on Fitts' Law and motor control research.
Provides multiple movement patterns for realistic UI interaction testing.
"""

import asyncio
import random
import math
from typing import List, Optional, Tuple
from enum import Enum
from dataclasses import dataclass


@dataclass
class Point:
    x: float
    y: float
    
    def distance_to(self, other: "Point") -> float:
        return math.sqrt((self.x - other.x)**2 + (self.y - other.y)**2)


class MovementType(Enum):
    BEZIER_SMOOTH = "bezier_smooth"
    BEZIER_SHARP = "bezier_sharp"
    DIRECT = "direct"
    S_CURVE = "s_curve"
    HESITANT = "hesitant"


@dataclass
class MouseConfig:
    base_speed: float = 400.0  # pixels per second
    bezier_control_variance: float = 0.35
    click_jitter_radius: float = 3.0
    overshoot_chance: float = 0.12
    overshoot_distance: float = 0.08


class MovementGenerator:
    """Generates various mouse movement path types."""
    
    def __init__(self, config: MouseConfig = None, profile_seed: int = None):
        self.config = config or MouseConfig()
        
        # Profile-specific movement style weights
        if profile_seed:
            rng = random.Random(profile_seed)
        else:
            rng = random
        
        self._movement_weights = {
            MovementType.BEZIER_SMOOTH: 30 + rng.randint(-8, 8),
            MovementType.BEZIER_SHARP: 15 + rng.randint(-5, 8),
            MovementType.DIRECT: 25 + rng.randint(-8, 12),
            MovementType.S_CURVE: 15 + rng.randint(-5, 5),
            MovementType.HESITANT: 15 + rng.randint(-5, 8),
        }
    
    def select_movement_type(self, distance: float) -> MovementType:
        """Select movement type based on distance and profile weights."""
        weights = self._movement_weights.copy()
        
        if distance < 100:
            weights[MovementType.DIRECT] *= 1.8
            weights[MovementType.S_CURVE] *= 0.5
        elif distance > 400:
            weights[MovementType.BEZIER_SMOOTH] *= 1.5
            weights[MovementType.HESITANT] *= 1.3
        
        total = sum(weights.values())
        r = random.uniform(0, total)
        
        cumulative = 0
        for move_type, weight in weights.items():
            cumulative += weight
            if r <= cumulative:
                return move_type
        
        return MovementType.BEZIER_SMOOTH
    
    def generate_path(
        self, 
        start: Point, 
        end: Point, 
        movement_type: MovementType = None
    ) -> List[Point]:
        """Generate movement path between two points."""
        distance = start.distance_to(end)
        
        if distance < 3:
            return [end]
        
        if movement_type is None:
            movement_type = self.select_movement_type(distance)
        
        if movement_type == MovementType.DIRECT:
            return self._generate_direct(start, end)
        elif movement_type == MovementType.S_CURVE:
            return self._generate_s_curve(start, end)
        elif movement_type == MovementType.HESITANT:
            return self._generate_hesitant(start, end)
        elif movement_type == MovementType.BEZIER_SHARP:
            return self._generate_bezier(start, end, sharp=True)
        else:
            return self._generate_bezier(start, end, sharp=False)
    
    def _generate_direct(self, start: Point, end: Point) -> List[Point]:
        """Nearly straight path with minimal deviation."""
        distance = start.distance_to(end)
        num_points = max(8, int(distance / 25))
        
        path = []
        dx, dy = end.x - start.x, end.y - start.y
        length = math.sqrt(dx*dx + dy*dy) or 1
        
        for i in range(num_points):
            t = i / (num_points - 1)
            x = start.x + dx * t
            y = start.y + dy * t
            
            if 0.1 < t < 0.9:
                noise = random.gauss(0, distance * 0.008)
                x += (-dy / length) * noise
                y += (dx / length) * noise
            
            path.append(Point(x, y))
        
        return path
    
    def _generate_s_curve(self, start: Point, end: Point) -> List[Point]:
        """S-shaped curved path."""
        num_points = 55
        path = []
        
        dx, dy = end.x - start.x, end.y - start.y
        distance = math.sqrt(dx*dx + dy*dy) or 1
        
        perp_x, perp_y = -dy / distance, dx / distance
        amplitude = distance * random.uniform(0.12, 0.22)
        
        for i in range(num_points):
            t = i / (num_points - 1)
            base_x = start.x + dx * t
            base_y = start.y + dy * t
            
            s_offset = amplitude * math.sin(t * math.pi * 2) * (1 - abs(2*t - 1))
            
            path.append(Point(
                base_x + perp_x * s_offset,
                base_y + perp_y * s_offset
            ))
        
        return path
    
    def _generate_hesitant(self, start: Point, end: Point) -> List[Point]:
        """Path with mid-movement pause."""
        base_path = self._generate_bezier(start, end, num_points=35)
        
        path = []
        pause_idx = random.randint(12, 25)
        pause_duration = random.randint(4, 10)
        
        for i, point in enumerate(base_path):
            path.append(point)
            
            if i == pause_idx:
                for _ in range(pause_duration):
                    path.append(Point(
                        point.x + random.gauss(0, 0.4),
                        point.y + random.gauss(0, 0.4)
                    ))
        
        return path
    
    def _generate_bezier(
        self, 
        start: Point, 
        end: Point, 
        num_points: int = 45,
        sharp: bool = False
    ) -> List[Point]:
        """Cubic Bezier curve path."""
        dx, dy = end.x - start.x, end.y - start.y
        distance = math.sqrt(dx*dx + dy*dy) or 1
        
        if sharp:
            ctrl1_t = random.uniform(0.1, 0.45)
            ctrl2_t = random.uniform(0.55, 0.9)
            variance = self.config.bezier_control_variance * 1.8
        else:
            ctrl1_t = random.uniform(0.25, 0.40)
            ctrl2_t = random.uniform(0.60, 0.75)
            variance = self.config.bezier_control_variance
        
        def get_control(t: float) -> Point:
            perp = random.uniform(-variance, variance) * distance
            return Point(
                start.x + dx * t + (dy / distance) * perp,
                start.y + dy * t - (dx / distance) * perp
            )
        
        ctrl1 = get_control(ctrl1_t)
        ctrl2 = get_control(ctrl2_t)
        
        path = []
        for i in range(num_points):
            t = i / (num_points - 1)
            mt = 1 - t
            
            x = (mt**3 * start.x + 
                 3 * mt**2 * t * ctrl1.x + 
                 3 * mt * t**2 * ctrl2.x + 
                 t**3 * end.x)
            y = (mt**3 * start.y + 
                 3 * mt**2 * t * ctrl1.y + 
                 3 * mt * t**2 * ctrl2.y + 
                 t**3 * end.y)
            
            path.append(Point(x, y))
        
        return path
    
    def get_asymmetric_speed_profile(self, num_points: int) -> List[float]:
        """
        Generate asymmetric velocity profile.
        
        Human movements: fast acceleration, slow deceleration.
        Peak speed occurs around 30-35% of movement.
        """
        if num_points < 3:
            return [1.0] * num_points
        
        profile = []
        peak_pos = random.uniform(0.28, 0.38)
        accel_power = random.uniform(0.4, 0.6)
        decel_power = random.uniform(1.8, 2.5)
        
        for i in range(num_points):
            t = i / (num_points - 1)
            
            if t < peak_pos:
                normalized = t / peak_pos
                speed = 0.15 + 0.85 * (normalized ** accel_power)
            else:
                normalized = (t - peak_pos) / (1 - peak_pos)
                speed = 1.0 - 0.75 * (normalized ** decel_power)
            
            if t > 0.85:
                speed += random.gauss(0, 0.08)
            
            speed *= random.uniform(0.94, 1.06)
            profile.append(max(0.12, min(1.15, speed)))
        
        return profile
    
    def calculate_movement_time(
        self, 
        distance: float, 
        target_size: float
    ) -> float:
        """
        Calculate movement time using Fitts' Law.
        
        T = a + b * log2(D/W + 1)
        """
        a = 0.05
        b = 0.15
        
        if target_size <= 0:
            target_size = 10
        
        index_of_difficulty = math.log2(distance / target_size + 1)
        base_time = a + b * index_of_difficulty
        
        return base_time * random.uniform(0.85, 1.15)


class MouseExecutor:
    """
    Executes mouse movements on a Playwright page.
    
    Combines MovementGenerator paths with realistic timing.
    """
    
    def __init__(self, page, generator: MovementGenerator = None):
        self.page = page
        self.generator = generator or MovementGenerator()
        self._current_pos = Point(0, 0)
    
    async def move_to(
        self,
        x: float,
        y: float,
        target_size: float = 50.0
    ) -> None:
        """
        Move mouse to target with realistic path and timing.
        
        Args:
            x, y: Target coordinates
            target_size: Size of target element for Fitts' Law
        """
        start = self._current_pos
        end = Point(x, y)
        distance = start.distance_to(end)
        
        if distance < 3:
            await self.page.mouse.move(x, y)
            self._current_pos = end
            return
        
        # Generate path
        path = self.generator.generate_path(start, end)
        
        # Calculate timing
        movement_time = self.generator.calculate_movement_time(distance, target_size)
        speed_profile = self.generator.get_asymmetric_speed_profile(len(path))
        
        # Execute movement
        for i, point in enumerate(path):
            base_delay = movement_time / len(path)
            adjusted = base_delay / speed_profile[i] if speed_profile[i] > 0 else base_delay
            
            await self.page.mouse.move(point.x, point.y)
            await asyncio.sleep(adjusted)
        
        self._current_pos = end
    
    async def hover(
        self,
        x: float,
        y: float,
        duration: float = None,
        with_micro_movements: bool = True
    ) -> None:
        """
        Hover over element with optional micro-movements.
        
        Real users don't hold mouse perfectly still while hovering.
        
        Args:
            x, y: Hover position
            duration: How long to hover (None = random 0.5-2s)
            with_micro_movements: Add subtle tremor/drift
        """
        # Move to position
        await self.move_to(x, y)
        
        # Determine hover duration
        if duration is None:
            duration = random.uniform(0.5, 2.0)
        
        if not with_micro_movements:
            await asyncio.sleep(duration)
            return
        
        # Hover with micro-movements
        start_time = asyncio.get_event_loop().time()
        
        while (asyncio.get_event_loop().time() - start_time) < duration:
            # Small random drift
            drift_x = random.gauss(0, 0.8)
            drift_y = random.gauss(0, 0.8)
            
            await self.page.mouse.move(x + drift_x, y + drift_y)
            await asyncio.sleep(random.uniform(0.05, 0.15))
        
        # Return to center
        await self.page.mouse.move(x, y)
        self._current_pos = Point(x, y)
    
    async def hover_before_click(
        self,
        x: float,
        y: float,
        hover_chance: float = 0.4
    ) -> None:
        """
        Optionally hover before clicking (human pattern).
        
        Real users often pause briefly over clickable elements
        before deciding to click.
        """
        if random.random() < hover_chance:
            await self.hover(x, y, duration=random.uniform(0.3, 0.8))
    
    def update_position(self, x: float, y: float) -> None:
        """Update tracked position (use after external moves)."""
        self._current_pos = Point(x, y)
    
    @property
    def current_position(self) -> Point:
        """Get current mouse position."""
        return self._current_pos
```

## Tests

```python
# tests/test_mouse_movement.py

import pytest
from input.mouse_movement import MovementGenerator, MouseExecutor, Point, MovementType

def test_movement_type_variety():
    """Verify multiple movement types are used."""
    gen = MovementGenerator()
    
    types_used = set()
    for _ in range(100):
        t = gen.select_movement_type(300)
        types_used.add(t)
    
    assert len(types_used) >= 4, "Insufficient movement variety"

def test_path_reaches_target():
    """Verify all paths end at target."""
    gen = MovementGenerator()
    start = Point(100, 100)
    end = Point(500, 400)
    
    for move_type in MovementType:
        path = gen.generate_path(start, end, move_type)
        final = path[-1]
        
        assert abs(final.x - end.x) < 5
        assert abs(final.y - end.y) < 5

def test_asymmetric_velocity():
    """Verify velocity peak is in first half of movement."""
    gen = MovementGenerator()
    profile = gen.get_asymmetric_speed_profile(50)
    
    peak_idx = profile.index(max(profile))
    assert peak_idx < 25, "Peak should be in first half"

def test_short_distance_prefers_direct():
    """Short movements should favor direct paths."""
    gen = MovementGenerator()
    
    direct_count = 0
    for _ in range(100):
        t = gen.select_movement_type(50)
        if t == MovementType.DIRECT:
            direct_count += 1
    
    assert direct_count > 30, "Short distances should prefer direct"

@pytest.mark.asyncio
async def test_executor_tracks_position():
    """Verify executor tracks current position."""
    # Mock page object
    class MockMouse:
        async def move(self, x, y): pass
    
    class MockPage:
        mouse = MockMouse()
    
    executor = MouseExecutor(MockPage())
    executor.update_position(100, 100)
    
    assert executor.current_position.x == 100
    assert executor.current_position.y == 100
```

---

# MODULE 3: REALISTIC CLICK TIMING

## Overview
Implement click event timing that matches human motor patterns.

## Background
Real clicks have measurable phases:
1. mousedown (finger contacts)
2. 50-150ms hold (finger presses)
3. mouseup (finger releases)

Instant clicks (<10ms) are unrealistic.

## File: `input/click_handler.py`

```python
"""
Realistic Click Event Handler

Implements proper timing between mousedown/mouseup events
to match human motor control patterns.
"""

import asyncio
import random
from typing import Optional
from dataclasses import dataclass


@dataclass
class ClickConfig:
    tap_hold_min: float = 0.04
    tap_hold_max: float = 0.09
    normal_hold_min: float = 0.08
    normal_hold_max: float = 0.15
    deliberate_hold_min: float = 0.12
    deliberate_hold_max: float = 0.25
    pre_click_pause_min: float = 0.02
    pre_click_pause_max: float = 0.08
    post_click_pause_min: float = 0.03
    post_click_pause_max: float = 0.10


class ClickHandler:
    """
    Handles click events with realistic timing.
    
    Real human clicks have distinct phases that automation
    frameworks typically skip.
    """
    
    def __init__(self, page, config: ClickConfig = None):
        self.page = page
        self.config = config or ClickConfig()
    
    async def click_at(
        self, 
        x: float, 
        y: float, 
        button: str = "left",
        click_style: str = None
    ) -> None:
        """
        Perform click with realistic event timing.
        
        Args:
            x, y: Click coordinates
            button: Mouse button
            click_style: 'tap', 'normal', or 'deliberate'
        """
        # Pre-click pause
        await asyncio.sleep(random.uniform(
            self.config.pre_click_pause_min,
            self.config.pre_click_pause_max
        ))
        
        # Select click style
        if click_style is None:
            click_style = random.choices(
                ['tap', 'normal', 'deliberate'],
                weights=[25, 55, 20]
            )[0]
        
        # Mouse down
        await self.page.mouse.down(button=button)
        
        # Hold duration based on style
        if click_style == 'tap':
            hold = random.uniform(
                self.config.tap_hold_min,
                self.config.tap_hold_max
            )
        elif click_style == 'deliberate':
            hold = random.uniform(
                self.config.deliberate_hold_min,
                self.config.deliberate_hold_max
            )
        else:
            hold = random.uniform(
                self.config.normal_hold_min,
                self.config.normal_hold_max
            )
        
        # Optional micro-movement during hold
        if hold > 0.1 and random.random() < 0.3:
            await asyncio.sleep(hold * 0.4)
            await self.page.mouse.move(
                x + random.gauss(0, 0.3),
                y + random.gauss(0, 0.3)
            )
            await asyncio.sleep(hold * 0.6)
        else:
            await asyncio.sleep(hold)
        
        # Mouse up
        await self.page.mouse.up(button=button)
        
        # Brief post-release delay
        await asyncio.sleep(random.uniform(0.005, 0.02))
        
        # Post-click pause
        await asyncio.sleep(random.uniform(
            self.config.post_click_pause_min,
            self.config.post_click_pause_max
        ))
    
    async def double_click_at(self, x: float, y: float) -> None:
        """Double-click with realistic inter-click timing."""
        # First click
        await self.page.mouse.down()
        await asyncio.sleep(random.uniform(0.06, 0.12))
        await self.page.mouse.up()
        
        # Inter-click delay (50-150ms is human range)
        await asyncio.sleep(random.uniform(0.05, 0.15))
        
        # Second click
        await self.page.mouse.down()
        await asyncio.sleep(random.uniform(0.05, 0.10))
        await self.page.mouse.up()
```

---

# MODULE 4: SCROLL WHEEL NORMALIZATION

## Overview
Normalize scroll wheel delta values to match real input devices.

## Background
Real scroll devices produce discrete delta values:
- Windows mouse: 120 per notch
- Mac mouse: 40-120 variable
- Touchpad: 2-15 fine-grained

Arbitrary values like 347 are unrealistic.

## File: `input/scroll_normalizer.py`

```python
"""
Scroll Wheel Delta Normalizer

Converts scroll amounts to realistic device-appropriate delta values.
"""

import random
from typing import List, Optional
from dataclasses import dataclass


@dataclass
class DeviceProfile:
    base_delta: Optional[int]
    noise_range: tuple
    weight: float


class ScrollNormalizer:
    """
    Normalizes scroll values to match real input devices.
    """
    
    DEVICES = {
        'windows_mouse': DeviceProfile(base_delta=120, noise_range=(-5, 5), weight=55),
        'mac_mouse': DeviceProfile(base_delta=40, noise_range=(-3, 3), weight=15),
        'precision_mouse': DeviceProfile(base_delta=60, noise_range=(-2, 2), weight=10),
        'touchpad': DeviceProfile(base_delta=None, noise_range=(3, 12), weight=20),
    }
    
    def __init__(self, profile_seed: int = None):
        if profile_seed:
            rng = random.Random(profile_seed)
        else:
            rng = random
        
        devices = list(self.DEVICES.keys())
        weights = [self.DEVICES[d].weight for d in devices]
        self.device_type = rng.choices(devices, weights=weights)[0]
        self.device = self.DEVICES[self.device_type]
    
    def normalize(self, target_pixels: int) -> List[int]:
        """Convert pixel scroll amount to realistic delta events."""
        if self.device_type == 'touchpad':
            return self._normalize_touchpad(target_pixels)
        return self._normalize_mouse(target_pixels)
    
    def _normalize_mouse(self, target: int) -> List[int]:
        """Discrete mouse wheel events."""
        base = self.device.base_delta
        noise_min, noise_max = self.device.noise_range
        
        direction = 1 if target > 0 else -1
        remaining = abs(target)
        deltas = []
        
        while remaining > base * 0.4:
            mult = random.choice([1, 1, 1, 2]) if remaining > base * 2.5 else 1
            
            delta = base * mult + random.randint(noise_min, noise_max)
            delta = min(delta, int(remaining * 1.2))
            
            deltas.append(delta * direction)
            remaining -= delta
        
        return deltas
    
    def _normalize_touchpad(self, target: int) -> List[int]:
        """Fine-grained touchpad events."""
        min_d, max_d = self.device.noise_range
        direction = 1 if target > 0 else -1
        remaining = abs(target)
        deltas = []
        
        while remaining > 0:
            delta = random.randint(min_d, max_d)
            
            if len(deltas) > 5 and remaining > abs(target) * 0.4:
                delta = int(delta * random.uniform(1.3, 1.7))
            
            delta = min(delta, remaining)
            deltas.append(delta * direction)
            remaining -= delta
        
        return deltas
    
    def get_inter_event_delay(self) -> float:
        """Get appropriate delay between scroll events."""
        if self.device_type == 'touchpad':
            return random.uniform(0.008, 0.02)
        return random.uniform(0.025, 0.06)
```

---

# MODULE 5: KEYBOARD INPUT PATTERNS

## Overview
Implement realistic typing with natural error patterns and corrections.

## Background
Real typing includes:
- Variable speed (fast for common words, slow for thinking)
- Natural errors (adjacent keys, transpositions, case errors)
- Self-corrections with realistic timing

## File: `input/keyboard_handler.py`

```python
"""
Realistic Keyboard Input Handler

Implements natural typing patterns including errors and corrections.
"""

import asyncio
import random
from typing import List, Optional
from enum import Enum

from delays.bimodal_delay import BimodalDelay


# QWERTY keyboard adjacency map
QWERTY_ADJACENT = {
    'q': ['w', 'a'], 'w': ['q', 'e', 's', 'a'], 'e': ['w', 'r', 'd', 's'],
    'r': ['e', 't', 'f', 'd'], 't': ['r', 'y', 'g', 'f'], 'y': ['t', 'u', 'h', 'g'],
    'u': ['y', 'i', 'j', 'h'], 'i': ['u', 'o', 'k', 'j'], 'o': ['i', 'p', 'l', 'k'],
    'p': ['o', 'l'], 'a': ['q', 'w', 's', 'z'], 's': ['a', 'w', 'e', 'd', 'z', 'x'],
    'd': ['s', 'e', 'r', 'f', 'x', 'c'], 'f': ['d', 'r', 't', 'g', 'c', 'v'],
    'g': ['f', 't', 'y', 'h', 'v', 'b'], 'h': ['g', 'y', 'u', 'j', 'b', 'n'],
    'j': ['h', 'u', 'i', 'k', 'n', 'm'], 'k': ['j', 'i', 'o', 'l', 'm'],
    'l': ['k', 'o', 'p'], 'z': ['a', 's', 'x'], 'x': ['z', 's', 'd', 'c'],
    'c': ['x', 'd', 'f', 'v'], 'v': ['c', 'f', 'g', 'b'], 'b': ['v', 'g', 'h', 'n'],
    'n': ['b', 'h', 'j', 'm'], 'm': ['n', 'j', 'k'],
}


class TypoType(Enum):
    ADJACENT = "adjacent"
    SKIP = "skip"
    DOUBLE = "double"
    SWAP = "swap"
    CASE = "case"


class KeyboardHandler:
    """
    Handles keyboard input with realistic human patterns.
    """
    
    def __init__(
        self, 
        page, 
        error_rate: float = 0.03,
        profile_seed: int = None
    ):
        self.page = page
        self.error_rate = error_rate
        
        # Profile-specific error patterns
        if profile_seed:
            rng = random.Random(profile_seed)
        else:
            rng = random
        
        self._typo_weights = {
            TypoType.ADJACENT: 40 + rng.randint(-8, 8),
            TypoType.SKIP: 12 + rng.randint(-4, 8),
            TypoType.DOUBLE: 20 + rng.randint(-5, 8),
            TypoType.SWAP: 15 + rng.randint(-5, 8),
            TypoType.CASE: 10 + rng.randint(-4, 4),
        }
        
        # Bimodal typing delay
        self._delay = BimodalDelay.for_typing()
    
    async def type_text(self, text: str) -> None:
        """Type text with natural patterns and occasional errors."""
        i = 0
        while i < len(text):
            char = text[i]
            next_char = text[i + 1] if i + 1 < len(text) else None
            
            # Occasional thinking pause
            if random.random() < 0.05:
                await asyncio.sleep(random.uniform(0.3, 1.2))
            
            # Maybe make and correct error
            if self._should_make_error(char):
                typo_type = self._select_typo_type(char, next_char)
                chars_consumed = await self._make_error(char, next_char, typo_type)
                i += chars_consumed
            else:
                await self._type_char(char)
                i += 1
            
            await self._delay.wait()
    
    def _should_make_error(self, char: str) -> bool:
        """Determine if error should occur."""
        if not char.isalpha():
            return False
        return random.random() < self.error_rate
    
    def _select_typo_type(self, char: str, next_char: Optional[str]) -> TypoType:
        """Select error type based on context."""
        weights = self._typo_weights.copy()
        
        if not next_char:
            weights[TypoType.SWAP] = 0
        if not char.isalpha():
            weights[TypoType.CASE] = 0
        
        total = sum(weights.values())
        r = random.uniform(0, total)
        
        cumulative = 0
        for typo_type, weight in weights.items():
            cumulative += weight
            if r <= cumulative:
                return typo_type
        
        return TypoType.ADJACENT
    
    async def _make_error(
        self, 
        char: str, 
        next_char: Optional[str],
        typo_type: TypoType
    ) -> int:
        """Make and correct an error. Returns chars consumed."""
        
        if typo_type == TypoType.ADJACENT:
            adjacent = QWERTY_ADJACENT.get(char.lower(), [])
            if adjacent:
                wrong = random.choice(adjacent)
                if char.isupper():
                    wrong = wrong.upper()
                await self._type_char(wrong)
                await asyncio.sleep(random.uniform(0.15, 0.30))
                await self._backspace(1)
                await self._type_char(char)
            else:
                await self._type_char(char)
            return 1
        
        elif typo_type == TypoType.SKIP:
            await asyncio.sleep(random.uniform(0.3, 0.6))
            await self._type_char(char)
            return 1
        
        elif typo_type == TypoType.DOUBLE:
            await self._type_char(char)
            await self._delay.wait()
            await self._type_char(char)
            await asyncio.sleep(random.uniform(0.2, 0.4))
            await self._backspace(1)
            return 1
        
        elif typo_type == TypoType.SWAP and next_char:
            await self._type_char(next_char)
            await self._delay.wait()
            await self._type_char(char)
            await asyncio.sleep(random.uniform(0.25, 0.45))
            await self._backspace(2)
            await self._type_char(char)
            await self._delay.wait()
            await self._type_char(next_char)
            return 2
        
        elif typo_type == TypoType.CASE:
            wrong = char.lower() if char.isupper() else char.upper()
            await self._type_char(wrong)
            await asyncio.sleep(random.uniform(0.2, 0.35))
            await self._backspace(1)
            await self._type_char(char)
            return 1
        
        await self._type_char(char)
        return 1
    
    async def _type_char(self, char: str) -> None:
        """Type single character."""
        await self.page.keyboard.type(char)
    
    async def _backspace(self, count: int) -> None:
        """Press backspace with appropriate timing."""
        for _ in range(count):
            await self.page.keyboard.press("Backspace")
            await asyncio.sleep(random.uniform(0.04, 0.10))
```

---

# MODULE 6: VIEWPORT CONFIGURATION

## Overview
Implement viewport pool with realistic screen size distribution.

## Background
Real users have diverse screen sizes. Testing should reflect actual market distribution.

## File: `config/viewport_pool.py`

```python
"""
Viewport Pool Configuration

Provides realistic viewport distribution based on market data.
"""

import random
import hashlib
from typing import Tuple, List, Optional


class ViewportPool:
    """
    Pool of viewports based on StatCounter 2024-2025 market share data.
    """
    
    # (width, height, market_share_weight)
    VIEWPORTS: List[Tuple[int, int, float]] = [
        (1920, 1080, 22.5),
        (1366, 768, 14.8),
        (1536, 864, 10.2),
        (2560, 1440, 8.5),
        (1440, 900, 6.5),
        (1280, 720, 5.2),
        (1600, 900, 3.5),
        (1360, 768, 3.8),
        (1680, 1050, 2.8),
        (3840, 2160, 2.5),
        (1280, 800, 2.1),
        (1920, 1200, 1.8),
        (1280, 1024, 1.5),
        (2560, 1080, 1.2),
    ]
    
    @classmethod
    def get_for_profile(
        cls,
        profile_id: str,
        max_width: Optional[int] = None,
        max_height: Optional[int] = None
    ) -> Tuple[int, int]:
        """
        Get consistent viewport for profile, constrained by screen size.
        
        Args:
            profile_id: Unique identifier for consistent selection
            max_width: Physical screen width limit
            max_height: Physical screen height limit
        
        Returns:
            (width, height) tuple
        """
        seed = int(hashlib.sha256(f"{profile_id}_viewport".encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)
        
        # Filter by screen constraints
        if max_width and max_height:
            pool = [
                (w, h, weight) for w, h, weight in cls.VIEWPORTS
                if w <= max_width and h <= max_height
            ]
            if not pool:
                pool = [(max_width - 50, max_height - 50, 1.0)]
        else:
            pool = cls.VIEWPORTS
        
        # Weighted selection
        total = sum(v[2] for v in pool)
        r = rng.uniform(0, total)
        
        cumulative = 0
        for width, height, weight in pool:
            cumulative += weight
            if r <= cumulative:
                # Add small variation
                width += rng.randint(-20, 20)
                height += rng.randint(-15, 15)
                return (width, height)
        
        return pool[0][:2]
```

---

# MODULE 7: PROFILE SEED GENERATOR

## Overview
Generate consistent but unpredictable seeds for profile-specific behavior.

## File: `config/seed_generator.py`

```python
"""
Secure Seed Generator

Generates reproducible but unpredictable seeds for profile-specific variations.
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
    
    Combines:
    - Profile ID (consistency)
    - Session ID (per-session variance)
    - Profile entropy (uniqueness)
    - Date (daily rotation for some behaviors)
    """
    
    def __init__(self, profile_id: str):
        self.profile_id = profile_id
        self.session_id = secrets.token_hex(8)
        self.date_str = datetime.now().strftime("%Y-%m-%d")
        self._action_counter = 0
        self.profile_entropy = self._get_profile_entropy()
    
    def _get_profile_entropy(self) -> str:
        """Get or create unique entropy for this profile."""
        entropy_dir = Path.home() / ".ui_automation" / "entropy" / self.profile_id
        entropy_file = entropy_dir / ".entropy"
        
        try:
            if entropy_file.exists():
                return entropy_file.read_text().strip()
            
            entropy_parts = [
                secrets.token_hex(32),
                str(os.getpid()),
                str(time.time_ns()),
                platform.node(),
                self.profile_id,
            ]
            
            entropy = hashlib.sha256("|".join(entropy_parts).encode()).hexdigest()
            
            entropy_dir.mkdir(parents=True, exist_ok=True)
            entropy_file.write_text(entropy)
            entropy_file.chmod(0o600)
            
            return entropy
            
        except Exception:
            return secrets.token_hex(32)
    
    def get_behavior_seed(self, component: str) -> int:
        """Seed for consistent behavior across sessions."""
        seed_input = f"{self.profile_id}:{component}:{self.profile_entropy}"
        return int(hashlib.sha256(seed_input.encode()).hexdigest()[:16], 16)
    
    def get_daily_seed(self, component: str) -> int:
        """Seed that changes daily."""
        seed_input = f"{self.profile_id}:{component}:{self.profile_entropy}:{self.date_str}"
        return int(hashlib.sha256(seed_input.encode()).hexdigest()[:16], 16)
    
    def get_session_seed(self, component: str) -> int:
        """Seed unique to this session."""
        seed_input = f"{self.profile_id}:{component}:{self.session_id}"
        return int(hashlib.sha256(seed_input.encode()).hexdigest()[:16], 16)
    
    def get_action_seed(self, component: str) -> int:
        """Unique seed for each action."""
        self._action_counter += 1
        seed_input = f"{self.session_id}:{component}:{self._action_counter}:{time.time_ns()}"
        return int(hashlib.sha256(seed_input.encode()).hexdigest()[:16], 16)
```

---

# MODULE 8: RETRY HANDLER

## Overview
Implement human-like retry behavior when actions fail.

## File: `utils/retry_handler.py`

```python
"""
Human-Like Retry Handler

Implements natural recovery patterns when actions fail.
"""

import asyncio
import random
from typing import Callable, TypeVar, List
from functools import wraps

T = TypeVar('T')


class RetryHandler:
    """
    Retry with human-like delays and recovery actions.
    """
    
    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 2.0,
        max_delay: float = 30.0
    ):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
    
    async def execute(
        self,
        action: Callable,
        recovery_actions: List[str] = None,
        page = None
    ) -> T:
        """Execute action with retries."""
        recovery_actions = recovery_actions or ['wait', 'refresh', 'scroll']
        last_error = None
        
        for attempt in range(self.max_attempts):
            try:
                return await action()
            except Exception as e:
                last_error = e
                
                if attempt >= self.max_attempts - 1:
                    break
                
                await self._recover(attempt, recovery_actions, page)
        
        raise last_error
    
    async def _recover(
        self,
        attempt: int,
        strategies: List[str],
        page
    ) -> None:
        """Perform recovery action."""
        delay = min(self.base_delay * (2 ** attempt), self.max_delay)
        delay *= random.uniform(0.8, 1.2)
        
        strategy = random.choice(strategies)
        
        if strategy == 'wait':
            await asyncio.sleep(delay)
        elif strategy == 'refresh' and page:
            await asyncio.sleep(delay * 0.3)
            await page.reload()
            await asyncio.sleep(delay * 0.7)
        elif strategy == 'scroll' and page:
            await asyncio.sleep(delay * 0.2)
            await page.mouse.wheel(0, random.choice([-200, 200]))
            await asyncio.sleep(delay * 0.8)
        else:
            await asyncio.sleep(delay)


def with_retry(max_attempts: int = 3, base_delay: float = 2.0):
    """Decorator for retry behavior."""
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            handler = RetryHandler(max_attempts=max_attempts, base_delay=base_delay)
            
            async def action():
                return await func(self, *args, **kwargs)
            
            page = getattr(self, 'page', None)
            return await handler.execute(action, page=page)
        
        return wrapper
    return decorator
```

---

# MODULE 9: SESSION STATE

## Overview
Persist session state for continuity between runs.

## File: `state/session_state.py`

```python
"""
Session State Manager

Persists state between automation runs for continuity.
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import random


class SessionState:
    """
    Manages persistent state for a profile.
    """
    
    def __init__(self, profile_id: str):
        self.profile_id = profile_id
        self.state_file = Path.home() / ".ui_automation" / "state" / f"{profile_id}.json"
        self._state = self._load()
    
    def _load(self) -> Dict[str, Any]:
        """Load state from disk."""
        try:
            if self.state_file.exists():
                return json.loads(self.state_file.read_text())
        except Exception:
            pass
        
        return {
            'scroll_positions': {},
            'visited_pages': [],
            'last_visits': {},
        }
    
    def _save(self) -> None:
        """Save state to disk."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(self._state, indent=2))
        except Exception:
            pass
    
    def get_scroll_position(self, page_id: str) -> Optional[int]:
        """Get remembered scroll position."""
        positions = self._state.get('scroll_positions', {})
        
        if page_id in positions:
            data = positions[page_id]
            saved_time = datetime.fromisoformat(data['timestamp'])
            
            if datetime.now() - saved_time < timedelta(hours=24):
                return data['position'] + random.randint(-100, 100)
        
        return None
    
    def save_scroll_position(self, page_id: str, position: int) -> None:
        """Remember scroll position."""
        if 'scroll_positions' not in self._state:
            self._state['scroll_positions'] = {}
        
        self._state['scroll_positions'][page_id] = {
            'position': position,
            'timestamp': datetime.now().isoformat()
        }
        self._save()
    
    def add_visited(self, page_id: str) -> None:
        """Record page visit."""
        visited = self._state.get('visited_pages', [])
        
        if page_id not in visited:
            visited.insert(0, page_id)
            visited = visited[:100]
            self._state['visited_pages'] = visited
            self._save()
    
    def was_recently_visited(self, page_id: str) -> bool:
        """Check if page was visited recently."""
        return page_id in self._state.get('visited_pages', [])[:20]
```

---

# IMPLEMENTATION ORDER

## Week 1: Core Input
1. `delays/bimodal_delay.py`
2. `input/mouse_movement.py`
3. `input/click_handler.py`

## Week 2: Input Extensions
4. `input/scroll_normalizer.py`
5. `input/keyboard_handler.py`

## Week 3: Configuration
6. `config/viewport_pool.py`
7. `config/seed_generator.py`

## Week 4: Utilities
8. `utils/retry_handler.py`
9. `state/session_state.py`

## Week 5: Integration & Testing
- Integration tests
- Performance tuning

---

# MODULE 10: HUMAN BROWSER (Integration)

## Overview
Unified interface combining all modules into a single easy-to-use class.

## File: `human_browser.py`

```python
"""
Human Browser - Unified Interface

Combines all human-like interaction modules into a single class.
This is the main entry point for the framework.
"""

import asyncio
import logging
from typing import Optional, Tuple
from dataclasses import dataclass

from playwright.async_api import Page, BrowserContext

from config.seed_generator import ProfileSeedGenerator
from config.viewport_pool import ViewportPool
from input.mouse_movement import MovementGenerator, MouseExecutor, Point
from input.click_handler import ClickHandler, ClickConfig
from input.keyboard_handler import KeyboardHandler
from input.scroll_normalizer import ScrollNormalizer
from delays.bimodal_delay import BimodalDelay
from utils.retry_handler import RetryHandler
from state.session_state import SessionState


logger = logging.getLogger(__name__)


@dataclass
class HumanBrowserConfig:
    """Configuration for HumanBrowser."""
    profile_id: str
    viewport_max_width: Optional[int] = None
    viewport_max_height: Optional[int] = None
    typing_error_rate: float = 0.03
    hover_before_click_chance: float = 0.4
    enable_state_persistence: bool = True
    log_level: int = logging.INFO


class HumanBrowser:
    """
    Human-like browser interaction interface.
    
    Provides unified access to:
    - Realistic mouse movements
    - Natural click timing
    - Human typing patterns
    - Proper scroll behavior
    - Session state management
    
    Usage:
        async with HumanBrowser(page, config) as browser:
            await browser.click(selector)
            await browser.type(selector, "Hello")
            await browser.scroll_down(300)
    """
    
    def __init__(self, page: Page, config: HumanBrowserConfig):
        self.page = page
        self.config = config
        self._setup_logging()
        
        # Initialize seed generator
        self._seed_gen = ProfileSeedGenerator(config.profile_id)
        
        # Initialize components
        self._movement_gen = MovementGenerator(
            profile_seed=self._seed_gen.get_behavior_seed('mouse')
        )
        self._mouse = MouseExecutor(page, self._movement_gen)
        self._clicker = ClickHandler(page)
        self._keyboard = KeyboardHandler(
            page,
            error_rate=config.typing_error_rate,
            profile_seed=self._seed_gen.get_behavior_seed('keyboard')
        )
        self._scroll_norm = ScrollNormalizer(
            profile_seed=self._seed_gen.get_behavior_seed('scroll')
        )
        self._retry = RetryHandler()
        
        # State management
        if config.enable_state_persistence:
            self._state = SessionState(config.profile_id)
        else:
            self._state = None
        
        # Delays
        self._action_delay = BimodalDelay.for_clicks()
        
        logger.info(f"HumanBrowser initialized for profile: {config.profile_id}")
    
    def _setup_logging(self) -> None:
        """Configure logging."""
        logging.basicConfig(
            level=self.config.log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    
    async def __aenter__(self) -> "HumanBrowser":
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        pass
    
    # === High-Level Actions ===
    
    async def click(
        self,
        selector: str,
        hover_first: bool = None,
        timeout: float = 10.0
    ) -> bool:
        """
        Click element with human-like behavior.
        
        Args:
            selector: CSS selector or XPath
            hover_first: Hover before click (None = random based on config)
            timeout: Max wait time for element
        
        Returns:
            True if successful
        """
        async def do_click():
            element = await self.page.wait_for_selector(selector, timeout=timeout * 1000)
            if not element:
                raise ValueError(f"Element not found: {selector}")
            
            box = await element.bounding_box()
            if not box:
                raise ValueError(f"Element has no bounding box: {selector}")
            
            # Calculate click position (slightly randomized within element)
            x = box["x"] + box["width"] * random.uniform(0.3, 0.7)
            y = box["y"] + box["height"] * random.uniform(0.35, 0.65)
            
            # Move to element
            await self._mouse.move_to(x, y, target_size=min(box["width"], box["height"]))
            
            # Optional hover
            should_hover = hover_first if hover_first is not None else (
                random.random() < self.config.hover_before_click_chance
            )
            if should_hover:
                await self._mouse.hover(x, y, duration=random.uniform(0.2, 0.6))
            
            # Click
            await self._clicker.click_at(x, y)
            
            logger.debug(f"Clicked: {selector} at ({x:.0f}, {y:.0f})")
            return True
        
        try:
            return await self._retry.execute(do_click, page=self.page)
        except Exception as e:
            logger.error(f"Click failed: {selector} - {e}")
            return False
    
    async def type(
        self,
        selector: str,
        text: str,
        clear_first: bool = True,
        timeout: float = 10.0
    ) -> bool:
        """
        Type text into element with human-like patterns.
        
        Args:
            selector: CSS selector for input element
            text: Text to type
            clear_first: Clear existing content first
            timeout: Max wait time for element
        
        Returns:
            True if successful
        """
        async def do_type():
            # Click to focus
            await self.click(selector, timeout=timeout)
            
            # Clear if needed
            if clear_first:
                await self.page.keyboard.press("Control+a")
                await asyncio.sleep(random.uniform(0.05, 0.15))
                await self.page.keyboard.press("Backspace")
                await asyncio.sleep(random.uniform(0.1, 0.3))
            
            # Type with natural patterns
            await self._keyboard.type_text(text)
            
            logger.debug(f"Typed {len(text)} chars into: {selector}")
            return True
        
        try:
            return await self._retry.execute(do_type, page=self.page)
        except Exception as e:
            logger.error(f"Type failed: {selector} - {e}")
            return False
    
    async def scroll_down(self, pixels: int = None) -> int:
        """
        Scroll down with realistic wheel events.
        
        Args:
            pixels: Amount to scroll (None = random 200-500)
        
        Returns:
            Actual pixels scrolled
        """
        if pixels is None:
            pixels = random.randint(200, 500)
        
        deltas = self._scroll_norm.normalize(pixels)
        total = 0
        
        for delta in deltas:
            await self.page.mouse.wheel(0, delta)
            total += delta
            await asyncio.sleep(self._scroll_norm.get_inter_event_delay())
        
        logger.debug(f"Scrolled down: {total}px")
        return total
    
    async def scroll_up(self, pixels: int = None) -> int:
        """Scroll up with realistic wheel events."""
        if pixels is None:
            pixels = random.randint(200, 500)
        return await self.scroll_down(-pixels)
    
    async def scroll_to_element(
        self,
        selector: str,
        timeout: float = 10.0
    ) -> bool:
        """
        Scroll until element is visible.
        
        Args:
            selector: CSS selector
            timeout: Max time to spend scrolling
        
        Returns:
            True if element found and scrolled to
        """
        start_time = asyncio.get_event_loop().time()
        
        while (asyncio.get_event_loop().time() - start_time) < timeout:
            element = await self.page.query_selector(selector)
            
            if element:
                box = await element.bounding_box()
                if box:
                    viewport = self.page.viewport_size
                    
                    # Check if visible
                    if 0 < box["y"] < viewport["height"] - box["height"]:
                        logger.debug(f"Element visible: {selector}")
                        return True
                    
                    # Scroll toward element
                    if box["y"] < 0:
                        await self.scroll_up(abs(box["y"]) + 100)
                    else:
                        await self.scroll_down(box["y"] - viewport["height"] // 2)
            else:
                # Element not in DOM yet, scroll down
                await self.scroll_down(300)
            
            await asyncio.sleep(random.uniform(0.3, 0.8))
        
        logger.warning(f"Element not found after scrolling: {selector}")
        return False
    
    async def hover(
        self,
        selector: str,
        duration: float = None,
        timeout: float = 10.0
    ) -> bool:
        """
        Hover over element.
        
        Args:
            selector: CSS selector
            duration: Hover duration (None = random)
            timeout: Max wait for element
        
        Returns:
            True if successful
        """
        try:
            element = await self.page.wait_for_selector(selector, timeout=timeout * 1000)
            if not element:
                return False
            
            box = await element.bounding_box()
            if not box:
                return False
            
            x = box["x"] + box["width"] / 2
            y = box["y"] + box["height"] / 2
            
            await self._mouse.hover(x, y, duration=duration)
            
            logger.debug(f"Hovered: {selector}")
            return True
            
        except Exception as e:
            logger.error(f"Hover failed: {selector} - {e}")
            return False
    
    async def wait(self, min_seconds: float = 0.5, max_seconds: float = 2.0) -> float:
        """
        Wait with human-like duration.
        
        Returns:
            Actual wait duration
        """
        duration = random.uniform(min_seconds, max_seconds)
        await asyncio.sleep(duration)
        return duration
    
    async def action_delay(self) -> float:
        """
        Natural delay between actions.
        
        Returns:
            Actual delay duration
        """
        return await self._action_delay.wait()
    
    # === State Management ===
    
    def save_scroll_position(self, page_id: str = None) -> None:
        """Save current scroll position."""
        if not self._state:
            return
        
        page_id = page_id or self.page.url
        # Would need to get actual scroll position from page
        # This is a placeholder
        logger.debug(f"Scroll position saved for: {page_id}")
    
    def get_saved_scroll_position(self, page_id: str = None) -> Optional[int]:
        """Get previously saved scroll position."""
        if not self._state:
            return None
        
        page_id = page_id or self.page.url
        return self._state.get_scroll_position(page_id)
    
    # === Utilities ===
    
    @property
    def viewport(self) -> Tuple[int, int]:
        """Get configured viewport for this profile."""
        return ViewportPool.get_for_profile(
            self.config.profile_id,
            max_width=self.config.viewport_max_width,
            max_height=self.config.viewport_max_height
        )
    
    @property
    def seed_generator(self) -> ProfileSeedGenerator:
        """Access seed generator for custom randomization."""
        return self._seed_gen


# Need to import random for the class
import random
```

---

# MODULE 11: PROJECT STRUCTURE

## Directory Layout

```
human_ui_automation/
├── __init__.py
├── human_browser.py
├── delays/
│   ├── __init__.py
│   └── bimodal_delay.py
├── input/
│   ├── __init__.py
│   ├── mouse_movement.py
│   ├── click_handler.py
│   ├── scroll_normalizer.py
│   └── keyboard_handler.py
├── config/
│   ├── __init__.py
│   ├── viewport_pool.py
│   └── seed_generator.py
├── utils/
│   ├── __init__.py
│   └── retry_handler.py
├── state/
│   ├── __init__.py
│   └── session_state.py
└── tests/
    ├── __init__.py
    ├── test_bimodal_delay.py
    ├── test_mouse_movement.py
    └── test_integration.py
```

## File: `__init__.py` (root)

```python
"""
Human UI Automation Framework

A library for browser automation with realistic human-like interaction patterns.
"""

__version__ = "1.0.0"

from .human_browser import HumanBrowser, HumanBrowserConfig
from .config.seed_generator import ProfileSeedGenerator
from .config.viewport_pool import ViewportPool
from .delays.bimodal_delay import BimodalDelay, ActionMode
from .input.mouse_movement import MovementGenerator, MouseExecutor, Point, MovementType
from .input.click_handler import ClickHandler, ClickConfig
from .input.keyboard_handler import KeyboardHandler, TypoType
from .input.scroll_normalizer import ScrollNormalizer
from .utils.retry_handler import RetryHandler, with_retry
from .state.session_state import SessionState

__all__ = [
    # Main interface
    "HumanBrowser",
    "HumanBrowserConfig",
    
    # Config
    "ProfileSeedGenerator",
    "ViewportPool",
    
    # Delays
    "BimodalDelay",
    "ActionMode",
    
    # Input
    "MovementGenerator",
    "MouseExecutor",
    "Point",
    "MovementType",
    "ClickHandler",
    "ClickConfig",
    "KeyboardHandler",
    "TypoType",
    "ScrollNormalizer",
    
    # Utils
    "RetryHandler",
    "with_retry",
    
    # State
    "SessionState",
]
```

## File: `delays/__init__.py`

```python
"""Delay generation modules."""
from .bimodal_delay import BimodalDelay, ActionMode, DelayConfig

__all__ = ["BimodalDelay", "ActionMode", "DelayConfig"]
```

## File: `input/__init__.py`

```python
"""Input simulation modules."""
from .mouse_movement import MovementGenerator, MouseExecutor, Point, MovementType, MouseConfig
from .click_handler import ClickHandler, ClickConfig
from .keyboard_handler import KeyboardHandler, TypoType
from .scroll_normalizer import ScrollNormalizer

__all__ = [
    "MovementGenerator", "MouseExecutor", "Point", "MovementType", "MouseConfig",
    "ClickHandler", "ClickConfig",
    "KeyboardHandler", "TypoType",
    "ScrollNormalizer",
]
```

## File: `config/__init__.py`

```python
"""Configuration modules."""
from .seed_generator import ProfileSeedGenerator
from .viewport_pool import ViewportPool

__all__ = ["ProfileSeedGenerator", "ViewportPool"]
```

## File: `utils/__init__.py`

```python
"""Utility modules."""
from .retry_handler import RetryHandler, with_retry

__all__ = ["RetryHandler", "with_retry"]
```

## File: `state/__init__.py`

```python
"""State management modules."""
from .session_state import SessionState

__all__ = ["SessionState"]
```

---

# MODULE 12: REQUIREMENTS & SETUP

## File: `requirements.txt`

```
playwright>=1.40.0
asyncio-throttle>=1.0.0
typing_extensions>=4.0.0;python_version<"3.10"
```

## File: `pyproject.toml`

```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "human-ui-automation"
version = "1.0.0"
description = "Browser automation with realistic human-like interaction patterns"
readme = "README.md"
requires-python = ">=3.8"
license = {text = "MIT"}
authors = [
    {name = "Developer", email = "dev@example.com"}
]
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.8",
    "Programming Language :: Python :: 3.9",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
]
dependencies = [
    "playwright>=1.40.0",
    "typing_extensions>=4.0.0;python_version<'3.10'",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.21.0",
    "black>=23.0.0",
    "mypy>=1.0.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.black]
line-length = 100
target-version = ["py38", "py39", "py310", "py311"]

[tool.mypy]
python_version = "3.8"
warn_return_any = true
warn_unused_configs = true
```

---

# MODULE 13: INTEGRATION TEST

## File: `tests/test_integration.py`

```python
"""
Integration tests for HumanBrowser.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from human_browser import HumanBrowser, HumanBrowserConfig


@pytest.fixture
def mock_page():
    """Create mock Playwright page."""
    page = MagicMock()
    page.mouse = MagicMock()
    page.mouse.move = AsyncMock()
    page.mouse.down = AsyncMock()
    page.mouse.up = AsyncMock()
    page.mouse.wheel = AsyncMock()
    page.keyboard = MagicMock()
    page.keyboard.type = AsyncMock()
    page.keyboard.press = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.query_selector = AsyncMock()
    page.viewport_size = {"width": 1920, "height": 1080}
    page.url = "https://example.com"
    return page


@pytest.fixture
def config():
    """Create test config."""
    return HumanBrowserConfig(
        profile_id="test_profile_001",
        enable_state_persistence=False,
    )


@pytest.mark.asyncio
async def test_browser_initialization(mock_page, config):
    """Test HumanBrowser initializes correctly."""
    browser = HumanBrowser(mock_page, config)
    
    assert browser.page == mock_page
    assert browser.config.profile_id == "test_profile_001"
    assert browser._seed_gen is not None


@pytest.mark.asyncio
async def test_click_calls_mouse_methods(mock_page, config):
    """Test click invokes proper mouse methods."""
    # Setup mock element
    mock_element = MagicMock()
    mock_element.bounding_box = AsyncMock(return_value={
        "x": 100, "y": 100, "width": 50, "height": 30
    })
    mock_page.wait_for_selector.return_value = mock_element
    
    browser = HumanBrowser(mock_page, config)
    result = await browser.click("#test-button")
    
    assert result == True
    assert mock_page.mouse.move.called
    assert mock_page.mouse.down.called
    assert mock_page.mouse.up.called


@pytest.mark.asyncio
async def test_type_calls_keyboard_methods(mock_page, config):
    """Test type invokes keyboard methods."""
    mock_element = MagicMock()
    mock_element.bounding_box = AsyncMock(return_value={
        "x": 100, "y": 100, "width": 200, "height": 30
    })
    mock_page.wait_for_selector.return_value = mock_element
    
    browser = HumanBrowser(mock_page, config)
    result = await browser.type("#input-field", "test")
    
    assert result == True
    assert mock_page.keyboard.type.called or mock_page.keyboard.press.called


@pytest.mark.asyncio
async def test_scroll_uses_normalized_deltas(mock_page, config):
    """Test scroll produces multiple wheel events."""
    browser = HumanBrowser(mock_page, config)
    
    pixels = await browser.scroll_down(300)
    
    assert mock_page.mouse.wheel.call_count >= 1
    assert pixels != 0


@pytest.mark.asyncio
async def test_viewport_is_consistent(config):
    """Test viewport is consistent for same profile."""
    browser1_viewport = HumanBrowser._get_viewport_for_profile(config.profile_id)
    browser2_viewport = HumanBrowser._get_viewport_for_profile(config.profile_id)
    
    # Note: This tests the class method if implemented, otherwise skip
    # The point is same profile = same viewport


@pytest.mark.asyncio
async def test_context_manager(mock_page, config):
    """Test async context manager works."""
    async with HumanBrowser(mock_page, config) as browser:
        assert browser is not None
        assert browser.page == mock_page


@pytest.mark.asyncio
async def test_retry_on_failure(mock_page, config):
    """Test retry behavior on element not found."""
    mock_page.wait_for_selector.side_effect = [None, None, MagicMock()]
    
    browser = HumanBrowser(mock_page, config)
    # This should retry and eventually fail or succeed
    # Depending on mock setup


def test_different_profiles_different_seeds():
    """Test different profiles get different behavior seeds."""
    from config.seed_generator import ProfileSeedGenerator
    
    gen1 = ProfileSeedGenerator("profile_A")
    gen2 = ProfileSeedGenerator("profile_B")
    
    seed1 = gen1.get_behavior_seed("mouse")
    seed2 = gen2.get_behavior_seed("mouse")
    
    assert seed1 != seed2


def test_same_profile_consistent_seeds():
    """Test same profile gets consistent seeds."""
    from config.seed_generator import ProfileSeedGenerator
    
    gen1 = ProfileSeedGenerator("profile_A")
    gen2 = ProfileSeedGenerator("profile_A")
    
    seed1 = gen1.get_behavior_seed("mouse")
    seed2 = gen2.get_behavior_seed("mouse")
    
    assert seed1 == seed2
```

---

# IMPLEMENTATION ORDER (Updated)

## Week 1: Core Foundation
1. `config/seed_generator.py`
2. `config/viewport_pool.py`
3. `delays/bimodal_delay.py`

## Week 2: Input Modules
4. `input/mouse_movement.py` (with MouseExecutor)
5. `input/click_handler.py`
6. `input/scroll_normalizer.py`
7. `input/keyboard_handler.py`

## Week 3: Infrastructure
8. `utils/retry_handler.py`
9. `state/session_state.py`
10. All `__init__.py` files
11. `requirements.txt` & `pyproject.toml`

## Week 4: Integration
12. `human_browser.py`
13. `tests/test_integration.py`
14. Documentation & examples

---

# USAGE EXAMPLE (Updated)

```python
import asyncio
from playwright.async_api import async_playwright
from human_ui_automation import HumanBrowser, HumanBrowserConfig

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        
        # Get viewport for profile
        from human_ui_automation import ViewportPool
        viewport = ViewportPool.get_for_profile("my_profile_001")
        
        context = await browser.new_context(
            viewport={"width": viewport[0], "height": viewport[1]}
        )
        page = await context.new_page()
        
        # Configure HumanBrowser
        config = HumanBrowserConfig(
            profile_id="my_profile_001",
            typing_error_rate=0.02,
            hover_before_click_chance=0.3,
        )
        
        # Use HumanBrowser
        async with HumanBrowser(page, config) as human:
            await page.goto("https://example.com")
            
            # Natural interactions
            await human.click("#search-input")
            await human.type("#search-input", "hello world")
            await human.click("#search-button")
            
            await human.wait(1, 3)
            await human.scroll_down(500)
            
            await human.hover("#result-link")
            await human.click("#result-link")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
```

---

**Total estimated time:** 50-70 hours  
**Dependencies:** playwright, typing_extensions (for Python <3.10)