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

# Import HumanCommenter for comment automation
try:
    from ..human_commenter import HumanCommenter, CommenterConfig
    HUMAN_COMMENTER_AVAILABLE = True
except ImportError:
    try:
        from human_commenter import HumanCommenter, CommenterConfig
        HUMAN_COMMENTER_AVAILABLE = True
    except ImportError:
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

            # Append save_trigger CTA to description if available
            description = brief.youtube.description
            if brief.save_trigger:
                description = f"{description}\n\n💾 {brief.save_trigger}"

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

            # Register for A/B monitoring (non-fatal)
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

            # Step 7: Add pinned comment
            if brief.youtube.pinned_comment:
                logger.info("Adding pinned comment...")

                # Use HumanCommenter with AdsPower if profile configured
                if channel_config.adspower_profile_id and HUMAN_COMMENTER_AVAILABLE:
                    logger.info("Using HumanCommenter for human-like behavior...")

                    commenter = HumanCommenter(CommenterConfig())
                    result = asyncio.get_event_loop().run_until_complete(
                        commenter.add_and_pin_comment(
                            video_id=video_id,
                            comment_text=brief.youtube.pinned_comment,
                            profile_id=channel_config.adspower_profile_id,
                            channel_keywords=channel_config.channel_keywords or None,
                            expected_region=channel_config.region,
                            expected_timezone=channel_config.timezone,
                        )
                    )

                    if result.success:
                        status.comment_id = "human_commenter"

                        self.config.append_history_event(PublishEvent(
                            event="comment_pinned",
                            project_id=project_id,
                            video_id=video_id,
                            comment_id="human_commenter",
                        ))
                    else:
                        logger.warning(f"Failed to add/pin comment: {result.error}")
                else:
                    if not HUMAN_COMMENTER_AVAILABLE:
                        logger.warning("HumanCommenter not available, skipping comment")
                    else:
                        logger.warning("No AdsPower profile configured, skipping comment")

            # Step 8: Update status
            status.status = (
                PublishStatus.SCHEDULED
                if brief.publish_config.scheduled_datetime
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

    def _register_for_ab_monitoring(
        self,
        project_id: str,
        video_id: str,
        channel_id: str,
        scheduled_datetime: Optional[datetime] = None,
    ) -> None:
        """
        Register a freshly uploaded video for A/B metadata rotation.

        Loads gen1_output.json from the project directory, extracts
        metadata_variants, and registers if all 4 variants present.

        If scheduled_datetime is set (future publication), variant_start_time
        is set to that moment so the A/B timer starts when the video goes live,
        not when it was uploaded.

        Non-fatal: if anything fails, just log a warning. Upload already succeeded.
        """
        try:
            import json
            from datetime import timezone

            # Find gen1_output.json
            project_dir = self.config.get_project_dir(project_id)
            gen1_path = project_dir / "gen1_output.json"

            if not gen1_path.exists():
                logger.debug(f"No gen1_output.json found for {project_id}, skipping AB registration")
                return

            with open(gen1_path, "r", encoding="utf-8") as f:
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
                gen1_output_path=str(gen1_path),
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
