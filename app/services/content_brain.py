"""
Content Brain - AI-powered script generation and image validation

Uses Google Gemini API for:
1. Script generation from topic/idea (with GLAZE CITY system prompt)
2. Scene breakdown with detailed prompts
3. Image validation with Gemini Vision

Provider: Google Gemini (gemini-3-pro)
SDK: google-genai (new unified SDK)

PROTECTED FILE WARNING:
The system prompt file (config/GEN1.txt) is PROTECTED.
DO NOT EDIT that file without explicit user permission.
See PROTECTED_FILES.md for details.
"""

import json
import math
from google import genai
from google.genai import types
from pathlib import Path
from typing import List, Optional
from PIL import Image

from app.core.config import settings
from app.utils.logger import logger
from app.services.glaze_models import GlazeCityProject
from app.services.glaze_parser import GlazeParser, save_project_brief, save_raw_output
from app.services.validation_models import SimpleValidationResult
from app.utils.prompt_loader import load_prompt_with_banlist, load_prompt_with_channel

# =============================================================================
# PROTECTED SYSTEM PROMPT - DO NOT EDIT THE SOURCE FILE
# =============================================================================
SYSTEM_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "GEN1.txt"


# =============================================================================
# DUPLICATE FRAMES DETECTION (pixel-level pre-check, no AI dependency)
# =============================================================================

def _row_std_dev(img_gray: Image.Image, y: int, width: int, sample_step: int = 3) -> float:
    """Compute standard deviation of pixel brightness in a single row."""
    row_strip = img_gray.crop((0, y, width, y + 1))
    pixels = list(row_strip.getdata())
    sampled = pixels[::sample_step]
    if len(sampled) < 10:
        return 999.0
    mean = sum(sampled) / len(sampled)
    variance = sum((p - mean) ** 2 for p in sampled) / len(sampled)
    return math.sqrt(variance)


def detect_duplicate_frames(image_path: Path) -> bool:
    """
    Fast pixel-level detection of duplicate frames (2+ images in one).

    Common AI generation glitch: generator produces a collage/grid instead
    of a single image. Detected by finding a horizontal seam (divider band)
    near the center — a strip of near-uniform color (usually white/black)
    with real image content on both sides.

    Algorithm:
    1. Scan rows in center 30% of the image
    2. Find bands of low-variance rows (uniform color = potential seam)
    3. Check content 30-60px AWAY from seam on both sides
    4. If both sides have real content (high variance), it's a double image

    Args:
        image_path: Path to the image to check

    Returns:
        True if duplicate frames detected (image should be rejected)
    """
    try:
        img = Image.open(image_path).convert('L')  # Grayscale
        width, height = img.size

        # Only check center 30% of image height
        y_start = int(height * 0.35)
        y_end = int(height * 0.65)

        # Phase 1: Find seam band (consecutive low-variance rows)
        seam_start = None
        seam_end = None

        y = y_start
        while y < y_end:
            std = _row_std_dev(img, y, width)

            if std < 5.0:
                # Found a low-variance row — scan for the full band
                band_start = y
                band_end = y
                while band_end < y_end:
                    next_std = _row_std_dev(img, band_end + 1, width)
                    if next_std < 10.0:
                        band_end += 1
                    else:
                        break

                band_width = band_end - band_start + 1

                # Seam band: 1-30 rows of uniform color (not a huge uniform area)
                if 1 <= band_width <= 30:
                    seam_start = band_start
                    seam_end = band_end
                    break

                # Skip past this band
                y = band_end + 1
                continue

            y += 1

        if seam_start is None:
            return False

        # Phase 2: Check content AWAY from the seam (30-60px on each side)
        # Skip transition zone near the seam edge
        above_check_start = max(0, seam_start - 60)
        above_check_end = max(0, seam_start - 15)
        below_check_start = min(height - 1, seam_end + 15)
        below_check_end = min(height - 1, seam_end + 60)

        above_stds = [
            _row_std_dev(img, cy, width)
            for cy in range(above_check_start, above_check_end, 4)
        ]
        below_stds = [
            _row_std_dev(img, cy, width)
            for cy in range(below_check_start, below_check_end, 4)
        ]

        if not above_stds or not below_stds:
            return False

        avg_above = sum(above_stds) / len(above_stds)
        avg_below = sum(below_stds) / len(below_stds)

        # Both sides must have real image content (std > 15)
        if avg_above > 15 and avg_below > 15:
            band_width = seam_end - seam_start + 1
            logger.warning(
                f"DUPLICATE_FRAMES detected: seam at y={seam_start}-{seam_end} "
                f"(band={band_width}px, above_avg={avg_above:.1f}, below_avg={avg_below:.1f})"
            )
            return True

        return False

    except Exception as e:
        logger.warning(f"Duplicate frame detection failed: {e}")
        return False  # Don't block pipeline on detection errors


class ContentBrain:
    """
    AI-powered Content Generation and Validation

    Responsibilities:
    - Generate video scripts from topics
    - Create detailed scene descriptions
    - Generate image and motion prompts
    - Validate generated images with Gemini Vision

    Uses Google Gemini API with structured JSON output
    """

    def __init__(self, channel_id: str = "glaze_city"):
        """Initialize Content Brain with Gemini API and channel-aware system prompt"""
        self.channel_id = channel_id

        # Initialize Gemini Client (new unified SDK)
        self.client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY)

        # =================================================================
        # LOAD PROTECTED SYSTEM PROMPT (READ-ONLY)
        # =================================================================
        self.system_prompt = self._load_system_prompt()

        # Models - використовуємо одну модель для всього (Gemini 3 Pro)
        self.model_name = settings.CONTENTBRAIN_MODEL  # gemini-3-pro
        self.temperature = settings.GEMINI_TEMPERATURE  # 1.0 (Gemini 3 Pro default)

        # Generation configs (new SDK uses types.GenerateContentConfig)
        self.script_config = types.GenerateContentConfig(
            system_instruction=self.system_prompt,  # GLAZE CITY system prompt
            temperature=self.temperature,
            top_p=0.95,
            top_k=40,
            max_output_tokens=settings.GEMINI_MAX_OUTPUT_TOKENS,
        )

        self.validator_config = types.GenerateContentConfig(
            temperature=1.0,  # Gemini 3 Pro optimized (thinking model)
            top_p=0.95,
            top_k=40,
            max_output_tokens=2048,
            response_mime_type="application/json",
        )

        logger.info("ContentBrain initialized:")
        logger.info(f"  Model: {self.model_name}")
        logger.info(f"  SDK: google-genai (unified)")
        logger.info(f"  System Prompt: GLAZE CITY VIRAL ENGINE v4.1")
        logger.info(f"  Temperature: {self.temperature}")

    def _load_system_prompt(self) -> str:
        """
        Load the protected system prompt with banlist injection + channel branding.

        WARNING: This file is PROTECTED. Do not edit without user permission.
        See PROTECTED_FILES.md for details.

        Injects ban_list.txt content into {{BANLIST}} placeholder,
        then replaces {{CHANNEL_*}} placeholders with channel branding.
        """
        if not SYSTEM_PROMPT_PATH.exists():
            logger.error(f"System prompt not found: {SYSTEM_PROMPT_PATH}")
            raise FileNotFoundError(
                f"PROTECTED system prompt file not found: {SYSTEM_PROMPT_PATH}\n"
                f"This file is required for content generation."
            )

        # Load prompt with banlist injection + channel branding
        banlist_path = SYSTEM_PROMPT_PATH.parent / "ban_list.txt"
        prompt = load_prompt_with_channel(
            prompt_path=SYSTEM_PROMPT_PATH,
            channel_id=self.channel_id,
            banlist_path=banlist_path,
        )

        logger.success(f"Loaded PROTECTED system prompt: {SYSTEM_PROMPT_PATH.name}")
        logger.info(f"  Size: {len(prompt)} characters")
        logger.info(f"  Channel: {self.channel_id}")

        return prompt

    # ========================================================================
    # GLAZE CITY PROJECT GENERATION (MAIN METHOD)
    # ========================================================================

    async def generate_glaze_project(
        self,
        topic: Optional[str] = None,
        project_dir: Optional[Path] = None
    ) -> GlazeCityProject:
        """
        Generate a complete GLAZE CITY project.

        Uses the PROTECTED system prompt (GLAZE CITY VIRAL ENGINE v4.1)
        to generate full video production package including:
        - Property brief with hook strategy
        - Scene-by-scene breakdown
        - Image prompts (Nano Banana Pro)
        - Video prompts (Kling/Veo/Wan)
        - Voiceover script (ElevenLabs)
        - Background audio config
        - SFX breakdown
        - Viral metadata (title, description, hashtags, tags)
        - Viral audit scores

        Args:
            topic: Optional specific topic. If None, LLM generates original concept.
            project_dir: Optional directory to save project files.

        Returns:
            GlazeCityProject with all parsed data ready for automation.

        Example:
            >>> brain = ContentBrain()
            >>> project = await brain.generate_glaze_project()
            >>> print(project.property.property_name)
            "The Wasabi Waterfront Estate"
            >>> print(project.scenes[0].image_prompt)
            "Hyperrealistic photograph of..."
        """
        logger.info("=" * 70)
        logger.info("GENERATING GLAZE CITY PROJECT")
        logger.info("=" * 70)

        # Build command based on topic
        if topic:
            command = f'ПРОДУМАЙ НОВИЙ ТОПІК: "{topic}"'
            logger.info(f"Topic: {topic}")
        else:
            command = "ПРОДУМАЙ НОВИЙ ТОПІК"
            logger.info("Topic: Auto-generated by GLAZE-GPT")

        try:
            # Generate with Gemini using GLAZE CITY system prompt (async API)
            logger.info("Sending request to Gemini...")
            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=command,
                config=self.script_config
            )
            raw_output = response.text

            logger.success(f"Received response: {len(raw_output)} characters")

            # Parse markdown output into structured project
            parser = GlazeParser()
            project = parser.parse(raw_output)

            # Set project directory if provided
            if project_dir:
                project.project_dir = project_dir

            # Save project brief for manual reference
            if project_dir:
                await self._save_project_brief(project, project_dir)

            logger.success("=" * 70)
            logger.success(f"PROJECT GENERATED: {project.project_id}")
            logger.success(f"  Property: {project.property.name}")
            logger.success(f"  Price: {project.property.price}")
            logger.success(f"  Scenes: {len(project.scenes)}")
            logger.success(f"  Duration: {project.total_duration}s")
            logger.success("=" * 70)

            return project

        except Exception as e:
            logger.error(f"GLAZE CITY generation failed: {e}")
            raise

    async def _save_project_brief(self, project: GlazeCityProject, project_dir: Path):
        """
        Save project brief as JSON for manual reference during editing.

        Creates project_brief.json with all data needed for:
        - Voiceover recording
        - Background music selection
        - Video editing
        - YouTube upload (metadata)

        Uses utility functions from glaze_parser module.
        """
        # Save structured project brief
        save_project_brief(project, project_dir)

        # Save raw JSON output for reference
        save_raw_output(project.raw_output, project_dir)

    # ========================================================================
    # IMAGE VALIDATION
    # ========================================================================

    async def validate_image(
        self,
        image_path: Path,
        expected_prompt: str,
        scene_number: int,
        scene_description: str = "",
        scene_mood: str = "",
        key_elements: Optional[List[str]] = None
    ) -> SimpleValidationResult:
        """
        Validate generated image using Gemini Vision with full scene context

        Передає LLM повний контекст сцени для точнішої валідації:
        - Опис сцени (що має бути зображено)
        - Промпт для генерації (технічні деталі)
        - Настрій та ключові елементи

        Args:
            image_path: Path to the generated image
            expected_prompt: The original prompt used to generate the image
            scene_number: Scene number for logging
            scene_description: Опис сцени зі сценарію (контекст)
            scene_mood: Настрій/атмосфера сцени
            key_elements: Ключові елементи що мають бути присутні

        Returns:
            ValidationResult with approval status and feedback

        Example:
            >>> result = await brain.validate_image(
            ...     Path("scene_1/image.png"),
            ...     "A cozy kitchen with fresh ingredients...",
            ...     scene_number=1,
            ...     scene_description="Кухня з інгредієнтами для карбонари",
            ...     scene_mood="warm and inviting",
            ...     key_elements=["pasta", "eggs", "cheese"]
            ... )
        """
        logger.info(f"[Scene {scene_number}] Validating image: {image_path}")

        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        # ============================================================
        # PRE-CHECK: Detect duplicate frames (pixel-level, no AI cost)
        # ============================================================
        import asyncio as _asyncio

        is_duplicate = await _asyncio.to_thread(detect_duplicate_frames, image_path)
        if is_duplicate:
            logger.warning(f"[Scene {scene_number}] DUPLICATE_FRAMES detected — instant reject")
            return SimpleValidationResult(
                approved=False,
                confidence=1.0,
                feedback="Зображення містить 2+ окремих кадри (duplicate frame glitch). Потрібна перегенерація.",
                issues=["DUPLICATE_FRAMES: зображення розділене на 2+ частини горизонтальною лінією"],
                strengths=[],
                suggestions=["Перегенерувати зображення — генератор видав колаж замість одного кадру"],
                matches_prompt=False,
                quality_score=0.0,
            )

        try:
            # Load image (run in thread to avoid blocking event loop with large files)

            def _load_and_resize():
                img = Image.open(image_path)
                max_size = 2048
                orig_size = img.size
                if max(orig_size) > max_size:
                    ratio = max_size / max(orig_size)
                    new_size = tuple(int(dim * ratio) for dim in orig_size)
                    img = img.resize(new_size, Image.Resampling.LANCZOS)
                return img, orig_size

            image, original_size = await _asyncio.to_thread(_load_and_resize)
            if image.size != original_size:
                logger.debug(f"[Scene {scene_number}] Resized image from {original_size} to {image.size} (2K)")

            # Construct validation prompt with full scene context
            validation_prompt = self._build_validation_prompt(
                expected_prompt=expected_prompt,
                scene_number=scene_number,
                scene_description=scene_description,
                scene_mood=scene_mood,
                key_elements=key_elements or []
            )

            # Generate validation with Gemini Vision (async API)
            import asyncio

            response = await asyncio.wait_for(
                self.client.aio.models.generate_content(
                    model=self.model_name,
                    contents=[validation_prompt, image],
                    config=self.validator_config
                ),
                timeout=180.0  # 180 seconds for 4K image processing
            )
            response_text = response.text

            # Handle None or empty response - return rejected result instead of raising
            if not response_text:
                logger.warning(f"[Scene {scene_number}] Gemini returned empty response, returning rejected result")
                return SimpleValidationResult(
                    approved=False,
                    confidence=0.0,
                    feedback="Gemini API returned empty response - retry recommended",
                    issues=["Empty response from Gemini Vision API"],
                    strengths=[],
                    suggestions=["Retry validation - API may be overloaded"],
                    matches_prompt=False,
                    quality_score=0.0,
                )

            logger.debug(f"[Scene {scene_number}] Gemini Vision response: {len(response_text)} chars")

            # Parse JSON - extract from markdown blocks if needed
            cleaned_text = self._extract_json_from_response(response_text)

            # Try to repair truncated JSON (missing closing braces/quotes)
            cleaned_text = self._repair_truncated_json(cleaned_text)

            validation_data = json.loads(cleaned_text)

            # Fill in missing required fields with safe defaults (handles truncated responses)
            validation_data = self._fill_missing_validation_fields(validation_data, scene_number)

            # Create SimpleValidationResult object
            result = SimpleValidationResult(**validation_data)

            # Log result
            if result.approved:
                logger.success(
                    f"[Scene {scene_number}] Image APPROVED "
                    f"(confidence: {result.confidence:.2f}, quality: {result.quality_score:.1f}/10)"
                )
            else:
                logger.warning(
                    f"[Scene {scene_number}] Image REJECTED "
                    f"(confidence: {result.confidence:.2f}, issues: {len(result.issues)})"
                )
                for issue in result.issues:
                    logger.warning(f"  - {issue}")

            return result

        except Exception as e:
            logger.error(f"[Scene {scene_number}] Image validation failed: {e}")
            raise

    # ========================================================================
    # PRIVATE HELPER METHODS - Prompt Engineering
    # ========================================================================

    def _extract_json_from_response(self, response_text: str) -> str:
        """
        Extract JSON from Gemini response, handling markdown code blocks.

        Gemini often wraps JSON in ```json ... ``` blocks.
        This method extracts the pure JSON content.
        """
        import re

        text = response_text.strip()

        # Check if response is wrapped in markdown code block
        if text.startswith("```"):
            # Find the content between ``` markers
            # Pattern: ```json\n{...}\n``` or ```\n{...}\n```
            pattern = r"```(?:json)?\s*\n?(.*?)\n?```"
            match = re.search(pattern, text, re.DOTALL)
            if match:
                text = match.group(1).strip()
                logger.debug(f"Extracted JSON from markdown block, length: {len(text)}")

        return text

    def _repair_truncated_json(self, text: str) -> str:
        """
        Attempt to repair truncated JSON responses.

        Gemini sometimes returns truncated JSON due to output limits.
        This method tries to close unclosed strings and brackets.
        """
        if not text:
            return text

        # Count brackets and quotes
        open_braces = text.count('{') - text.count('}')
        open_brackets = text.count('[') - text.count(']')

        # Check for unclosed string (odd number of unescaped quotes)
        in_string = False
        escaped = False
        for char in text:
            if escaped:
                escaped = False
                continue
            if char == '\\':
                escaped = True
                continue
            if char == '"':
                in_string = not in_string

        repaired = text

        # Close unclosed string
        if in_string:
            repaired += '"'
            logger.debug("Repaired: closed unclosed string")

        # Close unclosed brackets
        if open_brackets > 0:
            repaired += ']' * open_brackets
            logger.debug(f"Repaired: added {open_brackets} closing brackets")

        # Close unclosed braces
        if open_braces > 0:
            repaired += '}' * open_braces
            logger.debug(f"Repaired: added {open_braces} closing braces")

        if repaired != text:
            logger.warning(f"JSON was truncated and repaired (added {len(repaired) - len(text)} chars)")

        return repaired

    def _fill_missing_validation_fields(self, data: dict, scene_number: int) -> dict:
        """
        Fill in missing required fields for SimpleValidationResult.

        When Gemini returns truncated JSON, some fields may be missing.
        This method adds safe defaults to prevent Pydantic validation errors.

        Strategy: If response was truncated (missing fields), assume validation failed
        because we can't trust incomplete data.
        """
        required_fields = {
            "approved": False,  # Default to not approved for safety
            "confidence": 0.0,
            "feedback": "Validation response was incomplete (truncated)",
            "issues": ["Incomplete validation response from Gemini"],
            "strengths": [],
            "suggestions": ["Retry validation"],
            "matches_prompt": False,  # Default to False for safety
            "quality_score": 0.0,
        }

        missing_fields = []
        for field, default_value in required_fields.items():
            if field not in data:
                data[field] = default_value
                missing_fields.append(field)

        if missing_fields:
            logger.warning(
                f"[Scene {scene_number}] Truncated response - filled missing fields: {missing_fields}"
            )
            # Override approval to False since response was incomplete
            data["approved"] = False
            if "Incomplete validation response" not in data.get("feedback", ""):
                data["feedback"] = f"Truncated response (missing: {', '.join(missing_fields)}). {data.get('feedback', '')}"

        return data

    def _build_validation_prompt(
        self,
        expected_prompt: str,
        scene_number: int,
        scene_description: str = "",
        scene_mood: str = "",
        key_elements: Optional[List[str]] = None
    ) -> str:
        """Build prompt for image validation with full scene context"""

        # Формуємо контекст сцени
        elements_str = ", ".join(key_elements) if key_elements else "не вказано"

        context_section = ""
        if scene_description or scene_mood or key_elements:
            context_section = f"""
## КОНТЕКСТ СЦЕНИ (ти згенерував цей сценарій раніше):
- **Опис сцени:** {scene_description or 'не вказано'}
- **Настрій/атмосфера:** {scene_mood or 'не вказано'}
- **Ключові елементи що МАЮТЬ бути присутні:** {elements_str}
"""

        return f"""Ти експерт з валідації зображень для відео-контенту.
{context_section}
## ПРОМПТ ДЛЯ ГЕНЕРАЦІЇ:
{expected_prompt}

## ТВОЄ ЗАВДАННЯ:
Проаналізуй зображення (Scene {scene_number}) та визнач чи воно відповідає сценарію.

## КРИТЕРІЇ ОЦІНКИ:
1. **Відповідність промпту:** Чи зображення показує те, що було запитано?
2. **Ключові елементи:** Чи присутні всі обов'язкові елементи?
3. **Настрій:** Чи передає зображення правильну атмосферу?
4. **Якість:** Чи зображення професійне, без артефактів?
5. **Композиція:** Чи добре скомпоноване для відео?

## КРИТИЧНІ ДЕФЕКТИ (INSTANT REJECT — approved: false):
- **DUPLICATE_FRAMES:** Зображення містить 2+ окремих картинки склеєних вертикально або горизонтально. Видно лінію-розділювач. Це глюк генератора — ЗАВЖДИ відхиляй!
- **WRONG_ORIENTATION:** Зображення повернуте на 90° (горизонтальне замість вертикального 9:16)

## ФОРМАТ ВІДПОВІДІ (тільки JSON):
{{
  "approved": true/false (схвалити якщо quality >= 7 І всі ключові елементи присутні),
  "confidence": 0.0-1.0,
  "feedback": "Загальна оцінка українською",
  "issues": ["проблема1", "проблема2"] (пустий список якщо немає),
  "strengths": ["сильна сторона1", "сильна сторона2"],
  "suggestions": ["як покращити"] (пустий якщо схвалено),
  "matches_prompt": true/false,
  "quality_score": 0.0-10.0
}}

ВАЖЛИВО: Будь критичним але справедливим. Відхиляй тільки якщо є суттєві проблеми.
Повертай ТІЛЬКИ JSON без додаткового тексту."""


# ============================================================================
# EXPORT
# ============================================================================

__all__ = ["ContentBrain"]
