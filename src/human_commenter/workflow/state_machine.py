"""
Workflow State Machine

Orchestrates the entire comment workflow through states:
CONSUMPTION -> RESEARCH -> INTERACTION -> FINALIZATION -> NATURAL_EXIT
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List

from playwright.async_api import Page

from ..client import AdsPowerPlaywrightClient
from ..biometrics import HumanMouse, HumanScroll, HumanKeyboard, GaussianDelay, DistractedState
from ..youtube.video_player import VideoPlayer
from ..youtube.popup_handler import PopupHandler
from ..youtube.selectors import YouTubeSelectors
from ..entropy import EntropyActions
from ..safety import SafetyChecker
from ..config import CommenterConfig
from ..safety.logger import get_logger

from .consumption import ConsumptionPhase
from .research import ResearchPhase
from .interaction import InteractionPhase
from .finalization import FinalizationPhase

logger = get_logger(__name__)


class WorkflowState(Enum):
    """States in the comment workflow"""
    INIT = "init"
    SAFETY_CHECK = "safety_check"
    CONSUMPTION = "consumption"
    RESEARCH = "research"
    INTERACTION = "interaction"
    FINALIZATION = "finalization"
    NATURAL_EXIT = "natural_exit"  # Organic wandering (Shorts) + clean close
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class WorkflowResult:
    """Result of workflow execution"""
    success: bool = False
    state_reached: WorkflowState = WorkflowState.INIT
    comment_posted: bool = False
    comment_pinned: bool = False
    error: Optional[str] = None
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    duration_seconds: float = 0.0

    def __post_init__(self):
        if self.completed_at and self.started_at:
            self.duration_seconds = (self.completed_at - self.started_at).total_seconds()


class CommentWorkflowFSM:
    """
    Finite State Machine for comment workflow.

    Manages transitions through workflow states with
    entropy actions between states for unpredictability.
    """

    def __init__(
        self,
        page: Page,
        config: CommenterConfig
    ):
        self.page = page
        self.config = config
        self._selectors = YouTubeSelectors()

        # State tracking
        self._current_state = WorkflowState.INIT
        self._result = WorkflowResult()

        # Initialize biometrics
        self._mouse = HumanMouse(page, config)
        self._scroll = HumanScroll(page, config)
        self._keyboard = HumanKeyboard(page, config, mouse=self._mouse)  # Pass mouse for human focus
        self._distracted = DistractedState(page, config)

        # Initialize helpers
        self._player = VideoPlayer(page, self._mouse, config)
        self._popup_handler = PopupHandler(page, self._mouse, config)
        self._safety_checker = SafetyChecker(page, config)
        self._entropy = EntropyActions(page, self._mouse, self._scroll, self._keyboard, config)

        # Initialize workflow phases
        self._consumption = ConsumptionPhase(
            page, self._mouse, self._scroll, self._player, self._popup_handler, config
        )
        self._research = ResearchPhase(page, self._mouse, self._scroll, config)
        self._interaction = InteractionPhase(
            page, self._mouse, self._scroll, self._keyboard, config
        )
        self._finalization = FinalizationPhase(
            page, self._mouse, self._scroll, self._popup_handler, config
        )

    async def run(
        self,
        video_id: str,
        comment_text: str,
        expected_region: Optional[str] = None,
        expected_timezone: Optional[str] = None,
        channel_keywords: Optional[List[str]] = None,
        enable_natural_exit: bool = True
    ) -> WorkflowResult:
        """
        Execute the full comment workflow.

        Args:
            video_id: YouTube video ID
            comment_text: Comment to post
            expected_region: Expected IP region for safety check
            expected_timezone: Expected timezone for safety check
            channel_keywords: Keywords for entropy search actions
            enable_natural_exit: Enable organic exit wandering (Shorts + clean close)

        Returns:
            WorkflowResult with success status and details
        """
        logger.info(f"Starting comment workflow for video: {video_id}")
        self._result = WorkflowResult(started_at=datetime.now())

        try:
            # State: SAFETY_CHECK
            await self._transition_to(WorkflowState.SAFETY_CHECK)
            if not await self._run_safety_checks(expected_region, expected_timezone):
                return self._fail("Safety checks failed")

            # State: CONSUMPTION (with possible distraction)
            await self._maybe_entropy(channel_keywords)
            await self._transition_to(WorkflowState.CONSUMPTION)
            if not await self._consumption.execute(video_id):
                return self._fail("Consumption phase failed")

            # Maybe simulate distraction during consumption wait
            await self._maybe_distraction()

            # State: RESEARCH
            await self._maybe_entropy(channel_keywords)
            await self._transition_to(WorkflowState.RESEARCH)
            if not await self._research.execute():
                return self._fail("Research phase failed")

            # State: INTERACTION
            await self._maybe_entropy(channel_keywords)
            await self._transition_to(WorkflowState.INTERACTION)
            if not await self._interaction.execute(comment_text):
                return self._fail("Interaction phase failed")
            self._result.comment_posted = True

            # State: FINALIZATION (pin only ~70% of the time for natural behavior)
            pin_chance = 0.70
            should_pin = random.random() < pin_chance

            if should_pin:
                await self._maybe_entropy(channel_keywords)
                await self._transition_to(WorkflowState.FINALIZATION)
                if not await self._finalization.execute(video_id, comment_text):
                    # Comment was posted but pin failed
                    logger.warning("Pin failed, but comment was posted")
                else:
                    self._result.comment_pinned = True
            else:
                logger.info(f"Skipping pin (random chance: {pin_chance*100:.0f}%)")
                self._result.comment_pinned = False

            # State: NATURAL_EXIT (Organic wandering + clean close)
            if enable_natural_exit:
                await self._transition_to(WorkflowState.NATURAL_EXIT)
                await self._natural_exit()

            # Complete
            await self._transition_to(WorkflowState.COMPLETE)
            self._result.success = True
            self._result.completed_at = datetime.now()
            self._result.duration_seconds = (
                self._result.completed_at - self._result.started_at
            ).total_seconds()

            logger.info(f"Workflow completed in {self._result.duration_seconds:.1f}s")
            return self._result

        except Exception as e:
            logger.exception(f"Workflow failed with exception: {e}")
            return self._fail(str(e))

    async def _transition_to(self, state: WorkflowState) -> None:
        """
        Transition to a new state.

        Args:
            state: Target state
        """
        logger.info(f"Transitioning: {self._current_state.value} -> {state.value}")
        self._current_state = state
        self._result.state_reached = state

    async def _run_safety_checks(
        self,
        expected_region: Optional[str],
        expected_timezone: Optional[str]
    ) -> bool:
        """
        Run safety checks before proceeding.

        Returns:
            True if all checks pass
        """
        result = await self._safety_checker.verify_all(
            expected_region=expected_region,
            expected_timezone=expected_timezone
        )

        if not result.passed:
            logger.error(f"Safety check failures: {result.errors}")
            return False

        return True

    async def _maybe_entropy(self, keywords: Optional[List[str]] = None) -> None:
        """
        Maybe perform a random entropy action between states.

        Args:
            keywords: Keywords for search actions
        """
        if await self._entropy.maybe_do_random_action(keywords):
            logger.debug("Completed entropy action")
            # Small pause after entropy action
            await asyncio.sleep(random.uniform(0.5, 1.5))

    async def _maybe_distraction(self) -> None:
        """
        Maybe simulate user distraction (blur/focus).

        This creates natural pauses where the user appears to
        switch to another application briefly.
        """
        if await self._distracted.maybe_get_distracted():
            logger.debug("Completed distraction simulation")

    async def _natural_exit(self) -> None:
        """
        Perform natural exit sequence:
        1. Browse Shorts (2-3 videos)
        2. Like one random short
        3. Clean close (about:blank + wait)
        """
        logger.info("Starting natural exit sequence")

        try:
            # Step 1-2: Organic wandering (Shorts)
            success, shorts_watched = await self._entropy.organic_exit_wandering()
            if not success:
                logger.warning("Organic wandering partially failed")

            # Step 3: Clean close
            await self._entropy.clean_exit()

            logger.info(f"Natural exit complete: watched {shorts_watched} shorts")

        except Exception as e:
            logger.warning(f"Natural exit error: {e}")
            # Still try to do clean close
            try:
                await self._entropy.clean_exit()
            except Exception:
                pass

    def _fail(self, error: str) -> WorkflowResult:
        """
        Mark workflow as failed.

        Args:
            error: Error message

        Returns:
            Failed WorkflowResult
        """
        self._current_state = WorkflowState.FAILED
        self._result.state_reached = WorkflowState.FAILED
        self._result.success = False
        self._result.error = error
        self._result.completed_at = datetime.now()
        self._result.duration_seconds = (
            self._result.completed_at - self._result.started_at
        ).total_seconds()

        logger.error(f"Workflow failed: {error}")
        return self._result

    @property
    def current_state(self) -> WorkflowState:
        """Get current workflow state"""
        return self._current_state


# Need to import random for _maybe_entropy
import random
