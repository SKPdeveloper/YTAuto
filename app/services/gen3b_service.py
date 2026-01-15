"""
GEN3b Service - FFmpeg Manifest Generator v1.3.1

Трансформує аналіз GEN3a в production-ready manifest.json для FFmpeg.
Приймає креативні рішення про ефекти, субтитри та audio mixing.

Features:
- Hook style selection from variety pool
- Content-aware effect selection
- Subtitle style animations
- Beat-aligned cut recommendations
- 5-layer audio plan
- FFmpeg-ready manifest generation
"""

import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

from google import genai
from google.genai import types

from app.core.config import settings
from app.utils.logger import logger
from app.services.gen_models import (
    Gen3aOutput,
    Gen3bManifest,
    ManifestScene,
    ManifestEffect,
    ManifestCut,
    ManifestSubtitle,
    ManifestAudioLayers,
    ManifestAudioLayer,
    ManifestSFXEvent,
    HookSection,
    SpeedSegment,
)


# System prompt path
GEN3B_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "GEN3b.txt"


class Gen3bService:
    """
    GEN3b - The Artist v1.3.1

    Transforms GEN3a analysis into creative editing decisions
    and generates production-ready manifest.json for FFmpeg.
    """

    def __init__(self):
        """Initialize GEN3b service with Gemini client."""
        self.client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY)
        self.model_name = settings.CONTENTBRAIN_MODEL
        self.system_prompt = self._load_system_prompt()

        # Generation config for creative decisions
        self.config = types.GenerateContentConfig(
            system_instruction=self.system_prompt,
            temperature=0.5,  # Higher for creative decisions
            top_p=0.95,
            max_output_tokens=16384,
        )

        logger.info("GEN3b Service initialized:")
        logger.info(f"  Model: {self.model_name}")
        logger.info(f"  System prompt: GEN3b v1.3.1")

    def _load_system_prompt(self) -> str:
        """Load GEN3b system prompt."""
        if not GEN3B_PROMPT_PATH.exists():
            logger.warning(f"GEN3b prompt not found: {GEN3B_PROMPT_PATH}")
            return self._get_fallback_prompt()

        with open(GEN3B_PROMPT_PATH, "r", encoding="utf-8") as f:
            prompt = f.read()

        logger.success(f"Loaded GEN3b system prompt: {GEN3B_PROMPT_PATH.name}")
        return prompt

    def _get_fallback_prompt(self) -> str:
        """Fallback prompt if config file missing."""
        return """You are GEN3b - The Artist v1.3.1.
Transform video analysis into FFmpeg manifest with:
- hook: style selection and effects
- scenes: speed segments, effects, cuts
- audio_layers: 5-layer audio plan
- subtitles: styled text with animations
Return ONLY valid JSON."""

    async def generate_manifest(
        self,
        gen3a_analysis: Gen3aOutput,
        gen1_brief: Dict[str, Any],
        gen2_brief: Dict[str, Any],
    ) -> Gen3bManifest:
        """
        Generate FFmpeg manifest from GEN3a analysis.

        Args:
            gen3a_analysis: Complete analysis from GEN3a
            gen1_brief: GEN1 output (story, voiceover, audio plan)
            gen2_brief: GEN2 output (visual prompts, scene intentions)

        Returns:
            Gen3bManifest ready for FFmpeg rendering
        """
        logger.info("=" * 60)
        logger.info("GEN3b: Generating FFmpeg Manifest")
        logger.info("=" * 60)
        logger.info(f"  Scenes: {len(gen3a_analysis.scenes)}")
        logger.info(f"  Recommended hook style: {gen3a_analysis.hook_variety_analysis.recommended_style}")

        try:
            # Build generation request
            request_content = self._build_manifest_request(
                gen3a_analysis=gen3a_analysis,
                gen1_brief=gen1_brief,
                gen2_brief=gen2_brief,
            )

            # Generate manifest
            logger.info("Sending to Gemini for manifest generation...")
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=request_content,
                config=self.config,
            )

            # Parse response
            raw_output = response.text
            logger.info(f"Received response: {len(raw_output)} characters")

            # Extract JSON
            manifest_data = self._parse_json_response(raw_output)

            # Convert to Gen3bManifest
            manifest = self._convert_to_manifest(manifest_data, gen3a_analysis)

            logger.success("=" * 60)
            logger.success("GEN3b: Manifest Generated")
            logger.success(f"  Total duration: {manifest.total_duration}s")
            logger.success(f"  Hook style: {manifest.hook.style}")
            logger.success(f"  Subtitles: {len(manifest.subtitles)}")
            logger.success("=" * 60)

            return manifest

        except Exception as e:
            logger.error(f"GEN3b manifest generation failed: {e}")
            raise

    def _build_manifest_request(
        self,
        gen3a_analysis: Gen3aOutput,
        gen1_brief: Dict[str, Any],
        gen2_brief: Dict[str, Any],
    ) -> str:
        """Build the manifest generation request."""
        # Convert Gen3aOutput to dict for JSON serialization
        analysis_dict = gen3a_analysis.model_dump()

        request = f"""GENERATE FFMPEG MANIFEST from the analysis.

## INPUT DATA

### gen1_brief.json:
```json
{json.dumps(gen1_brief, indent=2, ensure_ascii=False)}
```

### gen2_brief.json:
```json
{json.dumps(gen2_brief, indent=2, ensure_ascii=False)}
```

### gen3a_analysis.json:
```json
{json.dumps(analysis_dict, indent=2, ensure_ascii=False)}
```

## YOUR TASK

Create production-ready manifest.json with:

1. **HOOK SELECTION**: Use recommended_style from gen3a or select alternative with justification
2. **SCENE PROCESSING**: Transform each scene with:
   - speed_segments from gen3a
   - effects based on visual_classification
   - cuts for glitch removal
3. **SUBTITLES**: Create styled subtitles from VO segments
   - Apply style based on VO tags
   - Position in safe zone (NOT bottom 20%)
   - Add animations
4. **AUDIO LAYERS**: Plan 5-layer audio:
   - BED: ambient bed
   - MUSIC: background music
   - SFX: impact sounds at transitions
   - FOLEY: food sounds
   - VO: voiceover (highest priority)
5. **GLOBAL EFFECTS**: Add any video-wide effects

Return ONLY valid JSON matching the Gen3bManifest schema.
Start with {{ and end with }}
NO markdown formatting."""

        return request

    def _parse_json_response(self, response_text: str) -> Dict[str, Any]:
        """Parse JSON from Gemini response."""
        import re

        text = response_text.strip()

        # Remove markdown code blocks if present
        if text.startswith("```"):
            pattern = r"```(?:json)?\s*\n?(.*?)\n?```"
            match = re.search(pattern, text, re.DOTALL)
            if match:
                text = match.group(1).strip()

        # Find JSON object
        start = text.find("{")
        end = text.rfind("}") + 1

        if start >= 0 and end > start:
            text = text[start:end]

        return json.loads(text)

    def _convert_to_manifest(
        self,
        data: Dict[str, Any],
        gen3a_analysis: Gen3aOutput,
    ) -> Gen3bManifest:
        """Convert parsed JSON to Gen3bManifest model."""
        # Parse hook section
        hook_data = data.get("hook", {})
        hook = HookSection(
            style=hook_data.get("style", gen3a_analysis.hook_variety_analysis.recommended_style),
            duration=hook_data.get("duration", 0.3),
            effects=[ManifestEffect(**e) for e in hook_data.get("effects", [])],
            sfx=hook_data.get("sfx", ""),
        )

        # Parse scenes
        scenes = []
        for scene_data in data.get("scenes", []):
            scene = ManifestScene(
                scene_number=scene_data.get("scene_number", 0),
                source_file=scene_data.get("source_file", ""),
                timeline_start=scene_data.get("timeline_start", 0.0),
                timeline_end=scene_data.get("timeline_end", 0.0),
                speed_segments=[
                    SpeedSegment(**ss) for ss in scene_data.get("speed_segments", [])
                ],
                effects=[
                    ManifestEffect(**e) for e in scene_data.get("effects", [])
                ],
                cuts=[
                    ManifestCut(**c) for c in scene_data.get("cuts", [])
                ],
            )
            scenes.append(scene)

        # Parse subtitles
        subtitles = [
            ManifestSubtitle(**sub) for sub in data.get("subtitles", [])
        ]

        # Parse audio layers
        audio_data = data.get("audio_layers", {})
        audio_layers = ManifestAudioLayers(
            bed=ManifestAudioLayer(**audio_data.get("bed", {"layer": "BED"})),
            music=ManifestAudioLayer(**audio_data.get("music", {"layer": "MUSIC"})),
            vo=ManifestAudioLayer(**audio_data.get("vo", {"layer": "VO"})),
            sfx_events=[
                ManifestSFXEvent(**sfx) for sfx in audio_data.get("sfx_events", [])
            ],
            foley_events=[
                ManifestSFXEvent(**foley) for foley in audio_data.get("foley_events", [])
            ],
        )

        # Parse global effects
        global_effects = [
            ManifestEffect(**e) for e in data.get("global_effects", [])
        ]

        return Gen3bManifest(
            version="1.3.1",
            project_id=gen3a_analysis.project_id,
            generated_at=datetime.now().isoformat(),
            total_duration=data.get("total_duration", gen3a_analysis.gen3b_handoff.total_output_duration),
            target_duration=data.get("target_duration", 25.0),
            hook=hook,
            scenes=scenes,
            audio_layers=audio_layers,
            subtitles=subtitles,
            global_effects=global_effects,
            loop_point=data.get("loop_point", 0.0),
            loop_compliant=data.get("loop_compliant", gen3a_analysis.gen3b_handoff.loop_compliant),
        )

    async def generate_simple_manifest(
        self,
        gen3a_analysis: Gen3aOutput,
        project_dir: Path,
    ) -> Gen3bManifest:
        """
        Generate a simple manifest without LLM call (for testing).

        Uses GEN3a analysis directly to create manifest.
        """
        logger.info("Generating simple manifest from GEN3a analysis...")

        scenes = []
        current_time = 0.3  # After hook

        for scene_analysis in gen3a_analysis.scenes:
            scene = ManifestScene(
                scene_number=scene_analysis.scene_number,
                source_file=f"gen3a_work/{scene_analysis.scene_number}.mp4",
                timeline_start=current_time,
                timeline_end=current_time + scene_analysis.output_duration,
                speed_segments=scene_analysis.speed_map,
                effects=[],
                cuts=[
                    ManifestCut(
                        source_start=g.source_start,
                        source_end=g.source_end,
                        reason=g.type,
                    )
                    for g in scene_analysis.glitches
                    if g.recommended_action == "CUT"
                ],
            )
            scenes.append(scene)
            current_time += scene_analysis.output_duration

        # Create default hook
        hook = HookSection(
            style=gen3a_analysis.hook_variety_analysis.recommended_style,
            duration=0.3,
            effects=[],
            sfx="impact_hit.mp3",
        )

        return Gen3bManifest(
            version="1.3.1",
            project_id=gen3a_analysis.project_id,
            generated_at=datetime.now().isoformat(),
            total_duration=current_time,
            target_duration=25.0,
            hook=hook,
            scenes=scenes,
            audio_layers=ManifestAudioLayers(),
            subtitles=[],
            global_effects=[],
            loop_point=0.0,
            loop_compliant=gen3a_analysis.gen3b_handoff.loop_compliant,
        )

    def save_manifest(
        self,
        manifest: Gen3bManifest,
        output_path: Path,
    ) -> Path:
        """Save manifest to JSON file."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(manifest.model_dump(), f, indent=2, ensure_ascii=False)

        logger.success(f"Manifest saved: {output_path}")
        return output_path


# ============================================================================
# EXPORT
# ============================================================================

__all__ = ["Gen3bService"]
