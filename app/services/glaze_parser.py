"""
GLAZE CITY JSON Parser

Простий парсер для JSON виводу GLAZE CITY VIRAL ENGINE v4.1.
Замість складного regex парсингу markdown - просто витягуємо JSON.

IMPORTANT: Цей парсер працює з JSON виводом згенерованим за допомогою
PROTECTED системних промптів: config/GEN1.txt та config/GEN2.txt
"""

import re
import json
import uuid
from typing import Optional
from pathlib import Path
from datetime import datetime

from app.utils.logger import logger
from app.services.glaze_models import GlazeCityProject


class GlazeParser:
    """
    Simple JSON parser for GLAZE CITY VIRAL ENGINE v4.1 output.

    Витягує JSON з відповіді LLM та конвертує в GlazeCityProject.
    """

    def __init__(self):
        """Initialize parser."""
        self.raw_output = ""

    def parse(self, llm_response: str) -> GlazeCityProject:
        """
        Parse LLM response containing JSON into GlazeCityProject.

        Args:
            llm_response: Raw response from LLM (may include ```json blocks)

        Returns:
            GlazeCityProject with all parsed data
        """
        self.raw_output = llm_response
        logger.info("Parsing GLAZE CITY JSON output...")
        logger.debug(f"  Input length: {len(llm_response)} chars")

        # Extract JSON from response
        json_str = self._extract_json(llm_response)

        if not json_str:
            raise ValueError("No valid JSON found in LLM response")

        # Parse JSON
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            logger.debug(f"JSON string (first 500 chars): {json_str[:500]}")
            raise ValueError(f"Invalid JSON in LLM response: {e}")

        # Generate project ID
        project_id = f"glaze_{uuid.uuid4().hex[:12]}"

        # Add processing fields
        data["project_id"] = project_id
        data["created_at"] = datetime.now().isoformat()
        data["raw_output"] = llm_response

        # Create project from dict
        try:
            project = GlazeCityProject.model_validate(data)
        except Exception as e:
            logger.error(f"Model validation error: {e}")
            raise ValueError(f"JSON structure doesn't match schema: {e}")

        logger.success(f"Parsed GLAZE CITY project: {project_id}")
        logger.info(f"  Property: {project.property.name}")
        logger.info(f"  Scenes: {len(project.scenes)}")
        logger.info(f"  Duration: {project.total_duration}s")

        return project

    def _extract_json(self, text: str) -> Optional[str]:
        """
        Extract JSON from LLM response.

        Handles:
        - ```json ... ``` code blocks
        - Raw JSON objects
        - JSON with surrounding text
        """
        # Method 1: Try to find ```json code block
        json_block_pattern = r"```json\s*([\s\S]*?)```"
        match = re.search(json_block_pattern, text, re.IGNORECASE)
        if match:
            logger.debug("Found JSON in ```json code block")
            return match.group(1).strip()

        # Method 2: Try to find ``` code block (without json marker)
        code_block_pattern = r"```\s*([\s\S]*?)```"
        match = re.search(code_block_pattern, text)
        if match:
            content = match.group(1).strip()
            # Check if it looks like JSON
            if content.startswith("{"):
                logger.debug("Found JSON in ``` code block")
                return content

        # Method 3: Try to find raw JSON object
        # Find the first { and last }
        first_brace = text.find("{")
        last_brace = text.rfind("}")

        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            potential_json = text[first_brace:last_brace + 1]
            # Quick validation - try to parse
            try:
                json.loads(potential_json)
                logger.debug("Found raw JSON object in text")
                return potential_json
            except json.JSONDecodeError:
                pass

        logger.warning("No JSON found in response")
        return None

    def parse_file(self, file_path: Path) -> GlazeCityProject:
        """
        Parse JSON from file.

        Args:
            file_path: Path to JSON file

        Returns:
            GlazeCityProject
        """
        logger.info(f"Parsing GLAZE CITY from file: {file_path}")

        content = file_path.read_text(encoding="utf-8")
        return self.parse(content)


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def save_project_brief(project: GlazeCityProject, output_dir: Path) -> Path:
    """
    Save project as JSON brief for manual editing.

    Args:
        project: Parsed project
        output_dir: Directory to save

    Returns:
        Path to saved file
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    brief_path = output_dir / "project_brief.json"

    # Convert to dict, excluding some fields
    data = project.model_dump(
        exclude={"raw_output", "project_dir", "created_at"},
        mode="json"
    )

    # Add metadata
    data["_meta"] = {
        "project_id": project.project_id,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "generator": "GLAZE CITY VIRAL ENGINE v4.1"
    }

    with open(brief_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    logger.info(f"Saved project brief: {brief_path}")
    return brief_path


def save_raw_output(raw_output: str, output_dir: Path) -> Path:
    """
    Save raw LLM output for reference.

    Args:
        raw_output: Original LLM response
        output_dir: Directory to save

    Returns:
        Path to saved file
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_path = output_dir / "raw_output.json"

    with open(raw_path, "w", encoding="utf-8") as f:
        f.write(raw_output)

    logger.info(f"Saved raw output: {raw_path}")
    return raw_path


# ============================================================================
# EXPORT
# ============================================================================

__all__ = [
    "GlazeParser",
    "save_project_brief",
    "save_raw_output",
]
