"""
Mouse Movement Visualization Test

Opens a local HTML page and demonstrates mouse movements using our biometric
algorithms. You can visually verify that paths look human.

Run with: python -m human_commenter.tests.test_mouse_visualization --profile YOUR_ADSPOWER_PROFILE_ID
"""

import asyncio
import argparse
import random
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
import threading

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from human_commenter.client import AdsPowerPlaywrightClient
from human_commenter.config import CommenterConfig
from human_commenter.biometrics import HumanMouse, HumanScroll, HumanKeyboard, GaussianDelay
from human_commenter.safety.logger import get_logger

logger = get_logger(__name__)


# Path to visualization HTML
VISUALIZATION_HTML = Path(__file__).parent / "visualization" / "mouse_path_test.html"


def start_local_server(port: int = 8765):
    """Start a simple HTTP server for the visualization page."""
    handler = SimpleHTTPRequestHandler
    server = HTTPServer(("localhost", port), handler)

    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()

    return server


async def run_bezier_test(mouse: HumanMouse, page, num_movements: int = 10):
    """
    Test Bezier curve mouse movements.

    Moves mouse between random points to demonstrate curved paths.
    """
    print("\n" + "="*50)
    print("TEST 1: Bezier Curve Mouse Movements")
    print("="*50)

    viewport = await page.viewport_size
    if not viewport:
        viewport = {"width": 1920, "height": 1080}

    for i in range(num_movements):
        # Random start and end points
        start_x = random.uniform(100, viewport["width"] - 100)
        start_y = random.uniform(100, viewport["height"] - 100)
        end_x = random.uniform(100, viewport["width"] - 100)
        end_y = random.uniform(100, viewport["height"] - 100)

        # Move to start
        await mouse.move_to(start_x, start_y)
        await asyncio.sleep(0.3)

        # Move to end (this uses Bezier curve)
        print(f"  Movement {i+1}: ({start_x:.0f}, {start_y:.0f}) -> ({end_x:.0f}, {end_y:.0f})")
        await mouse.move_to(end_x, end_y)

        await asyncio.sleep(0.5)

    print("✓ Bezier test complete - check browser for curved paths")


async def run_fitts_law_test(mouse: HumanMouse, page):
    """
    Test Fitts' Law timing.

    Moves to targets of different sizes/distances and measures timing.
    """
    print("\n" + "="*50)
    print("TEST 2: Fitts' Law Timing")
    print("="*50)

    viewport = await page.viewport_size
    if not viewport:
        viewport = {"width": 1920, "height": 1080}

    # Start position
    start_x, start_y = 100, viewport["height"] // 2
    await mouse.move_to(start_x, start_y)

    # Test different distances and sizes
    tests = [
        (200, 80, "Close, Large target"),
        (200, 20, "Close, Small target"),
        (600, 80, "Far, Large target"),
        (600, 20, "Far, Small target"),
    ]

    for distance, target_size, description in tests:
        # Reset to start
        await mouse.move_to(start_x, start_y)
        await asyncio.sleep(0.3)

        # Measure movement
        import time
        start_time = time.time()

        await mouse.move_to(
            start_x + distance,
            start_y,
            target_width=target_size,
            target_height=target_size
        )

        elapsed = (time.time() - start_time) * 1000  # ms

        print(f"  {description}: {elapsed:.0f}ms (D={distance}, W={target_size})")

        await asyncio.sleep(0.5)

    print("✓ Fitts' Law test complete - larger/closer targets should be faster")


async def run_tremor_test(mouse: HumanMouse, page):
    """
    Test micro-tremor during hover.

    Hovers at a point and shows subtle tremor movements.
    """
    print("\n" + "="*50)
    print("TEST 3: Micro-Tremor During Hover")
    print("="*50)

    viewport = await page.viewport_size
    center_x = viewport["width"] // 2
    center_y = viewport["height"] // 2

    # Move to center
    await mouse.move_to(center_x, center_y)

    print(f"  Hovering at center ({center_x}, {center_y}) with tremor for 5 seconds...")
    print("  Watch for subtle 1-2px jitter movements")

    await mouse.hover_with_tremor(center_x, center_y, duration=5.0)

    print("✓ Tremor test complete")


async def run_click_jitter_test(mouse: HumanMouse, page):
    """
    Test click position jitter.

    Clicks at the same target multiple times to show position variance.
    """
    print("\n" + "="*50)
    print("TEST 4: Click Position Jitter")
    print("="*50)

    viewport = await page.viewport_size
    target_x = viewport["width"] // 2
    target_y = viewport["height"] // 2

    print(f"  Clicking 20 times at ({target_x}, {target_y}) with jitter...")

    for i in range(20):
        await mouse.click_at(target_x, target_y, jitter_radius=5.0)
        await asyncio.sleep(0.2)

    print("✓ Click jitter test complete - clicks should form a cluster, not a single point")


async def run_typing_test(keyboard: HumanKeyboard, page):
    """
    Test keyboard typing with errors.

    Types text with occasional typos and corrections.
    """
    print("\n" + "="*50)
    print("TEST 5: Keyboard Typing with Errors")
    print("="*50)

    # Focus a text input (if available)
    test_text = "The quick brown fox jumps over the lazy dog. This is a test of human-like typing!"

    print(f"  Typing: {test_text}")
    print("  Watch for occasional typos and corrections...")

    # We need to find or create a text input
    # For visualization, we'll just type to the page (it won't show, but demonstrates the delays)
    await keyboard.type_text(test_text)

    print("✓ Typing test complete")


async def run_scroll_test(scroll: HumanScroll, page):
    """
    Test human-like scrolling.

    Scrolls down and up with variable speed.
    """
    print("\n" + "="*50)
    print("TEST 6: Human-Like Scrolling")
    print("="*50)

    print("  Scrolling down 500px...")
    await scroll.scroll_down(pixels=500)

    await asyncio.sleep(1)

    print("  Scrolling up 300px...")
    await scroll.scroll_up(pixels=300)

    await asyncio.sleep(1)

    print("  Scrolling to bottom...")
    await scroll.scroll_to_bottom(max_scrolls=5)

    await asyncio.sleep(1)

    print("  Scrolling to top...")
    await scroll.scroll_to_top()

    print("✓ Scroll test complete")


async def run_all_tests(profile_id: str, use_local_page: bool = True):
    """
    Run all visualization tests.
    """
    config = CommenterConfig()
    client = AdsPowerPlaywrightClient(config)

    try:
        await client.connect(profile_id)
        logger.info(f"Connected to AdsPower profile: {profile_id}")

        page = await client.get_page()

        # Navigate to visualization page or a blank page
        if use_local_page and VISUALIZATION_HTML.exists():
            # Start local server
            server = start_local_server(8765)
            url = f"file:///{VISUALIZATION_HTML.as_posix()}"
            print(f"\nOpening visualization page: {url}")
            await page.goto(url)
        else:
            # Use a simple test page
            await page.goto("about:blank")
            await page.set_content("""
                <html>
                <head><title>Mouse Test</title></head>
                <body style="background: #1a1a2e; min-height: 200vh;">
                    <h1 style="color: #fff; padding: 50px;">Mouse Movement Test</h1>
                    <input type="text" id="typing-test" style="width: 80%; padding: 20px; margin: 20px; font-size: 16px;" placeholder="Typing will appear here...">
                    <div style="height: 2000px;"></div>
                </body>
                </html>
            """)

        await asyncio.sleep(2)

        # Initialize biometrics
        mouse = HumanMouse(page, config)
        scroll = HumanScroll(page, config)
        keyboard = HumanKeyboard(page, config)

        # Set initial mouse position
        await mouse.set_position(100, 100)

        print("\n" + "="*60)
        print("HUMAN COMMENTER - BIOMETRICS VISUALIZATION TEST")
        print("="*60)
        print("\nWatch the browser window to see human-like movements.")
        print("Press Ctrl+C to stop at any time.\n")

        # Run tests
        await run_bezier_test(mouse, page)
        await asyncio.sleep(1)

        await run_fitts_law_test(mouse, page)
        await asyncio.sleep(1)

        await run_tremor_test(mouse, page)
        await asyncio.sleep(1)

        await run_click_jitter_test(mouse, page)
        await asyncio.sleep(1)

        await run_scroll_test(scroll, page)
        await asyncio.sleep(1)

        # Typing test - need to focus input first
        input_field = await page.query_selector("#typing-test, input[type='text']")
        if input_field:
            await input_field.focus()
            await run_typing_test(keyboard, page)

        print("\n" + "="*60)
        print("ALL TESTS COMPLETE")
        print("="*60)
        print("\nReview the browser window for visual verification.")
        print("The mouse movements should look natural and curved, not robotic.")
        print("\nPress Enter to close...")
        input()

    except KeyboardInterrupt:
        print("\nTest interrupted by user")

    finally:
        await client.disconnect()


async def main():
    parser = argparse.ArgumentParser(description="Mouse movement visualization test")
    parser.add_argument("--profile", "-p", required=True, help="AdsPower profile ID")
    parser.add_argument("--no-local", action="store_true", help="Don't use local HTML page")

    args = parser.parse_args()

    await run_all_tests(args.profile, use_local_page=not args.no_local)


if __name__ == "__main__":
    asyncio.run(main())
