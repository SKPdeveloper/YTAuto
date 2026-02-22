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

            # Parse expiry so Credentials knows when the token is stale
            expiry = None
            expiry_str = token_data.get("expiry")
            if expiry_str:
                from datetime import datetime
                try:
                    expiry = datetime.fromisoformat(expiry_str)
                except (ValueError, TypeError):
                    pass

            creds = Credentials(
                token=token_data.get("token"),
                refresh_token=token_data.get("refresh_token"),
                token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
                client_id=token_data.get("client_id"),
                client_secret=token_data.get("client_secret"),
                scopes=token_data.get("scopes", SCOPES),
                expiry=expiry,
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
    # CONNECTION TEST
    # ========================================================================

    # ========================================================================
    # VIDEO STATS & METADATA UPDATE (for A/B rotation)
    # ========================================================================

    def get_video_stats(self, video_id: str) -> Optional[dict]:
        """
        Get video statistics (views, likes, comments).

        Uses videos.list(part="statistics") — 1 quota unit.

        Args:
            video_id: YouTube video ID

        Returns:
            Dict with views/likes/comments counts or None on error
        """
        try:
            with self._proxy_env():
                youtube = self.get_youtube_client()

                response = youtube.videos().list(
                    part="statistics",
                    id=video_id,
                ).execute()

                items = response.get("items", [])
                if not items:
                    logger.warning(f"Video not found: {video_id}")
                    return None

                stats = items[0]["statistics"]
                return {
                    "views": int(stats.get("viewCount", 0)),
                    "likes": int(stats.get("likeCount", 0)),
                    "comments": int(stats.get("commentCount", 0)),
                }

        except HttpError as e:
            logger.error(f"Failed to get video stats: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting video stats: {e}")
            return None

    def update_video(
        self,
        video_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[list] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Update video metadata (title, description, tags).

        First GETs current snippet, merges changes, then PUTs.
        Uses videos.list + videos.update — 51 quota units.

        Args:
            video_id: YouTube video ID
            title: New title (or None to keep current)
            description: New description (or None to keep current)
            tags: New tags list (or None to keep current)

        Returns:
            Tuple of (success, error_message)
        """
        try:
            with self._proxy_env():
                youtube = self.get_youtube_client()

                # GET current snippet
                response = youtube.videos().list(
                    part="snippet",
                    id=video_id,
                ).execute()

                items = response.get("items", [])
                if not items:
                    return False, f"Video not found: {video_id}"

                raw_snippet = items[0]["snippet"]

                # Build clean snippet with only mutable fields
                # (YouTube API returns read-only fields like channelId,
                #  publishedAt, thumbnails that must not be sent back)
                clean_snippet = {
                    "title": raw_snippet.get("title", ""),
                    "description": raw_snippet.get("description", ""),
                    "categoryId": raw_snippet.get("categoryId", "24"),
                }
                if "tags" in raw_snippet:
                    clean_snippet["tags"] = raw_snippet["tags"]
                if "defaultLanguage" in raw_snippet:
                    clean_snippet["defaultLanguage"] = raw_snippet["defaultLanguage"]
                if "defaultAudioLanguage" in raw_snippet:
                    clean_snippet["defaultAudioLanguage"] = raw_snippet["defaultAudioLanguage"]

                # Merge caller changes
                if title is not None:
                    clean_snippet["title"] = title[:100]
                if description is not None:
                    clean_snippet["description"] = description[:5000]
                if tags is not None:
                    clean_snippet["tags"] = tags[:500]

                # PUT updated snippet
                youtube.videos().update(
                    part="snippet",
                    body={
                        "id": video_id,
                        "snippet": clean_snippet,
                    },
                ).execute()

                logger.info(f"Updated video metadata: {video_id}")
                return True, None

        except HttpError as e:
            error_msg = str(e)
            if e.resp.status == 404:
                error_msg = f"Video not found: {video_id}"
            elif e.resp.status == 403:
                error_msg = "Quota exceeded or permission denied"
            logger.error(f"Failed to update video: {error_msg}")
            return False, error_msg
        except Exception as e:
            logger.error(f"Unexpected error updating video: {e}")
            return False, str(e)

    def insert_comment_thread(
        self,
        video_id: str,
        text: str,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Post a top-level comment on a video.

        Uses commentThreads.insert — 50 quota units.

        Args:
            video_id: YouTube video ID
            text: Comment text

        Returns:
            Tuple of (success, comment_id, error_message)
        """
        if not text or not text.strip():
            return False, None, "Comment text is empty"

        try:
            with self._proxy_env():
                youtube = self.get_youtube_client()

                response = youtube.commentThreads().insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "videoId": video_id,
                            "topLevelComment": {
                                "snippet": {
                                    "textOriginal": text,
                                }
                            },
                        }
                    },
                ).execute()

                comment_id = response["snippet"]["topLevelComment"]["id"]
                logger.info(f"Posted comment on {video_id}: {comment_id}")
                return True, comment_id, None

        except HttpError as e:
            error_msg = str(e)
            if e.resp.status == 400:
                error_msg = f"Bad request (invalid video_id or comment content): {e}"
            elif e.resp.status == 403:
                error_msg = "Comments disabled or quota exceeded"
            logger.error(f"Failed to post comment: {error_msg}")
            return False, None, error_msg
        except Exception as e:
            logger.error(f"Unexpected error posting comment: {e}")
            return False, None, str(e)

    def delete_comment(self, comment_id: str) -> Tuple[bool, Optional[str]]:
        """
        Delete a comment by ID.

        Uses comments.delete — 50 quota units.

        Args:
            comment_id: YouTube comment ID

        Returns:
            Tuple of (success, error_message)
        """
        try:
            with self._proxy_env():
                youtube = self.get_youtube_client()

                youtube.comments().delete(id=comment_id).execute()

                logger.info(f"Deleted comment: {comment_id}")
                return True, None

        except HttpError as e:
            error_msg = str(e)
            if e.resp.status == 404:
                error_msg = f"Comment not found: {comment_id}"
            elif e.resp.status == 403:
                error_msg = "Permission denied (not comment owner?)"
            logger.error(f"Failed to delete comment: {error_msg}")
            return False, error_msg
        except Exception as e:
            logger.error(f"Unexpected error deleting comment: {e}")
            return False, str(e)

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

