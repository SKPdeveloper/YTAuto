"""
Human Commenter v2.0 - AdsPower Demo

Demonstrates HumanBrowser with AdsPower browser profile.

Usage:
    python -m src.human_commenter.examples.demo_adspower <profile_id>
    python -m src.human_commenter.examples.demo_adspower <profile_id> typing

Example:
    python -m src.human_commenter.examples.demo_adspower j5yrx8v
    python -m src.human_commenter.examples.demo_adspower j5yrx8v typing
"""

import asyncio
import sys

from src.human_commenter import (
    HumanBrowser,
    HumanBrowserConfig,
    CommenterConfig,
    ProfileSeedGenerator,
    ViewportPool,
)
from src.human_commenter.client import AdsPowerPlaywrightClient
from src.human_commenter.safety.logger import get_logger

logger = get_logger(__name__)


async def demo_with_adspower(profile_id: str):
    """Run demo with AdsPower profile."""
    print("\n" + "=" * 60)
    print(f"Human Commenter v2.0 - AdsPower Demo")
    print(f"Profile: {profile_id}")
    print("=" * 60)

    # Show profile configuration
    print(f"\n[1] Profile Configuration:")
    print("-" * 40)

    seed_gen = ProfileSeedGenerator(profile_id)
    print(f"    Seed Generator: {seed_gen}")

    viewport = ViewportPool.get_for_profile(profile_id)
    print(f"    Viewport: {viewport[0]}x{viewport[1]}")

    # Create config - disable force_viewport for real fullscreen
    config = CommenterConfig()
    config.viewport.force_viewport = False  # Use real window size
    config.randomize_for_profile(profile_id)

    personality = config.get_personality_info()
    print(f"    Personality seed: {personality['seed']}")
    print(f"    Wrong key chance: {personality['wrong_key_chance']:.3f}")
    print(f"    Bezier variance: {personality['bezier_variance']:.3f}")

    # Connect to AdsPower
    print(f"\n[2] Connecting to AdsPower...")
    print("-" * 40)

    client = AdsPowerPlaywrightClient(config)

    try:
        await client.connect(profile_id)
        print(f"    Connected!")

        page = await client.get_page()
        print(f"    Page ready")

        # Create HumanBrowser config
        browser_config = HumanBrowserConfig(
            profile_id=profile_id,
            typing_error_rate=0.08,
            hover_before_click_chance=0.5,
        )

        print(f"\n[3] Running Demo...")
        print("-" * 40)

        async with HumanBrowser(page, browser_config) as human:
            # Show profile info
            info = human.get_profile_info()
            print(f"    Scroll device: {info['scroll_device']['type']}")
            print(f"    Typo weights: {list(info['typo_weights'].keys())}")

            # Navigate to httpbin (neutral test site)
            print(f"\n    Navigating to httpbin.org...")
            await page.goto("https://httpbin.org/forms/post")
            await human.navigation_delay()

            # Scroll down
            print(f"    Scrolling down...")
            scrolled = await human.scroll_down(300)
            print(f"    - Scrolled: {scrolled}px")

            await human.action_delay()

            # Scroll up
            print(f"    Scrolling up...")
            scrolled = await human.scroll_up(150)
            print(f"    - Scrolled: {scrolled}px")

            await human.action_delay()

            # Move mouse around naturally
            print(f"\n    Moving mouse naturally...")
            for i in range(3):
                import random
                x = random.randint(200, 800)
                y = random.randint(200, 500)
                await human.mouse.move_to(x, y)
                await human.action_delay()
                print(f"    - Moved to ({x}, {y})")

            # Final wait
            await human.wait(2, 3)

            print(f"\n    Demo complete!")

    except Exception as e:
        logger.exception(f"Demo failed: {e}")
        print(f"\n    ERROR: {e}")

    finally:
        print(f"\n[4] Disconnecting...")
        await client.disconnect()
        print(f"    Disconnected")

    print("\n" + "=" * 60)
    print("Demo finished!")
    print("=" * 60 + "\n")


async def demo_typing_adspower(profile_id: str):
    """Demo typing with AdsPower profile on neutral site."""
    print("\n" + "=" * 60)
    print(f"Typing Demo - AdsPower Profile: {profile_id}")
    print("=" * 60)

    # Create config - disable force_viewport for real fullscreen
    config = CommenterConfig()
    config.viewport.force_viewport = False  # Use real window size
    config.randomize_for_profile(profile_id)

    client = AdsPowerPlaywrightClient(config)

    try:
        await client.connect(profile_id)
        page = await client.get_page()

        browser_config = HumanBrowserConfig(
            profile_id=profile_id,
            typing_error_rate=0.10,  # 10% for visible demo
        )

        async with HumanBrowser(page, browser_config) as human:
            # Go to httpbin forms page (neutral test site)
            print(f"\n    Navigating to httpbin.org/forms...")
            await page.goto("https://httpbin.org/forms/post")
            await human.navigation_delay()

            # Type in the "Customer name" field
            print(f"\n    Typing with human-like behavior...")
            print(f"    Text: '[emoji] Only one thing can put out this fire... spot the cure? [emoji]'")
            print(f"    (Watch for typos and corrections!)\n")

            # httpbin form has input with name="custname"
            input_selector = 'input[name="custname"]'

            success = await human.type_text(
                input_selector,
                "🥛 Only one thing can put out this fire... spot the cure? 👇",
                clear_first=True,
                timeout=10.0
            )

            if success:
                print(f"    - Typing complete!")
            else:
                print(f"    - Typing failed")

            # Also type in comments textarea
            print(f"\n    Typing in comments field...")
            textarea_selector = 'textarea[name="comments"]'

            success = await human.type_text(
                textarea_selector,
                "This is a test of human-like typing with natural mistakes and corrections.",
                clear_first=True,
                timeout=10.0
            )

            if success:
                print(f"    - Typing complete!")
            else:
                print(f"    - Typing failed")

            await human.wait(3, 4)

    except Exception as e:
        logger.exception(f"Demo failed: {e}")
        print(f"\n    ERROR: {e}")

    finally:
        await client.disconnect()

    print("\n    Typing demo complete!")


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m src.human_commenter.examples.demo_adspower <profile_id> [typing]")
        print("Example: python -m src.human_commenter.examples.demo_adspower j5yrx8v")
        print("         python -m src.human_commenter.examples.demo_adspower j5yrx8v typing")
        sys.exit(1)

    profile_id = sys.argv[1]
    demo_type = sys.argv[2] if len(sys.argv) > 2 else "basic"

    if demo_type == "typing":
        asyncio.run(demo_typing_adspower(profile_id))
    else:
        asyncio.run(demo_with_adspower(profile_id))


if __name__ == "__main__":
    main()
