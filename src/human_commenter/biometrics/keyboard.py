"""
Human-Like Keyboard Input

Simulates realistic typing with:
- Bimodal delays between keystrokes (fast/slow modes)
- 5 types of typos: adjacent, skip, double, swap, case
- Backspace corrections (faster than normal typing)
- Thinking pauses mid-typing
- Sticky keys (slightly longer holds)
- Human focus via mouse click (not programmatic focus())
- Profile-specific error patterns
"""

import asyncio
import random
from typing import Dict, List, Optional, TYPE_CHECKING
from enum import Enum

from playwright.async_api import Page

from ..config import CommenterConfig, KeyboardConfig
from .bimodal_delay import BimodalDelay
from ..safety.logger import get_logger
from ..safety.analytics_logger import get_analytics

# Avoid circular import
if TYPE_CHECKING:
    from .mouse import HumanMouse

logger = get_logger(__name__)


# QWERTY keyboard adjacency map (extended)
QWERTY_ADJACENT: Dict[str, List[str]] = {
    # Row 1
    'q': ['w', 'a', '1', '2'],
    'w': ['q', 'e', 'a', 's', '2', '3'],
    'e': ['w', 'r', 's', 'd', '3', '4'],
    'r': ['e', 't', 'd', 'f', '4', '5'],
    't': ['r', 'y', 'f', 'g', '5', '6'],
    'y': ['t', 'u', 'g', 'h', '6', '7'],
    'u': ['y', 'i', 'h', 'j', '7', '8'],
    'i': ['u', 'o', 'j', 'k', '8', '9'],
    'o': ['i', 'p', 'k', 'l', '9', '0'],
    'p': ['o', 'l', '0', '-', '['],

    # Row 2
    'a': ['q', 'w', 's', 'z'],
    's': ['w', 'e', 'a', 'd', 'z', 'x'],
    'd': ['e', 'r', 's', 'f', 'x', 'c'],
    'f': ['r', 't', 'd', 'g', 'c', 'v'],
    'g': ['t', 'y', 'f', 'h', 'v', 'b'],
    'h': ['y', 'u', 'g', 'j', 'b', 'n'],
    'j': ['u', 'i', 'h', 'k', 'n', 'm'],
    'k': ['i', 'o', 'j', 'l', 'm', ','],
    'l': ['o', 'p', 'k', ',', '.', ';'],

    # Row 3
    'z': ['a', 's', 'x'],
    'x': ['s', 'd', 'z', 'c'],
    'c': ['d', 'f', 'x', 'v'],
    'v': ['f', 'g', 'c', 'b'],
    'b': ['g', 'h', 'v', 'n'],
    'n': ['h', 'j', 'b', 'm'],
    'm': ['j', 'k', 'n', ','],

    # Numbers
    '1': ['2', 'q'],
    '2': ['1', '3', 'q', 'w'],
    '3': ['2', '4', 'w', 'e'],
    '4': ['3', '5', 'e', 'r'],
    '5': ['4', '6', 'r', 't'],
    '6': ['5', '7', 't', 'y'],
    '7': ['6', '8', 'y', 'u'],
    '8': ['7', '9', 'u', 'i'],
    '9': ['8', '0', 'i', 'o'],
    '0': ['9', '-', 'o', 'p'],
}


class TypoType(Enum):
    """Types of typing errors humans make."""
    ADJACENT = "adjacent"   # Hit neighboring key (most common)
    SKIP = "skip"           # Skip a letter, pause, then type it
    DOUBLE = "double"       # Type same letter twice, delete one
    SWAP = "swap"           # Transpose two adjacent letters
    CASE = "case"           # Wrong case (shift timing error)


class HumanKeyboard:
    """
    Simulates human typing behavior with realistic patterns.

    Features:
    - Bimodal-distributed delays between keys (fast automatic / slow deliberate)
    - 5 types of typos with weighted selection
    - Automatic backspace corrections (faster than normal typing)
    - Random thinking pauses
    - Sticky keys (longer press duration)
    - Human focus via mouse click (not programmatic focus())
    - Profile-specific "typing fingerprint"
    """

    def __init__(
        self,
        page: Page,
        config: CommenterConfig,
        mouse: Optional["HumanMouse"] = None,
        profile_seed: Optional[int] = None
    ):
        """
        Initialize keyboard handler.

        Args:
            page: Playwright page instance
            config: Commenter configuration
            mouse: Optional mouse for human-like focus
            profile_seed: Seed for consistent per-profile behavior
        """
        self.page = page
        self.config = config
        self.kb_config: KeyboardConfig = config.keyboard
        self._mouse = mouse

        # Initialize bimodal delay generator for typing
        self._delay = BimodalDelay.for_typing()

        # Backspace is faster than normal typing (humans delete quickly)
        self._backspace_delay_multiplier: float = 0.4  # 40% of normal speed

        # Initialize typo weights with profile-specific variation
        self._init_typo_weights(profile_seed)

    def _init_typo_weights(self, profile_seed: Optional[int] = None) -> None:
        """
        Initialize typo type weights with optional profile-specific variation.

        Each profile has a slightly different "typing fingerprint" -
        some people make more adjacent key errors, others swap letters more, etc.

        Args:
            profile_seed: Seed for consistent per-profile variation
        """
        if profile_seed:
            rng = random.Random(profile_seed)
        else:
            rng = random

        # Base weights with profile-specific variation (+/- ~20%)
        self._typo_weights = {
            TypoType.ADJACENT: 40 + rng.randint(-8, 8),   # Most common
            TypoType.SKIP: 12 + rng.randint(-4, 8),       # Fairly rare
            TypoType.DOUBLE: 20 + rng.randint(-5, 8),     # Common for fast typists
            TypoType.SWAP: 15 + rng.randint(-5, 8),       # Transposition errors
            TypoType.CASE: 10 + rng.randint(-4, 4),       # Shift timing errors
        }

        logger.debug(f"Typo weights initialized: {self._typo_weights}")

    def set_mouse(self, mouse: "HumanMouse") -> None:
        """Set the mouse reference for human-like focus behavior."""
        self._mouse = mouse

    async def type_text(
        self,
        text: str,
        selector: Optional[str] = None,
        clear_first: bool = False
    ) -> None:
        """
        Type text with human-like behavior.

        Args:
            text: Text to type
            selector: Optional element selector to focus first
            clear_first: Clear existing content before typing
        """
        if selector:
            await self._focus_element(selector)

        if clear_first:
            await self._clear_input()

        logger.debug(f"Typing {len(text)} characters")

        # Reset delay history for fresh rhythm
        self._delay.reset_history()

        i = 0
        while i < len(text):
            char = text[i]
            next_char = text[i + 1] if i + 1 < len(text) else None

            # Check for thinking pause (mid-sentence hesitation)
            if random.random() < self.kb_config.thinking_pause_chance:
                pause_time = random.uniform(
                    self.kb_config.thinking_pause_min,
                    self.kb_config.thinking_pause_max
                )
                logger.debug(f"Thinking pause: {pause_time:.2f}s")

                # Log thinking pause
                analytics = get_analytics()
                if analytics:
                    analytics.log_thinking_pause(pause_time * 1000)

                await asyncio.sleep(pause_time)

            # Check if we should make a typo
            if self._should_make_typo(char):
                typo_type = self._select_typo_type(char, next_char)
                chars_consumed = await self._make_typo(char, next_char, typo_type)
                i += chars_consumed
            else:
                # Normal keystroke
                await self._type_char(char)
                i += 1

            # Inter-key delay (bimodal)
            delay_value, delay_mode = self._delay.sample()
            await asyncio.sleep(delay_value)

            # Log inter-key delay
            analytics = get_analytics()
            if analytics:
                analytics.log_key_delay(delay_value * 1000, delay_mode.value)

    async def type_slowly(self, text: str, selector: Optional[str] = None) -> None:
        """
        Type text extra slowly (for important/careful typing).

        Uses longer delays between keys.
        """
        # Create a slower bimodal delay
        original_delay = self._delay
        self._delay = BimodalDelay.for_reading()  # Slower, more deliberate

        try:
            await self.type_text(text, selector)
        finally:
            self._delay = original_delay

    async def type_quickly(self, text: str, selector: Optional[str] = None) -> None:
        """
        Type text quickly (for routine typing).

        Uses shorter delays between keys with higher fast mode probability.
        """
        from .bimodal_delay import BimodalConfig

        original_delay = self._delay
        self._delay = BimodalDelay(BimodalConfig(
            fast_mean=0.05,
            fast_std=0.015,
            slow_mean=0.15,
            slow_std=0.04,
            fast_probability=0.85,  # More fast mode
            min_bound=0.02,
            max_bound=0.4
        ))

        try:
            await self.type_text(text, selector)
        finally:
            self._delay = original_delay

    async def press_key(self, key: str, hold_time: Optional[float] = None) -> None:
        """
        Press a special key (Enter, Tab, Escape, etc.).

        Args:
            key: Key name (e.g., "Enter", "Tab", "Escape")
            hold_time: Optional hold duration in seconds
        """
        if hold_time:
            await self.page.keyboard.down(key)
            await asyncio.sleep(hold_time)
            await self.page.keyboard.up(key)
        else:
            await self.page.keyboard.press(key)

    async def press_combo(self, *keys: str) -> None:
        """
        Press a key combination (e.g., Ctrl+A, Ctrl+V).

        Args:
            keys: Keys to press together (e.g., "Control", "a")
        """
        # Press all modifier keys
        for key in keys[:-1]:
            await self.page.keyboard.down(key)
            await asyncio.sleep(random.uniform(0.02, 0.05))

        # Press and release the final key
        await self.page.keyboard.press(keys[-1])

        # Release modifier keys in reverse order
        for key in reversed(keys[:-1]):
            await asyncio.sleep(random.uniform(0.02, 0.05))
            await self.page.keyboard.up(key)

    def _should_make_typo(self, char: str) -> bool:
        """
        Determine if we should make a typo for this character.

        Only makes typos on alphanumeric characters that have adjacent keys defined.
        """
        if not char.isalnum():
            return False

        if char.lower() not in QWERTY_ADJACENT:
            return False

        return random.random() < self.kb_config.wrong_key_chance

    def _select_typo_type(self, char: str, next_char: Optional[str]) -> TypoType:
        """
        Select error type based on context and profile weights.

        Args:
            char: Current character
            next_char: Next character (if any)

        Returns:
            Selected typo type
        """
        weights = self._typo_weights.copy()

        # Context-based adjustments
        if not next_char or not next_char.isalpha():
            # Can't swap with non-alpha or at end of text
            weights[TypoType.SWAP] = 0

        if not char.isalpha():
            # Case errors only for letters
            weights[TypoType.CASE] = 0

        if char.lower() not in QWERTY_ADJACENT:
            # Need adjacent keys for adjacent typo
            weights[TypoType.ADJACENT] = 0

        # Weighted random selection
        total = sum(weights.values())
        if total == 0:
            return TypoType.SKIP  # Fallback

        r = random.uniform(0, total)
        cumulative = 0

        for typo_type, weight in weights.items():
            cumulative += weight
            if r <= cumulative:
                return typo_type

        return TypoType.ADJACENT  # Default fallback

    async def _make_typo(
        self,
        char: str,
        next_char: Optional[str],
        typo_type: TypoType
    ) -> int:
        """
        Make and correct a typo.

        Args:
            char: Intended character
            next_char: Next character (for swap errors)
            typo_type: Type of error to make

        Returns:
            Number of characters consumed from input
        """
        logger.debug(f"Making typo: {typo_type.value} for '{char}'")

        if typo_type == TypoType.ADJACENT:
            return await self._typo_adjacent(char)

        elif typo_type == TypoType.SKIP:
            return await self._typo_skip(char)

        elif typo_type == TypoType.DOUBLE:
            return await self._typo_double(char)

        elif typo_type == TypoType.SWAP and next_char:
            return await self._typo_swap(char, next_char)

        elif typo_type == TypoType.CASE:
            return await self._typo_case(char)

        # Fallback: just type the character normally
        await self._type_char(char)
        return 1

    async def _typo_adjacent(self, char: str) -> int:
        """
        Type adjacent key, notice, backspace, type correct key.

        Most common typo - finger hits neighboring key.
        """
        analytics = get_analytics()
        adjacent = QWERTY_ADJACENT.get(char.lower(), [])

        if not adjacent:
            await self._type_char(char)
            return 1

        # Type wrong key
        wrong_char = random.choice(adjacent)
        if char.isupper():
            wrong_char = wrong_char.upper()

        await self._type_char(wrong_char)

        # Log typo made
        if analytics:
            analytics.log_typo_made("adjacent", ord(char))

        # Brief pause (noticing the mistake)
        notice_delay = random.uniform(0.15, 0.30)
        await asyncio.sleep(notice_delay)

        # Backspace
        await self._backspace(1)

        # Type correct character
        await self._type_char(char)

        # Log typo corrected
        if analytics:
            analytics.log_typo_corrected(1, notice_delay * 1000)

        return 1

    async def _typo_skip(self, char: str) -> int:
        """
        Pause (finger hesitation), then type the character.

        Simulates when finger hovers over key but doesn't press.
        """
        # Longer pause (hesitation/distraction)
        await asyncio.sleep(random.uniform(0.3, 0.6))

        # Type the character
        await self._type_char(char)

        return 1

    async def _typo_double(self, char: str) -> int:
        """
        Type character twice, notice, backspace once.

        Common for fast typists - finger bounces on key.
        """
        analytics = get_analytics()

        # Type first occurrence
        await self._type_char(char)

        # Quick second press (bounce)
        await self._delay.wait()
        await self._type_char(char)

        # Log typo made
        if analytics:
            analytics.log_typo_made("double", ord(char))

        # Notice the mistake
        notice_delay = random.uniform(0.2, 0.4)
        await asyncio.sleep(notice_delay)

        # Delete the extra character
        await self._backspace(1)

        # Log typo corrected
        if analytics:
            analytics.log_typo_corrected(1, notice_delay * 1000)

        return 1

    async def _typo_swap(self, char: str, next_char: str) -> int:
        """
        Type two characters in wrong order, notice, fix.

        Transposition error - common when typing fast.
        """
        analytics = get_analytics()

        # Type in wrong order
        await self._type_char(next_char)
        await self._delay.wait()
        await self._type_char(char)

        # Log typo made
        if analytics:
            analytics.log_typo_made("swap", ord(char))

        # Notice the mistake
        notice_delay = random.uniform(0.25, 0.45)
        await asyncio.sleep(notice_delay)

        # Delete both characters
        await self._backspace(2)

        # Type in correct order
        await self._type_char(char)
        await self._delay.wait()
        await self._type_char(next_char)

        # Log typo corrected
        if analytics:
            analytics.log_typo_corrected(2, notice_delay * 1000)

        return 2  # Consumed both characters

    async def _typo_case(self, char: str) -> int:
        """
        Type wrong case, notice, backspace, type correct case.

        Shift key timing error - pressed shift too early/late.
        """
        analytics = get_analytics()

        # Type wrong case
        wrong_case = char.lower() if char.isupper() else char.upper()
        await self._type_char(wrong_case)

        # Log typo made
        if analytics:
            analytics.log_typo_made("case", ord(char))

        # Notice the mistake
        notice_delay = random.uniform(0.2, 0.35)
        await asyncio.sleep(notice_delay)

        # Backspace
        await self._backspace(1)

        # Type correct case
        await self._type_char(char)

        # Log typo corrected
        if analytics:
            analytics.log_typo_corrected(1, notice_delay * 1000)

        return 1

    async def _type_char(self, char: str) -> None:
        """Type a single character with optional sticky key behavior."""
        analytics = get_analytics()

        # Use insertText for non-ASCII characters (emoji, unicode, etc.)
        # keyboard.press() only works with ASCII and special keys
        if ord(char) > 127:
            await self.page.keyboard.insert_text(char)
            if analytics:
                analytics.log_key_press(char, is_unicode=True)
            return

        # Check for sticky key (longer hold) - only for ASCII
        if random.random() < self.kb_config.sticky_key_chance:
            hold_time = self.kb_config.sticky_key_extra_ms / 1000
            await self.page.keyboard.down(char)
            await asyncio.sleep(hold_time)
            await self.page.keyboard.up(char)
            if analytics:
                analytics.log_key_press(char)
                analytics.log_key_hold(ord(char), hold_time * 1000)
        else:
            await self.page.keyboard.press(char)
            if analytics:
                analytics.log_key_press(char)

    async def _backspace(self, count: int) -> None:
        """
        Press backspace with fast timing.

        Humans delete errors quickly because they know what they typed wrong.
        """
        analytics = get_analytics()
        for _ in range(count):
            await self.page.keyboard.press("Backspace")
            # Faster than normal typing
            delay = self._delay.config.fast_mean * self._backspace_delay_multiplier
            actual_delay = random.uniform(delay * 0.5, delay * 1.5)
            await asyncio.sleep(actual_delay)

            if analytics:
                analytics.log_backspace(1, actual_delay * 1000)

    async def _focus_element(self, selector: str) -> None:
        """
        Focus an input element using human-like mouse click.

        Instead of programmatic element.focus(), this method:
        1. Uses HumanMouse to move to the element
        2. Performs a real page.mouse.click()
        3. Only then starts typing

        This creates more realistic behavior and proper isTrusted events.
        """
        try:
            element = await self.page.wait_for_selector(selector, timeout=5000)
            if not element:
                logger.warning(f"Element not found: {selector}")
                return

            # Get element bounding box
            box = await element.bounding_box()
            if not box:
                # Fallback to scroll into view and try again
                await element.scroll_into_view_if_needed()
                await asyncio.sleep(0.3)
                box = await element.bounding_box()

            if not box:
                logger.warning(f"Cannot get bounding box for: {selector}")
                # Last resort: use programmatic focus
                await element.focus()
                return

            # Calculate click position (slightly offset from center for realism)
            click_x = box["x"] + box["width"] * random.uniform(0.3, 0.7)
            click_y = box["y"] + box["height"] * random.uniform(0.3, 0.7)

            if self._mouse:
                # Use HumanMouse for realistic movement and click
                await self._mouse.move_to(
                    click_x,
                    click_y,
                    target_width=box["width"],
                    target_height=box["height"]
                )
                await asyncio.sleep(random.uniform(0.05, 0.15))
                await self.page.mouse.click(click_x, click_y)
            else:
                # No mouse reference - use direct page.mouse
                await self.page.mouse.click(click_x, click_y)

            # Small pause after clicking before typing
            await asyncio.sleep(random.uniform(0.15, 0.35))
            logger.debug(f"Focused element via click at ({click_x:.0f}, {click_y:.0f})")

        except Exception as e:
            logger.warning(f"Failed to focus element {selector}: {e}")
            # No fallback to programmatic focus - only real clicks are allowed

    async def _clear_input(self) -> None:
        """Clear current input field (Ctrl+A, Delete)."""
        await self.press_combo("Control", "a")
        await asyncio.sleep(random.uniform(0.05, 0.1))
        await self.page.keyboard.press("Delete")
        await asyncio.sleep(random.uniform(0.1, 0.2))

    def get_typo_stats(self) -> Dict[str, int]:
        """Get the current typo weight configuration."""
        return {t.value: w for t, w in self._typo_weights.items()}


def get_word_boundaries(text: str) -> List[int]:
    """
    Get indices of word boundaries in text.

    Useful for adding pauses at natural break points.
    """
    boundaries = [0]
    for i, char in enumerate(text):
        if char in " \n\t.,!?;:":
            boundaries.append(i + 1)
    return boundaries
