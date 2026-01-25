"""
Configuration Manager for YTAutoPublisher

Handles reading/writing configuration files for channels and global settings.
"""

import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from .models import (
    GlobalSettings,
    ChannelConfig,
    ProjectBrief,
    PublishStatusRecord,
    PublishEvent,
    OAuthToken,
)


class ConfigManager:
    """
    Manages all configuration files for YTAutoPublisher.

    Directory structure:
        config/
            global_settings.json
            channels/
                channel_001/
                    config.json
                    client_secrets.json
                    token.json
    """

    def __init__(self, base_path: Optional[Path] = None):
        """
        Initialize config manager.

        Args:
            base_path: Base directory (default: current working directory)
        """
        self.base_path = base_path or Path.cwd()
        self.config_dir = self.base_path / "config"
        self.channels_dir = self.config_dir / "channels"
        self.projects_dir = self.base_path / "projects"
        self.archive_dir = self.base_path / "archive"
        self.logs_dir = self.base_path / "logs"

    # ========================================================================
    # INITIALIZATION
    # ========================================================================

    def init_directories(self) -> Dict[str, bool]:
        """
        Create required directories if they don't exist.

        Returns:
            Dict with directory names and whether they were created
        """
        results = {}

        directories = [
            self.config_dir,
            self.channels_dir,
            self.projects_dir,
            self.archive_dir,
            self.logs_dir,
        ]

        for directory in directories:
            created = False
            if not directory.exists():
                directory.mkdir(parents=True, exist_ok=True)
                created = True
            results[directory.name] = created

        # Create default global settings if not exists
        if not self.get_global_settings_path().exists():
            self.save_global_settings(GlobalSettings())
            results["global_settings.json"] = True

        return results

    # ========================================================================
    # GLOBAL SETTINGS
    # ========================================================================

    def get_global_settings_path(self) -> Path:
        """Get path to global settings file"""
        return self.config_dir / "global_settings.json"

    def load_global_settings(self) -> GlobalSettings:
        """Load global settings from file"""
        path = self.get_global_settings_path()

        if not path.exists():
            return GlobalSettings()

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return GlobalSettings(**data)

    def save_global_settings(self, settings: GlobalSettings) -> None:
        """Save global settings to file"""
        path = self.get_global_settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            f.write(settings.model_dump_json(indent=2))

    # ========================================================================
    # CHANNEL CONFIG
    # ========================================================================

    def get_channel_dir(self, channel_id: str) -> Path:
        """Get directory for a channel"""
        return self.channels_dir / channel_id

    def get_channel_config_path(self, channel_id: str) -> Path:
        """Get path to channel config file"""
        return self.get_channel_dir(channel_id) / "config.json"

    def get_client_secrets_path(self, channel_id: str) -> Path:
        """Get path to client_secrets.json"""
        return self.get_channel_dir(channel_id) / "client_secrets.json"

    def get_token_path(self, channel_id: str) -> Path:
        """Get path to token.json"""
        return self.get_channel_dir(channel_id) / "token.json"

    def load_channel_config(self, channel_id: str) -> Optional[ChannelConfig]:
        """Load channel configuration"""
        path = self.get_channel_config_path(channel_id)

        if not path.exists():
            return None

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return ChannelConfig(**data)

    def save_channel_config(self, config: ChannelConfig) -> None:
        """Save channel configuration"""
        channel_dir = self.get_channel_dir(config.channel_id)
        channel_dir.mkdir(parents=True, exist_ok=True)

        path = self.get_channel_config_path(config.channel_id)

        with open(path, "w", encoding="utf-8") as f:
            f.write(config.model_dump_json(indent=2))

    def list_channels(self) -> List[str]:
        """List all configured channel IDs"""
        if not self.channels_dir.exists():
            return []

        channels = []
        for item in self.channels_dir.iterdir():
            if item.is_dir() and (item / "config.json").exists():
                channels.append(item.name)

        return sorted(channels)

    def channel_exists(self, channel_id: str) -> bool:
        """Check if channel configuration exists"""
        return self.get_channel_config_path(channel_id).exists()

    def channel_is_authorized(self, channel_id: str) -> bool:
        """Check if channel has valid OAuth token"""
        return self.get_token_path(channel_id).exists()

    # ========================================================================
    # OAuth TOKEN
    # ========================================================================

    def load_oauth_token(self, channel_id: str) -> Optional[OAuthToken]:
        """Load OAuth token for channel"""
        path = self.get_token_path(channel_id)

        if not path.exists():
            return None

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return OAuthToken(**data)

    def save_oauth_token(self, channel_id: str, token: OAuthToken) -> None:
        """Save OAuth token for channel"""
        path = self.get_token_path(channel_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            f.write(token.model_dump_json(indent=2))

    def load_client_secrets(self, channel_id: str) -> Optional[Dict[str, Any]]:
        """Load client_secrets.json for channel"""
        path = self.get_client_secrets_path(channel_id)

        if not path.exists():
            return None

        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    # ========================================================================
    # PROJECT BRIEF
    # ========================================================================

    def get_project_dir(self, project_id: str) -> Path:
        """Get project directory"""
        return self.projects_dir / project_id

    def get_project_brief_path(self, project_id: str) -> Path:
        """Get path to project_brief.json"""
        return self.get_project_dir(project_id) / "project_brief.json"

    def get_publish_status_path(self, project_id: str) -> Path:
        """Get path to publish_status.json"""
        return self.get_project_dir(project_id) / "publish_status.json"

    def load_project_brief(self, project_id: str) -> Optional[ProjectBrief]:
        """Load project brief for publishing"""
        path = self.get_project_brief_path(project_id)

        if not path.exists():
            return None

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Extract only required fields
        return ProjectBrief(
            project_id=data.get("project_id", project_id),
            youtube=data.get("youtube", {}),
            publish_config=data.get("publish_config"),
            _meta=data.get("_meta"),
        )

    def load_publish_status(self, project_id: str) -> Optional[PublishStatusRecord]:
        """Load publish status for project"""
        path = self.get_publish_status_path(project_id)

        if not path.exists():
            return None

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return PublishStatusRecord(**data)

    def save_publish_status(self, project_id: str, status: PublishStatusRecord) -> None:
        """Save publish status for project"""
        path = self.get_publish_status_path(project_id)

        with open(path, "w", encoding="utf-8") as f:
            f.write(status.model_dump_json(indent=2))

    # ========================================================================
    # VIDEO DISCOVERY
    # ========================================================================

    def find_video_file(self, project_id: str) -> Optional[Path]:
        """
        Find the video file to upload.

        Searches in order:
        1. upscaled/final_video.mp4
        2. upscaled/*.mp4
        3. final_video.mp4
        4. *.mp4 in project root
        """
        project_dir = self.get_project_dir(project_id)

        if not project_dir.exists():
            return None

        # Check upscaled directory first
        upscaled_dir = project_dir / "upscaled"
        if upscaled_dir.exists():
            # Priority: final_video.mp4
            final = upscaled_dir / "final_video.mp4"
            if final.exists():
                return final

            # Any .mp4 in upscaled
            for mp4 in upscaled_dir.glob("*.mp4"):
                return mp4

        # Check project root
        final = project_dir / "final_video.mp4"
        if final.exists():
            return final

        # Any .mp4 in root
        for mp4 in project_dir.glob("*.mp4"):
            # Skip scene videos
            if "scene_" not in mp4.name:
                return mp4

        return None

    # ========================================================================
    # PENDING PROJECTS
    # ========================================================================

    def list_pending_projects(self) -> List[str]:
        """
        List all projects ready for publishing.

        A project is ready if:
        1. Has project_brief.json
        2. Has video file
        3. Either no publish_status.json or status != 'published'
        """
        pending = []

        if not self.projects_dir.exists():
            return []

        for project_dir in self.projects_dir.iterdir():
            if not project_dir.is_dir():
                continue

            project_id = project_dir.name

            # Check brief exists
            if not self.get_project_brief_path(project_id).exists():
                continue

            # Check video exists
            if not self.find_video_file(project_id):
                continue

            # Check publish status
            status = self.load_publish_status(project_id)
            if status and status.status == "published":
                continue

            pending.append(project_id)

        return sorted(pending)

    # ========================================================================
    # ARCHIVE
    # ========================================================================

    def archive_project(self, project_id: str) -> Path:
        """
        Move project to archive directory.

        Returns:
            New path in archive
        """
        import shutil

        source = self.get_project_dir(project_id)
        dest = self.archive_dir / project_id

        if dest.exists():
            # Add timestamp to avoid collision
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest = self.archive_dir / f"{project_id}_{timestamp}"

        shutil.move(str(source), str(dest))
        return dest

    # ========================================================================
    # PUBLISH HISTORY
    # ========================================================================

    def get_history_path(self) -> Path:
        """Get path to publish history file"""
        return self.logs_dir / "publish_history.jsonl"

    def append_history_event(self, event: PublishEvent) -> None:
        """Append event to publish history"""
        path = self.get_history_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")

    def read_history(self, days: int = 7) -> List[PublishEvent]:
        """Read publish history for last N days"""
        path = self.get_history_path()

        if not path.exists():
            return []

        events = []
        cutoff = datetime.now().timestamp() - (days * 86400)

        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                    event = PublishEvent(**data)

                    if event.timestamp.timestamp() >= cutoff:
                        events.append(event)
                except (json.JSONDecodeError, ValueError):
                    continue

        return events


# Singleton instance
_config_manager: Optional[ConfigManager] = None


def get_config_manager(base_path: Optional[Path] = None) -> ConfigManager:
    """Get global ConfigManager instance"""
    global _config_manager

    if _config_manager is None:
        _config_manager = ConfigManager(base_path)

    return _config_manager
