"""
Timing Utilities for GEN3a/GEN3b autocorrectors.

Shared timing transformation functions extracted from manifest_renderer.py.
Used by gen3a_autocorrect.py and gen3b_autocorrect.py to convert
source-domain timestamps to output-domain timestamps via speed segments.

Usage:
    from app.services.timing_utils import (
        transform_source_to_output,
        calculate_output_duration,
        build_cumulative_starts,
    )
"""

from __future__ import annotations

from typing import Any, Dict, List


def transform_source_to_output(
    source_time: float,
    speed_segments: List[Dict[str, Any]],
) -> float:
    """
    Transform a source video timestamp to output time using speed segments.

    Walks through speed segments in order, accumulating output time.
    If source_time falls within a segment, partial time is added.
    If source_time is beyond all segments, total output duration is returned.

    Args:
        source_time: Timestamp in source video (0-10s typical).
        speed_segments: List of dicts with source_start, source_end, speed.

    Returns:
        Corresponding timestamp in output domain.
    """
    if not speed_segments:
        return source_time

    output_time = 0.0
    for segment in speed_segments:
        # Handle both Gemini raw keys (start/end) and Pydantic keys (source_start/source_end)
        seg_start = float(segment.get("source_start", segment.get("start", 0.0)))
        seg_end = float(segment.get("source_end", segment.get("end", 0.0)))
        speed = float(segment.get("speed", 1.0)) or 1.0

        if source_time < seg_start:
            break
        elif source_time <= seg_end:
            time_in_segment = source_time - seg_start
            output_time += time_in_segment / speed
            break
        else:
            segment_duration = (seg_end - seg_start) / speed
            output_time += segment_duration

    return round(output_time, 4)


def calculate_output_duration(speed_segments: List[Dict[str, Any]]) -> float:
    """
    Calculate total output duration from speed segments.

    Args:
        speed_segments: List of dicts with source_start, source_end, speed.

    Returns:
        Total output duration in seconds.
    """
    if not speed_segments:
        return 0.0

    total = 0.0
    for segment in speed_segments:
        # Handle both Gemini raw keys (start/end) and Pydantic keys (source_start/source_end)
        source_start = float(segment.get("source_start", segment.get("start", 0.0)))
        source_end = float(segment.get("source_end", segment.get("end", 0.0)))
        speed = float(segment.get("speed", 1.0)) or 1.0
        total += (source_end - source_start) / speed

    return round(total, 4)


def build_cumulative_starts(scenes: List[Dict[str, Any]]) -> Dict[str, float]:
    """
    Build cumulative scene start times from scene list.

    Args:
        scenes: List of scene dicts with scene_number and output_duration.

    Returns:
        Dict mapping "scene_N" -> cumulative start time.
    """
    result = {}
    current_start = 0.0
    for scene in scenes:
        scene_num = scene.get("scene_number", 0)
        result[f"scene_{scene_num}"] = round(current_start, 4)
        current_start += float(scene.get("output_duration", 0.0))
    return result
