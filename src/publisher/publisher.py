"""
Publisher - Core Publishing Logic for YTAutoPublisher

Orchestrates the entire publishing process:
1. Read project brief
2. Auto-schedule if enabled
3. Clean video metadata
4. Upload to YouTube (as private with scheduled time)
5. Add pinned comment
6. Update publish queue
7. Archive project
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Optional, Tuple
from datetime import datetime

from loguru import logger

from .models import (
    PublishStatus,
    PublishStatusRecord,
    PublishEvent,
    PrivacyStatus,
)
from .config_manager import ConfigManager, get_config_manager
from .metadata_cleaner import MetadataCleaner, get_metadata_cleaner
from .youtube_api import YouTubeAPI
from .scheduler import PublicationScheduler, create_scheduler, PublishStatus as QueueStatus
from .ab_models import ABStatus, VariantData, VideoABRecord, parse_metadata_variants
from .ab_store import ABStore

# HumanCommenter DISABLED — all comment pinning is done manually by the user
# to avoid YouTube anti-fraud detection. See: CLAUDE.md / memory notes.
HUMAN_COMMENTER_AVAILABLE = False


class Publisher:
    """
    Main publisher class.

    Handles the complete workflow of publishing a video to YouTube.
    """

    def __init__(
        self,
        config_manager: Optional[ConfigManager] = None,
        metadata_cleaner: Optional[MetadataCleaner] = None,
        scheduler: Optional[PublicationScheduler] = None,
    ):
        """
        Initialize publisher.

        Args:
            config_manager: Configuration manager instance
            metadata_cleaner: FFmpeg metadata cleaner instance
            scheduler: Publication scheduler instance
        """
        self.config = config_manager or get_config_manager()
        self.cleaner = metadata_cleaner or get_metadata_cleaner()
        self.scheduler = scheduler or create_scheduler()

    # ========================================================================
    # PUBLISH SINGLE PROJECT
    # ========================================================================

    def publish(
        self,
        project_id: str,
        dry_run: bool = False,
        skip_metadata_clean: bool = False,
        skip_archive: bool = False,
    ) -> Tuple[bool, PublishStatusRecord]:
        """
        Publish a single project to YouTube.

        Args:
            project_id: Project ID to publish
            dry_run: If True, validate but don't actually upload
            skip_metadata_clean: Skip FFmpeg metadata cleaning
            skip_archive: Don't move to archive after publish

        Returns:
            Tuple of (success, publish_status)
        """
        logger.info(f"{'[DRY RUN] ' if dry_run else ''}Publishing: {project_id}")

        # Initialize status
        status = PublishStatusRecord(
            status=PublishStatus.PENDING,
            attempts=0,
        )

        try:
            # Step 1: Load and validate project brief
            brief = self.config.load_project_brief(project_id)
            if not brief:
                status.status = PublishStatus.FAILED
                status.error = "project_brief.json not found"
                logger.error(status.error)
                return False, status

            logger.info(f"Title: {brief.youtube.title}")

            # Step 2: Check publish config
            if not brief.publish_config:
                status.status = PublishStatus.FAILED
                status.error = "publish_config not found in brief"
                logger.error(status.error)
                return False, status

            target_channel = brief.publish_config.target_channel
            status.channel_id = target_channel

            # Step 2b: Auto-schedule if enabled
            scheduled_datetime = brief.publish_config.scheduled_datetime
            scheduled_local_str = None

            if brief.publish_config.auto_schedule and not scheduled_datetime:
                logger.info("Auto-scheduling publication...")
                scheduled_datetime, scheduled_local_str = self.scheduler.get_next_available_slot(
                    channel_id=target_channel
                )
                logger.info(f"Scheduled for: {scheduled_local_str}")

            # If we have a scheduled datetime, privacy MUST be private (YouTube requirement)
            privacy_status = brief.publish_config.privacy_status
            if scheduled_datetime:
                privacy_status = PrivacyStatus.PRIVATE
                logger.info(f"Set privacy to PRIVATE for scheduled publish")

            # Step 3: Load channel config
            channel_config = self.config.load_channel_config(target_channel)
            if not channel_config:
                status.status = PublishStatus.FAILED
                status.error = f"Channel not configured: {target_channel}"
                logger.error(status.error)
                return False, status

            if not channel_config.settings.active:
                status.status = PublishStatus.FAILED
                status.error = f"Channel is inactive: {target_channel}"
                logger.error(status.error)
                return False, status

            # Step 4: Find video file
            video_path = self.config.find_video_file(project_id)
            if not video_path:
                status.status = PublishStatus.FAILED
                status.error = "No video file found"
                logger.error(status.error)
                return False, status

            logger.info(f"Video: {video_path.name} ({video_path.stat().st_size / 1024 / 1024:.1f} MB)")

            # Step 5: Clean metadata (optional)
            if not skip_metadata_clean and self.cleaner.is_ffmpeg_available():
                logger.info("Cleaning video metadata...")

                if not dry_run:
                    success, error = self.cleaner.clean_in_place(video_path)
                    if not success:
                        logger.warning(f"Metadata cleaning failed: {error}")
                else:
                    logger.info("[DRY RUN] Would clean metadata")
            else:
                if not self.cleaner.is_ffmpeg_available():
                    logger.warning("FFmpeg not available, skipping metadata cleaning")

            # Build final description (before dry_run check so it's available for logging)
            description = brief.youtube.description
            if brief.save_trigger:
                description = f"{description}\n\n💾 {brief.save_trigger}"

            # Step 6: Upload to YouTube
            if dry_run:
                logger.info("[DRY RUN] Would upload video to YouTube")
                logger.info(f"  Channel: {channel_config.channel_name}")
                logger.info(f"  Privacy: {privacy_status}")
                if scheduled_datetime:
                    logger.info(f"  Scheduled: {scheduled_local_str or scheduled_datetime}")
                logger.info(f"  Title: {brief.youtube.title}")
                logger.info(f"  Description: {description[:100]}...")
                logger.info(f"  Tags: {brief.youtube.tags}")
                if brief.save_trigger:
                    logger.info(f"  Save trigger: {brief.save_trigger}")

                status.status = PublishStatus.PENDING
                status.error = "Dry run - not uploaded"
                return True, status

            # Create YouTube API client
            youtube = YouTubeAPI(
                channel_config=channel_config,
                client_secrets_path=self.config.get_client_secrets_path(target_channel),
                token_path=self.config.get_token_path(target_channel),
            )

            status.status = PublishStatus.UPLOADING
            status.attempts += 1

            # Log event: upload started
            self.config.append_history_event(PublishEvent(
                event="upload_started",
                project_id=project_id,
                channel_id=target_channel,
            ))

            # Upload video (with resumable support)
            success, video_id, error = youtube.upload_video(
                video_path=video_path,
                title=brief.youtube.title,
                description=description,
                tags=brief.youtube.tags,
                category_id=channel_config.settings.default_category_id,
                privacy_status=privacy_status,
                scheduled_datetime=scheduled_datetime,
                made_for_kids=channel_config.settings.made_for_kids,
                progress_callback=self._progress_callback,
                project_id=project_id,  # Enable resumable upload
            )

            if not success:
                status.status = PublishStatus.FAILED
                status.error = error
                self.config.save_publish_status(project_id, status)

                self.config.append_history_event(PublishEvent(
                    event="upload_failed",
                    project_id=project_id,
                    channel_id=target_channel,
                    error=error,
                ))

                return False, status

            status.video_id = video_id
            status.video_url = f"https://youtube.com/shorts/{video_id}"

            # Log event: upload completed
            self.config.append_history_event(PublishEvent(
                event="upload_completed",
                project_id=project_id,
                channel_id=target_channel,
                video_id=video_id,
            ))

            # Register for A/B monitoring (non-fatal, skipped if disabled)
            if AB_ENABLED:
                self._register_for_ab_monitoring(
                    project_id=project_id,
                    video_id=video_id,
                    channel_id=target_channel,
                    scheduled_datetime=scheduled_datetime,
                )

            # Update scheduler queue if scheduled
            if scheduled_datetime:
                entry = self.scheduler.schedule_project(
                    channel_id=target_channel,
                    project_id=project_id,
                    scheduled_datetime=scheduled_datetime,
                )
                entry.video_id = video_id
                self.scheduler.update_entry_status(
                    channel_id=target_channel,
                    project_id=project_id,
                    status=QueueStatus.SCHEDULED,
                    video_id=video_id,
                )
                logger.info(f"Added to publish queue: {scheduled_local_str or scheduled_datetime}")

            # Step 7: Post comment via YouTube API (user pins manually)
            # Browser automation (HumanCommenter) is DISABLED to avoid YouTube
            # anti-fraud detection. The comment is posted via official API,
            # but PINNING must be done manually via YouTube Studio.
            if brief.youtube.pinned_comment:
                status.pinned_comment_text = brief.youtube.pinned_comment

                if scheduled_datetime:
                    # Video is scheduled (private with publishAt) — defer comment
                    # to A/B daemon which will post it when the video goes live.
                    self._save_deferred_comment(
                        video_id=video_id,
                        project_id=project_id,
                        channel_id=target_channel,
                        comment_text=brief.youtube.pinned_comment,
                        scheduled_go_live=scheduled_datetime,
                    )
                    logger.info(
                        f"Comment deferred to A/B daemon — will auto-post when video goes live "
                        f"({scheduled_local_str or scheduled_datetime})"
                    )
                else:
                    try:
                        comment_ok, comment_id, comment_err = youtube.insert_comment_thread(
                            video_id=video_id,
                            text=brief.youtube.pinned_comment,
                        )
                        if comment_ok:
                            status.comment_id = comment_id
                            logger.success(f"Comment posted via API (id={comment_id}) — PIN IT manually in YouTube Studio")

                            self.config.append_history_event(PublishEvent(
                                event="comment_posted",
                                project_id=project_id,
                                video_id=video_id,
                                comment_id=comment_id,
                                details={"needs_manual_pin": True},
                            ))
                        else:
                            logger.warning(f"Failed to post comment via API: {comment_err}")
                    except Exception as e:
                        logger.warning(f"Comment posting failed: {e}")

            # Step 8: Update status
            status.status = (
                PublishStatus.SCHEDULED
                if scheduled_datetime
                else PublishStatus.PUBLISHED
            )
            status.published_at = datetime.now()

            self.config.save_publish_status(project_id, status)

            # Step 9: Archive project
            if not skip_archive:
                global_settings = self.config.load_global_settings()

                if global_settings.post_publish.move_to_archive:
                    logger.info("Moving to archive...")
                    archive_path = self.config.archive_project(project_id)

                    self.config.append_history_event(PublishEvent(
                        event="archived",
                        project_id=project_id,
                        details={"archive_path": str(archive_path)},
                    ))

            logger.success(f"Published: {status.video_url}")

            # Ensure A/B daemon is running (non-fatal)
            from src.publisher.ab_config import AB_ENABLED
            if AB_ENABLED:
                self._ensure_ab_daemon()
            else:
                logger.info("A/B rotation disabled (AB_ENABLED=False)")

            return True, status

        except Exception as e:
            status.status = PublishStatus.FAILED
            status.error = str(e)

            logger.error(f"Publish failed: {e}")

            self.config.append_history_event(PublishEvent(
                event="error",
                project_id=project_id,
                error=str(e),
            ))

            try:
                self.config.save_publish_status(project_id, status)
            except Exception:
                pass

            return False, status

    def _progress_callback(self, uploaded: int, total: int) -> None:
        """Progress callback for video upload"""
        if total > 0:
            pct = int(uploaded / total * 100)
            logger.info(f"Upload progress: {pct}% ({uploaded / 1024 / 1024:.1f} MB / {total / 1024 / 1024:.1f} MB)")

    def _ensure_ab_daemon(self) -> None:
        """Ensure A/B daemon is running as a detached process. Non-fatal."""
        try:
            import subprocess

            pid_file = self.config.base_path / "ab_daemon.pid"

            # Check existing PID
            if pid_file.exists():
                try:
                    pid = int(pid_file.read_text().strip())
                    if self._is_pid_alive(pid):
                        logger.debug(f"AB daemon already running (PID {pid})")
                        return
                    else:
                        pid_file.unlink(missing_ok=True)
                except (ValueError, OSError):
                    pid_file.unlink(missing_ok=True)

            # Start detached daemon
            python_exe = sys.executable
            cmd = [python_exe, "-X", "utf8", "-m", "src.publisher.ab_daemon"]
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

            proc = subprocess.Popen(
                cmd,
                cwd=str(self.config.base_path),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
            pid_file.write_text(str(proc.pid))
            logger.info(f"AB daemon started (PID {proc.pid})")

        except Exception as e:
            logger.warning(f"Failed to start AB daemon: {e}")

    @staticmethod
    def _is_pid_alive(pid: int) -> bool:
        """Check if a process is alive (Windows-compatible)."""
        if sys.platform == "win32":
            try:
                import ctypes
                handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
                if handle:
                    ctypes.windll.kernel32.CloseHandle(handle)
                    return True
                return False
            except Exception:
                return False
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    def _register_for_ab_monitoring(
        self,
        project_id: str,
        video_id: str,
        channel_id: str,
        scheduled_datetime: Optional[datetime] = None,
    ) -> None:
        """
        Register a freshly uploaded video for A/B metadata rotation.

        Loads metadata_variants from gen1_output.json or project_brief.json,
        and registers if at least 2 variants present.

        If scheduled_datetime is set (future publication), variant_start_time
        is set to that moment so the A/B timer starts when the video goes live,
        not when it was uploaded.

        Non-fatal: if anything fails, just log a warning. Upload already succeeded.
        """
        try:
            import json
            from datetime import timezone

            # Find metadata_variants: try gen1_output.json first, then project_brief.json
            project_dir = self.config.get_project_dir(project_id)
            gen1_data = None
            source_path = None

            gen1_path = project_dir / "gen1_output.json"
            brief_path = project_dir / "project_brief.json"

            if gen1_path.exists():
                source_path = gen1_path
            elif brief_path.exists():
                source_path = brief_path
            else:
                logger.debug(f"No gen1_output.json or project_brief.json found for {project_id}, skipping AB registration")
                return

            with open(source_path, "r", encoding="utf-8") as f:
                gen1_data = json.load(f)

            # Extract metadata_variants via shared parser
            variants, warnings = parse_metadata_variants(gen1_data)
            for w in warnings:
                logger.debug(f"{project_id}: {w}")

            if len(variants) < 2:
                logger.debug(f"Only {len(variants)} valid variants found, need at least 2 for AB rotation")
                return

            # Use first available variant (usually "A")
            first_variant = sorted(variants.keys())[0]

            # If scheduled for future — timer starts at go-live, not now
            now = datetime.now(timezone.utc)
            go_live = scheduled_datetime if scheduled_datetime and scheduled_datetime > now else None
            start_time = go_live or now

            # Create and register record
            record = VideoABRecord(
                video_id=video_id,
                project_id=project_id,
                channel_id=channel_id,
                current_variant=first_variant,
                variants=variants,
                gen1_output_path=str(source_path),
                scheduled_go_live=go_live,
                variant_start_time=start_time,
            )

            store = ABStore(config_dir=self.config.config_dir)
            store.register_video(record)

            if go_live:
                logger.info(
                    f"Registered {video_id} for AB monitoring "
                    f"({len(variants)} variants, timer starts at {go_live.isoformat()})"
                )
            else:
                logger.info(f"Registered {video_id} for AB monitoring ({len(variants)} variants)")

        except Exception as e:
            logger.warning(f"Failed to register for AB monitoring: {e}")

    def _save_deferred_comment(
        self,
        video_id: str,
        project_id: str,
        channel_id: str,
        comment_text: str,
        scheduled_go_live: datetime,
    ) -> None:
        """
        Save a comment for deferred posting by the A/B daemon.

        When a video is scheduled (private with publishAt), the comment can't
        be posted immediately. Instead, we save it to the AB record and the
        A/B daemon will post it when the video goes live.

        If the video was already registered for AB monitoring, updates the
        existing record. If not (e.g., no AB variants), creates a minimal
        record just for comment tracking.

        Non-fatal: errors logged but don't block the publish flow.
        """
        try:
            from datetime import timezone

            store = ABStore(config_dir=self.config.config_dir)

            # Try to update existing AB record
            def _set_comment(video: VideoABRecord) -> bool:
                video.pending_comment_text = comment_text
                return True

            result = store.locked_update(
                video_id, _set_comment, require_monitoring=False
            )

            if result is not None:
                logger.info(f"Saved deferred comment to existing AB record for {video_id}")
                return

            # No AB record exists — create a minimal one for comment tracking
            now = datetime.now(timezone.utc)
            go_live = scheduled_go_live if scheduled_go_live > now else None

            record = VideoABRecord(
                video_id=video_id,
                project_id=project_id,
                channel_id=channel_id,
                scheduled_go_live=go_live,
                variant_start_time=go_live or now,
                pending_comment_text=comment_text,
            )
            store.register_video(record)
            logger.info(f"Registered {video_id} for deferred comment posting (no AB variants)")

        except Exception as e:
            logger.warning(f"Failed to save deferred comment: {e}")

    # ========================================================================
    # PUBLISH ALL PENDING
    # ========================================================================

    def publish_all(
        self,
        dry_run: bool = False,
        limit: Optional[int] = None,
    ) -> Tuple[int, int, list]:
        """
        Publish all pending projects.

        Args:
            dry_run: If True, validate but don't upload
            limit: Maximum number of projects to publish

        Returns:
            Tuple of (success_count, fail_count, list_of_results)
        """
        pending = self.config.list_pending_projects()

        if not pending:
            logger.info("No pending projects found")
            return 0, 0, []

        if limit:
            pending = pending[:limit]

        logger.info(f"Found {len(pending)} pending projects")

        success_count = 0
        fail_count = 0
        results = []

        for project_id in pending:
            success, status = self.publish(project_id, dry_run=dry_run)

            results.append({
                "project_id": project_id,
                "success": success,
                "status": status,
            })

            if success:
                success_count += 1
            else:
                fail_count += 1

        logger.info(f"Published: {success_count}/{len(pending)}, Failed: {fail_count}")

        return success_count, fail_count, results

    # ========================================================================
    # STATUS CHECK
    # ========================================================================

    def get_project_status(self, project_id: str) -> Optional[dict]:
        """
        Get current status of a project.

        Returns:
            Status dict or None if project not found
        """
        brief = self.config.load_project_brief(project_id)
        if not brief:
            return None

        status = self.config.load_publish_status(project_id)
        video_path = self.config.find_video_file(project_id)

        return {
            "project_id": project_id,
            "title": brief.youtube.title,
            "target_channel": brief.publish_config.target_channel if brief.publish_config else None,
            "video_found": video_path is not None,
            "video_path": str(video_path) if video_path else None,
            "publish_status": status.model_dump() if status else None,
        }


# Convenience function
def publish_project(project_id: str, **kwargs) -> Tuple[bool, PublishStatusRecord]:
    """Publish a single project"""
    publisher = Publisher()
    return publisher.publish(project_id, **kwargs)
