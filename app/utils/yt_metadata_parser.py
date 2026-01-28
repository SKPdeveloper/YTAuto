"""
YouTube Metadata Parser - Extracts YouTube posting info from GEN1 output.

Creates YT.txt file with easy-to-copy format:
- No quotes around text
- Each section is a separate paragraph (triple-click to select)
- Tags separated by commas (no quotes)

Usage:
    from app.utils.yt_metadata_parser import parse_gen1_to_yt_file

    # From GEN1 dict
    parse_gen1_to_yt_file(gen1_output, output_path)

    # From JSON file
    parse_gen1_json_to_yt_file(json_path, output_path)
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional, Union

from loguru import logger


def extract_youtube_metadata(gen1_data: Dict[str, Any]) -> Dict[str, str]:
    """
    Extract YouTube metadata from GEN1 output.

    Args:
        gen1_data: Parsed GEN1 JSON data

    Returns:
        Dict with keys: title, description, tags, hashtags, pinned_comment
    """
    # Try flat fields first (youtube_title, etc.), then nested (youtube.title)
    title = gen1_data.get("youtube_title") or gen1_data.get("youtube", {}).get("title", "")
    description = gen1_data.get("youtube_description") or gen1_data.get("youtube", {}).get("description", "")
    pinned_comment = gen1_data.get("youtube_pinned_comment") or gen1_data.get("youtube", {}).get("pinned_comment", "")

    # Tags - list to comma-separated string
    tags_list = gen1_data.get("youtube_tags") or gen1_data.get("youtube", {}).get("tags", [])
    tags = ", ".join(tags_list) if isinstance(tags_list, list) else str(tags_list)

    # Hashtags - list to space-separated string
    hashtags_list = gen1_data.get("youtube_hashtags") or gen1_data.get("engagement", {}).get("hashtags", [])
    hashtags = " ".join(hashtags_list) if isinstance(hashtags_list, list) else str(hashtags_list)

    return {
        "title": title,
        "description": description,
        "tags": tags,
        "hashtags": hashtags,
        "pinned_comment": pinned_comment,
    }


def format_yt_metadata(metadata: Dict[str, str]) -> str:
    """
    Format YouTube metadata as easy-to-copy text.

    Format:
    - Section headers in ALL CAPS
    - Empty line between sections
    - No quotes anywhere
    - Each value on its own line(s) for easy triple-click selection
    """
    lines = []

    # Title section
    lines.append("TITLE")
    lines.append(metadata.get("title", ""))
    lines.append("")

    # Description section (includes hashtags at the end typically)
    lines.append("DESCRIPTION")
    description = metadata.get("description", "")
    lines.append(description)
    lines.append("")

    # Tags section (comma-separated, no quotes)
    lines.append("TAGS")
    lines.append(metadata.get("tags", ""))
    lines.append("")

    # Pinned comment section
    lines.append("PINNED COMMENT")
    lines.append(metadata.get("pinned_comment", ""))

    return "\n".join(lines)


def parse_gen1_to_yt_file(
    gen1_data: Dict[str, Any],
    output_path: Union[str, Path],
) -> Path:
    """
    Parse GEN1 output dict and save YouTube metadata to YT.txt.

    Args:
        gen1_data: Parsed GEN1 JSON data (dict)
        output_path: Path where to save YT.txt

    Returns:
        Path to created YT.txt file
    """
    output_path = Path(output_path)

    # Extract metadata
    metadata = extract_youtube_metadata(gen1_data)

    # Format as text
    content = format_yt_metadata(metadata)

    # Write file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info(f"Saved YouTube metadata to: {output_path}")
    return output_path


def parse_gen1_json_to_yt_file(
    json_path: Union[str, Path],
    output_path: Optional[Union[str, Path]] = None,
) -> Path:
    """
    Parse GEN1 JSON file and save YouTube metadata to YT.txt.

    Args:
        json_path: Path to gen1_output.json file
        output_path: Path where to save YT.txt (default: same dir as json, named YT.txt)

    Returns:
        Path to created YT.txt file
    """
    json_path = Path(json_path)

    if not json_path.exists():
        raise FileNotFoundError(f"GEN1 JSON file not found: {json_path}")

    # Default output path
    if output_path is None:
        output_path = json_path.parent / "YT.txt"
    else:
        output_path = Path(output_path)

    # Read JSON
    with open(json_path, "r", encoding="utf-8") as f:
        gen1_data = json.load(f)

    return parse_gen1_to_yt_file(gen1_data, output_path)


__all__ = [
    "extract_youtube_metadata",
    "format_yt_metadata",
    "parse_gen1_to_yt_file",
    "parse_gen1_json_to_yt_file",
]
