"""
Pydantic Models for YTAutoPublisher

Defines all data structures used in the publishing pipeline.
"""

from datetime import datetime
from typing import Optional, List
from pathlib import Path
from enum import Enum

from pydantic import BaseModel, Field


# ============================================================================
# ENUMS
# ============================================================================

class PublishStatus(str, Enum):
    """Status of a video publication"""
    PENDING = "pending"
    UPLOADING = "uploading"
    PUBLISHED = "published"
    SCHEDULED = "scheduled"
    FAILED = "failed"


class PrivacyStatus(str, Enum):
    """YouTube video privacy status"""
    PUBLIC = "public"
    PRIVATE = "private"
    UNLISTED = "unlisted"


# ============================================================================
# PROXY CONFIG
# ============================================================================

class ProxyConfig(BaseModel):
    """Proxy configuration for a channel"""
    enabled: bool = True
    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None

    def get_proxy_url(self) -> str:
        """Get proxy URL for requests"""
        if self.username and self.password:
            return f"http://{self.username}:{self.password}@{self.host}:{self.port}"
        return f"http://{self.host}:{self.port}"

    def get_socks_proxy(self) -> dict:
        """Get SOCKS proxy config for httplib2"""
        return {
            "proxy_type": "http",
            "proxy_host": self.host,
            "proxy_port": self.port,
            "proxy_user": self.username,
            "proxy_pass": self.password,
        }


# ============================================================================
# CHANNEL CONFIG
# ============================================================================

class ChannelSettings(BaseModel):
    """Channel-specific settings"""
    active: bool = True
    default_privacy: PrivacyStatus = PrivacyStatus.PUBLIC
    default_category_id: str = "24"  # Entertainment
    made_for_kids: bool = False


class ChannelConfig(BaseModel):
    """Configuration for a YouTube channel"""
    channel_id: str  # Internal ID (e.g., "channel_001")
    channel_name: str  # Display name
    youtube_channel_id: str  # UC... ID
    region: str = "US"
    timezone: str = "America/New_York"
    proxy: Optional[ProxyConfig] = None
    adspower_profile_id: Optional[str] = None  # AdsPower profile for browser automation
    settings: ChannelSettings = Field(default_factory=ChannelSettings)

    class Config:
        use_enum_values = True


# ============================================================================
# GLOBAL SETTINGS
# ============================================================================

class PathsConfig(BaseModel):
    """Path configuration"""
    projects_dir: str = "projects"
    archive_dir: str = "archive"
    logs_dir: str = "logs"


class FFmpegConfig(BaseModel):
    """FFmpeg configuration"""
    path: str = "ffmpeg"
    clean_metadata: bool = True


class UploadConfig(BaseModel):
    """Upload defaults"""
    default_category_id: str = "24"  # Entertainment
    default_privacy: PrivacyStatus = PrivacyStatus.PUBLIC
    made_for_kids: bool = False
    retry_attempts: int = 3
    retry_delay_seconds: int = 30


class SchedulerConfig(BaseModel):
    """Scheduler configuration (placeholder)"""
    enabled: bool = False


class PostPublishConfig(BaseModel):
    """Post-publish actions"""
    move_to_archive: bool = True
    delete_clean_video: bool = True


class LoggingConfig(BaseModel):
    """Logging configuration"""
    level: str = "INFO"


class GlobalSettings(BaseModel):
    """Global application settings"""
    version: str = "1.0"
    paths: PathsConfig = Field(default_factory=PathsConfig)
    ffmpeg: FFmpegConfig = Field(default_factory=FFmpegConfig)
    upload: UploadConfig = Field(default_factory=UploadConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    post_publish: PostPublishConfig = Field(default_factory=PostPublishConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    class Config:
        use_enum_values = True


# ============================================================================
# PROJECT BRIEF (from pipeline)
# ============================================================================

class YouTubeMetadata(BaseModel):
    """YouTube metadata from project_brief.json"""
    title: str
    description: str
    pinned_comment: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    hashtags: List[str] = Field(default_factory=list)


class ProjectPublishConfig(BaseModel):
    """Publish configuration from project_brief.json"""
    target_channel: str
    scheduled_datetime: Optional[datetime] = None
    privacy_status: PrivacyStatus = PrivacyStatus.PUBLIC
    auto_schedule: bool = False  # If True, scheduler picks next available slot

    class Config:
        use_enum_values = True


class ProjectMeta(BaseModel):
    """Project metadata"""
    created_at: Optional[datetime] = None


class ProjectBrief(BaseModel):
    """Partial project_brief.json for publishing"""
    project_id: str
    youtube: YouTubeMetadata
    publish_config: Optional[ProjectPublishConfig] = None
    _meta: Optional[ProjectMeta] = None


# ============================================================================
# PUBLISH STATUS
# ============================================================================

class PublishStatusRecord(BaseModel):
    """Status of a published video"""
    status: PublishStatus = PublishStatus.PENDING
    video_id: Optional[str] = None
    video_url: Optional[str] = None
    comment_id: Optional[str] = None
    published_at: Optional[datetime] = None
    channel_id: Optional[str] = None
    attempts: int = 0
    error: Optional[str] = None

    class Config:
        use_enum_values = True


# ============================================================================
# PUBLISH HISTORY
# ============================================================================

class PublishEvent(BaseModel):
    """Single event in publish history"""
    timestamp: datetime = Field(default_factory=datetime.now)
    event: str  # upload_started, upload_completed, comment_pinned, archived, error
    project_id: Optional[str] = None
    channel_id: Optional[str] = None
    video_id: Optional[str] = None
    comment_id: Optional[str] = None
    error: Optional[str] = None
    details: Optional[dict] = None


# ============================================================================
# OAuth Token
# ============================================================================

class OAuthToken(BaseModel):
    """OAuth token storage"""
    token: str
    refresh_token: str
    token_uri: str = "https://oauth2.googleapis.com/token"
    client_id: str
    client_secret: str
    scopes: List[str] = Field(default_factory=lambda: [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.force-ssl"
    ])
    expiry: Optional[datetime] = None


# ============================================================================
# UPLOAD STATE (for resumable uploads)
# ============================================================================

class UploadState(BaseModel):
    """State for resumable video uploads"""
    project_id: str
    channel_id: str
    video_path: str
    resumable_uri: Optional[str] = None
    bytes_uploaded: int = 0
    total_bytes: int = 0
    started_at: datetime = Field(default_factory=datetime.now)
    last_updated: datetime = Field(default_factory=datetime.now)
    retry_count: int = 0

    # Video metadata (to recreate request if needed)
    title: str
    description: str
    tags: List[str] = Field(default_factory=list)
    category_id: str = "24"
    privacy_status: str = "private"
    scheduled_datetime: Optional[datetime] = None
    made_for_kids: bool = False
