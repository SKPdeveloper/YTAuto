"""
Human Commenter - Main Entry Point

Orchestrates the entire human-like comment workflow using
AdsPower browser profiles and Playwright automation.

Enhanced with:
- ProfileSeedGenerator for multi-factor seed management
- SessionState for persistent state across sessions
- BimodalDelay for realistic timing patterns
"""

import asyncio
from typing import Optional, List

from .client import AdsPowerPlaywrightClient
from .config import CommenterConfig, ProfileSeedGenerator
from .state import SessionState
from .workflow import CommentWorkflowFSM, WorkflowResult, WorkflowState
from .safety.logger import get_logger, configure_logging

logger = get_logger(__name__)


class HumanCommenter:
    """
    Main entry point for human-like YouTube comment automation.

    Connects to AdsPower browser profiles and executes a complete
    comment workflow with realistic human behaviors.

    Features:
    - Profile-specific behavior "fingerprints" via ProfileSeedGenerator
    - Session state persistence (scroll positions, visited pages)
    - Bimodal delays matching human cognitive patterns
    - 5 types of typing errors with natural corrections
    - Device-specific scroll normalization

    Usage:
        commenter = HumanCommenter(CommenterConfig())
        result = await commenter.add_and_pin_comment(
            video_id="abc123",
            comment_text="Great video!",
            profile_id="k18ewu4m"
        )
    """

    def __init__(
        self,
        config: Optional[CommenterConfig] = None,
        enable_state_persistence: bool = True
    ):
        """
        Initialize HumanCommenter.

        Args:
            config: Configuration options. Uses defaults if not provided.
            enable_state_persistence: Enable session state persistence
        """
        self.config = config or CommenterConfig()
        self._client: Optional[AdsPowerPlaywrightClient] = None
        self._seed_gen: Optional[ProfileSeedGenerator] = None
        self._state: Optional[SessionState] = None
        self._enable_state = enable_state_persistence

        # Configure logging
        configure_logging(log_sensitive=self.config.log_sensitive_data)

    def _init_profile(self, profile_id: str) -> None:
        """
        Initialize profile-specific components.

        Args:
            profile_id: AdsPower profile ID
        """
        # Create seed generator for this profile
        self._seed_gen = ProfileSeedGenerator(profile_id)

        # Apply personality seed based on profile_id
        # This creates unique "handwriting" for each account
        self.config.randomize_for_profile(profile_id)

        # Initialize session state if enabled
        if self._enable_state:
            self._state = SessionState(profile_id)

        # Log profile info
        personality = self.config.get_personality_info()
        logger.info(f"Initialized profile: {profile_id}")
        logger.info(f"Personality seed: {personality['seed']}")
        logger.debug(
            f"Personality params: wrong_key={personality['wrong_key_chance']:.3f}, "
            f"inter_key_delay={personality['inter_key_delay_mean']:.3f}s, "
            f"bezier_variance={personality['bezier_variance']:.3f}"
        )
        logger.debug(f"Seed generator: {self._seed_gen}")

    async def add_and_pin_comment(
        self,
        video_id: str,
        comment_text: str,
        profile_id: str,
        channel_keywords: Optional[List[str]] = None,
        expected_region: Optional[str] = None,
        expected_timezone: Optional[str] = None,
    ) -> WorkflowResult:
        """
        Add and pin a comment on a YouTube video.

        This is the main entry point for comment automation. It:
        1. Connects to AdsPower browser profile
        2. Initializes profile-specific behaviors
        3. Runs safety checks (IP, timezone)
        4. Watches video (45-120s)
        5. Scrolls to and reads comments
        6. Types and submits comment
        7. Pins comment in YouTube Studio

        Args:
            video_id: YouTube video ID (e.g., "dQw4w9WgXcQ")
            comment_text: Text of the comment to post
            profile_id: AdsPower profile ID (e.g., "k18ewu4m")
            channel_keywords: Keywords for entropy search actions (optional)
            expected_region: Expected IP region code for safety check (e.g., "US")
            expected_timezone: Expected timezone for safety check (e.g., "America/New_York")

        Returns:
            WorkflowResult with success status and details
        """
        logger.info(f"Starting add_and_pin_comment workflow")

        try:
            # Initialize profile-specific components
            self._init_profile(profile_id)

            # Connect to AdsPower
            self._client = AdsPowerPlaywrightClient(self.config)
            await self._client.connect(profile_id)

            # Get page
            page = await self._client.get_page()

            # Track video page visit
            if self._state:
                video_url = f"https://www.youtube.com/watch?v={video_id}"
                self._state.add_visited(video_url)

            # Create and run workflow
            workflow = CommentWorkflowFSM(
                page,
                self.config
            )
            result = await workflow.run(
                video_id=video_id,
                comment_text=comment_text,
                expected_region=expected_region,
                expected_timezone=expected_timezone,
                channel_keywords=channel_keywords,
            )

            # Save state on success
            if result.success and self._state:
                self._state.set('last_video_id', video_id)
                self._state.set('last_comment_text', comment_text[:50])  # Truncate for privacy

            return result

        except Exception as e:
            logger.exception(f"Workflow failed: {e}")
            return WorkflowResult(
                success=False,
                error=str(e),
                state_reached=WorkflowState.FAILED,
            )

        finally:
            # Always disconnect
            if self._client:
                await self._client.disconnect()

    async def add_comment_only(
        self,
        video_id: str,
        comment_text: str,
        profile_id: str,
        channel_keywords: Optional[List[str]] = None,
        expected_region: Optional[str] = None,
        expected_timezone: Optional[str] = None,
    ) -> WorkflowResult:
        """
        Add a comment without pinning.

        Runs the workflow up to INTERACTION phase only.

        Args:
            video_id: YouTube video ID
            comment_text: Text of the comment to post
            profile_id: AdsPower profile ID
            channel_keywords: Keywords for entropy actions
            expected_region: Expected IP region
            expected_timezone: Expected timezone

        Returns:
            WorkflowResult with success status
        """
        logger.info(f"Starting add_comment_only workflow")

        try:
            # Initialize profile-specific components
            self._init_profile(profile_id)

            # Connect to AdsPower
            self._client = AdsPowerPlaywrightClient(self.config)
            await self._client.connect(profile_id)

            page = await self._client.get_page()

            # Import phases directly for partial workflow
            from .workflow import ConsumptionPhase, ResearchPhase, InteractionPhase
            from .biometrics import HumanMouse, HumanScroll, HumanKeyboard
            from .youtube.video_player import VideoPlayer
            from .youtube.popup_handler import PopupHandler
            from .safety import SafetyChecker

            # Get profile seeds for components
            mouse_seed = self._seed_gen.get_behavior_seed('mouse') if self._seed_gen else None
            keyboard_seed = self._seed_gen.get_behavior_seed('keyboard') if self._seed_gen else None
            scroll_seed = self._seed_gen.get_behavior_seed('scroll') if self._seed_gen else None

            # Initialize components with profile seeds
            mouse = HumanMouse(page, self.config)
            scroll = HumanScroll(page, self.config, profile_seed=scroll_seed)
            keyboard = HumanKeyboard(page, self.config, mouse=mouse, profile_seed=keyboard_seed)
            player = VideoPlayer(page, mouse, self.config)
            popup_handler = PopupHandler(page, mouse, self.config)
            safety_checker = SafetyChecker(page, self.config)

            # Safety check
            if expected_region or expected_timezone:
                check_result = await safety_checker.verify_all(
                    expected_region=expected_region,
                    expected_timezone=expected_timezone,
                )
                if not check_result.passed:
                    return WorkflowResult(
                        success=False,
                        error=f"Safety check failed: {check_result.errors}",
                        state_reached=WorkflowState.SAFETY_CHECK,
                    )

            # Run phases
            consumption = ConsumptionPhase(
                page, mouse, scroll, player, popup_handler, self.config
            )
            if not await consumption.execute(video_id):
                return WorkflowResult(
                    success=False,
                    error="Consumption phase failed",
                    state_reached=WorkflowState.CONSUMPTION,
                )

            research = ResearchPhase(page, mouse, scroll, self.config)
            if not await research.execute():
                return WorkflowResult(
                    success=False,
                    error="Research phase failed",
                    state_reached=WorkflowState.RESEARCH,
                )

            interaction = InteractionPhase(page, mouse, scroll, keyboard, self.config)
            if not await interaction.execute(comment_text):
                return WorkflowResult(
                    success=False,
                    error="Interaction phase failed",
                    state_reached=WorkflowState.INTERACTION,
                )

            # Track visit
            if self._state:
                video_url = f"https://www.youtube.com/watch?v={video_id}"
                self._state.add_visited(video_url)

            return WorkflowResult(
                success=True,
                comment_posted=True,
                comment_pinned=False,
                state_reached=WorkflowState.INTERACTION,
            )

        except Exception as e:
            logger.exception(f"Workflow failed: {e}")
            return WorkflowResult(
                success=False,
                error=str(e),
                state_reached=WorkflowState.FAILED,
            )

        finally:
            if self._client:
                await self._client.disconnect()

    async def pin_existing_comment(
        self,
        video_id: str,
        comment_text: str,
        profile_id: str,
    ) -> WorkflowResult:
        """
        Pin an existing comment (doesn't post new comment).

        Useful when comment was already posted but pin failed.

        Args:
            video_id: YouTube video ID
            comment_text: Text of the comment to find and pin
            profile_id: AdsPower profile ID

        Returns:
            WorkflowResult with success status
        """
        logger.info(f"Starting pin_existing_comment workflow")

        try:
            # Initialize profile-specific components
            self._init_profile(profile_id)

            self._client = AdsPowerPlaywrightClient(self.config)
            await self._client.connect(profile_id)

            page = await self._client.get_page()

            from .workflow import FinalizationPhase
            from .biometrics import HumanMouse, HumanScroll
            from .youtube.popup_handler import PopupHandler

            # Get profile seed for scroll
            scroll_seed = self._seed_gen.get_behavior_seed('scroll') if self._seed_gen else None

            mouse = HumanMouse(page, self.config)
            scroll = HumanScroll(page, self.config, profile_seed=scroll_seed)
            popup_handler = PopupHandler(page, mouse, self.config)

            finalization = FinalizationPhase(
                page, mouse, scroll, popup_handler, self.config
            )

            if not await finalization.execute(video_id, comment_text):
                return WorkflowResult(
                    success=False,
                    error="Failed to pin comment",
                    state_reached=WorkflowState.FINALIZATION,
                )

            return WorkflowResult(
                success=True,
                comment_posted=True,  # Assumed existing
                comment_pinned=True,
                state_reached=WorkflowState.COMPLETE,
            )

        except Exception as e:
            logger.exception(f"Pin workflow failed: {e}")
            return WorkflowResult(
                success=False,
                error=str(e),
                state_reached=WorkflowState.FAILED,
            )

        finally:
            if self._client:
                await self._client.disconnect()

    def update_config(self, **kwargs) -> None:
        """
        Update configuration options.

        Args:
            **kwargs: Configuration fields to update
        """
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
            else:
                logger.warning(f"Unknown config option: {key}")

    @property
    def is_connected(self) -> bool:
        """Check if currently connected to browser"""
        return self._client is not None and self._client.is_connected

    @property
    def seed_generator(self) -> Optional[ProfileSeedGenerator]:
        """Access the profile seed generator (available after init_profile)"""
        return self._seed_gen

    @property
    def session_state(self) -> Optional[SessionState]:
        """Access the session state (available if state persistence enabled)"""
        return self._state

    def get_profile_info(self) -> dict:
        """Get information about the current profile configuration."""
        if not self._seed_gen:
            return {"error": "Profile not initialized"}

        return {
            "personality": self.config.get_personality_info(),
            "seed_info": self._seed_gen.get_info(),
            "state_stats": self._state.get_stats() if self._state else None,
        }


# Convenience function for simple usage
async def add_and_pin_comment(
    video_id: str,
    comment_text: str,
    profile_id: str,
    config: Optional[CommenterConfig] = None,
    **kwargs
) -> WorkflowResult:
    """
    Convenience function to add and pin a comment.

    Args:
        video_id: YouTube video ID
        comment_text: Comment text
        profile_id: AdsPower profile ID
        config: Optional configuration
        **kwargs: Additional arguments passed to add_and_pin_comment

    Returns:
        WorkflowResult
    """
    commenter = HumanCommenter(config)
    return await commenter.add_and_pin_comment(
        video_id=video_id,
        comment_text=comment_text,
        profile_id=profile_id,
        **kwargs,
    )
