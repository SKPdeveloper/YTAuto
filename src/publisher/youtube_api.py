"""
YouTube API Wrapper for YTAutoPublisher

Handles OAuth authentication, video upload, and comment posting.
Supports proxy connections for each channel.
"""

import os
import time
import json
import httplib2
import socks
from pathlib import Path
from typing import Optional, Tuple, Callable
from datetime import datetime, timezone

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

from loguru import logger

from .models import (
    ChannelConfig,
    ProxyConfig,
    OAuthToken,
    PrivacyStatus,
)


# OAuth scopes required for publishing
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


class YouTubeAPI:
    """
    YouTube Data API v3 wrapper.

    Handles:
    - OAuth authentication with proxy support
    - Video upload with progress callback
    - Pinned comment posting
    - Token refresh
    """

    def __init__(
        self,
        channel_config: ChannelConfig,
        client_secrets_path: Path,
        token_path: Path,
    ):
        """
        Initialize YouTube API client.

        Args:
            channel_config: Channel configuration with proxy settings
            client_secrets_path: Path to client_secrets.json
            token_path: Path to store/load OAuth token
        """
        self.channel_config = channel_config
        self.client_secrets_path = client_secrets_path
        self.token_path = token_path

        self._credentials: Optional[Credentials] = None
        self._youtube = None
        self._http = None

    # ========================================================================
    # PROXY SETUP
    # ========================================================================

    def _create_http_with_proxy(self) -> httplib2.Http:
        """Create httplib2.Http with proxy configuration"""
        proxy = self.channel_config.proxy

        if proxy and proxy.enabled:
            logger.info(f"Using proxy: {proxy.host}:{proxy.port}")

            # Create proxy info
            proxy_info = httplib2.ProxyInfo(
                proxy_type=socks.PROXY_TYPE_HTTP,
                proxy_host=proxy.host,
                proxy_port=proxy.port,
                proxy_user=proxy.username,
                proxy_pass=proxy.password,
            )

            return httplib2.Http(proxy_info=proxy_info)

        return httplib2.Http()

    # ========================================================================
    # OAUTH AUTHENTICATION
    # ========================================================================

    def _load_credentials(self) -> Optional[Credentials]:
        """Load credentials from token file"""
        if not self.token_path.exists():
            return None

        try:
            with open(self.token_path, "r") as f:
                token_data = json.load(f)

            creds = Credentials(
                token=token_data.get("token"),
                refresh_token=token_data.get("refresh_token"),
                token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
                client_id=token_data.get("client_id"),
                client_secret=token_data.get("client_secret"),
                scopes=token_data.get("scopes", SCOPES),
            )

            return creds

        except Exception as e:
            logger.error(f"Failed to load credentials: {e}")
            return None

    def _save_credentials(self, creds: Credentials) -> None:
        """Save credentials to token file"""
        token_data = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes,
            "expiry": creds.expiry.isoformat() if creds.expiry else None,
        }

        self.token_path.parent.mkdir(parents=True, exist_ok=True)

        with open(self.token_path, "w") as f:
            json.dump(token_data, f, indent=2)

        logger.debug(f"Credentials saved to {self.token_path}")

    def authenticate(self, force_refresh: bool = False) -> bool:
        """
        Authenticate with YouTube API.

        Loads existing token or triggers OAuth flow if needed.

        Args:
            force_refresh: Force token refresh even if valid

        Returns:
            True if authenticated successfully
        """
        creds = self._load_credentials()

        if creds:
            # Check if token needs refresh
            if creds.expired or force_refresh:
                if creds.refresh_token:
                    try:
                        logger.info("Refreshing OAuth token...")
                        creds.refresh(Request())
                        self._save_credentials(creds)
                        logger.success("Token refreshed successfully")
                    except Exception as e:
                        logger.error(f"Token refresh failed: {e}")
                        creds = None
                else:
                    logger.warning("No refresh token available")
                    creds = None

        if not creds:
            logger.error("No valid credentials. Run 'channel add' to authorize.")
            return False

        self._credentials = creds
        return True

    def run_oauth_flow(self) -> bool:
        """
        Run interactive OAuth flow.

        Opens browser for user to authorize access.

        Returns:
            True if authorization successful
        """
        if not self.client_secrets_path.exists():
            logger.error(f"client_secrets.json not found: {self.client_secrets_path}")
            return False

        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(self.client_secrets_path),
                scopes=SCOPES,
            )

            # Run local server to receive OAuth callback
            creds = flow.run_local_server(
                port=0,  # Random available port
                prompt="consent",
                authorization_prompt_message="Please authorize in the browser...",
            )

            self._save_credentials(creds)
            self._credentials = creds

            logger.success("OAuth authorization successful")
            return True

        except Exception as e:
            logger.error(f"OAuth flow failed: {e}")
            return False

    # ========================================================================
    # API CLIENT
    # ========================================================================

    def get_youtube_client(self):
        """
        Get authenticated YouTube API client.

        Returns:
            YouTube API service object
        """
        if self._youtube is not None:
            return self._youtube

        if not self._credentials:
            if not self.authenticate():
                raise Exception("Not authenticated")

        # Create HTTP with proxy
        self._http = self._create_http_with_proxy()

        # Build YouTube service
        self._youtube = build(
            "youtube",
            "v3",
            credentials=self._credentials,
            http=self._http,
        )

        return self._youtube

    # ========================================================================
    # CHANNEL INFO
    # ========================================================================

    def get_channel_info(self) -> Optional[dict]:
        """
        Get authenticated channel information.

        Returns:
            Channel info dict or None
        """
        try:
            youtube = self.get_youtube_client()

            response = youtube.channels().list(
                part="snippet,statistics",
                mine=True,
            ).execute()

            if response.get("items"):
                channel = response["items"][0]
                return {
                    "id": channel["id"],
                    "title": channel["snippet"]["title"],
                    "description": channel["snippet"].get("description", ""),
                    "subscribers": channel["statistics"].get("subscriberCount", "0"),
                    "videos": channel["statistics"].get("videoCount", "0"),
                    "views": channel["statistics"].get("viewCount", "0"),
                }

            return None

        except HttpError as e:
            logger.error(f"YouTube API error: {e}")
            return None

    # ========================================================================
    # VIDEO UPLOAD
    # ========================================================================

    def upload_video(
        self,
        video_path: Path,
        title: str,
        description: str,
        tags: list = None,
        category_id: str = "22",
        privacy_status: PrivacyStatus = PrivacyStatus.PUBLIC,
        scheduled_datetime: Optional[datetime] = None,
        made_for_kids: bool = False,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Upload video to YouTube.

        Args:
            video_path: Path to video file
            title: Video title
            description: Video description
            tags: List of tags
            category_id: YouTube category ID
            privacy_status: public/private/unlisted
            scheduled_datetime: For scheduled publish
            made_for_kids: COPPA compliance
            progress_callback: Callback(bytes_uploaded, total_bytes)

        Returns:
            Tuple of (success, video_id, error_message)
        """
        if not video_path.exists():
            return False, None, f"Video file not found: {video_path}"

        try:
            youtube = self.get_youtube_client()

            # Build request body
            body = {
                "snippet": {
                    "title": title[:100],  # YouTube limit
                    "description": description[:5000],  # YouTube limit
                    "tags": (tags or [])[:500],  # YouTube limit
                    "categoryId": category_id,
                },
                "status": {
                    "privacyStatus": privacy_status.value if isinstance(privacy_status, PrivacyStatus) else privacy_status,
                    "selfDeclaredMadeForKids": made_for_kids,
                },
            }

            # Handle scheduled publish
            if scheduled_datetime and privacy_status == PrivacyStatus.PRIVATE:
                body["status"]["publishAt"] = scheduled_datetime.astimezone(timezone.utc).isoformat()

            # Create media upload
            media = MediaFileUpload(
                str(video_path),
                chunksize=1024 * 1024,  # 1MB chunks
                resumable=True,
                mimetype="video/mp4",
            )

            # Create insert request
            request = youtube.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media,
            )

            logger.info(f"Uploading: {video_path.name}")
            logger.info(f"Title: {title}")

            # Execute with progress tracking
            response = None
            while response is None:
                status, response = request.next_chunk()

                if status and progress_callback:
                    progress_callback(
                        status.resumable_progress,
                        status.total_size or video_path.stat().st_size,
                    )

                if status:
                    progress_pct = int(status.progress() * 100)
                    logger.debug(f"Upload progress: {progress_pct}%")

            video_id = response.get("id")
            video_url = f"https://youtube.com/shorts/{video_id}"

            logger.success(f"Video uploaded: {video_id}")
            logger.info(f"URL: {video_url}")

            return True, video_id, None

        except HttpError as e:
            error_msg = str(e)

            # Parse specific error reasons
            if e.resp.status == 403:
                error_msg = "Quota exceeded or permission denied"
            elif e.resp.status == 400:
                error_msg = f"Invalid request: {e.error_details}"
            elif e.resp.status == 500:
                error_msg = "YouTube server error"

            logger.error(f"Upload failed: {error_msg}")
            return False, None, error_msg

        except Exception as e:
            logger.error(f"Upload error: {e}")
            return False, None, str(e)

    # ========================================================================
    # COMMENTS
    # ========================================================================

    def add_comment(
        self,
        video_id: str,
        comment_text: str,
        pin: bool = True,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Add comment to video and optionally pin it.

        Args:
            video_id: YouTube video ID
            comment_text: Comment text
            pin: Whether to pin the comment

        Returns:
            Tuple of (success, comment_id, error_message)
        """
        if not comment_text:
            logger.warning("No comment text provided, skipping")
            return True, None, None

        try:
            youtube = self.get_youtube_client()

            # Insert comment
            response = youtube.commentThreads().insert(
                part="snippet",
                body={
                    "snippet": {
                        "videoId": video_id,
                        "topLevelComment": {
                            "snippet": {
                                "textOriginal": comment_text,
                            }
                        }
                    }
                }
            ).execute()

            comment_id = response["snippet"]["topLevelComment"]["id"]
            logger.info(f"Comment added: {comment_id}")

            # Pin comment if requested (requires channel owner)
            # Note: YouTube API doesn't have direct "pin" - we use the UI for this
            # The comment will appear as the first one if posted by channel owner

            return True, comment_id, None

        except HttpError as e:
            error_msg = str(e)

            if e.resp.status == 403:
                error_msg = "Comments may be disabled on this video"
            elif e.resp.status == 404:
                error_msg = "Video not found"

            logger.error(f"Comment failed: {error_msg}")
            return False, None, error_msg

        except Exception as e:
            logger.error(f"Comment error: {e}")
            return False, None, str(e)

    # ========================================================================
    # CONNECTION TEST
    # ========================================================================

    def test_connection(self) -> Tuple[bool, dict]:
        """
        Test API connection and authentication.

        Returns:
            Tuple of (success, details_dict)
        """
        details = {
            "proxy_ok": False,
            "auth_ok": False,
            "channel_info": None,
            "error": None,
        }

        try:
            # Test proxy connection
            if self.channel_config.proxy and self.channel_config.proxy.enabled:
                http = self._create_http_with_proxy()
                response, content = http.request("https://www.googleapis.com/")
                details["proxy_ok"] = response.status < 500
            else:
                details["proxy_ok"] = True

            # Test authentication
            if self.authenticate():
                details["auth_ok"] = True

                # Get channel info
                channel_info = self.get_channel_info()
                if channel_info:
                    details["channel_info"] = channel_info
                else:
                    details["error"] = "Could not fetch channel info"
            else:
                details["error"] = "Authentication failed"

            success = details["proxy_ok"] and details["auth_ok"] and details["channel_info"]
            return success, details

        except Exception as e:
            details["error"] = str(e)
            return False, details
