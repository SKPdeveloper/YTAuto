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


# =============================================================================
# ЗАЛІЗОБЕТОННЕ РІШЕННЯ: Deep Merge GEN1 + GEN2
# =============================================================================

def deep_merge(base: dict, override: dict) -> dict:
    """
    Рекурсивно об'єднує два dict. Override має пріоритет.

    Правила:
    - Якщо обидва значення dict → рекурсивний merge
    - Якщо ключ "scenes" → спеціальний merge по scene_number
    - Інакше override перезаписує base (якщо не None)
    """
    result = base.copy()

    for key, override_value in override.items():
        if key not in result:
            result[key] = override_value
        elif key == "scenes" and isinstance(result[key], list) and isinstance(override_value, list):
            result[key] = _merge_scenes_by_number(result[key], override_value)
        elif isinstance(result[key], dict) and isinstance(override_value, dict):
            result[key] = deep_merge(result[key], override_value)
        elif override_value is not None:
            result[key] = override_value

    return result


def _merge_scenes_by_number(gen1_scenes: list, gen2_scenes: list) -> list:
    """Об'єднує scenes по scene_number."""
    gen1_map = {s.get("scene_number", i+1): s for i, s in enumerate(gen1_scenes)}
    gen2_map = {s.get("scene_number", i+1): s for i, s in enumerate(gen2_scenes)}

    all_numbers = sorted(set(gen1_map.keys()) | set(gen2_map.keys()))

    merged_scenes = []
    for num in all_numbers:
        gen1_scene = gen1_map.get(num, {})
        gen2_scene = gen2_map.get(num, {})
        merged_scene = deep_merge(gen1_scene, gen2_scene)
        merged_scenes.append(merged_scene)

    return merged_scenes


def save_merged_project_brief(
    gen1_dict: dict,
    gen2_dict: dict,
    project_id: str,
    output_dir: Path
) -> Path:
    """
    ЗАЛІЗОБЕТОННИЙ MERGE: зберігає deep merged GEN1+GEN2 без втрат.

    Це головна функція для збереження project_brief.json.
    Нічого не губиться, всі поля з обох джерел присутні.

    Args:
        gen1_dict: Повний вихід GEN1 (gen1.model_dump())
        gen2_dict: Повний вихід GEN2 (gen2.model_dump())
        project_id: ID проекту
        output_dir: Папка для збереження

    Returns:
        Path до збереженого файлу
    """
    from datetime import datetime

    output_dir.mkdir(parents=True, exist_ok=True)
    brief_path = output_dir / "project_brief.json"

    # Deep merge: GEN1 + GEN2
    merged = deep_merge(gen1_dict, gen2_dict)

    # Додаємо metadata
    merged["project_id"] = project_id
    merged["_meta"] = {
        "project_id": project_id,
        "created_at": datetime.now().isoformat(),
        "generator": "GLAZE CITY VIRAL ENGINE v4.1 - DEEP MERGE"
    }

    # Зберігаємо RAW для страховки
    merged["gen1_raw"] = gen1_dict
    merged["gen2_raw"] = gen2_dict

    # Зберігаємо
    with open(brief_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    logger.success(f"[DEEP MERGE] Saved project brief: {brief_path}")
    logger.info(f"  GEN1 keys: {len(gen1_dict)}")
    logger.info(f"  GEN2 keys: {len(gen2_dict)}")
    logger.info(f"  Merged keys: {len(merged)}")
    logger.info(f"  Scenes: {len(merged.get('scenes', []))}")

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
    "save_merged_project_brief",
    "save_raw_output",
    "deep_merge",
]
