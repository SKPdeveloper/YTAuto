"""
A/B Rotation Store — JSON Persistence Layer

Follows the same pattern as scheduler.py:
- Main state: config/ab_rotation.json
- Append-only metrics log: config/ab_metrics.jsonl (one JSON object per line)

Resilience:
- Atomic save: write to .tmp then os.replace()
- Backup: .bak copy before overwrite
- Load fallback: try .bak if main file corrupted
"""

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from loguru import logger

from .ab_models import (
    ABRotationStore,
    ABStatus,
    MetricsSnapshot,
    VideoABRecord,
)


class ABStore:
    """
    Persistent storage for A/B rotation state.

    State file: config/ab_rotation.json
    Metrics log: config/ab_metrics.jsonl (append-only)
    """

    def __init__(self, config_dir: Optional[Path] = None):
        if config_dir is None:
            config_dir = Path(__file__).parent.parent.parent / "config"

        self.config_dir = config_dir
        self.state_path = config_dir / "ab_rotation.json"
        self.metrics_path = config_dir / "ab_metrics.jsonl"
        self._store: Optional[ABRotationStore] = None

    # ========================================================================
    # LOAD / SAVE
    # ========================================================================

    def load(self) -> ABRotationStore:
        """Load store from disk, or create empty. Falls back to .bak if main corrupted."""
        if self._store is not None:
            return self._store

        if self.state_path.exists():
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._store = ABRotationStore.model_validate(data)
                logger.debug(f"Loaded AB store: {len(self._store.videos)} videos")
                return self._store
            except Exception as e:
                logger.warning(f"Failed to load AB store from main file: {e}")

        # Fallback: try .bak
        bak_path = self.state_path.with_suffix(".json.bak")
        if bak_path.exists():
            try:
                with open(bak_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._store = ABRotationStore.model_validate(data)
                logger.warning(
                    f"Recovered AB store from backup ({len(self._store.videos)} videos). "
                    f"Main file was missing or corrupted."
                )
                # Restore main file from backup
                self.save()
                return self._store
            except Exception as e2:
                logger.error(f"Backup also corrupted: {e2}")

        self._store = ABRotationStore()
        return self._store

    def save(self) -> None:
        """Save store to disk atomically (write .tmp → backup .bak → os.replace)."""
        if self._store is None:
            return

        self.config_dir.mkdir(parents=True, exist_ok=True)

        tmp_path = self.state_path.with_suffix(".json.tmp")
        bak_path = self.state_path.with_suffix(".json.bak")

        # Write to temp file first
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(
                self._store.model_dump(mode="json"),
                f,
                indent=2,
                default=str,
            )
            f.flush()
            os.fsync(f.fileno())

        # Backup current state before replacing
        if self.state_path.exists():
            try:
                shutil.copy2(str(self.state_path), str(bak_path))
            except Exception as e:
                logger.warning(f"Failed to create backup: {e}")

        # Atomic replace (on Windows os.replace is as atomic as possible)
        os.replace(str(tmp_path), str(self.state_path))

        logger.debug(f"Saved AB store to {self.state_path}")

    def reload(self) -> ABRotationStore:
        """Force reload from disk (useful for daemon that shares state)."""
        self._store = None
        return self.load()

    # ========================================================================
    # QUERIES
    # ========================================================================

    def get_active_videos(self) -> List[VideoABRecord]:
        """Get all videos that are actively being monitored."""
        store = self.load()
        return [v for v in store.videos if v.status == ABStatus.MONITORING]

    def get_video(self, video_id: str) -> Optional[VideoABRecord]:
        """Get a video record by YouTube video ID."""
        store = self.load()
        for v in store.videos:
            if v.video_id == video_id:
                return v
        return None

    def get_all_videos(self) -> List[VideoABRecord]:
        """Get all video records."""
        store = self.load()
        return store.videos

    # ========================================================================
    # MUTATIONS
    # ========================================================================

    def register_video(self, record: VideoABRecord) -> None:
        """Add a new video to monitoring."""
        store = self.load()

        # Check for duplicate
        for v in store.videos:
            if v.video_id == record.video_id:
                logger.warning(f"Video {record.video_id} already registered, updating")
                store.videos.remove(v)
                break

        store.videos.append(record)
        self.save()
        logger.info(f"Registered video for AB monitoring: {record.video_id} ({len(record.variants)} variants)")

    def update_video(self, record: VideoABRecord) -> None:
        """Update an existing video record."""
        store = self.load()

        for i, v in enumerate(store.videos):
            if v.video_id == record.video_id:
                store.videos[i] = record
                self.save()
                return

        logger.warning(f"Video {record.video_id} not found in store, adding")
        store.videos.append(record)
        self.save()

    def stop_video(self, video_id: str) -> bool:
        """Stop monitoring a video (set status to STOPPED)."""
        video = self.get_video(video_id)
        if not video:
            return False
        video.status = ABStatus.STOPPED
        video.final_variant = video.current_variant
        self.update_video(video)
        logger.info(f"Stopped monitoring: {video_id}")
        return True

    # ========================================================================
    # METRICS LOG (append-only JSONL)
    # ========================================================================

    def append_metrics(self, video_id: str, snapshot: MetricsSnapshot) -> None:
        """Append a metrics snapshot to the JSONL log."""
        self.config_dir.mkdir(parents=True, exist_ok=True)

        entry = {
            "video_id": video_id,
            "timestamp": snapshot.timestamp.isoformat(),
            "views": snapshot.views,
            "likes": snapshot.likes,
            "comments": snapshot.comments,
        }

        with open(self.metrics_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
