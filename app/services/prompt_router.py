"""
Prompt Router - Delivery Module for GEN1 -> GEN2 v2.1

This module handles the data flow between two prompt generation stages:
- GEN1: Generates script, concept, voiceover, audio, architectural/food identity
- GEN2: Generates visual prompts (image_prompt, video_prompt, reference_type)

Flow:
1. GEN1 generates project concept (ALWAYS 6 scenes)
2. PromptRouter validates and transforms GEN1 output
3. PromptRouter creates delivery payload for GEN2
4. GEN2 generates visual prompts
5. PromptRouter merges results into final GlazeCityProject
"""

import json
import re
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

from google import genai
from google.genai import types

from app.core.config import settings
from app.utils.logger import logger
from app.services.gen_models import (
    # Contract Constants
    REQUIRED_GEN1_FIELDS,
    REQUIRED_SCENE_FIELDS,
    REQUIRED_HANDOFF_FIELDS,
    VALID_HOOK_TYPES,
    VALID_NARRATIVE_PURPOSES,
    VALID_ENERGY_LEVELS,
    # GEN1 Models
    Gen1Output,
    Gen1Metadata,
    Gen1Concept,
    Gen1Property,
    Gen1Hook,
    Gen1ArchitecturalIdentity,
    Gen1FoodDNA,
    Gen1FoodIdentity,
    Gen1LightingMaster,
    Gen1ForegroundElement,
    Gen1EasterEgg,
    Gen1VisualConcept,
    Gen1CameraIntent,
    Gen1SceneConcept,
    Gen1VoiceoverConfig,
    Gen1SonicHook,
    Gen1FoleyPalette,
    Gen1SfxItem,
    Gen1SfxScene,
    Gen1AudioConfig,
    Gen1ShareTrigger,
    Gen1Engagement,
    # GEN2 Models
    Gen2SceneInput,
    Gen2SceneOutput,
    Gen2BatchOutput,
    Gen2VisualSummary,
    Gen2FirstFrameComposition,
    Gen2PostProductionNotes,
    # Delivery
    DeliveryPayload,
    # Enums
    ReferenceType,
    VideoTool,
)
from app.services.glaze_models import (
    GlazeCityProject,
    GlazeScene,
    PropertyBrief,
    HookStrategy,
    Psychology,
    EasterEgg,
    LoopConfig,
    VoiceoverConfig,
    VoiceoverSettings,
    AudioConfig,
    BackgroundMusic,
    SFXItem,
    ViralMetadata,
    ViralAudit,
    SeriesInfo,
    ProjectMeta,
    # Required by GEN1 OUTPUT CONTRACT
    ArchitecturalIdentity,
    FoodIdentity,
    FoodDNA,
    LightingMaster,
)
from app.services.validation_models import (
    Gen1ValidationResponse,
    Gen2ValidationResponse,
)
from app.services.topic_memory import topic_memory


# Paths to system prompts
CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
GEN1_PROMPT_PATH = CONFIG_DIR / "GEN1.txt"
GEN2_PROMPT_PATH = CONFIG_DIR / "GEN2.txt"
VAL_GEN1_PROMPT_PATH = CONFIG_DIR / "VAL_GEN1.txt"
VAL_GEN2_PROMPT_PATH = CONFIG_DIR / "VAL_GEN2.txt"

# Debug directory for raw responses
DEBUG_DIR = Path(__file__).parent.parent.parent / "debug" / "gen_responses"

# Validation constants
MAX_VALIDATION_RETRIES = 3  # Max retries for GEN1/GEN2 validation


class PromptRouter:
    """
    Routes prompts between GEN1 and GEN2 stages.

    Responsibilities:
    - Load and manage system prompts (GEN1, GEN2)
    - Validate outputs at each stage
    - Transform data between stages
    - Merge final results
    - Save raw responses for debugging
    """

    def __init__(self):
        """Initialize the prompt router."""
        self.gen1_prompt: Optional[str] = None
        self.gen2_prompt: Optional[str] = None
        self.val_gen1_prompt: Optional[str] = None
        self.val_gen2_prompt: Optional[str] = None

        # Initialize Gemini client
        self.client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY)
        self.model = settings.CONTENTBRAIN_MODEL  # Should be gemini-2.5-pro or similar

        # Ensure debug directory exists
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)

        # Load prompts
        self._load_prompts()

        logger.info("PromptRouter initialized")
        logger.info(f"  Model: {self.model}")
        logger.info(f"  GEN1 prompt: {'Loaded' if self.gen1_prompt else 'NOT FOUND'}")
        logger.info(f"  GEN2 prompt: {'Loaded' if self.gen2_prompt else 'NOT FOUND'}")
        logger.info(f"  VAL_GEN1 prompt: {'Loaded' if self.val_gen1_prompt else 'NOT FOUND'}")
        logger.info(f"  VAL_GEN2 prompt: {'Loaded' if self.val_gen2_prompt else 'NOT FOUND'}")

    def _load_prompts(self) -> None:
        """Load GEN1, GEN2, VAL_GEN1, and VAL_GEN2 system prompts."""
        # Load GEN1
        if GEN1_PROMPT_PATH.exists():
            with open(GEN1_PROMPT_PATH, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    self.gen1_prompt = content
                    logger.success(f"Loaded GEN1 prompt: {len(self.gen1_prompt)} chars")
                else:
                    logger.warning(f"GEN1 prompt file is empty: {GEN1_PROMPT_PATH}")
        else:
            logger.warning(f"GEN1 prompt not found: {GEN1_PROMPT_PATH}")

        # Load GEN2
        if GEN2_PROMPT_PATH.exists():
            with open(GEN2_PROMPT_PATH, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    self.gen2_prompt = content
                    logger.success(f"Loaded GEN2 prompt: {len(self.gen2_prompt)} chars")
                else:
                    logger.warning(f"GEN2 prompt file is empty: {GEN2_PROMPT_PATH}")
        else:
            logger.warning(f"GEN2 prompt not found: {GEN2_PROMPT_PATH}")

        # Load VAL_GEN1
        if VAL_GEN1_PROMPT_PATH.exists():
            with open(VAL_GEN1_PROMPT_PATH, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    self.val_gen1_prompt = content
                    logger.success(f"Loaded VAL_GEN1 prompt: {len(self.val_gen1_prompt)} chars")
                else:
                    logger.warning(f"VAL_GEN1 prompt file is empty: {VAL_GEN1_PROMPT_PATH}")
        else:
            logger.warning(f"VAL_GEN1 prompt not found: {VAL_GEN1_PROMPT_PATH}")

        # Load VAL_GEN2
        if VAL_GEN2_PROMPT_PATH.exists():
            with open(VAL_GEN2_PROMPT_PATH, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    self.val_gen2_prompt = content
                    logger.success(f"Loaded VAL_GEN2 prompt: {len(self.val_gen2_prompt)} chars")
                else:
                    logger.warning(f"VAL_GEN2 prompt file is empty: {VAL_GEN2_PROMPT_PATH}")
        else:
            logger.warning(f"VAL_GEN2 prompt not found: {VAL_GEN2_PROMPT_PATH}")

    def reload_prompts(self) -> None:
        """Reload prompts from disk (hot reload support)."""
        self._load_prompts()
        logger.info("Prompts reloaded")

    def _save_raw_response(
        self,
        response_text: str,
        gen_type: str,
        project_id: str = "unknown"
    ) -> Path:
        """
        Save raw Gemini response for debugging.

        Args:
            response_text: Raw response text from Gemini
            gen_type: Type of generation (GEN1 or GEN2)
            project_id: Project ID for filename

        Returns:
            Path to saved file
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Sanitize project_id for filename
        safe_project_id = re.sub(r'[^\w\-]', '_', project_id)[:30]
        filename = f"{gen_type}_{safe_project_id}_{timestamp}.txt"
        filepath = DEBUG_DIR / filename

        try:
            filepath.write_text(response_text, encoding="utf-8")
            logger.info(f"[{gen_type}] Raw response saved: {filename}")
        except Exception as e:
            logger.warning(f"Failed to save raw response: {e}")

        return filepath

    # =========================================================================
    # STAGE 1: GEN1 - Script & Concept Generation
    # =========================================================================

    async def run_gen1(
        self,
        topic: Optional[str] = None,
        num_scenes: int = 6,  # ALWAYS 6
        style: str = "cinematic food fantasy",
        target_audience: str = "YouTube Shorts viewers",
        duration_seconds: int = 10,
        project_id: str = "",
    ) -> Optional[Gen1Output]:
        """
        Run GEN1 to generate script and concept.

        Args:
            topic: The topic/theme for the video. If None, AI will auto-generate.
            num_scenes: Number of scenes (ALWAYS 6, enforced)
            style: Visual style
            target_audience: Target audience
            duration_seconds: Total video duration in seconds
            project_id: Optional project ID for debugging

        Returns:
            Gen1Output with script, concepts, voiceover, audio config
        """
        if not self.gen1_prompt:
            logger.error("GEN1 prompt not loaded!")
            return None

        # ENFORCE 6 SCENES
        num_scenes = 6
        logger.info(f"[GEN1] Enforcing {num_scenes} scenes (per contract)")

        is_auto_mode = topic is None or topic == "__AUTO_GENERATE__"

        if is_auto_mode:
            logger.info(f"[GEN1] AUTO MODE - AI will generate topic")
        else:
            logger.info(f"[GEN1] IDEA MODE - Using hint: {topic}")
        logger.info(f"  Scenes: {num_scenes}, Duration: {duration_seconds}s, Style: {style}")

        # Build user prompt
        user_prompt = self._build_gen1_user_prompt(
            topic=topic,
            num_scenes=num_scenes,
            style=style,
            target_audience=target_audience,
            duration_seconds=duration_seconds,
            auto_mode=is_auto_mode,
        )

        try:
            # Call Gemini with GEN1 system prompt
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=self.gen1_prompt,
                    temperature=0.7,  # Creative for concept generation
                    max_output_tokens=16384,  # Larger output for full contract
                ),
            )

            # Extract JSON from response
            raw_output = response.text
            if not raw_output:
                logger.error("[GEN1] Empty response from API")
                return None

            # Save raw response for debugging
            self._save_raw_response(raw_output, "GEN1", project_id)

            json_data = self._extract_json(raw_output)

            if not json_data:
                logger.error("[GEN1] Failed to extract JSON from response")
                logger.error(f"[GEN1] Raw output (first 2000 chars): {raw_output[:2000]}")
                return None

            # Log JSON structure for debugging
            logger.info(f"[GEN1] JSON keys: {list(json_data.keys())}")

            # Check critical fields before parsing
            if 'metadata' in json_data:
                logger.info(f"[GEN1] metadata.title: {json_data.get('metadata', {}).get('title', 'MISSING')}")
            if 'scenes' in json_data:
                logger.info(f"[GEN1] scenes count: {len(json_data.get('scenes', []))}")
            if 'youtube' in json_data:
                logger.info(f"[GEN1] youtube object: PRESENT")
            else:
                logger.warning(f"[GEN1] youtube object: MISSING (will use defaults)")
            if 'viral_assessment' in json_data:
                logger.info(f"[GEN1] viral_assessment: PRESENT")
            else:
                logger.warning(f"[GEN1] viral_assessment: MISSING (will use defaults)")

            # Parse into Gen1Output model
            try:
                gen1_output = Gen1Output.model_validate(json_data)
            except Exception as parse_error:
                logger.error(f"[GEN1] Model validation failed: {parse_error}")
                logger.error(f"[GEN1] JSON data: {json.dumps(json_data, indent=2, ensure_ascii=False)[:3000]}")
                raise

            logger.success(f"[GEN1] Generated: {gen1_output.metadata.title}")
            logger.info(f"  Concept: {gen1_output.metadata.concept.subject}")
            logger.info(f"  Scenes: {len(gen1_output.scenes)}")
            logger.info(f"  Food: {gen1_output.food_identity.primary_food}")
            logger.info(f"  Architecture: {gen1_output.architectural_identity.style_code}")
            logger.info(f"  YouTube title: {gen1_output.youtube_title}")
            logger.info(f"  Viral score: {gen1_output.viral_assessment.overall_score if gen1_output.viral_assessment else 'N/A'}")

            return gen1_output

        except Exception as e:
            logger.error(f"[GEN1] Error: {e}")
            import traceback
            logger.error(f"[GEN1] Full traceback:\n{traceback.format_exc()}")
            return None

    def _build_gen1_user_prompt(
        self,
        topic: Optional[str],
        num_scenes: int,
        style: str,
        target_audience: str,
        duration_seconds: int = 10,
        auto_mode: bool = False,
    ) -> str:
        """
        Build user prompt for GEN1.

        Args:
            topic: User-provided topic or hint. None for auto mode.
            num_scenes: Number of scenes (ALWAYS 6)
            style: Visual style
            target_audience: Target audience
            duration_seconds: Total video duration
            auto_mode: If True, AI generates topic automatically
        """
        # Get blacklist from topic memory
        blacklist = topic_memory.generate_blacklist_markdown()
        blacklist_section = f"""
{blacklist}

⚠️ IMPORTANT: You MUST avoid ALL subjects and foods listed above!
Using any blocked subject or food will result in IMMEDIATE REJECTION.

---

""" if topic_memory.topics else ""

        if auto_mode:
            # AUTO MODE: AI generates topic
            return f"""{blacklist_section}NEW TOPIC

Generate a completely new, UNIQUE and VIRAL video concept.

MODE: AUTO - Create an original topic yourself!

CONSTRAINTS:
- NUMBER OF SCENES: {num_scenes} (EXACTLY 6 scenes, no more, no less!)
- TOTAL DURATION: {duration_seconds} seconds
- VISUAL STYLE: {style}
- TARGET AUDIENCE: {target_audience}

CRITICAL REQUIREMENTS:
1. Follow the OUTPUT CONTRACT FOR GEN2 EXACTLY
2. Include ALL mandatory fields:
   - metadata (with concept object)
   - property
   - hook
   - architectural_identity (with style_code, style_description, distinctive_features, silhouette_description, interior_style)
   - food_identity (with primary_food, food_dna mapping ALL elements, texture_keywords, color_keywords, atmosphere)
   - lighting_master (with preset, mood_reason, prompt_snippet)
   - foreground_element (with type, prompt_snippet)
   - scenes (EXACTLY 6 scenes with visual_concept and camera_intent)
   - voiceover (with full_script)
   - audio (with sonic_hook, suno_prompt, foley_palette, sfx_per_scene)
   - engagement (with easter_egg, share_trigger, hashtags)
3. Each scene MUST have:
   - scene_number (1-6)
   - scene_name
   - duration_seconds
   - narrative_purpose
   - reference_hint (PRIMARY for scene 1, REQUIRES_REF/INDEPENDENT for others)
   - energy_level
   - visual_concept (with subject, environment, mood, key_elements, lighting_note, motion_elements)
   - camera_intent (with movement, combo, framing, special)
   - voiceover_segment
   - audio_moment

Output ONLY valid JSON. Start with {{ and end with }}"""
        else:
            # IDEA MODE: User provided hint/topic
            return f"""{blacklist_section}TOPIC: {topic}

Develop this idea into a complete video concept for "Glaze City" style channel.

CONSTRAINTS:
- NUMBER OF SCENES: {num_scenes} (EXACTLY 6 scenes, no more, no less!)
- TOTAL DURATION: {duration_seconds} seconds
- VISUAL STYLE: {style}
- TARGET AUDIENCE: {target_audience}

CRITICAL REQUIREMENTS:
1. Follow the OUTPUT CONTRACT FOR GEN2 EXACTLY
2. Include ALL mandatory fields:
   - metadata (with concept object)
   - property
   - hook
   - architectural_identity (with style_code, style_description, distinctive_features, silhouette_description, interior_style)
   - food_identity (with primary_food, food_dna mapping ALL elements, texture_keywords, color_keywords, atmosphere)
   - lighting_master (with preset, mood_reason, prompt_snippet)
   - foreground_element (with type, prompt_snippet)
   - scenes (EXACTLY 6 scenes with visual_concept and camera_intent)
   - voiceover (with full_script)
   - audio (with sonic_hook, suno_prompt, foley_palette, sfx_per_scene)
   - engagement (with easter_egg, share_trigger, hashtags)
3. Each scene MUST have:
   - scene_number (1-6)
   - scene_name
   - duration_seconds
   - narrative_purpose
   - reference_hint (PRIMARY for scene 1, REQUIRES_REF/INDEPENDENT for others)
   - energy_level
   - visual_concept (with subject, environment, mood, key_elements, lighting_note, motion_elements)
   - camera_intent (with movement, combo, framing, special)
   - voiceover_segment
   - audio_moment

Output ONLY valid JSON. Start with {{ and end with }}"""

    # =========================================================================
    # DELIVERY: GEN1 -> GEN2
    # =========================================================================

    def create_delivery_payload(
        self,
        gen1_output: Gen1Output,
        project_id: str = "",
    ) -> DeliveryPayload:
        """
        Create delivery payload from GEN1 output for GEN2.

        This is the contract between the two stages.
        Includes all new fields required by GEN2.
        """
        payload = DeliveryPayload.from_gen1_output(gen1_output, project_id)

        logger.info(f"[Delivery] Created payload for {len(payload.scenes)} scenes")
        logger.info(f"  Style: {payload.project_style}")
        logger.info(f"  Lighting: {payload.lighting_master.preset}")
        logger.info(f"  Architecture: {payload.architectural_identity.style_code}")
        logger.info(f"  Food: {payload.food_identity.primary_food}")
        logger.info(f"  Easter egg in scene: {payload.easter_egg.scene_number}")

        return payload

    def validate_delivery_payload(self, payload: DeliveryPayload) -> bool:
        """
        Validate delivery payload before sending to GEN2.

        Note: DeliveryPayload now has built-in validation via model_validator.
        This method provides additional logging and summary.
        """
        errors = []

        # Log handoff summary
        summary = payload.get_handoff_summary()
        logger.info("[Delivery Validation] Checking handoff contract...")
        logger.info(f"  Project: {summary['property_name']} ({summary['project_style']})")
        logger.info(f"  Scenes: {summary['scene_count']}")
        logger.info(f"  Architecture: {summary['architecture']}")
        logger.info(f"  Food: {summary['food']}")
        logger.info(f"  Lighting: {summary['lighting']}")
        logger.info(f"  Easter egg: Scene {summary['easter_egg_scene']}")

        # === SCENE COUNT ===
        if len(payload.scenes) != 6:
            errors.append(f"Expected 6 scenes, got {len(payload.scenes)}")

        # === REQUIRED HANDOFF FIELDS ===
        # These are now validated by DeliveryPayload.model_validator
        # but we double-check for logging

        if not payload.architectural_identity.style_code:
            errors.append("Missing architectural_identity.style_code")
        if not payload.architectural_identity.style_description:
            errors.append("Missing architectural_identity.style_description")
        if not payload.architectural_identity.distinctive_features:
            errors.append("Missing architectural_identity.distinctive_features")

        if not payload.food_identity.primary_food:
            errors.append("Missing food_identity.primary_food")
        if not payload.food_identity.food_dna.walls_become:
            errors.append("Missing food_identity.food_dna.walls_become")
        if not payload.food_identity.food_dna.roof_becomes:
            errors.append("Missing food_identity.food_dna.roof_becomes")

        if not payload.lighting_master.preset:
            errors.append("Missing lighting_master.preset")
        if not payload.lighting_master.prompt_snippet:
            errors.append("Missing lighting_master.prompt_snippet")

        if not payload.foreground_element.prompt_snippet:
            errors.append("Missing foreground_element.prompt_snippet")

        if not payload.easter_egg.object:
            errors.append("Missing easter_egg.object")

        # === SCENE CONTENT VALIDATION ===
        for scene in payload.scenes:
            scene_num = scene.scene_number

            if not scene.visual_concept.subject:
                errors.append(f"Scene {scene_num}: missing visual_concept.subject")
            if not scene.visual_concept.environment:
                errors.append(f"Scene {scene_num}: missing visual_concept.environment")
            if not scene.visual_concept.motion_elements:
                errors.append(f"Scene {scene_num}: missing visual_concept.motion_elements")
            if not scene.narrative_purpose:
                errors.append(f"Scene {scene_num}: missing narrative_purpose")
            if not scene.camera_intent.movement:
                errors.append(f"Scene {scene_num}: missing camera_intent.movement")

            # Validate enum values
            if scene.narrative_purpose not in VALID_NARRATIVE_PURPOSES:
                errors.append(f"Scene {scene_num}: invalid narrative_purpose '{scene.narrative_purpose}'")
            if scene.energy_level not in VALID_ENERGY_LEVELS:
                errors.append(f"Scene {scene_num}: invalid energy_level '{scene.energy_level}'")

        if errors:
            logger.error(f"[Delivery Validation] FAILED - {len(errors)} errors:")
            for err in errors:
                logger.error(f"  - {err}")
            return False

        logger.success(f"[Delivery] Payload validated - {len(REQUIRED_HANDOFF_FIELDS)} required fields OK")
        return True

    # =========================================================================
    # STAGE 2: GEN2 - Visual Prompt Generation
    # =========================================================================

    async def run_gen2(
        self,
        payload: DeliveryPayload,
        project_id: str = "",
    ) -> Optional[Gen2BatchOutput]:
        """
        Run GEN2 to generate visual prompts.

        Args:
            payload: Delivery payload from GEN1
            project_id: Optional project ID for debugging

        Returns:
            Gen2BatchOutput with image_prompt, video_prompt, reference_type for each scene
        """
        if not self.gen2_prompt:
            logger.error("GEN2 prompt not loaded!")
            return None

        logger.info(f"[GEN2] Generating visual prompts for {len(payload.scenes)} scenes")

        # Build user prompt with delivery payload
        user_prompt = self._build_gen2_user_prompt(payload)

        try:
            # Call Gemini with GEN2 system prompt
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=self.gen2_prompt,
                    temperature=0.3,  # Precise for prompt generation
                    max_output_tokens=16384,
                ),
            )

            # Extract JSON from response
            raw_output = response.text
            if not raw_output:
                logger.error("[GEN2] Empty response from API")
                return None

            # Save raw response for debugging
            self._save_raw_response(raw_output, "GEN2", project_id)

            json_data = self._extract_json(raw_output)

            if not json_data:
                logger.error("[GEN2] Failed to extract JSON from response")
                logger.debug(f"Raw output: {raw_output[:1000]}...")
                return None

            # Parse into Gen2BatchOutput model
            gen2_output = Gen2BatchOutput.model_validate(json_data)

            logger.success(f"[GEN2] Generated prompts for {len(gen2_output.scenes)} scenes")

            # Log reference type breakdown
            ref_counts = {}
            for scene in gen2_output.scenes:
                ref_type = scene.reference_type
                ref_counts[ref_type] = ref_counts.get(ref_type, 0) + 1
            logger.info(f"  Reference breakdown: {ref_counts}")

            return gen2_output

        except Exception as e:
            logger.error(f"[GEN2] Error: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None

    def _build_gen2_user_prompt(self, payload: DeliveryPayload) -> str:
        """Build user prompt for GEN2 with full delivery payload."""
        # Serialize payload to JSON for GEN2
        payload_json = payload.model_dump_json(indent=2)

        return f"""Generate visual prompts for the following creative brief:

{payload_json}

CRITICAL REQUIREMENTS:

1. IMAGE PROMPTS:
   - Use formulas from system prompt
   - Include "--ar 9:16 --no text, no letters..." suffix
   - Include "subject positioned in upper portion of frame for vertical safe zone"
   - Scene 1 (PRIMARY): Full description with foreground, landscaping
   - REQUIRES_REF: Include "Maintaining exact design and material consistency..."
   - INDEPENDENT (interior): Include food floor, furniture, fixtures

2. VIDEO PROMPTS:
   - MUST end with "10s" (Kling generates 10-second clips)
   - MAX 40 words
   - 2-3+ motion elements per scene
   - NO banned words (slow, gentle, accelerating, rack focus, speed ramp)
   - Include camera movement

3. SCENE 1 MUST HAVE first_frame_composition

4. LOOP: Scene 6 must match Scene 1 for seamless loop

5. OUTPUT STRUCTURE:
   - scenes: array of 6 Gen2SceneOutput objects
   - visual_summary: summary object

Output ONLY valid JSON matching Gen2BatchOutput schema."""

    # =========================================================================
    # VALIDATION: VAL_GEN1 & VAL_GEN2
    # =========================================================================

    async def validate_gen1(
        self,
        gen1_output: Gen1Output,
        original_topic: str = "",
        project_id: str = "",
    ) -> Optional[Gen1ValidationResponse]:
        """
        Validate GEN1 output using VAL_GEN1 system prompt.

        Args:
            gen1_output: The GEN1 output to validate
            original_topic: The original topic/hint requested
            project_id: Optional project ID for debugging

        Returns:
            Gen1ValidationResponse with validation decision
        """
        if not self.val_gen1_prompt:
            logger.error("[VAL_GEN1] Validator prompt not loaded!")
            return None

        logger.info("[VAL_GEN1] Validating GEN1 output...")

        # Build validation request
        gen1_json = gen1_output.model_dump_json(indent=2)
        user_prompt = f"""Validate the following GEN1 output:

ORIGINAL TOPIC: {original_topic or "AUTO_GENERATE"}

GEN1 OUTPUT:
{gen1_json}

Validate according to VAL_GEN1 rules and return JSON response."""

        try:
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=self.val_gen1_prompt,
                    temperature=0.1,  # Deterministic for validation
                    max_output_tokens=8192,
                ),
            )

            raw_output = response.text
            if not raw_output:
                logger.error("[VAL_GEN1] Empty response from API")
                return None
            self._save_raw_response(raw_output, "VAL_GEN1", project_id)

            json_data = self._extract_json(raw_output)
            if not json_data:
                logger.error("[VAL_GEN1] Failed to extract JSON from response")
                return None

            validation_response = Gen1ValidationResponse.model_validate(json_data)

            if validation_response.passed:
                logger.success(f"[VAL_GEN1] PASSED - {validation_response.decision.reasoning}")
            else:
                logger.warning(f"[VAL_GEN1] FAILED - {validation_response.decision.reasoning}")
                if validation_response.issues.concerns:
                    for concern in validation_response.issues.concerns:
                        logger.warning(f"  - {concern}")

            return validation_response

        except Exception as e:
            logger.error(f"[VAL_GEN1] Error: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None

    async def validate_gen2(
        self,
        gen2_output: Gen2BatchOutput,
        gen1_output: Gen1Output,
        project_id: str = "",
    ) -> Optional[Gen2ValidationResponse]:
        """
        Validate GEN2 output using VAL_GEN2 system prompt.

        Args:
            gen2_output: The GEN2 output to validate
            gen1_output: The original GEN1 output for consistency check
            project_id: Optional project ID for debugging

        Returns:
            Gen2ValidationResponse with validation decision
        """
        if not self.val_gen2_prompt:
            logger.error("[VAL_GEN2] Validator prompt not loaded!")
            return None

        logger.info("[VAL_GEN2] Validating GEN2 output...")

        # Build validation request
        gen2_json = gen2_output.model_dump_json(indent=2)
        gen1_json = gen1_output.model_dump_json(indent=2)

        user_prompt = f"""Validate the following GEN2 output:

GEN2 OUTPUT:
{gen2_json}

ORIGINAL GEN1 OUTPUT (for consistency check):
{gen1_json}

Validate according to VAL_GEN2 rules and return JSON response."""

        try:
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=self.val_gen2_prompt,
                    temperature=0.1,  # Deterministic for validation
                    max_output_tokens=8192,
                ),
            )

            raw_output = response.text
            if not raw_output:
                logger.error("[VAL_GEN2] Empty response from API")
                return None
            self._save_raw_response(raw_output, "VAL_GEN2", project_id)

            json_data = self._extract_json(raw_output)
            if not json_data:
                logger.error("[VAL_GEN2] Failed to extract JSON from response")
                return None

            validation_response = Gen2ValidationResponse.model_validate(json_data)

            if validation_response.passed:
                logger.success(f"[VAL_GEN2] PASSED - {validation_response.decision.reasoning}")
            else:
                logger.warning(f"[VAL_GEN2] FAILED - {validation_response.decision.reasoning}")
                if validation_response.issues.concerns:
                    for concern in validation_response.issues.concerns:
                        logger.warning(f"  - {concern}")
                failed_scenes = validation_response.get_failed_scenes()
                if failed_scenes:
                    logger.warning(f"  Failed scenes: {failed_scenes}")

            return validation_response

        except Exception as e:
            logger.error(f"[VAL_GEN2] Error: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None

    # =========================================================================
    # MERGE: Combine GEN1 + GEN2 into final project
    # =========================================================================

    def merge_outputs(
        self,
        gen1: Gen1Output,
        gen2: Gen2BatchOutput,
        project_id: str = "",
    ) -> GlazeCityProject:
        """
        Merge GEN1 and GEN2 outputs into final GlazeCityProject.

        This creates the complete project with all data from both stages.
        """
        logger.info("[Merge] Combining GEN1 + GEN2 outputs")

        # Create scene mapping from GEN2
        gen2_scenes: Dict[int, Gen2SceneOutput] = {
            s.scene_number: s for s in gen2.scenes
        }

        # Build GlazeScene list
        glaze_scenes: List[GlazeScene] = []

        for gen1_scene in gen1.scenes:
            gen2_scene = gen2_scenes.get(gen1_scene.scene_number)

            glaze_scene = GlazeScene(
                scene_number=gen1_scene.scene_number,
                scene_name=gen1_scene.scene_name,
                duration_seconds=gen1_scene.duration_seconds,
                voiceover=gen1_scene.voiceover_segment,
                on_screen_text=None,
                visual_description=gen1_scene.visual_concept.subject,
                camera_movement=gen1_scene.camera_intent.movement,
                audio_sfx=gen1_scene.audio_moment,
                # From GEN2
                image_prompt=gen2_scene.image_prompt if gen2_scene else "",
                video_prompt=gen2_scene.video_prompt if gen2_scene else "",
                reference_type=gen2_scene.reference_type if gen2_scene else "INDEPENDENT",
                video_tool="KLING",
            )
            glaze_scenes.append(glaze_scene)

        # Build final project with all required fields from GEN1
        project = GlazeCityProject(
            property=PropertyBrief(
                name=gen1.property.name,
            ),
            hook=HookStrategy(
                type=gen1.hook.type,
                opening_line=gen1.hook.first_words,
            ),
            psychology=Psychology(
                triggers=[gen1.hook.psychological_trigger],
            ),
            # REQUIRED per GEN1 OUTPUT CONTRACT
            architectural_identity=ArchitecturalIdentity(
                style_code=gen1.architectural_identity.style_code,
                style_description=gen1.architectural_identity.style_description,
                stories=gen1.architectural_identity.stories,
                distinctive_features=gen1.architectural_identity.distinctive_features,
                silhouette_description=gen1.architectural_identity.silhouette_description,
                interior_style=gen1.architectural_identity.interior_style,
            ),
            # REQUIRED per GEN1 OUTPUT CONTRACT
            food_identity=FoodIdentity(
                primary_food=gen1.food_identity.primary_food,
                food_dna=FoodDNA(
                    walls_become=gen1.food_identity.food_dna.walls_become,
                    roof_becomes=gen1.food_identity.food_dna.roof_becomes,
                    windows_become=gen1.food_identity.food_dna.windows_become,
                    # Gen1FoodDNA uses doors_become (plural), FoodDNA uses door_becomes (singular)
                    door_becomes=gen1.food_identity.food_dna.doors_become,
                    doors_become=gen1.food_identity.food_dna.doors_become,
                    floors_become=gen1.food_identity.food_dna.floors_become,
                    columns_become=gen1.food_identity.food_dna.columns_become,
                    furniture_becomes=gen1.food_identity.food_dna.furniture_becomes,
                ),
                texture_keywords=gen1.food_identity.texture_keywords,
                color_keywords=gen1.food_identity.color_keywords,
                atmosphere=gen1.food_identity.atmosphere,
            ),
            # REQUIRED per GEN1 OUTPUT CONTRACT
            lighting_master=LightingMaster(
                preset=gen1.lighting_master.preset,
                mood_reason=gen1.lighting_master.mood_reason,
                prompt_snippet=gen1.lighting_master.prompt_snippet,
            ),
            easter_egg=EasterEgg(
                object=gen1.engagement.easter_egg.object,
                scene_number=gen1.engagement.easter_egg.scene_number,
            ),
            loop=LoopConfig(
                connection=f"Scene 6 matches Scene 1 with reversed camera",
            ),
            scenes=glaze_scenes,
            voiceover=VoiceoverConfig(
                settings=VoiceoverSettings(
                    voice_id=gen1.voiceover.voice_id,
                    stability=gen1.voiceover.stability,
                    similarity_boost=gen1.voiceover.similarity_boost,
                ),
                full_script=gen1.voiceover.full_script,
                total_duration_seconds=gen1.metadata.target_duration_seconds,
            ),
            audio=AudioConfig(
                background_music=BackgroundMusic(
                    genre="cinematic",
                    mood="epic",
                    bpm=90,
                ),
            ),
            youtube=ViralMetadata(
                title=gen1.youtube_title or gen1.metadata.title,
                description=gen1.youtube_description or "",
                hashtags=gen1.engagement.hashtags,
                tags=gen1.youtube_tags,
            ),
            viral_audit=ViralAudit(),
            series=SeriesInfo(),
            meta=ProjectMeta(
                total_scenes=len(glaze_scenes),
                total_duration_seconds=sum(s.duration_seconds for s in glaze_scenes),
                generated_at=datetime.now().isoformat(),
            ),
            project_id=project_id,
            created_at=datetime.now(),
        )

        logger.success(f"[Merge] Created project: {project.property.name}")
        logger.info(f"  Scenes: {len(project.scenes)}")
        logger.info(f"  Duration: {project.meta.total_duration_seconds}s")

        return project

    # =========================================================================
    # FULL PIPELINE: GEN1 -> Delivery -> GEN2 -> Merge
    # =========================================================================

    async def generate_full_project(
        self,
        topic: Optional[str] = None,
        num_scenes: int = 6,  # ALWAYS 6
        style: str = "cinematic food fantasy",
        target_audience: str = "YouTube Shorts viewers",
        duration_seconds: int = 10,
        project_id: str = "",
        skip_validation: bool = False,
    ) -> Optional[GlazeCityProject]:
        """
        Run the complete two-stage generation pipeline with validation.

        Pipeline flow:
        1. GEN1 → VAL_GEN1 (retry up to 3x if failed)
        2. GEN2 → VAL_GEN2 (retry up to 3x if failed)
        3. Merge outputs

        Args:
            topic: Video topic/theme (None for auto-generate)
            num_scenes: Number of scenes (ALWAYS 6, enforced)
            style: Visual style
            target_audience: Target audience
            duration_seconds: Total duration
            project_id: Optional project ID
            skip_validation: If True, skip VAL_GEN1 and VAL_GEN2 (for testing)

        Returns:
            Complete GlazeCityProject with all prompts
        """
        logger.info("=" * 70)
        logger.info("STARTING TWO-STAGE GENERATION PIPELINE v2.2 (with validation)")
        logger.info("=" * 70)

        # Generate project_id if not provided
        if not project_id:
            project_id = f"proj_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # ENFORCE 6 SCENES
        num_scenes = 6

        # =====================================================================
        # STAGE 1: GEN1 with VAL_GEN1 validation (max 3 retries)
        # =====================================================================
        gen1_output: Optional[Gen1Output] = None
        gen1_validated = False

        for attempt in range(1, MAX_VALIDATION_RETRIES + 1):
            logger.info(f"\n[STAGE 1] Running GEN1 (attempt {attempt}/{MAX_VALIDATION_RETRIES})...")

            gen1_output = await self.run_gen1(
                topic=topic,
                num_scenes=num_scenes,
                style=style,
                target_audience=target_audience,
                duration_seconds=duration_seconds,
                project_id=project_id,
            )

            if not gen1_output:
                logger.error(f"[GEN1] Generation failed (attempt {attempt})")
                if attempt < MAX_VALIDATION_RETRIES:
                    logger.info("Retrying GEN1...")
                continue

            # Skip validation if requested
            if skip_validation:
                logger.warning("[VAL_GEN1] Skipping validation (skip_validation=True)")
                gen1_validated = True
                break

            # Validate GEN1 output
            logger.info(f"\n[VAL_GEN1] Validating GEN1 output (attempt {attempt})...")
            val_result = await self.validate_gen1(
                gen1_output=gen1_output,
                original_topic=topic or "",
                project_id=project_id,
            )

            if val_result and val_result.passed:
                logger.success(f"[VAL_GEN1] Validation PASSED on attempt {attempt}")
                gen1_validated = True
                break
            else:
                logger.warning(f"[VAL_GEN1] Validation FAILED (attempt {attempt})")
                if val_result and val_result.retry_guidance:
                    logger.info(f"  Retry guidance: {val_result.retry_guidance.fixes_needed}")
                if attempt < MAX_VALIDATION_RETRIES:
                    logger.info("Retrying GEN1 with fresh generation...")

        if not gen1_output or not gen1_validated:
            logger.error(f"[GEN1] Failed after {MAX_VALIDATION_RETRIES} attempts")
            return None

        # Save topic to memory (blacklist for future generations)
        try:
            topic_memory.add_topic(gen1_output.model_dump())
            logger.info(f"[TopicMemory] Added to blacklist: {gen1_output.metadata.title}")
        except Exception as e:
            logger.warning(f"[TopicMemory] Failed to save topic: {e}")

        # Create delivery payload
        logger.info("\n[DELIVERY] Creating payload for GEN2...")
        payload = self.create_delivery_payload(gen1_output, project_id)

        if not self.validate_delivery_payload(payload):
            logger.error("Pipeline failed at delivery validation")
            return None

        # =====================================================================
        # STAGE 2: GEN2 with VAL_GEN2 validation (max 3 retries)
        # =====================================================================
        gen2_output: Optional[Gen2BatchOutput] = None
        gen2_validated = False

        for attempt in range(1, MAX_VALIDATION_RETRIES + 1):
            logger.info(f"\n[STAGE 2] Running GEN2 (attempt {attempt}/{MAX_VALIDATION_RETRIES})...")

            gen2_output = await self.run_gen2(payload, project_id)

            if not gen2_output:
                logger.error(f"[GEN2] Generation failed (attempt {attempt})")
                if attempt < MAX_VALIDATION_RETRIES:
                    logger.info("Retrying GEN2...")
                continue

            # Skip validation if requested
            if skip_validation:
                logger.warning("[VAL_GEN2] Skipping validation (skip_validation=True)")
                gen2_validated = True
                break

            # Validate GEN2 output
            logger.info(f"\n[VAL_GEN2] Validating GEN2 output (attempt {attempt})...")
            val_result = await self.validate_gen2(
                gen2_output=gen2_output,
                gen1_output=gen1_output,
                project_id=project_id,
            )

            if val_result and val_result.passed:
                logger.success(f"[VAL_GEN2] Validation PASSED on attempt {attempt}")
                gen2_validated = True
                break
            else:
                logger.warning(f"[VAL_GEN2] Validation FAILED (attempt {attempt})")
                if val_result and val_result.retry_guidance:
                    logger.info(f"  Retry guidance: {val_result.retry_guidance.fixes_needed}")
                failed_scenes = val_result.get_failed_scenes() if val_result else []
                if failed_scenes:
                    logger.info(f"  Failed scenes: {failed_scenes}")
                if attempt < MAX_VALIDATION_RETRIES:
                    logger.info("Retrying GEN2 with fresh generation...")

        if not gen2_output:
            logger.error(f"[GEN2] Failed after {MAX_VALIDATION_RETRIES} attempts - no output")
            return None

        if not gen2_validated:
            # Check if we have usable prompts despite validation failure
            has_prompts = all(
                scene.image_prompt and scene.video_prompt
                for scene in gen2_output.scenes
            )
            if has_prompts:
                logger.warning(f"[VAL_GEN2] Validation failed but GEN2 has all prompts - continuing anyway")
            else:
                logger.error(f"[GEN2] Failed after {MAX_VALIDATION_RETRIES} attempts - validation failed and missing prompts")
                return None

        # =====================================================================
        # STAGE 3: Merge outputs
        # =====================================================================
        logger.info("\n[MERGE] Combining results...")
        project = self.merge_outputs(gen1_output, gen2_output, project_id)

        logger.info("=" * 70)
        logger.success("TWO-STAGE PIPELINE v2.2 COMPLETED SUCCESSFULLY")
        logger.info("=" * 70)

        return project

    # =========================================================================
    # UTILITIES
    # =========================================================================

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract JSON from text (handles markdown code blocks and raw JSON)."""
        # Try to find JSON in markdown code block
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Try to find raw JSON (starts with { and ends with })
            # Find the first { and last }
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1 and end > start:
                json_str = text[start:end+1]
            else:
                json_str = text.strip()

        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            logger.debug(f"Attempted to parse: {json_str[:500]}...")
            return None

    def get_prompt_status(self) -> Dict[str, Any]:
        """Get status of loaded prompts."""
        return {
            "model": self.model,
            "gen1": {
                "loaded": self.gen1_prompt is not None,
                "path": str(GEN1_PROMPT_PATH),
                "size": len(self.gen1_prompt) if self.gen1_prompt else 0,
            },
            "gen2": {
                "loaded": self.gen2_prompt is not None,
                "path": str(GEN2_PROMPT_PATH),
                "size": len(self.gen2_prompt) if self.gen2_prompt else 0,
            },
            "val_gen1": {
                "loaded": self.val_gen1_prompt is not None,
                "path": str(VAL_GEN1_PROMPT_PATH),
                "size": len(self.val_gen1_prompt) if self.val_gen1_prompt else 0,
            },
            "val_gen2": {
                "loaded": self.val_gen2_prompt is not None,
                "path": str(VAL_GEN2_PROMPT_PATH),
                "size": len(self.val_gen2_prompt) if self.val_gen2_prompt else 0,
            },
            "debug_dir": str(DEBUG_DIR),
            "max_validation_retries": MAX_VALIDATION_RETRIES,
        }


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_router_instance: Optional[PromptRouter] = None


def get_prompt_router() -> PromptRouter:
    """Get singleton PromptRouter instance."""
    global _router_instance
    if _router_instance is None:
        _router_instance = PromptRouter()
    return _router_instance


# ============================================================================
# EXPORT
# ============================================================================

__all__ = [
    "PromptRouter",
    "get_prompt_router",
    "GEN1_PROMPT_PATH",
    "GEN2_PROMPT_PATH",
    "VAL_GEN1_PROMPT_PATH",
    "VAL_GEN2_PROMPT_PATH",
    "DEBUG_DIR",
    "MAX_VALIDATION_RETRIES",
]
