"""
YouTube DOM Selectors

Centralized selectors for YouTube elements, including Shadow DOM handling.
YouTube uses custom web components with Shadow DOM that require special handling.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class YouTubeSelectors:
    """
    Collection of CSS selectors for YouTube elements.

    Note: YouTube uses custom elements with Shadow DOM.
    Some selectors may need JavaScript evaluation to pierce shadow roots.
    """

    # =========================================================================
    # VIDEO PAGE
    # =========================================================================

    # Video player
    VIDEO_PLAYER = "video.html5-main-video"
    VIDEO_PLAYER_CONTAINER = "#movie_player"
    VIDEO_PLAYER_CONTROLS = ".ytp-chrome-bottom"

    # Video info
    VIDEO_TITLE = "h1.ytd-watch-metadata yt-formatted-string"
    VIDEO_TITLE_ALT = "#title h1"
    CHANNEL_NAME = "#channel-name a"
    CHANNEL_AVATAR = "#owner #avatar"

    # Player controls
    PLAY_BUTTON = ".ytp-play-button"
    MUTE_BUTTON = ".ytp-mute-button"
    VOLUME_SLIDER = ".ytp-volume-slider-handle"
    FULLSCREEN_BUTTON = ".ytp-fullscreen-button"
    SETTINGS_BUTTON = ".ytp-settings-button"
    QUALITY_MENU_ITEM = ".ytp-menuitem[role='menuitemradio']"

    # Progress bar
    PROGRESS_BAR = ".ytp-progress-bar"
    CURRENT_TIME = ".ytp-time-current"
    DURATION = ".ytp-time-duration"

    # =========================================================================
    # COMMENTS SECTION
    # =========================================================================

    # Comment section container
    COMMENTS_SECTION = "#comments"
    COMMENTS_HEADER = "#comments #header"
    COMMENT_COUNT = "#comments #count yt-formatted-string"

    # Comment input
    COMMENT_INPUT_BOX = "#placeholder-area"  # Click to focus
    COMMENT_INPUT_FOCUSED = "#contenteditable-root"  # Actual input after focus
    COMMENT_INPUT_SIMPLE = "#simplebox-placeholder"

    # Comment submit
    COMMENT_SUBMIT_BUTTON = "#submit-button"
    COMMENT_SUBMIT_ENABLED = "#submit-button:not([disabled])"

    # Individual comments
    COMMENT_THREAD = "ytd-comment-thread-renderer"
    COMMENT_CONTENT = "#content-text"
    COMMENT_AUTHOR = "#author-text"
    COMMENT_TIMESTAMP = "#published-time-text"
    COMMENT_LIKES = "#vote-count-middle"
    COMMENT_REPLY_BUTTON = "#reply-button-end button"
    COMMENT_ACTION_MENU = "#action-menu"
    COMMENT_MORE_BUTTON = "#more-button"  # "Read more" on long comments

    # Sorting
    SORT_BUTTON = "#sort-menu tp-yt-paper-button"
    SORT_TOP_COMMENTS = "tp-yt-paper-listbox tp-yt-paper-item:nth-child(1)"
    SORT_NEWEST_FIRST = "tp-yt-paper-listbox tp-yt-paper-item:nth-child(2)"

    # =========================================================================
    # YOUTUBE STUDIO
    # =========================================================================

    # Studio navigation
    STUDIO_CONTENT_TAB = "#menu-item-1"  # Content tab
    STUDIO_COMMENTS_TAB = "#menu-item-4"  # Comments tab

    # Video row in content
    STUDIO_VIDEO_ROW = "ytcp-video-row"
    STUDIO_VIDEO_TITLE = "#video-title"
    STUDIO_VIDEO_THUMBNAIL = "#thumbnail-preview"

    # Comments in Studio
    STUDIO_COMMENT_ITEM = "ytcp-comment-thread"
    STUDIO_COMMENT_TEXT = "#body #content"
    STUDIO_COMMENT_MENU = "#overflow-menu-button"

    # Comment actions in Studio
    STUDIO_PIN_BUTTON = "tp-yt-paper-item:has-text('Pin')"
    STUDIO_PIN_BUTTON_ALT = "[test-id='pin-button']"
    STUDIO_UNPIN_BUTTON = "tp-yt-paper-item:has-text('Unpin')"
    STUDIO_DELETE_BUTTON = "tp-yt-paper-item:has-text('Remove')"
    STUDIO_HEART_BUTTON = "tp-yt-paper-item:has-text('Heart')"

    # Studio dialogs
    STUDIO_CONFIRM_DIALOG = "ytcp-confirmation-dialog"
    STUDIO_CONFIRM_BUTTON = "#confirm-button"
    STUDIO_CANCEL_BUTTON = "#cancel-button"

    # =========================================================================
    # POPUPS & DIALOGS
    # =========================================================================

    # Cookie consent
    COOKIE_DIALOG = "ytd-consent-bump-v2-lightbox"
    COOKIE_ACCEPT_BUTTON = "button[aria-label*='Accept']"
    COOKIE_REJECT_BUTTON = "button[aria-label*='Reject']"

    # Premium upsell
    PREMIUM_DIALOG = "ytd-popup-container"
    PREMIUM_DISMISS = "yt-button-renderer[dialog-dismiss]"
    PREMIUM_CLOSE = "#dismiss-button"

    # Sign in prompt
    SIGNIN_DIALOG = "yt-upsell-dialog-renderer"
    SIGNIN_DISMISS = "#dismiss-button"

    # Generic dismiss
    DISMISS_BUTTON = "[aria-label='Dismiss']"
    CLOSE_BUTTON = "[aria-label='Close']"

    # =========================================================================
    # NAVIGATION
    # =========================================================================

    # Top bar
    YOUTUBE_LOGO = "#logo"
    SEARCH_BOX = "input#search"
    SEARCH_BUTTON = "#search-icon-legacy"
    VOICE_SEARCH = "#voice-search-button"

    # Side menu
    HOME_BUTTON = "a[title='Home']"
    SHORTS_BUTTON = "a[title='Shorts']"
    SUBSCRIPTIONS_BUTTON = "a[title='Subscriptions']"

    # User menu
    AVATAR_BUTTON = "#avatar-btn"
    USER_MENU = "tp-yt-iron-dropdown"

    # =========================================================================
    # SHORTS PAGE
    # =========================================================================

    SHORTS_PLAYER = "ytd-reel-video-renderer"
    SHORTS_VIDEO = "div#shorts-player video, ytd-shorts video, video"
    SHORTS_LIKE_BUTTON = "#like-button"
    SHORTS_DISLIKE_BUTTON = "#dislike-button"
    SHORTS_COMMENT_BUTTON = "#comments-button"
    SHORTS_SHARE_BUTTON = "#share-button"

    # =========================================================================
    # ADS (2025-2026 selectors)
    # =========================================================================

    # Skip buttons
    AD_SKIP_SELECTORS = [
        ".ytp-ad-skip-button",
        ".ytp-ad-skip-button-modern",
        ".ytp-skip-ad-button",
        "button.ytp-ad-skip-button",
        ".ytp-ad-skip-button-slot button",
        ".videoAdUiSkipButton",
        "button[id^='skip-button']",
        "[id*='skip'][id*='button']",
        ".ytp-ad-skip-button-text",
    ]

    # Overlay/banner ad close buttons
    AD_OVERLAY_CLOSE_SELECTORS = [
        ".ytp-ad-overlay-close-button",
        ".ytp-ad-overlay-close-container button",
        ".ytp-ad-overlay-close-container",
        "[aria-label='Close ad']",
    ]

    # Indicators that ad is playing
    AD_PLAYING_SELECTORS = [
        ".ad-showing",
        ".ytp-ad-player-overlay",
        ".ytp-ad-player-overlay-instream-info",
        ".ytp-ad-text",
        ".ytp-ad-preview-container",
        ".ytp-ad-message-container",
        "div.ytp-ad-module",
    ]

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    @staticmethod
    def video_url(video_id: str) -> str:
        """Get YouTube video URL"""
        return f"https://www.youtube.com/watch?v={video_id}"

    @staticmethod
    def shorts_url(video_id: str) -> str:
        """Get YouTube Shorts URL"""
        return f"https://www.youtube.com/shorts/{video_id}"

    @staticmethod
    def studio_url() -> str:
        """Get YouTube Studio URL"""
        return "https://studio.youtube.com"

    @staticmethod
    def studio_video_url(video_id: str) -> str:
        """Get YouTube Studio video edit URL"""
        return f"https://studio.youtube.com/video/{video_id}/edit"

    @staticmethod
    def studio_comments_url(video_id: str) -> str:
        """Get YouTube Studio comments URL for specific video"""
        return f"https://studio.youtube.com/video/{video_id}/comments"

    @staticmethod
    def channel_url(channel_id: str) -> str:
        """Get channel URL"""
        return f"https://www.youtube.com/channel/{channel_id}"


# Shadow DOM piercing selectors (require JavaScript execution)
SHADOW_DOM_SELECTORS = {
    "cookie_accept": """
        document.querySelector('ytd-consent-bump-v2-lightbox')
            ?.shadowRoot?.querySelector('button[aria-label*="Accept"]')
    """,
    "premium_dismiss": """
        document.querySelector('ytd-popup-container')
            ?.querySelector('yt-button-renderer[dialog-dismiss]')
    """,
}


async def get_shadow_element(page, selector_name: str):
    """
    Get element inside Shadow DOM using JavaScript.

    Args:
        page: Playwright page
        selector_name: Key from SHADOW_DOM_SELECTORS

    Returns:
        Element handle or None
    """
    if selector_name not in SHADOW_DOM_SELECTORS:
        return None

    js_code = SHADOW_DOM_SELECTORS[selector_name]
    return await page.evaluate_handle(js_code)
