"""
Beat Analyzer Service - Librosa Integration

Аналізує музичні файли для beat detection.
Результат використовується GEN3a для beat-aligned cuts.

Features:
- BPM detection
- Beat timestamps extraction
- Strong/weak beat classification
- Music sections detection (intro, build, drop, outro)
"""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional
import asyncio

from app.utils.logger import logger


class MusicBeatData:
    """Container for music beat analysis results."""

    def __init__(
        self,
        source: str = "librosa_preprocessing",
        version: str = "1.0",
        file: str = "",
        total_duration: float = 0.0,
        bpm: float = 120.0,
        time_signature: str = "4/4",
        beats: List[Dict[str, Any]] = None,
        strong_beats_only: List[float] = None,
        sections: List[Dict[str, Any]] = None,
    ):
        self.source = source
        self.version = version
        self.file = file
        self.total_duration = total_duration
        self.bpm = bpm
        self.time_signature = time_signature
        self.beats = beats or []
        self.strong_beats_only = strong_beats_only or []
        self.sections = sections or []

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "source": self.source,
            "version": self.version,
            "file": self.file,
            "total_duration": self.total_duration,
            "bpm": self.bpm,
            "time_signature": self.time_signature,
            "beats": self.beats,
            "strong_beats_only": self.strong_beats_only,
            "sections": self.sections,
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2)


class BeatAnalyzer:
    """
    Analyzes music for beat detection using librosa.

    Output: music_beat_data.json for GEN3a

    Features:
    - BPM detection using librosa.beat.beat_track
    - Beat strength classification (STRONG/MEDIUM/WEAK)
    - Music section detection using onset strength
    """

    def __init__(self):
        """Initialize BeatAnalyzer."""
        self._librosa_available = self._check_librosa()
        logger.info(f"BeatAnalyzer initialized (librosa: {'available' if self._librosa_available else 'not available'})")

    def _check_librosa(self) -> bool:
        """Check if librosa is available."""
        try:
            import librosa
            return True
        except ImportError:
            logger.warning("librosa not installed. Install with: pip install librosa")
            return False

    async def analyze_music(self, music_path: Path) -> MusicBeatData:
        """
        Analyze music file for beats.

        Args:
            music_path: Path to music file (mp3, wav, etc.)

        Returns:
            MusicBeatData with beat analysis

        Example:
            >>> analyzer = BeatAnalyzer()
            >>> data = await analyzer.analyze_music(Path("music.mp3"))
            >>> print(f"BPM: {data.bpm}")
            >>> print(f"Strong beats: {data.strong_beats_only[:5]}")
        """
        if not self._librosa_available:
            logger.warning("librosa not available, returning default beat data")
            return self._get_default_beat_data(music_path)

        if not music_path.exists():
            logger.error(f"Music file not found: {music_path}")
            return self._get_default_beat_data(music_path)

        logger.info(f"Analyzing music: {music_path.name}")

        # Run analysis in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._analyze_sync,
            music_path,
        )

    def _analyze_sync(self, music_path: Path) -> MusicBeatData:
        """Synchronous analysis using librosa."""
        import librosa
        import numpy as np

        try:
            # Load audio file
            logger.info("  Loading audio...")
            y, sr = librosa.load(str(music_path), sr=None)
            duration = librosa.get_duration(y=y, sr=sr)
            logger.info(f"  Duration: {duration:.2f}s, Sample rate: {sr}")

            # Detect tempo and beats
            logger.info("  Detecting tempo and beats...")
            tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
            beat_times = librosa.frames_to_time(beat_frames, sr=sr)

            # Handle tempo as array or scalar
            if isinstance(tempo, np.ndarray):
                tempo = float(tempo[0]) if len(tempo) > 0 else 120.0
            else:
                tempo = float(tempo)

            logger.info(f"  Detected BPM: {tempo:.1f}")
            logger.info(f"  Total beats: {len(beat_times)}")

            # Classify beat strength
            beats = []
            strong_beats = []

            for i, t in enumerate(beat_times):
                # Classify based on position in 4/4 measure
                beat_in_measure = (i % 4) + 1

                if beat_in_measure == 1:
                    strength = "STRONG"
                    strong_beats.append(float(t))
                elif beat_in_measure == 3:
                    strength = "MEDIUM"
                else:
                    strength = "WEAK"

                beats.append({
                    "timestamp": float(t),
                    "strength": strength,
                    "beat_number": beat_in_measure,
                })

            # Detect sections using onset strength envelope
            logger.info("  Detecting sections...")
            sections = self._detect_sections(y, sr, duration)

            return MusicBeatData(
                source="librosa_preprocessing",
                version="1.0",
                file=music_path.name,
                total_duration=duration,
                bpm=tempo,
                time_signature="4/4",
                beats=beats,
                strong_beats_only=strong_beats,
                sections=sections,
            )

        except Exception as e:
            logger.error(f"Beat analysis failed: {e}")
            return self._get_default_beat_data(music_path)

    def _detect_sections(
        self,
        y,
        sr: int,
        duration: float,
    ) -> List[Dict[str, Any]]:
        """Detect music sections using onset strength."""
        import librosa
        import numpy as np

        try:
            # Get onset strength envelope
            onset_env = librosa.onset.onset_strength(y=y, sr=sr)

            # Simple section detection based on energy levels
            # Divide into quarters and classify
            quarter = len(onset_env) // 4
            sections = []

            # Calculate average energy per quarter
            energies = []
            for i in range(4):
                start = i * quarter
                end = (i + 1) * quarter if i < 3 else len(onset_env)
                avg_energy = float(np.mean(onset_env[start:end]))
                energies.append(avg_energy)

            # Normalize energies
            max_energy = max(energies) if max(energies) > 0 else 1
            normalized = [e / max_energy for e in energies]

            # Classify sections
            section_names = ["INTRO", "BUILD", "DROP", "OUTRO"]
            energy_labels = []

            for i, norm_e in enumerate(normalized):
                if norm_e < 0.4:
                    energy_labels.append("LOW")
                elif norm_e < 0.7:
                    energy_labels.append("RISING" if i < 2 else "FALLING")
                else:
                    energy_labels.append("HIGH")

            # Create sections
            quarter_duration = duration / 4
            for i, name in enumerate(section_names):
                sections.append({
                    "name": name,
                    "start": i * quarter_duration,
                    "end": (i + 1) * quarter_duration,
                    "energy": energy_labels[i],
                })

            return sections

        except Exception as e:
            logger.warning(f"Section detection failed: {e}")
            # Return default sections
            quarter = duration / 4
            return [
                {"name": "INTRO", "start": 0.0, "end": quarter, "energy": "LOW"},
                {"name": "BUILD", "start": quarter, "end": 2 * quarter, "energy": "RISING"},
                {"name": "DROP", "start": 2 * quarter, "end": 3 * quarter, "energy": "HIGH"},
                {"name": "OUTRO", "start": 3 * quarter, "end": duration, "energy": "FALLING"},
            ]

    def _get_default_beat_data(self, music_path: Path) -> MusicBeatData:
        """Return default beat data when analysis fails."""
        # Generate default beats for 25 seconds at 120 BPM
        default_duration = 25.0
        bpm = 120.0
        beat_interval = 60.0 / bpm  # 0.5 seconds

        beats = []
        strong_beats = []
        current_time = 0.0
        beat_count = 0

        while current_time < default_duration:
            beat_in_measure = (beat_count % 4) + 1

            if beat_in_measure == 1:
                strength = "STRONG"
                strong_beats.append(current_time)
            elif beat_in_measure == 3:
                strength = "MEDIUM"
            else:
                strength = "WEAK"

            beats.append({
                "timestamp": current_time,
                "strength": strength,
                "beat_number": beat_in_measure,
            })

            current_time += beat_interval
            beat_count += 1

        return MusicBeatData(
            source="default_fallback",
            version="1.0",
            file=music_path.name if music_path else "unknown",
            total_duration=default_duration,
            bpm=bpm,
            time_signature="4/4",
            beats=beats,
            strong_beats_only=strong_beats,
            sections=[
                {"name": "INTRO", "start": 0.0, "end": 6.0, "energy": "LOW"},
                {"name": "BUILD", "start": 6.0, "end": 12.0, "energy": "RISING"},
                {"name": "DROP", "start": 12.0, "end": 19.0, "energy": "HIGH"},
                {"name": "OUTRO", "start": 19.0, "end": 25.0, "energy": "FALLING"},
            ],
        )

    async def save_beat_data(
        self,
        beat_data: MusicBeatData,
        output_path: Path,
    ) -> Path:
        """Save beat data to JSON file."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(beat_data.to_dict(), f, indent=2)

        logger.success(f"Beat data saved: {output_path}")
        return output_path

    async def load_beat_data(self, path: Path) -> Optional[MusicBeatData]:
        """Load beat data from JSON file."""
        if not path.exists():
            return None

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return MusicBeatData(**data)


# ============================================================================
# EXPORT
# ============================================================================

__all__ = ["BeatAnalyzer", "MusicBeatData"]
