"""
Analytics Logger for Human Commenter

Structured event logging for pattern analysis.
Logs every action with timestamps, coordinates, and timing data.
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum


class EventType(Enum):
    """Types of logged events."""
    # Mouse events
    MOUSE_MOVE_START = "mouse_move_start"
    MOUSE_MOVE_POINT = "mouse_move_point"
    MOUSE_MOVE_END = "mouse_move_end"
    MOUSE_CLICK = "mouse_click"
    MOUSE_HOVER = "mouse_hover"
    MOUSE_TREMOR = "mouse_tremor"
    MOUSE_OVERSHOOT = "mouse_overshoot"
    MOUSE_SPIRAL = "mouse_spiral"

    # Keyboard events
    KEY_PRESS = "key_press"
    KEY_HOLD = "key_hold"
    KEY_RELEASE = "key_release"
    KEY_DELAY = "key_delay"
    TYPO_MADE = "typo_made"
    TYPO_CORRECTED = "typo_corrected"
    BACKSPACE = "backspace"
    THINKING_PAUSE = "thinking_pause"

    # Scroll events
    SCROLL_START = "scroll_start"
    SCROLL_DELTA = "scroll_delta"
    SCROLL_END = "scroll_end"
    SCROLL_OVERSHOOT = "scroll_overshoot"

    # Delay events
    DELAY_WAIT = "delay_wait"
    DELAY_BIMODAL = "delay_bimodal"
    DELAY_NAVIGATION = "delay_navigation"
    DELAY_ACTION = "delay_action"

    # Session events
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    PROFILE_CHARACTERISTICS = "profile_characteristics"
    PAGE_NAVIGATE = "page_navigate"
    WINDOW_FOCUS = "window_focus"
    WINDOW_BLUR = "window_blur"

    # Element events
    ELEMENT_FOCUS = "element_focus"
    ELEMENT_CLICK = "element_click"
    ELEMENT_TYPE = "element_type"

    # Ad events
    AD_DETECTED = "ad_detected"
    AD_ACTION = "ad_action"
    AD_SKIP_PREPARING = "ad_skip_preparing"
    AD_SKIPPED = "ad_skipped"
    AD_SKIP_FAILED = "ad_skip_failed"

    # Shorts events
    SHORTS_ERROR = "shorts_error"
    SHORTS_PAUSED_DETECTED = "shorts_paused_detected"
    SHORTS_PLAY_CLICKED = "shorts_play_clicked"
    SHORTS_SCROLLING_NEXT = "shorts_scrolling_next"
    SHORTS_SURF_START = "shorts_surf_start"
    SHORTS_SURF_END = "shorts_surf_end"
    SHORTS_WATCHING = "shorts_watching"
    SHORTS_REWATCH = "shorts_rewatch"
    SHORTS_NEXT = "shorts_next"

    # Shorts debug events
    SHORTS_SURF_DEBUG = "shorts_surf_debug"
    SHORTS_SURF_SKIP = "shorts_surf_skip"
    SHORTS_WATCHED_ONE = "shorts_watched_one"
    SHORTS_NEXT_ATTEMPT = "shorts_next_attempt"
    SHORTS_SCROLL_ERROR = "shorts_scroll_error"
    SHORTS_VIDEO_STATE = "shorts_video_state"

    # Mouse debug events
    MOUSE_OVERSHOOT_DEBUG = "mouse_overshoot_debug"

    # Bimodal stats
    BIMODAL_STATS = "bimodal_stats"

    # Video player profile
    VIDEO_PLAYER_PROFILE = "video_player_profile"
    WATCH_SESSION_END = "watch_session_end"


@dataclass
class AnalyticsEvent:
    """Single analytics event."""
    timestamp: float  # Unix timestamp with microseconds
    event_type: str
    data: Dict[str, Any] = field(default_factory=dict)
    session_id: Optional[str] = None
    profile_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "ts": self.timestamp,
            "ts_human": datetime.fromtimestamp(self.timestamp).isoformat(),
            "type": self.event_type,
            "profile": self.profile_id,
            "session": self.session_id,
            **self.data
        }


class AnalyticsLogger:
    """
    Logs detailed analytics events for pattern analysis.

    All events are stored with:
    - Precise timestamps (microsecond resolution)
    - Event type classification
    - Relevant coordinates/values
    - Timing information

    Events can be written to file for later analysis.
    """

    def __init__(
        self,
        profile_id: Optional[str] = None,
        session_id: Optional[str] = None,
        log_dir: Optional[Path] = None,
        enabled: bool = True
    ):
        """
        Initialize analytics logger.

        Args:
            profile_id: AdsPower profile identifier
            session_id: Unique session identifier
            log_dir: Directory for log files (None = memory only)
            enabled: Whether logging is enabled
        """
        self.profile_id = profile_id
        self.session_id = session_id or self._generate_session_id()
        self.log_dir = Path(log_dir) if log_dir else None
        self.enabled = enabled

        self._events: List[AnalyticsEvent] = []
        self._file_handle = None
        self._start_time = time.time()
        self._closed = False  # Track if session already closed

        if self.log_dir and self.enabled:
            self._init_log_file()

    def _generate_session_id(self) -> str:
        """Generate unique session ID."""
        return f"sess_{int(time.time() * 1000)}"

    def _init_log_file(self) -> None:
        """Initialize log file for writing."""
        self.log_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        profile_suffix = f"_{self.profile_id}" if self.profile_id else ""
        filename = f"analytics_{timestamp}{profile_suffix}.jsonl"

        self._log_path = self.log_dir / filename
        self._file_handle = open(self._log_path, "w", encoding="utf-8")

        # Write header event
        self.log(EventType.SESSION_START, {
            "log_version": "1.0",
            "profile_id": self.profile_id,
        })

    def log(self, event_type: EventType, data: Optional[Dict[str, Any]] = None) -> None:
        """
        Log an analytics event.

        Args:
            event_type: Type of event
            data: Event-specific data
        """
        if not self.enabled:
            return

        event = AnalyticsEvent(
            timestamp=time.time(),
            event_type=event_type.value,
            data=data or {},
            session_id=self.session_id,
            profile_id=self.profile_id
        )

        self._events.append(event)

        # Write to file if enabled
        if self._file_handle:
            line = json.dumps(event.to_dict(), ensure_ascii=False)
            self._file_handle.write(line + "\n")
            self._file_handle.flush()

    # ==================== Mouse Events ====================

    def log_mouse_move_start(
        self,
        from_x: float,
        from_y: float,
        to_x: float,
        to_y: float,
        target_width: float = 0,
        target_height: float = 0,
        movement_type: str = "bezier_smooth"
    ) -> None:
        """Log start of mouse movement."""
        self.log(EventType.MOUSE_MOVE_START, {
            "from_x": round(from_x, 1),
            "from_y": round(from_y, 1),
            "to_x": round(to_x, 1),
            "to_y": round(to_y, 1),
            "target_w": round(target_width, 1),
            "target_h": round(target_height, 1),
            "distance": round(((to_x - from_x)**2 + (to_y - from_y)**2)**0.5, 1),
            "movement_type": movement_type
        })

    def log_mouse_move_point(self, x: float, y: float, step: int, delay_ms: float) -> None:
        """Log individual point in mouse path."""
        self.log(EventType.MOUSE_MOVE_POINT, {
            "x": round(x, 1),
            "y": round(y, 1),
            "step": step,
            "delay_ms": round(delay_ms, 2)
        })

    def log_mouse_move_end(
        self,
        x: float,
        y: float,
        duration_ms: float,
        path_points: int,
        movement_type: str = "bezier_smooth"
    ) -> None:
        """Log end of mouse movement."""
        self.log(EventType.MOUSE_MOVE_END, {
            "x": round(x, 1),
            "y": round(y, 1),
            "duration_ms": round(duration_ms, 2),
            "path_points": path_points,
            "movement_type": movement_type
        })

    def log_mouse_click(
        self,
        x: float,
        y: float,
        button: str = "left",
        jitter_x: float = 0,
        jitter_y: float = 0,
        hold_ms: float = None,
        click_style: str = None
    ) -> None:
        """Log mouse click with hold duration and style."""
        data = {
            "x": round(x, 1),
            "y": round(y, 1),
            "button": button,
            "jitter_x": round(jitter_x, 2),
            "jitter_y": round(jitter_y, 2)
        }
        if hold_ms is not None:
            data["hold_ms"] = round(hold_ms, 2)
        if click_style is not None:
            data["click_style"] = click_style
        self.log(EventType.MOUSE_CLICK, data)

    def log_mouse_hover(self, x: float, y: float, duration_ms: float) -> None:
        """Log mouse hover."""
        self.log(EventType.MOUSE_HOVER, {
            "x": round(x, 1),
            "y": round(y, 1),
            "duration_ms": round(duration_ms, 2)
        })

    def log_mouse_tremor(self, base_x: float, base_y: float, offset_x: float, offset_y: float) -> None:
        """Log micro-tremor movement."""
        self.log(EventType.MOUSE_TREMOR, {
            "base_x": round(base_x, 1),
            "base_y": round(base_y, 1),
            "offset_x": round(offset_x, 2),
            "offset_y": round(offset_y, 2)
        })

    def log_mouse_overshoot(
        self,
        target_x: float,
        target_y: float,
        overshoot_px: float,
        correction_px: float = None,
        pause_ms: float = None
    ) -> None:
        """Log target overshoot with correction details."""
        data = {
            "target_x": round(target_x, 1),
            "target_y": round(target_y, 1),
            "overshoot_px": round(overshoot_px, 2)
        }
        if correction_px is not None:
            data["correction_px"] = round(correction_px, 2)
        if pause_ms is not None:
            data["pause_ms"] = round(pause_ms, 1)
        self.log(EventType.MOUSE_OVERSHOOT, data)

    def log_mouse_spiral(self, target_x: float, target_y: float, revolutions: float) -> None:
        """Log spiral approach."""
        self.log(EventType.MOUSE_SPIRAL, {
            "target_x": round(target_x, 1),
            "target_y": round(target_y, 1),
            "revolutions": round(revolutions, 2)
        })

    def log_mouse_overshoot_debug(
        self,
        distance: float,
        overshoot_chance: float,
        should_check: bool,
        roll: float,
        will_overshoot: bool
    ) -> None:
        """Log overshoot decision debug info."""
        self.log(EventType.MOUSE_OVERSHOOT_DEBUG, {
            "distance": round(distance, 1),
            "overshoot_chance": round(overshoot_chance, 3),
            "should_check": should_check,
            "roll": round(roll, 3),
            "will_overshoot": will_overshoot
        })

    # ==================== Keyboard Events ====================

    def log_key_press(self, char: str, is_unicode: bool = False) -> None:
        """Log key press."""
        # Don't log actual characters for privacy, just metadata
        self.log(EventType.KEY_PRESS, {
            "char_code": ord(char) if len(char) == 1 else 0,
            "is_unicode": is_unicode,
            "is_alpha": char.isalpha() if len(char) == 1 else False,
            "is_upper": char.isupper() if len(char) == 1 else False
        })

    def log_key_delay(self, delay_ms: float, mode: str) -> None:
        """Log inter-key delay."""
        self.log(EventType.KEY_DELAY, {
            "delay_ms": round(delay_ms, 2),
            "mode": mode  # "fast" or "slow" (bimodal)
        })

    def log_typo_made(self, typo_type: str, intended_char_code: int) -> None:
        """Log typo being made."""
        self.log(EventType.TYPO_MADE, {
            "typo_type": typo_type,
            "intended_char_code": intended_char_code
        })

    def log_typo_corrected(self, backspaces: int, correction_delay_ms: float) -> None:
        """Log typo correction."""
        self.log(EventType.TYPO_CORRECTED, {
            "backspaces": backspaces,
            "correction_delay_ms": round(correction_delay_ms, 2)
        })

    def log_backspace(self, count: int, delay_ms: float) -> None:
        """Log backspace press."""
        self.log(EventType.BACKSPACE, {
            "count": count,
            "delay_ms": round(delay_ms, 2)
        })

    def log_thinking_pause(self, duration_ms: float) -> None:
        """Log thinking pause during typing."""
        self.log(EventType.THINKING_PAUSE, {
            "duration_ms": round(duration_ms, 2)
        })

    def log_key_hold(self, char_code: int, hold_ms: float) -> None:
        """Log sticky key hold."""
        self.log(EventType.KEY_HOLD, {
            "char_code": char_code,
            "hold_ms": round(hold_ms, 2)
        })

    # ==================== Scroll Events ====================

    def log_scroll_start(self, direction: str, target_px: int, device_type: str) -> None:
        """Log start of scroll action."""
        self.log(EventType.SCROLL_START, {
            "direction": direction,  # "down" or "up"
            "target_px": target_px,
            "device_type": device_type
        })

    def log_scroll_delta(self, delta: int, cumulative: int) -> None:
        """Log individual scroll delta event."""
        self.log(EventType.SCROLL_DELTA, {
            "delta": delta,
            "cumulative": cumulative
        })

    def log_scroll_end(self, total_px: int, num_events: int, duration_ms: float) -> None:
        """Log end of scroll action."""
        self.log(EventType.SCROLL_END, {
            "total_px": total_px,
            "num_events": num_events,
            "duration_ms": round(duration_ms, 2)
        })

    def log_scroll_overshoot(self, overshoot_px: int, correction_px: int) -> None:
        """Log scroll overshoot and correction."""
        self.log(EventType.SCROLL_OVERSHOOT, {
            "overshoot_px": overshoot_px,
            "correction_px": correction_px
        })

    # ==================== Delay Events ====================

    def log_delay(self, delay_type: str, duration_ms: float, mode: Optional[str] = None) -> None:
        """Log any delay/wait."""
        self.log(EventType.DELAY_WAIT, {
            "delay_type": delay_type,
            "duration_ms": round(duration_ms, 2),
            "mode": mode
        })

    def log_bimodal_delay(self, duration_ms: float, mode: str, delay_category: str) -> None:
        """Log bimodal delay with mode info."""
        self.log(EventType.DELAY_BIMODAL, {
            "duration_ms": round(duration_ms, 2),
            "mode": mode,  # "automatic" or "deliberate"
            "category": delay_category  # "typing", "click", "navigation", "reading"
        })

    def log_bimodal_stats(
        self,
        total_samples: int,
        automatic_count: int,
        automatic_pct: float,
        expected_pct: float
    ) -> None:
        """Log bimodal distribution statistics."""
        self.log(EventType.BIMODAL_STATS, {
            "total_samples": total_samples,
            "automatic_count": automatic_count,
            "automatic_pct": round(automatic_pct, 3),
            "expected_pct": round(expected_pct, 3)
        })

    # ==================== Session Events ====================

    def log_profile_characteristics(self, characteristics: Dict[str, Any]) -> None:
        """
        Log profile-specific randomized characteristics at session start.

        Args:
            characteristics: Dict containing mouse, click, scroll, bimodal, keyboard configs
        """
        self.log(EventType.PROFILE_CHARACTERISTICS, characteristics)

    def log_page_navigate(self, url: str) -> None:
        """Log page navigation (URL is hashed for privacy)."""
        import hashlib
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        self.log(EventType.PAGE_NAVIGATE, {
            "url_hash": url_hash,
            "domain": url.split("/")[2] if "/" in url else "unknown"
        })

    def log_window_focus(self) -> None:
        """Log window gaining focus."""
        self.log(EventType.WINDOW_FOCUS, {})

    def log_window_blur(self) -> None:
        """Log window losing focus."""
        self.log(EventType.WINDOW_BLUR, {})

    def log_element_focus(self, selector: str, method: str) -> None:
        """Log element focus."""
        self.log(EventType.ELEMENT_FOCUS, {
            "selector_type": "id" if "#" in selector else "class" if "." in selector else "tag",
            "method": method  # "click" or "programmatic"
        })

    def log_element_type(self, selector: str, char_count: int, duration_ms: float) -> None:
        """Log typing into element."""
        self.log(EventType.ELEMENT_TYPE, {
            "selector_type": "id" if "#" in selector else "class" if "." in selector else "tag",
            "char_count": char_count,
            "duration_ms": round(duration_ms, 2)
        })

    # ==================== Utility Methods ====================

    @property
    def is_closed(self) -> bool:
        """Check if session is already closed."""
        return self._closed

    def get_events(self) -> List[Dict[str, Any]]:
        """Get all logged events as dictionaries."""
        return [e.to_dict() for e in self._events]

    def get_stats(self) -> Dict[str, Any]:
        """Get summary statistics."""
        if not self._events:
            return {}

        event_counts = {}
        for event in self._events:
            event_counts[event.event_type] = event_counts.get(event.event_type, 0) + 1

        duration = time.time() - self._start_time

        return {
            "session_id": self.session_id,
            "profile_id": self.profile_id,
            "total_events": len(self._events),
            "duration_seconds": round(duration, 2),
            "events_per_second": round(len(self._events) / duration, 2) if duration > 0 else 0,
            "event_counts": event_counts
        }

    def close(self, error: Optional[str] = None) -> None:
        """
        Close log file and finalize session.

        Args:
            error: Optional error message if session ended abnormally
        """
        # Prevent double close
        if self._closed:
            return
        self._closed = True

        try:
            # Log session end with stats
            end_data = self.get_stats()
            if error:
                end_data["error"] = error
                end_data["status"] = "error"
            else:
                end_data["status"] = "completed"

            self.log(EventType.SESSION_END, end_data)
        except Exception:
            pass  # Don't fail on logging error

        # Close file handle safely
        if self._file_handle:
            try:
                self._file_handle.flush()
                self._file_handle.close()
            except Exception:
                pass  # Don't fail on file close error
            finally:
                self._file_handle = None

    def __enter__(self) -> "AnalyticsLogger":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        # If exception occurred, log it
        error = None
        if exc_type is not None:
            error = f"{exc_type.__name__}: {exc_val}"
        self.close(error=error)


# Global analytics logger instance
_analytics: Optional[AnalyticsLogger] = None


def init_analytics(
    profile_id: Optional[str] = None,
    log_dir: Optional[Path] = None,
    enabled: bool = True
) -> AnalyticsLogger:
    """Initialize global analytics logger."""
    global _analytics
    _analytics = AnalyticsLogger(
        profile_id=profile_id,
        log_dir=log_dir,
        enabled=enabled
    )
    return _analytics


def get_analytics() -> Optional[AnalyticsLogger]:
    """Get global analytics logger instance."""
    return _analytics


def close_analytics(error: Optional[str] = None) -> None:
    """
    Close global analytics logger.

    Args:
        error: Optional error message if session ended abnormally
    """
    global _analytics
    if _analytics:
        _analytics.close(error=error)
        _analytics = None
