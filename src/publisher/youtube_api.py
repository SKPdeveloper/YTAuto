"""
YouTube API Wrapper for YTAutoPublisher

Handles OAuth authentication, video upload, and comment posting.
Supports proxy connections for each channel.
"""

import os
import time
import json
import httplib2
from pathlib import Path
from typing import Optional, Tuple, Callable
from datetime import datetime, timezone
from contextlib import contextmanager

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

    def _get_proxy_url(self) -> Optional[str]:
        """Get proxy URL with authentication if configured"""
        proxy = self.channel_config.proxy

        if proxy and proxy.enabled:
            if proxy.username and proxy.password:
                return f"http://{proxy.username}:{proxy.password}@{proxy.host}:{proxy.port}"
            else:
                return f"http://{proxy.host}:{proxy.port}"
        return None

    def _create_http_with_proxy(self):
        """
        Create HTTP client with proxy support.

        Uses a requests-based wrapper that's compatible with googleapiclient.
        """
        import requests

        proxy = self.channel_config.proxy

        if proxy and proxy.enabled:
            logger.info(f"Using proxy: {proxy.host}:{proxy.port}")
            proxy_url = self._get_proxy_url()

            # Create a custom Http class that uses requests with proxy
            class RequestsHttp:
                """httplib2-compatible wrapper around requests with proxy support"""

                def __init__(self, proxy_url):
                    self.session = requests.Session()
                    self.session.proxies = {
                        'http': proxy_url,
                        'https': proxy_url,
                    }
                    self.session.trust_env = False  # Don't use env proxies

                def request(self, uri, method="GET", body=None, headers=None,
                           redirections=5, connection_type=None):
                    """Make HTTP request - compatible with httplib2 interface"""
                    headers = headers or {}

                    try:
                        response = self.session.request(
                            method=method,
                            url=uri,
                            data=body,
                            headers=headers,
                            allow_redirects=redirections > 0,
                            timeout=300,
                        )

                        # Create httplib2-like response object
                        class HttpResponse(dict):
                            """httplib2-compatible response object"""

                            def __init__(self, resp):
                                # Initialize as dict with lowercase headers
                                super().__init__()
                                for key, value in resp.headers.items():
                                    self[key.lower()] = value

                                self.status = resp.status_code
                                self.reason = resp.reason

                        return HttpResponse(response), response.content

                    except requests.exceptions.RequestException as e:
                        raise httplib2.HttpLib2Error(str(e))

            return RequestsHttp(proxy_url)

        return httplib2.Http()

    @contextmanager
    def _proxy_env(self):
        """Context manager for proxy - kept for compatibility"""
        yield

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

    def run_oauth_flow(self, adspower_profile_id: Optional[str] = None) -> bool:
        """
        Run interactive OAuth flow.

        Opens browser for user to authorize access.
        If adspower_profile_id is provided, uses AdsPower browser instead of system default.

        Args:
            adspower_profile_id: AdsPower profile ID (e.g., 'j5yrx8v')

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

            if adspower_profile_id:
                # Use AdsPower browser for OAuth
                creds = self._run_oauth_with_adspower(flow, adspower_profile_id)
            else:
                # Use default system browser
                creds = flow.run_local_server(
                    port=0,
                    prompt="consent",
                    authorization_prompt_message="Please authorize in the browser...",
                )

            if creds:
                self._save_credentials(creds)
                self._credentials = creds
                logger.success("OAuth authorization successful")
                return True
            else:
                logger.error("OAuth flow did not return credentials")
                return False

        except Exception as e:
            logger.error(f"OAuth flow failed: {e}")
            return False

    def _run_oauth_with_adspower(
        self,
        flow: InstalledAppFlow,
        profile_id: str,
        base_url: str = "http://local.adspower.net:50325"
    ) -> Optional[Credentials]:
        """
        Run OAuth flow using AdsPower browser.

        Args:
            flow: OAuth flow instance
            profile_id: AdsPower profile ID
            base_url: AdsPower API base URL

        Returns:
            Credentials if successful, None otherwise
        """
        import httpx
        import socket
        import threading
        from wsgiref.simple_server import make_server, WSGIRequestHandler
        from urllib.parse import urlparse, parse_qs

        logger.info(f"Starting OAuth with AdsPower profile: {profile_id}")

        # Find available port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            port = s.getsockname()[1]

        redirect_uri = f"http://localhost:{port}/"
        flow.redirect_uri = redirect_uri

        # Generate authorization URL
        auth_url, state = flow.authorization_url(
            prompt="consent",
            access_type="offline",
        )

        logger.info(f"Authorization URL generated")
        logger.debug(f"URL: {auth_url}")

        # Storage for the authorization response
        auth_response = {"code": None, "error": None}

        # Simple WSGI app to capture the callback
        def wsgi_app(environ, start_response):
            query = parse_qs(environ.get('QUERY_STRING', ''))

            if 'code' in query:
                auth_response['code'] = query['code'][0]
                body = b"""
                <html><body style="font-family: Arial; text-align: center; padding: 50px;">
                <h1>Authorization Successful!</h1>
                <p>You can close this window and return to the terminal.</p>
                </body></html>
                """
            elif 'error' in query:
                auth_response['error'] = query.get('error', ['Unknown'])[0]
                body = f"""
                <html><body style="font-family: Arial; text-align: center; padding: 50px;">
                <h1>Authorization Failed</h1>
                <p>Error: {auth_response['error']}</p>
                </body></html>
                """.encode()
            else:
                body = b"Waiting for authorization..."

            start_response('200 OK', [
                ('Content-Type', 'text/html'),
                ('Content-Length', str(len(body)))
            ])
            return [body]

        # Silent request handler
        class SilentHandler(WSGIRequestHandler):
            def log_message(self, format, *args):
                pass

        # Start local server in background
        server = make_server('localhost', port, wsgi_app, handler_class=SilentHandler)
        server_thread = threading.Thread(target=server.handle_request)
        server_thread.daemon = True
        server_thread.start()

        logger.info(f"Callback server started on port {port}")

        # Start AdsPower profile and open URL
        try:
            with httpx.Client(timeout=60) as client:
                # Start browser profile
                start_resp = client.get(f"{base_url}/api/v1/browser/start?user_id={profile_id}")
                start_data = start_resp.json()

                if start_data.get("code") != 0:
                    logger.error(f"Failed to start AdsPower profile: {start_data.get('msg')}")
                    return None

                selenium_addr = start_data["data"]["ws"]["selenium"]
                webdriver_path = start_data["data"]["webdriver"]

                logger.info("AdsPower browser started, connecting Selenium...")

                # Connect Selenium and navigate to auth URL
                from selenium import webdriver
                from selenium.webdriver.chrome.service import Service
                from selenium.webdriver.chrome.options import Options

                chrome_options = Options()
                chrome_options.add_experimental_option("debuggerAddress", selenium_addr)
                service = Service(executable_path=webdriver_path)
                driver = webdriver.Chrome(service=service, options=chrome_options)

                logger.info("Opening authorization page in AdsPower browser...")
                driver.get(auth_url)

                # Wait for authorization (max 5 minutes)
                logger.info("Waiting for user to authorize in browser...")
                logger.info("Please complete the authorization in the browser window.")

                timeout = 300  # 5 minutes
                start_time = time.time()

                while auth_response['code'] is None and auth_response['error'] is None:
                    if time.time() - start_time > timeout:
                        logger.error("Authorization timeout")
                        return None
                    time.sleep(1)

                # Close browser tab (optional - keep profile open)
                # driver.quit()

        except Exception as e:
            logger.error(f"AdsPower OAuth error: {e}")
            return None

        finally:
            server.server_close()

        if auth_response['error']:
            logger.error(f"Authorization error: {auth_response['error']}")
            return None

        if not auth_response['code']:
            logger.error("No authorization code received")
            return None

        # Exchange code for credentials
        logger.info("Exchanging authorization code for tokens...")
        try:
            flow.fetch_token(code=auth_response['code'])
            return flow.credentials
        except Exception as e:
            logger.error(f"Token exchange failed: {e}")
            return None

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

        proxy = self.channel_config.proxy

        if proxy and proxy.enabled:
            # Use custom http with proxy - need to handle auth manually
            self._http = self._create_http_with_proxy()

            # Create authorized http wrapper
            from google_auth_httplib2 import AuthorizedHttp

            # Wrap our custom http with authorization
            class AuthorizedRequestsHttp:
                """Wrapper that adds auth headers to our requests-based http"""

                def __init__(self, credentials, base_http):
                    self.credentials = credentials
                    self.base_http = base_http

                def request(self, uri, method="GET", body=None, headers=None,
                           redirections=5, connection_type=None):
                    headers = dict(headers) if headers else {}

                    # Add authorization header
                    if self.credentials.token:
                        headers['Authorization'] = f'Bearer {self.credentials.token}'

                    return self.base_http.request(
                        uri, method=method, body=body, headers=headers,
                        redirections=redirections, connection_type=connection_type
                    )

            authorized_http = AuthorizedRequestsHttp(self._credentials, self._http)

            # Build YouTube service with authorized proxy http
            self._youtube = build(
                "youtube",
                "v3",
                http=authorized_http,
            )
        else:
            # No proxy - use standard credentials approach
            self._youtube = build(
                "youtube",
                "v3",
                credentials=self._credentials,
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
            with self._proxy_env():
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
            with self._proxy_env():
                youtube = self.get_youtube_client()

                # Build request body
                body = {
                    "snippet": {
                        "title": title[:100],  # YouTube limit
                        "description": description[:5000],  # YouTube limit
                        "tags": (tags or [])[:500],  # YouTube limit
                        "categoryId": category_id,
                        "defaultLanguage": "en-US",  # English (United States)
                        "defaultAudioLanguage": "en-US",  # English (United States)
                    },
                    "status": {
                        "privacyStatus": privacy_status.value if isinstance(privacy_status, PrivacyStatus) else privacy_status,
                        "selfDeclaredMadeForKids": made_for_kids,
                        "containsSyntheticMedia": True,  # Altered content = Yes
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
            with self._proxy_env():
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
        import requests as req

        details = {
            "proxy_ok": False,
            "auth_ok": False,
            "channel_info": None,
            "error": None,
        }

        try:
            # Test proxy connection
            proxy_url = self._get_proxy_url()
            if proxy_url:
                proxies = {"http": proxy_url, "https": proxy_url}
                response = req.get("https://www.googleapis.com/", proxies=proxies, timeout=15)
                details["proxy_ok"] = response.status_code < 500
            else:
                details["proxy_ok"] = True

            # Test authentication
            if self.authenticate():
                details["auth_ok"] = True

                # Get channel info (uses proxy via _proxy_env context)
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
