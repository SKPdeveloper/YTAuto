"""
Audio Engine - 5-Layer Audio System for Glaze City

This module provides:
1. AudioEngine - ElevenLabs TTS for voiceover generation
2. AudioMixer - 5-layer audio mixing with ducking support

5-Layer Audio System:
- BED: Ambient bed (volume: 0.15)
- MUSIC: Background music from SUNO (volume: 0.3, ducked to 0.15 during VO)
- SFX: Impact sounds at transitions (volume: 0.7)
- FOLEY: Food sounds at food moments (volume: 0.5)
- VO: Voiceover - highest priority (volume: 1.0)

Features:
- Async-first with AsyncElevenLabs client
- SSML break tags for pause markers [0.3s] -> <break time="0.3s"/>
- Multi-layer audio mixing with priority
- Auto-ducking: MUSIC volume drops during VO segments
- Beat-aligned SFX triggers

API Documentation: https://elevenlabs.io/docs/api-reference/text-to-speech/convert
"""

import re
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, List

from app.core.config import settings
from app.utils.logger import logger
from app.services.glaze_models import VoiceoverSettings, VoiceoverConfig


class AudioEngine:
    """
    Client for ElevenLabs TTS API - generates voiceovers from text

    Workflow:
    1. Convert pause markers [0.3s] to SSML <break time="0.3s"/>
    2. Call ElevenLabs API with voice settings
    3. Save audio to file

    Features:
    - Automatic pause marker conversion
    - Configurable voice settings from project_brief.json
    - Multiple output formats (mp3, wav)
    - Async file operations
    """

    # Regex pattern to match pause markers like [0.3s], [0.5s], [1s], [1.5s]
    PAUSE_PATTERN = re.compile(r'\[(\d+(?:\.\d+)?)\s*s\]')

    @staticmethod
    def _sanitize_stability_for_model(stability: float, model_id: str) -> float:
        """
        Sanitize stability value based on model restrictions.

        eleven_v3 accepts continuous float 0.0-1.0 (discrete restriction removed —
        was an alpha-era server limitation, API now accepts any value).
        Clamps to [0.0, 1.0] range for safety.
        """
        return max(0.0, min(1.0, stability))

    def __init__(self):
        """Initialize ElevenLabs client with credentials from .env"""
        self.api_key = settings.ELEVENLABS_API_KEY
        self.model_id = settings.ELEVENLABS_MODEL
        self.default_voice_id = settings.ELEVENLABS_DEFAULT_VOICE_ID
        self.output_format = settings.ELEVENLABS_OUTPUT_FORMAT

        # Processing settings
        self.max_retries = settings.MAX_RETRIES
        self.request_timeout = settings.REQUEST_TIMEOUT

        # Validate API key
        if not self.api_key:
            logger.warning("ElevenLabs API key not configured. Set ELEVENLABS_API_KEY in .env")

        logger.info("AudioEngine initialized:")
        logger.info(f"  Model: {self.model_id}")
        logger.info(f"  Default Voice: {self.default_voice_id}")
        logger.info(f"  Output Format: {self.output_format}")

    # Common voice name to ID mapping (pre-built voices)
    VOICE_NAME_MAP = {
        "adam": "pNInz6obpgDQGcFmaJgB",
        "rachel": "21m00Tcm4TlvDq8ikWAM",
        "domi": "AZnzlk1XvdvUeBnXmlld",
        "bella": "EXAVITQu4vr4xnSDxMaL",
        "antoni": "ErXwobaYiN019PkySvjV",
        "elli": "MF3mGyEYCl7XYWbV9V6O",
        "josh": "TxGEqnHWrfWFTfGW9XjX",
        "arnold": "VR6AewLTigWG4xSOukaG",
        "sam": "yoZ06aMxZJJ28mfd3POQ",
    }

    async def _resolve_voice_id(self, voice_id_or_name: str) -> str:
        """
        Resolve voice name to voice_id if needed

        Args:
            voice_id_or_name: Either a voice_id or a voice name like "Adam"

        Returns:
            Actual voice_id string

        Note:
            If the input looks like a voice_id (20+ chars, alphanumeric),
            it's returned as-is. Otherwise, we try to match it as a name.
        """
        # Check if it looks like a voice_id (20+ alphanumeric chars)
        if len(voice_id_or_name) >= 20 and voice_id_or_name.isalnum():
            return voice_id_or_name

        # Try to resolve from pre-built mapping
        name_lower = voice_id_or_name.lower()
        if name_lower in self.VOICE_NAME_MAP:
            resolved = self.VOICE_NAME_MAP[name_lower]
            logger.debug(f"Resolved voice name '{voice_id_or_name}' -> {resolved}")
            return resolved

        # Try to fetch from API
        try:
            actual_id = await self.get_voice_id_by_name(voice_id_or_name)
            if actual_id:
                return actual_id
        except Exception as e:
            logger.warning(f"Failed to resolve voice name '{voice_id_or_name}': {e}")

        # Return as-is if resolution failed
        logger.warning(f"Could not resolve voice '{voice_id_or_name}', using as-is")
        return voice_id_or_name

    def _convert_pause_markers(self, text: str) -> str:
        """
        Convert pause markers to SSML break tags

        Examples:
            [0.3s] -> <break time="0.3s"/>
            [0.5s] -> <break time="0.5s"/>
            [1s]   -> <break time="1s"/>
            [1.5s] -> <break time="1.5s"/>

        Args:
            text: Input text with [Xs] pause markers

        Returns:
            Text with SSML <break time="Xs"/> tags

        Note:
            ElevenLabs supports breaks up to 3 seconds.
            Breaks are billed at 10 characters each.
        """
        def replace_pause(match: re.Match) -> str:
            duration = match.group(1)
            # Ensure max 3 seconds per ElevenLabs limit
            try:
                duration_float = float(duration)
                if duration_float > 3.0:
                    logger.warning(f"Pause duration {duration}s exceeds 3s limit, capping to 3s")
                    duration = "3"
            except ValueError:
                pass
            return f'<break time="{duration}s"/>'

        converted = self.PAUSE_PATTERN.sub(replace_pause, text)

        # v8.4.0: Convert [silence] tag to a 1.5s SSML break (ElevenLabs doesn't support [silence])
        # Money shot scenes use [silence] to mark "no voice here — only ASMR SFX"
        silence_count = converted.lower().count('[silence]')
        if silence_count > 0:
            converted = re.sub(r'\[silence\]', '<break time="1.5s"/>', converted, flags=re.IGNORECASE)
            logger.debug(f"Converted {silence_count} [silence] markers to 1.5s SSML breaks")

        # Log conversion stats
        original_pauses = len(self.PAUSE_PATTERN.findall(text))
        if original_pauses > 0:
            logger.debug(f"Converted {original_pauses} pause markers to SSML break tags")

        return converted

    async def generate_voiceover(
        self,
        text: str,
        voice_settings: Optional[VoiceoverSettings] = None,
        voice_id: Optional[str] = None,
    ) -> bytes:
        """
        Generate voiceover audio from text

        Args:
            text: Script text with optional [Xs] pause markers
            voice_settings: Voice configuration (stability, similarity_boost, etc.)
            voice_id: Override voice ID (uses default if not provided)

        Returns:
            Audio bytes (MP3 format by default)

        Raises:
            Exception: If generation fails after all retries

        Example:
            >>> engine = AudioEngine()
            >>> audio = await engine.generate_voiceover(
            ...     "Welcome to Glaze City. [0.5s] Your destination awaits.",
            ...     voice_settings=VoiceoverSettings(stability=0.5)
            ... )
        """
        if not text or not text.strip():
            raise ValueError("Empty voiceover text — cannot generate audio from empty input")

        from elevenlabs import AsyncElevenLabs, VoiceSettings

        # Convert pause markers to SSML
        ssml_text = self._convert_pause_markers(text)

        # Resolve voice ID - check if it's a name that needs resolution
        raw_voice_id = voice_id or (
            voice_settings.voice_id if voice_settings else None
        ) or self.default_voice_id

        # If voice_id looks like a name (not a UUID-like string), try to resolve it
        effective_voice_id = await self._resolve_voice_id(raw_voice_id)

        # Build voice settings (with model-specific sanitization)
        if voice_settings:
            sanitized_stability = self._sanitize_stability_for_model(
                voice_settings.stability, self.model_id
            )
            elevenlabs_kwargs = dict(
                stability=sanitized_stability,
                similarity_boost=voice_settings.similarity_boost,
                style=voice_settings.style,
                speed=getattr(voice_settings, 'speed', 1.05),
            )
            # use_speaker_boost is NOT supported by eleven_v3 — only pass for v2/turbo
            if "eleven_v3" not in self.model_id:
                elevenlabs_kwargs["use_speaker_boost"] = voice_settings.speaker_boost
            elevenlabs_settings = VoiceSettings(**elevenlabs_kwargs)
        else:
            elevenlabs_settings = None

        logger.info(f"Generating voiceover...")
        logger.info(f"  Voice ID: {effective_voice_id}")
        logger.info(f"  Model: {self.model_id}")
        logger.info(f"  Text length: {len(text)} chars")
        logger.debug(f"  SSML text: {ssml_text[:100]}...")

        retries = 0
        while retries <= self.max_retries:
            try:
                # Initialize async client
                client = AsyncElevenLabs(api_key=self.api_key)

                # Generate audio - convert() returns an async generator directly
                audio_generator = client.text_to_speech.convert(
                    text=ssml_text,
                    voice_id=effective_voice_id,
                    model_id=self.model_id,
                    output_format=self.output_format,
                    voice_settings=elevenlabs_settings,
                )

                # Collect audio bytes from generator
                audio_chunks = []
                async for chunk in audio_generator:
                    audio_chunks.append(chunk)

                audio_bytes = b"".join(audio_chunks)

                logger.success(f"Voiceover generated: {len(audio_bytes)} bytes")
                return audio_bytes

            except Exception as e:
                retries += 1
                logger.error(
                    f"Voiceover generation error (attempt {retries}/{self.max_retries + 1}): {e}"
                )

                if retries > self.max_retries:
                    logger.error("All retries exhausted for voiceover generation")
                    raise

                wait_time = 5 * retries
                logger.info(f"Waiting {wait_time}s before retry...")
                await asyncio.sleep(wait_time)

    async def generate_voiceover_with_timestamps(
        self,
        text: str,
        voice_settings: Optional[VoiceoverSettings] = None,
        voice_id: Optional[str] = None,
    ) -> tuple[bytes, dict]:
        """
        Generate voiceover with character-level timestamps from ElevenLabs.

        Returns:
            Tuple of (audio_bytes, alignment_data)
            alignment_data contains:
            - characters: list of characters
            - character_start_times_seconds: list of start times
            - character_end_times_seconds: list of end times
        """
        from elevenlabs import AsyncElevenLabs, VoiceSettings
        import base64

        if not text or not text.strip():
            raise ValueError("Empty voiceover text — cannot generate audio from empty input")

        ssml_text = self._convert_pause_markers(text)

        raw_voice_id = voice_id or (
            voice_settings.voice_id if voice_settings else None
        ) or self.default_voice_id
        effective_voice_id = await self._resolve_voice_id(raw_voice_id)

        if voice_settings:
            sanitized_stability = self._sanitize_stability_for_model(
                voice_settings.stability, self.model_id
            )
            elevenlabs_kwargs = dict(
                stability=sanitized_stability,
                similarity_boost=voice_settings.similarity_boost,
                style=voice_settings.style,
                speed=getattr(voice_settings, 'speed', 1.05),
            )
            if "eleven_v3" not in self.model_id:
                elevenlabs_kwargs["use_speaker_boost"] = voice_settings.speaker_boost
            elevenlabs_settings = VoiceSettings(**elevenlabs_kwargs)
        else:
            elevenlabs_settings = None

        logger.info(f"Generating voiceover with timestamps...")
        logger.info(f"  Voice ID: {effective_voice_id}")
        logger.info(f"  Text length: {len(text)} chars")

        retries = 0
        while retries <= self.max_retries:
            try:
                client = AsyncElevenLabs(api_key=self.api_key)

                response = await client.text_to_speech.convert_with_timestamps(
                    text=ssml_text,
                    voice_id=effective_voice_id,
                    model_id=self.model_id,
                    output_format=self.output_format,
                    voice_settings=elevenlabs_settings,
                )

                audio_bytes = base64.b64decode(response.audio_base_64)

                if not response.alignment or not response.alignment.characters:
                    raise ValueError(
                        "ElevenLabs returned empty alignment data. "
                        "Cannot generate word-by-word subtitles without character timestamps."
                    )

                chars = response.alignment.characters
                starts = response.alignment.character_start_times_seconds
                ends = response.alignment.character_end_times_seconds

                if len(chars) != len(starts) or len(chars) != len(ends):
                    raise ValueError(
                        f"ElevenLabs alignment array length mismatch: "
                        f"chars={len(chars)}, starts={len(starts)}, ends={len(ends)}"
                    )

                alignment_data = {
                    'characters': chars,
                    'character_start_times_seconds': starts,
                    'character_end_times_seconds': ends,
                }

                logger.success(f"Voiceover with timestamps: {len(audio_bytes)} bytes, {len(alignment_data['characters'])} chars aligned")
                return audio_bytes, alignment_data

            except ValueError:
                # Non-transient data validation errors — don't retry
                raise
            except Exception as e:
                retries += 1
                logger.error(f"Voiceover+timestamps error (attempt {retries}/{self.max_retries + 1}): {e}")
                if retries > self.max_retries:
                    raise
                await asyncio.sleep(5 * retries)

    async def generate_and_save_voiceover(
        self,
        text: str,
        output_path: Path,
        voice_settings: Optional[VoiceoverSettings] = None,
        voice_id: Optional[str] = None,
    ) -> Path:
        """
        Generate voiceover and save to file

        Args:
            text: Script text with optional pause markers
            output_path: Path where to save the audio file
            voice_settings: Voice configuration
            voice_id: Override voice ID

        Returns:
            Path to the saved audio file

        Example:
            >>> path = await engine.generate_and_save_voiceover(
            ...     voiceover_config.full_script,
            ...     Path("projects/test/voiceover.mp3"),
            ...     voice_settings=voiceover_config.settings
            ... )
        """
        # Generate audio
        audio_bytes = await self.generate_voiceover(
            text=text,
            voice_settings=voice_settings,
            voice_id=voice_id,
        )

        # Ensure parent directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Save to file
        output_path.write_bytes(audio_bytes)

        logger.success(f"Voiceover saved: {output_path}")
        return output_path

    async def generate_project_voiceover(
        self,
        voiceover_config: VoiceoverConfig,
        project_dir: Path,
        filename: str = "voiceover.mp3",
    ) -> Path:
        """
        Generate voiceover for a project using its VoiceoverConfig

        This is the main method for generating voiceovers from project_brief.json

        Args:
            voiceover_config: VoiceoverConfig from project (contains settings + full_script)
            project_dir: Project directory where to save the audio
            filename: Output filename (default: voiceover.mp3)

        Returns:
            Path to the saved voiceover file

        Example:
            >>> from app.services.glaze_models import GlazeCityProject
            >>> project = GlazeCityProject.parse_file("project_brief.json")
            >>> path = await engine.generate_project_voiceover(
            ...     project.voiceover,
            ...     Path("projects/my_project")
            ... )
        """
        logger.info(f"Generating project voiceover...")
        logger.info(f"  Script length: {len(voiceover_config.full_script)} chars")
        logger.info(f"  Expected duration: {voiceover_config.total_duration_seconds}s")
        logger.info(f"  Voice: {voiceover_config.settings.voice_id}")

        output_path = project_dir / filename

        return await self.generate_and_save_voiceover(
            text=voiceover_config.full_script,
            output_path=output_path,
            voice_settings=voiceover_config.settings,
        )

    async def generate_voiceover_and_subtitles(
        self,
        voiceover_config: VoiceoverConfig,
        project_dir: Path,
        hook_offset: float = 0.3,
    ) -> tuple[Path, Path, Path, Path]:
        """
        Generate voiceover with timestamps and create synced subtitles.

        This is the RECOMMENDED method for generating voiceover - it ensures
        subtitles are perfectly synced with the audio.

        Args:
            voiceover_config: VoiceoverConfig from project
            project_dir: Project directory
            hook_offset: Time offset for hook at video start (default 0.3s)

        Returns:
            Tuple of (voiceover_path, alignment_path, subtitles_path, timing_path)
        """
        import json
        import re

        logger.info(f"Generating voiceover with synced subtitles...")
        logger.info(f"  Script: {voiceover_config.full_script[:60]}...")
        logger.info(f"  Hook offset: {hook_offset}s")

        # Generate voiceover with timestamps — retry with speed adjustment if overrun
        expected_duration = voiceover_config.total_duration_seconds
        max_retries = 2  # original + 1 retry
        current_speed = getattr(voiceover_config.settings, 'speed', 1.0)

        audio_bytes = None
        alignment = None
        ratio = 1.0

        for attempt in range(max_retries):
            voiceover_config.settings.speed = current_speed
            audio_bytes, alignment = await self.generate_voiceover_with_timestamps(
                text=voiceover_config.full_script,
                voice_settings=voiceover_config.settings,
            )

            # Measure actual duration from alignment
            end_times = alignment.get("character_end_times_seconds", [])
            actual_duration = end_times[-1] if end_times else 0.0
            ratio = actual_duration / expected_duration if expected_duration > 0 else 1.0

            logger.info(
                f"  TTS attempt {attempt + 1}: actual={actual_duration:.1f}s, "
                f"expected={expected_duration:.1f}s, ratio={ratio:.2f}x, speed={current_speed}"
            )

            if ratio <= 1.15:
                break

            if attempt < max_retries - 1:
                needed_speed = min(current_speed * ratio, 1.2)
                if needed_speed > current_speed + 0.01:
                    logger.info(f"  VO overrun {ratio:.2f}x — retrying with speed={needed_speed:.2f}")
                    current_speed = round(needed_speed, 2)
                else:
                    logger.warning(f"  VO overrun {ratio:.2f}x but speed already at max {current_speed}")
                    break

        if ratio > 1.3:
            end_times = alignment.get("character_end_times_seconds", [])
            actual_duration = end_times[-1] if end_times else 0.0
            logger.error(
                f"  VO DURATION WARNING: {actual_duration:.1f}s for {expected_duration:.1f}s "
                f"video ({ratio:.1f}x) even after speed={current_speed}"
            )

        # Save audio
        voiceover_path = project_dir / "voiceover.mp3"
        voiceover_path.write_bytes(audio_bytes)
        logger.success(f"Voiceover saved: {voiceover_path}")

        # Save alignment (character-level)
        alignment_path = project_dir / "vo_alignment.json"
        with open(alignment_path, 'w', encoding='utf-8') as f:
            json.dump(alignment, f, indent=2, ensure_ascii=False)
        logger.success(f"Alignment saved: {alignment_path}")

        # Generate voiceover_timing.json FIRST (needed by subtitles for Easter Egg positioning)
        timing_path = project_dir / "voiceover_timing.json"
        self._generate_voiceover_timing(alignment, project_dir, timing_path, hook_offset)
        logger.success(f"Timing saved: {timing_path}")

        # Generate subtitles from alignment (Netflix-style, word-by-word)
        # Must come AFTER timing so voiceover_timing.json exists for Easter Egg scene detection
        subtitles_path = project_dir / "subtitles.ass"

        # Resolve subtitle title from channel branding
        sub_title = "Glaze City Subtitles"
        try:
            brief_path = project_dir / "project_brief.json"
            if brief_path.exists():
                with open(brief_path, 'r', encoding='utf-8') as f:
                    brief = json.load(f)
                channel_id = brief.get("publish_config", {}).get("target_channel", "glaze_city")
                from app.utils.prompt_loader import load_channel_branding
                branding = load_channel_branding(channel_id)
                sub_title = branding.get("{{SUBTITLE_TITLE}}", sub_title)
        except Exception as e:
            logger.debug(f"Could not resolve subtitle title from branding: {e}")

        self._generate_subtitles_from_alignment(alignment, output_path=subtitles_path, project_dir=project_dir, hook_offset=hook_offset, subtitle_title=sub_title)
        logger.success(f"Subtitles saved: {subtitles_path}")

        return voiceover_path, alignment_path, subtitles_path, timing_path

    def _generate_subtitles_from_alignment(
        self,
        alignment: dict,
        output_path: Path,
        project_dir: Path = None,
        hook_offset: float = 0.3,
        subtitle_title: str = "Glaze City Subtitles",
    ) -> None:
        """
        Generate Netflix-style ASS subtitle file with WORD-BY-WORD display.

        Uses ElevenLabs character-level timestamps for precise word timing.
        Style: Montserrat-Bold, 72px, white, shadow 2px, no stroke, UPPERCASE.

        Args:
            alignment: ElevenLabs alignment data with character timestamps
            output_path: Path to save subtitles.ass
            project_dir: Project directory (to find easter_egg scene)
            hook_offset: Time offset for hook at video start (default 0.3s)
        """
        import re
        import json

        chars = alignment['characters']
        starts = alignment['character_start_times_seconds']
        ends = alignment['character_end_times_seconds']

        # Find easter egg scene number from project_brief
        easter_egg_scene = None
        if project_dir:
            project_brief_path = project_dir / "project_brief.json"
            if project_brief_path.exists():
                with open(project_brief_path, 'r', encoding='utf-8') as f:
                    brief = json.load(f)
                # Easter egg is usually in engagement section
                easter_egg_info = brief.get('engagement', {}).get('easter_egg', {})
                if easter_egg_info:
                    # Try to find scene number from location or scene field
                    easter_egg_scene = easter_egg_info.get('scene_number') or easter_egg_info.get('scene')
                    if not easter_egg_scene:
                        # Default to middle scene if not specified
                        total = len(brief.get('scenes', []))
                        easter_egg_scene = max(2, total // 2) if total else 4
                    logger.info(f"  Easter egg detected in scene {easter_egg_scene}")

        # Load voiceover_timing.json to map words to scenes (needed for merge/bleed protection)
        scene_timings = []
        if project_dir:
            timing_path = project_dir / "voiceover_timing.json"
            if timing_path.exists():
                with open(timing_path, 'r', encoding='utf-8') as f:
                    timing_data = json.load(f)
                for seg in timing_data.get('segments', []):
                    scene_timings.append({
                        'scene': seg.get('scene_number', 0),
                        'start': seg.get('start_time', 0) + hook_offset,
                        'end': seg.get('end_time', 0) + hook_offset,
                    })

        def get_scene_for_time(t: float) -> int:
            """Find which scene a timestamp belongs to."""
            for st in scene_timings:
                if st['start'] <= t <= st['end']:
                    return st['scene']
            return 0

        # Parse words with their exact timestamps from character-level data
        words = []
        current_word = ''
        word_start = 0.0
        word_end = 0.0
        in_tag = False  # Track if we're inside a [tag]
        in_xml_tag = False  # Track if we're inside an <xml> tag (SSML break tags etc.)

        for i, char in enumerate(chars):
            # Handle style tags like [whispers], [pause], etc.
            if char == '[':
                in_tag = True
                continue
            if char == ']':
                in_tag = False
                continue
            if in_tag:
                continue

            # Handle XML-style tags like <break time="0.5s"/>
            if char == '<':
                in_xml_tag = True
                continue
            if char == '>':
                in_xml_tag = False
                continue
            if in_xml_tag:
                continue

            # Start new word
            if current_word == '' and char not in ' \n\t':
                word_start = starts[i]

            # Build word
            if char not in ' \n\t':
                current_word += char
                word_end = ends[i]
            else:
                # End of word - save it
                if current_word and len(current_word) >= 1:
                    # Remove punctuation for cleaner display but keep word
                    display_word = current_word.rstrip('.,!?;:')
                    if display_word:
                        words.append({
                            'word': display_word.upper(),  # UPPERCASE
                            'start': word_start + hook_offset,
                            'end': word_end + hook_offset,
                            'scene': get_scene_for_time(word_start + hook_offset),
                        })
                current_word = ''

        # Don't forget last word
        if current_word and len(current_word) >= 1:
            display_word = current_word.rstrip('.,!?;:')
            if display_word:
                words.append({
                    'word': display_word.upper(),
                    'start': word_start + hook_offset,
                    'end': word_end + hook_offset,
                    'scene': get_scene_for_time(word_start + hook_offset),
                })

        # ================================================================
        # GROUP SHORT WORDS: Merge articles/prepositions with next word
        # Rule: the/a/an/is/are/was/were/in/on/at/to/of/for/and/but/or/do/not/has/had + next word = one chunk
        # ================================================================
        MERGE_WORDS = {
            'THE', 'A', 'AN', 'IS', 'ARE', 'WAS', 'WERE',
            'IN', 'ON', 'AT', 'TO', 'OF', 'FOR', 'BY', 'WITH',
            'AND', 'BUT', 'OR', 'SO', 'DO', 'NOT', "DON'T",
            'HAS', 'HAD', 'HAVE', 'WILL', 'BE', 'IT', "IT'S",
            'I', 'YOU', 'WE', 'HE', 'SHE', 'THEY',
            'THIS', 'THAT', 'THESE', 'THOSE',
            'MY', 'YOUR', 'OUR', 'HIS', 'HER', 'ITS', 'THEIR',
        }

        grouped_words = []
        i = 0
        while i < len(words):
            current = words[i]

            # Check if current word should be merged with next
            if current['word'] in MERGE_WORDS and i + 1 < len(words):
                next_word = words[i + 1]
                # Don't merge across scene boundaries (Fix #8 cross-scene subtitle merge)
                same_scene = current.get('scene', 0) == next_word.get('scene', 0) or current.get('scene', 0) == 0
                if same_scene:
                    # Merge: combine text, use start of first, end of last
                    grouped_words.append({
                        'word': f"{current['word']} {next_word['word']}",
                        'start': current['start'],
                        'end': next_word['end'],
                        'scene': current.get('scene', 0),
                    })
                    i += 2  # Skip both words
                else:
                    grouped_words.append(current)
                    i += 1
            else:
                grouped_words.append(current)
                i += 1

        words = grouped_words

        # Enforce minimum word display duration (0.3s) — prevents
        # invisible flashes like "STILL" showing for 0.05s
        MIN_WORD_DURATION = 0.3
        for idx in range(len(words)):
            w = words[idx]
            if w['end'] - w['start'] < MIN_WORD_DURATION:
                desired_end = w['start'] + MIN_WORD_DURATION
                # Don't overlap with next word
                if idx + 1 < len(words):
                    desired_end = min(desired_end, words[idx + 1]['start'] - 0.02)
                w['end'] = max(w['end'], desired_end)

        # Clamp subtitle end times to scene VO boundaries (Fix #10 subtitle bleed)
        scene_end_map = {st['scene']: st['end'] for st in scene_timings}
        for w in words:
            w_scene = w.get('scene', 0)
            if w_scene and w_scene in scene_end_map:
                scene_vo_end = scene_end_map[w_scene]
                if w['end'] > scene_vo_end + 0.05:
                    w['end'] = scene_vo_end + 0.05

        # Pre-display offset: show subtitle 50ms before audio (Fix #7 perceived delay)
        PRE_DISPLAY_OFFSET = 0.05
        for w in words:
            w['start'] = max(0.0, w['start'] - PRE_DISPLAY_OFFSET)

        logger.info(f"  Grouped into {len(words)} subtitle chunks (merged articles/prepositions, min {MIN_WORD_DURATION}s)")

        # Helper function for ASS time format (atomic total_cs approach — no cs=100 overflow)
        def time_to_ass(seconds: float) -> str:
            seconds = max(seconds, 0.0)
            total_cs = int(round(seconds * 100))
            h = total_cs // 360000
            total_cs %= 360000
            m = total_cs // 6000
            total_cs %= 6000
            s = total_cs // 100
            cs = total_cs % 100
            return f'{h}:{m:02d}:{s:02d}.{cs:02d}'

        # Viral/TikTok style ASS header
        # Montserrat Black, 76px, white text, black stroke 3px
        # OutlineColour: &H00000000 = solid black
        # BorderStyle: 1 = outline+shadow
        # Outline: 3 = 3px stroke
        # Shadow: 0 = no shadow (stroke only)
        # Alignment: 2 = bottom-center, 8 = top-center
        #
        # YOUTUBE SAFE ZONES (1080x1920 vertical):
        # - Bottom: 350px margin (avoid like/comment/share/subscribe buttons)
        # - Top: 200px margin (avoid video title, channel name overlay)
        ass_content = f'''[Script Info]
Title: {subtitle_title}
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Bottom,Montserrat Black,76,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,3,0,2,50,50,350,1
Style: Top,Montserrat Black,76,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,3,0,8,50,50,200,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''

        for w in words:
            start = time_to_ass(w['start'])
            end = time_to_ass(w['end'])
            word = w['word']

            # Determine position based on scene (use pre-computed scene field, not time-lookup)
            word_scene = w.get('scene', 0)

            # Use Top style for easter egg scene, Bottom for others
            if easter_egg_scene and word_scene == easter_egg_scene:
                style = "Top"
            else:
                style = "Bottom"

            ass_content += f'Dialogue: 0,{start},{end},{style},,0,0,0,,{word}\n'

        output_path.write_text(ass_content, encoding='utf-8')
        logger.info(f"  Generated {len(words)} word-by-word subtitles (Netflix style, UPPERCASE)")

    def _generate_voiceover_timing(
        self,
        alignment: dict,
        project_dir: Path,
        output_path: Path,
        hook_offset: float = 0.3,
    ) -> None:
        """
        Generate voiceover_timing.json for GEN3b from ElevenLabs alignment data.

        Maps voiceover audio to scene numbers using TEXT MATCHING against
        project_brief.json scene voiceover_segments.

        Key: Sentences are matched to scenes by text containment, NOT sequential index.
        This handles scenes with multiple sentences correctly (they merge into one entry).

        Format:
        {
            "segments": [
                {"scene_number": 1, "start_time": 0.0, "end_time": 2.5, "text": "..."},
                ...
            ]
        }
        """
        import json
        import re

        chars = alignment['characters']
        starts = alignment['character_start_times_seconds']
        ends = alignment['character_end_times_seconds']

        # Parse sentences from alignment
        sentences = []
        current_text = ''
        sent_start = 0.0

        for i, char in enumerate(chars):
            if current_text == '':
                sent_start = starts[i]
            current_text += char

            if char in '.!?':
                sent_end = ends[i]
                # Clean text - remove style tags like [whispers], [pause], [excited]
                clean_text = re.sub(r'\[[^\]]+\]', '', current_text).strip()
                clean_text = re.sub(r'<[^>]+>', '', clean_text).strip()
                if len(clean_text) > 2:
                    sentences.append({
                        'text': clean_text,
                        'start': sent_start,  # No hook offset - GEN3b/renderer adds it
                        'end': sent_end,
                    })
                current_text = ''

        # Capture remaining text without trailing punctuation (e.g. "Imagine living here")
        if current_text.strip():
            clean_text = re.sub(r'\[[^\]]+\]', '', current_text).strip()
            clean_text = re.sub(r'<[^>]+>', '', clean_text).strip()
            if len(clean_text) > 2:
                sentences.append({
                    'text': clean_text,
                    'start': sent_start,
                    'end': ends[-1] if ends else 0.0,
                })

        # Load project_brief to get scene voiceover segments
        project_brief_path = project_dir / "project_brief.json"
        scene_vo_segments = []

        if project_brief_path.exists():
            with open(project_brief_path, 'r', encoding='utf-8') as f:
                project_brief = json.load(f)

            for scene in sorted(
                project_brief.get('scenes', []),
                key=lambda s: s.get('scene_number', 0)
            ):
                scene_num = scene.get('scene_number', 0)
                vo_segment = scene.get('voiceover_segment', '') or scene.get('voiceover', '')
                if vo_segment:
                    # Clean the segment for matching
                    clean_vo = re.sub(r'\[[^\]]+\]', '', vo_segment).strip()
                    clean_vo = re.sub(r'<[^>]+>', '', clean_vo).strip()
                    clean_vo = ' '.join(clean_vo.split())  # normalize whitespace
                    if clean_vo and len(clean_vo) >= 3:
                        scene_vo_segments.append({
                            'scene_number': scene_num,
                            'text_lower': clean_vo.lower(),
                        })

        # Match sentences to scenes by TEXT CONTAINMENT (not sequential index!)
        # This correctly handles scenes with multiple sentences
        segments_by_scene = {}  # scene_number -> {start_time, end_time, text}
        last_matched_idx = 0

        for sent in sentences:
            clean_sent = ' '.join(sent['text'].split()).lower()

            # Find which scene's voiceover contains this sentence
            matched_idx = last_matched_idx
            match_key = clean_sent[:30] if len(clean_sent) > 30 else clean_sent

            # Search forward from last match (scenes are in order)
            for idx in range(last_matched_idx, len(scene_vo_segments)):
                if match_key in scene_vo_segments[idx]['text_lower']:
                    matched_idx = idx
                    break

            if matched_idx < len(scene_vo_segments):
                scene_number = scene_vo_segments[matched_idx]['scene_number']
                last_matched_idx = matched_idx  # never go backwards
            elif scene_vo_segments:
                scene_number = scene_vo_segments[-1]['scene_number']
            else:
                scene_number = 1

            # Merge sentences from the same scene into one timing entry
            if scene_number in segments_by_scene:
                existing = segments_by_scene[scene_number]
                existing['end_time'] = max(existing['end_time'], sent['end'])
                existing['text'] += ' ' + sent['text']
            else:
                segments_by_scene[scene_number] = {
                    'scene_number': scene_number,
                    'start_time': sent['start'],
                    'end_time': sent['end'],
                    'text': sent['text'],
                }

        # Sort by start time and save
        final_segments = sorted(segments_by_scene.values(), key=lambda s: s['start_time'])

        # Safety net: split segments exceeding MAX_SCENE_VO at sentence boundary (Fix #4)
        MAX_SCENE_VO = 5.0
        split_segments = []
        for seg in final_segments:
            dur = seg['end_time'] - seg['start_time']
            if dur > MAX_SCENE_VO:
                text = seg['text']
                sentences = re.split(r'(?<=[.!?])\s+', text)
                if len(sentences) >= 2:
                    # Find split point closest to MAX_SCENE_VO proportion
                    total_chars = len(text)
                    char_pos = 0
                    best_split = None
                    best_diff = float('inf')
                    for k, sent in enumerate(sentences[:-1]):
                        char_pos += len(sent) + 1  # +1 for space
                        proportion = char_pos / total_chars if total_chars > 0 else 0.5
                        split_time = seg['start_time'] + proportion * dur
                        diff = abs((split_time - seg['start_time']) - MAX_SCENE_VO)
                        if diff < best_diff:
                            best_diff = diff
                            best_split = (k, split_time, char_pos)

                    if best_split:
                        _, split_time, cpos = best_split
                        text1 = text[:cpos].strip()
                        text2 = text[cpos:].strip()
                        if text1 and text2:
                            split_segments.append({
                                'scene_number': seg['scene_number'],
                                'start_time': seg['start_time'],
                                'end_time': split_time,
                                'text': text1,
                            })
                            split_segments.append({
                                'scene_number': seg['scene_number'],
                                'start_time': split_time,
                                'end_time': seg['end_time'],
                                'text': text2,
                            })
                            logger.info(
                                f"  Split S{seg['scene_number']} VO ({dur:.1f}s > {MAX_SCENE_VO}s) "
                                f"into {split_time - seg['start_time']:.1f}s + {seg['end_time'] - split_time:.1f}s"
                            )
                            continue
                # No suitable split found — keep as-is
                split_segments.append(seg)
            else:
                split_segments.append(seg)
        final_segments = split_segments

        timing_data = {'segments': final_segments}
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(timing_data, f, indent=2, ensure_ascii=False)

        logger.info(f"  Generated voiceover_timing.json with {len(final_segments)} scene segments (text-matched)")

        # Validate per-scene VO durations
        for seg in final_segments:
            dur = seg['end_time'] - seg['start_time']
            sn = seg.get('scene_number', '?')
            text_preview = seg.get('text', '')[:50]
            if dur > MAX_SCENE_VO:
                logger.warning(
                    f"  ⚠ Scene {sn} VO duration {dur:.1f}s exceeds {MAX_SCENE_VO}s "
                    f"— TTS may be too slow/dramatic (text: \"{text_preview}...\")"
                )
            else:
                logger.info(f"  Scene {sn}: VO {dur:.1f}s — \"{text_preview}\"")

    async def list_voices(self) -> List[Dict[str, Any]]:
        """
        List all available voices from ElevenLabs

        Returns:
            List of voice dictionaries with voice_id, name, and other info

        Example:
            >>> voices = await engine.list_voices()
            >>> for v in voices:
            ...     print(f"{v['name']}: {v['voice_id']}")
        """
        from elevenlabs import AsyncElevenLabs

        logger.info("Fetching available voices...")

        try:
            client = AsyncElevenLabs(api_key=self.api_key)
            response = await client.voices.get_all()

            voices = []
            for voice in response.voices:
                voices.append({
                    "voice_id": voice.voice_id,
                    "name": voice.name,
                    "category": getattr(voice, "category", None),
                    "description": getattr(voice, "description", None),
                    "labels": getattr(voice, "labels", {}),
                })

            logger.info(f"Found {len(voices)} voices")
            return voices

        except Exception as e:
            logger.error(f"Failed to list voices: {e}")
            raise

    async def get_voice_id_by_name(self, name: str) -> Optional[str]:
        """
        Find voice_id by voice name

        Args:
            name: Voice name (e.g., "Adam", "Rachel")

        Returns:
            voice_id string or None if not found

        Example:
            >>> voice_id = await engine.get_voice_id_by_name("Adam")
            >>> print(voice_id)  # "pNInz6obpgDQGcFmaJgB"
        """
        voices = await self.list_voices()

        for voice in voices:
            if voice["name"].lower() == name.lower():
                logger.info(f"Found voice '{name}': {voice['voice_id']}")
                return voice["voice_id"]

        logger.warning(f"Voice '{name}' not found")
        return None

    # ========================================================================
    # SOUND EFFECTS GENERATION (ElevenLabs SFX API)
    # ========================================================================

    async def generate_sfx(
        self,
        text: str,
        duration_seconds: Optional[float] = None,
        prompt_influence: float = 0.3,
    ) -> bytes:
        """
        Generate sound effect using ElevenLabs Sound Effects API.

        Args:
            text: Description of the sound effect (e.g., "Loud sizzling pan")
            duration_seconds: Duration 0.5-30 seconds (auto if None)
            prompt_influence: How closely to follow prompt (0-1, default 0.3)

        Returns:
            Audio bytes (MP3 format)

        Example:
            >>> sfx_bytes = await engine.generate_sfx("explosion impact boom")
        """
        import aiohttp

        logger.info(f"Generating SFX: {text[:50]}...")

        url = "https://api.elevenlabs.io/v1/sound-generation"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        payload = {
            "text": text,
            "model_id": "eleven_text_to_sound_v2",
            "prompt_influence": prompt_influence,
        }

        if duration_seconds is not None:
            # Clamp to valid range
            duration_seconds = max(0.5, min(30.0, duration_seconds))
            payload["duration_seconds"] = duration_seconds

        retries = 0
        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        url,
                        headers=headers,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=60),
                    ) as response:
                        if response.status == 200:
                            audio_bytes = await response.read()
                            logger.success(f"SFX generated: {len(audio_bytes)} bytes")
                            return audio_bytes
                        else:
                            error_text = await response.text()
                            raise Exception(f"SFX API error {response.status}: {error_text}")

            except Exception as e:
                retries += 1
                logger.error(f"SFX generation error (attempt {retries}/{self.max_retries + 1}): {e}")

                if retries > self.max_retries:
                    logger.error("All retries exhausted for SFX generation")
                    raise

                wait_time = 5 * retries
                logger.info(f"Waiting {wait_time}s before retry...")
                await asyncio.sleep(wait_time)

    async def generate_and_save_sfx(
        self,
        text: str,
        output_path: Path,
        duration_seconds: Optional[float] = None,
        prompt_influence: float = 0.3,
    ) -> Path:
        """
        Generate sound effect and save to file.

        Args:
            text: Description of the sound effect
            output_path: Path where to save the audio file
            duration_seconds: Duration 0.5-30 seconds (auto if None)
            prompt_influence: How closely to follow prompt (0-1)

        Returns:
            Path to the saved audio file
        """
        audio_bytes = await self.generate_sfx(
            text=text,
            duration_seconds=duration_seconds,
            prompt_influence=prompt_influence,
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio_bytes)

        logger.success(f"SFX saved: {output_path}")
        return output_path


# ============================================================================
# 5-LAYER AUDIO MIXER
# ============================================================================

from enum import Enum
from dataclasses import dataclass, field
from typing import Tuple


class AudioLayer(str, Enum):
    """5-layer audio system for Glaze City pipeline."""
    BED = "BED"       # Ambient bed
    MUSIC = "MUSIC"   # Background music (SUNO)
    SFX = "SFX"       # Impact sounds
    FOLEY = "FOLEY"   # Food sounds
    VO = "VO"         # Voiceover (highest priority)


@dataclass
class AudioLayerConfig:
    """Configuration for a single audio layer."""
    layer: AudioLayer
    volume: float = 1.0
    ducked_volume: float = 1.0  # Volume when VO is playing
    file_path: Optional[Path] = None
    fade_in: float = 0.0  # seconds
    fade_out: float = 0.0  # seconds
    loop: bool = False


@dataclass
class SFXEvent:
    """A single SFX or FOLEY event at a specific timestamp."""
    timestamp: float  # seconds
    file_path: Path
    volume: float = 0.7
    layer: AudioLayer = AudioLayer.SFX
    reason: str = ""  # e.g., "beat_aligned", "transition", "food_moment"


@dataclass
class AudioMixConfig:
    """Complete 5-layer audio mix configuration."""
    total_duration: float
    bed: Optional[AudioLayerConfig] = None
    music: Optional[AudioLayerConfig] = None
    vo: Optional[AudioLayerConfig] = None
    sfx_events: List[SFXEvent] = field(default_factory=list)
    foley_events: List[SFXEvent] = field(default_factory=list)
    vo_segments: List[Tuple[float, float]] = field(default_factory=list)  # (start, end) for ducking
    vo_delay: float = 0.0  # Delay VO start (e.g., for hook offset)


# Default volume levels for each layer
DEFAULT_VOLUMES = {
    AudioLayer.BED: 0.15,
    AudioLayer.MUSIC: 0.5,   # Increased from 0.3 - music should be felt
    AudioLayer.SFX: 0.40,    # Was 0.7 — SFX should complement scenes, not overpower VO
    AudioLayer.FOLEY: 0.35,  # Was 0.5
    AudioLayer.VO: 1.5,      # Was 1.0 — boost whisper-style voices; alimiter prevents clipping
}

# Ducked volumes (when VO is playing)
DUCKED_VOLUMES = {
    AudioLayer.BED: 0.1,
    AudioLayer.MUSIC: 0.25,  # Increased from 0.15 - still audible during VO
    AudioLayer.SFX: 0.20,    # Was 0.5 — duck SFX during VO so voice stays clear
    AudioLayer.FOLEY: 0.15,  # Was 0.3
}


class AudioMixer:
    """
    5-Layer Audio Mixer for Glaze City Pipeline

    Handles multi-layer audio mixing with:
    - 5 audio layers (BED, MUSIC, SFX, FOLEY, VO)
    - Auto-ducking: MUSIC volume reduced during VO segments
    - Beat-aligned SFX triggers
    - Fade in/out support

    Note: Actual mixing is done by FFmpeg. This class generates
    the filter_complex configuration for FFmpeg.
    """

    def __init__(self):
        """Initialize AudioMixer."""
        logger.info("AudioMixer initialized (5-layer system)")

    def create_default_config(
        self,
        total_duration: float,
        vo_path: Optional[Path] = None,
        music_path: Optional[Path] = None,
        bed_path: Optional[Path] = None,
        vo_delay: float = 0.0,
    ) -> AudioMixConfig:
        """
        Create default audio mix configuration.

        Args:
            total_duration: Total video duration in seconds
            vo_path: Path to voiceover audio
            music_path: Path to background music (SUNO)
            bed_path: Path to ambient bed audio
            vo_delay: Delay VO start (e.g., for hook offset)

        Returns:
            AudioMixConfig with default settings
        """
        config = AudioMixConfig(total_duration=total_duration, vo_delay=vo_delay)

        if vo_path and vo_path.exists():
            config.vo = AudioLayerConfig(
                layer=AudioLayer.VO,
                volume=DEFAULT_VOLUMES[AudioLayer.VO],
                file_path=vo_path,
            )

        if music_path and music_path.exists():
            config.music = AudioLayerConfig(
                layer=AudioLayer.MUSIC,
                volume=DEFAULT_VOLUMES[AudioLayer.MUSIC],
                ducked_volume=DUCKED_VOLUMES[AudioLayer.MUSIC],
                file_path=music_path,
                loop=True,  # Loop music to fill duration
            )

        if bed_path and bed_path.exists():
            config.bed = AudioLayerConfig(
                layer=AudioLayer.BED,
                volume=DEFAULT_VOLUMES[AudioLayer.BED],
                ducked_volume=DUCKED_VOLUMES[AudioLayer.BED],
                file_path=bed_path,
                loop=True,
            )

        return config

    def add_sfx_event(
        self,
        config: AudioMixConfig,
        timestamp: float,
        sfx_path: Path,
        volume: float = None,
        reason: str = "",
    ) -> None:
        """Add an SFX event to the mix configuration."""
        effective_vol = volume if volume is not None else DEFAULT_VOLUMES[AudioLayer.SFX]
        effective_vol = min(effective_vol, 0.50)  # Hard cap — SFX must never overpower VO
        config.sfx_events.append(SFXEvent(
            timestamp=timestamp,
            file_path=sfx_path,
            volume=effective_vol,
            layer=AudioLayer.SFX,
            reason=reason,
        ))

    def add_foley_event(
        self,
        config: AudioMixConfig,
        timestamp: float,
        foley_path: Path,
        volume: float = None,
        reason: str = "",
    ) -> None:
        """Add a FOLEY event to the mix configuration."""
        effective_vol = volume if volume is not None else DEFAULT_VOLUMES[AudioLayer.FOLEY]
        effective_vol = min(effective_vol, 0.50)  # Hard cap — foley must not overpower VO
        config.foley_events.append(SFXEvent(
            timestamp=timestamp,
            file_path=foley_path,
            volume=effective_vol,
            layer=AudioLayer.FOLEY,
            reason=reason,
        ))

    def add_vo_segment(
        self,
        config: AudioMixConfig,
        start: float,
        end: float,
    ) -> None:
        """Add a VO segment for ducking calculations."""
        config.vo_segments.append((start, end))

    def generate_ffmpeg_filter(self, config: AudioMixConfig, input_offset: int = 1) -> str:
        """
        Generate FFmpeg filter_complex string for audio mixing.

        This creates the filter graph that:
        1. Applies volume levels to each layer
        2. Applies ducking to MUSIC during VO segments
        3. Mixes all layers together

        Args:
            config: AudioMixConfig with all layer settings
            input_offset: Starting input index for audio files (default 1, since video is input 0)

        Returns:
            FFmpeg filter_complex string

        Note:
            The filter assumes inputs are:
            - [0] = video file
            - [1:a] = VO
            - [2:a] = MUSIC
            - [3:a] = BED
            - [4:a]+ = SFX/FOLEY events
        """
        filters = []
        inputs = []
        input_idx = input_offset  # Start after video input

        # VO layer (with optional delay for hook offset)
        if config.vo and config.vo.file_path:
            if config.vo_delay > 0:
                delay_ms = int(config.vo_delay * 1000)
                filters.append(f"[{input_idx}:a]adelay={delay_ms}|{delay_ms},volume={config.vo.volume}[vo]")
            else:
                filters.append(f"[{input_idx}:a]volume={config.vo.volume}[vo]")
            inputs.append("vo")
            input_idx += 1

        # MUSIC layer with ducking
        # IMPORTANT: Add apad to ensure music plays for full video duration
        # This prevents music from cutting off when VO ends
        if config.music and config.music.file_path:
            # Trim music to video duration (if longer) or pad with silence (if shorter)
            music_prep = f"[{input_idx}:a]atrim=0:{config.total_duration},apad=whole_dur={config.total_duration}"
            if config.vo_segments:
                # Build ducking filter with prepared music
                filters.append(f"{music_prep}[music_prep]")
                duck_filter = self._build_ducking_filter_from_label(
                    "music_prep",
                    config.music.volume,
                    config.music.ducked_volume,
                    config.vo_segments,
                )
                filters.append(duck_filter)
            else:
                filters.append(f"{music_prep},volume={config.music.volume}[music]")
            inputs.append("music")
            input_idx += 1

        # BED layer (with atrim/apad + ducking, like MUSIC)
        if config.bed and config.bed.file_path:
            bed_prep = f"[{input_idx}:a]atrim=0:{config.total_duration},apad=whole_dur={config.total_duration}"
            if config.vo_segments and config.bed.ducked_volume != config.bed.volume:
                filters.append(f"{bed_prep}[bed_prep]")
                duck_filter = self._build_ducking_filter_from_label(
                    "bed_prep",
                    config.bed.volume,
                    config.bed.ducked_volume,
                    config.vo_segments,
                    output_label="bed",
                )
                filters.append(duck_filter)
            else:
                filters.append(f"{bed_prep},volume={config.bed.volume}[bed]")
            inputs.append("bed")
            input_idx += 1

        # SFX events (with ducking during VO)
        sfx_ducked_vol = DUCKED_VOLUMES.get(AudioLayer.SFX, 0.20)
        for i, sfx in enumerate(config.sfx_events):
            sfx_label = f"sfx{i}"
            delay_ms = int(sfx.timestamp * 1000)
            if config.vo_segments:
                # adelay BEFORE volume so that 't' matches global timeline
                expr_parts = [f"between(t,{s},{e})" for s, e in config.vo_segments]
                conditions = "+".join(expr_parts)
                vol_expr = f"if({conditions},{sfx_ducked_vol},{sfx.volume})"
                filters.append(
                    f"[{input_idx}:a]adelay={delay_ms}|{delay_ms},volume='{vol_expr}':eval=frame[{sfx_label}]"
                )
            else:
                filters.append(
                    f"[{input_idx}:a]volume={sfx.volume},adelay={delay_ms}|{delay_ms}[{sfx_label}]"
                )
            inputs.append(sfx_label)
            input_idx += 1

        # FOLEY events (with ducking during VO)
        foley_ducked_vol = DUCKED_VOLUMES.get(AudioLayer.FOLEY, 0.15)
        for i, foley in enumerate(config.foley_events):
            foley_label = f"foley{i}"
            delay_ms = int(foley.timestamp * 1000)
            if config.vo_segments:
                expr_parts = [f"between(t,{s},{e})" for s, e in config.vo_segments]
                conditions = "+".join(expr_parts)
                vol_expr = f"if({conditions},{foley_ducked_vol},{foley.volume})"
                filters.append(
                    f"[{input_idx}:a]adelay={delay_ms}|{delay_ms},volume='{vol_expr}':eval=frame[{foley_label}]"
                )
            else:
                filters.append(
                    f"[{input_idx}:a]volume={foley.volume},adelay={delay_ms}|{delay_ms}[{foley_label}]"
                )
            inputs.append(foley_label)
            input_idx += 1

        # Mix all inputs
        if inputs:
            input_labels = "".join(f"[{i}]" for i in inputs)
            # Use duration=longest so music/ambient continue for full video length
            # VO may be shorter than video, but music should play throughout
            # IMPORTANT: normalize=0 prevents volume reduction when mixing many inputs
            # Without this, amix divides volume by sqrt(N) where N is number of inputs
            # Then trim to total_duration to match video length
            filters.append(f"{input_labels}amix=inputs={len(inputs)}:duration=longest:normalize=0[amixed]")
            filters.append(f"[amixed]alimiter=limit=0.95:attack=5:release=50,atrim=0:{config.total_duration}[aout]")

        return ";".join(filters)

    def _build_ducking_filter(
        self,
        input_idx: int,
        normal_volume: float,
        ducked_volume: float,
        vo_segments: List[Tuple[float, float]],
        output_label: str = "music",
    ) -> str:
        """
        Build FFmpeg filter for volume ducking during VO segments.

        Uses volume filter with expression for time-based volume control.
        """
        # Build volume expression
        # volume='if(between(t,start1,end1),ducked,if(between(t,start2,end2),ducked,normal))'
        expr_parts = []
        for start, end in vo_segments:
            expr_parts.append(f"between(t,{start},{end})")

        if expr_parts:
            conditions = "+".join(expr_parts)
            volume_expr = f"if({conditions},{ducked_volume},{normal_volume})"
        else:
            volume_expr = str(normal_volume)

        return f"[{input_idx}:a]volume='{volume_expr}':eval=frame[{output_label}]"

    def _build_ducking_filter_from_label(
        self,
        label: str,
        normal_volume: float,
        ducked_volume: float,
        vo_segments: List[Tuple[float, float]],
        output_label: str = "music",
    ) -> str:
        """
        Build FFmpeg filter for volume ducking during VO segments.

        Similar to _build_ducking_filter but accepts a label string instead of input index.
        Used when the audio stream has been pre-processed (e.g., with atrim/apad).

        Args:
            label: The label name of the pre-processed stream (e.g., "music_prep")
            normal_volume: Volume level when VO is not playing
            ducked_volume: Volume level when VO is playing (ducked)
            vo_segments: List of (start, end) tuples for VO segments

        Returns:
            FFmpeg filter string like "[music_prep]volume='...'[music]"
        """
        expr_parts = []
        for start, end in vo_segments:
            expr_parts.append(f"between(t,{start},{end})")

        if expr_parts:
            conditions = "+".join(expr_parts)
            volume_expr = f"if({conditions},{ducked_volume},{normal_volume})"
        else:
            volume_expr = str(normal_volume)

        return f"[{label}]volume='{volume_expr}':eval=frame[{output_label}]"

    def get_input_files(self, config: AudioMixConfig) -> List[Tuple[str, Path, bool]]:
        """
        Get list of input files for FFmpeg in order.

        Returns:
            List of (layer_name, file_path, needs_loop) tuples in input order.
            needs_loop=True means `-stream_loop -1` should be added before the input.
        """
        inputs = []

        if config.vo and config.vo.file_path:
            inputs.append(("vo", config.vo.file_path, False))

        if config.music and config.music.file_path:
            inputs.append(("music", config.music.file_path, config.music.loop))

        if config.bed and config.bed.file_path:
            inputs.append(("bed", config.bed.file_path, config.bed.loop))

        for i, sfx in enumerate(config.sfx_events):
            inputs.append((f"sfx_{i}", sfx.file_path, False))

        for i, foley in enumerate(config.foley_events):
            inputs.append((f"foley_{i}", foley.file_path, False))

        return inputs

    def log_config(self, config: AudioMixConfig) -> None:
        """Log the audio mix configuration."""
        logger.info("=" * 50)
        logger.info("Audio Mix Configuration (5-Layer System)")
        logger.info("=" * 50)
        logger.info(f"Total duration: {config.total_duration}s")

        if config.vo:
            logger.info(f"VO: {config.vo.file_path} (vol: {config.vo.volume})")
        if config.music:
            logger.info(f"MUSIC: {config.music.file_path} (vol: {config.music.volume}, ducked: {config.music.ducked_volume})")
        if config.bed:
            logger.info(f"BED: {config.bed.file_path} (vol: {config.bed.volume})")

        sfx_ducked = DUCKED_VOLUMES.get(AudioLayer.SFX, 0.20)
        logger.info(f"SFX events: {len(config.sfx_events)} (ducked: {sfx_ducked} during VO)")
        for sfx in config.sfx_events:
            logger.info(f"  - {sfx.timestamp}s: {sfx.file_path.name} vol={sfx.volume} ({sfx.reason})")

        foley_ducked = DUCKED_VOLUMES.get(AudioLayer.FOLEY, 0.15)
        logger.info(f"FOLEY events: {len(config.foley_events)} (ducked: {foley_ducked} during VO)")
        for foley in config.foley_events:
            logger.info(f"  - {foley.timestamp}s: {foley.file_path.name} vol={foley.volume} ({foley.reason})")

        logger.info(f"VO segments (for ducking): {len(config.vo_segments)}")
        logger.info("=" * 50)


# ============================================================================
# EXPORT
# ============================================================================

__all__ = [
    "AudioEngine",
    "AudioMixer",
    "AudioLayer",
    "AudioLayerConfig",
    "SFXEvent",
    "AudioMixConfig",
    "DEFAULT_VOLUMES",
    "DUCKED_VOLUMES",
]
