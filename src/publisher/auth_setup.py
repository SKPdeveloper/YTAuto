"""
OAuth Authorization Setup for YTAutoPublisher

Handles the one-time OAuth authorization flow.
Run this through ADS Power browser for proper fingerprinting.
"""

import sys
from pathlib import Path

# Ensure imports work
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.publisher.config_manager import get_config_manager
from src.publisher.youtube_api import YouTubeAPI


def run_authorization(channel_id: str) -> bool:
    """
    Run OAuth authorization for a channel.

    This opens a browser for the user to authorize access.
    Should be run in an ADS Power browser profile for proper fingerprinting.

    Args:
        channel_id: Channel ID to authorize

    Returns:
        True if authorization successful
    """
    config = get_config_manager()

    # Load channel config
    channel_config = config.load_channel_config(channel_id)
    if not channel_config:
        print(f"ERROR: Channel not found: {channel_id}")
        print(f"Run 'channel add {channel_id}' first.")
        return False

    # Check for client_secrets.json
    client_secrets_path = config.get_client_secrets_path(channel_id)
    if not client_secrets_path.exists():
        print(f"ERROR: client_secrets.json not found!")
        print(f"Please copy to: {client_secrets_path}")
        print()
        print("To get client_secrets.json:")
        print("1. Go to console.cloud.google.com (in ADS Power browser)")
        print("2. Create a project or select existing")
        print("3. Enable YouTube Data API v3")
        print("4. Create OAuth credentials (Desktop app)")
        print("5. Download the JSON file")
        return False

    # Create YouTube API client
    youtube = YouTubeAPI(
        channel_config=channel_config,
        client_secrets_path=client_secrets_path,
        token_path=config.get_token_path(channel_id),
    )

    print(f"\nAuthorizing channel: {channel_id}")
    print(f"Channel name: {channel_config.channel_name}")
    print()
    print("A browser window will open.")
    print("Please log in with the YouTube account and click 'Allow'.")
    print()

    # Run OAuth flow
    success = youtube.run_oauth_flow()

    if success:
        print("\n" + "=" * 50)
        print("SUCCESS! Channel authorized.")
        print("=" * 50)
        print()
        print(f"Token saved to: {config.get_token_path(channel_id)}")
        print()
        print("Test connection with:")
        print(f"  python -m src.publisher.main channel test {channel_id}")
        return True
    else:
        print("\n" + "=" * 50)
        print("FAILED! Authorization did not complete.")
        print("=" * 50)
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m src.publisher.auth_setup <channel_id>")
        print()
        print("Example:")
        print("  python -m src.publisher.auth_setup channel_001")
        sys.exit(1)

    channel_id = sys.argv[1]
    success = run_authorization(channel_id)
    sys.exit(0 if success else 1)
