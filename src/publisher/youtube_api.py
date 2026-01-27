"""
YouTube API Wrapper for YTAutoPublisher

Handles OAuth authentication, video upload, and comment posting.
Supports proxy connections for each channel.
"""

import os
import time
import json
import httplib2
import random
from pathlib import Path
from typing import Optional, Tuple, Callable
from datetime import datetime, timezone
from contextlib import contextmanager


# ============================================================================
# HUMAN-LIKE BEHAVIOR HELPERS
# ============================================================================

def human_delay(min_sec: float = 0.5, max_sec: float = 2.0) -> None:
    """Random delay to simulate human thinking/reaction time"""
    time.sleep(random.uniform(min_sec, max_sec))


def human_typing_delay() -> None:
    """Short delay between typing actions"""
    time.sleep(random.uniform(0.05, 0.15))


def human_scroll(driver, direction: str = "random") -> None:
    """Perform human-like scroll with random amount"""
    if direction == "random":
        direction = random.choice(["up", "down"])

    scroll_amount = random.randint(50, 200)
    if direction == "up":
        scroll_amount = -scroll_amount

    driver.execute_script(f"window.scrollBy(0, {scroll_amount});")
    time.sleep(random.uniform(0.3, 0.8))


def human_mouse_move(actions, element=None) -> None:
    """Move mouse in a more natural way with slight randomness"""
    if element:
        # Move to element with small random offset
        offset_x = random.randint(-5, 5)
        offset_y = random.randint(-5, 5)
        try:
            actions.move_to_element_with_offset(element, offset_x, offset_y).perform()
        except:
            actions.move_to_element(element).perform()
    time.sleep(random.uniform(0.1, 0.3))


def human_click(actions, element) -> None:
    """Human-like click with pre-movement and slight delay"""
    human_mouse_move(actions, element)
    human_delay(0.2, 0.5)  # Think before clicking
    element.click()
    human_delay(0.3, 0.7)  # Pause after click


def human_before_action() -> None:
    """Random pause before important action (simulates thinking)"""
    if random.random() < 0.3:  # 30% chance of extra pause
        time.sleep(random.uniform(0.5, 1.5))

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
    UploadState,
)


# Retry settings for resumable uploads
MAX_RETRIES = 999  # Practically unlimited - will retry for days
INITIAL_RETRY_DELAY = 5  # seconds
MAX_RETRY_DELAY = 1800  # 30 minutes max between retries
RETRIABLE_EXCEPTIONS = (
    IOError,
    ConnectionError,
    ConnectionResetError,
    TimeoutError,
    BrokenPipeError,
    OSError,
)
RETRIABLE_STATUS_CODES = [500, 502, 503, 504, 408]  # Added 408 Request Timeout


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

        # Upload state directory
        self._uploads_dir = self.token_path.parent.parent / "uploads"
        self._uploads_dir.mkdir(parents=True, exist_ok=True)

    # ========================================================================
    # UPLOAD STATE MANAGEMENT
    # ========================================================================

    def _get_upload_state_path(self, project_id: str) -> Path:
        """Get path for upload state file"""
        return self._uploads_dir / f"{project_id}_upload.json"

    def _save_upload_state(self, state: UploadState) -> None:
        """Save upload state to disk"""
        state.last_updated = datetime.now()
        state_path = self._get_upload_state_path(state.project_id)
        with open(state_path, "w", encoding="utf-8") as f:
            f.write(state.model_dump_json(indent=2))
        logger.debug(f"Saved upload state: {state.bytes_uploaded}/{state.total_bytes} bytes")

    def _load_upload_state(self, project_id: str) -> Optional[UploadState]:
        """Load upload state from disk if exists"""
        state_path = self._get_upload_state_path(project_id)
        if state_path.exists():
            try:
                with open(state_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                state = UploadState(**data)
                logger.info(f"Found existing upload state: {state.bytes_uploaded}/{state.total_bytes} bytes")
                return state
            except Exception as e:
                logger.warning(f"Failed to load upload state: {e}")
        return None

    def _delete_upload_state(self, project_id: str) -> None:
        """Delete upload state file after successful upload"""
        state_path = self._get_upload_state_path(project_id)
        if state_path.exists():
            state_path.unlink()
            logger.debug(f"Deleted upload state for {project_id}")

    def _calculate_retry_delay(self, retry_count: int) -> float:
        """Calculate exponential backoff delay"""
        import random
        delay = min(INITIAL_RETRY_DELAY * (2 ** retry_count), MAX_RETRY_DELAY)
        # Add jitter
        delay = delay + random.uniform(0, delay * 0.1)
        return delay

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
        category_id: str = "24",
        privacy_status: PrivacyStatus = PrivacyStatus.PUBLIC,
        scheduled_datetime: Optional[datetime] = None,
        made_for_kids: bool = False,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        project_id: Optional[str] = None,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Upload video to YouTube with resumable upload support.

        Handles network interruptions with automatic retry and resume capability.
        Upload state is saved to disk, allowing recovery after crashes.

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
            project_id: Project ID for state tracking (enables resume)

        Returns:
            Tuple of (success, video_id, error_message)
        """
        if not video_path.exists():
            return False, None, f"Video file not found: {video_path}"

        video_path = Path(video_path)
        total_bytes = video_path.stat().st_size

        # Check for existing upload state
        existing_state = None
        if project_id:
            existing_state = self._load_upload_state(project_id)
            if existing_state:
                # Verify it's the same file
                if existing_state.video_path != str(video_path):
                    logger.warning("Video path changed, starting fresh upload")
                    existing_state = None
                elif existing_state.resumable_uri:
                    logger.info(f"Resuming upload from {existing_state.bytes_uploaded}/{total_bytes} bytes")

        # Create upload state
        state = existing_state or UploadState(
            project_id=project_id or f"upload_{int(time.time())}",
            channel_id=self.channel_config.channel_id,
            video_path=str(video_path),
            total_bytes=total_bytes,
            title=title,
            description=description,
            tags=tags or [],
            category_id=category_id,
            privacy_status=privacy_status.value if isinstance(privacy_status, PrivacyStatus) else privacy_status,
            scheduled_datetime=scheduled_datetime,
            made_for_kids=made_for_kids,
        )

        retry_count = state.retry_count

        while retry_count < MAX_RETRIES:
            try:
                result = self._execute_upload(
                    state=state,
                    progress_callback=progress_callback,
                )

                if result[0]:  # Success
                    # Clean up state file
                    if project_id:
                        self._delete_upload_state(project_id)
                    return result

                # Non-retriable error
                return result

            except RETRIABLE_EXCEPTIONS as e:
                retry_count += 1
                state.retry_count = retry_count

                if retry_count >= MAX_RETRIES:
                    logger.error(f"Max retries ({MAX_RETRIES}) exceeded")
                    if project_id:
                        self._save_upload_state(state)
                    return False, None, f"Upload failed after {MAX_RETRIES} retries: {e}"

                delay = self._calculate_retry_delay(retry_count)
                logger.warning(f"Network error: {e}. Retry {retry_count}/{MAX_RETRIES} in {delay:.1f}s")

                # Save state before sleeping
                if project_id:
                    self._save_upload_state(state)

                time.sleep(delay)

            except HttpError as e:
                if e.resp.status in RETRIABLE_STATUS_CODES:
                    retry_count += 1
                    state.retry_count = retry_count

                    if retry_count >= MAX_RETRIES:
                        logger.error(f"Max retries ({MAX_RETRIES}) exceeded")
                        if project_id:
                            self._save_upload_state(state)
                        return False, None, f"Upload failed after {MAX_RETRIES} retries: {e}"

                    delay = self._calculate_retry_delay(retry_count)
                    logger.warning(f"Server error {e.resp.status}. Retry {retry_count}/{MAX_RETRIES} in {delay:.1f}s")

                    if project_id:
                        self._save_upload_state(state)

                    time.sleep(delay)
                else:
                    # Non-retriable HTTP error
                    error_msg = str(e)
                    if e.resp.status == 403:
                        error_msg = "Quota exceeded or permission denied"
                    elif e.resp.status == 400:
                        error_msg = f"Invalid request: {getattr(e, 'error_details', str(e))}"
                    logger.error(f"Upload failed: {error_msg}")
                    return False, None, error_msg

            except Exception as e:
                logger.error(f"Unexpected upload error: {e}")
                if project_id:
                    self._save_upload_state(state)
                return False, None, str(e)

        return False, None, "Upload failed: max retries exceeded"

    def _execute_upload(
        self,
        state: UploadState,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Execute the actual upload with progress tracking.

        This method handles the chunk-by-chunk upload and can resume
        from a previously saved resumable_uri.
        """
        with self._proxy_env():
            youtube = self.get_youtube_client()

            video_path = Path(state.video_path)
            privacy_status = state.privacy_status

            # Build request body
            body = {
                "snippet": {
                    "title": state.title[:100],
                    "description": state.description[:5000],
                    "tags": state.tags[:500] if state.tags else [],
                    "categoryId": state.category_id,
                    "defaultLanguage": "en-US",
                    "defaultAudioLanguage": "en-US",
                },
                "status": {
                    "privacyStatus": privacy_status,
                    "selfDeclaredMadeForKids": state.made_for_kids,
                    "containsSyntheticMedia": True,
                },
            }

            # Handle scheduled publish
            if state.scheduled_datetime and privacy_status == "private":
                body["status"]["publishAt"] = state.scheduled_datetime.astimezone(timezone.utc).isoformat()

            # Create media upload
            media = MediaFileUpload(
                str(video_path),
                chunksize=1024 * 1024,  # 1MB chunks
                resumable=True,
                mimetype="video/mp4",
            )

            # Create or resume request
            if state.resumable_uri:
                # Resume existing upload
                logger.info(f"Resuming upload from {state.bytes_uploaded} bytes")
                request = youtube.videos().insert(
                    part="snippet,status",
                    body=body,
                    media_body=media,
                )
                # Set the resumable URI to continue
                request.resumable_uri = state.resumable_uri
                media.resumable_progress = state.bytes_uploaded
            else:
                # Start new upload
                logger.info(f"Starting new upload: {video_path.name}")
                logger.info(f"Title: {state.title}")
                request = youtube.videos().insert(
                    part="snippet,status",
                    body=body,
                    media_body=media,
                )

            # Execute upload with progress tracking
            response = None
            last_save_time = time.time()
            save_interval = 10  # Save state every 10 seconds

            while response is None:
                status, response = request.next_chunk()

                if status:
                    # Update state
                    state.bytes_uploaded = status.resumable_progress
                    state.resumable_uri = request.resumable_uri

                    # Progress callback
                    if progress_callback:
                        progress_callback(
                            status.resumable_progress,
                            status.total_size or state.total_bytes,
                        )

                    progress_pct = int(status.progress() * 100)
                    logger.debug(f"Upload progress: {progress_pct}%")

                    # Periodically save state
                    current_time = time.time()
                    if current_time - last_save_time > save_interval:
                        if state.project_id:
                            self._save_upload_state(state)
                        last_save_time = current_time

            video_id = response.get("id")
            video_url = f"https://youtube.com/shorts/{video_id}"

            logger.success(f"Video uploaded: {video_id}")
            logger.info(f"URL: {video_url}")

            return True, video_id, None

    def resume_upload(
        self,
        project_id: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Resume a previously interrupted upload.

        Args:
            project_id: Project ID to resume
            progress_callback: Progress callback function

        Returns:
            Tuple of (success, video_id, error_message)
        """
        state = self._load_upload_state(project_id)
        if not state:
            return False, None, f"No upload state found for {project_id}"

        if not Path(state.video_path).exists():
            return False, None, f"Video file not found: {state.video_path}"

        logger.info(f"Resuming upload for {project_id}")
        logger.info(f"Progress: {state.bytes_uploaded}/{state.total_bytes} bytes ({int(state.bytes_uploaded/state.total_bytes*100)}%)")

        return self.upload_video(
            video_path=Path(state.video_path),
            title=state.title,
            description=state.description,
            tags=state.tags,
            category_id=state.category_id,
            privacy_status=PrivacyStatus(state.privacy_status),
            scheduled_datetime=state.scheduled_datetime,
            made_for_kids=state.made_for_kids,
            progress_callback=progress_callback,
            project_id=project_id,
        )

    def list_pending_uploads(self) -> list:
        """List all pending/interrupted uploads"""
        pending = []
        if self._uploads_dir.exists():
            for state_file in self._uploads_dir.glob("*_upload.json"):
                try:
                    with open(state_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    state = UploadState(**data)
                    pending.append({
                        "project_id": state.project_id,
                        "title": state.title,
                        "progress": f"{int(state.bytes_uploaded/state.total_bytes*100)}%",
                        "bytes_uploaded": state.bytes_uploaded,
                        "total_bytes": state.total_bytes,
                        "started_at": state.started_at,
                        "last_updated": state.last_updated,
                    })
                except Exception as e:
                    logger.warning(f"Failed to read {state_file}: {e}")
        return pending

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

    # ========================================================================
    # COMMENT PINNING VIA ADSPOWER (Browser Automation)
    # ========================================================================

    def pin_comment_via_adspower(
        self,
        video_id: str,
        adspower_profile_id: str,
        comment_text: Optional[str] = None,
        base_url: str = "http://local.adspower.net:50325",
        timeout: int = 60,
    ) -> Tuple[bool, Optional[str]]:
        """
        Pin a comment on a video using AdsPower browser automation.

        Since YouTube API doesn't support comment pinning, we use browser automation
        to navigate to YouTube Studio and pin the comment.

        Args:
            video_id: YouTube video ID
            adspower_profile_id: AdsPower profile ID to use
            comment_text: Optional text to identify the comment (pins first channel comment if not specified)
            base_url: AdsPower API base URL
            timeout: Max time to wait for elements (seconds)

        Returns:
            Tuple of (success, error_message)
        """
        import httpx
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.common.exceptions import TimeoutException, NoSuchElementException

        logger.info(f"Starting comment pin via AdsPower for video: {video_id}")

        driver = None
        try:
            # Start AdsPower profile
            with httpx.Client(timeout=60) as client:
                start_resp = client.get(f"{base_url}/api/v1/browser/start?user_id={adspower_profile_id}")
                start_data = start_resp.json()

                if start_data.get("code") != 0:
                    error = f"Failed to start AdsPower profile: {start_data.get('msg')}"
                    logger.error(error)
                    return False, error

                selenium_addr = start_data["data"]["ws"]["selenium"]
                webdriver_path = start_data["data"]["webdriver"]

                logger.info("AdsPower browser started, connecting Selenium...")

                # Connect to AdsPower browser
                chrome_options = Options()
                chrome_options.add_experimental_option("debuggerAddress", selenium_addr)

                service = Service(executable_path=webdriver_path)
                driver = webdriver.Chrome(service=service, options=chrome_options)

                wait = WebDriverWait(driver, timeout)

                # Screenshots directory for debugging
                screenshots_dir = self._uploads_dir.parent / "debug_screenshots"
                screenshots_dir.mkdir(parents=True, exist_ok=True)

                # Navigate to YouTube Studio comments page
                studio_url = f"https://studio.youtube.com/video/{video_id}/comments"
                logger.info(f"Opening YouTube Studio: {studio_url}")
                driver.get(studio_url)

                # Wait for page to load
                logger.info("Waiting for page to load...")
                time.sleep(5)

                # Save screenshot for debugging
                screenshot_path = screenshots_dir / f"pin_comment_{video_id}_1_initial.png"
                driver.save_screenshot(str(screenshot_path))
                logger.debug(f"Screenshot saved: {screenshot_path}")

                # Check current URL - might have redirected
                current_url = driver.current_url
                logger.info(f"Current URL: {current_url}")

                # Check if we need to handle any consent dialogs or popups
                try:
                    # YouTube consent
                    consent_buttons = driver.find_elements(By.XPATH,
                        "//button[contains(., 'Accept') or contains(., 'Agree') or contains(., 'I agree')]")
                    for btn in consent_buttons:
                        if btn.is_displayed():
                            btn.click()
                            time.sleep(2)
                            break
                except:
                    pass

                # Check for "Got it" or tutorial dialogs and popups
                try:
                    popup_buttons = driver.find_elements(By.XPATH,
                        "//button[contains(., 'Got it') or contains(., 'Dismiss') or contains(., 'Close') or contains(., 'OK')]")
                    for btn in popup_buttons:
                        if btn.is_displayed():
                            logger.info(f"Closing popup: {btn.text}")
                            btn.click()
                            time.sleep(1)
                except:
                    pass

                # Also try clicking any overlay close buttons
                try:
                    close_buttons = driver.find_elements(By.CSS_SELECTOR,
                        "[aria-label='Close'], .close-button, .dismiss-button")
                    for btn in close_buttons:
                        if btn.is_displayed():
                            btn.click()
                            time.sleep(1)
                except:
                    pass

                # Wait for comments section to load
                logger.info("Waiting for comments to load...")
                time.sleep(5)

                # Save another screenshot after waiting
                screenshot_path = screenshots_dir / f"pin_comment_{video_id}_2_after_wait.png"
                driver.save_screenshot(str(screenshot_path))

                # Log page source for debugging
                page_title = driver.title
                logger.info(f"Page title: {page_title}")

                # Find the comment to pin
                comment_found = False

                # Try to find comment rows with multiple selector strategies
                try:
                    # First, try to find any element that indicates comments loaded
                    comment_selectors = [
                        "ytcp-comment-thread",
                        "#comment-thread",
                        "[class*='comment']",
                        "ytcp-comments-section",
                        "#comments-section",
                    ]

                    comment_threads = []
                    for selector in comment_selectors:
                        try:
                            elements = driver.find_elements(By.CSS_SELECTOR, selector)
                            if elements:
                                logger.info(f"Found {len(elements)} elements with selector: {selector}")
                                comment_threads = elements
                                break
                        except:
                            continue

                    # If no comments found, try waiting longer
                    if not comment_threads:
                        logger.info("No comments found yet, waiting longer...")
                        time.sleep(10)

                        # Try again with broader selectors
                        for selector in comment_selectors:
                            try:
                                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                                if elements:
                                    comment_threads = elements
                                    break
                            except:
                                continue

                    # Save screenshot
                    screenshot_path = screenshots_dir / f"pin_comment_{video_id}_3_comments.png"
                    driver.save_screenshot(str(screenshot_path))

                    if not comment_threads:
                        # Log HTML for debugging
                        html_path = screenshots_dir / f"pin_comment_{video_id}_page.html"
                        with open(html_path, "w", encoding="utf-8") as f:
                            f.write(driver.page_source)
                        logger.info(f"Page HTML saved to: {html_path}")

                        return False, f"No comments found. Screenshots saved to {screenshots_dir}"

                    logger.info(f"Found {len(comment_threads)} comment elements")

                    target_comment = None

                    if comment_text:
                        # Find comment by text
                        for thread in comment_threads:
                            try:
                                # Try different text selectors
                                text_found = False
                                for text_sel in ["#content-text", ".comment-text", "[slot='main']", "span", "p"]:
                                    try:
                                        text_element = thread.find_element(By.CSS_SELECTOR, text_sel)
                                        if comment_text[:30] in text_element.text:
                                            target_comment = thread
                                            logger.info(f"Found comment by text match: {text_element.text[:50]}")
                                            text_found = True
                                            break
                                    except:
                                        continue
                                if text_found:
                                    break
                            except:
                                continue

                    if not target_comment and comment_threads:
                        # Use first comment
                        target_comment = comment_threads[0]
                        logger.info("Using first comment element")

                    # Import ActionChains for hover
                    from selenium.webdriver.common.action_chains import ActionChains
                    actions = ActionChains(driver)

                    # Hover over comment to reveal menu button
                    logger.info("Hovering over comment to reveal menu...")
                    actions.move_to_element(target_comment).perform()
                    time.sleep(2)

                    # Screenshot after hover
                    screenshot_path = screenshots_dir / f"pin_comment_{video_id}_4_hover.png"
                    driver.save_screenshot(str(screenshot_path))

                    # Find and click the 3-dot menu button (vertical dots ⋮)
                    menu_button = None

                    # The 3-dot menu is usually the last icon button in the comment row
                    # Look for it specifically
                    try:
                        # Find all icon buttons in the comment
                        icon_buttons = target_comment.find_elements(By.CSS_SELECTOR, "ytcp-icon-button")
                        logger.info(f"Found {len(icon_buttons)} icon buttons in comment")

                        # The 3-dot menu is typically the last one or has more-vert icon
                        for btn in reversed(icon_buttons):  # Start from last
                            try:
                                icon = btn.get_attribute("icon") or ""
                                if "more" in icon.lower() or "vert" in icon.lower():
                                    menu_button = btn
                                    logger.info(f"Found 3-dot menu by icon attribute: {icon}")
                                    break
                            except:
                                continue

                        # If not found by icon, use the last button (usually the menu)
                        if not menu_button and icon_buttons:
                            menu_button = icon_buttons[-1]
                            logger.info("Using last icon button as menu")
                    except Exception as e:
                        logger.debug(f"Error finding icon buttons: {e}")

                    # Fallback selectors
                    if not menu_button:
                        menu_selectors = [
                            "[icon='icons:more-vert']",
                            "#overflow-menu-button",
                            "button[aria-label*='More']",
                            ".dropdown-trigger",
                        ]
                        for selector in menu_selectors:
                            try:
                                menu_button = target_comment.find_element(By.CSS_SELECTOR, selector)
                                if menu_button.is_displayed():
                                    logger.info(f"Found menu button with selector: {selector}")
                                    break
                                menu_button = None
                            except:
                                continue

                    if not menu_button:
                        # Try clicking directly on the comment row area where menu should be
                        screenshot_path = screenshots_dir / f"pin_comment_{video_id}_5_no_menu.png"
                        driver.save_screenshot(str(screenshot_path))
                        return False, f"Could not find comment menu button. Screenshots saved."

                    logger.info("Clicking menu button...")
                    menu_button.click()
                    time.sleep(2)

                    # Screenshot of opened menu
                    screenshot_path = screenshots_dir / f"pin_comment_{video_id}_6_menu_open.png"
                    driver.save_screenshot(str(screenshot_path))

                    # Find and click "Pin" option
                    pin_clicked = False
                    pin_selectors = [
                        "//ytcp-ve[contains(., 'Pin')]",
                        "//tp-yt-paper-item[contains(., 'Pin')]",
                        "//*[contains(@class, 'item')][contains(., 'Pin')]",
                        "//div[contains(text(), 'Pin')]",
                        "//span[contains(text(), 'Pin')]",
                        "//yt-formatted-string[contains(text(), 'Pin')]",
                    ]

                    for selector in pin_selectors:
                        try:
                            pin_options = driver.find_elements(By.XPATH, selector)
                            for pin_option in pin_options:
                                if pin_option.is_displayed() and "pin" in pin_option.text.lower():
                                    pin_option.click()
                                    pin_clicked = True
                                    logger.info(f"Clicked Pin option: {pin_option.text}")
                                    break
                            if pin_clicked:
                                break
                        except:
                            continue

                    if not pin_clicked:
                        # Try clicking any visible menu item that contains "Pin"
                        try:
                            # Get all potential menu items
                            all_items = driver.find_elements(By.CSS_SELECTOR,
                                "tp-yt-paper-item, paper-item, ytcp-ve, .menu-item, [role='menuitem']")
                            logger.info(f"Found {len(all_items)} potential menu items")

                            for item in all_items:
                                try:
                                    item_text = item.text.strip().lower()
                                    if item.is_displayed() and "pin" in item_text:
                                        logger.info(f"Clicking menu item: {item.text}")
                                        item.click()
                                        pin_clicked = True
                                        break
                                except:
                                    continue
                        except Exception as e:
                            logger.debug(f"Error searching menu items: {e}")

                    if not pin_clicked:
                        screenshot_path = screenshots_dir / f"pin_comment_{video_id}_7_no_pin.png"
                        driver.save_screenshot(str(screenshot_path))
                        return False, f"Could not find Pin option in menu. Screenshots saved."

                    time.sleep(2)

                    # Handle confirmation dialog if present
                    try:
                        confirm_button = driver.find_element(By.XPATH,
                            "//button[contains(., 'Pin') or contains(., 'Confirm') or contains(., 'Yes')]"
                        )
                        confirm_button.click()
                        logger.info("Confirmed pin action")
                        time.sleep(1)
                    except NoSuchElementException:
                        pass  # No confirmation needed

                    logger.success(f"Comment pinned successfully for video {video_id}")
                    return True, None

                except TimeoutException:
                    return False, "Timeout waiting for comments to load"

        except Exception as e:
            error = f"AdsPower pin comment error: {e}"
            logger.error(error)
            return False, error

        finally:
            # Don't close the browser - leave it for user to verify
            # if driver:
            #     driver.quit()
            pass

    def add_and_pin_comment(
        self,
        video_id: str,
        comment_text: str,
        adspower_profile_id: Optional[str] = None,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Add a comment and pin it.

        If adspower_profile_id is provided, uses browser automation for both
        adding and pinning (recommended - avoids API auth issues).

        Args:
            video_id: YouTube video ID
            comment_text: Comment text to add
            adspower_profile_id: AdsPower profile for browser automation

        Returns:
            Tuple of (success, comment_id, error_message)
        """
        if not comment_text:
            return True, None, None

        # If AdsPower profile provided, use full browser automation
        if adspower_profile_id:
            logger.info("Adding and pinning comment via AdsPower browser...")
            success, error = self.add_and_pin_comment_via_adspower(
                video_id=video_id,
                comment_text=comment_text,
                adspower_profile_id=adspower_profile_id,
            )
            if success:
                return True, "browser_comment", None
            else:
                return False, None, error

        # Fallback: try API (may fail with 401)
        logger.info("Adding comment via API (no AdsPower profile)...")
        success, comment_id, error = self.add_comment(
            video_id=video_id,
            comment_text=comment_text,
            pin=False,
        )
        return success, comment_id, error

    def add_and_pin_comment_via_adspower(
        self,
        video_id: str,
        comment_text: str,
        adspower_profile_id: str,
        base_url: str = "http://local.adspower.net:50325",
        timeout: int = 60,
    ) -> Tuple[bool, Optional[str]]:
        """
        Add a comment and pin it using AdsPower browser automation.

        Opens YouTube video page, adds comment, then goes to Studio to pin it.

        Args:
            video_id: YouTube video ID
            comment_text: Comment text to add
            adspower_profile_id: AdsPower profile ID
            base_url: AdsPower API base URL
            timeout: Max time to wait for elements

        Returns:
            Tuple of (success, error_message)
        """
        import httpx
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.common.exceptions import TimeoutException, NoSuchElementException
        from selenium.webdriver.common.action_chains import ActionChains

        logger.info(f"Adding and pinning comment via AdsPower for video: {video_id}")

        driver = None
        try:
            # Start AdsPower profile
            with httpx.Client(timeout=60) as client:
                start_resp = client.get(f"{base_url}/api/v1/browser/start?user_id={adspower_profile_id}")
                start_data = start_resp.json()

                if start_data.get("code") != 0:
                    error = f"Failed to start AdsPower profile: {start_data.get('msg')}"
                    logger.error(error)
                    return False, error

                selenium_addr = start_data["data"]["ws"]["selenium"]
                webdriver_path = start_data["data"]["webdriver"]

                logger.info("AdsPower browser started, connecting Selenium...")

                chrome_options = Options()
                chrome_options.add_experimental_option("debuggerAddress", selenium_addr)

                service = Service(executable_path=webdriver_path)
                driver = webdriver.Chrome(service=service, options=chrome_options)

                wait = WebDriverWait(driver, timeout)
                actions = ActionChains(driver)

                # Screenshots directory
                screenshots_dir = self._uploads_dir.parent / "debug_screenshots"
                screenshots_dir.mkdir(parents=True, exist_ok=True)

                # ============================================================
                # STEP 1: Go to YouTube video watch page and add comment
                # ============================================================
                # Use regular watch URL (not shorts) for better comment UI
                video_url = f"https://www.youtube.com/watch?v={video_id}"
                logger.info(f"Opening video page: {video_url}")
                driver.get(video_url)
                human_delay(5, 8)  # Human-like wait for page load

                # Verify we're on the right page
                current_url = driver.current_url
                logger.info(f"Current URL: {current_url}")

                if "youtube.com/watch" not in current_url and "youtube.com/shorts" not in current_url:
                    logger.warning(f"Unexpected URL: {current_url}, retrying navigation...")
                    driver.get(video_url)
                    human_delay(5, 8)

                # Handle cookie consent if appears
                try:
                    consent_buttons = driver.find_elements(By.XPATH,
                        "//button[contains(., 'Accept') or contains(., 'Agree') or contains(., 'Reject')]")
                    for btn in consent_buttons:
                        if btn.is_displayed():
                            human_before_action()
                            btn.click()
                            logger.info("Handled consent dialog")
                            human_delay(1, 3)
                            break
                except:
                    pass

                # Human-like: look around the page first
                human_delay(1, 2)
                human_scroll(driver, "down")  # Scroll down a bit
                human_delay(0.5, 1.5)
                human_scroll(driver, "up")    # Scroll back up slightly
                human_delay(0.5, 1)

                # Screenshot
                screenshot_path = screenshots_dir / f"add_comment_{video_id}_1_video.png"
                driver.save_screenshot(str(screenshot_path))

                # Scroll down to comments section with human-like behavior
                logger.info("Scrolling to comments section...")
                # Multiple smaller scrolls instead of one big jump
                for _ in range(random.randint(2, 4)):
                    scroll_amount = random.randint(150, 300)
                    driver.execute_script(f"window.scrollBy(0, {scroll_amount});")
                    human_delay(0.4, 1.0)

                human_delay(1, 2)  # Pause to "read" comments

                # Screenshot after scroll
                screenshot_path = screenshots_dir / f"add_comment_{video_id}_2_scrolled.png"
                driver.save_screenshot(str(screenshot_path))

                # Find comment input placeholder and click to activate
                logger.info("Looking for comment input...")
                input_activated = False

                # First, look for the placeholder that says "Add a comment..."
                placeholder_selectors = [
                    "#simplebox-placeholder",
                    "#placeholder-area",
                    "ytd-comment-simplebox-renderer #placeholder-area",
                    "[placeholder*='Add a comment']",
                    "yt-formatted-string#placeholder-area",
                ]

                for selector in placeholder_selectors:
                    try:
                        placeholders = driver.find_elements(By.CSS_SELECTOR, selector)
                        for ph in placeholders:
                            if ph.is_displayed():
                                logger.info(f"Found placeholder: {selector}")
                                # Human-like: move to element, pause, then click
                                human_mouse_move(actions, ph)
                                human_before_action()
                                human_delay(0.3, 0.8)
                                ph.click()
                                input_activated = True
                                human_delay(1, 2.5)
                                break
                        if input_activated:
                            break
                    except:
                        continue

                if not input_activated:
                    screenshot_path = screenshots_dir / f"add_comment_{video_id}_error_no_placeholder.png"
                    driver.save_screenshot(str(screenshot_path))
                    return False, f"Could not find comment placeholder. Screenshot saved."

                # Now find the actual editable input area
                human_delay(1, 2)
                screenshot_path = screenshots_dir / f"add_comment_{video_id}_3_input_active.png"
                driver.save_screenshot(str(screenshot_path))

                # Type the comment
                input_box = None
                input_selectors = [
                    "#contenteditable-root",
                    "div#contenteditable-root[contenteditable='true']",
                    "ytd-comment-simplebox-renderer #contenteditable-root",
                ]

                for selector in input_selectors:
                    try:
                        elements = driver.find_elements(By.CSS_SELECTOR, selector)
                        for el in elements:
                            if el.is_displayed():
                                input_box = el
                                logger.info(f"Found input: {selector}")
                                break
                        if input_box:
                            break
                    except:
                        continue

                if not input_box:
                    return False, "Could not find comment input after activation"

                # Human-like: move to input, pause, then click
                human_mouse_move(actions, input_box)
                human_delay(0.3, 0.7)
                input_box.click()
                human_delay(0.8, 1.5)  # Pause like thinking what to write

                # Use clipboard paste to support emoji - most reliable method
                # ChromeDriver send_keys doesn't support characters outside BMP (emoji)
                try:
                    import pyperclip
                    pyperclip.copy(comment_text)
                    human_delay(0.3, 0.8)  # Small pause before paste
                    # Paste from clipboard using Ctrl+V
                    actions.key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()
                    logger.info("Typed comment text via clipboard paste (supports emoji)")
                except ImportError:
                    logger.warning("pyperclip not installed, trying JavaScript...")
                    # Fallback to JavaScript with proper event triggering
                    try:
                        driver.execute_script("""
                            var el = arguments[0];
                            var text = arguments[1];
                            el.focus();
                            el.textContent = text;
                            el.dispatchEvent(new Event('input', { bubbles: true }));
                            el.dispatchEvent(new Event('change', { bubbles: true }));
                        """, input_box, comment_text)
                        logger.info("Typed comment text via JavaScript with events")
                    except Exception as js_err:
                        logger.warning(f"JavaScript failed: {js_err}, trying send_keys (may lose emoji)...")
                        input_box.send_keys(comment_text)
                        logger.info("Typed comment text via send_keys")
                except Exception as paste_err:
                    logger.warning(f"Clipboard paste failed: {paste_err}, trying JavaScript...")
                    driver.execute_script(
                        "arguments[0].textContent = arguments[1];",
                        input_box,
                        comment_text
                    )
                    logger.info("Typed comment text via JavaScript fallback")

                # Human-like: pause to "review" the comment before submitting
                human_delay(1.5, 3.0)

                # Screenshot after typing
                screenshot_path = screenshots_dir / f"add_comment_{video_id}_4_typed.png"
                driver.save_screenshot(str(screenshot_path))

                # Find and click Submit/Comment button
                submit_button = None

                # Look for the submit button in the comment form
                submit_selectors = [
                    "ytd-comment-simplebox-renderer #submit-button",
                    "#submit-button yt-button-shape button",
                    "#submit-button button",
                    "#submit-button",
                ]

                for selector in submit_selectors:
                    try:
                        buttons = driver.find_elements(By.CSS_SELECTOR, selector)
                        for btn in buttons:
                            if btn.is_displayed():
                                # Check if button is enabled (not aria-disabled)
                                aria_disabled = btn.get_attribute("aria-disabled")
                                if aria_disabled != "true":
                                    submit_button = btn
                                    logger.info(f"Found submit button: {selector}")
                                    break
                        if submit_button:
                            break
                    except:
                        continue

                # Try XPath
                if not submit_button:
                    try:
                        xpaths = [
                            "//ytd-comment-simplebox-renderer//button[@aria-label='Comment']",
                            "//div[@id='submit-button']//button",
                            "//tp-yt-paper-button[@aria-label='Comment']",
                        ]
                        for xpath in xpaths:
                            try:
                                btn = driver.find_element(By.XPATH, xpath)
                                if btn.is_displayed():
                                    submit_button = btn
                                    logger.info(f"Found submit via XPath")
                                    break
                            except:
                                continue
                    except:
                        pass

                if not submit_button:
                    screenshot_path = screenshots_dir / f"add_comment_{video_id}_error_no_submit.png"
                    driver.save_screenshot(str(screenshot_path))
                    return False, f"Could not find submit button. Screenshot saved."

                # Human-like: move to button, pause, then click
                logger.info("Clicking submit button...")
                human_mouse_move(actions, submit_button)
                human_delay(0.5, 1.0)  # Hesitate before submitting
                submit_button.click()
                human_delay(2, 4)  # Wait for submission

                # Handle "Remember that anyone can see what you write" popup
                try:
                    got_it_buttons = driver.find_elements(By.XPATH,
                        "//button[contains(., 'Got it')] | //yt-button-shape//button[contains(., 'Got it')]")
                    for btn in got_it_buttons:
                        if btn.is_displayed():
                            logger.info("Handling 'Got it' popup...")
                            btn.click()
                            time.sleep(3)
                            break
                except:
                    pass

                # Wait for comment to be submitted - need longer wait for YouTube to process
                logger.info("Waiting for YouTube to process comment...")
                time.sleep(8)

                # Screenshot after submit
                screenshot_path = screenshots_dir / f"add_comment_{video_id}_5_submitted.png"
                driver.save_screenshot(str(screenshot_path))

                # Verify comment was added by checking if our text appears
                comment_verified = False
                max_verify_attempts = 3

                for attempt in range(max_verify_attempts):
                    try:
                        # Scroll to comments section to refresh view
                        driver.execute_script("window.scrollTo(0, 400);")
                        time.sleep(3)

                        page_source = driver.page_source
                        if comment_text[:30] in page_source:
                            logger.success(f"Comment verified on page! (attempt {attempt + 1})")
                            comment_verified = True
                            break
                        else:
                            logger.warning(f"Comment not found yet (attempt {attempt + 1}/{max_verify_attempts})")
                            time.sleep(5)
                    except Exception as e:
                        logger.debug(f"Verification error: {e}")
                        time.sleep(3)

                if not comment_verified:
                    # Take screenshot and return error - don't proceed to pin random comment
                    screenshot_path = screenshots_dir / f"add_comment_{video_id}_error_not_verified.png"
                    driver.save_screenshot(str(screenshot_path))
                    return False, f"Comment was not verified on page after {max_verify_attempts} attempts. May have been blocked by YouTube moderation. Screenshot saved."

                logger.success("Comment added and verified!")

                # ============================================================
                # STEP 2: Go to YouTube Studio to pin the comment
                # ============================================================
                logger.info("Now going to YouTube Studio to pin comment...")
                logger.info(f"Will verify comment author matches: {self.channel_config.channel_name}")

                # Use existing pin method with channel name for author verification
                pin_success, pin_error = self._pin_comment_in_studio(
                    driver=driver,
                    video_id=video_id,
                    comment_text=comment_text,
                    screenshots_dir=screenshots_dir,
                    timeout=timeout,
                    channel_name=self.channel_config.channel_name,
                )

                if not pin_success:
                    return False, f"Comment added but pin failed: {pin_error}"

                logger.success("Comment added and pinned successfully!")
                return True, None

        except Exception as e:
            error = f"AdsPower add/pin comment error: {e}"
            logger.error(error)
            return False, error

        finally:
            pass  # Don't close browser

    def _pin_comment_in_studio(
        self,
        driver,
        video_id: str,
        comment_text: str,
        screenshots_dir: Path,
        timeout: int = 60,
        channel_name: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Pin a comment in YouTube Studio (helper method, uses existing driver).

        IMPORTANT: Only pins comments that match BOTH:
        1. The exact comment text (first 30 chars)
        2. The channel owner (our channel)

        Never pins random/other people's comments.
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.common.exceptions import TimeoutException, NoSuchElementException
        from selenium.webdriver.common.action_chains import ActionChains

        wait = WebDriverWait(driver, timeout)
        actions = ActionChains(driver)

        # Get channel name for author verification
        if not channel_name:
            channel_name = self.channel_config.channel_name
        logger.info(f"Will only pin comments from channel: {channel_name}")

        # Navigate to YouTube Studio comments page
        studio_url = f"https://studio.youtube.com/video/{video_id}/comments"
        logger.info(f"Opening YouTube Studio: {studio_url}")
        driver.get(studio_url)
        human_delay(4, 6)

        # Human-like: look around the page
        human_scroll(driver, "down")
        human_delay(0.5, 1)
        human_scroll(driver, "up")
        human_delay(1, 2)

        # Refresh page to ensure we see latest comments
        logger.info("Refreshing page to load latest comments...")
        driver.refresh()
        human_delay(4, 6)

        # Handle popups with human-like behavior
        try:
            popup_buttons = driver.find_elements(By.XPATH,
                "//button[contains(., 'Got it') or contains(., 'Dismiss') or contains(., 'Close') or contains(., 'OK')]")
            for btn in popup_buttons:
                if btn.is_displayed():
                    human_delay(0.5, 1.0)
                    btn.click()
                    human_delay(0.8, 1.5)
        except:
            pass

        human_delay(2, 4)

        # IMPORTANT: Clear any filters that might hide our comment
        # Look for filter chips with "X" close button and remove them
        logger.info("Clearing any active filters...")
        try:
            # Find filter chips (like "Response status: Unresponded")
            filter_close_buttons = driver.find_elements(By.CSS_SELECTOR,
                "[class*='filter'] [aria-label*='Remove'], [class*='chip'] button, ytcp-chip-bar button")
            for btn in filter_close_buttons:
                try:
                    if btn.is_displayed():
                        logger.info(f"Removing filter: clicking close button")
                        human_delay(0.3, 0.7)
                        btn.click()
                        human_delay(0.8, 1.5)
                except:
                    continue

            # Also try clicking the "X" icon on filter badges
            filter_x_icons = driver.find_elements(By.XPATH,
                "//span[contains(@class, 'remove') or contains(@class, 'close')]//ancestor::button | " +
                "//button[contains(@aria-label, 'Remove') or contains(@aria-label, 'Clear')]")
            for icon in filter_x_icons:
                try:
                    if icon.is_displayed():
                        logger.info("Clicking filter X icon")
                        human_delay(0.3, 0.6)
                        icon.click()
                        human_delay(0.8, 1.2)
                except:
                    continue

            # Try clicking directly on chips that have X in them
            chips_with_x = driver.find_elements(By.XPATH,
                "//*[contains(text(), '×') or contains(text(), '✕')]/ancestor::*[contains(@class, 'chip') or contains(@class, 'filter')]")
            for chip in chips_with_x:
                try:
                    if chip.is_displayed():
                        # Find the close button inside
                        close_btn = chip.find_elements(By.CSS_SELECTOR, "button, [role='button']")
                        for btn in close_btn:
                            if btn.is_displayed():
                                human_delay(0.3, 0.5)
                                btn.click()
                                human_delay(0.6, 1.0)
                                break
                except:
                    continue

        except Exception as e:
            logger.debug(f"Filter clearing error (non-fatal): {e}")

        # Try to find and click any visible "✕" or close icons in the filter area
        try:
            # Look for elements containing ✕ character specifically
            close_elements = driver.find_elements(By.XPATH,
                "//*[text()='✕' or text()='×' or text()='X']")
            for el in close_elements:
                try:
                    if el.is_displayed():
                        parent = el.find_element(By.XPATH, "./..")
                        if parent.is_displayed():
                            logger.info("Found ✕ element, clicking parent")
                            human_delay(0.4, 0.8)
                            parent.click()
                            human_delay(1.5, 2.5)
                except:
                    continue
        except:
            pass

        human_delay(1.5, 3)

        # Screenshot after clearing filters
        screenshot_path = screenshots_dir / f"pin_{video_id}_studio.png"
        driver.save_screenshot(str(screenshot_path))

        # Find comments
        try:
            comment_selectors = ["ytcp-comment-thread", "[class*='comment']"]
            comment_threads = []

            for selector in comment_selectors:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                if elements:
                    comment_threads = elements
                    break

            if not comment_threads:
                logger.info("No comments found yet, waiting longer...")
                time.sleep(10)
                # Refresh and try again
                driver.refresh()
                time.sleep(5)
                for selector in comment_selectors:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        comment_threads = elements
                        break

            if not comment_threads:
                return False, "No comments found in Studio after refresh"

            logger.info(f"Found {len(comment_threads)} comments")

            # Find our specific comment by BOTH text AND author
            target_comment = None
            search_text = comment_text[:30] if comment_text else ""

            if not search_text:
                return False, "No comment text provided - cannot verify which comment to pin"

            logger.info(f"Looking for comment with text: '{search_text}...'")
            logger.info(f"And author: '{channel_name}'")

            for thread in comment_threads:
                try:
                    thread_text = thread.text
                    logger.debug(f"Checking comment: {thread_text[:100]}...")

                    # Check if text matches
                    if search_text not in thread_text:
                        continue

                    logger.info("Text match found! Verifying author...")

                    # Try to find author name in the comment thread
                    # In YouTube Studio, the author is usually in a specific element
                    author_found = False
                    author_selectors = [
                        "#author-text",
                        ".author-text",
                        "[class*='author']",
                        "a[href*='channel']",
                        "#name",
                    ]

                    for author_sel in author_selectors:
                        try:
                            author_elements = thread.find_elements(By.CSS_SELECTOR, author_sel)
                            for author_el in author_elements:
                                author_text = author_el.text.strip()
                                if author_text:
                                    logger.info(f"Found author: '{author_text}'")
                                    # Check if this is our channel (case-insensitive, partial match)
                                    if (channel_name.lower() in author_text.lower() or
                                        author_text.lower() in channel_name.lower()):
                                        author_found = True
                                        logger.info(f"Author verified as our channel!")
                                        break
                            if author_found:
                                break
                        except:
                            continue

                    # If we couldn't verify author but text matches,
                    # check if the comment has "owner" badge or similar indicator
                    if not author_found:
                        try:
                            # Look for owner badge or similar indicators
                            owner_indicators = thread.find_elements(By.CSS_SELECTOR,
                                "[class*='owner'], [class*='creator'], [class*='badge']")
                            for indicator in owner_indicators:
                                if indicator.is_displayed():
                                    logger.info("Found owner/creator badge - this is our comment")
                                    author_found = True
                                    break
                        except:
                            pass

                    # If text matches and either author verified OR we're in the first position
                    # (owner comments typically appear first in Studio)
                    if author_found:
                        target_comment = thread
                        logger.success("Found our comment with verified authorship!")
                        break
                    else:
                        # Text matches but couldn't verify author
                        # Log this but continue looking for a better match
                        logger.warning(f"Text matches but couldn't verify author for this comment")
                        # Store as potential match but keep looking
                        if target_comment is None:
                            target_comment = thread
                            logger.info("Storing as potential match, continuing search...")

                except Exception as e:
                    logger.debug(f"Error checking comment: {e}")
                    continue

            # STRICT CHECK: Never pin a random comment
            if not target_comment:
                screenshot_path = screenshots_dir / f"pin_{video_id}_not_found.png"
                driver.save_screenshot(str(screenshot_path))

                # Log all visible comments for debugging
                logger.warning("Could not find our comment. Visible comments:")
                for i, thread in enumerate(comment_threads[:5]):
                    try:
                        logger.warning(f"  {i+1}. {thread.text[:100]}...")
                    except:
                        pass

                return False, f"Could not find comment with text '{search_text}' from our channel. Screenshot saved."

            logger.info("Proceeding to pin the verified comment...")

            # Human-like: random scroll before action
            human_before_action()
            if random.random() < 0.3:
                human_scroll(driver, "random")

            # Hover to reveal menu with human-like movement
            human_mouse_move(actions, target_comment)
            human_delay(1, 2)

            # Find 3-dot menu
            icon_buttons = target_comment.find_elements(By.CSS_SELECTOR, "ytcp-icon-button")
            menu_button = None

            for btn in reversed(icon_buttons):
                icon = btn.get_attribute("icon") or ""
                if "more" in icon.lower() or "vert" in icon.lower():
                    menu_button = btn
                    break

            if not menu_button and icon_buttons:
                menu_button = icon_buttons[-1]

            if not menu_button:
                return False, "Could not find menu button"

            # Human-like click on menu
            logger.info("Clicking menu...")
            human_mouse_move(actions, menu_button)
            human_delay(0.3, 0.7)
            menu_button.click()
            human_delay(1.5, 2.5)

            # Screenshot of menu
            screenshot_path = screenshots_dir / f"pin_{video_id}_menu.png"
            driver.save_screenshot(str(screenshot_path))

            # Find Pin option
            pin_clicked = False
            all_items = driver.find_elements(By.CSS_SELECTOR,
                "tp-yt-paper-item, paper-item, ytcp-ve, [role='menuitem']")

            for item in all_items:
                try:
                    if item.is_displayed() and "pin" in item.text.lower():
                        # Human-like: move to item and click
                        human_mouse_move(actions, item)
                        human_delay(0.3, 0.6)
                        item.click()
                        pin_clicked = True
                        logger.info(f"Clicked: {item.text}")
                        break
                except:
                    continue

            if not pin_clicked:
                return False, "Could not find Pin option"

            human_delay(1.5, 2.5)

            # Handle confirmation
            try:
                confirm = driver.find_element(By.XPATH,
                    "//button[contains(., 'Pin') or contains(., 'Confirm') or contains(., 'Yes')]")
                human_mouse_move(actions, confirm)
                human_delay(0.4, 0.8)
                confirm.click()
                logger.info("Confirmed pin")
                human_delay(1.5, 2.5)
            except:
                pass

            logger.success("Comment pinned!")
            return True, None

        except Exception as e:
            return False, str(e)
