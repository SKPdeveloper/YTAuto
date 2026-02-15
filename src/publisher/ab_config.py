"""
A/B Metadata Rotation Configuration

Thresholds, timing, and rotation constants for the A/B monitoring system.
Based on empirical Glaze City Shorts performance data and YouTube Shorts
algorithm research (seed testing cycle, distribution patterns).
"""

# Evaluation checkpoints
# Each checkpoint defines hours since variant start, and view thresholds.
# - dead_below: Immediate swap (video is dead)
# - uncertain_below: May swap at next checkpoint
# - alive_above: Video is performing, stop monitoring
THRESHOLDS = {
    "check_1": {
        "hours": 6,
        "dead_below": 50,
        "uncertain_below": 200,
        "alive_above": 200,
    },
    "check_2": {
        "hours": 18,
        "dead_below": 200,
        "alive_above": 500,
    },
    "check_3": {
        "hours": 48,
        "dead_below": 500,
        "alive_above": 500,
    },
}

# Variant rotation order
ROTATION_ORDER = ["A", "B", "C", "D"]

# Maximum number of swaps (A->B->C->D = 3 swaps)
MAX_SWAPS = 3

# How often the daemon polls for videos to evaluate (minutes)
MONITOR_INTERVAL_MINUTES = 30

# Swap window: metadata changes are most effective when done during
# low-traffic hours (2:00-6:00 AM ET) so the new variant gets a fresh
# seed push during peak hours. CHECK #1 (dead) swaps immediately.
SWAP_WINDOW_START_HOUR = 2   # 02:00 ET
SWAP_WINDOW_END_HOUR = 6     # 06:00 ET
SWAP_WINDOW_TIMEZONE = "America/New_York"

# API retry settings for monitor operations
MONITOR_API_MAX_RETRIES = 3
