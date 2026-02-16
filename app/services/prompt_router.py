"""
Prompt Router - Delivery Module for GEN1 -> GEN2 v2.1

This module handles the data flow between two prompt generation stages:
- GEN1: Generates script, concept, voiceover, audio, architectural/food identity
- GEN2: Generates visual prompts (image_prompt, video_prompt, reference_type)

Flow:
1. GEN1 generates project concept (6-10 scenes, dynamic)
2. PromptRouter validates and transforms GEN1 output
3. PromptRouter creates delivery payload for GEN2
4. GEN2 generates visual prompts
5. PromptRouter merges results into final GlazeCityProject
"""

import asyncio
import json
import re
import traceback
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime

from google import genai
from google.genai import types

from app.core.config import settings
from app.core.paths import get_project_path
from config.timeouts import GEMINI
from app.utils.logger import logger
from app.utils.yt_metadata_parser import parse_gen1_to_yt_file
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
    HookMatrix,
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
    ViralAuditScores,
    AuditScore,
    SeriesInfo,
    ProjectMeta,
    # Required by GEN1 OUTPUT CONTRACT
    ArchitecturalIdentity,
    FoodIdentity,
    FoodDNA,
    FoodMaterial,
    PropertySpecs,
    LightingMaster,
    ForegroundElement,
    # New models for full data transfer
    ShareTrigger,
    SonicHook,
    FoleyPalette,
    SceneSFX,
    SceneSFXAssignment,
    EasterEggIntegration,
    SceneInheritance,
    PostProductionNotes,
    FirstFrameCompositionGEN2,
    ScalesTechniques,
    LoopVerification,
    VisualSummary,
    # GEN1 data models (preserved during merge)
    VisualConcept,
    CameraIntent,
    # Publish config for multi-channel support
    PublishConfig,
    # GEN1 metadata for brief completeness
    ProjectMetadata,
    ProjectConcept,
)
from app.services.validation_models import (
    Gen1ValidationResponse,
    Gen2ValidationResponse,
    Gen1ValidationMetadata,
    Gen1Phase1Structural,
    Gen1Decision,
    Gen1Issues,
    Gen1RetryGuidance,
    Gen2ValidationMetadata,
    Gen2Phase1Structural,
    Gen2Decision,
    Gen2Issues,
    Gen2RetryGuidance,
)
from app.services.topic_memory import topic_memory
from app.utils.prompt_loader import load_prompt_with_banlist

# Python validators (deterministic, ~5ms, 0 tokens) - replacing LLM validators
from app.services.gen1_validator import (
    Gen1Validator,
    validate_gen1 as python_validate_gen1,
    ValidationResult as Gen1ValidationResult,
)
from app.services.gen2_validator import (
    Gen2Validator,
    validate_gen2 as python_validate_gen2,
    Gen2ValidationResult,
)


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


# =============================================================================
# DEEP MERGE UTILITIES - Залізобетонне об'єднання GEN1 + GEN2
# =============================================================================

def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    Рекурсивно об'єднує два dict. Override має пріоритет.

    Правила:
    - Якщо обидва значення dict → рекурсивний merge
    - Якщо ключ "scenes" → спеціальний merge по scene_number
    - Інакше override перезаписує base

    Args:
        base: Базовий dict (GEN1)
        override: Dict який доповнює/перезаписує (GEN2)

    Returns:
        Об'єднаний dict
    """
    result = base.copy()

    for key, override_value in override.items():
        if key not in result:
            # Новий ключ - просто додаємо
            result[key] = override_value
        elif key == "scenes" and isinstance(result[key], list) and isinstance(override_value, list):
            # Спеціальна обробка scenes - merge по scene_number
            result[key] = merge_scenes_by_number(result[key], override_value)
        elif isinstance(result[key], dict) and isinstance(override_value, dict):
            # Обидва dict - рекурсивний merge
            result[key] = deep_merge(result[key], override_value)
        elif override_value is not None:
            # Override перезаписує (якщо не None)
            result[key] = override_value

    return result


def merge_scenes_by_number(gen1_scenes: List[Dict], gen2_scenes: List[Dict]) -> List[Dict]:
    """
    Об'єднує scenes по scene_number.

    GEN1 scene + GEN2 scene → merged scene з усіма полями.

    Args:
        gen1_scenes: Список сцен з GEN1
        gen2_scenes: Список сцен з GEN2

    Returns:
        Об'єднаний список сцен
    """
    # Індексуємо по scene_number
    gen1_map = {s.get("scene_number", i+1): s for i, s in enumerate(gen1_scenes)}
    gen2_map = {s.get("scene_number", i+1): s for i, s in enumerate(gen2_scenes)}

    # Всі унікальні scene_number
    all_numbers = sorted(set(gen1_map.keys()) | set(gen2_map.keys()))

    merged_scenes = []
    for num in all_numbers:
        gen1_scene = gen1_map.get(num, {})
        gen2_scene = gen2_map.get(num, {})

        # Deep merge кожної сцени
        merged_scene = deep_merge(gen1_scene, gen2_scene)
        merged_scenes.append(merged_scene)

    return merged_scenes


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

        # Track if last GEN2 call was truncated (for retry guidance)
        self._last_gen2_truncated: bool = False
        # Track last GEN1 parse error for retry guidance
        self._last_gen1_parse_error: Optional[str] = None

        # Initialize Gemini client
        self.client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY)
        self.model = settings.CONTENTBRAIN_MODEL  # gemini-3-pro

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
        # Load GEN1 with banlist injection
        if GEN1_PROMPT_PATH.exists():
            banlist_path = CONFIG_DIR / "ban_list.txt"
            content = load_prompt_with_banlist(
                prompt_path=GEN1_PROMPT_PATH,
                banlist_path=banlist_path
            ).strip()
            if content:
                self.gen1_prompt = content
                logger.success(f"Loaded GEN1 prompt with banlist: {len(self.gen1_prompt)} chars")
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
        except OSError as e:
            logger.warning(f"Failed to save raw response to {filepath}: {e}")

        return filepath

    # =========================================================================
    # STAGE 1: GEN1 - Script & Concept Generation
    # =========================================================================

    async def run_gen1(
        self,
        topic: Optional[str] = None,
        num_scenes: int = 8,
        style: str = "cinematic food fantasy",
        target_audience: str = "YouTube Shorts viewers",
        duration_seconds: int = 10,
        project_id: str = "",
        retry_guidance: Optional[List[str]] = None,
    ) -> Optional[Gen1Output]:
        """
        Run GEN1 to generate script and concept.

        Args:
            topic: The topic/theme for the video. If None, AI will auto-generate.
            num_scenes: Number of scenes (6-10, GEN1 v6 dynamic scene engine decides)
            style: Visual style
            target_audience: Target audience
            duration_seconds: Total video duration in seconds
            project_id: Optional project ID for debugging
            retry_guidance: List of validation errors to fix from previous attempt

        Returns:
            Gen1Output with script, concepts, voiceover, audio config
        """
        if not self.gen1_prompt:
            logger.error("GEN1 prompt not loaded!")
            return None

        logger.info(f"[GEN1] Scene count: dynamic (GEN1 v6 decides, hint={num_scenes})")

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
            retry_guidance=retry_guidance,
        )

        try:
            # Call Gemini with GEN1 system prompt (with timeout)
            response = await asyncio.wait_for(
                self.client.aio.models.generate_content(
                    model=self.model,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=self.gen1_prompt,
                        temperature=0.7,  # Creative for concept generation
                        max_output_tokens=16384,  # Reduced - some models have lower limits
                    ),
                ),
                timeout=GEMINI.GEN1_CALL,
            )

            # Log response metadata for debugging
            if hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0]
                finish_reason = getattr(candidate, 'finish_reason', 'UNKNOWN')
                logger.info(f"[GEN1] Response finish_reason: {finish_reason}")
            if hasattr(response, 'usage_metadata'):
                usage = response.usage_metadata
                logger.info(f"[GEN1] Tokens - prompt: {getattr(usage, 'prompt_token_count', 'N/A')}, output: {getattr(usage, 'candidates_token_count', 'N/A')}")

            # Extract JSON from response (safety-blocked responses raise ValueError on .text)
            try:
                raw_output = response.text
            except ValueError as e:
                logger.error(f"[GEN1] Response blocked by safety filters: {e}")
                return None
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
                # Store error for retry guidance instead of raising blindly
                self._last_gen1_parse_error = str(parse_error)[:500]
                raise

            logger.success(f"[GEN1] Generated: {gen1_output.metadata.title}")
            logger.info(f"  Concept: {gen1_output.metadata.concept.subject}")
            logger.info(f"  Scenes: {len(gen1_output.scenes)}")
            logger.info(f"  Food: {gen1_output.food_identity.primary_food}")
            logger.info(f"  Architecture: {gen1_output.architectural_identity.style_code}")
            logger.info(f"  YouTube title: {gen1_output.youtube_title}")
            logger.info(f"  Viral score: {gen1_output.viral_assessment.overall_score if gen1_output.viral_assessment else 'N/A'}")

            # Detailed scene logging
            self._log_gen1_scenes(gen1_output)

            # Generate YT.txt for easy manual posting
            if project_id:
                try:
                    project_dir = get_project_path(project_id)
                    project_dir.mkdir(parents=True, exist_ok=True)
                    yt_path = project_dir / "YT.txt"
                    parse_gen1_to_yt_file(gen1_output.model_dump(), yt_path)
                    logger.info(f"[GEN1] Saved YT.txt to {yt_path}")
                except (OSError, ValueError, KeyError) as yt_err:
                    logger.warning(f"[GEN1] Failed to save YT.txt: {type(yt_err).__name__}: {yt_err}")

            return gen1_output

        except asyncio.TimeoutError:
            logger.error(f"[GEN1] Gemini API call timed out after {GEMINI.GEN1_CALL}s")
            return None
        except Exception as e:
            logger.error(f"[GEN1] Error: {e}")
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
        retry_guidance: Optional[List[str]] = None,
    ) -> str:
        """
        Build user prompt for GEN1.

        Args:
            topic: User-provided topic or hint. None for auto mode.
            num_scenes: Number of scenes (6-10, dynamic — GEN1 v6 decides)
            style: Visual style
            target_audience: Target audience
            duration_seconds: Total video duration
            auto_mode: If True, AI generates topic automatically
            retry_guidance: List of validation errors to fix from previous attempt
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
- SCENES: TARGET {num_scenes} scenes (Dynamic Scene Engine range: 6-10, but AIM FOR {num_scenes})
- TOTAL DURATION: {duration_seconds} seconds
- VISUAL STYLE: {style}
- TARGET AUDIENCE: {target_audience}

CRITICAL REQUIREMENTS:
1. Follow the OUTPUT CONTRACT FOR GEN2 EXACTLY
2. Include ALL mandatory fields:
   - metadata (with concept object, scene_count matching actual scenes)
   - property
   - hook
   - architectural_identity (with style_code, style_description, distinctive_features, silhouette_description, interior_style)
   - food_identity (with primary_food, food_dna mapping ALL elements, texture_keywords, color_keywords, atmosphere)
   - lighting_master (with preset, mood_reason, prompt_snippet)
   - foreground_element (with type, prompt_snippet)
   - scenes (6-10 scenes with visual_concept and camera_intent)
   - voiceover (with full_script)
   - audio (with sonic_hook, suno_prompt, foley_palette, sfx_per_scene)
   - engagement (with easter_egg, share_trigger, hashtags)
3. Each scene MUST have:
   - scene_number (1-N sequential)
   - scene_name
   - duration_seconds
   - narrative_purpose
   - reference_hint (PRIMARY for scene 1, REQUIRES_REF/INDEPENDENT for others)
   - energy_level
   - visual_concept (with subject, environment, mood, key_elements, lighting_note, motion_elements)
   - camera_intent (with movement, combo, framing, special)
   - voiceover_segment
   - audio_moment

{self._format_retry_guidance(retry_guidance)}Output ONLY valid JSON. Start with {{ and end with }}"""
        else:
            # IDEA MODE: User provided hint/topic
            return f"""{blacklist_section}TOPIC: {topic}

Develop this idea into a complete video concept for "Glaze City" style channel.

CONSTRAINTS:
- SCENES: TARGET {num_scenes} scenes (Dynamic Scene Engine range: 6-10, but AIM FOR {num_scenes})
- TOTAL DURATION: {duration_seconds} seconds
- VISUAL STYLE: {style}
- TARGET AUDIENCE: {target_audience}

CRITICAL REQUIREMENTS:
1. Follow the OUTPUT CONTRACT FOR GEN2 EXACTLY
2. Include ALL mandatory fields:
   - metadata (with concept object, scene_count matching actual scenes)
   - property
   - hook
   - architectural_identity (with style_code, style_description, distinctive_features, silhouette_description, interior_style)
   - food_identity (with primary_food, food_dna mapping ALL elements, texture_keywords, color_keywords, atmosphere)
   - lighting_master (with preset, mood_reason, prompt_snippet)
   - foreground_element (with type, prompt_snippet)
   - scenes (6-10 scenes with visual_concept and camera_intent)
   - voiceover (with full_script)
   - audio (with sonic_hook, suno_prompt, foley_palette, sfx_per_scene)
   - engagement (with easter_egg, share_trigger, hashtags)
3. Each scene MUST have:
   - scene_number (1-N sequential)
   - scene_name
   - duration_seconds
   - narrative_purpose
   - reference_hint (PRIMARY for scene 1, REQUIRES_REF/INDEPENDENT for others)
   - energy_level
   - visual_concept (with subject, environment, mood, key_elements, lighting_note, motion_elements)
   - camera_intent (with movement, combo, framing, special)
   - voiceover_segment
   - audio_moment

{self._format_retry_guidance(retry_guidance)}Output ONLY valid JSON. Start with {{ and end with }}"""

    def _format_retry_guidance(self, retry_guidance: Optional[List[str]]) -> str:
        """Format retry guidance for inclusion in prompt."""
        if not retry_guidance:
            return ""

        fixes = "\n".join(f"  - {fix}" for fix in retry_guidance)
        return f"""⚠️ PREVIOUS ATTEMPT FAILED VALIDATION - FIX THESE ISSUES:
{fixes}

You MUST fix ALL the issues listed above. Pay special attention to:
- motion_elements: Each scene needs AT LEAST 2 motion elements
- Ensure all required fields are present and properly formatted

"""

    def _log_gen1_scenes(self, gen1: Gen1Output) -> None:
        """Log detailed GEN1 scene information for debugging."""
        logger.info("=" * 70)
        logger.info("[GEN1] DETAILED SCENE BREAKDOWN")
        logger.info("=" * 70)

        for scene in gen1.scenes:
            logger.info(f"\n[GEN1] Scene {scene.scene_number}: {scene.scene_name}")
            logger.info(f"  duration: {scene.duration_seconds}s")
            logger.info(f"  narrative_purpose: {scene.narrative_purpose}")
            logger.info(f"  reference_hint: {scene.reference_hint}")
            logger.info(f"  energy_level: {scene.energy_level}")

            # Visual concept
            vc = scene.visual_concept
            logger.info(f"  visual_concept.subject: {vc.subject[:80]}..." if len(vc.subject) > 80 else f"  visual_concept.subject: {vc.subject}")
            logger.info(f"  visual_concept.environment: {vc.environment[:60]}..." if len(vc.environment) > 60 else f"  visual_concept.environment: {vc.environment}")
            logger.info(f"  visual_concept.mood: {vc.mood}")
            logger.info(f"  visual_concept.key_elements: {vc.key_elements}")
            logger.info(f"  visual_concept.lighting_note: {vc.lighting_note}")
            logger.info(f"  visual_concept.motion_elements: {vc.motion_elements}")

            # Camera intent
            ci = scene.camera_intent
            logger.info(f"  camera_intent.movement: {ci.movement}")
            logger.info(f"  camera_intent.combo: {ci.combo}")
            logger.info(f"  camera_intent.framing: {ci.framing}")
            logger.info(f"  camera_intent.special: {ci.special}")

            # Voiceover
            logger.info(f"  voiceover_segment: {scene.voiceover_segment[:50]}..." if scene.voiceover_segment and len(scene.voiceover_segment) > 50 else f"  voiceover_segment: {scene.voiceover_segment}")
            logger.info(f"  audio_moment: {scene.audio_moment}")

        logger.info("=" * 70)

    def _fix_last_scene_reference_type(self, gen2: Gen2BatchOutput) -> Gen2BatchOutput:
        """
        Auto-fix last scene reference_type to LOOP_CLOSE if incorrect.

        Last scene MUST always have reference_type='LOOP_CLOSE' for seamless video loop.
        The LLM sometimes generates 'REQUIRES_REF' instead, so we fix it deterministically.

        Also ensures last scene has proper inheritance pointing to Scene 1.
        """
        if not gen2.scenes:
            logger.error("[GEN2 POST-FIX] GEN2 has no scenes — cannot fix reference types")
            return gen2
        last_scene_num = max(s.scene_number for s in gen2.scenes)
        for scene in gen2.scenes:
            if scene.scene_number == last_scene_num:
                if scene.reference_type != "LOOP_CLOSE":
                    logger.warning(
                        f"[GEN2 POST-FIX] Scene {last_scene_num} reference_type was '{scene.reference_type}', "
                        f"auto-correcting to 'LOOP_CLOSE'"
                    )
                    scene.reference_type = "LOOP_CLOSE"

                # Ensure inheritance exists and points to Scene 1
                if not scene.inheritance:
                    from app.services.gen_models import Gen2Inheritance
                    logger.warning(
                        f"[GEN2 POST-FIX] Scene {last_scene_num} missing inheritance, creating with parent_scene=1"
                    )
                    scene.inheritance = Gen2Inheritance(
                        parent_scene=1,
                        inherited_elements=["exterior establishing shot", "subject design", "lighting"],
                        modified_elements=["camera movement for loop"]
                    )
                elif scene.inheritance.parent_scene != 1:
                    logger.warning(
                        f"[GEN2 POST-FIX] Scene {last_scene_num} inheritance.parent_scene was {scene.inheritance.parent_scene}, "
                        f"correcting to 1"
                    )
                    scene.inheritance.parent_scene = 1

        return gen2

    def _log_gen2_scenes(self, gen2: Gen2BatchOutput) -> None:
        """Log detailed GEN2 scene information for debugging."""
        logger.info("=" * 70)
        logger.info("[GEN2] DETAILED SCENE BREAKDOWN")
        logger.info("=" * 70)

        for scene in gen2.scenes:
            logger.info(f"\n[GEN2] Scene {scene.scene_number}: {scene.reference_type}")
            logger.info(f"  image_prompt: {scene.image_prompt[:100]}..." if len(scene.image_prompt) > 100 else f"  image_prompt: {scene.image_prompt}")
            logger.info(f"  video_prompt: {scene.video_prompt[:100]}..." if len(scene.video_prompt) > 100 else f"  video_prompt: {scene.video_prompt}")
            logger.info(f"  motion_elements: {scene.motion_elements}")

            # Check for missing critical fields
            missing = []
            if not scene.image_prompt:
                missing.append("image_prompt")
            if not scene.video_prompt:
                missing.append("video_prompt")
            if not scene.motion_elements:
                missing.append("motion_elements")

            if missing:
                logger.warning(f"  [!] MISSING FIELDS: {missing}")

            # Inheritance info
            if scene.inheritance:
                logger.info(f"  inheritance.parent_scene: {scene.inheritance.parent_scene}")
                logger.info(f"  inheritance.inherited_elements: {scene.inheritance.inherited_elements}")

            # First frame (scene 1 only)
            if scene.first_frame_composition:
                logger.info(f"  first_frame_composition: PRESENT")
                logger.info(f"    hook_element: {scene.first_frame_composition.hook_element}")

            # Scale techniques
            if scene.scale_techniques:
                logger.info(f"  scale_techniques: PRESENT")

        # Visual summary
        if gen2.visual_summary:
            logger.info("\n[GEN2] Visual Summary:")
            logger.info(f"  total_scenes: {gen2.visual_summary.total_scenes}")
            logger.info(f"  reference_breakdown: {gen2.visual_summary.reference_breakdown}")
            logger.info(f"  loop_verified: {gen2.visual_summary.loop_verified}")
            logger.info(f"  gigantism_protocol: {gen2.visual_summary.gigantism_protocol}")
            if gen2.visual_summary.loop_verification:
                lv = gen2.visual_summary.loop_verification
                logger.info(f"  loop_verification.movements_are_different: {lv.movements_are_different}")
                logger.info(f"  loop_verification.sceneN_camera_movement: {lv.sceneN_camera_movement}")

        logger.info("=" * 70)

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
        if payload.easter_egg and payload.easter_egg.object:
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
        if len(payload.scenes) < 6 or len(payload.scenes) > 10:
            errors.append(f"Expected 6-10 scenes, got {len(payload.scenes)}")

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

        if payload.easter_egg and not payload.easter_egg.object:
            # Only check if easter_egg was provided (v8.0.0 uses replay_hooks instead)
            pass

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
        retry_guidance: Optional[List[str]] = None,
    ) -> Optional[Gen2BatchOutput]:
        """
        Run GEN2 to generate visual prompts.

        Args:
            payload: Delivery payload from GEN1
            project_id: Optional project ID for debugging
            retry_guidance: List of validation errors to fix from previous attempt

        Returns:
            Gen2BatchOutput with image_prompt, video_prompt, reference_type for each scene
        """
        # Reset truncation flag
        self._last_gen2_truncated = False

        if not self.gen2_prompt:
            logger.error("GEN2 prompt not loaded!")
            return None

        logger.info(f"[GEN2] Generating visual prompts for {len(payload.scenes)} scenes")

        # Build user prompt with delivery payload
        user_prompt = self._build_gen2_user_prompt(payload, retry_guidance)

        try:
            # Call Gemini with GEN2 system prompt (with timeout)
            # NOTE: response_mime_type removed - it may cause token limit issues
            response = await asyncio.wait_for(
                self.client.aio.models.generate_content(
                    model=self.model,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=self.gen2_prompt,
                        temperature=0.3,  # Precise for prompt generation
                        max_output_tokens=16384,  # Reduced - some models have lower limits
                    ),
                ),
                timeout=GEMINI.GEN2_CALL,
            )

            # Extract JSON from response (safety-blocked responses raise ValueError on .text)
            try:
                raw_output = response.text
            except ValueError as e:
                logger.error(f"[GEN2] Response blocked by safety filters: {e}")
                return None

            # Log response metadata for debugging truncation issues
            finish_reason = None
            if hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0]
                finish_reason = getattr(candidate, 'finish_reason', None)
                finish_reason_str = str(finish_reason) if finish_reason is not None else ""
                logger.info(f"[GEN2] Response finish_reason: {finish_reason_str}")
                if finish_reason is not None and "STOP" not in finish_reason_str and finish_reason_str != "1":
                    logger.warning(f"[GEN2] Abnormal finish_reason: {finish_reason_str} (STOP=normal, MAX_TOKENS=truncated, SAFETY=blocked)")
            if hasattr(response, 'usage_metadata'):
                usage = response.usage_metadata
                logger.info(f"[GEN2] Tokens - prompt: {getattr(usage, 'prompt_token_count', 'N/A')}, output: {getattr(usage, 'candidates_token_count', 'N/A')}")

            # Check for truncation - if MAX_TOKENS, the response is incomplete
            finish_reason_str = str(finish_reason) if finish_reason is not None else ""
            if finish_reason is not None and ("MAX_TOKENS" in finish_reason_str or finish_reason_str == "2"):
                logger.error(f"[GEN2] Response TRUNCATED (MAX_TOKENS) - output will be incomplete!")
                logger.error(f"[GEN2] Raw output ends with: ...{raw_output[-200:] if raw_output else 'EMPTY'}")
                # Set truncation flag for retry guidance
                self._last_gen2_truncated = True
                # Don't return None - let it try to parse, validation will catch incomplete data

            if not raw_output:
                logger.error("[GEN2] Empty response from API")
                return None

            logger.info(f"[GEN2] Raw output length: {len(raw_output)} chars")

            # Save raw response for debugging
            self._save_raw_response(raw_output, "GEN2", project_id)

            json_data = self._extract_json(raw_output)

            if not json_data:
                logger.error("[GEN2] Failed to extract JSON from response")
                logger.warning(f"[GEN2] Raw output first 1500 chars:\n{raw_output[:1500]}")
                return None

            # Parse into Gen2BatchOutput model
            gen2_output = Gen2BatchOutput.model_validate(json_data)

            logger.success(f"[GEN2] Generated prompts for {len(gen2_output.scenes)} scenes")

            # Validate scene count matches input payload
            expected_count = len(payload.scenes)
            actual_count = len(gen2_output.scenes)
            if actual_count != expected_count:
                logger.error(
                    f"[GEN2] Scene count MISMATCH: payload has {expected_count} scenes, "
                    f"GEN2 returned {actual_count}. Likely truncated output."
                )
                self._last_gen2_truncated = True
                return None

            # Post-process: Auto-fix last scene reference_type to LOOP_CLOSE
            # This is a deterministic fix since the last scene MUST always be LOOP_CLOSE
            gen2_output = self._fix_last_scene_reference_type(gen2_output)

            # Log reference type breakdown
            ref_counts = {}
            for scene in gen2_output.scenes:
                ref_type = scene.reference_type
                ref_counts[ref_type] = ref_counts.get(ref_type, 0) + 1
            logger.info(f"  Reference breakdown: {ref_counts}")

            # Detailed scene logging
            self._log_gen2_scenes(gen2_output)

            return gen2_output

        except asyncio.TimeoutError:
            logger.error(f"[GEN2] Gemini API call timed out after {GEMINI.GEN2_CALL}s")
            return None
        except Exception as e:
            logger.error(f"[GEN2] Error: {e}")
            logger.error(traceback.format_exc())
            return None

    def _build_gen2_user_prompt(
        self,
        payload: DeliveryPayload,
        retry_guidance: Optional[List[str]] = None,
    ) -> str:
        """Build user prompt for GEN2 with full delivery payload."""
        # Serialize payload to JSON for GEN2
        payload_json = payload.model_dump_json(indent=2)

        # Build retry guidance section if present
        retry_section = ""
        if retry_guidance:
            fixes = "\n".join(f"  - {fix}" for fix in retry_guidance)
            retry_section = f"""
⚠️ PREVIOUS ATTEMPT FAILED VALIDATION - FIX THESE ISSUES:
{fixes}

You MUST fix ALL the issues listed above before generating output.

"""

        return f"""Generate visual prompts for the following creative brief:

{payload_json}

⚠️ TOKEN LIMIT WARNING: Keep your response CONCISE to avoid truncation!
- image_prompt: MAX 150 words each
- video_prompt: MAX 40 words each
- motion_elements: MAX 4 items per scene
- scale_techniques: Keep brief, 5-10 words per field

CRITICAL REQUIREMENTS:

1. SCENE COUNT (MANDATORY - DO NOT SKIP!):
   - You MUST return scenes matching the GEN1 scene count from the input
   - scene_number MUST be: 1 through N (in order, no duplicates, no gaps)
   - Process ALL scenes from the input - do not skip any!

2. IMAGE PROMPTS:
   - Use formulas from system prompt
   - Include "--no tilt-shift, miniature, diorama..." negative prompt
   - Include "subject positioned in upper portion of frame for vertical safe zone"
   - Scene 1 (PRIMARY): Full description with foreground, landscaping
   - REQUIRES_REF: Include "Maintaining exact design and material consistency..."
   - INDEPENDENT (interior): Include food floor, furniture, fixtures
   - NO --ar (hardcoded in software)

3. VIDEO PROMPTS:
   - MAX 40 words
   - 2-3+ motion elements per scene
   - NO banned words (slow, gentle, accelerating, rack focus, speed ramp)
   - Include camera movement
   - NO duration spec like "10s" (hardcoded in software)

4. SCENE 1 MUST HAVE first_frame_composition

5. LAST SCENE LOOP REQUIREMENTS (CRITICAL!):
   - reference_type MUST be "LOOP_CLOSE" (NOT "REQUIRES_REF"!)
   - Must match Scene 1 for seamless loop
   - Must have inheritance object referencing Scene 1

6. OUTPUT STRUCTURE:
   - scenes: array of Gen2SceneOutput objects with scene_number 1 through N
   - visual_summary: summary object with total_scenes matching scene count

{retry_section}Output ONLY valid JSON matching Gen2BatchOutput schema."""

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
        Validate GEN1 output using Python deterministic validator.

        REPLACED LLM validator with Python validator for:
        - Speed: ~5ms vs ~10-15s
        - Cost: 0 tokens vs ~3000-5000 tokens
        - Determinism: 100% reproducible results
        - No hallucinations

        Args:
            gen1_output: The GEN1 output to validate
            original_topic: The original topic/hint requested
            project_id: Optional project ID for debugging

        Returns:
            Gen1ValidationResponse with validation decision
        """
        logger.info("[VAL_GEN1_PYTHON] Validating GEN1 output with Python validator...")

        try:
            # Convert Pydantic model to dict for Python validator
            gen1_dict = gen1_output.model_dump()

            # Run Python validator (deterministic, ~5ms)
            result: Gen1ValidationResult = python_validate_gen1(gen1_dict, strict_mode=True)

            # Save debug output
            debug_output = json.dumps(result.to_dict(), indent=2, ensure_ascii=False)
            self._save_raw_response(debug_output, "VAL_GEN1_PYTHON", project_id)

            # Convert to Gen1ValidationResponse format
            # Note: phase1_structural.errors expects List[str], not List[dict]
            validation_data = {
                "validation": {
                    "stage": "VAL_GEN1",
                    "version": result.validator_version,
                    "timestamp": result.timestamp,
                },
                "phase1_structural": {
                    "status": "PASS" if result.passed else "FAIL",
                    "errors": [str(e) for e in result.errors],  # Convert to strings
                    "warnings": [str(w) for w in result.warnings],  # Convert to strings
                },
                "phase2_quality": None,
                "decision": {
                    "status": "PASSED" if result.passed else "FAILED",
                    "reasoning": f"Python validator: {len(result.errors)} errors, {len(result.warnings)} warnings. "
                                 + ("Ready for GEN2." if result.passed else "Fix errors before proceeding."),
                    "proceed_to": "GEN2" if result.passed else None,
                },
                "issues": {
                    "has_issues": len(result.errors) > 0 or len(result.warnings) > 0,
                    "concerns": [str(e) for e in result.errors] + [str(w) for w in result.warnings],
                },
                "retry_guidance": {
                    "fixes_needed": [f"{e.field}: {e.message}" for e in result.errors],
                    "regenerate": True,
                } if not result.passed else None,
            }

            validation_response = Gen1ValidationResponse.model_validate(validation_data)

            if validation_response.passed:
                logger.success(f"[VAL_GEN1_PYTHON] PASSED in {result.validation_time_ms:.1f}ms - {validation_response.decision.reasoning}")
            else:
                logger.warning(f"[VAL_GEN1_PYTHON] FAILED in {result.validation_time_ms:.1f}ms - {validation_response.decision.reasoning}")
                if validation_response.issues.concerns:
                    for concern in validation_response.issues.concerns[:5]:  # Limit to first 5
                        logger.warning(f"  - {concern}")
                    if len(validation_response.issues.concerns) > 5:
                        logger.warning(f"  ... and {len(validation_response.issues.concerns) - 5} more issues")

            return validation_response

        except Exception as e:
            logger.error(f"[VAL_GEN1_PYTHON] Error: {e}")
            logger.error(traceback.format_exc())
            return None

    async def validate_gen2(
        self,
        gen2_output: Gen2BatchOutput,
        gen1_output: Gen1Output,
        project_id: str = "",
    ) -> Optional[Gen2ValidationResponse]:
        """
        Validate GEN2 output using Python deterministic validator.

        REPLACED LLM validator with Python validator for:
        - Speed: ~5ms vs ~10-15s
        - Cost: 0 tokens vs ~4000-6000 tokens
        - Determinism: 100% reproducible results
        - No hallucinations

        Args:
            gen2_output: The GEN2 output to validate
            gen1_output: The original GEN1 output for consistency check
            project_id: Optional project ID for debugging

        Returns:
            Gen2ValidationResponse with validation decision
        """
        logger.info("[VAL_GEN2_PYTHON] Validating GEN2 output with Python validator...")

        try:
            # Convert Pydantic models to dicts for Python validator
            gen2_dict = gen2_output.model_dump()
            gen1_dict = gen1_output.model_dump()

            # Run Python validator (deterministic, ~5ms)
            result: Gen2ValidationResult = python_validate_gen2(gen2_dict, gen1_dict)

            # Save debug output
            debug_output = json.dumps(result.to_dict(), indent=2, ensure_ascii=False)
            self._save_raw_response(debug_output, "VAL_GEN2_PYTHON", project_id)

            # Convert scene_checks to Gen2SceneCheck format
            scene_checks = []
            for sc in result.scene_checks:
                scene_checks.append({
                    "scene": sc.scene,
                    "image_prompt": sc.image_prompt if sc.image_prompt in ["PASS", "FAIL", "WARNING"] else "PASS",
                    "video_prompt": sc.video_prompt if sc.video_prompt in ["PASS", "FAIL", "WARNING"] else "PASS",
                    "motion_elements": sc.motion_elements if sc.motion_elements in ["PASS", "FAIL", "WARNING"] else "PASS",
                })

            # Convert to Gen2ValidationResponse format
            validation_data = {
                "validation": {
                    "stage": "VAL_GEN2",
                    "version": result.validator_version,
                    "timestamp": result.timestamp,
                },
                "phase1_structural": {
                    "status": "PASS" if result.passed else "FAIL",
                    "scene_checks": scene_checks,
                    "errors": [str(e) for e in result.errors],  # Convert to strings
                    "warnings": [str(w) for w in result.warnings],  # Convert to strings
                },
                "phase2_quality": None,
                "decision": {
                    "status": "PASSED" if result.passed else "FAILED",
                    "reasoning": f"Python validator: {len(result.errors)} errors, {len(result.warnings)} warnings. "
                                 + ("Ready for IMG_GEN." if result.passed else "Fix errors before proceeding."),
                    "proceed_to": "IMG_GEN" if result.passed else None,
                },
                "issues": {
                    "has_issues": len(result.errors) > 0 or len(result.warnings) > 0,
                    "concerns": [str(e) for e in result.errors] + [str(w) for w in result.warnings],
                },
                "retry_guidance": {
                    "fixes_needed": [f"{e.field}: {e.message}" for e in result.errors],
                    "regenerate": True,
                } if not result.passed else None,
            }

            validation_response = Gen2ValidationResponse.model_validate(validation_data)

            if validation_response.passed:
                logger.success(f"[VAL_GEN2_PYTHON] PASSED in {result.validation_time_ms:.1f}ms - {validation_response.decision.reasoning}")
            else:
                logger.warning(f"[VAL_GEN2_PYTHON] FAILED in {result.validation_time_ms:.1f}ms - {validation_response.decision.reasoning}")
                if validation_response.issues.concerns:
                    for concern in validation_response.issues.concerns[:5]:  # Limit to first 5
                        logger.warning(f"  - {concern}")
                    if len(validation_response.issues.concerns) > 5:
                        logger.warning(f"  ... and {len(validation_response.issues.concerns) - 5} more issues")
                failed_scenes = validation_response.get_failed_scenes()
                if failed_scenes:
                    logger.warning(f"  Failed scenes: {failed_scenes}")

            return validation_response

        except Exception as e:
            logger.error(f"[VAL_GEN2_PYTHON] Error: {e}")
            logger.error(traceback.format_exc())
            return None

    # =========================================================================
    # MERGE: Combine GEN1 + GEN2 into final project
    # =========================================================================

    def _parse_price_numeric(self, price_str: str) -> int:
        """Extract numeric value from price string like '$65 per day' or '$2.5M'."""
        if not price_str:
            return 0
        import re
        # Remove $ and commas
        cleaned = price_str.replace('$', '').replace(',', '').strip()
        # Try to find number with optional M/K suffix
        match = re.search(r'([\d.]+)\s*(M|K|million|thousand)?', cleaned, re.IGNORECASE)
        if match:
            num = float(match.group(1))
            suffix = (match.group(2) or '').upper()
            if suffix in ('M', 'MILLION'):
                return int(num * 1_000_000)
            elif suffix in ('K', 'THOUSAND'):
                return int(num * 1_000)
            return int(num)
        return 0

    def _parse_safe_zone_from_placement(
        self,
        placement: str,
        validation_check: str = "",
        gen2_placement_in_prompt: str = ""
    ) -> str:
        """
        Parse safe_zone_position from placement, validation_check, or GEN2 placement_in_prompt.

        Priority order:
        1. gen2_placement_in_prompt (most accurate - GEN2 Visual Director specifies exact position)
        2. placement (GEN1 placement description)
        3. validation_check (fallback)

        Examples:
            - "bottom right, 5% of frame" -> "bottom-right"
            - "center-right area" -> "center-right"
            - "Red jar on beige cable, middle right" -> "center-right"
        """
        # Try gen2_placement_in_prompt first (most accurate), then placement, then validation_check
        for text in [gen2_placement_in_prompt, placement, validation_check]:
            if not text:
                continue
            text_lower = text.lower()

            # Check for position keywords
            if 'bottom' in text_lower:
                if 'right' in text_lower:
                    return "bottom-right"
                elif 'left' in text_lower:
                    return "bottom-left"
                elif 'center' in text_lower or 'middle' in text_lower:
                    return "bottom-center"
                return "bottom-right"  # default bottom
            elif 'top' in text_lower:
                if 'right' in text_lower:
                    return "top-right"
                elif 'left' in text_lower:
                    return "top-left"
                return "top-right"  # default top
            elif 'center' in text_lower or 'middle' in text_lower:
                if 'right' in text_lower:
                    return "center-right"
                elif 'left' in text_lower:
                    return "center-left"
                return "center"
            elif 'right' in text_lower:
                return "center-right"
            elif 'left' in text_lower:
                return "center-left"

        return "center"

    def _parse_visibility_score(self, visibility: str) -> float:
        """Convert visibility string to score."""
        if not visibility:
            return 0.5
        visibility_upper = visibility.upper()
        if visibility_upper == "HIDDEN":
            return 0.2
        elif visibility_upper == "OBVIOUS":
            return 0.8
        elif visibility_upper == "FINDABLE":
            return 0.5
        return 0.5

    def _build_loop_config(self, gen1) -> "LoopConfig":
        """Build LoopConfig from GEN1 loop data (extra field)."""
        gen1_loop = getattr(gen1, 'loop', None)
        if gen1_loop is None and gen1.__pydantic_extra__:
            gen1_loop = gen1.__pydantic_extra__.get('loop')

        if isinstance(gen1_loop, dict):
            return LoopConfig(
                last_line=gen1_loop.get('scene_n_exit', '') or gen1_loop.get('last_line', '') or '',
                first_line=gen1_loop.get('scene_1_entry', '') or gen1_loop.get('first_line', '') or '',
                connection=gen1_loop.get('technique', '') or gen1_loop.get('connection', '')
                    or "Last scene (LOOP_CLOSE) matches Scene 1 with reversed camera",
                bridge_sfx=gen1_loop.get('bridge_sfx', '') or '',
            )

        return LoopConfig(
            connection="Last scene (LOOP_CLOSE) matches Scene 1 with reversed camera",
        )

    def _parse_bpm_from_suno_prompt(self, suno_prompt: str) -> int:
        """Extract BPM from suno prompt like 'Tropical house, 124 bpm'."""
        if not suno_prompt:
            return 90
        import re
        match = re.search(r'(\d+)\s*bpm', suno_prompt, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return 90

    def _convert_viral_score(self, score_0_1: float) -> int:
        """Convert 0.0-1.0 score to 0-10 integer."""
        return int(round(score_0_1 * 10))

    def _get_viral_probability(self, overall_score: float) -> str:
        """Get viral probability string from overall score (0.0-1.0)."""
        if overall_score >= 0.75:
            return "VERY_HIGH"
        elif overall_score >= 0.6:
            return "HIGH"
        elif overall_score >= 0.4:
            return "MEDIUM"
        return "LOW"

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
        logger.info("=" * 70)
        logger.info("[MERGE] Combining GEN1 + GEN2 outputs")
        logger.info("=" * 70)
        logger.info(f"[MERGE] GEN1 scenes: {len(gen1.scenes)}")
        logger.info(f"[MERGE] GEN2 scenes: {len(gen2.scenes)}")

        # Validate GEN2 scene_numbers BEFORE creating dict
        gen2_scene_numbers = [s.scene_number for s in gen2.scenes]
        logger.info(f"[MERGE] GEN2 scene_numbers (raw): {gen2_scene_numbers}")

        # Check for duplicates
        if len(gen2_scene_numbers) != len(set(gen2_scene_numbers)):
            duplicates = sorted(set(n for n in gen2_scene_numbers if gen2_scene_numbers.count(n) > 1))
            logger.error(f"[MERGE] CRITICAL: GEN2 has duplicate scene_numbers: {duplicates}")
            raise RuntimeError(f"GEN2 output has duplicate scene_numbers: {duplicates}. Cannot merge.")

        # Check for missing scenes
        gen1_scene_numbers = {s.scene_number for s in gen1.scenes}
        gen2_scene_numbers_set = set(gen2_scene_numbers)
        missing_in_gen2 = gen1_scene_numbers - gen2_scene_numbers_set
        if missing_in_gen2:
            logger.error(f"[MERGE] CRITICAL: GEN2 missing scene_numbers that exist in GEN1: {sorted(missing_in_gen2)}")
            logger.error(f"[MERGE] These scenes will have EMPTY image/video prompts — image generation will fail for them")
            raise RuntimeError(f"GEN2 output incomplete: missing scenes {sorted(missing_in_gen2)}. Cannot merge.")

        # Create scene mapping from GEN2
        gen2_scenes: Dict[int, Gen2SceneOutput] = {
            s.scene_number: s for s in gen2.scenes
        }
        logger.info(f"[MERGE] GEN2 scene numbers (after dict): {list(gen2_scenes.keys())}")

        # Build GlazeScene list
        glaze_scenes: List[GlazeScene] = []
        current_timestamp: float = 0.0
        merge_issues: List[str] = []

        for gen1_scene in gen1.scenes:
            gen2_scene = gen2_scenes.get(gen1_scene.scene_number)

            # Log FULL merge status for this scene
            logger.info(f"\n{'='*60}")
            logger.info(f"[MERGE] Scene {gen1_scene.scene_number}: {gen1_scene.scene_name}")
            logger.info(f"{'='*60}")

            # GEN1 fields
            logger.info(f"  [GEN1 FIELDS]:")
            logger.info(f"    scene_number: {gen1_scene.scene_number}")
            logger.info(f"    scene_name: {gen1_scene.scene_name}")
            logger.info(f"    duration_seconds: {gen1_scene.duration_seconds}")
            logger.info(f"    narrative_purpose: {gen1_scene.narrative_purpose}")
            logger.info(f"    reference_hint: {gen1_scene.reference_hint}")
            logger.info(f"    energy_level: {gen1_scene.energy_level}")
            logger.info(f"    voiceover_segment: {gen1_scene.voiceover_segment[:40]}..." if gen1_scene.voiceover_segment else "    voiceover_segment: EMPTY")
            logger.info(f"    audio_moment: {gen1_scene.audio_moment}")

            # GEN1 visual_concept
            vc = gen1_scene.visual_concept
            logger.info(f"    visual_concept.subject: {vc.subject[:50]}..." if vc.subject else "    visual_concept.subject: MISSING!")
            logger.info(f"    visual_concept.environment: {vc.environment[:40]}..." if vc.environment else "    visual_concept.environment: MISSING!")
            logger.info(f"    visual_concept.mood: {vc.mood}")
            logger.info(f"    visual_concept.key_elements: {vc.key_elements}")
            logger.info(f"    visual_concept.lighting_note: {vc.lighting_note}")
            logger.info(f"    visual_concept.motion_elements: {vc.motion_elements}")

            # GEN1 camera_intent
            ci = gen1_scene.camera_intent
            logger.info(f"    camera_intent.movement: {ci.movement}")
            logger.info(f"    camera_intent.combo: {ci.combo}")
            logger.info(f"    camera_intent.framing: {ci.framing}")
            logger.info(f"    camera_intent.special: {ci.special}")

            if gen2_scene:
                logger.info(f"  [GEN2 FIELDS]:")
                logger.info(f"    reference_type: {gen2_scene.reference_type}")
                logger.info(f"    image_prompt: {gen2_scene.image_prompt[:80]}..." if gen2_scene.image_prompt else "    image_prompt: MISSING!")
                logger.info(f"    video_prompt: {gen2_scene.video_prompt[:80]}..." if gen2_scene.video_prompt else "    video_prompt: MISSING!")
                logger.info(f"    motion_elements: {gen2_scene.motion_elements}")

                if gen2_scene.inheritance:
                    logger.info(f"    inheritance.parent_scene: {gen2_scene.inheritance.parent_scene}")
                    logger.info(f"    inheritance.inherited_elements: {gen2_scene.inheritance.inherited_elements}")
                if gen2_scene.first_frame_composition:
                    logger.info(f"    first_frame_composition: PRESENT (hook={gen2_scene.first_frame_composition.hook_element})")
                if gen2_scene.scale_techniques:
                    logger.info(f"    scale_techniques: PRESENT")
                if gen2_scene.post_production_notes:
                    logger.info(f"    post_production_notes: PRESENT")

                # Track missing fields
                if not gen2_scene.image_prompt:
                    merge_issues.append(f"Scene {gen1_scene.scene_number}: missing image_prompt")
                if not gen2_scene.video_prompt:
                    merge_issues.append(f"Scene {gen1_scene.scene_number}: missing video_prompt")
            else:
                logger.warning(f"  [GEN2 FIELDS]: NOT FOUND!")
                merge_issues.append(f"Scene {gen1_scene.scene_number}: no GEN2 data")

            # Format timestamp as "M:SS"
            minutes = int(current_timestamp // 60)
            seconds = int(current_timestamp % 60)
            timestamp_str = f"{minutes}:{seconds:02d}"

            # Build GEN2 metadata for this scene
            scene_inheritance = None
            scene_post_production = None
            scene_first_frame = None
            scene_scale_techniques = None
            scene_visual_punctuation = None
            scene_easter_egg_integration = None

            if gen2_scene:
                # Inheritance (REQUIRES_REF and LOOP_CLOSE scenes)
                if gen2_scene.inheritance:
                    scene_inheritance = SceneInheritance(
                        parent_scene=gen2_scene.inheritance.parent_scene,
                        inherited_elements=gen2_scene.inheritance.inherited_elements or [],
                        modified_elements=gen2_scene.inheritance.modified_elements or [],
                    )

                # Post-production notes
                if gen2_scene.post_production_notes:
                    scene_post_production = PostProductionNotes(
                        speed_ramp=gen2_scene.post_production_notes.speed_ramp or "None",
                        color_grade=gen2_scene.post_production_notes.color_grade or "Match Scene 1",
                        loop_match=gen2_scene.post_production_notes.loop_match or gen2_scene.post_production_notes.loop_reference or "N/A",
                    )

                # First frame composition (Scene 1 only)
                if gen2_scene.first_frame_composition:
                    ffc = gen2_scene.first_frame_composition
                    scene_first_frame = FirstFrameCompositionGEN2(
                        hook_element=ffc.hook_element or "",
                        focal_point=ffc.focal_point or "",
                        foreground=ffc.foreground or "",
                        background=ffc.background or "",
                        scale_proof=ffc.scale_proof or "",
                        color_anchor=ffc.color_anchor or "",
                        safe_zone=ffc.safe_zone or "",
                        motion_visible=ffc.motion_visible or "",
                        scroll_stop=ffc.scroll_stop or "",
                    )

                # Scale techniques (exterior scenes)
                if gen2_scene.scale_techniques:
                    scene_scale_techniques = ScalesTechniques(
                        camera_angle=gen2_scene.scale_techniques.camera_angle or "",
                        atmospheric_depth=gen2_scene.scale_techniques.atmospheric_depth or "",
                        scale_indicators=gen2_scene.scale_techniques.scale_indicators or "",
                    )

                # Visual punctuation
                scene_visual_punctuation = gen2_scene.visual_punctuation

                # Easter egg integration
                if gen2_scene.easter_egg_integration:
                    eei = gen2_scene.easter_egg_integration
                    scene_easter_egg_integration = EasterEggIntegration(
                        object=eei.object or "",
                        placement_in_prompt=eei.placement_in_prompt or "",
                        visibility_check=eei.visibility_check or "",
                        integrated_in_image_prompt=getattr(eei, 'integrated_in_image_prompt', True),
                    )

            # Build full visual_concept from GEN1
            scene_visual_concept = VisualConcept(
                subject=gen1_scene.visual_concept.subject,
                environment=gen1_scene.visual_concept.environment,
                mood=gen1_scene.visual_concept.mood,
                key_elements=gen1_scene.visual_concept.key_elements,
                lighting_note=gen1_scene.visual_concept.lighting_note,
                motion_elements=gen1_scene.visual_concept.motion_elements,
            )

            # Build full camera_intent from GEN1
            scene_camera_intent = CameraIntent(
                movement=gen1_scene.camera_intent.movement,
                combo=gen1_scene.camera_intent.combo,
                framing=gen1_scene.camera_intent.framing,
                special=gen1_scene.camera_intent.special,
            )

            # Collect extra fields from GEN1 and GEN2 scenes
            # Remove keys that are already passed as explicit kwargs to avoid
            # "got multiple values for keyword argument" errors
            _explicit_keys = {
                'scene_number', 'scene_name', 'timestamp', 'duration_seconds',
                'voiceover', 'voiceover_segment', 'on_screen_text',
                'narrative_purpose', 'energy_level', 'visual_description',
                'camera_movement', 'motion_elements', 'broker_script',
                'visual_concept', 'camera_intent', 'audio_sfx', 'audio_moment',
                'image_prompt', 'video_prompt', 'reference_type', 'visual_tier', 'motion_intensity', 'video_tool',
                'status', 'inheritance', 'post_production_notes',
                'first_frame_composition', 'scale_techniques',
                'visual_punctuation', 'easter_egg_integration',
            }
            extra_kwargs = {}
            if gen1_scene.__pydantic_extra__:
                extra_kwargs.update({k: v for k, v in gen1_scene.__pydantic_extra__.items() if k not in _explicit_keys})
            if gen2_scene and gen2_scene.__pydantic_extra__:
                extra_kwargs.update({k: v for k, v in gen2_scene.__pydantic_extra__.items() if k not in _explicit_keys})

            glaze_scene = GlazeScene(
                scene_number=gen1_scene.scene_number,
                scene_name=gen1_scene.scene_name,
                timestamp=timestamp_str,
                duration_seconds=gen1_scene.duration_seconds,
                # Script & Text
                voiceover=gen1_scene.voiceover_segment,
                voiceover_segment=gen1_scene.voiceover_segment,
                on_screen_text=getattr(gen1_scene, 'on_screen_text', ''),
                narrative_purpose=gen1_scene.narrative_purpose,
                energy_level=gen1_scene.energy_level,
                # Visual (summary fields for quick access)
                visual_description=gen1_scene.visual_concept.subject,
                camera_movement=gen1_scene.camera_intent.movement,
                motion_elements=gen2_scene.motion_elements if gen2_scene else gen1_scene.visual_concept.motion_elements,
                # GEN1 full data (preserved for complete context)
                broker_script=gen1_scene.broker_script or "",
                visual_concept=scene_visual_concept,
                camera_intent=scene_camera_intent,
                # Audio
                audio_sfx=gen1_scene.audio_moment,
                audio_moment=gen1_scene.audio_moment,
                # From GEN2
                image_prompt=gen2_scene.image_prompt if gen2_scene else "",
                video_prompt=gen2_scene.video_prompt if gen2_scene else "",
                reference_type=gen2_scene.reference_type if gen2_scene else "INDEPENDENT",
                visual_tier=gen2_scene.visual_tier if gen2_scene else None,
                motion_intensity=gen2_scene.motion_intensity if gen2_scene else None,
                video_tool="KLING",
                # Status
                status="pending",
                # GEN2 metadata
                inheritance=scene_inheritance,
                post_production_notes=scene_post_production,
                first_frame_composition=scene_first_frame,
                scale_techniques=scene_scale_techniques,
                visual_punctuation=scene_visual_punctuation,
                easter_egg_integration=scene_easter_egg_integration,
                **extra_kwargs,  # Forward undeclared fields from GEN1/GEN2 scenes
            )
            glaze_scenes.append(glaze_scene)
            current_timestamp += gen1_scene.duration_seconds

        # Build final project with all required fields from GEN1
        total_duration = sum(s.duration_seconds for s in glaze_scenes)
        youtube_title = (gen1.youtube.title if gen1.youtube else None) or gen1.youtube_title or gen1.metadata.title or "Glaze City Property"

        # Find easter egg scene in GEN2 to get placement_in_prompt for safe_zone_position
        gen2_placement_in_prompt = ""
        if gen1.engagement.easter_egg and gen1.engagement.easter_egg.scene_number:
            easter_egg_scene_num = gen1.engagement.easter_egg.scene_number
            gen2_easter_egg_scene = gen2_scenes.get(easter_egg_scene_num)
            if gen2_easter_egg_scene and gen2_easter_egg_scene.easter_egg_integration:
                gen2_placement_in_prompt = gen2_easter_egg_scene.easter_egg_integration.placement_in_prompt or ""

        # Build full audio data from GEN1
        sonic_hook_data = None
        foley_palette_data = None
        sfx_per_scene_data: List[SceneSFXAssignment] = []

        if gen1.audio:
            # Sonic hook
            if gen1.audio.sonic_hook:
                sonic_hook_data = SonicHook(
                    type=gen1.audio.sonic_hook.type,
                    timing=gen1.audio.sonic_hook.timing,
                    description=gen1.audio.sonic_hook.description,
                    volume=gen1.audio.sonic_hook.volume,
                )

            # Foley palette
            if gen1.audio.foley_palette:
                # Get primary_sounds: prefer sounds[].id, fallback to primary_sounds
                if gen1.audio.foley_palette.sounds:
                    primary = [getattr(s, 'id', '') for s in gen1.audio.foley_palette.sounds if getattr(s, 'id', None)]
                    search_from_sounds = [getattr(s, 'search', '') for s in gen1.audio.foley_palette.sounds if getattr(s, 'search', None)]
                else:
                    primary = gen1.audio.foley_palette.primary_sounds or []
                    search_from_sounds = []

                # MERGE both search sources: sounds[].search + search_terms (deduplicated)
                search_terms_list = gen1.audio.foley_palette.search_terms or []
                merged_search = list(dict.fromkeys(search_from_sounds + search_terms_list))  # preserves order, removes dupes
                search = merged_search if merged_search else primary  # fallback to primary if no search terms

                foley_palette_data = FoleyPalette(
                    primary_sounds=primary,
                    search_terms=search,
                    scene_assignments=gen1.audio.foley_palette.scene_assignments or {},
                )

            # SFX per scene
            if gen1.audio.sfx_per_scene:
                for sfx_scene in gen1.audio.sfx_per_scene:
                    sfx_items = [
                        SceneSFX(
                            type=getattr(item, 'type', 'EFFECT'),
                            timing=getattr(item, 'timing', '0.0s'),
                            description=getattr(item, 'description', ''),
                            volume=getattr(item, 'volume', 'MEDIUM'),
                        )
                        for item in sfx_scene.sfx
                    ]
                    sfx_per_scene_data.append(SceneSFXAssignment(
                        scene=sfx_scene.scene,
                        sfx=sfx_items,
                    ))

        # Build share_trigger from GEN1
        share_trigger_data = None
        if gen1.engagement.share_trigger:
            share_trigger_data = ShareTrigger(
                text=gen1.engagement.share_trigger.text,
                placement=gen1.engagement.share_trigger.placement,
            )

        # Build visual_summary from GEN2
        visual_summary_data = None
        if gen2.visual_summary:
            loop_verification_data = None
            if gen2.visual_summary.loop_verification:
                loop_verification_data = LoopVerification(
                    scene1_camera_movement=gen2.visual_summary.loop_verification.scene1_camera_movement or "",
                    sceneN_camera_movement=gen2.visual_summary.loop_verification.sceneN_camera_movement or "",
                    movements_are_different=gen2.visual_summary.loop_verification.movements_are_different if gen2.visual_summary.loop_verification.movements_are_different is not None else True,
                    sceneN_after_reverse=gen2.visual_summary.loop_verification.sceneN_after_reverse or "",
                    scene1_foreground=gen2.visual_summary.loop_verification.scene1_foreground or "",
                    sceneN_foreground=gen2.visual_summary.loop_verification.sceneN_foreground or "",
                    foreground_match=gen2.visual_summary.loop_verification.foreground_match if gen2.visual_summary.loop_verification.foreground_match is not None else True,
                    scene1_lighting=gen2.visual_summary.loop_verification.scene1_lighting or "",
                    sceneN_lighting=gen2.visual_summary.loop_verification.sceneN_lighting or "",
                    lighting_match=gen2.visual_summary.loop_verification.lighting_match if gen2.visual_summary.loop_verification.lighting_match is not None else True,
                    same_reference_image=gen2.visual_summary.loop_verification.same_reference_image if gen2.visual_summary.loop_verification.same_reference_image is not None else True,
                    loop_ready=gen2.visual_summary.loop_verification.loop_ready if gen2.visual_summary.loop_verification.loop_ready is not None else True,
                )

            visual_summary_data = VisualSummary(
                total_scenes=len(gen1.scenes),  # authoritative: actual scene count from GEN1
                gigantism_protocol=gen2.visual_summary.gigantism_protocol or "APPLIED",
                reference_breakdown=gen2.visual_summary.reference_breakdown or {},
                scale_techniques_used=gen2.visual_summary.scale_techniques_used or [],
                lighting_continuity=gen2.visual_summary.lighting_continuity or "",
                foreground_scenes=gen2.visual_summary.foreground_scenes or [],
                motion_summary=gen2.visual_summary.motion_summary or "",
                energy_pattern=gen2.visual_summary.energy_pattern or "",
                motion_enforcement=gen2.visual_summary.motion_enforcement or "",
                loop_verified=gen2.visual_summary.loop_verified if gen2.visual_summary.loop_verified is not None else True,
                banned_words_checked=gen2.visual_summary.banned_words_checked if gen2.visual_summary.banned_words_checked is not None else True,
                loop_verification=loop_verification_data,
            )

        project = GlazeCityProject(
            property=PropertyBrief(
                name=gen1.property.name,
                location=gen1.property.location,
                price=gen1.property.price or "$0",
                price_numeric=self._parse_price_numeric(gen1.property.price or ""),
                food_material=FoodMaterial(
                    primary=gen1.food_identity.primary_food,
                    secondary=gen1.food_identity.texture_keywords[:2] if gen1.food_identity.texture_keywords else [],
                ),
                specs=PropertySpecs(
                    bedrooms=0,
                    bathrooms=0,
                    sqft=0,
                    unique_feature=gen1.property.tagline,
                ),
            ),
            hook=HookStrategy(
                type=gen1.hook.type,
                psychological_trigger=gen1.hook.psychological_trigger,
                first_frame_visual=gen1.hook.first_frame_visual,
                first_words=gen1.hook.first_words,
                complete_hook_vo=gen1.hook.complete_hook_vo,
                scroll_stop_element=gen1.hook.scroll_stop_element,
                opening_line=gen1.hook.first_words,  # legacy alias
                visual_hook=gen1.hook.first_frame_visual,  # legacy alias
                audio_hook=gen1.hook.complete_hook_vo,  # legacy alias
                scene_1_entry_type=getattr(gen1.hook, 'scene_1_entry_type', 'MACRO_ENTRY'),
            ),
            psychology=Psychology(
                triggers=[gen1.hook.psychological_trigger],
                reasoning=f"Using {gen1.hook.psychological_trigger} trigger from hook strategy",
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
                    # Additional fields required by FoodDNA (not in Gen1FoodDNA)
                    chimney_becomes=getattr(gen1.food_identity.food_dna, 'chimney_becomes', f"{gen1.food_identity.primary_food} stack"),
                    stairs_become=getattr(gen1.food_identity.food_dna, 'stairs_become', f"Layered {gen1.food_identity.primary_food} steps"),
                    fence_becomes=getattr(gen1.food_identity.food_dna, 'fence_becomes', f"{gen1.food_identity.primary_food} railing"),
                    landscaping_becomes=getattr(gen1.food_identity.food_dna, 'landscaping_becomes', f"{gen1.food_identity.primary_food} garden"),
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
            # Foreground element from GEN1 (optional but important for visual consistency)
            foreground_element=ForegroundElement(
                type=gen1.foreground_element.type,
                prompt_snippet=gen1.foreground_element.prompt_snippet,
            ) if gen1.foreground_element else None,
            # Atmosphere mode
            atmosphere_mode=gen1.atmosphere_mode or "CINEMATIC",
            # Hook Matrix
            hook_matrix=HookMatrix(
                selected_style=gen1.hook.type,
                style_reason=f"Selected for {gen1.hook.psychological_trigger} trigger",
                avoid_styles=[],
            ),
            # Easter egg with all required fields (safe_zone_position from GEN2 if available)
            # v8.0.0: easter_egg may be None (replaced by replay_hooks)
            easter_egg=EasterEgg(
                object=gen1.engagement.easter_egg.object if gen1.engagement.easter_egg else "",
                scene_number=gen1.engagement.easter_egg.scene_number if gen1.engagement.easter_egg else 0,
                placement=gen1.engagement.easter_egg.placement if gen1.engagement.easter_egg else "",
                visibility=gen1.engagement.easter_egg.visibility if gen1.engagement.easter_egg else "FINDABLE",
                comment_bait=gen1.engagement.easter_egg.comment_bait if gen1.engagement.easter_egg else "",
                validation_check=gen1.engagement.easter_egg.validation_check if gen1.engagement.easter_egg else "",
                format=(gen1.engagement.easter_egg.format if gen1.engagement.easter_egg else "VISUAL") or "VISUAL",
                audio_hint=(gen1.engagement.easter_egg.audio_hint if gen1.engagement.easter_egg else "") or "",
                safe_zone_position=self._parse_safe_zone_from_placement(
                    gen1.engagement.easter_egg.placement if gen1.engagement.easter_egg else "",
                    gen1.engagement.easter_egg.validation_check if gen1.engagement.easter_egg else "",
                    gen2_placement_in_prompt,
                ) if gen1.engagement.easter_egg else "center-left",
                visibility_score=self._parse_visibility_score(gen1.engagement.easter_egg.visibility) if gen1.engagement.easter_egg else 0.7,
            ),
            loop=self._build_loop_config(gen1),
            scenes=glaze_scenes,
            voiceover=VoiceoverConfig(
                settings=VoiceoverSettings(
                    voice_id=gen1.voiceover.voice_id,
                    stability=gen1.voiceover.stability,
                    similarity_boost=gen1.voiceover.similarity_boost,
                    style=gen1.voiceover.style if hasattr(gen1.voiceover, 'style') else 0.30,
                    speaker_boost=gen1.voiceover.speaker_boost if hasattr(gen1.voiceover, 'speaker_boost') else True,
                ),
                full_script=gen1.voiceover.full_script,
                character=gen1.voiceover.character if hasattr(gen1.voiceover, 'character') else "sensory_witness",
                model=gen1.voiceover.model if hasattr(gen1.voiceover, 'model') else "eleven_v3",
                total_duration_seconds=gen1.metadata.target_duration_seconds,
            ),
            # Audio with all required fields (including full GEN1 audio data)
            audio=AudioConfig(
                background_music=BackgroundMusic(
                    genre="cinematic",
                    style="epic orchestral",
                    bpm=self._parse_bpm_from_suno_prompt(gen1.audio.suno_prompt if gen1.audio else ""),
                    mood="epic",
                    duration_seconds=gen1.metadata.target_duration_seconds,
                    reference=gen1.audio.suno_prompt if gen1.audio else "",
                ),
                sfx=[],  # Empty list, SFX are in sfx_per_scene
                sonic_hook=sonic_hook_data,
                foley_palette=foley_palette_data,
                sfx_per_scene=sfx_per_scene_data,
            ),
            # Publish config for multi-channel support
            publish_config=PublishConfig(
                target_channel=getattr(gen1.publish_config, 'target_channel', "glaze_city") if gen1.publish_config else "glaze_city"
            ),
            youtube=ViralMetadata(
                title=(gen1.youtube.title if gen1.youtube else None) or gen1.youtube_title or gen1.metadata.title or "Glaze City Property",
                description=(gen1.youtube.description if gen1.youtube else None) or gen1.youtube_description or gen1.metadata.title or "Glaze City",
                pinned_comment=(gen1.youtube.pinned_comment if gen1.youtube and gen1.youtube.pinned_comment is not None else None) if gen1.youtube else gen1.youtube_pinned_comment if gen1.youtube_pinned_comment is not None else (gen1.engagement.easter_egg.comment_bait if gen1.engagement.easter_egg else ""),
                hashtags=gen1.youtube_hashtags or gen1.engagement.hashtags or [],
                tags=(gen1.youtube.tags if gen1.youtube else None) or gen1.youtube_tags or [],
            ),
            # Viral audit with scores from GEN1 viral_assessment
            viral_audit=ViralAudit(
                scores=ViralAuditScores(
                    hook_strength=AuditScore(
                        score=self._convert_viral_score(gen1.viral_assessment.hook_strength),
                        reason=gen1.viral_assessment.strength_points[0] if gen1.viral_assessment.strength_points else "Strong visual hook"
                    ),
                    retention_architecture=AuditScore(
                        score=self._convert_viral_score(gen1.viral_assessment.visual_uniqueness),
                        reason="Unique visual style" if gen1.viral_assessment.visual_uniqueness > 0.6 else "Standard visual approach"
                    ),
                    loop_quality=AuditScore(
                        score=self._convert_viral_score(gen1.viral_assessment.shareability),
                        reason="Highly shareable content" if gen1.viral_assessment.shareability > 0.6 else "Moderate shareability"
                    ),
                    psychological_triggers=AuditScore(
                        score=self._convert_viral_score(gen1.viral_assessment.comment_potential),
                        reason=f"Uses {gen1.hook.psychological_trigger} trigger"
                    ),
                    easter_egg_appeal=AuditScore(
                        score=self._convert_viral_score(gen1.viral_assessment.humor_quotient),
                        reason="Engaging easter egg with humor" if gen1.viral_assessment.humor_quotient > 0.5 else "Subtle easter egg"
                    ),
                    brand_fit=AuditScore(
                        score=self._convert_viral_score(gen1.viral_assessment.overall_score),
                        reason="Matches Glaze City style"
                    ),
                    # v8.3.0 qualitative verdicts → AuditScore (verdict string as reason)
                    mute_test=AuditScore(
                        score=8, reason=gen1.viral_assessment.mute_test_verdict
                    ) if gen1.viral_assessment.mute_test_verdict else None,
                    categorization_clarity=AuditScore(
                        score=8, reason=gen1.viral_assessment.categorization_verdict
                    ) if gen1.viral_assessment.categorization_verdict else None,
                    niche_alignment=AuditScore(
                        score=8, reason=gen1.viral_assessment.niche_alignment_verdict
                    ) if gen1.viral_assessment.niche_alignment_verdict else None,
                ),
                total_score=int(gen1.viral_assessment.overall_score * 60) + (
                    24 if gen1.viral_assessment.mute_test_verdict else 0  # 3×8 for qualitative verdicts
                ),
                max_score=60 + (
                    30 if gen1.viral_assessment.mute_test_verdict else 0  # 3×10
                ),
                viral_probability=self._get_viral_probability(gen1.viral_assessment.overall_score),
                viral_reasoning="; ".join(gen1.viral_assessment.strength_points[:2]) if gen1.viral_assessment.strength_points else "Strong hook combined with engaging visuals",
                weak_points=gen1.viral_assessment.weak_points or [],
                strength_points=gen1.viral_assessment.strength_points or [],
            ),
            # Series info with all required fields
            series=SeriesInfo(
                category=gen1.metadata.concept.category if gen1.metadata.concept else "LANDMARKS",
                sequel_ideas=["Follow-up property tour", "Behind the scenes"],
            ),
            # Meta with all required fields
            meta=ProjectMeta(
                total_scenes=len(gen1.scenes),  # authoritative: GEN1 scene count
                total_duration_seconds=sum(s.duration_seconds for s in glaze_scenes),
                generated_at=datetime.now().isoformat(),
            ),
            # Warning line for AERIAL (N-1) scene
            warning_line=gen1.warning_line or "",
            # Replay hooks (v8.0.0+)
            replay_hooks=[rh.model_dump() for rh in gen1.engagement.replay_hooks] if gen1.engagement.replay_hooks else [],
            # Metadata variants A/B/C/D (v8.2.0+)
            metadata_variants=gen1.metadata_variants.model_dump() if gen1.metadata_variants else None,
            project_id=project_id,
            created_at=datetime.now(),
            # RAW PRESERVATION - Повні GEN1/GEN2 без втрат
            gen1_raw=gen1.model_dump(),
            gen2_raw=gen2.model_dump(),
            # Additional data from GEN1 and GEN2
            share_trigger=share_trigger_data,
            visual_summary=visual_summary_data,
            # GEN1 Metadata (version, status, title, concept) - for brief completeness
            gen1_metadata=ProjectMetadata(
                version=gen1.metadata.version,
                status=gen1.metadata.status,
                title=gen1.metadata.title,
                concept=ProjectConcept(
                    category=gen1.metadata.concept.category,
                    subject=gen1.metadata.concept.subject,
                    food_material=gen1.metadata.concept.food_material,
                    architectural_style=gen1.metadata.concept.architectural_style,
                    originality_note=gen1.metadata.concept.originality_note,
                ) if gen1.metadata.concept else None,
                target_duration_seconds=gen1.metadata.target_duration_seconds,
                scene_count=gen1.metadata.scene_count,
            ),
            # GEN2 Global Settings - negative_prompt CRITICAL for image generation
            negative_prompt=gen2.global_settings.negative_prompt if gen2.global_settings else "tilt-shift, miniature, diorama, toy, cartoon, anime, illustration, drawing, painting, sketch",
        )

        # Log merge summary
        logger.info("=" * 70)
        logger.success(f"[MERGE] Created project: {project.property.name}")
        logger.info(f"  Scenes: {len(project.scenes)}")
        logger.info(f"  Duration: {project.meta.total_duration_seconds}s")

        # Log and check merge issues
        if merge_issues:
            logger.warning(f"[MERGE] Issues found ({len(merge_issues)}):")
            for issue in merge_issues:
                logger.warning(f"  - {issue}")
            # Critical: any scene missing prompts means image gen will fail
            critical_issues = [i for i in merge_issues if "no GEN2 data" in i or "missing image_prompt" in i]
            if critical_issues:
                logger.error(f"[MERGE] {len(critical_issues)} critical merge issues — image generation will fail for these scenes")
        else:
            logger.success("[MERGE] All fields merged successfully!")

        # Verify critical fields in final project
        for i, scene in enumerate(project.scenes):
            scene_num = scene.scene_number
            missing = []
            if not scene.image_prompt:
                missing.append("image_prompt")
            if not scene.video_prompt:
                missing.append("video_prompt")
            if not scene.visual_concept:
                missing.append("visual_concept")
            if not scene.camera_intent:
                missing.append("camera_intent")

            if missing:
                logger.error(f"[MERGE] Scene {scene_num} MISSING: {missing}")
            else:
                logger.info(f"[MERGE] Scene {scene_num}: OK (image_prompt={len(scene.image_prompt)}ch, video_prompt={len(scene.video_prompt)}ch)")

        logger.info("=" * 70)

        return project

    def validate_merged_brief(self, project: GlazeCityProject) -> Tuple[bool, List[str]]:
        """
        Validate that merged brief has ALL required fields.

        This function checks for missing fields that may be lost during merge.
        Per user request: if any field is missing, merge should be retried.

        Returns:
            Tuple of (is_valid, list of missing/empty fields)
        """
        missing_fields = []

        # ===== GEN1 METADATA VALIDATION =====
        if not project.gen1_metadata:
            missing_fields.append("gen1_metadata")
        else:
            if not project.gen1_metadata.version:
                missing_fields.append("gen1_metadata.version")
            if not project.gen1_metadata.status:
                missing_fields.append("gen1_metadata.status")
            if not project.gen1_metadata.title:
                missing_fields.append("gen1_metadata.title")
            if not project.gen1_metadata.concept:
                missing_fields.append("gen1_metadata.concept")
            elif project.gen1_metadata.concept:
                if not project.gen1_metadata.concept.category:
                    missing_fields.append("gen1_metadata.concept.category")
                if not project.gen1_metadata.concept.subject:
                    missing_fields.append("gen1_metadata.concept.subject")
                if not project.gen1_metadata.concept.food_material:
                    missing_fields.append("gen1_metadata.concept.food_material")

        # ===== NEGATIVE PROMPT VALIDATION (CRITICAL) =====
        if not project.negative_prompt:
            missing_fields.append("negative_prompt (CRITICAL for image quality)")

        # ===== PROPERTY VALIDATION =====
        if not project.property.name:
            missing_fields.append("property.name")

        # ===== ARCHITECTURAL IDENTITY VALIDATION =====
        if not project.architectural_identity.style_code:
            missing_fields.append("architectural_identity.style_code")
        if not project.architectural_identity.style_description:
            missing_fields.append("architectural_identity.style_description")

        # ===== FOOD IDENTITY VALIDATION =====
        if not project.food_identity.primary_food:
            missing_fields.append("food_identity.primary_food")
        if not project.food_identity.food_dna.walls_become:
            missing_fields.append("food_identity.food_dna.walls_become")

        # ===== LIGHTING MASTER VALIDATION =====
        if not project.lighting_master.preset:
            missing_fields.append("lighting_master.preset")
        if not project.lighting_master.prompt_snippet:
            missing_fields.append("lighting_master.prompt_snippet")

        # ===== HOOK VALIDATION =====
        if not project.hook.type:
            missing_fields.append("hook.type")
        if not project.hook.psychological_trigger:
            missing_fields.append("hook.psychological_trigger")

        # ===== YOUTUBE VALIDATION =====
        if not project.youtube.title:
            missing_fields.append("youtube.title")
        if not project.youtube.description:
            missing_fields.append("youtube.description")

        # ===== VOICEOVER VALIDATION =====
        if not project.voiceover.full_script:
            missing_fields.append("voiceover.full_script")

        # ===== SCENES VALIDATION =====
        if len(project.scenes) < 6 or len(project.scenes) > 10:
            missing_fields.append(f"scenes (expected 6-10, got {len(project.scenes)})")

        for scene in project.scenes:
            if not scene.image_prompt:
                missing_fields.append(f"scene_{scene.scene_number}.image_prompt")
            if not scene.video_prompt:
                missing_fields.append(f"scene_{scene.scene_number}.video_prompt")
            if not scene.visual_concept:
                missing_fields.append(f"scene_{scene.scene_number}.visual_concept")

        # ===== EASTER EGG VALIDATION (optional in v8.0.0) =====
        # easter_egg may be empty when GEN1 v8.0.0 uses replay_hooks instead

        is_valid = len(missing_fields) == 0

        if is_valid:
            logger.success("[VALIDATE_BRIEF] All required fields present!")
        else:
            logger.warning(f"[VALIDATE_BRIEF] Missing {len(missing_fields)} fields:")
            for field in missing_fields:
                logger.warning(f"  ❌ {field}")

        return (is_valid, missing_fields)

    # =========================================================================
    # FULL PIPELINE: GEN1 -> Delivery -> GEN2 -> Merge
    # =========================================================================

    async def generate_full_project(
        self,
        topic: Optional[str] = None,
        num_scenes: int = 8,
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
            num_scenes: Number of scenes (6-10, GEN1 v6 dynamic engine decides)
            style: Visual style
            target_audience: Target audience
            duration_seconds: Total duration
            project_id: Optional project ID
            skip_validation: If True, skip VAL_GEN1 and VAL_GEN2 (for testing)

        Returns:
            Complete GlazeCityProject with all prompts
        """
        logger.info("=" * 70)
        logger.info("STARTING TWO-STAGE GENERATION PIPELINE v3.0 (dynamic scenes)")
        logger.info("=" * 70)

        # Generate project_id if not provided
        if not project_id:
            project_id = f"proj_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # =====================================================================
        # STAGE 1: GEN1 with VAL_GEN1 validation (max 3 retries)
        # =====================================================================
        gen1_output: Optional[Gen1Output] = None
        gen1_validated = False
        last_retry_guidance: Optional[List[str]] = None

        for attempt in range(1, MAX_VALIDATION_RETRIES + 1):
            logger.info(f"\n[STAGE 1] Running GEN1 (attempt {attempt}/{MAX_VALIDATION_RETRIES})...")

            gen1_output = await self.run_gen1(
                topic=topic,
                num_scenes=num_scenes,
                style=style,
                target_audience=target_audience,
                duration_seconds=duration_seconds,
                project_id=project_id,
                retry_guidance=last_retry_guidance,
            )

            if not gen1_output:
                logger.error(f"[GEN1] Generation failed (attempt {attempt})")
                # Capture parse error for retry guidance so Gemini knows what to fix
                parse_err = self._last_gen1_parse_error
                if parse_err:
                    last_retry_guidance = [f"JSON PARSE ERROR: {parse_err}", "Ensure ALL required fields are present and valid"]
                    self._last_gen1_parse_error = None
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
                    last_retry_guidance = val_result.retry_guidance.fixes_needed
                    logger.info(f"  Retry guidance: {last_retry_guidance}")
                if attempt < MAX_VALIDATION_RETRIES:
                    logger.info("Retrying GEN1 with validation feedback...")

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
        last_gen2_retry_guidance: Optional[List[str]] = None

        for attempt in range(1, MAX_VALIDATION_RETRIES + 1):
            logger.info(f"\n[STAGE 2] Running GEN2 (attempt {attempt}/{MAX_VALIDATION_RETRIES})...")

            gen2_output = await self.run_gen2(payload, project_id, last_gen2_retry_guidance)

            if not gen2_output:
                logger.error(f"[GEN2] Generation failed (attempt {attempt})")
                # If truncation was detected, add it to retry guidance
                if self._last_gen2_truncated:
                    expected = len(payload.scenes)
                    logger.warning(f"[GEN2] Previous attempt was TRUNCATED or had scene count mismatch (expected {expected} scenes)")
                    truncation_guidance = [
                        "CRITICAL: Your previous response was TRUNCATED or had WRONG scene count",
                        f"You MUST output EXACTLY {expected} scenes (matching GEN1 scene_count)",
                        "Be MORE CONCISE - shorter image_prompt and video_prompt",
                        "Do NOT add extra fields or verbose descriptions"
                    ]
                    if last_gen2_retry_guidance:
                        last_gen2_retry_guidance = truncation_guidance + last_gen2_retry_guidance
                    else:
                        last_gen2_retry_guidance = truncation_guidance
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
                    last_gen2_retry_guidance = val_result.retry_guidance.fixes_needed
                    logger.info(f"  Retry guidance: {last_gen2_retry_guidance}")
                failed_scenes = val_result.get_failed_scenes() if val_result else []
                if failed_scenes:
                    logger.info(f"  Failed scenes: {failed_scenes}")
                if attempt < MAX_VALIDATION_RETRIES:
                    logger.info("Retrying GEN2 with validation feedback...")

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
            logger.warning(f"JSON parse error: {e} — attempting repair")
            # Try to repair truncated JSON by closing unclosed brackets/braces
            repaired = self._repair_truncated_json(json_str)
            if repaired is not None:
                try:
                    result = json.loads(repaired)
                    logger.info(f"JSON repair succeeded (added closing delimiters)")
                    return result
                except json.JSONDecodeError:
                    pass
            # Repair failed — log diagnostics
            logger.error(f"JSON parse error (repair failed): {e}")
            error_pos = e.pos if hasattr(e, 'pos') else 0
            start_ctx = max(0, error_pos - 100)
            end_ctx = min(len(json_str), error_pos + 100)
            context = json_str[start_ctx:end_ctx]
            logger.error(f"Error context (chars {start_ctx}-{end_ctx}):\n{context}")
            logger.error(f"Full JSON length: {len(json_str)} chars")
            logger.warning(f"JSON start: {json_str[:500]}...")
            return None

    @staticmethod
    def _repair_truncated_json(json_str: str) -> Optional[str]:
        """Attempt to repair truncated JSON by closing unclosed brackets/braces.

        Handles Gemini responses that get cut off mid-output due to
        max_output_tokens or safety filters.
        """
        # Strip trailing whitespace and incomplete tokens
        s = json_str.rstrip()
        # Remove trailing comma (common at truncation point)
        if s.endswith(','):
            s = s[:-1]
        # Remove truncated string value (unclosed quote)
        # Count quotes — if odd, truncation happened inside a string
        if s.count('"') % 2 == 1:
            # Find last quote and trim everything after it
            last_quote = s.rfind('"')
            # Check if it's a key or value by looking for preceding colon
            before = s[:last_quote].rstrip()
            if before.endswith(':'):
                # Truncated at start of value — add placeholder and close
                s = s[:last_quote + 1] + '...'  + '"'
            else:
                # Truncated inside a value — close the string
                s = s[:last_quote + 1]
            # Remove trailing comma after our fix
            s = s.rstrip().rstrip(',')

        # Count unclosed delimiters
        stack = []
        in_string = False
        escape_next = False
        for ch in s:
            if escape_next:
                escape_next = False
                continue
            if ch == '\\' and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch in ('{', '['):
                stack.append(ch)
            elif ch == '}':
                if stack and stack[-1] == '{':
                    stack.pop()
            elif ch == ']':
                if stack and stack[-1] == '[':
                    stack.pop()

        if not stack:
            return s if s != json_str else None  # Nothing to repair

        # Close unclosed delimiters in reverse order
        for opener in reversed(stack):
            s += '}' if opener == '{' else ']'

        return s

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
