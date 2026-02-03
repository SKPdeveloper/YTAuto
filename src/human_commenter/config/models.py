"""
Configuration Models for Human Commenter

Pydantic-based configuration with tunable parameters for human-like behavior.
"""

from typing import Tuple, Optional, List
from pydantic import BaseModel, Field, PrivateAttr, ConfigDict


class DelayConfig(BaseModel):
    """Gaussian delay configuration (mean, std_dev, min_bound, max_bound)"""
    mean: float
    std_dev: float
    min_bound: float
    max_bound: float

    def as_tuple(self) -> Tuple[float, float, float, float]:
        return (self.mean, self.std_dev, self.min_bound, self.max_bound)


class MouseConfig(BaseModel):
    """Mouse movement configuration"""
    bezier_control_variance: float = Field(
        default=0.3,
        description="Variance for Bezier curve control points (0.1-0.5)"
    )
    click_jitter_radius: float = Field(
        default=3.0,
        description="Random offset radius for click positions in pixels"
    )
    tremor_amplitude: float = Field(
        default=1.5,
        description="Micro-tremor amplitude during hover in pixels"
    )
    tremor_frequency_min: float = Field(
        default=8.0,
        description="Minimum tremor frequency in Hz"
    )
    tremor_frequency_max: float = Field(
        default=12.0,
        description="Maximum tremor frequency in Hz"
    )
    # Fitts' Law constants: MT = a + b * log2(2D/W)
    fitts_a: float = Field(default=0.1, description="Fitts' Law intercept")
    fitts_b: float = Field(default=0.1, description="Fitts' Law slope")
    min_movement_time: float = Field(default=0.2, description="Minimum movement time in seconds")
    max_movement_time: float = Field(default=2.0, description="Maximum movement time in seconds")

    # Overshoot parameters (will be randomized per profile)
    overshoot_chance: Optional[float] = Field(
        default=None,
        description="Probability of overshooting target (None = randomize per profile, range 0.05-0.25)"
    )
    overshoot_distance_ratio: Optional[float] = Field(
        default=None,
        description="Overshoot distance as ratio of movement (None = randomize per profile, range 0.04-0.15)"
    )
    spiral_chance: Optional[float] = Field(
        default=None,
        description="Probability of spiral approach (None = randomize per profile, range 0.15-0.35)"
    )

    # Click hold duration ranges (ms)
    tap_hold_min: float = Field(default=40.0, description="Min hold for tap click (ms)")
    tap_hold_max: float = Field(default=80.0, description="Max hold for tap click (ms)")
    normal_hold_min: float = Field(default=80.0, description="Min hold for normal click (ms)")
    normal_hold_max: float = Field(default=150.0, description="Max hold for normal click (ms)")
    deliberate_hold_min: float = Field(default=150.0, description="Min hold for deliberate click (ms)")
    deliberate_hold_max: float = Field(default=280.0, description="Max hold for deliberate click (ms)")


class KeyboardConfig(BaseModel):
    """Keyboard typing configuration"""
    wrong_key_chance: float = Field(
        default=0.05,
        description="Probability of hitting adjacent key (0.0-0.15)"
    )
    thinking_pause_chance: float = Field(
        default=0.02,
        description="Probability of mid-typing pause (0.0-0.1)"
    )
    thinking_pause_min: float = Field(default=0.5, description="Min thinking pause in seconds")
    thinking_pause_max: float = Field(default=1.5, description="Max thinking pause in seconds")
    sticky_key_chance: float = Field(
        default=0.03,
        description="Probability of holding key slightly longer"
    )
    sticky_key_extra_ms: float = Field(default=50.0, description="Extra hold time for sticky keys")
    inter_key_delay: DelayConfig = Field(
        default_factory=lambda: DelayConfig(
            mean=0.15, std_dev=0.05, min_bound=0.08, max_bound=0.30
        ),
        description="Delay between keystrokes"
    )


class ScrollConfig(BaseModel):
    """Scroll behavior configuration"""
    pixels_per_step_min: int = Field(default=50, description="Min pixels per scroll step")
    pixels_per_step_max: int = Field(default=150, description="Max pixels per scroll step")
    steps_per_scroll_min: int = Field(default=2, description="Min wheel events per scroll action")
    steps_per_scroll_max: int = Field(default=5, description="Max wheel events per scroll action")
    delay_between_steps: DelayConfig = Field(
        default_factory=lambda: DelayConfig(
            mean=0.08, std_dev=0.03, min_bound=0.03, max_bound=0.15
        ),
        description="Delay between scroll steps"
    )
    overshoot_chance: float = Field(
        default=0.2,
        description="Probability of overshooting and scrolling back"
    )


class WorkflowConfig(BaseModel):
    """Workflow timing configuration"""
    consumption_duration_min: float = Field(default=45.0, description="Min video watch time in seconds")
    consumption_duration_max: float = Field(default=120.0, description="Max video watch time in seconds")
    research_pause_min: float = Field(default=5.0, description="Min pause while reading comments")
    research_pause_max: float = Field(default=10.0, description="Max pause while reading comments")
    post_comment_wait: float = Field(default=30.0, description="Wait time after posting before pinning")
    entropy_chance: float = Field(default=0.15, description="Chance of random action between states")
    max_read_more_clicks: int = Field(default=3, description="Max 'Read more' clicks during research")


class ViewportConfig(BaseModel):
    """Viewport and scaling configuration"""
    force_viewport: bool = Field(default=True, description="Force viewport size on connect")
    width: int = Field(default=1920, description="Viewport width")
    height: int = Field(default=1080, description="Viewport height")
    device_scale_factor: float = Field(default=1.0, description="Device scale factor (1.0 to ignore system scaling)")
    override_device_pixel_ratio: bool = Field(default=True, description="Override window.devicePixelRatio via init script")
    maximize_on_connect: bool = Field(default=True, description="Maximize browser window on connect")


class SafetyConfig(BaseModel):
    """Safety check configuration"""
    check_ip: bool = Field(default=True, description="Verify IP matches expected region")
    check_timezone: bool = Field(default=True, description="Verify browser timezone")
    check_viewport: bool = Field(default=True, description="Verify viewport dimensions")
    expected_viewport_width: int = Field(default=1920, description="Expected viewport width")
    expected_viewport_height: int = Field(default=1080, description="Expected viewport height")


class CommenterConfig(BaseModel):
    """Main configuration for HumanCommenter"""

    # AdsPower connection
    adspower_base_url: str = Field(
        default="http://local.adspower.net:50325",
        description="AdsPower local API base URL"
    )
    adspower_timeout: float = Field(
        default=30.0,
        description="Timeout for AdsPower API calls in seconds"
    )

    # Personality seed (set by randomize_for_profile)
    _personality_seed: Optional[int] = PrivateAttr(default=None)
    _profile_id: Optional[str] = PrivateAttr(default=None)

    # Page load delays
    delay_page_load: DelayConfig = Field(
        default_factory=lambda: DelayConfig(
            mean=3.0, std_dev=1.0, min_bound=1.0, max_bound=6.0
        ),
        description="Delay after page loads"
    )
    delay_before_click: DelayConfig = Field(
        default_factory=lambda: DelayConfig(
            mean=0.3, std_dev=0.1, min_bound=0.1, max_bound=0.8
        ),
        description="Delay before clicking"
    )
    delay_after_action: DelayConfig = Field(
        default_factory=lambda: DelayConfig(
            mean=0.5, std_dev=0.2, min_bound=0.2, max_bound=1.2
        ),
        description="Delay after completing an action"
    )

    # Component configs
    mouse: MouseConfig = Field(default_factory=MouseConfig)
    keyboard: KeyboardConfig = Field(default_factory=KeyboardConfig)
    scroll: ScrollConfig = Field(default_factory=ScrollConfig)
    workflow: WorkflowConfig = Field(default_factory=WorkflowConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    viewport: ViewportConfig = Field(default_factory=ViewportConfig)

    # Logging
    log_sensitive_data: bool = Field(
        default=False,
        description="Whether to log potentially sensitive data (video IDs, comment text)"
    )

    model_config = ConfigDict(validate_assignment=True)

    def randomize_for_profile(self, profile_id: str) -> "CommenterConfig":
        """
        Create a personalized config variant for a specific profile.

        Uses profile_id as a seed to create consistent but unique
        "personality" for each account. Parameters are varied by +/- 20%.

        This ensures:
        - Each account has its own typing/mouse "handwriting"
        - The handwriting is consistent across sessions for the same account
        - Different accounts behave slightly differently

        Args:
            profile_id: AdsPower profile ID

        Returns:
            Self with modified parameters
        """
        import hashlib
        import random as rnd

        # Create deterministic seed from profile_id
        seed = int(hashlib.md5(profile_id.encode()).hexdigest()[:8], 16)
        self._personality_seed = seed
        self._profile_id = profile_id

        # Create seeded random generator
        gen = rnd.Random(seed)

        def vary(value: float, variation: float = 0.2) -> float:
            """Vary a value by +/- variation percent"""
            multiplier = 1.0 + gen.uniform(-variation, variation)
            return value * multiplier

        # Vary keyboard parameters (+/- 20%)
        self.keyboard.wrong_key_chance = vary(self.keyboard.wrong_key_chance)
        self.keyboard.thinking_pause_chance = vary(self.keyboard.thinking_pause_chance)
        self.keyboard.sticky_key_chance = vary(self.keyboard.sticky_key_chance)
        self.keyboard.inter_key_delay.mean = vary(self.keyboard.inter_key_delay.mean)
        self.keyboard.inter_key_delay.std_dev = vary(self.keyboard.inter_key_delay.std_dev)

        # Vary mouse parameters (+/- 20%)
        self.mouse.bezier_control_variance = vary(self.mouse.bezier_control_variance)
        self.mouse.click_jitter_radius = vary(self.mouse.click_jitter_radius)
        self.mouse.tremor_amplitude = vary(self.mouse.tremor_amplitude)
        self.mouse.fitts_a = vary(self.mouse.fitts_a)
        self.mouse.fitts_b = vary(self.mouse.fitts_b)

        # Vary scroll parameters (+/- 20%)
        self.scroll.overshoot_chance = vary(self.scroll.overshoot_chance)
        self.scroll.delay_between_steps.mean = vary(self.scroll.delay_between_steps.mean)

        # Vary delay parameters (+/- 15%)
        self.delay_before_click.mean = vary(self.delay_before_click.mean, 0.15)
        self.delay_after_action.mean = vary(self.delay_after_action.mean, 0.15)

        return self

    def get_personality_info(self) -> dict:
        """
        Get info about the current personality settings.

        Returns:
            Dict with seed and key personality parameters
        """
        return {
            "profile_id": self._profile_id,
            "seed": self._personality_seed,
            "wrong_key_chance": self.keyboard.wrong_key_chance,
            "inter_key_delay_mean": self.keyboard.inter_key_delay.mean,
            "bezier_variance": self.mouse.bezier_control_variance,
            "click_jitter": self.mouse.click_jitter_radius,
            "tremor_amplitude": self.mouse.tremor_amplitude,
        }
