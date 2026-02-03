"""
Human Commenter CLI - Full Anti-Fraud Workflow

Usage:
    python -m src.human_commenter --profile <id> --video <id> --comment "text" [--pin]

Examples:
    # Add comment and pin (full workflow)
    python -m src.human_commenter --profile j5yrx8v --video dQw4w9WgXcQ --comment "Great video!" --pin

    # Add comment only (no pin)
    python -m src.human_commenter --profile j5yrx8v --video dQw4w9WgXcQ --comment "Nice!"

    # With safety checks
    python -m src.human_commenter --profile j5yrx8v --video abc123 --comment "Hello" --pin --region US --timezone America/New_York

Workflow phases:
    1. SAFETY_CHECK    - Verify IP/timezone match expected
    2. CONSUMPTION     - Watch video (45-120s) with human behaviors
    3. RESEARCH        - Scroll to comments, read existing
    4. INTERACTION     - Type comment with typos & corrections
    5. FINALIZATION    - Pin comment in YouTube Studio (if --pin)
    6. NATURAL_EXIT    - Surf Shorts, clean exit
"""

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

from .commenter import HumanCommenter
from .config import CommenterConfig
from .safety.logger import get_logger, configure_logging
from .safety.analytics_logger import init_analytics, close_analytics

logger = get_logger(__name__)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Human Commenter - Full Anti-Fraud YouTube Comment Automation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --profile j5yrx8v --video dQw4w9WgXcQ --comment "Great video!" --pin
  %(prog)s --profile j5yrx8v --video abc123 --comment "Nice content!" --region US
        """
    )

    # Required arguments
    parser.add_argument(
        "--profile", "-p",
        required=True,
        help="AdsPower profile ID (e.g., j5yrx8v)"
    )
    parser.add_argument(
        "--video", "-v",
        required=True,
        help="YouTube video ID (e.g., dQw4w9WgXcQ) or full URL"
    )
    parser.add_argument(
        "--comment", "-c",
        required=True,
        help="Comment text to post"
    )

    # Optional arguments
    parser.add_argument(
        "--pin",
        action="store_true",
        default=False,
        help="Pin the comment after posting (requires channel ownership)"
    )
    parser.add_argument(
        "--region",
        help="Expected IP region for safety check (e.g., US, DE, UA)"
    )
    parser.add_argument(
        "--timezone",
        help="Expected timezone for safety check (e.g., America/New_York)"
    )
    parser.add_argument(
        "--keywords",
        nargs="+",
        help="Keywords for entropy search actions"
    )
    parser.add_argument(
        "--no-natural-exit",
        action="store_true",
        default=False,
        help="Skip natural exit (Shorts surfing)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Enable debug logging"
    )

    return parser.parse_args()


def extract_video_id(video_input: str) -> str:
    """
    Extract video ID from URL or return as-is if already ID.

    Supports:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://www.youtube.com/shorts/VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - VIDEO_ID (direct)
    """
    video_input = video_input.strip()

    # Already an ID (11 chars, no slashes)
    if len(video_input) == 11 and "/" not in video_input and "?" not in video_input:
        return video_input

    # YouTube watch URL
    if "youtube.com/watch" in video_input and "v=" in video_input:
        try:
            return video_input.split("v=")[1].split("&")[0][:11]
        except IndexError:
            pass

    # YouTube Shorts URL
    if "youtube.com/shorts/" in video_input:
        try:
            return video_input.split("/shorts/")[1].split("?")[0][:11]
        except IndexError:
            pass

    # youtu.be short URL
    if "youtu.be/" in video_input:
        try:
            return video_input.split("youtu.be/")[1].split("?")[0][:11]
        except IndexError:
            pass

    # Return as-is (might be valid ID)
    return video_input[:11] if len(video_input) >= 11 else video_input


async def run_workflow(args) -> int:
    """
    Run the full comment workflow.

    Returns:
        Exit code (0 = success, 1 = failure)
    """
    # Extract video ID
    video_id = extract_video_id(args.video)

    print("\n" + "=" * 70)
    print("HUMAN COMMENTER - FULL ANTI-FRAUD WORKFLOW")
    print("=" * 70)
    print(f"Profile:     {args.profile}")
    print(f"Video ID:    {video_id}")
    print(f"Comment:     {args.comment[:50]}{'...' if len(args.comment) > 50 else ''}")
    print(f"Pin:         {'Yes' if args.pin else 'No'}")
    print(f"Region:      {args.region or 'Not specified'}")
    print(f"Timezone:    {args.timezone or 'Not specified'}")
    print(f"Started:     {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # Initialize analytics with log directory
    log_dir = Path("logs/analytics")
    log_dir.mkdir(parents=True, exist_ok=True)

    analytics = init_analytics(
        profile_id=args.profile,
        log_dir=log_dir,
        enabled=True
    )
    if analytics and hasattr(analytics, '_log_path') and analytics._log_path:
        print(f"\n[Analytics] Log file: {analytics._log_path}")

    # Create config - IMPORTANT: disable force_viewport to prevent YouTube layout shift
    config = CommenterConfig()
    config.viewport.force_viewport = False  # Use real browser window size
    config._profile_id = args.profile  # Store for WatchHistory

    # Create commenter
    commenter = HumanCommenter(config)

    try:
        print("\n" + "-" * 70)
        print("WORKFLOW PHASES")
        print("-" * 70)

        if args.pin:
            # Full workflow with pin
            print("\n[1/6] Starting full workflow (comment + pin)...")
            result = await commenter.add_and_pin_comment(
                video_id=video_id,
                comment_text=args.comment,
                profile_id=args.profile,
                channel_keywords=args.keywords,
                expected_region=args.region,
                expected_timezone=args.timezone,
            )
        else:
            # Comment only (no pin)
            print("\n[1/5] Starting comment-only workflow...")
            result = await commenter.add_comment_only(
                video_id=video_id,
                comment_text=args.comment,
                profile_id=args.profile,
                channel_keywords=args.keywords,
                expected_region=args.region,
                expected_timezone=args.timezone,
            )

        # Print result
        print("\n" + "=" * 70)
        print("WORKFLOW RESULT")
        print("=" * 70)
        print(f"Success:         {'[OK] YES' if result.success else '[FAIL] NO'}")
        print(f"State reached:   {result.state_reached.value}")
        print(f"Comment posted:  {'[OK] Yes' if result.comment_posted else '[FAIL] No'}")
        print(f"Comment pinned:  {'[OK] Yes' if result.comment_pinned else '[FAIL] No'}")
        print(f"Duration:        {result.duration_seconds:.1f} seconds")

        if result.error:
            print(f"Error:           {result.error}")

        print("=" * 70 + "\n")

        return 0 if result.success else 1

    except KeyboardInterrupt:
        print("\n\n[!] Workflow interrupted by user")
        return 130

    except Exception as e:
        logger.exception(f"Workflow failed: {e}")
        print(f"\n[ERROR] {e}")
        return 1

    finally:
        # Close analytics
        if analytics:
            close_analytics()
            print(f"[Analytics] Session saved")


def main():
    """Main entry point."""
    args = parse_args()

    # Configure logging
    configure_logging(log_sensitive=args.debug)

    if args.debug:
        print("[Debug mode enabled]")

    # Run async workflow
    exit_code = asyncio.run(run_workflow(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
