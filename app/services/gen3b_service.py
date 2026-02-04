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
import re
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
            max_output_tokens=settings.GEMINI_MAX_OUTPUT_TOKENS,
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

            # DEBUG: Save raw Gemini response for analysis
            from app.core.config import settings
            debug_path = Path(settings.PROJECTS_DIR) / gen3a_analysis.project_id / "gen3b_raw_response.json"
            with open(debug_path, "w", encoding="utf-8") as f:
                json.dump(manifest_data, f, indent=2, ensure_ascii=False)
            logger.info(f"DEBUG: Raw response saved to {debug_path}")

            # Convert to Gen3bManifest
            manifest = self._convert_to_manifest(manifest_data, gen3a_analysis, gen1_brief)

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

    def _safe_parse_list(self, items: list, model_class, defaults: dict = None) -> list:
        """Safely parse list of items, silently skipping invalid entries."""
        result = []
        defaults = defaults or {}
        for i, item in enumerate(items or []):
            try:
                if isinstance(item, dict):
                    result.append(model_class(**item))
                elif isinstance(item, str):
                    # Create minimal object with string as main field
                    if model_class == ManifestEffect:
                        result.append(model_class(type=item, **defaults))
                    elif model_class == ManifestSubtitle:
                        result.append(model_class(id=f"s{i+1}", text=item, output_start=0.0, output_end=3.0))
                    elif model_class == ManifestSFXEvent:
                        result.append(model_class(id=f"sfx{i+1}", file=item, timestamp=0.0))
                    # Silently skip string values for other types (SpeedSegment, ManifestCut)
                    # These require complex dict structures that can't be inferred from a string
                # Skip None or other invalid types silently
            except Exception as e:
                # Use debug level to avoid cluttering output - these are expected parsing variations
                logger.debug(f"Skipped {model_class.__name__} item: {e}")
        return result

    def _validate_subtitles(self, subtitles: List[ManifestSubtitle]) -> bool:
        """
        Validate that subtitles are usable (not placeholder/garbage text).

        Returns True if subtitles are valid, False if they need regeneration.
        """
        if not subtitles:
            return False

        # Placeholder patterns that indicate bad subtitle generation
        placeholder_patterns = [
            "lorem", "ipsum", "placeholder", "test", "sample",
            "[text]", "<text>", "subtitle text", "description here",
            "tagline", "hook text", "voiceover", "narration",
        ]

        valid_count = 0
        for sub in subtitles:
            text = sub.text.lower().strip()

            # Skip empty or very short
            if len(text) < 3:
                continue

            # Check for placeholder patterns
            is_placeholder = any(pattern in text for pattern in placeholder_patterns)
            if is_placeholder:
                logger.debug(f"Subtitle '{sub.text}' looks like placeholder")
                continue

            # Check timing makes sense
            if sub.output_end <= sub.output_start:
                logger.debug(f"Subtitle '{sub.text}' has invalid timing")
                continue

            valid_count += 1

        # At least 50% should be valid
        min_valid = max(1, len(subtitles) // 2)
        is_valid = valid_count >= min_valid

        if not is_valid:
            logger.warning(f"Only {valid_count}/{len(subtitles)} subtitles are valid")

        return is_valid

    def _split_text_by_pause(self, raw_text: str, start_time: float, end_time: float) -> List[dict]:
        """
        Split text by [pause] tags and calculate timing for each part.

        Returns list of {text, start, end} for each segment.
        Timing is estimated based on character count ratio.
        """
        # Find all pause tags (case insensitive)
        pause_pattern = r'\[(?:pause|short pause|long pause)\]'

        # Split by pause, keeping the delimiters to know pause positions
        parts = re.split(f'({pause_pattern})', raw_text, flags=re.IGNORECASE)

        # Filter out empty parts and pause tags, collect text segments
        text_segments = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if re.match(pause_pattern, part, re.IGNORECASE):
                continue  # Skip pause tags
            # Clean ElevenLabs tags from this segment
            clean_part = part
            for tag in ["[shouts]", "[whispers]", "[whisper]", "[soft]", "[excited]",
                        "[shout]", "[dramatic]", "[sarcastic]", "[sighs]", "[laughs]", "[sad]",
                        "[angry]", "[happily]"]:
                clean_part = clean_part.replace(tag, "").strip()
            clean_part = re.sub(r'<[^>]+>', '', clean_part)
            clean_part = " ".join(clean_part.split())
            if clean_part and len(clean_part) >= 3:
                text_segments.append(clean_part)

        if len(text_segments) <= 1:
            # No pause split needed
            return None

        # Calculate timing based on character ratios
        total_chars = sum(len(seg) for seg in text_segments)
        total_duration = end_time - start_time
        pause_gap = 0.4  # Gap between segments (pause duration estimate)

        # Adjust duration for pauses
        num_pauses = len(text_segments) - 1
        speaking_duration = total_duration - (num_pauses * pause_gap)

        result = []
        current_time = start_time

        for i, segment in enumerate(text_segments):
            # Calculate segment duration based on character ratio
            char_ratio = len(segment) / total_chars
            seg_duration = speaking_duration * char_ratio

            result.append({
                "text": segment,
                "start": round(current_time, 2),
                "end": round(current_time + seg_duration, 2),
            })

            current_time += seg_duration + pause_gap

        logger.info(f"Split text into {len(result)} segments by [pause] tags")
        return result

    def _merge_subtitles_with_voiceover(
        self,
        gen3b_subtitles: List[ManifestSubtitle],
        gen1_brief: Dict[str, Any],
        manifest_scenes: List[ManifestScene],
        project_dir: Path = None,
    ) -> List[ManifestSubtitle]:
        """
        Merge GEN3b subtitles with voiceover from gen1_brief.

        - Uses voiceover_timing.json for accurate timing when available
        - Falls back to gen1_brief.scenes[N].voiceover_segment for text
        - Keeps GEN3b style if available
        - Splits subtitles at [pause] tags for sync
        - Adds hook offset (0.3s) to sync with video timeline
        """
        gen1_scenes = gen1_brief.get("scenes", [])
        result = []

        # Hook duration offset - subtitles start after hook
        HOOK_OFFSET = 0.3

        # REQUIRE voiceover_timing.json for accurate timing (no fallback!)
        vo_timing = {}
        if not project_dir:
            raise ValueError("project_dir is required for subtitle timing - cannot load voiceover_timing.json")

        timing_path = project_dir / "voiceover_timing.json"
        if not timing_path.exists():
            raise FileNotFoundError(
                f"voiceover_timing.json not found at {timing_path}. "
                f"Ensure AudioStage completed successfully with ElevenLabs timestamps. "
                f"Required files: voiceover.mp3, vo_alignment.json, voiceover_timing.json"
            )

        import json
        with open(timing_path, "r", encoding="utf-8") as f:
            timing_data = json.load(f)
        for seg in timing_data.get("segments", []):
            # Add hook offset to timing - voiceover plays after hook
            vo_timing[seg["scene_number"]] = {
                "start_time": seg["start_time"] + HOOK_OFFSET,
                "end_time": seg["end_time"] + HOOK_OFFSET,
                "text": seg["text"],
            }
        logger.info(f"Loaded voiceover timing for {len(vo_timing)} segments (with {HOOK_OFFSET}s hook offset)")

        # Build lookup of existing GEN3b subtitles by scene
        existing_by_scene = {}
        for sub in gen3b_subtitles:
            for scene in manifest_scenes:
                if scene.timeline_start <= sub.output_start < scene.timeline_end:
                    existing_by_scene[scene.scene_number] = sub
                    break

        for i, gen1_scene in enumerate(gen1_scenes):
            scene_num = gen1_scene.get("scene_number", i + 1)

            # Get voiceover text from scene
            raw_text = gen1_scene.get("voiceover_segment", "") or gen1_scene.get("voiceover", "")

            # Skip empty or placeholder voiceover
            placeholder_texts = ["tagline", "final vo (can be empty)", "(can be empty)", "",
                                 "loop setup", "loop close", "closing loop", "loop", "(loop)"]
            raw_lower = raw_text.lower().strip() if raw_text else ""
            # Check exact match or if text contains "loop" and is short (likely placeholder)
            is_placeholder = (
                not raw_text or
                raw_lower in placeholder_texts or
                (len(raw_lower) < 20 and "loop" in raw_lower)
            )
            if is_placeholder:
                continue

            # Determine timing - REQUIRE voiceover_timing.json (no fallback!)
            if scene_num in vo_timing:
                start_time = vo_timing[scene_num]["start_time"]
                end_time = vo_timing[scene_num]["end_time"]
                logger.debug(f"Scene {scene_num}: Using VO timing {start_time}-{end_time}s")
            else:
                # NO FALLBACK - voiceover_timing.json is required for accurate subtitles
                raise ValueError(
                    f"Scene {scene_num} missing from voiceover_timing.json. "
                    f"Ensure AudioStage generated voiceover with timestamps (vo_alignment.json + voiceover_timing.json). "
                    f"Scene boundaries fallback has been removed - accurate subtitle timing requires voiceover timestamps."
                )

            # Determine style based on voice direction tags
            style = "NORMAL"
            animation = "BOUNCE"

            if "[whisper" in raw_text.lower():
                style = "WHISPER"
                animation = "FADE_ELEGANT"
            elif "[shout" in raw_text.lower():
                style = "Impact"
                animation = "SHAKE"
            elif "[dramatic" in raw_text.lower():
                style = "DRAMATIC"
                animation = "SLOW_REVEAL"

            # Check if text has [pause] - split into multiple subtitles
            pause_segments = self._split_text_by_pause(raw_text, start_time, end_time)

            if pause_segments:
                # Create separate subtitle for each segment
                for j, seg in enumerate(pause_segments):
                    sub_id = f"SUB{scene_num}_{chr(65+j)}"  # SUB1_A, SUB1_B, etc.

                    # Get style from existing or determine from segment
                    seg_style = style
                    seg_animation = animation
                    if scene_num in existing_by_scene:
                        existing = existing_by_scene[scene_num]
                        seg_style = existing.style or style
                        seg_animation = existing.animation or animation

                    subtitle = ManifestSubtitle(
                        id=sub_id,
                        text=seg["text"],
                        output_start=seg["start"],
                        output_end=seg["end"],
                        style=seg_style,
                        position="bottom-center",
                        animation=seg_animation,
                    )
                    result.append(subtitle)
                    logger.info(f"Added split subtitle {sub_id}: '{seg['text'][:30]}...' @ {seg['start']:.2f}s")
            else:
                # No pause - single subtitle
                # Clean up text - remove ElevenLabs audio tags for display
                display_text = raw_text
                for tag in ["[shouts]", "[whispers]", "[whisper]", "[pause]", "[soft]", "[excited]",
                            "[shout]", "[dramatic]", "[sarcastic]", "[sighs]", "[laughs]", "[sad]",
                            "[angry]", "[happily]", "[short pause]", "[long pause]"]:
                    display_text = display_text.replace(tag, "").strip()
                display_text = re.sub(r'<[^>]+>', '', display_text)
                display_text = " ".join(display_text.split())

                if not display_text or len(display_text) < 3:
                    continue

                # Use GEN3b style if available, but always use correct timing from voiceover
                if scene_num in existing_by_scene:
                    existing = existing_by_scene[scene_num]
                    subtitle = ManifestSubtitle(
                        id=existing.id,
                        text=display_text,
                        output_start=float(start_time),  # Always use voiceover timing
                        output_end=float(end_time),
                        style=existing.style or style,
                        position=existing.position or "bottom-center",
                        animation=existing.animation or animation,
                    )
                else:
                    subtitle = ManifestSubtitle(
                        id=f"SUB_S{scene_num}",
                        text=display_text,
                        output_start=float(start_time),
                        output_end=float(end_time),
                        style=style,
                        position="bottom-center",
                        animation=animation,
                    )
                    logger.info(f"Added subtitle for scene {scene_num}: '{display_text[:30]}...' @ {start_time:.2f}s")

                result.append(subtitle)

        result.sort(key=lambda s: s.output_start)
        logger.info(f"Merged subtitles: {len(result)} total (timing source: voiceover_timing.json)")
        return result

    # NOTE: _generate_subtitles_from_voiceover fallback method was REMOVED
    # Subtitle timing now REQUIRES voiceover_timing.json from AudioStage
    # If voiceover_timing.json is missing, the pipeline will fail with a clear error

    def _parse_subtitles(self, items: list) -> List[ManifestSubtitle]:
        """Parse subtitles from Gemini format to ManifestSubtitle."""
        result = []
        for i, item in enumerate(items or []):
            try:
                if not isinstance(item, dict):
                    continue

                # Extract timing - Gemini nests in "timing" object
                timing = item.get("timing", {})
                output_start = timing.get("output_start") or item.get("output_start", 0.0)
                output_end = timing.get("output_end") or item.get("output_end", 0.0)

                # Extract text
                text = item.get("text", "")
                if not text:
                    continue

                # Skip placeholder text
                placeholder_texts = ["tagline", "hook text", "placeholder", "subtitle text"]
                if text.lower().strip() in placeholder_texts:
                    logger.debug(f"Skipped placeholder subtitle: '{text}'")
                    continue

                # Extract style and animation
                style = item.get("style", "NORMAL")
                visual = item.get("visual", {})
                animation = visual.get("animation") or item.get("animation", "fade")

                # Extract position
                position = item.get("position", {})
                position_zone = position.get("zone") or item.get("position", "bottom_center")

                subtitle = ManifestSubtitle(
                    id=item.get("id", f"sub_{i+1}"),
                    text=text,
                    output_start=float(output_start),
                    output_end=float(output_end),
                    style=style,
                    position=position_zone,
                    animation=animation,
                )
                result.append(subtitle)
                logger.debug(f"Parsed subtitle: {subtitle.id} '{text[:30]}...' @ {output_start}-{output_end}s")
            except Exception as e:
                logger.debug(f"Skipped subtitle item: {e}")

        logger.info(f"Parsed {len(result)} subtitles from Gemini response")
        return result

    def _convert_to_manifest(
        self,
        data: Dict[str, Any],
        gen3a_analysis: Gen3aOutput,
        gen1_brief: Dict[str, Any] = None,
    ) -> Gen3bManifest:
        """Convert parsed JSON to Gen3bManifest model."""
        # Parse hook section
        hook_data = data.get("hook", {})
        hook = HookSection(
            style=hook_data.get("style", gen3a_analysis.hook_variety_analysis.recommended_style),
            duration=hook_data.get("duration", 0.3),
            effects=self._safe_parse_list(hook_data.get("effects", []), ManifestEffect),
            sfx=hook_data.get("sfx", ""),
        )

        # Parse scenes (try multiple keys: scenes, timeline)
        scenes = []
        raw_scenes = data.get("scenes") or data.get("timeline", [])
        logger.info(f"Raw scenes count: {len(raw_scenes)}")
        if not raw_scenes:
            logger.warning(f"No scenes in data. Keys: {list(data.keys())}")
        for i, scene_data in enumerate(raw_scenes):
            try:
                # Handle multiple possible field names (Gemini uses nested structure)
                scene_number = (
                    scene_data.get("scene_number") or
                    scene_data.get("sequence_index") or
                    scene_data.get("scene") or
                    (i + 1)
                )
                source_file = (
                    scene_data.get("source_file") or
                    scene_data.get("source") or
                    scene_data.get("file") or
                    ""
                )

                # Gemini nests timing in output_timing
                output_timing = scene_data.get("output_timing", {})
                timeline_start = (
                    scene_data.get("timeline_start") or
                    output_timing.get("cumulative_start") or
                    output_timing.get("start") or
                    scene_data.get("start") or
                    scene_data.get("in") or
                    0.0
                )
                timeline_end = (
                    scene_data.get("timeline_end") or
                    output_timing.get("cumulative_end") or
                    output_timing.get("end") or
                    scene_data.get("end") or
                    scene_data.get("out") or
                    0.0
                )

                # Gemini nests speed in speed_processing.speed_map
                speed_processing = scene_data.get("speed_processing", {})
                speed_data = (
                    scene_data.get("speed_segments") or
                    speed_processing.get("speed_map") or
                    scene_data.get("speed") or
                    []
                )

                # Gemini uses visual_effects
                effects_data = (
                    scene_data.get("effects") or
                    scene_data.get("visual_effects") or
                    []
                )

                # Gemini may return cuts as dict {"has_cuts": false} or list
                cuts_data = scene_data.get("cuts", [])
                if isinstance(cuts_data, dict):
                    # Extract actual cut list from dict, or empty if no cuts
                    cuts_data = cuts_data.get("cut_list", cuts_data.get("cuts", []))
                    if not isinstance(cuts_data, list):
                        cuts_data = []

                scene = ManifestScene(
                    scene_number=int(scene_number) if scene_number else i + 1,
                    source_file=str(source_file),
                    timeline_start=float(timeline_start),
                    timeline_end=float(timeline_end),
                    speed_segments=self._safe_parse_list(speed_data, SpeedSegment),
                    effects=self._safe_parse_list(effects_data, ManifestEffect),
                    cuts=self._safe_parse_list(cuts_data, ManifestCut),
                )
                scenes.append(scene)
            except Exception as e:
                logger.warning(f"Failed to parse scene {i+1}: {e}")

        # Parse subtitles - handle nested structure {"items": [...]} or flat list
        subtitles_data = data.get("subtitles", [])
        if isinstance(subtitles_data, dict):
            # Gemini may return {"style_system_version": "1.3", "items": [...]}
            subtitles_data = subtitles_data.get("items", [])
        subtitles = self._parse_subtitles(subtitles_data)

        # ALWAYS merge with gen1_brief to ensure all voiceover scenes have subtitles
        logger.info(f"  Pre-merge subtitles: {len(subtitles)}, gen1_brief has scenes: {bool(gen1_brief and gen1_brief.get('scenes'))}")
        if gen1_brief and gen1_brief.get("scenes"):
            # Get project_dir for voiceover_timing.json
            from app.core.config import settings
            project_dir = Path(settings.PROJECTS_DIR) / gen3a_analysis.project_id
            subtitles = self._merge_subtitles_with_voiceover(subtitles, gen1_brief, scenes, project_dir)
            logger.info(f"  Post-merge subtitles: {len(subtitles)}")
        elif not subtitles:
            logger.warning("No gen1_brief scenes available for subtitle generation")

        # Parse audio layers with safe defaults
        audio_data = data.get("audio_layers", {})

        def safe_audio_layer(layer_data, layer_name: str) -> ManifestAudioLayer:
            """Create audio layer with safe defaults."""
            if isinstance(layer_data, dict) and layer_data:
                # Ensure 'layer' field exists
                layer_data.setdefault("layer", layer_name)
                return ManifestAudioLayer(**layer_data)
            return ManifestAudioLayer(layer=layer_name)

        audio_layers = ManifestAudioLayers(
            bed=safe_audio_layer(audio_data.get("bed"), "BED"),
            music=safe_audio_layer(audio_data.get("music"), "MUSIC"),
            vo=safe_audio_layer(audio_data.get("vo"), "VO"),
            sfx_events=self._safe_parse_list(audio_data.get("sfx_events", []), ManifestSFXEvent),
            foley_events=self._safe_parse_list(audio_data.get("foley_events", []), ManifestSFXEvent),
        )

        # Parse global effects
        global_effects = self._safe_parse_list(data.get("global_effects", []), ManifestEffect)

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
