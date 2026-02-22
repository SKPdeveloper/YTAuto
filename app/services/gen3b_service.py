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
    # Core models
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
    # GEN3a models (v1.3.2)
    MusicAnalysis,
    MusicBeat,
    VisualClassification,
    GlitchInfo,
    ActionPeak,
    EasterEggVerification,
    # GEN3b models (v1.3.2)
    CanvasConfig,
    Resolution,
    FpsConfig,
    FontConfig,
    BeatSyncReport,
    BeatSyncScore,
    SceneTransitionBeat,
    TransitionToNext,
    TransitionBeatInfo,
    SceneVisualType,
    EasterEggProtection,
    LoopProcessing,
    OutputConfig,
    VideoOutputConfig,
    AudioOutputConfig,
    ValidationResult,
    CreativeSummary,
    EffectSelectionLog,
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
            temperature=1.0,  # Gemini 3 Pro optimized (thinking model)
            top_p=0.95,
            max_output_tokens=settings.GEMINI_MAX_OUTPUT_TOKENS,
            response_mime_type="application/json",
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
        voiceover_timing: Optional[Dict[str, Any]] = None,
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
            # Build generation request (with VO timing for duration-aware scene planning)
            request_content = self._build_manifest_request(
                gen3a_analysis=gen3a_analysis,
                gen1_brief=gen1_brief,
                gen2_brief=gen2_brief,
                voiceover_timing=voiceover_timing,
            )

            # Generate manifest (async API)
            logger.info("Sending to Gemini for manifest generation...")
            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=request_content,
                config=self.config,
            )

            # Parse response — handle None from safety filter
            raw_output = response.text
            if not raw_output:
                raise ValueError("Gemini returned empty response — content may have been blocked by safety filters")
            logger.info(f"Received response: {len(raw_output)} characters")

            # Extract JSON
            manifest_data = self._parse_json_response(raw_output)

            # DEBUG: Save raw Gemini response for analysis
            try:
                debug_path = Path(settings.PROJECTS_DIR) / gen3a_analysis.project_id / "gen3b_raw_response.json"
                debug_path.parent.mkdir(parents=True, exist_ok=True)
                with open(debug_path, "w", encoding="utf-8") as f:
                    json.dump(manifest_data, f, indent=2, ensure_ascii=False)
                logger.info(f"DEBUG: Raw response saved to {debug_path}")
            except Exception as e:
                logger.warning(f"Failed to save debug response: {e}")

            # Convert to Gen3bManifest
            manifest = self._convert_to_manifest(manifest_data, gen3a_analysis, gen1_brief)

            # Post-process: enforce money shot minimum duration
            self._enforce_money_shot_floor(manifest, gen3a_analysis)

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
        voiceover_timing: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build the manifest generation request."""
        # Convert Gen3aOutput to dict for JSON serialization
        analysis_dict = gen3a_analysis.model_dump()

        # Build VO timing block if available
        vo_timing_block = ""
        if voiceover_timing and voiceover_timing.get("segments"):
            vo_timing_block = f"""
### voiceover_timing.json (ACTUAL TTS durations — use for scene duration planning):
```json
{json.dumps(voiceover_timing, indent=2, ensure_ascii=False)}
```
"""

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
{vo_timing_block}
## YOUR TASK

Create production-ready manifest.json with:

1. **HOOK SELECTION**: Use recommended_style from gen3a or select alternative with justification
2. **SCENE PROCESSING**: Transform each scene with:
   - speed_segments from gen3a
   - effects based on visual_classification
   - cuts for glitch removal
   - **SCENE DURATION must accommodate voiceover** (see VO TIMING rule in system prompt)
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

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"GEN3b: Failed to parse JSON from Gemini response: {e}")
            logger.error(f"GEN3b: Response text (first 500 chars): {text[:500]}")
            raise ValueError(f"Gemini returned invalid JSON: {e}") from e

    def _regenerate_voiceover_timing(
        self, project_dir: Path, alignment_path: Path, output_path: Path
    ) -> None:
        """
        Regenerate voiceover_timing.json from vo_alignment.json.

        Fallback recovery when AudioStage generated voiceover.mp3 + vo_alignment.json
        but voiceover_timing.json was not created (e.g. partial failure).
        Uses the same text-matching logic as AudioEngine._generate_voiceover_timing.
        """
        import json
        import re

        try:
            with open(alignment_path, "r", encoding="utf-8") as f:
                alignment = json.load(f)

            chars = alignment.get("characters", [])
            starts = alignment.get("character_start_times_seconds", [])
            ends = alignment.get("character_end_times_seconds", [])

            if not chars or not starts or not ends:
                logger.warning("vo_alignment.json has empty data, cannot regenerate timing")
                return

            # Parse sentences from alignment
            sentences = []
            current_text = ""
            sent_start = 0.0

            for i, char in enumerate(chars):
                if current_text == "":
                    sent_start = starts[i]
                current_text += char

                if char in ".!?":
                    sent_end = ends[i]
                    clean_text = re.sub(r"\[[^\]]+\]", "", current_text).strip()
                    clean_text = re.sub(r"<[^>]+>", "", clean_text).strip()
                    if len(clean_text) > 2:
                        sentences.append({"text": clean_text, "start": sent_start, "end": sent_end})
                    current_text = ""

            # Capture remaining text
            if current_text.strip():
                clean_text = re.sub(r"\[[^\]]+\]", "", current_text).strip()
                clean_text = re.sub(r"<[^>]+>", "", clean_text).strip()
                if len(clean_text) > 2:
                    sentences.append({"text": clean_text, "start": sent_start, "end": ends[-1] if ends else 0.0})

            # Load project_brief for scene matching
            brief_path = project_dir / "project_brief.json"
            scene_vo_segments = []
            if brief_path.exists():
                with open(brief_path, "r", encoding="utf-8") as f:
                    brief = json.load(f)
                for scene in sorted(brief.get("scenes", []), key=lambda s: s.get("scene_number", 0)):
                    vo_segment = scene.get("voiceover_segment", "") or scene.get("voiceover", "")
                    if vo_segment:
                        clean_vo = re.sub(r"\[[^\]]+\]", "", vo_segment).strip()
                        clean_vo = re.sub(r"<[^>]+>", "", clean_vo).strip()
                        clean_vo = " ".join(clean_vo.split())
                        if clean_vo and len(clean_vo) >= 3:
                            scene_vo_segments.append({"scene_number": scene.get("scene_number", 0), "text_lower": clean_vo.lower()})

            # Match sentences to scenes by text containment
            segments_by_scene = {}
            last_matched_idx = 0

            for sent in sentences:
                clean_sent = " ".join(sent["text"].split()).lower()
                matched_idx = last_matched_idx
                match_key = clean_sent[:30] if len(clean_sent) > 30 else clean_sent

                for idx in range(last_matched_idx, len(scene_vo_segments)):
                    if match_key in scene_vo_segments[idx]["text_lower"]:
                        matched_idx = idx
                        break

                if matched_idx < len(scene_vo_segments):
                    scene_number = scene_vo_segments[matched_idx]["scene_number"]
                    last_matched_idx = matched_idx
                elif scene_vo_segments:
                    scene_number = scene_vo_segments[-1]["scene_number"]
                else:
                    scene_number = 1

                if scene_number in segments_by_scene:
                    existing = segments_by_scene[scene_number]
                    existing["end_time"] = max(existing["end_time"], sent["end"])
                    existing["text"] += " " + sent["text"]
                else:
                    segments_by_scene[scene_number] = {
                        "scene_number": scene_number,
                        "start_time": sent["start"],
                        "end_time": sent["end"],
                        "text": sent["text"],
                    }

            final_segments = sorted(segments_by_scene.values(), key=lambda s: s["start_time"])
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump({"segments": final_segments}, f, indent=2, ensure_ascii=False)

            logger.success(f"Regenerated voiceover_timing.json with {len(final_segments)} segments from vo_alignment.json")

        except Exception as e:
            logger.error(f"Failed to regenerate voiceover_timing.json: {e}")

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
                        result.append(model_class(id=f"sfx{i+1}", file=item, output_timestamp=0.0, effect=item))
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
            clean_part = re.sub(
                r'\[(?:shouts?|whispers?|soft|excited|dramatic|sarcastic|sighs?|laughs?|sad|angry|happily)\]',
                '', clean_part, flags=re.IGNORECASE
            ).strip()
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

        # Adjust duration for pauses — clamp to prevent negative when many segments in short duration
        num_pauses = len(text_segments) - 1
        speaking_duration = total_duration - (num_pauses * pause_gap)
        if speaking_duration <= 0:
            # Too many pauses for the duration — reduce pause gap proportionally
            pause_gap = (total_duration * 0.2) / max(num_pauses, 1)
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

        # Load voiceover timing (with fallback recovery)
        vo_timing = {}
        if not project_dir:
            raise ValueError("project_dir is required for subtitle timing - cannot load voiceover_timing.json")

        import json
        import re as _re

        timing_path = project_dir / "voiceover_timing.json"

        # If voiceover_timing.json missing, try to regenerate from vo_alignment.json
        if not timing_path.exists():
            alignment_path = project_dir / "vo_alignment.json"
            if alignment_path.exists():
                logger.warning(
                    f"voiceover_timing.json not found - regenerating from vo_alignment.json"
                )
                self._regenerate_voiceover_timing(project_dir, alignment_path, timing_path)
            else:
                logger.warning(
                    f"Neither voiceover_timing.json nor vo_alignment.json found at {project_dir}. "
                    f"Subtitles will use scene timeline estimates for all scenes."
                )

        if timing_path.exists():
            with open(timing_path, "r", encoding="utf-8") as f:
                timing_data = json.load(f)
            for seg in timing_data.get("segments", []):
                scene_num = seg.get("scene_number")
                if scene_num is None:
                    logger.warning(f"Skipping timing segment without scene_number: {seg}")
                    continue
                # Add hook offset to timing - voiceover plays after hook
                vo_timing[scene_num] = {
                    "start_time": seg.get("start_time", 0.0) + HOOK_OFFSET,
                    "end_time": seg.get("end_time", 0.0) + HOOK_OFFSET,
                    "text": seg.get("text", ""),
                }
            logger.info(f"Loaded voiceover timing for {len(vo_timing)} segments (with {HOOK_OFFSET}s hook offset)")
        else:
            logger.warning("No voiceover timing available - all subtitles will use scene timeline estimates")

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

            # Determine timing from voiceover_timing.json
            if scene_num in vo_timing:
                start_time = vo_timing[scene_num]["start_time"]
                end_time = vo_timing[scene_num]["end_time"]
                logger.debug(f"Scene {scene_num}: Using VO timing {start_time}-{end_time}s")
            else:
                # Fallback: estimate from scene timeline (text matching may miss edge cases)
                logger.warning(
                    f"Scene {scene_num} missing from voiceover_timing.json "
                    f"(text matching may have assigned it to another scene). "
                    f"Using scene timeline estimate."
                )
                # Find matching manifest scene for timeline bounds
                matching_scene = next(
                    (s for s in manifest_scenes if s.scene_number == scene_num), None
                )
                if matching_scene:
                    # timeline_start already accounts for hook position — don't add HOOK_OFFSET again
                    start_time = matching_scene.timeline_start
                    end_time = matching_scene.timeline_end
                else:
                    # Last resort: skip this subtitle
                    logger.warning(f"Scene {scene_num}: no timeline data, skipping subtitle")
                    continue

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
                # Clean up text - remove ElevenLabs audio tags for display (case-insensitive)
                display_text = re.sub(r'\[[\w\s]+\]', '', raw_text)
                display_text = re.sub(r'<[^>]+>', '', display_text)
                display_text = " ".join(display_text.split()).strip()

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
                # Use `is not None` checks — 0.0 is a valid timestamp (falsy in Python `or` chains)
                timing = item.get("timing", {})
                output_start = timing.get("output_start")
                if output_start is None:
                    output_start = timing.get("segment_start")
                if output_start is None:
                    output_start = item.get("output_start", 0.0)
                output_end = timing.get("output_end")
                if output_end is None:
                    output_end = timing.get("segment_end")
                if output_end is None:
                    output_end = item.get("output_end", 0.0)

                # Extract text - GEN3b nests in text_source.clean_text
                text_source = item.get("text_source", {})
                text = (
                    item.get("text") or
                    text_source.get("clean_text") or
                    text_source.get("original") or
                    ""
                )
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

                # Extract position — Gemini may return string "bottom_center" or dict {"zone": "bottom_center"}
                position = item.get("position", {})
                if isinstance(position, str):
                    position_zone = position
                else:
                    position_zone = position.get("zone", "bottom_center") if isinstance(position, dict) else "bottom_center"

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

    def _enforce_money_shot_floor(
        self,
        manifest: Gen3bManifest,
        gen3a_analysis: Gen3aOutput,
    ) -> None:
        """Ensure money shot gets at least gen3a-recommended duration (min 3.0s).

        If the money shot was compressed below the floor, expand it and shift
        all subsequent scenes forward.
        """
        MONEY_SHOT_MIN = 3.0
        gen3a_scenes_map = {s.scene_number: s for s in gen3a_analysis.scenes}

        shifted = False
        for scene in manifest.scenes:
            if "MONEY_SHOT" not in (scene.special_flags or []):
                continue

            sn = scene.scene_number
            gen3a_scene = gen3a_scenes_map.get(sn)
            gen3a_dur = 0.0
            if gen3a_scene and gen3a_scene.speed_map:
                gen3a_dur = sum(
                    (seg.source_end - seg.source_start) / (seg.speed or 1.0)
                    for seg in gen3a_scene.speed_map
                )

            min_dur = max(gen3a_dur, MONEY_SHOT_MIN)
            current_dur = scene.timeline_end - scene.timeline_start

            if current_dur < min_dur:
                deficit = min_dur - current_dur
                scene.timeline_end = scene.timeline_start + min_dur
                logger.info(f"  Money shot S{sn}: {current_dur:.1f}s → {min_dur:.1f}s (floor, +{deficit:.1f}s)")

                # Shift subsequent scenes
                for later_scene in manifest.scenes:
                    if later_scene.scene_number > sn:
                        later_scene.timeline_start += deficit
                        later_scene.timeline_end += deficit

                # Rescale speed segments for new duration
                if scene.speed_segments:
                    source_dur = scene.source_duration or 10.0
                    new_speed = round(source_dur / min_dur, 2)
                    scene.speed_segments = [SpeedSegment(
                        source_start=0.0,
                        source_end=source_dur,
                        speed=new_speed,
                        output_duration=min_dur,
                    )]

                shifted = True

        if shifted:
            manifest.total_duration = manifest.scenes[-1].timeline_end

    def _convert_to_manifest(
        self,
        data: Dict[str, Any],
        gen3a_analysis: Gen3aOutput,
        gen1_brief: Dict[str, Any] = None,
    ) -> Gen3bManifest:
        """
        Convert parsed JSON to Gen3bManifest model.

        v1.3.2: Preserves 100% of data from GEN3a and GEN3b.
        """
        # =====================================================================
        # HOOK SECTION - with effects from hook_sequence
        # =====================================================================
        hook_data = data.get("hook", {})
        hook_sequence = data.get("hook_sequence", {})

        # Parse hook effects from hook_sequence (GEN3b provides them there)
        hook_effects_raw = (
            hook_data.get("effects") or
            hook_sequence.get("effects") or
            []
        )
        hook_effects = self._safe_parse_list(hook_effects_raw, ManifestEffect)

        hook = HookSection(
            style=hook_data.get("style") or hook_sequence.get("style_selected") or gen3a_analysis.hook_variety_analysis.recommended_style,
            duration=hook_data.get("duration") or hook_sequence.get("duration") or 0.3,
            effects=hook_effects,
            sfx=hook_data.get("sfx", ""),
        )

        # =====================================================================
        # SCENES - with full GEN3a and GEN3b data
        # =====================================================================
        scenes = []
        raw_scenes = data.get("scenes") or data.get("timeline", [])
        logger.info(f"Raw scenes count: {len(raw_scenes)}")
        if not raw_scenes:
            raise ValueError(f"GEN3b returned no scenes (available keys: {list(data.keys())})")

        # Build lookup for GEN3a scene data
        gen3a_scenes_map = {s.scene_number: s for s in gen3a_analysis.scenes}

        for i, scene_data in enumerate(raw_scenes):
            try:
                # Handle multiple possible field names (Gemini uses nested structure)
                raw_scene_num = (
                    scene_data.get("scene_number") or
                    scene_data.get("sequence_index") or
                    scene_data.get("scene") or
                    (i + 1)
                )
                # Gemini sometimes returns "N (last scene)" or other non-numeric strings
                try:
                    scene_number = int(raw_scene_num) if raw_scene_num else i + 1
                except (ValueError, TypeError):
                    # Extract digits from string like "N (last scene)" or "8 (loop)"
                    import re
                    digits = re.findall(r'\d+', str(raw_scene_num))
                    scene_number = int(digits[0]) if digits else i + 1

                source_file = (
                    scene_data.get("source_file") or
                    scene_data.get("source") or
                    scene_data.get("file") or
                    f"gen3a_work/{scene_number}.mp4"
                )

                # Gemini nests timing in output_timing
                # Use `is not None` — 0.0 is valid for scene 1 (falsy in Python `or` chains)
                output_timing = scene_data.get("output_timing", {})
                timeline_start = scene_data.get("timeline_start")
                if timeline_start is None:
                    timeline_start = output_timing.get("cumulative_start")
                if timeline_start is None:
                    timeline_start = output_timing.get("start")
                if timeline_start is None:
                    timeline_start = scene_data.get("start")
                if timeline_start is None:
                    timeline_start = scene_data.get("in")
                if timeline_start is None:
                    timeline_start = 0.0
                timeline_end = scene_data.get("timeline_end")
                if timeline_end is None:
                    timeline_end = output_timing.get("cumulative_end")
                if timeline_end is None:
                    timeline_end = output_timing.get("end")
                if timeline_end is None:
                    timeline_end = scene_data.get("end")
                if timeline_end is None:
                    timeline_end = scene_data.get("out")
                if timeline_end is None:
                    timeline_end = 0.0

                # -----------------------------------------------------------------
                # GET GEN3a DATA FOR THIS SCENE (must be before speed_data fallback)
                # -----------------------------------------------------------------
                gen3a_scene = gen3a_scenes_map.get(scene_number)

                # Gemini nests speed in speed_processing.speed_map
                speed_processing = scene_data.get("speed_processing", {})
                speed_data = (
                    scene_data.get("speed_segments") or
                    speed_processing.get("speed_map") or
                    scene_data.get("speed") or
                    []
                )

                # Fallback: use GEN3a speed_map if Gemini didn't return speed segments
                if not speed_data and gen3a_scene and gen3a_scene.speed_map:
                    speed_data = [seg.model_dump() for seg in gen3a_scene.speed_map]
                    logger.debug(f"  Scene {scene_number}: Using GEN3a speed_map ({len(speed_data)} segments)")

                # Gemini uses visual_effects
                effects_data = (
                    scene_data.get("effects") or
                    scene_data.get("visual_effects") or
                    []
                )

                # Gemini may return cuts as dict {"has_cuts": false} or list
                cuts_data = scene_data.get("cuts", [])
                if isinstance(cuts_data, dict):
                    cuts_data = cuts_data.get("cut_list", cuts_data.get("cuts", []))
                    if not isinstance(cuts_data, list):
                        cuts_data = []

                # Parse GEN3a fields
                glitches = []
                action_peaks = []
                visual_classification = None
                easter_egg_verification = None
                source_duration = 10.0
                video_quality = 0.8
                dead_spots = []

                if gen3a_scene:
                    source_duration = gen3a_scene.source_duration
                    video_quality = gen3a_scene.video_quality
                    dead_spots = gen3a_scene.dead_spots or []

                    # Parse glitches
                    for g in gen3a_scene.glitches or []:
                        glitches.append(GlitchInfo(
                            id=g.id,
                            source_start=g.source_start,
                            source_end=g.source_end,
                            type=g.type,
                            severity=g.severity,
                            description=g.description,
                            recommended_action=g.recommended_action,
                        ))

                    # Parse action peaks
                    for ap in gen3a_scene.action_peaks or []:
                        action_peaks.append(ActionPeak(
                            id=ap.id,
                            source_timestamp=ap.source_timestamp,
                            type=ap.type,
                            intensity=ap.intensity,
                            beat_aligned=ap.beat_aligned,
                            nearest_beat=ap.nearest_beat,
                        ))

                    # Parse visual classification
                    if gen3a_scene.visual_classification:
                        vc = gen3a_scene.visual_classification
                        visual_classification = VisualClassification(
                            primary_type=vc.primary_type,
                            secondary_type=vc.secondary_type,
                            confidence=vc.confidence,
                            reasoning=vc.reasoning,
                            dominant_elements=vc.dominant_elements or [],
                            scale=vc.scale,
                            camera_motion=vc.camera_motion,
                            effect_palette_recommendation=vc.effect_palette_recommendation,
                        )

                    # Parse easter egg verification
                    if gen3a_scene.easter_egg_verification:
                        eev = gen3a_scene.easter_egg_verification
                        easter_egg_verification = EasterEggVerification(
                            found=eev.found,
                            source_timestamp=eev.source_timestamp,
                            visibility_score=eev.visibility_score,
                            position_in_frame=eev.position_in_frame,
                            safe_zone_compliant=eev.safe_zone_compliant,
                        )

                # -----------------------------------------------------------------
                # PARSE GEN3b SCENE-SPECIFIC DATA
                # -----------------------------------------------------------------
                special_flags = scene_data.get("special_flags", [])

                # Visual type from GEN3b
                visual_type_data = scene_data.get("visual_type", {})
                visual_type = None
                if visual_type_data:
                    visual_type = SceneVisualType(
                        primary=visual_type_data.get("primary", "EPIC_WIDE"),
                        secondary=visual_type_data.get("secondary"),
                        effect_palette=visual_type_data.get("effect_palette", "DRAMATIC"),
                        source=visual_type_data.get("source", ""),
                    )

                # Transition to next
                transition_data = scene_data.get("transition_to_next", {})
                transition_to_next = None
                if transition_data:
                    beat_info_data = transition_data.get("beat_info", {})
                    beat_info = None
                    if beat_info_data:
                        beat_info = TransitionBeatInfo(
                            timestamp=beat_info_data.get("timestamp", 0.0),
                            nearest_beat=beat_info_data.get("nearest_beat", 0.0),
                            on_beat=beat_info_data.get("on_beat", False),
                            offset=beat_info_data.get("offset", 0.0),
                        )
                    transition_to_next = TransitionToNext(
                        type=transition_data.get("type", "HARD_CUT"),
                        beat_info=beat_info,
                    )

                # Effect selection log
                effect_log_data = scene_data.get("effect_selection_log", {})
                effect_selection_log = None
                if effect_log_data:
                    effect_selection_log = EffectSelectionLog(
                        palette_used=effect_log_data.get("palette_used", ""),
                        visual_type=effect_log_data.get("visual_type", ""),
                        effects_applied=effect_log_data.get("effects_applied", 0),
                        reason=effect_log_data.get("reason"),
                        forbidden_checked=effect_log_data.get("forbidden_checked", []),
                    )

                # Easter egg protection
                ee_protection_data = scene_data.get("easter_egg_protection", {})
                easter_egg_protection = None
                if ee_protection_data:
                    easter_egg_protection = EasterEggProtection(
                        object=ee_protection_data.get("object", ""),
                        verified=ee_protection_data.get("verified", False),
                        applied_restrictions=ee_protection_data.get("applied_restrictions", {}),
                    )

                # Loop processing
                loop_proc_data = scene_data.get("loop_processing", {})
                loop_processing = None
                if loop_proc_data:
                    loop_processing = LoopProcessing(
                        reverse=loop_proc_data.get("reverse", True),
                        duration_match=loop_proc_data.get("duration_match", {}),
                    )

                # -----------------------------------------------------------------
                # CREATE SCENE WITH ALL DATA
                # -----------------------------------------------------------------
                scene = ManifestScene(
                    # Core fields
                    scene_number=scene_number,
                    source_file=str(source_file),
                    timeline_start=float(timeline_start),
                    timeline_end=float(timeline_end),
                    speed_segments=self._safe_parse_list(speed_data, SpeedSegment),
                    effects=self._safe_parse_list(effects_data, ManifestEffect),
                    cuts=self._safe_parse_list(cuts_data, ManifestCut),
                    # GEN3a fields
                    source_duration=source_duration,
                    video_quality=video_quality,
                    glitches=glitches,
                    action_peaks=action_peaks,
                    dead_spots=dead_spots,
                    visual_classification=visual_classification,
                    easter_egg_verification=easter_egg_verification,
                    # GEN3b fields
                    special_flags=special_flags,
                    visual_type=visual_type,
                    transition_to_next=transition_to_next,
                    effect_selection_log=effect_selection_log,
                    easter_egg_protection=easter_egg_protection,
                    loop_processing=loop_processing,
                )
                scenes.append(scene)
            except Exception as e:
                logger.warning(f"Failed to parse scene {i+1}: {e}")
                import traceback
                logger.debug(traceback.format_exc())

        # =====================================================================
        # SUBTITLES
        # =====================================================================
        subtitles_data = data.get("subtitles", [])
        if isinstance(subtitles_data, dict):
            subtitles_data = subtitles_data.get("items") or subtitles_data.get("segments") or []
        subtitles = self._parse_subtitles(subtitles_data)

        logger.info(f"  Pre-merge subtitles: {len(subtitles)}, gen1_brief has scenes: {bool(gen1_brief and gen1_brief.get('scenes'))}")
        if gen1_brief and gen1_brief.get("scenes"):
            from app.core.config import settings
            project_dir = Path(settings.PROJECTS_DIR) / gen3a_analysis.project_id
            subtitles = self._merge_subtitles_with_voiceover(subtitles, gen1_brief, scenes, project_dir)
            logger.info(f"  Post-merge subtitles: {len(subtitles)}")
        elif not subtitles:
            logger.warning("No gen1_brief scenes available for subtitle generation")

        # =====================================================================
        # AUDIO LAYERS - FIX: check both "audio" and "audio_layers"
        # =====================================================================
        audio_data = data.get("audio_layers") or data.get("audio", {})

        # GEN3b may nest layers inside "audio.layers"
        if "layers" in audio_data:
            audio_layers_list = audio_data.get("layers", [])
            # Convert list format to dict format
            audio_dict = {}
            for layer in audio_layers_list:
                layer_type = layer.get("type", "").upper()
                if layer_type == "MUSIC":
                    ducking_data = layer.get("ducking", {})
                    # Gemini returns ducking.regions or ducking.enabled
                    has_ducking = (
                        ducking_data.get("enabled", False) or
                        bool(ducking_data.get("regions")) or
                        layer.get("duck_during_vo", False)
                    )
                    audio_dict["music"] = {
                        "layer": "MUSIC",
                        "file": layer.get("file", ""),
                        "volume": self._db_to_linear(layer.get("volume_db", 0)),
                        "duck_during_vo": has_ducking,
                        "duck_amount": 0.4,
                    }
                elif layer_type == "VOICEOVER":
                    audio_dict["vo"] = {
                        "layer": "VO",
                        "file": layer.get("file", ""),
                        "volume": self._db_to_linear(layer.get("volume_db", 0)),
                    }
                elif layer_type == "SFX":
                    # Parse SFX events
                    sfx_events = []
                    for event in layer.get("events", []):
                        # Gemini uses "time" or "timestamp" — 0.0 is valid, so use `is not None`
                        evt_timestamp = event.get("timestamp")
                        if evt_timestamp is None:
                            evt_timestamp = event.get("time")
                        if evt_timestamp is None:
                            evt_timestamp = event.get("output_timestamp")
                        if evt_timestamp is None:
                            evt_timestamp = 0.0
                        evt_id = event.get("id") or event.get("effect") or event.get("file", "").replace(".wav", "")
                        if not evt_id:
                            evt_id = f"sfx_event_{len(sfx_events)}"
                        sfx_events.append({
                            "id": evt_id,
                            "output_timestamp": float(evt_timestamp),
                            "effect": evt_id,
                            "file": event.get("file", ""),
                            "volume": self._db_to_linear(event.get("volume_db", 0)),
                        })
                    audio_dict["sfx_events"] = sfx_events
                elif layer_type == "BED":
                    audio_dict["bed"] = {
                        "layer": "BED",
                        "file": layer.get("file", ""),
                        "volume": self._db_to_linear(layer.get("volume_db", 0)),
                    }
                elif layer_type == "FOLEY":
                    foley_events = []
                    for event in layer.get("events", []):
                        # 0.0 is valid timestamp, use `is not None`
                        evt_timestamp = event.get("timestamp")
                        if evt_timestamp is None:
                            evt_timestamp = event.get("time")
                        if evt_timestamp is None:
                            evt_timestamp = event.get("output_timestamp")
                        if evt_timestamp is None:
                            evt_timestamp = 0.0
                        evt_id = event.get("id") or event.get("effect") or event.get("file", "").replace(".wav", "")
                        if not evt_id:
                            evt_id = f"foley_event_{len(foley_events)}"
                        foley_events.append({
                            "id": evt_id,
                            "output_timestamp": float(evt_timestamp),
                            "effect": evt_id,
                            "file": event.get("file", ""),
                            "volume": self._db_to_linear(event.get("volume_db", 0)),
                        })
                    audio_dict["foley_events"] = foley_events
            audio_data = audio_dict

        def safe_audio_layer(layer_data, layer_name: str) -> ManifestAudioLayer:
            if isinstance(layer_data, dict) and layer_data:
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

        # =====================================================================
        # GLOBAL EFFECTS
        # =====================================================================
        raw_global_effects = data.get("global_effects", [])
        # Gemini sometimes returns global_effects as dict {type: {params}} instead of list
        if isinstance(raw_global_effects, dict):
            effects_list = []
            for effect_type, effect_data in raw_global_effects.items():
                if isinstance(effect_data, dict):
                    if not effect_data.get("enabled", True):
                        continue  # Skip disabled effects
                    effects_list.append({
                        "type": effect_type,
                        "params": effect_data.get("params", {}),
                        "ffmpeg_filter": effect_data.get("ffmpeg_filter"),
                    })
                else:
                    effects_list.append({"type": effect_type})
            raw_global_effects = effects_list
        global_effects = self._safe_parse_list(raw_global_effects, ManifestEffect)

        # =====================================================================
        # NEW GEN3a FIELDS
        # =====================================================================
        # Music analysis
        music_analysis = None
        if gen3a_analysis.music_analysis:
            ma = gen3a_analysis.music_analysis
            beats = []
            for b in ma.beats or []:
                beats.append(MusicBeat(
                    timestamp=b.timestamp,
                    strength=b.strength,
                    beat_number=b.beat_number,
                ))
            music_analysis = MusicAnalysis(
                bpm=ma.bpm,
                time_signature=ma.time_signature,
                beats=beats,
                strong_beats_for_cuts=ma.strong_beats_for_cuts or [],
            )

        # Hook variety analysis (as dict for flexibility)
        hook_variety_analysis = None
        if gen3a_analysis.hook_variety_analysis:
            hva = gen3a_analysis.hook_variety_analysis
            hook_variety_analysis = {
                "recommended_style": hva.recommended_style,
                "reasoning": hva.reasoning,
                "avoid_styles": hva.avoid_styles or [],
                "scene1_energy": hva.scene1_energy,
            }

        # =====================================================================
        # NEW GEN3b FIELDS
        # =====================================================================
        # Canvas
        canvas = None
        canvas_data = data.get("canvas", {})
        if canvas_data:
            canvas = CanvasConfig(
                source_resolution=Resolution(**canvas_data.get("source_resolution", {"width": 1080, "height": 1920})),
                working_resolution=Resolution(**canvas_data.get("working_resolution", {"width": 1404, "height": 2496})),
                final_resolution=Resolution(**canvas_data.get("final_resolution", {"width": 1080, "height": 1920})),
            )

        # FPS config
        fps_config = None
        fps_data = data.get("fps_config", {})
        if fps_data:
            fps_config = FpsConfig(
                target_fps=fps_data.get("target_fps", 30),
                source_fps=fps_data.get("source_fps", "auto_detect"),
                conversion_filter=fps_data.get("conversion_filter", "fps=30"),
            )

        # Font config
        font_config = None
        font_data = data.get("font_config", {})
        if font_data:
            font_config = FontConfig(
                font_name=font_data.get("font_name", "Montserrat-Bold"),
                fontfile=font_data.get("fontfile", ""),
                fallback=font_data.get("fallback", "DejaVu-Sans-Bold"),
            )

        # Beat sync report
        beat_sync_report = None
        bsr_data = data.get("beat_sync_report", {})
        if bsr_data:
            sync_score_data = bsr_data.get("sync_score", {})
            scene_transitions = []
            for t in bsr_data.get("scene_transitions", []):
                scene_transitions.append(SceneTransitionBeat(
                    from_scene=t.get("from_scene", 0),
                    to_scene=t.get("to_scene", 0),
                    timestamp=t.get("timestamp", 0.0),
                    nearest_beat=t.get("nearest_beat", 0.0),
                    offset=t.get("offset", 0.0),
                    aligned=t.get("aligned", True),
                ))
            beat_sync_report = BeatSyncReport(
                music_bpm=bsr_data.get("music_bpm", 120.0),
                strong_beats_used=bsr_data.get("strong_beats_used", []),
                scene_transitions=scene_transitions,
                sync_score=BeatSyncScore(
                    transitions_on_beat=sync_score_data.get("transitions_on_beat", 0),
                    effects_on_beat=sync_score_data.get("effects_on_beat", 0),
                    overall_sync_quality=sync_score_data.get("overall_sync_quality", "GOOD"),
                    final_score=sync_score_data.get("final_score", 0.7),
                ),
            )

        # Filter chain
        filter_chain = data.get("filter_chain", {}).get("order", [])

        # Output config
        output_config = None
        oc_data = data.get("output_config", {})
        if oc_data:
            output_config = OutputConfig(
                filename=oc_data.get("filename", "output_final.mp4"),
                video=VideoOutputConfig(**oc_data.get("video", {})),
                audio=AudioOutputConfig(**oc_data.get("audio", {})),
            )

        # Validation
        validation = None
        val_data = data.get("validation", {})
        if val_data:
            validation = ValidationResult(**val_data)

        # Creative summary
        creative_summary = None
        cs_data = data.get("creative_summary", {})
        if cs_data:
            creative_summary = CreativeSummary(
                hook_style=cs_data.get("hook_style", ""),
                hook_reasoning=cs_data.get("hook_reasoning", ""),
                effects_by_palette=cs_data.get("effects_by_palette", {}),
                subtitle_style=cs_data.get("subtitle_style", ""),
                subtitle_word_count=cs_data.get("subtitle_word_count", 0),
                beat_sync_quality=cs_data.get("beat_sync_quality", ""),
                variety_score=cs_data.get("variety_score", 0.0),
                loop_ready=cs_data.get("loop_ready", True),
            )

        # =====================================================================
        # BUILD AND RETURN MANIFEST
        # =====================================================================
        return Gen3bManifest(
            version="1.3.2",
            project_id=gen3a_analysis.project_id,
            generated_at=datetime.now().isoformat(),
            total_duration=data.get("total_duration", gen3a_analysis.gen3b_handoff.total_output_duration if gen3a_analysis.gen3b_handoff else 25.0),
            target_duration=data.get("target_duration", 25.0),
            hook=hook,
            scenes=scenes,
            audio_layers=audio_layers,
            subtitles=subtitles,
            global_effects=global_effects,
            loop_point=data.get("loop_point", 0.0),
            loop_compliant=data.get("loop_compliant", gen3a_analysis.gen3b_handoff.loop_compliant if gen3a_analysis.gen3b_handoff else True),
            # NEW GEN3a fields
            music_analysis=music_analysis,
            hook_variety_analysis=hook_variety_analysis,
            # NEW GEN3b fields
            canvas=canvas,
            fps_config=fps_config,
            font_config=font_config,
            beat_sync_report=beat_sync_report,
            filter_chain=filter_chain,
            output_config=output_config,
            validation=validation,
            creative_summary=creative_summary,
            # RAW BACKUPS for 100% data preservation
            gen3a_raw=gen3a_analysis.model_dump() if hasattr(gen3a_analysis, 'model_dump') else None,
            gen3b_raw=data,
        )

    def _db_to_linear(self, db_value) -> float:
        """Convert dB to linear volume (0-1 range). Handles string input from Gemini."""
        if db_value is None:
            return 1.0
        try:
            db_value = float(db_value)
        except (ValueError, TypeError):
            return 1.0
        if db_value == 0:
            return 1.0
        import math
        return min(1.0, max(0.0, math.pow(10, db_value / 20)))

    async def generate_simple_manifest(
        self,
        gen3a_analysis: Gen3aOutput,
        project_dir: Path,
    ) -> Gen3bManifest:
        """
        Generate a simple manifest without LLM call (for testing).

        Uses GEN3a analysis directly to create manifest.
        v1.3.2: Now includes all GEN3a data.
        """
        logger.info("Generating simple manifest from GEN3a analysis...")

        scenes = []
        current_time = 0.3  # After hook

        for scene_analysis in gen3a_analysis.scenes:
            # Parse GEN3a scene data
            glitches = [
                GlitchInfo(
                    id=g.id,
                    source_start=g.source_start,
                    source_end=g.source_end,
                    type=g.type,
                    severity=g.severity,
                    description=g.description,
                    recommended_action=g.recommended_action,
                )
                for g in scene_analysis.glitches or []
            ]

            action_peaks = [
                ActionPeak(
                    id=ap.id,
                    source_timestamp=ap.source_timestamp,
                    type=ap.type,
                    intensity=ap.intensity,
                    beat_aligned=ap.beat_aligned,
                    nearest_beat=ap.nearest_beat,
                )
                for ap in scene_analysis.action_peaks or []
            ]

            visual_classification = None
            if scene_analysis.visual_classification:
                vc = scene_analysis.visual_classification
                visual_classification = VisualClassification(
                    primary_type=vc.primary_type,
                    secondary_type=vc.secondary_type,
                    confidence=vc.confidence,
                    reasoning=vc.reasoning,
                    dominant_elements=vc.dominant_elements or [],
                    scale=vc.scale,
                    camera_motion=vc.camera_motion,
                    effect_palette_recommendation=vc.effect_palette_recommendation,
                )

            easter_egg_verification = None
            if scene_analysis.easter_egg_verification:
                eev = scene_analysis.easter_egg_verification
                easter_egg_verification = EasterEggVerification(
                    found=eev.found,
                    source_timestamp=eev.source_timestamp,
                    visibility_score=eev.visibility_score,
                    position_in_frame=eev.position_in_frame,
                    safe_zone_compliant=eev.safe_zone_compliant,
                )

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
                    for g in scene_analysis.glitches or []
                    if g.recommended_action == "CUT"
                ],
                # GEN3a fields
                source_duration=scene_analysis.source_duration,
                video_quality=scene_analysis.video_quality,
                glitches=glitches,
                action_peaks=action_peaks,
                dead_spots=scene_analysis.dead_spots or [],
                visual_classification=visual_classification,
                easter_egg_verification=easter_egg_verification,
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

        # Build music analysis
        music_analysis = None
        if gen3a_analysis.music_analysis:
            ma = gen3a_analysis.music_analysis
            beats = [
                MusicBeat(
                    timestamp=b.timestamp,
                    strength=b.strength,
                    beat_number=b.beat_number,
                )
                for b in ma.beats or []
            ]
            music_analysis = MusicAnalysis(
                bpm=ma.bpm,
                time_signature=ma.time_signature,
                beats=beats,
                strong_beats_for_cuts=ma.strong_beats_for_cuts or [],
            )

        # Hook variety analysis
        hook_variety_analysis = None
        if gen3a_analysis.hook_variety_analysis:
            hva = gen3a_analysis.hook_variety_analysis
            hook_variety_analysis = {
                "recommended_style": hva.recommended_style,
                "reasoning": hva.reasoning,
                "avoid_styles": hva.avoid_styles or [],
                "scene1_energy": hva.scene1_energy,
            }

        return Gen3bManifest(
            version="1.3.2",
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
            loop_compliant=gen3a_analysis.gen3b_handoff.loop_compliant if gen3a_analysis.gen3b_handoff else True,
            # GEN3a fields
            music_analysis=music_analysis,
            hook_variety_analysis=hook_variety_analysis,
            # RAW backup
            gen3a_raw=gen3a_analysis.model_dump() if hasattr(gen3a_analysis, 'model_dump') else None,
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
