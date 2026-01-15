"""
Content Brain - AI-powered script generation and image validation

Uses Google Gemini API for:
1. Script generation from topic/idea (with GLAZE CITY system prompt)
2. Scene breakdown with detailed prompts
3. Image validation with Gemini Vision

Provider: Google Gemini (gemini-3-pro-preview)
SDK: google-genai (new unified SDK)

PROTECTED FILE WARNING:
The system prompt file (config/GEN1.txt) is PROTECTED.
DO NOT EDIT that file without explicit user permission.
See PROTECTED_FILES.md for details.
"""

import json
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

# =============================================================================
# PROTECTED SYSTEM PROMPT - DO NOT EDIT THE SOURCE FILE
# =============================================================================
SYSTEM_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "GEN1.txt"


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

    def __init__(self):
        """Initialize Content Brain with Gemini API and GLAZE CITY system prompt"""

        # Initialize Gemini Client (new unified SDK)
        self.client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY)

        # =================================================================
        # LOAD PROTECTED SYSTEM PROMPT (READ-ONLY)
        # =================================================================
        self.system_prompt = self._load_system_prompt()

        # Models - використовуємо одну модель для всього (Gemini 3 Pro Preview)
        self.model_name = settings.CONTENTBRAIN_MODEL  # gemini-3-pro-preview
        self.temperature = settings.GEMINI_TEMPERATURE  # 0.3

        # Generation configs (new SDK uses types.GenerateContentConfig)
        self.script_config = types.GenerateContentConfig(
            system_instruction=self.system_prompt,  # GLAZE CITY system prompt
            temperature=self.temperature,
            top_p=0.95,
            top_k=40,
            max_output_tokens=8192,
        )

        self.validator_config = types.GenerateContentConfig(
            temperature=0.2,  # Lower for validation (more deterministic)
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
        Load the protected GLAZE CITY system prompt.

        WARNING: This file is PROTECTED. Do not edit without user permission.
        See PROTECTED_FILES.md for details.
        """
        if not SYSTEM_PROMPT_PATH.exists():
            logger.error(f"System prompt not found: {SYSTEM_PROMPT_PATH}")
            raise FileNotFoundError(
                f"PROTECTED system prompt file not found: {SYSTEM_PROMPT_PATH}\n"
                f"This file is required for content generation."
            )

        with open(SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as f:
            prompt = f.read()

        logger.success(f"Loaded PROTECTED system prompt: {SYSTEM_PROMPT_PATH.name}")
        logger.info(f"  Size: {len(prompt)} characters")

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
            # Generate with Gemini using GLAZE CITY system prompt
            logger.info("Sending request to Gemini...")
            response = self.client.models.generate_content(
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

        try:
            # Load image
            image = Image.open(image_path)

            # Resize to max 2K (2048px on longest side) to save tokens and speed up processing
            max_size = 2048
            if max(image.size) > max_size:
                # Calculate new size maintaining aspect ratio
                ratio = max_size / max(image.size)
                new_size = tuple(int(dim * ratio) for dim in image.size)
                image = image.resize(new_size, Image.Resampling.LANCZOS)
                logger.debug(f"[Scene {scene_number}] Resized image from {Image.open(image_path).size} to {new_size} (2K)")

            # Construct validation prompt with full scene context
            validation_prompt = self._build_validation_prompt(
                expected_prompt=expected_prompt,
                scene_number=scene_number,
                scene_description=scene_description,
                scene_mood=scene_mood,
                key_elements=key_elements or []
            )

            # Generate validation with Gemini Vision
            # Use longer timeout for 4K images (180 seconds instead of default 30)
            # Wrap in try-except to handle timeout more gracefully
            import asyncio
            from concurrent.futures import ThreadPoolExecutor

            async def _generate_with_timeout():
                """Wrapper to add custom timeout to sync generate_content call"""
                loop = asyncio.get_event_loop()
                with ThreadPoolExecutor() as executor:
                    response = await asyncio.wait_for(
                        loop.run_in_executor(
                            executor,
                            lambda: self.client.models.generate_content(
                                model=self.model_name,
                                contents=[validation_prompt, image],
                                config=self.validator_config
                            )
                        ),
                        timeout=180.0  # 180 seconds for 4K image processing
                    )
                return response

            response = await _generate_with_timeout()
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
