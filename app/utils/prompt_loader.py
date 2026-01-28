"""
Prompt Loader - Utility for loading prompts with dynamic placeholder substitution.

Supports:
- {{BANLIST}} - Injects ban_list.txt content into GEN1 prompt
- Other placeholders can be added in the future

Usage:
    from app.utils.prompt_loader import load_prompt_with_banlist

    prompt = load_prompt_with_banlist(
        prompt_path=settings.CONFIG_DIR / "GEN1.txt",
        banlist_path=settings.CONFIG_DIR / "ban_list.txt"
    )
"""

from pathlib import Path
from typing import Optional

from app.utils.logger import logger


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


def get_default_banlist_path(config_dir: Path) -> Path:
    """Get the default banlist path from config directory."""
    return config_dir / "ban_list.txt"


__all__ = ["load_prompt_with_banlist", "get_default_banlist_path"]
