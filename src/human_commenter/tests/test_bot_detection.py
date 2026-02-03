"""
Bot Detection Test Script

Tests the browser automation against known bot detection sites:
- bot.sannysoft.com - WebDriver detection
- browserleaks.com - Fingerprint analysis
- pixelscan.net - Bot detection

Run with: python -m human_commenter.tests.test_bot_detection --profile YOUR_ADSPOWER_PROFILE_ID
"""

import asyncio
import argparse
import json
from datetime import datetime
from pathlib import Path

# Add parent to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from human_commenter.client import AdsPowerPlaywrightClient
from human_commenter.config import CommenterConfig
from human_commenter.biometrics import HumanMouse, HumanScroll, GaussianDelay
from human_commenter.safety.logger import get_logger

logger = get_logger(__name__)


BOT_DETECTION_SITES = [
    {
        "name": "Sannysoft Bot Test",
        "url": "https://bot.sannysoft.com/",
        "description": "Перевіряє WebDriver detection, Chrome automation flags",
        "check_selectors": {
            "webdriver": "#webdriver-result",
            "chrome": "#chrome-result",
        }
    },
    {
        "name": "BrowserLeaks WebRTC",
        "url": "https://browserleaks.com/webrtc",
        "description": "Перевіряє WebRTC витоки IP",
    },
    {
        "name": "BrowserLeaks Canvas",
        "url": "https://browserleaks.com/canvas",
        "description": "Перевіряє Canvas fingerprint",
    },
    {
        "name": "PixelScan",
        "url": "https://pixelscan.net/",
        "description": "Комплексна перевірка на бота",
    },
    {
        "name": "CreepJS",
        "url": "https://abrahamjuliot.github.io/creepjs/",
        "description": "Глибокий fingerprint analysis",
    },
    {
        "name": "Incolumitas Bot Detection",
        "url": "https://bot.incolumitas.com/",
        "description": "Просунута детекція ботів",
    }
]


async def test_single_site(client: AdsPowerPlaywrightClient, site: dict, config: CommenterConfig) -> dict:
    """
    Test a single bot detection site.

    Returns:
        dict with test results
    """
    page = await client.get_page()
    mouse = HumanMouse(page, config)
    scroll = HumanScroll(page, config)

    result = {
        "site": site["name"],
        "url": site["url"],
        "timestamp": datetime.now().isoformat(),
        "success": False,
        "screenshot": None,
        "details": {},
        "errors": []
    }

    try:
        logger.info(f"Testing: {site['name']}")
        logger.info(f"URL: {site['url']}")

        # Navigate to site
        await page.goto(site["url"], wait_until="networkidle", timeout=30000)

        # Wait for page to fully load
        await GaussianDelay(mean=3.0, std_dev=1.0, min_bound=2.0, max_bound=5.0).wait()

        # Do some human-like actions
        viewport = page.viewport_size
        if viewport:
            # Move mouse around
            for _ in range(3):
                x = viewport["width"] * (0.2 + 0.6 * (await asyncio.sleep(0) or 1) * 0.5)
                y = viewport["height"] * (0.2 + 0.6 * (await asyncio.sleep(0) or 1) * 0.5)
                import random
                x = random.uniform(100, viewport["width"] - 100)
                y = random.uniform(100, viewport["height"] - 100)
                await mouse.move_to(x, y)
                await asyncio.sleep(random.uniform(0.5, 1.5))

            # Scroll down and up
            await scroll.scroll_down(pixels=300)
            await asyncio.sleep(1)
            await scroll.scroll_up(pixels=150)

        # Wait for any async checks
        await asyncio.sleep(3)

        # Take screenshot
        screenshots_dir = Path(__file__).parent / "screenshots"
        screenshots_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = site["name"].replace(" ", "_").lower()
        screenshot_path = screenshots_dir / f"{safe_name}_{timestamp}.png"

        await page.screenshot(path=str(screenshot_path), full_page=True)
        result["screenshot"] = str(screenshot_path)
        logger.info(f"Screenshot saved: {screenshot_path}")

        # Try to extract results if selectors provided
        if "check_selectors" in site:
            for name, selector in site["check_selectors"].items():
                try:
                    element = await page.query_selector(selector)
                    if element:
                        text = await element.text_content()
                        result["details"][name] = text
                        logger.info(f"  {name}: {text}")
                except Exception as e:
                    result["details"][name] = f"Error: {e}"

        # Get page title as basic check
        result["details"]["page_title"] = await page.title()

        result["success"] = True
        logger.info(f"[OK] {site['name']} - Test completed")

    except Exception as e:
        result["errors"].append(str(e))
        logger.error(f"[FAIL] {site['name']} - Error: {e}")

    return result


async def run_bot_detection_tests(profile_id: str, sites: list = None) -> list:
    """
    Run bot detection tests on specified sites.

    Args:
        profile_id: AdsPower profile ID
        sites: List of sites to test (default: all)

    Returns:
        List of test results
    """
    config = CommenterConfig()
    client = AdsPowerPlaywrightClient(config)

    results = []

    try:
        await client.connect(profile_id)
        logger.info(f"Connected to AdsPower profile: {profile_id}")

        test_sites = sites or BOT_DETECTION_SITES

        for site in test_sites:
            result = await test_single_site(client, site, config)
            results.append(result)

            # Pause between sites
            await asyncio.sleep(2)

    finally:
        await client.disconnect()

    return results


def print_results_summary(results: list):
    """Print a summary of test results."""
    print("\n" + "="*60)
    print("BOT DETECTION TEST RESULTS")
    print("="*60)

    for result in results:
        status = "[PASS]" if result["success"] else "[FAIL]"
        print(f"\n{status} - {result['site']}")
        print(f"  URL: {result['url']}")

        if result["screenshot"]:
            print(f"  Screenshot: {result['screenshot']}")

        if result["details"]:
            print("  Details:")
            for key, value in result["details"].items():
                # Truncate long values
                if isinstance(value, str) and len(value) > 50:
                    value = value[:50] + "..."
                print(f"    {key}: {value}")

        if result["errors"]:
            print("  Errors:")
            for error in result["errors"]:
                print(f"    - {error}")

    print("\n" + "="*60)
    passed = sum(1 for r in results if r["success"])
    print(f"TOTAL: {passed}/{len(results)} tests passed")
    print("="*60)


async def main():
    parser = argparse.ArgumentParser(description="Test bot detection sites")
    parser.add_argument("--profile", "-p", required=True, help="AdsPower profile ID")
    parser.add_argument("--site", "-s", help="Test specific site by name")
    parser.add_argument("--output", "-o", help="Output JSON file for results")

    args = parser.parse_args()

    # Filter sites if specific one requested
    sites = None
    if args.site:
        sites = [s for s in BOT_DETECTION_SITES if args.site.lower() in s["name"].lower()]
        if not sites:
            print(f"Site '{args.site}' not found. Available sites:")
            for s in BOT_DETECTION_SITES:
                print(f"  - {s['name']}")
            return

    # Run tests
    results = await run_bot_detection_tests(args.profile, sites)

    # Print summary
    print_results_summary(results)

    # Save to file if requested
    if args.output:
        output_path = Path(args.output)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
