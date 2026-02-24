"""
Prompt Loader - Utility for loading prompts with dynamic placeholder substitution.

Supports:
- {{BANLIST}} - Injects ban_list.txt content into GEN1 prompt
- {{CHANNEL_*}} - Injects channel branding values from config/channels/{channel_id}/config.json

Usage:
    from app.utils.prompt_loader import load_prompt_with_banlist, load_prompt_with_channel

    # Basic (banlist only)
    prompt = load_prompt_with_banlist(
        prompt_path=settings.CONFIG_DIR / "GEN1.txt",
        banlist_path=settings.CONFIG_DIR / "ban_list.txt"
    )

    # Channel-aware (banlist + branding placeholders)
    prompt = load_prompt_with_channel(
        prompt_path=settings.CONFIG_DIR / "GEN1.txt",
        channel_id="yum_estate"
    )
"""

import json
from pathlib import Path
from typing import Optional, Dict

from app.utils.logger import logger


# Channel config directory
_CHANNELS_DIR = Path(__file__).parent.parent.parent / "config" / "channels"


def load_prompt_with_banlist(
    prompt_path: Path,
    banlist_path: Optional[Path] = None,
    banlist_placeholder: str = "{{BANLIST}}"
) -> str:
    """
    Load a prompt file and substitute {{BANLIST}} placeholder with ban_list.txt content.

    Args:
        prompt_path: Path to the prompt file (e.g., GEN1.txt)
        banlist_path: Path to the banlist file (e.g., ban_list.txt).
                      If None, will try to find ban_list.txt in the same directory as prompt_path.
        banlist_placeholder: The placeholder string to replace (default: "{{BANLIST}}")

    Returns:
        Prompt string with banlist injected

    Raises:
        FileNotFoundError: If prompt_path doesn't exist

    Note:
        If banlist_path doesn't exist, logs a warning and continues with empty banlist.
    """
    # Validate prompt file exists
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")

    # Read prompt
    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt = f.read()

    # Determine banlist path if not provided
    if banlist_path is None:
        banlist_path = prompt_path.parent / "ban_list.txt"

    # Read banlist (REQUIRED - exit on error)
    if not banlist_path.exists():
        raise FileNotFoundError(
            f"Banlist file not found: {banlist_path}\n"
            f"This file is REQUIRED for content generation."
        )

    with open(banlist_path, "r", encoding="utf-8") as f:
        banlist_content = f.read().strip()
    logger.debug(f"Loaded banlist: {len(banlist_content)} chars from {banlist_path.name}")

    # Substitute placeholder
    if banlist_placeholder in prompt:
        prompt = prompt.replace(banlist_placeholder, banlist_content)
        logger.debug(f"Injected banlist into prompt (placeholder: {banlist_placeholder})")
    else:
        logger.debug(f"No {banlist_placeholder} placeholder found in prompt")

    return prompt


def load_channel_branding(channel_id: str) -> Dict[str, str]:
    """
    Load branding config for a channel and return a flat placeholder→value map.

    Reads config/channels/{channel_id}/config.json → branding section,
    then maps it to {{CHANNEL_*}} placeholders.

    Args:
        channel_id: Channel identifier (e.g., "glaze_city", "yum_estate")

    Returns:
        Dict mapping placeholder strings to their values, e.g.:
        {"{{CHANNEL_BRAND}}": "GLAZE CITY", "{{CHANNEL_BRAND_DISPLAY}}": "Glaze City", ...}

    Raises:
        FileNotFoundError: If channel config doesn't exist
        KeyError: If branding section is missing
    """
    config_path = _CHANNELS_DIR / channel_id / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Channel config not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    branding = config.get("branding")
    if not branding:
        raise KeyError(f"No 'branding' section in channel config: {config_path}")

    audio_stings = branding.get("audio_stings", {})

    placeholders = {
        "{{CHANNEL_BRAND}}": branding["brand_name"],
        "{{CHANNEL_BRAND_DISPLAY}}": branding["brand_name_display"],
        "{{CHANNEL_ID}}": channel_id,
        "{{CREATIVE_DIRECTOR_TITLE}}": branding["creative_director_title"],
        "{{OPEN_SFX_FILE}}": audio_stings.get("open_sfx", ""),
        "{{STING_SFX_FILE}}": audio_stings.get("sting_sfx", ""),
        "{{OPEN_SFX_NAME}}": audio_stings.get("open_name", ""),
        "{{WHOOSH_SFX_NAME}}": audio_stings.get("whoosh_name", ""),
        "{{STING_SFX_NAME}}": audio_stings.get("sting_name", ""),
        "{{WATERMARK_TEXT}}": branding.get("watermark_text", branding["brand_name"]),
        "{{DESCRIPTION_PREFIX}}": branding.get("description_prefix", ""),
        "{{SUBTITLE_TITLE}}": branding.get("subtitle_title", f"{branding['brand_name_display']} Subtitles"),
    }

    logger.debug(f"Loaded branding for channel '{channel_id}': {len(placeholders)} placeholders")
    return placeholders


def load_prompt_with_channel(
    prompt_path: Path,
    channel_id: str,
    banlist_path: Optional[Path] = None,
) -> str:
    """
    Load a prompt file with banlist injection AND channel branding placeholders.

    Order: banlist first → then channel placeholders.

    Args:
        prompt_path: Path to the prompt file (e.g., GEN1.txt)
        channel_id: Channel identifier (e.g., "glaze_city", "yum_estate")
        banlist_path: Optional explicit banlist path

    Returns:
        Prompt string with all placeholders resolved
    """
    # Step 1: Load with banlist
    prompt = load_prompt_with_banlist(prompt_path, banlist_path)

    # Step 2: Apply channel branding placeholders
    placeholders = load_channel_branding(channel_id)
    for placeholder, value in placeholders.items():
        if placeholder in prompt:
            prompt = prompt.replace(placeholder, value)

    # Step 3: Verify no unresolved {{CHANNEL_*}} placeholders remain
    import re
    unresolved = re.findall(r"\{\{CHANNEL_[A-Z_]+\}\}", prompt)
    if unresolved:
        logger.warning(f"Unresolved channel placeholders in {prompt_path.name}: {unresolved}")

    logger.debug(f"Loaded prompt with channel '{channel_id}': {len(prompt)} chars")
    return prompt


def get_default_banlist_path(config_dir: Path) -> Path:
    """Get the default banlist path from config directory."""
    return config_dir / "ban_list.txt"


__all__ = [
    "load_prompt_with_banlist",
    "load_prompt_with_channel",
    "load_channel_branding",
    "get_default_banlist_path",
]
