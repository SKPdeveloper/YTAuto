"""
GEN3a Service - Video Analyst v1.6.0

Аналізує згенеровані відео та створює structured analysis для GEN3b.
Використовує Gemini Vision для frame-by-frame аналізу.

v1.6.0 Features:
- Preprocessing integration (beats.json, vo_timing.json, audio_levels.json)
- Last scene (LOOP_CLOSE) pre-reversed for seamless loop
- Glitch detection (morphing errors, flicker, freeze)
- Action peak identification with SFX recommendations
- Speed map recommendations with techniques
- Easter egg verification with fallback
- Visual type classification
- Punchline moment detection
- Narrative purpose speed modifiers
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
    Gen3aSceneAnalysis,
    GlitchDetection,
    ActionPeak,
    DeadSpot,
    SpeedSegment,
    VisualClassification,
    EasterEggVerification,
    VOSegmentAnalysis,
    MusicAnalysis,
    MusicBeat,
    HookVarietyAnalysis,
    Gen3bHandoff,
)
from app.services.gen3a_preprocessing import Gen3aPreprocessor, PreprocessingResult
from app.services.gen3a_autocorrect import autocorrect_gen3a


# System prompt path
GEN3A_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "GEN3a.txt"


class Gen3aService:
    """
    GEN3a - Video Analyst v1.6.0

    Analyzes preprocessed Kling videos (6-10 scenes, 10 seconds each) and produces:
    - Glitch detection with timestamps
    - Action peaks with SFX recommendations
    - Dead spots with speed recommendations
    - Speed map with techniques
    - Easter egg verification with fallback
    - Visual type classification per scene
    - VO timing from precomputed data
    - Music beat alignment from precomputed data
    - Audio ducking recommendations
    - Punchline moment detection
    - Narrative purpose speed modifiers

    v1.6.0 Preprocessing:
    - Last scene (LOOP_CLOSE) is ALREADY REVERSED before analysis
    - beats.json provided (DO NOT analyze music)
    - vo_timing.json provided (DO NOT analyze voiceover audio)
    - audio_levels.json provided (ducking recommendations)
    """

    def __init__(self):
        """Initialize GEN3a service with Gemini client and preprocessor."""
        self.client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY)
        self.model_name = settings.CONTENTBRAIN_MODEL
        self.system_prompt = self._load_system_prompt()
        self.preprocessor = Gen3aPreprocessor()

        # Generation config for video analysis
        self.config = types.GenerateContentConfig(
            system_instruction=self.system_prompt,
            temperature=1.0,  # Gemini 3 Pro optimized (thinking model)
            top_p=0.95,
            max_output_tokens=settings.GEMINI_MAX_OUTPUT_TOKENS,
            response_mime_type="application/json",
        )

        logger.info("GEN3a Service v1.6.0 initialized:")
        logger.info(f"  Model: {self.model_name}")
        logger.info(f"  System prompt: GEN3a v1.6.0")
        logger.info(f"  Preprocessor: Enabled")

    def _load_system_prompt(self) -> str:
        """Load GEN3a system prompt."""
        if not GEN3A_PROMPT_PATH.exists():
            logger.warning(f"GEN3a prompt not found: {GEN3A_PROMPT_PATH}")
            return self._get_fallback_prompt()

        with open(GEN3A_PROMPT_PATH, "r", encoding="utf-8") as f:
            prompt = f.read()

        logger.success(f"Loaded GEN3a system prompt: {GEN3A_PROMPT_PATH.name}")
        return prompt

    def _get_fallback_prompt(self) -> str:
        """Fallback prompt if config file missing."""
        return """You are GEN3a - Video Analyst v1.3.1.
Analyze video files and return JSON with:
- glitches: detected visual issues
- action_peaks: moments of high activity
- dead_spots: low activity zones
- speed_map: recommended speed adjustments
- visual_classification: content type per scene
Return ONLY valid JSON."""

    async def analyze_videos(
        self,
        video_paths: List[Path],
        gen1_brief: Dict[str, Any],
        gen2_brief: Dict[str, Any],
        music_path: Optional[Path] = None,
        voiceover_path: Optional[Path] = None,
        channel_context: Optional[Dict[str, Any]] = None,
        project_dir: Optional[Path] = None,
    ) -> Gen3aOutput:
        """
        Analyze all videos using Gemini Vision with preprocessing.

        v1.6.0 Flow:
        1. Run preprocessing (beats.json, vo_timing.json, audio_levels.json, reverse last scene)
        2. Replace last scene with reversed version
        3. Upload videos to Gemini
        4. Send analysis request with precomputed data
        5. Parse and return structured output

        Args:
            video_paths: List of video paths (1.mp4 - N.mp4)
            gen1_brief: GEN1 output (story, voiceover, easter egg)
            gen2_brief: GEN2 output (visual prompts, energy levels)
            music_path: Path to music.mp3 for beat analysis
            voiceover_path: Path to voiceover.mp3
            channel_context: Optional history for hook variety
            project_dir: Project directory for preprocessing outputs

        Returns:
            Gen3aOutput with complete analysis
        """
        logger.info("=" * 60)
        logger.info("GEN3a v1.6.0: Starting Video Analysis with Preprocessing")
        logger.info("=" * 60)
        logger.info(f"  Videos: {len(video_paths)}")
        logger.info(f"  Music: {'provided' if music_path else 'not provided'}")
        logger.info(f"  Voiceover: {'provided' if voiceover_path else 'not provided'}")

        try:
            # Determine project directory
            if project_dir is None and video_paths:
                # Get project root (parent of scene_N folder)
                project_dir = video_paths[0].parent.parent

            # ==========================================
            # STEP 1: PREPROCESSING (creates gen3a_work/)
            # ==========================================
            preprocessing_result = None
            beats_data = None
            vo_timing_data = None
            audio_levels_data = None

            if project_dir and len(video_paths) >= 1:
                if len(video_paths) < 6:
                    logger.warning(f"[GEN3a] Only {len(video_paths)} videos available for preprocessing (min 6)")
                if not music_path:
                    logger.warning("[GEN3a] No music path - beats analysis will use fallback")
                if not voiceover_path:
                    logger.warning("[GEN3a] No voiceover path - VO timing will use fallback")
                logger.info("Running preprocessing (creating gen3a_work/)...")
                preprocessing_result = await self.preprocessor.preprocess(
                    project_dir=project_dir,
                    video_paths=video_paths,
                    music_path=music_path,
                    voiceover_path=voiceover_path,
                )

                # Use preprocessed video paths (1.mp4-N.mp4 in gen3a_work/)
                if preprocessing_result.video_paths:
                    video_paths = preprocessing_result.video_paths
                    logger.info(f"Using preprocessed videos: {[p.name for p in video_paths]}")

                # Load precomputed data from gen3a_work/
                if preprocessing_result.beats_json_path.exists():
                    with open(preprocessing_result.beats_json_path, 'r', encoding='utf-8') as f:
                        beats_data = json.load(f)

                if preprocessing_result.vo_timing_json_path.exists():
                    with open(preprocessing_result.vo_timing_json_path, 'r', encoding='utf-8') as f:
                        vo_timing_data = json.load(f)

                if preprocessing_result.audio_levels_json_path.exists():
                    with open(preprocessing_result.audio_levels_json_path, 'r', encoding='utf-8') as f:
                        audio_levels_data = json.load(f)

            # ==========================================
            # STEP 2: BUILD ANALYSIS REQUEST
            # ==========================================
            request_content = self._build_analysis_request(
                gen1_brief=gen1_brief,
                gen2_brief=gen2_brief,
                beats_data=beats_data,
                vo_timing_data=vo_timing_data,
                audio_levels_data=audio_levels_data,
                channel_context=channel_context,
            )

            # ==========================================
            # STEP 3: UPLOAD VIDEOS TO GEMINI
            # ==========================================
            video_parts = []
            for i, video_path in enumerate(video_paths):
                if video_path.exists():
                    # Upload video to Gemini (async)
                    video_file = await self.client.aio.files.upload(file=video_path)
                    logger.info(f"  Uploaded video {i+1}: {video_path.name} -> {video_file.name}")

                    # Wait for file to be ACTIVE (processing takes time for videos)
                    video_file = await self._wait_for_file_active(video_file.name)
                    if video_file:
                        video_parts.append(video_file)
                        logger.info(f"  Video {i+1} is ACTIVE and ready")
                    else:
                        logger.warning(f"  Video {i+1} failed to become ACTIVE")
                else:
                    logger.warning(f"  Video not found: {video_path}")

            # ==========================================
            # STEP 4: GEMINI ANALYSIS
            # ==========================================
            if not video_parts:
                raise ValueError(f"No videos were successfully uploaded to Gemini ({len(video_paths)} videos attempted). Cannot produce analysis.")

            logger.info(f"Sending {len(video_parts)} videos to Gemini for analysis...")
            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=[request_content] + video_parts,
                config=self.config,
            )

            # Parse response — handle None/empty from safety filter
            raw_output = response.text
            if not raw_output:
                raise ValueError("Gemini returned empty response — content may have been blocked by safety filters")
            logger.info(f"Received response: {len(raw_output)} characters")

            # Log token usage
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                usage = response.usage_metadata
                input_tokens = getattr(usage, 'prompt_token_count', 0) or 0
                output_tokens = getattr(usage, 'candidates_token_count', 0) or 0
                total_tokens = getattr(usage, 'total_token_count', 0) or (input_tokens + output_tokens)
                logger.info(f"Token usage: {input_tokens:,} input + {output_tokens:,} output = {total_tokens:,} total")

            # Extract JSON
            analysis_data = self._parse_json_response(raw_output)

            # ==========================================
            # STEP 4.5: AUTOCORRECT (before model conversion)
            # ==========================================
            analysis_data, autocorrect_warnings = autocorrect_gen3a(
                analysis_data, gen1_brief=gen1_brief
            )
            if autocorrect_warnings:
                logger.info(f"GEN3a autocorrect: {len(autocorrect_warnings)} fixes applied")
                for aw in autocorrect_warnings[:10]:
                    logger.debug(f"  {aw}")

            # ==========================================
            # STEP 5: CONVERT TO OUTPUT MODEL
            # ==========================================
            output = self._convert_to_output(
                analysis_data,
                gen1_brief,
                beats_data=beats_data,
                vo_timing_data=vo_timing_data,
                audio_levels_data=audio_levels_data,
            )

            logger.success("=" * 60)
            logger.success("GEN3a v1.6.0: Analysis Complete")
            logger.success(f"  Scenes analyzed: {len(output.scenes)}")
            logger.success(f"  Total output duration: {output.gen3b_handoff.total_output_duration}s")
            logger.success(f"  Preprocessing: {'Success' if preprocessing_result and preprocessing_result.success else 'Partial/Skipped'}")
            logger.success("=" * 60)

            return output

        except Exception as e:
            logger.error(f"GEN3a analysis failed: {e}")
            raise

    async def _wait_for_file_active(
        self, file_name: str, timeout: int = 300, poll_interval: int = 5
    ):
        """
        Wait for an uploaded file to become ACTIVE in Gemini.

        Args:
            file_name: The name of the uploaded file
            timeout: Maximum time to wait in seconds (default 5 min)
            poll_interval: Time between status checks in seconds

        Returns:
            The file object if ACTIVE, None if timeout or failed
        """
        import asyncio
        import time

        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                file_info = await self.client.aio.files.get(name=file_name)
                state = getattr(file_info, 'state', None)

                if state is None:
                    # Try to get state from different attribute
                    state = getattr(file_info, 'status', 'UNKNOWN')

                state_str = str(state).upper()
                logger.debug(f"  File {file_name}: state={state_str}")

                # Handle both "ACTIVE" and "FileState.ACTIVE" formats
                if "ACTIVE" in state_str:
                    return file_info
                elif "FAILED" in state_str or "ERROR" in state_str:
                    logger.error(f"File processing failed: {file_name}")
                    return None

                # Wait before next check
                await asyncio.sleep(poll_interval)

            except Exception as e:
                logger.warning(f"Error checking file status: {e}")
                await asyncio.sleep(poll_interval)

        logger.error(f"Timeout waiting for file {file_name} to become ACTIVE")
        return None

    def _build_analysis_request(
        self,
        gen1_brief: Dict[str, Any],
        gen2_brief: Dict[str, Any],
        beats_data: Optional[Dict[str, Any]] = None,
        vo_timing_data: Optional[Dict[str, Any]] = None,
        audio_levels_data: Optional[Dict[str, Any]] = None,
        channel_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build the analysis request prompt for GEN3a v1.6.0."""
        request = f"""ANALYZE THE PREPROCESSED VIDEOS PROVIDED.

IMPORTANT v1.6.0 NOTES:
- Last scene (LOOP_CLOSE) is ALREADY PHYSICALLY REVERSED by Preprocessing Module
- Use precomputed beats.json for music data (DO NOT analyze music yourself)
- Use precomputed vo_timing.json for voiceover timing (DO NOT analyze voiceover audio yourself)
- Use precomputed audio_levels.json for ducking recommendations
- Get VO TEXT from gen1_brief.scenes[].voiceover_segment, NOT from vo_timing.json

## INPUT DATA

### gen1_brief.json:
```json
{json.dumps(gen1_brief, indent=2, ensure_ascii=False)}
```

### gen2_brief.json:
```json
{json.dumps(gen2_brief, indent=2, ensure_ascii=False)}
```
"""

        if beats_data:
            request += f"""
### beats.json (PRECOMPUTED - USE THIS DATA):
```json
{json.dumps(beats_data, indent=2, ensure_ascii=False)}
```
"""

        if vo_timing_data:
            request += f"""
### vo_timing.json (PRECOMPUTED - USE THIS DATA):
```json
{json.dumps(vo_timing_data, indent=2, ensure_ascii=False)}
```
"""

        if audio_levels_data:
            request += f"""
### audio_levels.json (PRECOMPUTED - USE THIS DATA):
```json
{json.dumps(audio_levels_data, indent=2, ensure_ascii=False)}
```
"""

        if channel_context:
            request += f"""
### channel_context.json:
```json
{json.dumps(channel_context, indent=2, ensure_ascii=False)}
```
"""

        request += """

## YOUR TASK

Analyze each video (1.mp4 through N.mp4) and provide:
1. Glitch detection with precise timestamps and salvage analysis
2. Action peaks with SFX recommendations
3. Dead spots with speed recommendations (NEVER CUT for boring content)
4. Speed map with motion density and techniques (RAMP_IN_OUT, WHIP_RAMP, etc.)
5. Visual type classification for content-aware effects
6. Easter egg verification (MANDATORY - use fallback if not visible)
7. VO segment timing from precomputed data
8. Punchline moments from [pause] tags
9. Narrative purpose speed modifiers from gen2_brief

CRITICAL:
- Final duration MUST be 18-25 seconds
- CUT only for glitches, SPEED for boring content
- Last scene (LOOP_CLOSE) is already reversed - do NOT flag reverse motion as glitch
- Use precomputed beats.json, vo_timing.json, audio_levels.json

Return ONLY valid JSON matching the Gen3aOutput schema.
Start with { and end with }
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
            logger.error(f"GEN3a: Failed to parse JSON from Gemini response: {e}")
            logger.error(f"GEN3a: Response text (first 500 chars): {text[:500]}")
            raise ValueError(f"Gemini returned invalid JSON: {e}") from e

    def _convert_to_output(
        self,
        data: Dict[str, Any],
        gen1_brief: Dict[str, Any],
        beats_data: Optional[Dict[str, Any]] = None,
        vo_timing_data: Optional[Dict[str, Any]] = None,
        audio_levels_data: Optional[Dict[str, Any]] = None,
    ) -> Gen3aOutput:
        """Convert parsed JSON to Gen3aOutput model with precomputed data."""
        # Parse scenes - GEN3a prompt uses "scene_analysis" key, not "scenes"
        scenes = []
        scene_list = data.get("scene_analysis") or data.get("scenes") or []
        for idx, scene_data in enumerate(scene_list):
            try:
                # Handle speed_map which may be nested in speed_analysis
                speed_analysis = scene_data.get("speed_analysis", {})
                speed_map_data = scene_data.get("speed_map", speed_analysis.get("speed_map", []))

                scene = Gen3aSceneAnalysis(
                    scene_number=scene_data.get("scene_number") or (idx + 1),
                    source_duration=scene_data.get("source_duration", 10.0),
                    output_duration=scene_data.get("output_duration",
                        speed_analysis.get("calculated_output_duration", 4.0)),
                    video_quality=scene_data.get("video_quality", 0.8),
                    glitches=[
                        GlitchDetection(**g) for g in scene_data.get("glitches", [])
                    ],
                    action_peaks=[
                        ActionPeak(**ap) for ap in scene_data.get("action_peaks", [])
                    ],
                    dead_spots=[
                        DeadSpot(**ds) for ds in scene_data.get("dead_spots", [])
                    ],
                    speed_map=[
                        SpeedSegment(**sm) for sm in speed_map_data
                    ],
                    visual_classification=VisualClassification(
                        **scene_data.get("visual_classification", {})
                    ) if scene_data.get("visual_classification") else VisualClassification(
                        primary_type="EPIC_WIDE"
                    ),
                    easter_egg_verification=EasterEggVerification(
                        **scene_data.get("easter_egg_verification", {})
                    ) if scene_data.get("easter_egg_verification") else EasterEggVerification(
                        found=False,
                        source_timestamp=0.0,
                        visibility_score=0.0,
                        position_in_frame="NOT_FOUND",
                        safe_zone_compliant=True,
                    ),
                    special_flags=scene_data.get("special_flags", []),
                )
                scenes.append(scene)
            except Exception as e:
                logger.warning(f"Failed to parse GEN3a scene {idx+1}: {e}")
                import traceback
                logger.debug(traceback.format_exc())

        if not scenes:
            raise ValueError(f"Failed to parse any scenes from Gemini response ({len(scene_list)} scenes in raw data)")

        # Parse music analysis - prefer precomputed data
        music_data = data.get("music_analysis", {})
        if beats_data:
            # Use precomputed beats data
            music_analysis = MusicAnalysis(
                bpm=beats_data.get("bpm", 120.0),
                time_signature=beats_data.get("time_signature", "4/4"),
                strong_beats_for_cuts=beats_data.get("strong_beats_only", []),
                beats=[MusicBeat(**b) for b in beats_data.get("beats", [])],
            )
        else:
            music_analysis = MusicAnalysis(
                bpm=music_data.get("bpm", 120.0),
                time_signature=music_data.get("time_signature", "4/4"),
                strong_beats_for_cuts=music_data.get("strong_beats_for_cuts",
                    music_data.get("downbeats", [])),
                beats=[MusicBeat(**b) for b in music_data.get("beats", [])],
            )

        # Parse VO segments - prefer precomputed data
        vo_segments = []
        if vo_timing_data:
            # Create VO segments from precomputed timing + gen1_brief text
            # Use TEXT MATCHING to map librosa SPEECH segments to gen1_brief scenes
            # (librosa may split one scene's VO into multiple SPEECH segments)
            import re as _re
            gen1_scenes = gen1_brief.get("scenes", [])

            # Build clean text lookup for each scene
            scene_vo_texts = []
            for si, scene in enumerate(gen1_scenes):
                raw = scene.get("voiceover_segment", "") or scene.get("voiceover", "")
                clean = _re.sub(r'\[[^\]]+\]', '', raw).strip().lower()
                clean = _re.sub(r'<[^>]+>', '', clean).strip()
                clean = ' '.join(clean.split())
                scene_vo_texts.append({
                    'scene_number': scene.get('scene_number') or (si + 1),
                    'text_lower': clean,
                    'raw': raw,
                })

            # Match SPEECH segments to scenes using text overlap
            # Multiple SPEECH segments can belong to one scene (librosa splits on pauses)
            speech_segments = [s for s in vo_timing_data.get("segments", []) if s.get("type") == "SPEECH"]

            # Track which scenes have been matched (merge multi-segment scenes)
            scene_segments: dict = {}  # scene_idx -> list of speech segments

            current_scene_idx = 0
            for seg_i, segment in enumerate(speech_segments):
                # Try to find best matching scene by advancing from current position
                # If current scene has no VO text (empty), skip it
                best_idx = current_scene_idx

                # Skip scenes with empty VO text
                while best_idx < len(scene_vo_texts) and not scene_vo_texts[best_idx]['text_lower']:
                    best_idx += 1

                # Cap to valid range — fall back to last scene that actually has VO text
                if best_idx >= len(scene_vo_texts):
                    best_idx = len(scene_vo_texts) - 1
                    while best_idx > 0 and not scene_vo_texts[best_idx]['text_lower']:
                        best_idx -= 1

                if best_idx not in scene_segments:
                    scene_segments[best_idx] = []
                scene_segments[best_idx].append(segment)

                # Check if this scene's text is "complete" by looking at accumulated segments
                # Move to next scene when segments cover roughly the expected text
                accumulated_duration = sum(
                    s.get("end", 0) - s.get("start", 0) for s in scene_segments[best_idx]
                )
                # Heuristic: if accumulated >2s or next segment starts after gap, advance
                if accumulated_duration > 1.5 and seg_i < len(speech_segments) - 1:
                    next_start = speech_segments[seg_i + 1].get("start", 0)
                    current_end = segment.get("end", 0)
                    if next_start - current_end > 0.3:  # Gap between segments = new scene
                        current_scene_idx = best_idx + 1

            # Build VO segments from merged data
            for scene_idx, scene_info in enumerate(scene_vo_texts):
                segs = scene_segments.get(scene_idx, [])
                if not segs and not scene_info['text_lower']:
                    # Empty VO scene (e.g., loop scene) — skip
                    continue
                if not segs:
                    # Scene has text but no matching speech segment — use estimated timing
                    continue

                scene_num = scene_info.get('scene_number', scene_idx + 1)
                source_start = min(s.get("start", 0.0) for s in segs)
                source_end = max(s.get("end", 0.0) for s in segs)

                # Detect style from text tags (v8.4.0: [calm] added, [silence] = no VO)
                raw_text = scene_info.get('raw', '')
                style_tag = "NORMAL"
                raw_lower = raw_text.lower()
                if '[silence]' in raw_lower:
                    style_tag = "SILENCE"
                elif '[whispers]' in raw_lower or '[whisper]' in raw_lower:
                    style_tag = "WHISPER"
                elif '[calm]' in raw_lower:
                    style_tag = "CALM"
                # Legacy tag detection (banned in v8.4.0 but may appear in old briefs)
                elif '[excited]' in raw_lower or '[excitement]' in raw_lower:
                    style_tag = "EXCITED"
                elif '[dramatic]' in raw_lower:
                    style_tag = "DRAMATIC"

                vo_segments.append(VOSegmentAnalysis(
                    segment_id=f"VO{scene_num}",
                    text=raw_text,
                    source_start=source_start,
                    source_end=source_end,
                    style_tag=style_tag,
                    recommended_subtitle_style=style_tag,
                ))
        else:
            vo_segments = [
                VOSegmentAnalysis(**vo) for vo in data.get("vo_segments", [])
            ]

        # Parse hook variety
        hook_data = data.get("hook_variety_analysis", {})
        recommended_hook = hook_data.get("recommended_hook_style", {})
        hook_variety = HookVarietyAnalysis(
            recommended_style=recommended_hook.get("style",
                hook_data.get("recommended_style", "CLASSIC")),
            reasoning=recommended_hook.get("reason",
                hook_data.get("reasoning", "")),
            avoid_styles=hook_data.get("avoided_styles",
                hook_data.get("avoid_styles", [])),
            scene1_energy=hook_data.get("scene_1_visual_type",
                hook_data.get("scene1_energy", "HIGH")),
        )

        # Parse handoff with audio ducking from precomputed data
        handoff_data = data.get("gen3b_handoff", {})

        # Calculate total duration from scenes if not provided
        total_duration = handoff_data.get("total_output_duration", 0.0)
        if not total_duration and scenes:
            total_duration = sum(s.output_duration for s in scenes)

        # Build cumulative scene starts
        cumulative_starts = handoff_data.get("cumulative_scene_starts", {})
        if not cumulative_starts and scenes:
            current_start = 0.0
            for scene in scenes:
                cumulative_starts[f"scene_{scene.scene_number}"] = current_start
                current_start += scene.output_duration

        handoff = Gen3bHandoff(
            total_output_duration=total_duration or 25.0,
            cumulative_scene_starts=cumulative_starts,
            loop_compliant=handoff_data.get("loop_compliant", True),
        )

        return Gen3aOutput(
            version="1.6.0",
            project_id=gen1_brief.get("project_id", ""),
            analysis_timestamp=datetime.now().isoformat(),
            scenes=scenes,
            music_analysis=music_analysis,
            vo_segments=vo_segments,
            hook_variety_analysis=hook_variety,
            gen3b_handoff=handoff,
        )

    async def analyze_single_video(
        self,
        video_path: Path,
        scene_number: int,
        gen2_scene: Dict[str, Any],
    ) -> Gen3aSceneAnalysis:
        """
        Analyze a single video for quick testing.

        Args:
            video_path: Path to video file
            scene_number: Scene number (1-N)
            gen2_scene: GEN2 scene data

        Returns:
            Gen3aSceneAnalysis for this scene
        """
        logger.info(f"Analyzing single video: Scene {scene_number}")

        # Simple prompt for single video
        prompt = f"""Analyze this video (Scene {scene_number}):

Visual intent: {gen2_scene.get('visual_description', '')}
Energy level: {gen2_scene.get('energy_level', 'MEDIUM')}

Return JSON with:
- glitches: array of detected issues
- action_peaks: array of high-activity moments
- dead_spots: array of low-activity zones
- speed_map: array of speed segments
- visual_classification: object with primary_type, confidence, etc.

JSON only, no markdown."""

        try:
            video_file = await self.client.aio.files.upload(file=video_path)
            # Wait for file to become ACTIVE before sending to Gemini
            active_file = await self._wait_for_file_active(video_file.name)
            if not active_file:
                raise RuntimeError(f"Video {video_path.name} failed to become ACTIVE in Gemini")
            video_file = active_file

            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=[prompt, video_file],
                config=self.config,
            )

            raw_text = response.text
            if not raw_text:
                raise ValueError("Gemini returned empty response — content may have been blocked by safety filters")
            data = self._parse_json_response(raw_text)

            return Gen3aSceneAnalysis(
                scene_number=scene_number,
                source_duration=10.0,
                output_duration=data.get("output_duration", 4.0),
                video_quality=data.get("video_quality", 0.8),
                glitches=[GlitchDetection(**g) for g in data.get("glitches", [])],
                action_peaks=[ActionPeak(**ap) for ap in data.get("action_peaks", [])],
                dead_spots=[DeadSpot(**ds) for ds in data.get("dead_spots", [])],
                speed_map=[SpeedSegment(**sm) for sm in data.get("speed_map", [])],
                visual_classification=VisualClassification(
                    **data.get("visual_classification", {"primary_type": "EPIC_WIDE"})
                ),
            )

        except Exception as e:
            logger.error(f"Single video analysis failed: {e}")
            raise


# ============================================================================
# EXPORT
# ============================================================================

__all__ = ["Gen3aService"]
