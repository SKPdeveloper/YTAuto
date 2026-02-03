"""
Safety Checks Module

Validates environment before running automation:
- IP address matches expected region
- Browser timezone matches proxy timezone
- Viewport dimensions are correct
"""

import asyncio
from dataclasses import dataclass, field
from typing import Optional, List

from playwright.async_api import Page, BrowserContext

from ..config import CommenterConfig, SafetyConfig, ViewportConfig
from .logger import get_logger

logger = get_logger(__name__)


# JavaScript to override devicePixelRatio and screen dimensions
DEVICE_PIXEL_RATIO_OVERRIDE_SCRIPT = """
Object.defineProperty(window, 'devicePixelRatio', {
    get: function() { return 1; },
    configurable: true
});
Object.defineProperty(screen, 'width', {
    get: function() { return %d; },
    configurable: true
});
Object.defineProperty(screen, 'height', {
    get: function() { return %d; },
    configurable: true
});
Object.defineProperty(screen, 'availWidth', {
    get: function() { return %d; },
    configurable: true
});
Object.defineProperty(screen, 'availHeight', {
    get: function() { return %d; },
    configurable: true
});
"""


@dataclass
class RTTCheckResult:
    """Result of RTT/latency check"""
    passed: bool = True
    avg_rtt_ms: float = 0.0
    min_rtt_ms: float = 0.0
    max_rtt_ms: float = 0.0
    jitter_ms: float = 0.0  # Difference between max and min
    samples: List[float] = field(default_factory=list)
    warning: Optional[str] = None


@dataclass
class SafetyCheckResult:
    """Result of safety checks"""
    passed: bool = True
    ip_check: Optional[bool] = None
    timezone_check: Optional[bool] = None
    viewport_check: Optional[bool] = None
    rtt_check: Optional[bool] = None
    detected_ip: Optional[str] = None
    detected_timezone: Optional[str] = None
    detected_viewport: Optional[tuple] = None
    rtt_result: Optional[RTTCheckResult] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class SafetyChecker:
    """
    Validates browser environment before automation.

    Checks:
    1. IP address matches expected region (proxy working)
    2. Browser timezone matches expected timezone
    3. Viewport dimensions match configuration
    4. Network RTT/latency (proxy leak detection)

    Also provides methods to force viewport settings when system scaling
    causes incorrect resolution reporting.
    """

    # RTT thresholds
    RTT_MIN_THRESHOLD_MS: float = 20.0  # Below this = likely local, proxy leak
    RTT_JITTER_THRESHOLD_MS: float = 100.0  # Above this = unstable connection

    def __init__(self, page: Page, config: CommenterConfig, context: Optional[BrowserContext] = None):
        self.page = page
        self.config = config
        self.context = context
        self.safety_config: SafetyConfig = config.safety
        self.viewport_config: ViewportConfig = config.viewport
        self._adjusted_timeouts: bool = False  # Flag if timeouts were increased due to jitter

    async def verify_all(
        self,
        expected_region: Optional[str] = None,
        expected_timezone: Optional[str] = None,
        check_rtt: bool = True
    ) -> SafetyCheckResult:
        """
        Run all configured safety checks.

        Args:
            expected_region: Expected IP region/country code (e.g., "US", "GB")
            expected_timezone: Expected timezone (e.g., "America/New_York")
            check_rtt: Whether to check network RTT for proxy leak detection

        Returns:
            SafetyCheckResult with all check results
        """
        result = SafetyCheckResult()

        # Run checks in parallel
        checks = []
        check_names = []

        if self.safety_config.check_ip and expected_region:
            checks.append(self._check_ip(expected_region))
            check_names.append("ip")

        if self.safety_config.check_timezone and expected_timezone:
            checks.append(self._check_timezone(expected_timezone))
            check_names.append("timezone")

        if self.safety_config.check_viewport:
            checks.append(self._check_viewport())
            check_names.append("viewport")

        if check_rtt:
            checks.append(self.check_rtt())
            check_names.append("rtt")

        if not checks:
            logger.info("No safety checks configured")
            return result

        check_results = await asyncio.gather(*checks, return_exceptions=True)

        # Process results
        for i, name in enumerate(check_names):
            check_result = check_results[i]

            if name == "ip":
                if isinstance(check_result, Exception):
                    result.ip_check = False
                    result.errors.append(f"IP check failed: {check_result}")
                else:
                    result.ip_check, result.detected_ip = check_result
                    if not result.ip_check:
                        result.errors.append(
                            f"IP region mismatch: expected {expected_region}, got {result.detected_ip}"
                        )

            elif name == "timezone":
                if isinstance(check_result, Exception):
                    result.timezone_check = False
                    result.errors.append(f"Timezone check failed: {check_result}")
                else:
                    result.timezone_check, result.detected_timezone = check_result
                    if not result.timezone_check:
                        result.errors.append(
                            f"Timezone mismatch: expected {expected_timezone}, got {result.detected_timezone}"
                        )

            elif name == "viewport":
                if isinstance(check_result, Exception):
                    result.viewport_check = False
                    result.errors.append(f"Viewport check failed: {check_result}")
                else:
                    result.viewport_check, result.detected_viewport = check_result
                    if not result.viewport_check:
                        expected = (
                            self.safety_config.expected_viewport_width,
                            self.safety_config.expected_viewport_height
                        )
                        result.errors.append(
                            f"Viewport mismatch: expected {expected}, got {result.detected_viewport}"
                        )

            elif name == "rtt":
                if isinstance(check_result, Exception):
                    result.rtt_check = True  # Don't fail on RTT errors
                    result.warnings.append(f"RTT check error: {check_result}")
                else:
                    rtt_result: RTTCheckResult = check_result
                    result.rtt_check = rtt_result.passed
                    result.rtt_result = rtt_result
                    if not rtt_result.passed:
                        result.errors.append(rtt_result.warning or "RTT check failed")
                    elif rtt_result.warning:
                        result.warnings.append(rtt_result.warning)

        # Overall pass/fail
        result.passed = all([
            result.ip_check is None or result.ip_check,
            result.timezone_check is None or result.timezone_check,
            result.viewport_check is None or result.viewport_check,
            result.rtt_check is None or result.rtt_check,
        ])

        if result.passed:
            if result.warnings:
                logger.info(f"Safety checks passed with warnings: {result.warnings}")
            else:
                logger.info("All safety checks passed")
        else:
            logger.warning(f"Safety checks failed: {result.errors}")

        return result

    async def check_ip(self, expected_region: str) -> bool:
        """
        Check if IP matches expected region.

        Args:
            expected_region: Expected region code (e.g., "US")

        Returns:
            True if IP is in expected region
        """
        passed, _ = await self._check_ip(expected_region)
        return passed

    async def check_timezone(self, expected_tz: str) -> bool:
        """
        Check if browser timezone matches expected.

        Args:
            expected_tz: Expected timezone (e.g., "America/New_York")

        Returns:
            True if timezone matches
        """
        passed, _ = await self._check_timezone(expected_tz)
        return passed

    async def check_viewport(self) -> bool:
        """
        Check if viewport dimensions match configuration.

        Returns:
            True if viewport matches expected dimensions
        """
        passed, _ = await self._check_viewport()
        return passed

    async def _check_ip(self, expected_region: str) -> tuple:
        """
        Internal IP check implementation.

        Uses a public IP lookup service to determine current region.
        """
        try:
            # Navigate to IP check service
            # Using ipapi.co as it provides simple JSON response
            response = await self.page.evaluate("""
                async () => {
                    try {
                        const response = await fetch('https://ipapi.co/json/', {
                            method: 'GET',
                            headers: { 'Accept': 'application/json' }
                        });
                        return await response.json();
                    } catch (e) {
                        return { error: e.message };
                    }
                }
            """)

            if "error" in response:
                logger.warning(f"IP check API error: {response['error']}")
                # Don't fail on API errors, just warn
                return (True, "unknown")

            detected_region = response.get("country_code", "unknown")
            detected_ip = response.get("ip", "unknown")

            logger.debug(f"Detected IP region: {detected_region}")

            passed = detected_region.upper() == expected_region.upper()
            return (passed, detected_region)

        except Exception as e:
            logger.warning(f"IP check failed: {e}")
            # Don't fail on errors, just warn
            return (True, "error")

    async def _check_timezone(self, expected_tz: str) -> tuple:
        """
        Internal timezone check implementation.

        Gets browser's timezone from JavaScript.
        """
        try:
            detected_tz = await self.page.evaluate("""
                () => Intl.DateTimeFormat().resolvedOptions().timeZone
            """)

            logger.debug(f"Detected timezone: {detected_tz}")

            # Check if timezones match
            # Allow partial matches for region (e.g., "America/New_York" matches "America/*")
            passed = (
                detected_tz == expected_tz or
                detected_tz.split('/')[0] == expected_tz.split('/')[0]
            )

            return (passed, detected_tz)

        except Exception as e:
            logger.warning(f"Timezone check failed: {e}")
            return (True, "error")

    async def _check_viewport(self) -> tuple:
        """
        Internal viewport check implementation.

        Also checks devicePixelRatio to detect system scaling issues.
        """
        try:
            viewport = await self.page.evaluate("""
                () => ({
                    width: window.innerWidth,
                    height: window.innerHeight,
                    devicePixelRatio: window.devicePixelRatio,
                    screenWidth: screen.width,
                    screenHeight: screen.height
                })
            """)

            detected = (viewport["width"], viewport["height"])
            detected_dpr = viewport["devicePixelRatio"]

            # Use viewport config if available, otherwise safety config
            expected = (
                self.viewport_config.width if self.viewport_config.force_viewport
                else self.safety_config.expected_viewport_width,
                self.viewport_config.height if self.viewport_config.force_viewport
                else self.safety_config.expected_viewport_height
            )
            expected_dpr = self.viewport_config.device_scale_factor

            logger.debug(
                f"Detected viewport: {detected}, DPR={detected_dpr}, "
                f"screen={viewport['screenWidth']}x{viewport['screenHeight']}"
            )

            # Check dimensions with 5% tolerance
            width_ok = abs(detected[0] - expected[0]) < expected[0] * 0.05
            height_ok = abs(detected[1] - expected[1]) < expected[1] * 0.05

            # Check devicePixelRatio
            dpr_ok = abs(detected_dpr - expected_dpr) < 0.1

            if not dpr_ok:
                logger.warning(
                    f"devicePixelRatio mismatch: expected {expected_dpr}, got {detected_dpr}. "
                    "This may indicate system scaling issues (e.g., Windows 200% DPI)"
                )

            return (width_ok and height_ok and dpr_ok, detected)

        except Exception as e:
            logger.warning(f"Viewport check failed: {e}")
            return (True, (0, 0))

    async def get_browser_fingerprint(self) -> dict:
        """
        Get browser fingerprint info for debugging.

        Returns dict with various browser properties.
        """
        try:
            return await self.page.evaluate("""
                () => ({
                    userAgent: navigator.userAgent,
                    platform: navigator.platform,
                    language: navigator.language,
                    languages: navigator.languages,
                    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                    timezoneOffset: new Date().getTimezoneOffset(),
                    screenWidth: screen.width,
                    screenHeight: screen.height,
                    colorDepth: screen.colorDepth,
                    devicePixelRatio: window.devicePixelRatio,
                    hardwareConcurrency: navigator.hardwareConcurrency,
                    webdriver: navigator.webdriver,
                    plugins: Array.from(navigator.plugins).map(p => p.name),
                })
            """)
        except Exception as e:
            logger.error(f"Failed to get fingerprint: {e}")
            return {}

    async def force_viewport_settings(self) -> bool:
        """
        Force viewport and devicePixelRatio settings.

        Use this when Windows system scaling (e.g., 200% DPI) causes
        incorrect viewport reporting (960x540 instead of 1920x1080).

        Returns:
            True if settings were applied successfully
        """
        vp = self.viewport_config

        if not vp.force_viewport:
            logger.debug("Viewport forcing disabled")
            return True

        try:
            logger.info(f"Forcing viewport: {vp.width}x{vp.height}, DPR={vp.device_scale_factor}")

            # Step 1: Set viewport size via Playwright
            await self.page.set_viewport_size({
                "width": vp.width,
                "height": vp.height
            })

            # Step 2: Override devicePixelRatio and screen dimensions via JavaScript
            if vp.override_device_pixel_ratio:
                script = DEVICE_PIXEL_RATIO_OVERRIDE_SCRIPT % (vp.width, vp.height, vp.width, vp.height)

                # Add as init script for future navigations
                if self.context:
                    await self.context.add_init_script(script)

                # Execute immediately on current page
                await self.page.evaluate(script)

            # Step 3: Try CDP-level override if context is available
            if self.context:
                try:
                    cdp = await self.context.new_cdp_session(self.page)
                    await cdp.send("Emulation.setDeviceMetricsOverride", {
                        "width": vp.width,
                        "height": vp.height,
                        "deviceScaleFactor": vp.device_scale_factor,
                        "mobile": False,
                        "screenWidth": vp.width,
                        "screenHeight": vp.height,
                    })
                    await cdp.detach()
                except Exception as e:
                    logger.debug(f"CDP metrics override not available: {e}")

            # Verify
            actual = await self.page.evaluate("""
                () => ({
                    innerWidth: window.innerWidth,
                    innerHeight: window.innerHeight,
                    devicePixelRatio: window.devicePixelRatio,
                    screenWidth: screen.width,
                    screenHeight: screen.height
                })
            """)

            logger.info(
                f"Viewport after forcing: {actual['innerWidth']}x{actual['innerHeight']}, "
                f"DPR={actual['devicePixelRatio']}, screen={actual['screenWidth']}x{actual['screenHeight']}"
            )

            return True

        except Exception as e:
            logger.error(f"Failed to force viewport settings: {e}")
            return False

    async def verify_viewport_forced(self) -> bool:
        """
        Verify that viewport settings are correctly applied.

        Returns:
            True if viewport matches expected values
        """
        vp = self.viewport_config

        try:
            actual = await self.page.evaluate("""
                () => ({
                    innerWidth: window.innerWidth,
                    innerHeight: window.innerHeight,
                    devicePixelRatio: window.devicePixelRatio
                })
            """)

            width_ok = abs(actual["innerWidth"] - vp.width) < 50
            height_ok = abs(actual["innerHeight"] - vp.height) < 50
            dpr_ok = abs(actual["devicePixelRatio"] - vp.device_scale_factor) < 0.1

            if not (width_ok and height_ok and dpr_ok):
                logger.warning(
                    f"Viewport mismatch: expected {vp.width}x{vp.height} DPR={vp.device_scale_factor}, "
                    f"got {actual['innerWidth']}x{actual['innerHeight']} DPR={actual['devicePixelRatio']}"
                )
                return False

            return True

        except Exception as e:
            logger.error(f"Failed to verify viewport: {e}")
            return False

    async def check_rtt(self, num_samples: int = 3) -> RTTCheckResult:
        """
        Check network RTT (Round-Trip Time) to detect proxy issues.

        Makes requests to Google servers and measures latency.
        - RTT < 20ms: CRITICAL - Likely proxy leak (direct connection)
        - Jitter > 100ms: WARNING - Unstable connection, increase timeouts

        Args:
            num_samples: Number of RTT samples to collect (default 3)

        Returns:
            RTTCheckResult with latency measurements and status
        """
        result = RTTCheckResult()

        try:
            # JavaScript to measure RTT to Google servers
            rtt_script = """
                async (numSamples) => {
                    const targets = [
                        'https://www.google.com/generate_204',
                        'https://www.gstatic.com/generate_204',
                        'https://connectivitycheck.gstatic.com/generate_204'
                    ];

                    const samples = [];

                    for (let i = 0; i < numSamples; i++) {
                        const target = targets[i % targets.length];
                        const start = performance.now();

                        try {
                            await fetch(target, {
                                method: 'HEAD',
                                mode: 'no-cors',
                                cache: 'no-store'
                            });
                            const end = performance.now();
                            samples.push(end - start);
                        } catch (e) {
                            // If fetch fails, try with a different approach
                            const img = new Image();
                            const imgStart = performance.now();

                            await new Promise((resolve) => {
                                img.onload = img.onerror = () => {
                                    const imgEnd = performance.now();
                                    samples.push(imgEnd - imgStart);
                                    resolve();
                                };
                                img.src = `https://www.google.com/favicon.ico?_=${Date.now()}`;
                            });
                        }

                        // Small delay between samples
                        await new Promise(r => setTimeout(r, 100));
                    }

                    return samples;
                }
            """

            samples = await self.page.evaluate(rtt_script, num_samples)

            if not samples or len(samples) == 0:
                result.passed = True
                result.warning = "Could not measure RTT"
                return result

            result.samples = samples
            result.avg_rtt_ms = sum(samples) / len(samples)
            result.min_rtt_ms = min(samples)
            result.max_rtt_ms = max(samples)
            result.jitter_ms = result.max_rtt_ms - result.min_rtt_ms

            logger.debug(
                f"RTT check: avg={result.avg_rtt_ms:.1f}ms, "
                f"min={result.min_rtt_ms:.1f}ms, max={result.max_rtt_ms:.1f}ms, "
                f"jitter={result.jitter_ms:.1f}ms"
            )

            # Check for proxy leak (RTT too low)
            if result.min_rtt_ms < self.RTT_MIN_THRESHOLD_MS:
                result.passed = False
                result.warning = (
                    f"CRITICAL: RTT {result.min_rtt_ms:.1f}ms < {self.RTT_MIN_THRESHOLD_MS}ms - "
                    "Possible proxy leak! Connection may be direct."
                )
                logger.error(result.warning)

            # Check for high jitter (unstable connection)
            elif result.jitter_ms > self.RTT_JITTER_THRESHOLD_MS:
                result.passed = True  # Don't fail, but warn
                result.warning = (
                    f"WARNING: High jitter {result.jitter_ms:.1f}ms > {self.RTT_JITTER_THRESHOLD_MS}ms - "
                    "Unstable connection, timeouts will be increased."
                )
                logger.warning(result.warning)
                self._adjusted_timeouts = True

            else:
                result.passed = True
                logger.info(f"RTT check passed: avg={result.avg_rtt_ms:.1f}ms, jitter={result.jitter_ms:.1f}ms")

            return result

        except Exception as e:
            logger.warning(f"RTT check failed: {e}")
            result.passed = True  # Don't fail on measurement error
            result.warning = f"RTT measurement error: {e}"
            return result

    def should_increase_timeouts(self) -> bool:
        """
        Check if timeouts should be increased due to network conditions.

        Returns:
            True if high jitter was detected
        """
        return self._adjusted_timeouts

    def get_timeout_multiplier(self) -> float:
        """
        Get timeout multiplier based on network conditions.

        Returns:
            1.0 for normal, 1.5-2.0 for unstable connections
        """
        return 1.5 if self._adjusted_timeouts else 1.0
