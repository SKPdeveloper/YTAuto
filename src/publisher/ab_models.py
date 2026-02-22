"""
A/B Metadata Rotation Models

Pydantic v2 models for tracking YouTube Shorts A/B metadata rotation.
Each video can cycle through up to 4 variants (A->B->C->D) based on
performance checkpoints at 6h, 18h, and 48h.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from enum import Enum

from loguru import logger
from pydantic import BaseModel, Field


class ABStatus(str, Enum):
    """Status of a video in the A/B rotation system."""
    MONITORING = "monitoring"   # Actively being monitored
    SUCCESS = "success"         # Hit alive threshold, no more swaps needed
    EXHAUSTED = "exhausted"     # All 4 variants used, none succeeded
    MANUAL = "manual"           # API errors, needs manual intervention
    ERROR = "error"             # Video deleted/blocked/not found
    STOPPED = "stopped"         # Manually stopped by user


class VariantData(BaseModel):
    """Metadata for a single variant (A/B/C/D)."""
    trigger: str = Field(..., description="Psychological trigger (e.g., SATISFYING, FORBIDDEN)")
    title: str = Field(..., description="YouTube title for this variant")
    description: str = Field(..., description="YouTube description for this variant")
    pinned_comment: Optional[str] = Field(default=None, description="Pinned comment text")


class SwapRecord(BaseModel):
    """Record of a single metadata swap."""
    from_variant: str = Field(..., description="Previous variant letter")
    to_variant: str = Field(..., description="New variant letter")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    views_at_swap: int = Field(..., description="View count at time of swap")
    reason: str = Field(..., description="Why the swap was triggered (e.g., check_1_dead)")


class MetricsSnapshot(BaseModel):
    """Point-in-time metrics for a video."""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    views: int = 0
    likes: int = 0
    comments: int = 0


class VideoABRecord(BaseModel):
    """Complete A/B rotation state for a single video."""
    video_id: str = Field(..., description="YouTube video ID")
    project_id: str = Field(..., description="YTAuto project ID")
    channel_id: str = Field(..., description="Internal channel ID")
    upload_time: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC time of initial upload",
    )
    scheduled_go_live: Optional[datetime] = Field(
        default=None,
        description="UTC time when video is scheduled to go public (None = already live)",
    )
    variant_start_time: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC time when current variant started (resets on swap)",
    )
    current_variant: str = Field(default="A", description="Current active variant letter")
    status: ABStatus = Field(default=ABStatus.MONITORING, description="Monitoring status")
    checks_completed: List[str] = Field(
        default_factory=list,
        description="Completed checkpoint names (e.g., ['check_1', 'check_2'])",
    )
    variants: Dict[str, VariantData] = Field(
        default_factory=dict,
        description="All available variants keyed by letter",
    )
    swap_history: List[SwapRecord] = Field(default_factory=list, description="History of swaps")
    metrics_log: List[MetricsSnapshot] = Field(
        default_factory=list,
        description="Time-series metrics snapshots",
    )
    pending_comment_text: Optional[str] = Field(
        default=None,
        description="Comment to post via API when scheduled video goes live (cleared after posting)",
    )
    current_comment_id: Optional[str] = Field(
        default=None,
        description="YouTube comment ID of current pinned comment",
    )
    final_variant: Optional[str] = Field(
        default=None,
        description="Variant that succeeded or was active when monitoring ended",
    )
    final_views_48h: Optional[int] = Field(
        default=None,
        description="View count at 48h mark (for reporting)",
    )
    gen1_output_path: Optional[str] = Field(
        default=None,
        description="Path to gen1_output.json for reference",
    )


class ABRotationStore(BaseModel):
    """Root model for the A/B rotation JSON store."""
    version: str = "1.0"
    videos: List[VideoABRecord] = Field(default_factory=list)


# ============================================================================
# UTILITY: Shared variant parser
# ============================================================================

_VARIANT_KEYS = [
    ("variant_a", "A"),
    ("variant_b", "B"),
    ("variant_c", "C"),
    ("variant_d", "D"),
]


def parse_metadata_variants(gen1_data: dict) -> Tuple[Dict[str, VariantData], List[str]]:
    """
    Extract metadata variants from gen1_output data.

    Used by both publisher._register_for_ab_monitoring and CLI 'ab register'.

    Args:
        gen1_data: Parsed gen1_output.json dict

    Returns:
        Tuple of (variants_dict, warnings_list).
        variants_dict maps letter -> VariantData.
        warnings_list contains human-readable skip reasons.
    """
    variants_data = gen1_data.get("metadata_variants")
    warnings: List[str] = []

    if not variants_data:
        return {}, ["No metadata_variants found in gen1_output"]

    variants: Dict[str, VariantData] = {}

    for key, letter in _VARIANT_KEYS:
        vdata = variants_data.get(key)
        if not vdata or not isinstance(vdata, dict):
            continue

        v_title = vdata.get("title", "").strip()
        v_desc = vdata.get("description", "").strip()

        if not v_title:
            warnings.append(f"Skipping variant {letter}: empty title")
            continue

        variants[letter] = VariantData(
            trigger=vdata.get("trigger", letter),
            title=v_title,
            description=v_desc,
            pinned_comment=vdata.get("pinned_comment"),
        )

    return variants, warnings
