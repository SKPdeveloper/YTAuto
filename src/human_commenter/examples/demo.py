"""
Human Commenter v2.0 - Demo Script

Demonstrates the HumanBrowser interface with realistic human behavior.

Usage:
    python -m src.human_commenter.examples.demo

Requirements:
    - playwright install chromium
"""

import asyncio
from playwright.async_api import async_playwright

# Import from human_commenter
from src.human_commenter import (
    HumanBrowser,
    HumanBrowserConfig,
    ViewportPool,
    ProfileSeedGenerator,
    BimodalDelay,
)


async def demo_basic_interactions():
    """Demo basic HumanBrowser interactions."""
    print("\n" + "=" * 60)
    print("Human Commenter v2.0 - Demo")
    print("=" * 60)

    profile_id = "demo_profile_001"

    # Show profile configuration
    print(f"\n[1] Profile Configuration for '{profile_id}':")
    print("-" * 40)

    seed_gen = ProfileSeedGenerator(profile_id)
    print(f"    Seed Generator: {seed_gen}")
    print(f"    Behavior seed (mouse): {seed_gen.get_behavior_seed('mouse')}")
    print(f"    Behavior seed (keyboard): {seed_gen.get_behavior_seed('keyboard')}")

    viewport = ViewportPool.get_for_profile(profile_id)
    print(f"    Viewport: {viewport[0]}x{viewport[1]}")

    # Show bimodal delay demo
    print(f"\n[2] BimodalDelay Demo:")
    print("-" * 40)

    delay = BimodalDelay.for_typing()
    print(f"    Config: {delay}")

    samples = []
    for _ in range(10):
        value, mode = delay.sample()
        samples.append((value, mode.value))

    print(f"    Samples: {[(f'{v:.3f}s', m) for v, m in samples[:5]]}")
    auto_count = sum(1 for _, m in samples if m == 'automatic')
    print(f"    Mode distribution: {auto_count}/10 automatic")

    # Launch browser
    print(f"\n[3] Browser Automation Demo:")
    print("-" * 40)

    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(
            headless=False,
            slow_mo=50  # Slow down for visibility
        )

        context = await browser.new_context(
            viewport={"width": viewport[0], "height": viewport[1]}
        )
        page = await context.new_page()

        # Configure HumanBrowser
        config = HumanBrowserConfig(
            profile_id=profile_id,
            typing_error_rate=0.08,  # 8% typo chance for demo
            hover_before_click_chance=0.5,
        )

        print(f"    Launching HumanBrowser...")
        print(f"    - Profile: {config.profile_id}")
        print(f"    - Typo rate: {config.typing_error_rate:.0%}")
        print(f"    - Hover chance: {config.hover_before_click_chance:.0%}")

        async with HumanBrowser(page, config) as human:
            # Navigate to example page
            print(f"\n    Navigating to example.com...")
            await page.goto("https://example.com")
            await human.navigation_delay()

            # Show profile info
            info = human.get_profile_info()
            print(f"\n    Profile Info:")
            print(f"    - Scroll device: {info['scroll_device']['type']}")
            print(f"    - Typo weights: {info['typo_weights']}")

            # Demonstrate scrolling
            print(f"\n    Scrolling down...")
            scrolled = await human.scroll_down(300)
            print(f"    - Scrolled: {scrolled}px")

            await human.action_delay()

            # Scroll back up
            print(f"    Scrolling up...")
            scrolled = await human.scroll_up(200)
            print(f"    - Scrolled: {scrolled}px")

            await human.action_delay()

            # Demonstrate hover
            print(f"\n    Hovering over link...")
            await human.hover("a", duration=1.0)

            await human.action_delay()

            # Demonstrate click
            print(f"    Clicking link...")
            await human.click("a")

            # Wait to see result
            await human.wait(2, 3)

            print(f"\n    Demo complete!")

        await browser.close()

    print("\n" + "=" * 60)
    print("Demo finished successfully!")
    print("=" * 60 + "\n")


async def demo_typing():
    """Demo typing with typos and corrections."""
    print("\n" + "=" * 60)
    print("Typing Demo - Watch for typos and corrections!")
    print("=" * 60)

    profile_id = "typing_demo_profile"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=30)

        viewport = ViewportPool.get_for_profile(profile_id)
        context = await browser.new_context(
            viewport={"width": viewport[0], "height": viewport[1]}
        )
        page = await context.new_page()

        config = HumanBrowserConfig(
            profile_id=profile_id,
            typing_error_rate=0.15,  # 15% for visible demo
        )

        async with HumanBrowser(page, config) as human:
            # Go to a page with input
            await page.goto("https://www.google.com")
            await human.navigation_delay()

            print("\n    Typing 'Hello World' with human-like behavior...")
            print("    (Watch for typos and corrections!)\n")

            # Type in search box
            await human.type_text(
                'textarea[name="q"], input[name="q"]',
                "Hello World this is a typing demonstration",
                clear_first=True
            )

            await human.wait(3, 4)

        await browser.close()

    print("\n    Typing demo complete!")


async def demo_scroll_devices():
    """Demo different scroll device behaviors."""
    print("\n" + "=" * 60)
    print("Scroll Device Demo")
    print("=" * 60)

    from src.human_commenter import ScrollNormalizer

    devices_found = {}

    # Find different devices by trying different seeds
    for seed in range(100):
        norm = ScrollNormalizer(profile_seed=seed)
        if norm.device_type not in devices_found:
            devices_found[norm.device_type] = seed
            print(f"\n    Device: {norm.device_type}")
            print(f"    - Seed: {seed}")
            print(f"    - Base delta: {norm.device.base_delta}")
            print(f"    - Noise range: {norm.device.noise_range}")

            # Show normalized deltas
            deltas = norm.normalize(300)
            print(f"    - 300px normalized to {len(deltas)} events")
            print(f"    - First 5 deltas: {deltas[:5]}")

        if len(devices_found) == 4:
            break

    print("\n    Scroll device demo complete!")


def main():
    """Run demos."""
    import sys

    demos = {
        "basic": demo_basic_interactions,
        "typing": demo_typing,
        "scroll": demo_scroll_devices,
    }

    if len(sys.argv) > 1:
        demo_name = sys.argv[1]
        if demo_name in demos:
            asyncio.run(demos[demo_name]())
        else:
            print(f"Unknown demo: {demo_name}")
            print(f"Available: {list(demos.keys())}")
    else:
        # Run basic demo by default
        asyncio.run(demo_basic_interactions())


if __name__ == "__main__":
    main()
