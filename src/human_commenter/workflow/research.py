"""
Research Phase

Simulates scrolling to and reading comments before adding own comment.
Includes pausing on comments and clicking "Read more" links.
"""

import asyncio
import random
from typing import Optional

from playwright.async_api import Page

from ..biometrics import HumanMouse, HumanScroll, GaussianDelay
from ..youtube.selectors import YouTubeSelectors
from ..config import CommenterConfig
from ..safety.logger import get_logger

logger = get_logger(__name__)


class ResearchPhase:
    """
    Handles the research phase where user reads existing comments.

    Before commenting, real users scroll to the comments section
    and read some existing comments. This phase simulates that.
    """

    def __init__(
        self,
        page: Page,
        mouse: HumanMouse,
        scroll: HumanScroll,
        config: CommenterConfig
    ):
        self.page = page
        self.mouse = mouse
        self.scroll = scroll
        self.config = config
        self._selectors = YouTubeSelectors()

    async def execute(self) -> bool:
        """
        Execute the research phase.

        Returns:
            True if phase completed successfully
        """
        logger.info("Starting research phase")

        try:
            # Scroll to comments section
            await self._scroll_to_comments()

            # Wait for comments to load
            await asyncio.sleep(random.uniform(1.5, 3.0))

            # Read some comments
            await self._read_comments()

            logger.info("Research phase complete")
            return True

        except Exception as e:
            logger.error(f"Research phase failed: {e}")
            return False

    async def _scroll_to_comments(self) -> bool:
        """
        Scroll down to reveal the comments section.

        Returns:
            True if comments section found
        """
        logger.debug("Scrolling to comments")

        # Scroll down gradually
        total_scrolled = 0
        max_scroll = 3000  # Don't scroll forever

        while total_scrolled < max_scroll:
            # Check if comments are visible
            comments = await self.page.query_selector(self._selectors.COMMENTS_SECTION)
            if comments:
                box = await comments.bounding_box()
                if box and box["y"] < 800:  # Comments visible in viewport
                    logger.debug("Comments section found")
                    return True

            # Scroll down
            scroll_amount = random.randint(200, 400)
            await self.scroll.scroll_down(pixels=scroll_amount)
            total_scrolled += scroll_amount

            # Brief pause
            await asyncio.sleep(random.uniform(0.3, 0.8))

        # Try scrolling directly to comments
        return await self.scroll.scroll_to_element(self._selectors.COMMENTS_SECTION)

    async def _read_comments(self) -> None:
        """
        Simulate reading some existing comments.
        """
        # Get visible comment threads
        comments = await self.page.query_selector_all(self._selectors.COMMENT_THREAD)

        if not comments:
            logger.debug("No comments found to read")
            await asyncio.sleep(random.uniform(2, 4))  # Pause anyway
            return

        # Read 2-5 comments
        num_to_read = min(len(comments), random.randint(2, 5))
        comments_to_read = random.sample(comments[:10], num_to_read)  # Top 10 comments

        read_more_clicks = 0
        max_read_more = self.config.workflow.max_read_more_clicks

        for comment in comments_to_read:
            try:
                # Scroll comment into view if needed
                await comment.scroll_into_view_if_needed()
                await asyncio.sleep(random.uniform(0.3, 0.6))

                # Get comment bounding box
                box = await comment.bounding_box()
                if not box:
                    continue

                # Hover over comment
                hover_x = box["x"] + random.uniform(50, box["width"] - 50)
                hover_y = box["y"] + box["height"] / 2

                await self.mouse.hover_with_tremor(hover_x, hover_y, duration=0.3)

                # Pause to "read" (5-10 seconds)
                pause_min = self.config.workflow.research_pause_min
                pause_max = self.config.workflow.research_pause_max
                read_time = random.uniform(pause_min, pause_max)

                await asyncio.sleep(read_time)

                # Maybe click "Read more" if present
                if read_more_clicks < max_read_more and random.random() < 0.3:
                    more_button = await comment.query_selector(self._selectors.COMMENT_MORE_BUTTON)
                    if more_button:
                        more_box = await more_button.bounding_box()
                        if more_box:
                            await self.mouse.click_at(
                                more_box["x"] + more_box["width"] / 2,
                                more_box["y"] + more_box["height"] / 2
                            )
                            read_more_clicks += 1
                            await asyncio.sleep(random.uniform(2, 4))

            except Exception as e:
                logger.debug(f"Failed to read comment: {e}")
                continue

        logger.debug(f"Read {num_to_read} comments, clicked 'Read more' {read_more_clicks} times")

    async def scroll_through_comments(self, duration: float = 10.0) -> None:
        """
        Leisurely scroll through comments section.

        Args:
            duration: How long to scroll in seconds
        """
        start = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start < duration:
            # Random scroll
            if random.random() < 0.7:  # 70% scroll down
                await self.scroll.scroll_down(pixels=random.randint(100, 250))
            else:
                await self.scroll.scroll_up(pixels=random.randint(50, 150))

            # Pause to "read"
            await asyncio.sleep(random.uniform(1, 3))
