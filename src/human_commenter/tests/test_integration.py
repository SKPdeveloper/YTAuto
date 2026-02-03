"""
Integration Tests for Human Commenter Framework

Tests the complete integration of all modules:
- BimodalDelay
- HumanKeyboard (5 typo types)
- HumanScroll (ScrollNormalizer)
- ProfileSeedGenerator
- ViewportPool
- RetryHandler
- SessionState
- HumanBrowser
"""

import asyncio
import pytest
import random
from pathlib import Path
from unittest.mock import Mock, AsyncMock, MagicMock

# Import all Phase 1-3 modules
from src.human_commenter.biometrics import (
    BimodalDelay,
    BimodalConfig,
    ActionMode,
    HumanKeyboard,
    HumanScroll,
    ScrollNormalizer,
    TypoType,
)
from src.human_commenter.config import (
    CommenterConfig,
    ProfileSeedGenerator,
    ViewportPool,
)
from src.human_commenter.utils import (
    RetryHandler,
    RetryError,
    with_retry,
)
from src.human_commenter.state import SessionState
from src.human_commenter.core import HumanBrowser, HumanBrowserConfig


class TestBimodalDelay:
    """Tests for BimodalDelay."""

    def test_bimodal_distribution(self):
        """Test that delays follow bimodal distribution."""
        delay = BimodalDelay.for_typing()

        auto_count = 0
        delib_count = 0

        for _ in range(100):
            value, mode = delay.sample()
            if mode == ActionMode.AUTOMATIC:
                auto_count += 1
            else:
                delib_count += 1

        # Should be roughly 70/30 split (with some variance)
        assert 50 < auto_count < 90, f"Auto count {auto_count} outside expected range"
        assert 10 < delib_count < 50, f"Delib count {delib_count} outside expected range"

    def test_factory_methods(self):
        """Test factory methods create different configurations."""
        typing = BimodalDelay.for_typing()
        clicks = BimodalDelay.for_clicks()
        nav = BimodalDelay.for_navigation()

        # Typing should be fastest
        assert typing.config.fast_mean < clicks.config.fast_mean
        # Navigation should be slowest
        assert nav.config.fast_mean > clicks.config.fast_mean

    def test_bounds_enforcement(self):
        """Test that delays are clamped to bounds."""
        delay = BimodalDelay(BimodalConfig(
            fast_mean=0.1,
            fast_std=0.5,  # High std to test clamping
            slow_mean=0.5,
            slow_std=0.5,
            fast_probability=0.5,
            min_bound=0.05,
            max_bound=1.0
        ))

        for _ in range(50):
            value = delay.sample_value()
            assert 0.05 <= value <= 1.0


class TestTypoTypes:
    """Tests for keyboard typo types."""

    def test_all_typo_types_exist(self):
        """Test that all 5 typo types are defined."""
        types = list(TypoType)
        assert len(types) == 5
        assert TypoType.ADJACENT in types
        assert TypoType.SKIP in types
        assert TypoType.DOUBLE in types
        assert TypoType.SWAP in types
        assert TypoType.CASE in types

    def test_keyboard_typo_weights(self):
        """Test that keyboard initializes typo weights."""
        # Create mock page
        page = Mock()
        config = CommenterConfig()

        keyboard = HumanKeyboard(page, config, profile_seed=12345)

        weights = keyboard.get_typo_stats()
        assert 'adjacent' in weights
        assert 'skip' in weights
        assert 'double' in weights
        assert 'swap' in weights
        assert 'case' in weights

        # Adjacent should be most common
        assert weights['adjacent'] > weights['skip']

    def test_keyboard_profile_variation(self):
        """Test that different profiles get different typo weights."""
        page = Mock()
        config = CommenterConfig()

        kb1 = HumanKeyboard(page, config, profile_seed=11111)
        kb2 = HumanKeyboard(page, config, profile_seed=22222)

        weights1 = kb1.get_typo_stats()
        weights2 = kb2.get_typo_stats()

        # Weights should differ between profiles
        assert weights1 != weights2


class TestScrollNormalizer:
    """Tests for ScrollNormalizer."""

    def test_device_selection(self):
        """Test that device is selected based on seed."""
        # Same seed = same device
        norm1 = ScrollNormalizer(profile_seed=12345)
        norm2 = ScrollNormalizer(profile_seed=12345)
        assert norm1.device_type == norm2.device_type

        # Different seed = may be different device
        # (not guaranteed, but test multiple seeds)
        devices = set()
        for seed in range(100):
            norm = ScrollNormalizer(profile_seed=seed)
            devices.add(norm.device_type)

        # Should have selected multiple device types
        assert len(devices) > 1

    def test_normalize_produces_valid_deltas(self):
        """Test that normalized deltas are realistic."""
        norm = ScrollNormalizer(profile_seed=12345)
        deltas = norm.normalize(300)

        # Should produce multiple events
        assert len(deltas) > 0

        # Sum should be approximately target
        total = sum(deltas)
        assert abs(total - 300) < 50  # Allow some variance

    def test_device_specific_deltas(self):
        """Test that different devices produce different patterns."""
        # Force specific devices by checking device profiles
        windows_norm = ScrollNormalizer.__new__(ScrollNormalizer)
        windows_norm.device_type = 'windows_mouse'
        windows_norm.device = ScrollNormalizer.DEVICES['windows_mouse']

        touchpad_norm = ScrollNormalizer.__new__(ScrollNormalizer)
        touchpad_norm.device_type = 'touchpad'
        touchpad_norm.device = ScrollNormalizer.DEVICES['touchpad']

        win_deltas = windows_norm.normalize(300)
        touch_deltas = touchpad_norm.normalize(300)

        # Touchpad should have more, smaller events
        assert len(touch_deltas) > len(win_deltas)


class TestProfileSeedGenerator:
    """Tests for ProfileSeedGenerator."""

    def test_behavior_seed_consistency(self):
        """Test that behavior seed is consistent across instances."""
        gen1 = ProfileSeedGenerator("test_profile")
        gen2 = ProfileSeedGenerator("test_profile")

        # Same profile should get same behavior seeds
        assert gen1.get_behavior_seed("mouse") == gen2.get_behavior_seed("mouse")
        assert gen1.get_behavior_seed("keyboard") == gen2.get_behavior_seed("keyboard")

    def test_different_profiles_different_seeds(self):
        """Test that different profiles get different seeds."""
        gen1 = ProfileSeedGenerator("profile_a")
        gen2 = ProfileSeedGenerator("profile_b")

        assert gen1.get_behavior_seed("mouse") != gen2.get_behavior_seed("mouse")

    def test_session_seed_uniqueness(self):
        """Test that session seeds are unique per instance."""
        gen1 = ProfileSeedGenerator("test_profile")
        gen2 = ProfileSeedGenerator("test_profile")

        # Session seeds should differ (different session IDs)
        assert gen1.get_session_seed("test") != gen2.get_session_seed("test")

    def test_action_seed_uniqueness(self):
        """Test that action seeds are unique each call."""
        gen = ProfileSeedGenerator("test_profile")

        seeds = [gen.get_action_seed("test") for _ in range(10)]

        # All should be unique
        assert len(set(seeds)) == 10

    def test_variation_within_bounds(self):
        """Test that variation produces values within expected range."""
        gen = ProfileSeedGenerator("test_profile")

        for _ in range(50):
            varied = gen.get_variation("test", 100.0, 0.2)
            assert 80.0 <= varied <= 120.0


class TestViewportPool:
    """Tests for ViewportPool."""

    def test_profile_consistency(self):
        """Test that same profile gets same viewport."""
        vp1 = ViewportPool.get_for_profile("test_profile", add_variation=False)
        vp2 = ViewportPool.get_for_profile("test_profile", add_variation=False)

        assert vp1 == vp2

    def test_different_profiles(self):
        """Test that different profiles may get different viewports."""
        viewports = set()
        for i in range(50):
            vp = ViewportPool.get_for_profile(f"profile_{i}", add_variation=False)
            viewports.add(vp)

        # Should have some variation (not all same viewport)
        assert len(viewports) > 1

    def test_screen_constraints(self):
        """Test that viewports respect screen size limits."""
        vp = ViewportPool.get_for_profile(
            "test_profile",
            max_width=1280,
            max_height=720,
            add_variation=False  # Disable variation for exact constraint test
        )

        assert vp[0] <= 1280
        assert vp[1] <= 720

    def test_common_viewports(self):
        """Test that common viewports are returned correctly."""
        common = ViewportPool.get_common_viewports(3)

        assert len(common) == 3
        # First should be most common (1920x1080)
        assert common[0][0] == 1920
        assert common[0][1] == 1080


class TestRetryHandler:
    """Tests for RetryHandler."""

    @pytest.mark.asyncio
    async def test_success_no_retry(self):
        """Test that successful action doesn't retry."""
        handler = RetryHandler(max_attempts=3)
        call_count = 0

        async def action():
            nonlocal call_count
            call_count += 1
            return "success"

        result = await handler.execute(action)

        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        """Test that action is retried on failure."""
        handler = RetryHandler(max_attempts=3, base_delay=0.1)
        call_count = 0

        async def action():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("fail")
            return "success"

        result = await handler.execute(action, recovery_strategies=['wait'])

        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_max_attempts_exceeded(self):
        """Test that RetryError is raised after max attempts."""
        handler = RetryHandler(max_attempts=2, base_delay=0.1)

        async def action():
            raise ValueError("always fails")

        with pytest.raises(RetryError) as exc_info:
            await handler.execute(action, recovery_strategies=['wait'])

        assert exc_info.value.attempts == 2

    def test_exponential_backoff(self):
        """Test that delays increase exponentially."""
        handler = RetryHandler(base_delay=1.0, exponential_base=2.0, jitter=0)

        # Without jitter, delays should be exactly exponential
        d0 = handler.calculate_delay(0)
        d1 = handler.calculate_delay(1)
        d2 = handler.calculate_delay(2)

        # Allow for some floating point variance
        assert 0.8 < d0 < 1.2  # ~1.0
        assert 1.6 < d1 < 2.4  # ~2.0
        assert 3.2 < d2 < 4.8  # ~4.0


class TestSessionState:
    """Tests for SessionState."""

    def test_scroll_position_save_restore(self, tmp_path):
        """Test saving and restoring scroll positions."""
        state = SessionState("test_profile", data_dir=tmp_path)

        state.save_scroll_position("page1", 500)

        # Restore (with drift)
        pos = state.get_scroll_position("page1", add_drift=False)
        assert pos == 500

    def test_scroll_position_drift(self, tmp_path):
        """Test that drift is applied to restored positions."""
        state = SessionState("test_profile", data_dir=tmp_path)

        state.save_scroll_position("page1", 500)

        positions = [state.get_scroll_position("page1", add_drift=True) for _ in range(10)]

        # Should have some variation due to drift
        assert len(set(positions)) > 1

    def test_visited_pages(self, tmp_path):
        """Test visited page tracking."""
        state = SessionState("test_profile", data_dir=tmp_path)

        state.add_visited("page1")
        state.add_visited("page2")
        state.add_visited("page3")

        assert state.was_recently_visited("page1")
        assert state.was_recently_visited("page2")
        assert not state.was_recently_visited("page_unknown")

        recent = state.get_recent_pages(2)
        assert recent == ["page3", "page2"]  # Most recent first

    def test_custom_data(self, tmp_path):
        """Test custom data storage."""
        state = SessionState("test_profile", data_dir=tmp_path)

        state.set("key1", {"complex": "data"})
        state.set("key2", 42)

        assert state.get("key1") == {"complex": "data"}
        assert state.get("key2") == 42
        assert state.get("unknown", "default") == "default"

    def test_persistence(self, tmp_path):
        """Test that state persists across instances."""
        state1 = SessionState("test_profile", data_dir=tmp_path)
        state1.set("persistent", "value")
        state1.add_visited("persistent_page")

        # Create new instance
        state2 = SessionState("test_profile", data_dir=tmp_path)

        assert state2.get("persistent") == "value"
        assert state2.was_ever_visited("persistent_page")


class TestIntegration:
    """Full integration tests."""

    def test_config_seed_integration(self):
        """Test that config randomization uses consistent seeds."""
        config1 = CommenterConfig()
        config1.randomize_for_profile("test_profile")

        config2 = CommenterConfig()
        config2.randomize_for_profile("test_profile")

        # Same profile should produce same personality
        assert config1.get_personality_info()['seed'] == config2.get_personality_info()['seed']
        assert config1.keyboard.wrong_key_chance == config2.keyboard.wrong_key_chance

    def test_human_browser_config(self):
        """Test HumanBrowserConfig initialization."""
        config = HumanBrowserConfig(
            profile_id="test_profile",
            typing_error_rate=0.08,
            hover_before_click_chance=0.5
        )

        assert config.profile_id == "test_profile"
        assert config.typing_error_rate == 0.08
        assert config._commenter_config is not None

    def test_all_modules_import(self):
        """Test that all modules can be imported together."""
        from src.human_commenter import HumanCommenter, CommenterConfig
        from src.human_commenter.biometrics import BimodalDelay, HumanMouse, HumanKeyboard, HumanScroll
        from src.human_commenter.config import ProfileSeedGenerator, ViewportPool
        from src.human_commenter.utils import RetryHandler
        from src.human_commenter.state import SessionState
        from src.human_commenter.core import HumanBrowser

        # All imports successful
        assert HumanCommenter is not None
        assert BimodalDelay is not None
        assert ProfileSeedGenerator is not None
        assert RetryHandler is not None
        assert SessionState is not None
        assert HumanBrowser is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
