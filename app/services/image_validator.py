"""
Image Validator - VAL_IMG v3.0 Implementation

Validates AI-generated images for Glaze City video production pipeline.
Uses Google Gemini Vision API with the VAL_IMG system prompt.

SDK: google-genai (new unified SDK)

v3.0 Features:
- Glitch Detection (morphing, artifacts, anatomical errors)
- Quality Scoring (8 criteria, 0-10 each)
- Safe Zone Compliance (subject in upper 60% for 9:16 vertical)
- Gigantism Protocol (buildings look massive, not toy-like)
- Food DNA Validation (textures matching architectural elements)
- First-Frame Composition (Scene 1 hook-ready)

Workflow:
1. Receive 4 generated images for a scene
2. Send to Gemini with validation prompt and context
3. Parse JSON response with scoring and decision
4. Return best image or VALIDATION_FAILED with retry prompts

PROTECTED FILE WARNING:
The validation prompt file (config/VAL_IMG.txt) is PROTECTED.
DO NOT EDIT that file without explicit user permission.
See PROTECTED_FILES.md for details.
"""

import json
import re
import base64
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

from google import genai
from google.genai import types
from PIL import Image

from app.core.config import settings
from app.utils.logger import logger
from app.services.validation_models import ValidationResponse, RetryPrompts


# =============================================================================
# PROTECTED VALIDATION PROMPT - DO NOT EDIT THE SOURCE FILE
# =============================================================================
VALIDATION_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "VAL_IMG.txt"


class ImageValidator:
    """
    VAL_IMG v3.0 - Image Validation for Glaze City Pipeline

    Validates AI-generated images using a 3-phase process:
    1. Glitch Detection - instant reject for AI artifacts
    2. Quality Scoring - 8 criteria, 0-10 each
    3. Selection - best image or VALIDATION_FAILED

    v3.0 Additional Checks:
    - Safe Zone Compliance (vertical 9:16, subject in upper 60%)
    - Gigantism Protocol (massive buildings, anti-toy effect)
    - Food DNA (textures matching architectural elements)
    - First-Frame Composition (Scene 1 hook-ready)

    Uses Google Gemini Vision API with structured JSON output.
    """

    def __init__(self):
        """Initialize Image Validator with Gemini Vision API"""

        # Initialize Gemini Client (new unified SDK)
        self.client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY)

        # Load PROTECTED validation prompt (READ-ONLY)
        self.validation_prompt = self._load_validation_prompt()

        # Model configuration
        self.model_name = settings.CONTENTBRAIN_MODEL  # gemini-3-pro
        self.max_retries = 2

        # Validation config (new SDK uses types.GenerateContentConfig)
        self.validation_config = types.GenerateContentConfig(
            system_instruction=self.validation_prompt,  # VAL_IMG system prompt
            temperature=0.2,  # Low for consistent validation
            top_p=0.95,
            top_k=40,
            max_output_tokens=4096,
            response_mime_type="application/json",
        )

        logger.info("ImageValidator initialized:")
        logger.info(f"  Model: {self.model_name}")
        logger.info(f"  SDK: google-genai (unified)")
        logger.info(f"  System Prompt: VAL_IMG v3.0")

    def _load_validation_prompt(self) -> str:
        """
        Load the PROTECTED validation prompt

        This file is READ-ONLY. Do not modify without user permission.
        See PROTECTED_FILES.md for details.
        """
        if not VALIDATION_PROMPT_PATH.exists():
            raise FileNotFoundError(
                f"PROTECTED validation prompt not found: {VALIDATION_PROMPT_PATH}\n"
                "This file is required for image validation."
            )

        prompt = VALIDATION_PROMPT_PATH.read_text(encoding="utf-8")
        logger.debug(f"Loaded validation prompt ({len(prompt)} chars)")
        return prompt

    async def validate_images(
        self,
        image_paths: List[Path],
        scene_context: Dict[str, Any],
        project_id: str = "unknown"
    ) -> ValidationResponse:
        """
        Validate a batch of generated images

        Args:
            image_paths: List of 4 image paths to validate
            scene_context: Context including:
                - scene_number: int
                - scene_name: str
                - image_prompt: str (original prompt used)
                - easter_egg: dict or None (if this scene has easter egg)
            project_id: Project identifier for logging

        Returns:
            ValidationResponse with decision and scores

        Raises:
            Exception: If validation fails after retries
        """
        scene_num = scene_context.get("scene_number", 0)
        logger.info(f"[Scene {scene_num}] Starting image validation ({len(image_paths)} images)")

        # Build validation request
        validation_request = self._build_validation_request(image_paths, scene_context)

        # Send to Gemini
        for attempt in range(1, self.max_retries + 1):
            try:
                response = await self._call_gemini(validation_request, image_paths)
                result = self._parse_response(response, scene_context)

                # Log result
                if result.passed:
                    logger.success(
                        f"[Scene {scene_num}] Validation PASSED: {result.selected_image_id} "
                        f"({result.phase3_decision.selected_percentage}%)"
                    )
                else:
                    logger.warning(
                        f"[Scene {scene_num}] Validation FAILED: {result.phase3_decision.reasoning}"
                    )

                return result

            except Exception as e:
                logger.error(f"[Scene {scene_num}] Validation attempt {attempt} failed: {e}")
                if attempt == self.max_retries:
                    raise
                logger.info(f"Retrying validation (attempt {attempt + 1}/{self.max_retries})...")

    def _build_validation_request(
        self,
        image_paths: List[Path],
        scene_context: Dict[str, Any]
    ) -> str:
        """Build the text part of the validation request (v3.0 format)"""

        scene_num = scene_context.get("scene_number", 0)
        scene_name = scene_context.get("scene_name", "Unknown")
        image_prompt = scene_context.get("image_prompt", "No prompt provided")
        easter_egg = scene_context.get("easter_egg")

        # v3.0 extended context
        food_dna = scene_context.get("food_dna")
        architectural_identity = scene_context.get("architectural_identity")
        is_first_scene = scene_num == 1

        # Build context message
        context_parts = [
            f"## Validation Request (VAL_IMG v3.0)",
            f"",
            f"**Scene:** {scene_num} - {scene_name}",
            f"**Images Received:** {len(image_paths)}",
            f"**Timestamp:** {datetime.utcnow().isoformat()}Z",
            f"**First Scene (Hook):** {'YES' if is_first_scene else 'NO'}",
            f"",
            f"### Original Prompt",
            f"```",
            f"{image_prompt}",
            f"```",
        ]

        # v3.0: Add Safe Zone requirement
        context_parts.extend([
            f"",
            f"### Safe Zone Compliance (v3.0)",
            f"- Format: 9:16 vertical",
            f"- Subject must be in upper 60% of frame",
            f"- Bottom 20% reserved for potential UI overlays",
        ])

        # v3.0: Add Gigantism Protocol
        context_parts.extend([
            f"",
            f"### Gigantism Protocol (v3.0)",
            f"- Buildings must appear MASSIVE, not toy-like",
            f"- Look for: proper scale references, dramatic perspective",
            f"- Reject: miniature/doll-house appearance, flat perspective",
        ])

        # v3.0: Add Food DNA context if available
        if food_dna:
            context_parts.extend([
                f"",
                f"### Food DNA Validation (v3.0)",
                f"- Walls texture: {food_dna.get('walls_become', 'N/A')}",
                f"- Roof texture: {food_dna.get('roof_becomes', 'N/A')}",
                f"- Windows texture: {food_dna.get('windows_become', 'N/A')}",
                f"- Food textures must be clearly visible and consistent",
            ])

        # v3.0: Add Architectural Identity if available
        if architectural_identity:
            context_parts.extend([
                f"",
                f"### Architectural Identity (v3.0)",
                f"- Style: {architectural_identity.get('style_description', 'N/A')}",
                f"- Stories: {architectural_identity.get('stories', 'N/A')}",
                f"- Features: {', '.join(architectural_identity.get('distinctive_features', []))}",
            ])

        # v3.0: First-Frame Composition for Scene 1
        if is_first_scene:
            context_parts.extend([
                f"",
                f"### First-Frame Composition (Hook Scene)",
                f"- Must be visually striking for 0.3s hook",
                f"- High contrast, clear subject, immediate impact",
                f"- Consider scroll-stopping power",
            ])

        # Add Easter Egg context if applicable
        if easter_egg:
            context_parts.extend([
                f"",
                f"### Easter Egg Required",
                f"- **Object:** {easter_egg.get('object', 'Unknown')}",
                f"- **Placement:** {easter_egg.get('placement', 'Unknown')}",
                f"- **Safe Zone Position:** {easter_egg.get('safe_zone_position', 'top_left')}",
                f"- **Scene Number:** {easter_egg.get('scene_number', scene_num)}",
            ])
        else:
            context_parts.extend([
                f"",
                f"### Easter Egg",
                f"Not required for this scene (score as N/A)",
            ])

        context_parts.extend([
            f"",
            f"---",
            f"",
            f"Please validate the {len(image_paths)} images provided and return your JSON decision.",
            f"Apply all v3.0 criteria: Safe Zone, Gigantism, Food DNA consistency.",
        ])

        return "\n".join(context_parts)

    async def _call_gemini(
        self,
        validation_request: str,
        image_paths: List[Path]
    ) -> str:
        """Call Gemini Vision API with images and validation request"""

        # Prepare content parts: images first, then text
        # New google.genai SDK requires bytes, not PIL objects
        content_parts = []

        # Add each image as bytes
        for i, path in enumerate(image_paths, 1):
            if not path.exists():
                logger.warning(f"Image not found: {path}")
                continue

            try:
                # Read image as bytes for new SDK
                image_bytes = path.read_bytes()

                # Determine mime type
                suffix = path.suffix.lower()
                mime_types = {
                    '.png': 'image/png',
                    '.jpg': 'image/jpeg',
                    '.jpeg': 'image/jpeg',
                    '.webp': 'image/webp',
                    '.gif': 'image/gif',
                }
                mime_type = mime_types.get(suffix, 'image/png')

                # Create Part object for new SDK
                image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
                content_parts.append(image_part)
                logger.debug(f"Added IMG_{i}: {path.name} ({len(image_bytes)/1024:.1f} KB)")
            except Exception as e:
                logger.error(f"Failed to load image {path}: {e}")

        if len(content_parts) < 1:
            raise Exception(f"No valid images to validate")

        if len(content_parts) < 4:
            logger.warning(f"Only {len(content_parts)} image(s) provided. Recommend 4 for best selection.")

        # Add the validation request text
        content_parts.append(validation_request)

        # Call Gemini with new SDK (async)
        logger.debug(f"Calling Gemini Vision API with {len(content_parts)-1} images...")
        response = await self.client.aio.models.generate_content(
            model=self.model_name,
            contents=content_parts,
            config=self.validation_config
        )

        # Handle response - check for None
        if response is None:
            raise Exception("Gemini returned empty response")

        if response.text is None:
            # Try to get text from candidates
            if hasattr(response, 'candidates') and response.candidates:
                for candidate in response.candidates:
                    if hasattr(candidate, 'content') and candidate.content:
                        if hasattr(candidate.content, 'parts') and candidate.content.parts:
                            for part in candidate.content.parts:
                                if hasattr(part, 'text') and part.text:
                                    return part.text
            raise Exception("Gemini response has no text content")

        return response.text

    def _parse_response(
        self,
        response_text: str,
        scene_context: Dict[str, Any]
    ) -> ValidationResponse:
        """Parse Gemini response into ValidationResponse model"""

        # Extract JSON from response
        json_str = self._extract_json(response_text)
        if not json_str:
            raise Exception(f"No valid JSON in response: {response_text[:500]}")

        try:
            data = json.loads(json_str)
            result = ValidationResponse.model_validate(data)

            # Log detailed evaluation results for ALL candidates
            self._log_all_candidates_evaluation(result)

            return result
        except json.JSONDecodeError as e:
            raise Exception(f"Invalid JSON: {e}\nResponse: {json_str[:500]}")
        except Exception as e:
            raise Exception(f"Failed to parse validation response: {e}")

    def _log_all_candidates_evaluation(self, result: ValidationResponse) -> None:
        """Log evaluation results for ALL candidates to prove they were all checked"""

        logger.info("=" * 60)
        logger.info("VAL_IMG v3.0 - ALL CANDIDATES EVALUATION")
        logger.info("=" * 60)

        # Phase 1: Glitch Detection
        logger.info(f"Phase 1 (Glitch Detection): {result.phase1_glitch_detection.summary}")
        for glitch_result in result.phase1_glitch_detection.results:
            status_icon = "PASS" if glitch_result.status == "PASS" else "REJECT"
            glitch_info = f" ({', '.join(glitch_result.glitches)})" if glitch_result.glitches else ""
            logger.info(f"  {glitch_result.image}: [{status_icon}]{glitch_info}")

        # Phase 2: Quality Scoring
        logger.info("-" * 60)
        logger.info("Phase 2 (Quality Scoring):")
        scored_images = result.phase2_quality_scoring.scored_images
        logger.info(f"  Images scored: {', '.join(scored_images)}")

        for img_id, scores in result.phase2_quality_scoring.scores.items():
            logger.info(f"  {img_id}: {scores.total}/{scores.max_possible} ({scores.percentage}%) Grade: {scores.grade}")

        # Phase 3: Decision
        logger.info("-" * 60)
        decision = result.phase3_decision
        logger.info(f"Phase 3 (Decision): {decision.validation_status}")
        logger.info(f"  Selected: {decision.selected_image}")
        if decision.selected_percentage:
            logger.info(f"  Score: {decision.selected_score}/{decision.selected_max} ({decision.selected_percentage}%)")
        logger.info(f"  Reasoning: {decision.reasoning}")
        logger.info("=" * 60)

    def _extract_json(self, text: str) -> Optional[str]:
        """Extract JSON from response (handles ```json blocks)"""

        # Method 1: Try to find ```json code block
        json_block_pattern = r"```json\s*([\s\S]*?)```"
        match = re.search(json_block_pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()

        # Method 2: Try to find raw JSON object
        if text.strip().startswith("{"):
            return text.strip()

        # Method 3: Find first { and last }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return text[start:end + 1]

        return None

    def get_retry_prompt(
        self,
        validation_result: ValidationResponse,
        original_prompt: str
    ) -> Optional[str]:
        """
        Generate a retry prompt for failed validation

        Args:
            validation_result: Failed validation result
            original_prompt: Original image generation prompt

        Returns:
            Modified prompt for retry, or None if validation passed
        """
        if validation_result.passed:
            return None

        retry = validation_result.retry_prompts
        if not retry:
            # Generate basic retry prompt
            return f"{original_prompt}, high quality, no artifacts, sharp details"

        return retry.full_retry_prompt


# =============================================================================
# EXPORT
# =============================================================================

__all__ = ["ImageValidator"]
