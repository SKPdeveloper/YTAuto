"""
A/B Rotation Store — JSON Persistence Layer

Follows the same pattern as scheduler.py:
- Main state: config/ab_rotation.json
- Append-only metrics log: config/ab_metrics.jsonl (one JSON object per line)

Resilience:
- Atomic save: write to .tmp then os.replace()
- Backup: .bak copy before overwrite
- Load fallback: try .bak if main file corrupted
- File locking: sidecar .lock file prevents concurrent write clobber
"""

import json
import os
import platform
import shutil
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, TypeVar

from loguru import logger

from .ab_models import (
    ABRotationStore,
    ABStatus,
    MetricsSnapshot,
    VideoABRecord,
)


# ============================================================================
# Platform-aware file locking helpers
# ============================================================================

if platform.system() == "Windows":
    import msvcrt

    def _lock_file(fh):
        """Acquire exclusive lock on open file handle (Windows)."""
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock_file(fh):
        """Release exclusive lock on open file handle (Windows)."""
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _lock_file(fh):
        """Acquire exclusive lock on open file handle (Unix)."""
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock_file(fh):
        """Release exclusive lock on open file handle (Unix)."""
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


T = TypeVar("T")


class ABStore:
    """
    Persistent storage for A/B rotation state.

    State file: config/ab_rotation.json
    Metrics log: config/ab_metrics.jsonl (append-only)

    Thread/process safety:
    - All mutations acquire an exclusive file lock via _file_lock()
    - The daemon should use locked_update() for atomic read-modify-write
    """

    def __init__(self, config_dir: Optional[Path] = None):
        if config_dir is None:
            config_dir = Path(__file__).parent.parent.parent / "config"

        self.config_dir = config_dir.resolve()
        self.state_path = self.config_dir / "ab_rotation.json"
        self.metrics_path = self.config_dir / "ab_metrics.jsonl"
        self.lock_path = self.config_dir / "ab_rotation.lock"
        self._store: Optional[ABRotationStore] = None

    @contextmanager
    def _file_lock(self, timeout: float = 10.0):
        """
        Acquire an exclusive file lock using a sidecar .lock file.

        Prevents concurrent writes from pipeline + daemon clobbering each other.
        Invalidates the in-memory cache on entry AND exit so we always read
        fresh from disk and never serve stale data after the lock is released.
        """
        self.config_dir.mkdir(parents=True, exist_ok=True)
        fh = None
        acquired = False
        try:
            # Open in "r+b" (non-truncating). Create with sentinel if absent.
            if not self.lock_path.exists():
                self.lock_path.write_bytes(b" ")
            fh = open(self.lock_path, "r+b")
            fh.seek(0)

            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    _lock_file(fh)
                    acquired = True
                    break
                except (OSError, IOError):
                    time.sleep(0.05)
            if not acquired:
                raise TimeoutError(
                    f"Could not acquire AB store lock within {timeout}s"
                )
            # Invalidate cache — force fresh disk read inside the lock
            self._store = None
            yield
        finally:
            # Invalidate cache after lock release so next read is fresh
            self._store = None
            if acquired and fh is not None:
                try:
                    _unlock_file(fh)
                except (OSError, IOError):
                    pass
            if fh is not None:
                fh.close()

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
        """Force reload from disk. Safe without lock because save() uses atomic os.replace."""
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
    # MUTATIONS (locked)
    #
    # Public methods acquire _file_lock, then delegate to _impl (unlocked).
    # This avoids deadlock in stop_video() which needs both update + get.
    # ========================================================================

    def _register_video_impl(self, record: VideoABRecord) -> None:
        """Add a new video to monitoring (caller must hold lock)."""
        store = self.load()

        # Check for duplicate — skip if actively monitoring to avoid resetting progress
        for v in store.videos:
            if v.video_id == record.video_id:
                if v.status == ABStatus.MONITORING:
                    logger.warning(
                        f"Video {record.video_id} already actively monitoring, skipping re-register"
                    )
                    return
                logger.warning(f"Video {record.video_id} already registered (status={v.status.value}), replacing")
                store.videos.remove(v)
                break

        store.videos.append(record)
        self.save()
        logger.info(f"Registered video for AB monitoring: {record.video_id} ({len(record.variants)} variants)")

    def register_video(self, record: VideoABRecord) -> None:
        """Add a new video to monitoring (thread-safe)."""
        with self._file_lock():
            self._register_video_impl(record)

    def _update_video_impl(self, record: VideoABRecord) -> None:
        """Update an existing video record (caller must hold lock)."""
        store = self.load()

        for i, v in enumerate(store.videos):
            if v.video_id == record.video_id:
                store.videos[i] = record
                self.save()
                return

        logger.warning(f"Video {record.video_id} not found in store, adding")
        store.videos.append(record)
        self.save()

    def update_video(self, record: VideoABRecord) -> None:
        """Update an existing video record (thread-safe)."""
        with self._file_lock():
            self._update_video_impl(record)

    def stop_video(self, video_id: str) -> bool:
        """Stop monitoring a video (thread-safe)."""
        with self._file_lock():
            video = self.get_video(video_id)
            if not video:
                return False
            video.status = ABStatus.STOPPED
            video.final_variant = video.current_variant
            self._update_video_impl(video)
            logger.info(f"Stopped monitoring: {video_id}")
            return True

    # ========================================================================
    # ATOMIC READ-MODIFY-WRITE (for daemon / monitor)
    #
    # Holds the lock for the entire read → mutate → write cycle so that
    # concurrent modifications (CLI "ab stop", pipeline register) are not lost.
    # ========================================================================

    def locked_update(
        self,
        video_id: str,
        mutate_fn: Callable[[VideoABRecord], T],
        *,
        require_monitoring: bool = True,
    ) -> Optional[T]:
        """
        Atomic read-modify-write for a single video under the file lock.

        1. Acquires file lock
        2. Reads fresh video record from disk
        3. Calls mutate_fn(video) which mutates the record in-place and returns a result
        4. Saves the mutated record to disk
        5. Releases lock

        Args:
            require_monitoring: If True (default), returns None when status != MONITORING.
                Set to False for operations that must succeed regardless of status
                (e.g., committing a swap after YouTube API already changed metadata).

        Returns mutate_fn's return value, or None if video not found (or not monitoring
        when require_monitoring=True).
        """
        with self._file_lock():
            video = self.get_video(video_id)
            if not video:
                return None
            if require_monitoring and video.status != ABStatus.MONITORING:
                return None
            result = mutate_fn(video)
            self._update_video_impl(video)
            return result

    # ========================================================================
    # METRICS LOG (append-only JSONL)
    # ========================================================================

    def append_metrics(self, video_id: str, snapshot: MetricsSnapshot) -> None:
        """Append a metrics snapshot to the JSONL log.

        No file lock needed: JSONL is independent of the main state file,
        and single-line appends are atomic on POSIX. On Windows, each line
        is small enough (<200 bytes) for a single write() call.
        """
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
