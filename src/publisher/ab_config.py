"""
A/B Metadata Rotation Configuration

Thresholds, timing, and rotation constants for the A/B monitoring system.
Calibrated for a new channel (0 subscribers) based on YouTube Shorts
seed-test mechanics: ~200-1500 initial impressions, 2-5% CTR in feed.

Sources:
- YouTube seed phase gives 200-1500 impressions to new Shorts
- "200 views in 2 days = good" for 0-sub channels (Quora creator data)
- 85% of Shorts impressions arrive within 48h
- Since March 2025 every view/replay counts (no min watch time)
"""

# Evaluation checkpoints (calibrated for 0-subscriber channel)
# Each checkpoint defines hours since variant start, and view thresholds.
# - dead_below: Swap triggered (video got no traction from seed test)
# - uncertain_below: Gray zone — wait for next checkpoint
# - alive_above: Video is performing, stop monitoring
#
# Scale these UP as channel grows (e.g., 3-5x for 1000+ subs).
THRESHOLDS = {
    "check_1": {
        "hours": 6,
        "dead_below": 15,           # seed test gave ~0 impressions
        "uncertain_below": 50,      # seed test inconclusive
        "alive_above": 50,          # seed test passed, algo expanding
    },
    "check_2": {
        "hours": 18,
        "dead_below": 40,           # impressions stopped
        "alive_above": 150,         # active distribution
    },
    "check_3": {
        "hours": 48,
        "dead_below": 100,          # final evaluation — no traction
        "alive_above": 100,         # minimum viability reached
    },
}

# Variant rotation order
ROTATION_ORDER = ["A", "B", "C", "D"]

# Maximum number of swaps (A->B->C->D = 3 swaps)
MAX_SWAPS = 3

# Checkpoint-aligned polling: daemon sleeps until next checkpoint
# instead of fixed-interval polling.
MIN_INTERVAL_MINUTES = 120          # floor: never poll more often than 2h
MAX_INTERVAL_MINUTES = 360          # ceiling: health-check even if no checkpoint soon
CHECKPOINT_MARGIN_MINUTES = 5       # wake up 5 min before checkpoint for precision

# Legacy constant kept for backwards compatibility with any external code
MONITOR_INTERVAL_MINUTES = MIN_INTERVAL_MINUTES

# Swap window: metadata changes are most effective when done during
# low-traffic hours (2:00-6:00 AM ET) so the new variant gets a fresh
# seed push during peak hours. CHECK #1 (dead) swaps immediately.
SWAP_WINDOW_START_HOUR = 2   # 02:00 ET
SWAP_WINDOW_END_HOUR = 6     # 06:00 ET
SWAP_WINDOW_TIMEZONE = "America/New_York"

# API retry settings for monitor operations
MONITOR_API_MAX_RETRIES = 3
