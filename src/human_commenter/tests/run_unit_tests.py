"""
Standalone Unit Tests for Biometrics Module

Tests mathematical correctness without requiring any external imports.
Run with: python run_unit_tests.py
"""

import math
import random
import statistics


# ============================================================================
# Copy of classes/functions for standalone testing
# ============================================================================

class GaussianDelay:
    """Copy of GaussianDelay for testing"""
    def __init__(self, mean: float, std_dev: float, min_bound: float, max_bound: float):
        self.mean = mean
        self.std_dev = std_dev
        self.min_bound = min_bound
        self.max_bound = max_bound

    def sample(self) -> float:
        delay = random.gauss(self.mean, self.std_dev)
        return max(self.min_bound, min(self.max_bound, delay))


class Point:
    """2D point with x, y coordinates"""
    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y

    def distance_to(self, other: "Point") -> float:
        return math.sqrt((self.x - other.x) ** 2 + (self.y - other.y) ** 2)

    def __add__(self, other: "Point") -> "Point":
        return Point(self.x + other.x, self.y + other.y)

    def __sub__(self, other: "Point") -> "Point":
        return Point(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar: float) -> "Point":
        return Point(self.x * scalar, self.y * scalar)


# QWERTY keyboard adjacency map
QWERTY_ADJACENT = {
    'q': ['w', 'a', '1', '2'], 'w': ['q', 'e', 'a', 's', '2', '3'],
    'e': ['w', 'r', 's', 'd', '3', '4'], 'r': ['e', 't', 'd', 'f', '4', '5'],
    't': ['r', 'y', 'f', 'g', '5', '6'], 'y': ['t', 'u', 'g', 'h', '6', '7'],
    'u': ['y', 'i', 'h', 'j', '7', '8'], 'i': ['u', 'o', 'j', 'k', '8', '9'],
    'o': ['i', 'p', 'k', 'l', '9', '0'], 'p': ['o', 'l', '0', '-', '['],
    'a': ['q', 'w', 's', 'z'], 's': ['w', 'e', 'a', 'd', 'z', 'x'],
    'd': ['e', 'r', 's', 'f', 'x', 'c'], 'f': ['r', 't', 'd', 'g', 'c', 'v'],
    'g': ['t', 'y', 'f', 'h', 'v', 'b'], 'h': ['y', 'u', 'g', 'j', 'b', 'n'],
    'j': ['u', 'i', 'h', 'k', 'n', 'm'], 'k': ['i', 'o', 'j', 'l', 'm', ','],
    'l': ['o', 'p', 'k', ',', '.', ';'],
    'z': ['a', 's', 'x'], 'x': ['s', 'd', 'z', 'c'],
    'c': ['d', 'f', 'x', 'v'], 'v': ['f', 'g', 'c', 'b'],
    'b': ['g', 'h', 'v', 'n'], 'n': ['h', 'j', 'b', 'm'],
    'm': ['j', 'k', 'n', ','],
    '1': ['2', 'q'], '2': ['1', '3', 'q', 'w'], '3': ['2', '4', 'w', 'e'],
    '4': ['3', '5', 'e', 'r'], '5': ['4', '6', 'r', 't'], '6': ['5', '7', 't', 'y'],
    '7': ['6', '8', 'y', 'u'], '8': ['7', '9', 'u', 'i'], '9': ['8', '0', 'i', 'o'],
    '0': ['9', '-', 'o', 'p'],
}


# ============================================================================
# Test Functions
# ============================================================================

def test_gaussian_within_bounds():
    """All samples should be within min/max bounds"""
    print("Testing: Gaussian samples within bounds...", end=" ")

    delay = GaussianDelay(mean=1.0, std_dev=0.5, min_bound=0.5, max_bound=2.0)
    samples = [delay.sample() for _ in range(1000)]

    assert all(0.5 <= s <= 2.0 for s in samples), "FAIL: Sample outside bounds!"
    print("[PASS]")


def test_gaussian_mean():
    """Mean of samples should be close to configured mean"""
    print("Testing: Gaussian mean accuracy...", end=" ")

    delay = GaussianDelay(mean=1.0, std_dev=0.2, min_bound=0.0, max_bound=3.0)
    samples = [delay.sample() for _ in range(10000)]
    actual_mean = statistics.mean(samples)

    assert abs(actual_mean - 1.0) < 0.05, f"FAIL: Mean {actual_mean} too far from 1.0"
    print(f"[PASS] (mean={actual_mean:.3f})")


def test_gaussian_spread():
    """Samples should have reasonable spread"""
    print("Testing: Gaussian distribution spread...", end=" ")

    delay = GaussianDelay(mean=1.0, std_dev=0.3, min_bound=0.0, max_bound=3.0)
    samples = [delay.sample() for _ in range(100)]
    std_dev = statistics.stdev(samples)

    assert std_dev > 0.1, f"FAIL: Std dev {std_dev} too low"
    print(f"[PASS] (std_dev={std_dev:.3f})")


def test_fitts_law_larger_target():
    """Larger targets should have shorter movement time"""
    print("Testing: Fitts' Law - larger target faster...", end=" ")

    # Fitts' Law: MT = a + b * log2(2D/W)
    a, b = 0.1, 0.1
    distance = 500

    small_target = 10
    large_target = 100

    mt_small = a + b * math.log2(2 * distance / small_target)
    mt_large = a + b * math.log2(2 * distance / large_target)

    assert mt_large < mt_small, "FAIL: Larger target should be faster"
    print(f"[PASS] (small={mt_small:.3f}s, large={mt_large:.3f}s)")


def test_fitts_law_closer_target():
    """Closer targets should have shorter movement time"""
    print("Testing: Fitts' Law - closer target faster...", end=" ")

    a, b = 0.1, 0.1
    target_width = 50

    close_distance = 100
    far_distance = 500

    mt_close = a + b * math.log2(2 * close_distance / target_width)
    mt_far = a + b * math.log2(2 * far_distance / target_width)

    assert mt_close < mt_far, "FAIL: Closer target should be faster"
    print(f"[PASS] (close={mt_close:.3f}s, far={mt_far:.3f}s)")


def test_keyboard_adjacency_exists():
    """All common keys should have adjacent keys defined"""
    print("Testing: Keyboard adjacency map completeness...", end=" ")

    common_keys = "qwertyuiopasdfghjklzxcvbnm1234567890"
    missing = []

    for key in common_keys:
        if key not in QWERTY_ADJACENT:
            missing.append(key)

    assert len(missing) == 0, f"FAIL: Keys missing: {missing}"
    print(f"[PASS] ({len(QWERTY_ADJACENT)} keys mapped)")


def test_keyboard_adjacency_reasonable():
    """Adjacent keys should actually be physically adjacent"""
    print("Testing: Keyboard adjacency is reasonable...", end=" ")

    # Test known adjacencies
    assert 'w' in QWERTY_ADJACENT['q'], "FAIL: Q should be next to W"
    assert 's' in QWERTY_ADJACENT['a'], "FAIL: A should be next to S"
    assert 'n' in QWERTY_ADJACENT['b'], "FAIL: B should be next to N"

    # Test non-adjacent
    assert 'p' not in QWERTY_ADJACENT['a'], "FAIL: A and P are not adjacent"
    assert 'z' not in QWERTY_ADJACENT['o'], "FAIL: O and Z are not adjacent"

    print("[PASS]")


def test_bezier_speed_profile():
    """Speed profile should have bell shape (peak in middle)"""
    print("Testing: Bezier speed profile shape...", end=" ")

    # Speed profile: 0.3 + 0.7 * sin(π * t)
    num_points = 50
    profile = []

    for i in range(num_points):
        t = i / (num_points - 1)
        speed = 0.3 + 0.7 * math.sin(math.pi * t)
        profile.append(speed)

    middle_idx = num_points // 2
    edge_speed = (profile[0] + profile[-1]) / 2
    middle_speed = profile[middle_idx]

    assert middle_speed > edge_speed, "FAIL: Middle should be faster than edges"
    print(f"[PASS] (edge={edge_speed:.2f}, middle={middle_speed:.2f})")


def test_point_distance():
    """Point distance calculation should be correct"""
    print("Testing: Point distance calculation...", end=" ")

    p1 = Point(0, 0)
    p2 = Point(3, 4)

    # 3-4-5 triangle
    assert p1.distance_to(p2) == 5.0, "FAIL: 3-4-5 triangle distance"
    print("[PASS]")


def test_point_operations():
    """Point arithmetic operations should work"""
    print("Testing: Point arithmetic operations...", end=" ")

    p1 = Point(1, 2)
    p2 = Point(3, 4)

    add = p1 + p2
    assert add.x == 4 and add.y == 6, "FAIL: Addition"

    sub = p2 - p1
    assert sub.x == 2 and sub.y == 2, "FAIL: Subtraction"

    mul = p1 * 3
    assert mul.x == 3 and mul.y == 6, "FAIL: Scalar multiplication"

    print("[PASS]")


def test_error_rate_distribution():
    """Error rate should match configured probability"""
    print("Testing: Typing error rate distribution...", end=" ")

    error_chance = 0.05  # 5%
    errors = sum(1 for _ in range(10000) if random.random() < error_chance)

    # Should be around 500 (5% of 10000), allow 20% deviation
    assert 400 < errors < 600, f"FAIL: Error count {errors} outside range"
    print(f"[PASS] ({errors} errors in 10000 = {errors/100:.1f}%)")


def test_bezier_path_generation():
    """Bezier curve should generate smooth path"""
    print("Testing: Bezier path smoothness...", end=" ")

    start = Point(0, 0)
    end = Point(100, 100)

    # Generate cubic Bezier with random control points
    ctrl1 = Point(25, 40)
    ctrl2 = Point(75, 60)

    num_points = 50
    path = []

    for i in range(num_points):
        t = i / (num_points - 1)
        t2 = t * t
        t3 = t2 * t
        mt = 1 - t
        mt2 = mt * mt
        mt3 = mt2 * mt

        # Cubic Bezier formula
        x = mt3 * start.x + 3 * mt2 * t * ctrl1.x + 3 * mt * t2 * ctrl2.x + t3 * end.x
        y = mt3 * start.y + 3 * mt2 * t * ctrl1.y + 3 * mt * t2 * ctrl2.y + t3 * end.y
        path.append(Point(x, y))

    # Check path starts and ends correctly
    assert abs(path[0].x - start.x) < 0.01, "FAIL: Path should start at start"
    assert abs(path[-1].x - end.x) < 0.01, "FAIL: Path should end at end"

    # Check no sharp angles (smooth curve)
    max_angle = 0
    for i in range(1, len(path) - 1):
        p1, p2, p3 = path[i-1], path[i], path[i+1]

        v1 = Point(p2.x - p1.x, p2.y - p1.y)
        v2 = Point(p3.x - p2.x, p3.y - p2.y)

        dot = v1.x * v2.x + v1.y * v2.y
        mag1 = math.sqrt(v1.x**2 + v1.y**2)
        mag2 = math.sqrt(v2.x**2 + v2.y**2)

        if mag1 > 0.01 and mag2 > 0.01:
            cos_angle = max(-1, min(1, dot / (mag1 * mag2)))
            angle = math.acos(cos_angle)
            max_angle = max(max_angle, angle)

    assert max_angle < math.pi / 2, f"FAIL: Sharp angle detected: {math.degrees(max_angle):.1f} deg"
    print(f"[PASS] (max angle={math.degrees(max_angle):.1f} deg)")


def test_bezier_path_variance():
    """Multiple Bezier paths should differ (randomness)"""
    print("Testing: Bezier path variance...", end=" ")

    start = Point(0, 0)
    end = Point(100, 0)

    # Generate multiple paths with random control points
    paths = []
    for _ in range(10):
        variance = 0.3
        distance = start.distance_to(end)

        ctrl1_perp = (random.random() - 0.5) * 2 * variance * distance
        ctrl2_perp = (random.random() - 0.5) * 2 * variance * distance

        ctrl1 = Point(25, ctrl1_perp)
        ctrl2 = Point(75, ctrl2_perp)

        # Sample middle point of path
        t = 0.5
        t2 = t * t
        t3 = t2 * t
        mt = 1 - t
        mt2 = mt * mt
        mt3 = mt2 * mt

        mid_y = mt3 * start.y + 3 * mt2 * t * ctrl1.y + 3 * mt * t2 * ctrl2.y + t3 * end.y
        paths.append(mid_y)

    # Check variance in middle y coordinates
    y_variance = statistics.variance(paths)
    assert y_variance > 10, f"FAIL: Paths too similar (variance={y_variance:.2f})"
    print(f"[PASS] (y_variance={y_variance:.1f})")


def test_tremor_frequency():
    """Tremor should produce points within amplitude range"""
    print("Testing: Tremor amplitude bounds...", end=" ")

    center_x, center_y = 500, 500
    amplitude = 2.0

    points = []
    for _ in range(100):
        # Simulate tremor offset
        tremor_x = random.gauss(0, amplitude)
        tremor_y = random.gauss(0, amplitude)

        # Clamp (as in actual implementation)
        tremor_x = max(-amplitude * 2, min(amplitude * 2, tremor_x))
        tremor_y = max(-amplitude * 2, min(amplitude * 2, tremor_y))

        points.append((center_x + tremor_x, center_y + tremor_y))

    # Check all points within bounds
    for x, y in points:
        assert abs(x - center_x) <= amplitude * 2, f"FAIL: X tremor out of bounds"
        assert abs(y - center_y) <= amplitude * 2, f"FAIL: Y tremor out of bounds"

    print("[PASS]")


# ============================================================================
# Main
# ============================================================================

def main():
    print("\n" + "="*60)
    print("HUMAN COMMENTER - BIOMETRICS UNIT TESTS")
    print("="*60)
    print("Testing mathematical correctness of human behavior simulation")
    print("="*60 + "\n")

    tests = [
        test_gaussian_within_bounds,
        test_gaussian_mean,
        test_gaussian_spread,
        test_fitts_law_larger_target,
        test_fitts_law_closer_target,
        test_keyboard_adjacency_exists,
        test_keyboard_adjacency_reasonable,
        test_bezier_speed_profile,
        test_point_distance,
        test_point_operations,
        test_error_rate_distribution,
        test_bezier_path_generation,
        test_bezier_path_variance,
        test_tremor_frequency,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"[FAIL] {e}")
            failed += 1
        except Exception as e:
            print(f"[FAIL] ERROR: {e}")
            failed += 1

    print("\n" + "="*60)
    if failed == 0:
        print(f"ALL TESTS PASSED: {passed}/{passed}")
    else:
        print(f"RESULTS: {passed} passed, {failed} failed")
    print("="*60 + "\n")

    return failed == 0


if __name__ == "__main__":
    import sys
    success = main()
    sys.exit(0 if success else 1)
