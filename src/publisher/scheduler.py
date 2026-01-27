"""
Publication Scheduler for YTAutoPublisher

Automatically schedules video publications based on:
- Channel-specific posting schedule (different times for different days)
- Existing queue of scheduled publications
- Timezone-aware datetime handling

Edge cases handled:
- Empty queue: starts from next available weekday
- Today after posting time: starts from tomorrow
- Weekends: skips to Monday
- Past entries in queue: ignored when finding next slot
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from enum import Enum
from zoneinfo import ZoneInfo

from loguru import logger
from pydantic import BaseModel, Field


# ============================================================================
# CONSTANTS
# ============================================================================

# Default posting schedule (24h format, Eastern Time)
DEFAULT_SCHEDULE = {
    "monday": "16:00",     # 4 PM
    "tuesday": "15:00",    # 3 PM
    "wednesday": "16:00",  # 4 PM
    "thursday": "15:00",   # 3 PM
    "friday": "15:00",     # 3 PM
    "saturday": None,      # No posting
    "sunday": None,        # No posting
}

WEEKDAY_NAMES = [
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday"
]


# ============================================================================
# MODELS
# ============================================================================

class PublishStatus(str, Enum):
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    FAILED = "failed"
    CANCELLED = "cancelled"


class QueueEntry(BaseModel):
    """Single entry in the publish queue"""
    project_id: str
    scheduled_datetime: datetime  # UTC
    scheduled_datetime_local: str  # Human-readable local time
    status: PublishStatus = PublishStatus.SCHEDULED
    video_id: Optional[str] = None  # YouTube video ID after publish
    created_at: datetime = Field(default_factory=lambda: datetime.now(ZoneInfo("UTC")))


class ChannelQueue(BaseModel):
    """Queue for a single channel"""
    channel_id: str
    timezone: str = "America/New_York"
    schedule: Dict[str, Optional[str]] = Field(default_factory=lambda: DEFAULT_SCHEDULE.copy())
    entries: List[QueueEntry] = Field(default_factory=list)


class PublishQueue(BaseModel):
    """Full publish queue for all channels"""
    version: str = "1.0"
    channels: Dict[str, ChannelQueue] = Field(default_factory=dict)


# ============================================================================
# SCHEDULER
# ============================================================================

class PublicationScheduler:
    """
    Manages publication scheduling across channels.

    Features:
    - Finds next available slot based on schedule and existing queue
    - Handles timezone conversions
    - Persists queue to JSON file
    - Supports multiple channels with different schedules
    """

    def __init__(self, config_dir: Path):
        """
        Initialize scheduler.

        Args:
            config_dir: Path to config directory (contains publish_queue.json)
        """
        self.config_dir = config_dir
        self.queue_path = config_dir / "publish_queue.json"
        self._queue: Optional[PublishQueue] = None

    # ========================================================================
    # QUEUE PERSISTENCE
    # ========================================================================

    def _load_queue(self) -> PublishQueue:
        """Load queue from file or create new"""
        if self._queue is not None:
            return self._queue

        if self.queue_path.exists():
            try:
                with open(self.queue_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._queue = PublishQueue.model_validate(data)
                logger.debug(f"Loaded publish queue from {self.queue_path}")
            except Exception as e:
                logger.warning(f"Failed to load queue, creating new: {e}")
                self._queue = PublishQueue()
        else:
            self._queue = PublishQueue()

        return self._queue

    def _save_queue(self) -> None:
        """Save queue to file"""
        if self._queue is None:
            return

        self.config_dir.mkdir(parents=True, exist_ok=True)

        with open(self.queue_path, "w", encoding="utf-8") as f:
            json.dump(self._queue.model_dump(mode="json"), f, indent=2, default=str)

        logger.debug(f"Saved publish queue to {self.queue_path}")

    # ========================================================================
    # CHANNEL MANAGEMENT
    # ========================================================================

    def get_channel_queue(self, channel_id: str, timezone: str = "America/New_York") -> ChannelQueue:
        """
        Get or create queue for channel.

        Args:
            channel_id: Channel identifier
            timezone: Timezone for scheduling (default: Eastern Time)

        Returns:
            ChannelQueue instance
        """
        queue = self._load_queue()

        if channel_id not in queue.channels:
            queue.channels[channel_id] = ChannelQueue(
                channel_id=channel_id,
                timezone=timezone,
            )
            self._save_queue()

        return queue.channels[channel_id]

    def set_channel_schedule(
        self,
        channel_id: str,
        schedule: Dict[str, Optional[str]],
        timezone: str = "America/New_York"
    ) -> None:
        """
        Set posting schedule for a channel.

        Args:
            channel_id: Channel identifier
            schedule: Dict mapping weekday names to times (24h format) or None
            timezone: Timezone for the schedule

        Example:
            scheduler.set_channel_schedule("glaze_city", {
                "monday": "16:00",
                "tuesday": "15:00",
                ...
            })
        """
        channel_queue = self.get_channel_queue(channel_id, timezone)
        channel_queue.schedule = schedule
        channel_queue.timezone = timezone
        self._save_queue()

        logger.info(f"Updated schedule for channel {channel_id}")

    # ========================================================================
    # SCHEDULING LOGIC
    # ========================================================================

    def get_next_available_slot(
        self,
        channel_id: str,
        timezone: str = "America/New_York"
    ) -> Tuple[datetime, str]:
        """
        Find the next available publication slot for a channel.

        Logic:
        1. Get channel schedule and existing queue
        2. Find the latest scheduled date (or today if queue empty)
        3. Find next weekday with posting time
        4. If today and before posting time, use today
        5. Return UTC datetime and local time string

        Args:
            channel_id: Channel identifier
            timezone: Timezone for scheduling

        Returns:
            Tuple of (UTC datetime, local time string)
        """
        channel_queue = self.get_channel_queue(channel_id, timezone)
        tz = ZoneInfo(channel_queue.timezone)
        now_local = datetime.now(tz)

        # Find the latest scheduled date from queue (only future/scheduled entries)
        latest_date = None
        for entry in channel_queue.entries:
            if entry.status == PublishStatus.SCHEDULED:
                entry_local = entry.scheduled_datetime.astimezone(tz)
                if entry_local.date() >= now_local.date():
                    if latest_date is None or entry_local.date() > latest_date:
                        latest_date = entry_local.date()

        # Start searching from the day after latest scheduled, or today
        if latest_date:
            search_date = latest_date + timedelta(days=1)
            logger.debug(f"Queue has entries, searching from {search_date}")
        else:
            search_date = now_local.date()
            logger.debug(f"Queue empty, searching from today {search_date}")

        # Find next available slot (max 14 days ahead to prevent infinite loop)
        for _ in range(14):
            weekday_name = WEEKDAY_NAMES[search_date.weekday()]
            posting_time = channel_queue.schedule.get(weekday_name)

            if posting_time:
                # This day has a posting slot
                hour, minute = map(int, posting_time.split(":"))
                slot_local = datetime(
                    search_date.year,
                    search_date.month,
                    search_date.day,
                    hour,
                    minute,
                    tzinfo=tz
                )

                # Check if this slot is in the future
                if slot_local > now_local:
                    # Check if this slot is not already taken
                    slot_taken = False
                    for entry in channel_queue.entries:
                        if entry.status == PublishStatus.SCHEDULED:
                            entry_local = entry.scheduled_datetime.astimezone(tz)
                            if entry_local.date() == search_date:
                                slot_taken = True
                                break

                    if not slot_taken:
                        slot_utc = slot_local.astimezone(ZoneInfo("UTC"))
                        local_str = slot_local.strftime("%Y-%m-%d %H:%M %Z")

                        logger.info(f"Next available slot: {local_str}")
                        return slot_utc, local_str

            # Move to next day
            search_date += timedelta(days=1)

        # Fallback: if no slot found in 14 days, something is wrong
        raise ValueError(f"No available slot found in next 14 days for channel {channel_id}")

    # ========================================================================
    # QUEUE OPERATIONS
    # ========================================================================

    def schedule_project(
        self,
        channel_id: str,
        project_id: str,
        scheduled_datetime: Optional[datetime] = None,
        timezone: str = "America/New_York"
    ) -> QueueEntry:
        """
        Schedule a project for publication.

        Args:
            channel_id: Channel identifier
            project_id: Project identifier
            scheduled_datetime: Specific datetime (UTC) or None for auto-schedule
            timezone: Timezone for scheduling

        Returns:
            QueueEntry with scheduled datetime
        """
        channel_queue = self.get_channel_queue(channel_id, timezone)
        tz = ZoneInfo(channel_queue.timezone)

        # Auto-schedule if no datetime provided
        if scheduled_datetime is None:
            scheduled_datetime, local_str = self.get_next_available_slot(channel_id, timezone)
        else:
            local_str = scheduled_datetime.astimezone(tz).strftime("%Y-%m-%d %H:%M %Z")

        # Check if project already scheduled
        for entry in channel_queue.entries:
            if entry.project_id == project_id and entry.status == PublishStatus.SCHEDULED:
                logger.warning(f"Project {project_id} already scheduled for {entry.scheduled_datetime_local}")
                return entry

        # Create new entry
        entry = QueueEntry(
            project_id=project_id,
            scheduled_datetime=scheduled_datetime,
            scheduled_datetime_local=local_str,
            status=PublishStatus.SCHEDULED,
        )

        channel_queue.entries.append(entry)
        self._save_queue()

        logger.success(f"Scheduled {project_id} for {local_str}")
        return entry

    def update_entry_status(
        self,
        channel_id: str,
        project_id: str,
        status: PublishStatus,
        video_id: Optional[str] = None
    ) -> Optional[QueueEntry]:
        """
        Update status of a queue entry.

        Args:
            channel_id: Channel identifier
            project_id: Project identifier
            status: New status
            video_id: YouTube video ID (for published status)

        Returns:
            Updated entry or None if not found
        """
        channel_queue = self.get_channel_queue(channel_id)

        for entry in channel_queue.entries:
            if entry.project_id == project_id:
                entry.status = status
                if video_id:
                    entry.video_id = video_id
                self._save_queue()
                logger.info(f"Updated {project_id} status to {status.value}")
                return entry

        logger.warning(f"Entry not found: {project_id}")
        return None

    def get_pending_publications(self, channel_id: str) -> List[QueueEntry]:
        """
        Get all pending publications for a channel.

        Returns entries that are scheduled and due (datetime <= now).
        """
        channel_queue = self.get_channel_queue(channel_id)
        now_utc = datetime.now(ZoneInfo("UTC"))

        pending = []
        for entry in channel_queue.entries:
            if entry.status == PublishStatus.SCHEDULED:
                if entry.scheduled_datetime <= now_utc:
                    pending.append(entry)

        return sorted(pending, key=lambda e: e.scheduled_datetime)

    def get_scheduled_publications(self, channel_id: str) -> List[QueueEntry]:
        """
        Get all future scheduled publications for a channel.
        """
        channel_queue = self.get_channel_queue(channel_id)
        now_utc = datetime.now(ZoneInfo("UTC"))

        scheduled = []
        for entry in channel_queue.entries:
            if entry.status == PublishStatus.SCHEDULED:
                if entry.scheduled_datetime > now_utc:
                    scheduled.append(entry)

        return sorted(scheduled, key=lambda e: e.scheduled_datetime)

    def cancel_publication(self, channel_id: str, project_id: str) -> bool:
        """Cancel a scheduled publication."""
        entry = self.update_entry_status(channel_id, project_id, PublishStatus.CANCELLED)
        return entry is not None

    # ========================================================================
    # DISPLAY HELPERS
    # ========================================================================

    def print_queue(self, channel_id: str) -> None:
        """Print formatted queue for a channel."""
        channel_queue = self.get_channel_queue(channel_id)

        print(f"\n{'='*60}")
        print(f"Publication Queue: {channel_id}")
        print(f"Timezone: {channel_queue.timezone}")
        print(f"{'='*60}")

        scheduled = self.get_scheduled_publications(channel_id)

        if not scheduled:
            print("No scheduled publications")
        else:
            for i, entry in enumerate(scheduled, 1):
                print(f"{i}. {entry.project_id}")
                print(f"   {entry.scheduled_datetime_local}")
                print(f"   Status: {entry.status.value}")
                print()

        print(f"{'='*60}\n")


# ============================================================================
# FACTORY FUNCTION
# ============================================================================

def create_scheduler(config_dir: Optional[Path] = None) -> PublicationScheduler:
    """
    Create a scheduler instance.

    Args:
        config_dir: Path to config directory (default: ./config)

    Returns:
        PublicationScheduler instance
    """
    if config_dir is None:
        config_dir = Path(__file__).parent.parent.parent / "config"

    return PublicationScheduler(config_dir)
