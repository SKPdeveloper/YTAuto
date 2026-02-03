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

    # eleven_v3 model only accepts these stability values (undocumented server-side restriction)
    ELEVEN_V3_STABILITY_VALUES = [0.0, 0.5, 1.0]

    @staticmethod
    def _sanitize_stability_for_model(stability: float, model_id: str) -> float:
        """
        Sanitize stability value based on model restrictions.

        eleven_v3 only accepts [0.0, 0.5, 1.0] - rounds to nearest valid value.
        Other models (eleven_multilingual_v2, etc.) accept any 0.0-1.0 value.
        """
        if "eleven_v3" in model_id or model_id == "eleven_v3":
            # Round to nearest valid value for eleven_v3
            valid_values = AudioEngine.ELEVEN_V3_STABILITY_VALUES
            nearest = min(valid_values, key=lambda x: abs(x - stability))
            if nearest != stability:
                logger.warning(
                    f"eleven_v3 requires stability in {valid_values}. "
                    f"Rounding {stability} -> {nearest}"
                )
            return nearest
        return stability

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
            elevenlabs_settings = VoiceSettings(
                stability=sanitized_stability,
                similarity_boost=voice_settings.similarity_boost,
                style=voice_settings.style,
                use_speaker_boost=voice_settings.speaker_boost,
            )
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
        from elevenlabs import ElevenLabs

        logger.info("Fetching available voices...")

        try:
            # Use sync client for listing voices (simpler)
            client = ElevenLabs(api_key=self.api_key)
            response = client.voices.get_all()

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
    AudioLayer.SFX: 0.7,
    AudioLayer.FOLEY: 0.5,
    AudioLayer.VO: 1.0,
}

# Ducked volumes (when VO is playing)
DUCKED_VOLUMES = {
    AudioLayer.BED: 0.1,
    AudioLayer.MUSIC: 0.25,  # Increased from 0.15 - still audible during VO
    AudioLayer.SFX: 0.5,
    AudioLayer.FOLEY: 0.3,
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
        config.sfx_events.append(SFXEvent(
            timestamp=timestamp,
            file_path=sfx_path,
            volume=volume or DEFAULT_VOLUMES[AudioLayer.SFX],
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
        config.foley_events.append(SFXEvent(
            timestamp=timestamp,
            file_path=foley_path,
            volume=volume or DEFAULT_VOLUMES[AudioLayer.FOLEY],
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
        if config.music and config.music.file_path:
            if config.vo_segments:
                # Build ducking filter
                duck_filter = self._build_ducking_filter(
                    input_idx,
                    config.music.volume,
                    config.music.ducked_volume,
                    config.vo_segments,
                )
                filters.append(duck_filter)
            else:
                filters.append(f"[{input_idx}:a]volume={config.music.volume}[music]")
            inputs.append("music")
            input_idx += 1

        # BED layer
        if config.bed and config.bed.file_path:
            filters.append(f"[{input_idx}:a]volume={config.bed.volume}[bed]")
            inputs.append("bed")
            input_idx += 1

        # SFX events
        for i, sfx in enumerate(config.sfx_events):
            sfx_label = f"sfx{i}"
            filters.append(
                f"[{input_idx}:a]volume={sfx.volume},adelay={int(sfx.timestamp * 1000)}|{int(sfx.timestamp * 1000)}[{sfx_label}]"
            )
            inputs.append(sfx_label)
            input_idx += 1

        # FOLEY events
        for i, foley in enumerate(config.foley_events):
            foley_label = f"foley{i}"
            filters.append(
                f"[{input_idx}:a]volume={foley.volume},adelay={int(foley.timestamp * 1000)}|{int(foley.timestamp * 1000)}[{foley_label}]"
            )
            inputs.append(foley_label)
            input_idx += 1

        # Mix all inputs
        if inputs:
            input_labels = "".join(f"[{i}]" for i in inputs)
            # Use duration=longest so music/ambient continue for full video length
            # VO may be shorter than video, but music should play throughout
            # Then trim to total_duration to match video length
            filters.append(f"{input_labels}amix=inputs={len(inputs)}:duration=longest[amixed]")
            filters.append(f"[amixed]atrim=0:{config.total_duration}[aout]")

        return ";".join(filters)

    def _build_ducking_filter(
        self,
        input_idx: int,
        normal_volume: float,
        ducked_volume: float,
        vo_segments: List[Tuple[float, float]],
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

        return f"[{input_idx}:a]volume='{volume_expr}':eval=frame[music]"

    def get_input_files(self, config: AudioMixConfig) -> List[Tuple[str, Path]]:
        """
        Get list of input files for FFmpeg in order.

        Returns:
            List of (layer_name, file_path) tuples in input order
        """
        inputs = []

        if config.vo and config.vo.file_path:
            inputs.append(("vo", config.vo.file_path))

        if config.music and config.music.file_path:
            inputs.append(("music", config.music.file_path))

        if config.bed and config.bed.file_path:
            inputs.append(("bed", config.bed.file_path))

        for i, sfx in enumerate(config.sfx_events):
            inputs.append((f"sfx_{i}", sfx.file_path))

        for i, foley in enumerate(config.foley_events):
            inputs.append((f"foley_{i}", foley.file_path))

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

        logger.info(f"SFX events: {len(config.sfx_events)}")
        for sfx in config.sfx_events:
            logger.info(f"  - {sfx.timestamp}s: {sfx.file_path.name} ({sfx.reason})")

        logger.info(f"FOLEY events: {len(config.foley_events)}")
        for foley in config.foley_events:
            logger.info(f"  - {foley.timestamp}s: {foley.file_path.name} ({foley.reason})")

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
