"""
AdsPower Playwright Client

Connects to AdsPower browser profiles via CDP (Chrome DevTools Protocol).
"""

import asyncio
from typing import Optional

import httpx
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright, CDPSession

from ..config import CommenterConfig
from ..safety.logger import get_logger

logger = get_logger(__name__)


# JavaScript to override devicePixelRatio
DEVICE_PIXEL_RATIO_OVERRIDE_SCRIPT = """
Object.defineProperty(window, 'devicePixelRatio', {
    get: function() { return 1; },
    configurable: true
});

// Also override screen dimensions to match viewport
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


class AdsPowerConnectionError(Exception):
    """Raised when connection to AdsPower fails"""
    pass


class AdsPowerPlaywrightClient:
    """
    Manages Playwright connection to AdsPower browser profiles.

    AdsPower provides anti-detect browser profiles with unique fingerprints.
    This client connects via CDP to control the browser with Playwright.
    """

    def __init__(self, config: CommenterConfig):
        self.config = config
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._profile_id: Optional[str] = None
        self._ws_endpoint: Optional[str] = None
        self._cdp_session: Optional[CDPSession] = None

    async def connect(self, profile_id: str) -> None:
        """
        Connect to an AdsPower browser profile.

        Args:
            profile_id: AdsPower profile ID (e.g., "k18ewu4m")

        Raises:
            AdsPowerConnectionError: If connection fails
        """
        self._profile_id = profile_id
        logger.info(f"Connecting to AdsPower profile: {profile_id}")

        # Step 1: Start browser via AdsPower API
        start_url = f"{self.config.adspower_base_url}/api/v1/browser/start"
        params = {"user_id": profile_id}

        try:
            async with httpx.AsyncClient(timeout=self.config.adspower_timeout) as client:
                response = await client.get(start_url, params=params)
                response.raise_for_status()
                data = response.json()
        except httpx.RequestError as e:
            raise AdsPowerConnectionError(f"Failed to connect to AdsPower API: {e}")
        except httpx.HTTPStatusError as e:
            raise AdsPowerConnectionError(f"AdsPower API error: {e.response.status_code}")

        # Parse response
        if data.get("code") != 0:
            error_msg = data.get("msg", "Unknown error")
            raise AdsPowerConnectionError(f"AdsPower returned error: {error_msg}")

        ws_data = data.get("data", {})
        ws_endpoint = ws_data.get("ws", {}).get("puppeteer")

        if not ws_endpoint:
            raise AdsPowerConnectionError("No WebSocket endpoint in AdsPower response")

        self._ws_endpoint = ws_endpoint
        logger.debug(f"Got WebSocket endpoint: {ws_endpoint[:50]}...")

        # Step 2: Connect Playwright via CDP
        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.connect_over_cdp(ws_endpoint)
        except Exception as e:
            await self._cleanup()
            raise AdsPowerConnectionError(f"Failed to connect Playwright to CDP: {e}")

        # Get the default context and page
        contexts = self._browser.contexts
        if contexts:
            self._context = contexts[0]
            pages = self._context.pages
            if pages:
                self._page = pages[0]
            else:
                self._page = await self._context.new_page()
        else:
            # Create new context if none exists
            self._context = await self._browser.new_context()
            self._page = await self._context.new_page()

        # Apply viewport and scaling settings
        await self._configure_viewport_and_scaling()

        logger.info(f"Connected to AdsPower profile: {profile_id}")

    async def get_page(self) -> Page:
        """
        Get the current page instance.

        Returns:
            Playwright Page object

        Raises:
            AdsPowerConnectionError: If not connected
        """
        if not self._page:
            raise AdsPowerConnectionError("Not connected to browser. Call connect() first.")
        return self._page

    async def get_context(self) -> BrowserContext:
        """
        Get the current browser context.

        Returns:
            Playwright BrowserContext object

        Raises:
            AdsPowerConnectionError: If not connected
        """
        if not self._context:
            raise AdsPowerConnectionError("Not connected to browser. Call connect() first.")
        return self._context

    async def new_page(self) -> Page:
        """
        Create a new page in the current context.

        Returns:
            New Playwright Page object
        """
        if not self._context:
            raise AdsPowerConnectionError("Not connected to browser. Call connect() first.")

        new_page = await self._context.new_page()

        # Apply init script to new pages as well
        if self.config.viewport.override_device_pixel_ratio:
            vp = self.config.viewport
            await new_page.add_init_script(
                DEVICE_PIXEL_RATIO_OVERRIDE_SCRIPT % (vp.width, vp.height, vp.width, vp.height)
            )

        return new_page

    async def _configure_viewport_and_scaling(self) -> None:
        """
        Configure viewport size, device scale factor, and maximize window.

        This fixes issues with Windows system scaling (e.g., 200% DPI)
        reporting incorrect viewport sizes like 960x540 instead of 1920x1080.
        """
        vp_config = self.config.viewport

        # Step 1: Maximize browser window (always, if enabled)
        if vp_config.maximize_on_connect:
            logger.debug("Maximizing browser window")
            await self._maximize_window()

        if not vp_config.force_viewport:
            logger.debug("Viewport forcing disabled, skipping viewport override")
            return

        try:

            # Step 2: Create CDP session for low-level control
            self._cdp_session = await self._context.new_cdp_session(self._page)

            # Step 3: Set device metrics override via CDP
            # This forces the viewport and deviceScaleFactor regardless of system scaling
            logger.debug(f"Setting device metrics: {vp_config.width}x{vp_config.height}, scale={vp_config.device_scale_factor}")
            await self._cdp_session.send("Emulation.setDeviceMetricsOverride", {
                "width": vp_config.width,
                "height": vp_config.height,
                "deviceScaleFactor": vp_config.device_scale_factor,
                "mobile": False,
                "screenWidth": vp_config.width,
                "screenHeight": vp_config.height,
            })

            # Step 4: Add init script to override window.devicePixelRatio
            # This ensures JavaScript sees the correct value
            if vp_config.override_device_pixel_ratio:
                logger.debug("Adding devicePixelRatio override script")
                await self._context.add_init_script(
                    DEVICE_PIXEL_RATIO_OVERRIDE_SCRIPT % (vp_config.width, vp_config.height, vp_config.width, vp_config.height)
                )

                # Also run it immediately on the current page
                await self._page.evaluate(
                    DEVICE_PIXEL_RATIO_OVERRIDE_SCRIPT % (vp_config.width, vp_config.height, vp_config.width, vp_config.height)
                )

            # Step 5: Set Playwright viewport as well
            await self._page.set_viewport_size({
                "width": vp_config.width,
                "height": vp_config.height
            })

            # Verify the settings
            actual = await self._page.evaluate("""
                () => ({
                    innerWidth: window.innerWidth,
                    innerHeight: window.innerHeight,
                    devicePixelRatio: window.devicePixelRatio,
                    screenWidth: screen.width,
                    screenHeight: screen.height
                })
            """)

            logger.info(
                f"Viewport configured: {actual['innerWidth']}x{actual['innerHeight']}, "
                f"DPR={actual['devicePixelRatio']}, screen={actual['screenWidth']}x{actual['screenHeight']}"
            )

        except Exception as e:
            logger.warning(f"Failed to configure viewport: {e}")
            # Don't fail the connection, just warn

    async def _maximize_window(self) -> None:
        """Maximize the browser window using CDP."""
        try:
            # Get window ID first
            cdp = await self._context.new_cdp_session(self._page)

            # Get the window bounds
            window_info = await cdp.send("Browser.getWindowForTarget")
            window_id = window_info.get("windowId")

            if window_id:
                # Set window to maximized state
                await cdp.send("Browser.setWindowBounds", {
                    "windowId": window_id,
                    "bounds": {"windowState": "maximized"}
                })
                logger.debug(f"Window {window_id} maximized")

                # Small delay to allow window to resize
                await asyncio.sleep(0.5)

            await cdp.detach()

        except Exception as e:
            logger.warning(f"Failed to maximize window: {e}")

    async def disconnect(self) -> None:
        """
        Disconnect from the AdsPower browser.

        Note: This does NOT close the AdsPower browser, just disconnects Playwright.
        """
        logger.info(f"Disconnecting from AdsPower profile: {self._profile_id}")
        await self._cleanup()

    async def close_browser(self) -> None:
        """
        Close the AdsPower browser via API.

        This stops the browser profile in AdsPower.
        """
        if not self._profile_id:
            return

        logger.info(f"Closing AdsPower browser: {self._profile_id}")

        stop_url = f"{self.config.adspower_base_url}/api/v1/browser/stop"
        params = {"user_id": self._profile_id}

        try:
            async with httpx.AsyncClient(timeout=self.config.adspower_timeout) as client:
                await client.get(stop_url, params=params)
        except Exception as e:
            logger.warning(f"Failed to stop AdsPower browser: {e}")

        await self._cleanup()

    async def _cleanup(self) -> None:
        """Clean up resources"""
        self._page = None
        self._context = None

        if self._cdp_session:
            try:
                await self._cdp_session.detach()
            except Exception:
                pass
            self._cdp_session = None

        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

        self._ws_endpoint = None

    @property
    def is_connected(self) -> bool:
        """Check if currently connected to a browser"""
        return self._browser is not None and self._page is not None

    @property
    def profile_id(self) -> Optional[str]:
        """Get the current profile ID"""
        return self._profile_id

    async def __aenter__(self) -> "AdsPowerPlaywrightClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.disconnect()
