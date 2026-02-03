"""
Profile Warmup Test - Full Anti-Fraud Mechanics

Tests ALL anti-fraud mechanisms in human_commenter:
- HumanMouse: Bezier curves, Fitts' Law, tremor, overshoot, spiral
- HumanKeyboard: Bimodal delays, 5 typo types, corrections
- HumanScroll: Device normalization, overshoot
- DistractedState: Window blur/focus simulation
- BimodalDelay: Automatic/deliberate modes
- PopupHandler: Dismiss YouTube popups
- VideoPlayer: Video interaction
- Analytics: Full event logging

Usage:
    python -m src.human_commenter.examples.test_warmup <profile_id> [video_id]

Example:
    python -m src.human_commenter.examples.test_warmup j5yrx8v
    python -m src.human_commenter.examples.test_warmup j5yrx8v dQw4w9WgXcQ
"""

import asyncio
import sys
import random
from pathlib import Path
from datetime import datetime

from src.human_commenter.client import AdsPowerPlaywrightClient
from src.human_commenter.config import CommenterConfig, ProfileSeedGenerator
from src.human_commenter.biometrics import (
    HumanMouse,
    HumanKeyboard,
    HumanScroll,
    BimodalDelay,
)
from src.human_commenter.biometrics.distraction import DistractedState
from src.human_commenter.entropy.random_actions import EntropyActions
from src.human_commenter.youtube.popup_handler import PopupHandler
from src.human_commenter.youtube.video_player import VideoPlayer
from src.human_commenter.safety.logger import get_logger
from src.human_commenter.safety.analytics_logger import (
    init_analytics,
    close_analytics,
    get_analytics,
)

logger = get_logger(__name__)

# Default videos for warmup
DEFAULT_VIDEOS = [
    "dQw4w9WgXcQ",  # Rick Astley
    "jNQXAC9IVRw",  # First YouTube video
    "9bZkp7q19f0",  # Gangnam Style
]


async def warmup_profile(profile_id: str, video_id: str = None):
    """
    Full warmup with ALL anti-fraud mechanisms.
    """
    if not video_id:
        video_id = random.choice(DEFAULT_VIDEOS)

    print("\n" + "=" * 70)
    print("FULL ANTI-FRAUD WARMUP TEST")
    print("=" * 70)
    print(f"Profile ID: {profile_id}")
    print(f"Video ID: {video_id}")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print("=" * 70)

    # Setup analytics logging
    log_dir = Path("logs/analytics")
    log_dir.mkdir(parents=True, exist_ok=True)

    analytics = init_analytics(
        profile_id=profile_id,
        log_dir=log_dir,
        enabled=True
    )
    print(f"\n[1] Analytics initialized")
    print(f"    Log file: {analytics._log_path}")

    # Create config with profile-specific personality
    config = CommenterConfig()
    config.viewport.force_viewport = False
    config.randomize_for_profile(profile_id)

    # Show personality
    personality = config.get_personality_info()
    print(f"\n[2] Profile Personality:")
    print(f"    Seed: {personality['seed']}")
    print(f"    Wrong key chance: {personality['wrong_key_chance']:.3f}")
    print(f"    Inter-key delay: {personality['inter_key_delay_mean']:.3f}s")
    print(f"    Bezier variance: {personality['bezier_variance']:.3f}")

    # Seed generator for consistent behavior
    seed_gen = ProfileSeedGenerator(profile_id)
    print(f"    Behavior seed (mouse): {seed_gen.get_behavior_seed('mouse')}")
    print(f"    Behavior seed (keyboard): {seed_gen.get_behavior_seed('keyboard')}")
    print(f"    Behavior seed (scroll): {seed_gen.get_behavior_seed('scroll')}")

    client = AdsPowerPlaywrightClient(config)
    session_error = None

    try:
        # Connect
        print(f"\n[3] Connecting to AdsPower...")
        await client.connect(profile_id)
        print(f"    Connected!")

        page = await client.get_page()
        viewport = page.viewport_size or {"width": 1280, "height": 720}

        # Initialize ALL biometrics components
        print(f"\n[4] Initializing anti-fraud components...")

        mouse = HumanMouse(page, config)
        print(f"    HumanMouse: Bezier curves, Fitts' Law, tremor, overshoot, spiral")

        keyboard = HumanKeyboard(
            page, config,
            mouse=mouse,
            profile_seed=seed_gen.get_behavior_seed('keyboard')
        )
        print(f"    HumanKeyboard: 5 typo types, bimodal delays, corrections")
        print(f"      Typo weights: {keyboard.get_typo_stats()}")

        scroll = HumanScroll(page, config, profile_seed=seed_gen.get_behavior_seed('scroll'))
        scroll_info = scroll.get_device_info()
        print(f"    HumanScroll: Device={scroll_info['type']}, base_delta={scroll_info['base_delta']}")

        distraction = DistractedState(page, config)
        print(f"    DistractedState: Window blur/focus simulation")

        popup_handler = PopupHandler(page, mouse, config)
        print(f"    PopupHandler: YouTube popup dismissal")

        player = VideoPlayer(page, mouse, config, profile_seed=seed_gen.get_behavior_seed('video'))
        print(f"    VideoPlayer: Video interaction + Ad handling + Shorts Surfing")
        print(f"      Ad personality: sniper={player._ad_personality_weights['sniper']:.1%}, lazy={player._ad_personality_weights['lazy']:.1%}")
        print(f"      Shorts rewatch chance: {player._shorts_rewatch_chance:.1%}")
        print(f"      Shorts watch multiplier: {player._shorts_watch_multiplier_base:.2f}x")
        print(f"      Shorts patience: {player._shorts_patience:.2f}x")

        entropy = EntropyActions(page, mouse, scroll, keyboard, config)
        print(f"    EntropyActions: Organic exit, Shorts wandering")

        # Delays
        action_delay = BimodalDelay.for_clicks()
        nav_delay = BimodalDelay.for_navigation()
        reading_delay = BimodalDelay.for_reading()
        print(f"    BimodalDelay: clicks, navigation, reading modes")

        # Log profile characteristics
        profile_chars = {
            "mouse": mouse.get_profile_characteristics(),
            "scroll": scroll.get_device_info(),
            "bimodal": {
                "fast_probability": action_delay.config.fast_probability,
                "fast_mean_ms": round(action_delay.config.fast_mean * 1000, 1),
                "slow_mean_ms": round(action_delay.config.slow_mean * 1000, 1),
            },
            "keyboard": keyboard.get_typo_stats(),
            "video_player": {
                "ad_personality_weights": {
                    k: round(v, 3) for k, v in player._ad_personality_weights.items()
                },
                "shorts_rewatch_chance": round(player._shorts_rewatch_chance, 3),
                "shorts_watch_multiplier": round(player._shorts_watch_multiplier_base, 3),
                "shorts_scroll_weights": player._shorts_scroll_weights,
                "shorts_patience": round(player._shorts_patience, 3)
            }
        }
        analytics.log_profile_characteristics(profile_chars)
        print(f"\n[4.1] Profile characteristics logged")

        # ============================================================
        # WARMUP SEQUENCE
        # ============================================================

        # --- PHASE 1: YouTube Homepage ---
        print(f"\n[5] PHASE 1: YouTube Homepage")
        print("-" * 50)

        await page.goto("https://www.youtube.com")
        analytics.log_page_navigate("https://www.youtube.com")
        await nav_delay.wait(category="page_load")
        print(f"    Navigated to YouTube")

        # Dismiss popups (cookies, etc)
        await popup_handler.dismiss_all()
        print(f"    Popups dismissed")

        # Mouse movements with various behaviors
        print(f"    Mouse movements (Bezier + tremor)...")
        for i in range(4):
            x = random.randint(200, viewport["width"] - 200)
            y = random.randint(150, viewport["height"] - 150)

            # Move with Bezier curve
            await mouse.move_to(x, y, target_width=50, target_height=50)
            await action_delay.wait(category="mouse_move")

            # Sometimes hover with tremor
            if random.random() < 0.5:
                await mouse.hover_with_tremor(x, y, duration=random.uniform(0.3, 0.8))
            print(f"      Move #{i+1}: ({x}, {y})")

        # Scroll homepage with device-specific deltas
        print(f"    Scrolling homepage ({scroll_info['type']})...")
        for i in range(3):
            scrolled = await scroll.scroll_down(random.randint(250, 450))
            await reading_delay.wait(category="reading")
            print(f"      Scroll #{i+1}: {scrolled}px")

        # --- PHASE 2: Use Search (test keyboard) ---
        print(f"\n[6] PHASE 2: Search Test (Keyboard)")
        print("-" * 50)

        # Click search box
        search_selector = "input#search"
        try:
            search_box = await page.wait_for_selector(search_selector, timeout=5000)
            if search_box:
                box = await search_box.bounding_box()
                if box:
                    # Click with overshoot/spiral chance
                    await mouse.click_at(
                        box["x"] + box["width"] / 2,
                        box["y"] + box["height"] / 2,
                        use_overshoot=True,
                        use_spiral=random.random() < 0.3
                    )
                    await action_delay.wait(category="click")
                    print(f"    Clicked search box (overshoot/spiral enabled)")

                    # Type search query with typos and corrections
                    search_text = "music videos 2024"
                    print(f"    Typing: '{search_text}'")
                    print(f"    (Watch for typos and corrections!)")

                    await keyboard.type_text(search_text)
                    print(f"    Typing complete")

                    # Clear and don't search (just testing)
                    await keyboard.press_combo("Control", "a")
                    await asyncio.sleep(0.2)
                    await page.keyboard.press("Backspace")
                    print(f"    Search cleared")

        except Exception as e:
            print(f"    Search test skipped: {e}")

        # --- PHASE 3: Distraction Simulation ---
        print(f"\n[7] PHASE 3: Distraction Simulation")
        print("-" * 50)

        print(f"    Simulating user distraction (5-8 seconds)...")
        print(f"    - Cursor moves outside viewport")
        print(f"    - Window blur event triggered")
        print(f"    - Idle period")
        print(f"    - Window focus restored")

        await distraction.simulate_distraction(min_duration=5, max_duration=8)
        print(f"    Distraction complete, focus restored")

        # --- PHASE 4: Video Page ---
        print(f"\n[8] PHASE 4: Video Watching")
        print("-" * 50)

        video_url = f"https://www.youtube.com/watch?v={video_id}"
        await page.goto(video_url)
        analytics.log_page_navigate(video_url)
        await nav_delay.wait(category="page_load")
        print(f"    Navigated to video: {video_id}")

        # Dismiss video popups
        await popup_handler.dismiss_all()

        # Check for pre-roll ads
        print(f"    Checking for pre-roll ads...")
        ad_result = await player.check_and_skip_ads()
        if ad_result.get("ad_detected"):
            print(f"    Ad detected! Action: {ad_result.get('action')}, Personality: {ad_result.get('personality')}")

        # Wait for video
        if await player.wait_for_video_element(timeout=10):
            print(f"    Video element found")

            # Ensure playing
            await asyncio.sleep(2)
            if not await player.is_playing():
                await player.play()
                print(f"    Started playback")

            # Get video info
            state = await player.get_state()
            volume = await player.get_volume()
            print(f"    Video state: {state.value}, volume: {volume:.0%}")

            # Watch with behaviors + ad checking
            watch_duration = random.uniform(20, 35)
            print(f"    Watching for {watch_duration:.1f}s with human behaviors + ad detection...")

            start_time = asyncio.get_event_loop().time()
            behavior_log = []
            ads_handled = 0

            while asyncio.get_event_loop().time() - start_time < watch_duration:
                elapsed = asyncio.get_event_loop().time() - start_time

                # Check for mid-roll ads periodically
                if random.random() < 0.15:  # ~15% chance each loop
                    ad_result = await player.check_and_skip_ads()
                    if ad_result.get("ad_detected"):
                        ads_handled += 1
                        behavior_log.append(f"[{elapsed:.1f}s] ad_{ad_result.get('action')}")

                # Random behaviors
                if random.random() < 0.12:
                    behavior = random.choice([
                        "mouse_move", "small_scroll", "hover_player",
                        "volume_adjust", "check_title"
                    ])

                    if behavior == "mouse_move":
                        x = random.randint(200, viewport["width"] - 200)
                        y = random.randint(200, viewport["height"] - 200)
                        await mouse.move_to(x, y)
                        behavior_log.append(f"[{elapsed:.1f}s] mouse_move ({x},{y})")

                    elif behavior == "small_scroll":
                        direction = random.choice(["down", "up"])
                        pixels = random.randint(50, 120)
                        if direction == "down":
                            await scroll.scroll_down(pixels)
                        else:
                            await scroll.scroll_up(pixels)
                        behavior_log.append(f"[{elapsed:.1f}s] scroll_{direction} {pixels}px")

                    elif behavior == "hover_player":
                        x = viewport["width"] // 2 + random.randint(-100, 100)
                        y = 300 + random.randint(-30, 30)
                        await mouse.hover_with_tremor(x, y, duration=random.uniform(0.5, 1.2))
                        behavior_log.append(f"[{elapsed:.1f}s] hover_player")

                    elif behavior == "volume_adjust":
                        current_vol = await player.get_volume()
                        new_vol = max(0.2, min(1.0, current_vol + random.uniform(-0.15, 0.15)))
                        await player.set_volume(new_vol)
                        behavior_log.append(f"[{elapsed:.1f}s] volume {current_vol:.0%}->{new_vol:.0%}")

                    elif behavior == "check_title":
                        await scroll.scroll_up(random.randint(30, 60))
                        await asyncio.sleep(random.uniform(0.5, 1))
                        await scroll.scroll_down(random.randint(30, 60))
                        behavior_log.append(f"[{elapsed:.1f}s] check_title")

                await asyncio.sleep(1)

            print(f"    Behaviors performed: {len(behavior_log)}")
            for log in behavior_log[-5:]:  # Show last 5
                print(f"      {log}")
        else:
            print(f"    Video element not found, skipping player test")

        # --- PHASE 5: Comments Section ---
        print(f"\n[9] PHASE 5: Comments Browsing")
        print("-" * 50)

        # Scroll to comments
        print(f"    Scrolling to comments...")
        for i in range(5):
            scrolled = await scroll.scroll_down(random.randint(250, 400))
            await reading_delay.wait(category="scroll")

        # Browse comments
        print(f"    Browsing comments (15 seconds)...")
        browse_start = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - browse_start < 15:
            # Random scroll
            if random.random() < 0.6:
                await scroll.scroll_down(random.randint(80, 180))
            else:
                await scroll.scroll_up(random.randint(40, 100))

            # Mouse hover on comment area
            x = random.randint(300, 900)
            y = random.randint(400, 650)
            await mouse.move_to(x, y)

            # Sometimes hover with tremor (reading)
            if random.random() < 0.3:
                await mouse.hover_with_tremor(x, y, duration=random.uniform(1, 3))

            await reading_delay.wait(category="reading")

        # --- PHASE 6: Another Distraction ---
        print(f"\n[10] PHASE 6: Final Distraction")
        print("-" * 50)

        if random.random() < 0.5:
            print(f"    Random distraction triggered...")
            await distraction.simulate_distraction(min_duration=3, max_duration=6)
            print(f"    Distraction complete")
        else:
            print(f"    No distraction this time (50% chance)")

        # --- PHASE 7: Natural Exit (Shorts + Clean Close) ---
        print(f"\n[11] PHASE 7: Natural Exit Sequence")
        print("-" * 50)

        print(f"    Starting organic exit wandering (YouTube Shorts)...")
        print(f"    - Navigate to Shorts")
        print(f"    - Watch 2-3 shorts (15-40s each)")
        print(f"    - Like one short (personality-based chance)")

        try:
            success, shorts_watched = await entropy.organic_exit_wandering()
            if success:
                print(f"    Watched {shorts_watched} shorts")
            else:
                print(f"    Shorts wandering partially failed, watched {shorts_watched}")
        except Exception as e:
            print(f"    Shorts wandering error: {e}")

        # Clean exit
        print(f"\n    Performing clean exit...")
        print(f"    - Navigate to about:blank")
        print(f"    - Wait 5-10 seconds")
        await entropy.clean_exit()
        print(f"    Clean exit complete")

        # ============================================================
        # ANALYTICS SUMMARY
        # ============================================================
        stats = analytics.get_stats()
        print(f"\n" + "=" * 70)
        print("ANALYTICS SUMMARY")
        print("=" * 70)
        print(f"Session ID: {stats.get('session_id', 'N/A')}")
        print(f"Profile ID: {stats.get('profile_id', 'N/A')}")
        print(f"Total events: {stats.get('total_events', 0)}")
        print(f"Duration: {stats.get('duration_seconds', 0):.1f}s")
        print(f"Events/second: {stats.get('events_per_second', 0):.2f}")

        print(f"\nEvent breakdown:")
        event_counts = stats.get('event_counts', {})
        for event_type in sorted(event_counts.keys()):
            count = event_counts[event_type]
            print(f"    {event_type}: {count}")

        # Categorize events
        mouse_events = sum(v for k, v in event_counts.items() if 'mouse' in k)
        scroll_events = sum(v for k, v in event_counts.items() if 'scroll' in k)
        key_events = sum(v for k, v in event_counts.items() if 'key' in k or 'typo' in k or 'backspace' in k)
        delay_events = sum(v for k, v in event_counts.items() if 'delay' in k)
        session_events = sum(v for k, v in event_counts.items() if 'window' in k or 'session' in k or 'page' in k)

        print(f"\nBy category:")
        print(f"    Mouse: {mouse_events}")
        print(f"    Scroll: {scroll_events}")
        print(f"    Keyboard: {key_events}")
        print(f"    Delays: {delay_events}")
        print(f"    Session: {session_events}")

    except Exception as e:
        session_error = str(e)
        logger.exception(f"Warmup failed: {e}")
        print(f"\n    ERROR: {e}")
        import traceback
        traceback.print_exc()

    finally:
        print(f"\n[12] Closing session...")

        # Close analytics with error status if failed
        if session_error:
            close_analytics(error=session_error)
            print(f"    Analytics saved (with error status)")
        else:
            close_analytics()
            print(f"    Analytics saved (completed)")

        print(f"    Log file: {log_dir}")

        # Disconnect from browser
        print(f"    Disconnecting from AdsPower...")
        await client.disconnect()
        print(f"    Disconnected")

    print("\n" + "=" * 70)
    print("WARMUP TEST COMPLETE!")
    print("=" * 70 + "\n")


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m src.human_commenter.examples.test_warmup <profile_id> [video_id]")
        print("\nThis test exercises ALL anti-fraud mechanisms:")
        print("  - HumanMouse (Bezier, Fitts' Law, tremor, overshoot, spiral)")
        print("  - HumanKeyboard (5 typo types, bimodal delays)")
        print("  - HumanScroll (device normalization)")
        print("  - DistractedState (window blur/focus)")
        print("  - PopupHandler, VideoPlayer")
        print("  - Full analytics logging")
        print("\nExample:")
        print("    python -m src.human_commenter.examples.test_warmup j5yrx8v")
        sys.exit(1)

    profile_id = sys.argv[1]
    video_id = sys.argv[2] if len(sys.argv) > 2 else None

    asyncio.run(warmup_profile(profile_id, video_id))


if __name__ == "__main__":
    main()
