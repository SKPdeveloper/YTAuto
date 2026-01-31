"""
GEN3a Preprocessing Module v1.6.0

Prepares data for GEN3a Video Analyst:
1. beats.json - Music beat analysis using librosa
2. vo_timing.json - Voiceover timing (SPEECH/PAUSE segments)
3. audio_levels.json - Audio levels and ducking recommendations
4. Scene 6 reversal - Physically reverse scene 6 for seamless loop

This preprocessing runs BEFORE GEN3a receives the videos.
GEN3a uses this precomputed data instead of analyzing audio itself.
"""

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass

from app.utils.logger import logger
from app.core.config import settings


@dataclass
class BeatInfo:
    """Single beat information."""
    timestamp: float
    strength: str  # STRONG, MEDIUM, WEAK
    beat_number: int  # 1-4 for 4/4 time


@dataclass
class VOSegment:
    """Voiceover segment (speech or pause)."""
    start: float
    end: float
    segment_type: str  # SPEECH or PAUSE


@dataclass
class PreprocessingResult:
    """Result of preprocessing."""
    work_dir: Path  # gen3a_work/ directory
    video_paths: List[Path]  # [1.mp4, 2.mp4, ..., 6.mp4] in work_dir
    beats_json_path: Path
    vo_timing_json_path: Path
    audio_levels_json_path: Path
    success: bool
    errors: List[str]


class Gen3aPreprocessor:
    """
    Preprocessing module for GEN3a v1.6.0

    Prepares:
    - beats.json from music.mp3 using librosa
    - vo_timing.json from voiceover.mp3
    - audio_levels.json with ducking recommendations
    - Reversed scene 6 video
    """

    def __init__(self):
        """Initialize preprocessor."""
        logger.info("GEN3a Preprocessor v1.6.0 initialized")

    async def preprocess(
        self,
        project_dir: Path,
        video_paths: List[Path],
        music_path: Optional[Path],
        voiceover_path: Optional[Path],
    ) -> PreprocessingResult:
        """
        Run full preprocessing pipeline.

        Creates gen3a_work/ directory with:
        - 1.mp4 through 6.mp4 (copies of scene videos, scene 6 reversed)
        - beats.json (music beat analysis)
        - vo_timing.json (voiceover timing)
        - audio_levels.json (audio levels for ducking)

        Args:
            project_dir: Project directory
            video_paths: List of 6 video paths [scene_1/video.mp4, ..., scene_6/video.mp4]
            music_path: Path to background music
            voiceover_path: Path to voiceover.mp3

        Returns:
            PreprocessingResult with work_dir and standardized video paths
        """
        import shutil

        logger.info("=" * 60)
        logger.info("GEN3a Preprocessing v1.7.0")
        logger.info("=" * 60)

        errors = []

        # Create work directory
        work_dir = project_dir / "gen3a_work"
        work_dir.mkdir(exist_ok=True)
        logger.info(f"Work directory: {work_dir}")

        # Output paths (all in work_dir)
        beats_path = work_dir / "beats.json"
        vo_timing_path = work_dir / "vo_timing.json"
        audio_levels_path = work_dir / "audio_levels.json"

        # ====================================================================
        # STEP 1: Prepare video files (copy 1-5, reverse 6)
        # ====================================================================
        logger.info(f"Step 1/4: Preparing {len(video_paths)} videos...")
        prepared_video_paths = []

        for i, src_path in enumerate(video_paths):
            scene_num = i + 1
            dst_path = work_dir / f"{scene_num}.mp4"

            try:
                if not src_path.exists():
                    errors.append(f"Video {scene_num} not found: {src_path}")
                    logger.error(f"  Video {scene_num} not found: {src_path}")
                    continue

                if scene_num == 6:
                    # Reverse scene 6 for seamless loop
                    logger.info(f"  Reversing scene 6 -> {dst_path.name}")
                    await self._reverse_video(src_path, dst_path)
                else:
                    # Copy scenes 1-5
                    logger.info(f"  Copying scene {scene_num} -> {dst_path.name}")
                    shutil.copy2(src_path, dst_path)

                prepared_video_paths.append(dst_path)
                logger.success(f"  {dst_path.name} ready")

            except Exception as e:
                errors.append(f"Video {scene_num} preparation failed: {e}")
                logger.error(f"  Video {scene_num} failed: {e}")

        logger.info(f"  Prepared {len(prepared_video_paths)}/{len(video_paths)} videos")

        # ====================================================================
        # STEP 2: Generate beats.json
        # ====================================================================
        logger.info("Step 2/4: Analyzing music beats...")
        if music_path and music_path.exists():
            try:
                beats_data = await self._analyze_beats(music_path)
                with open(beats_path, 'w', encoding='utf-8') as f:
                    json.dump(beats_data, f, indent=2, ensure_ascii=False)
                logger.success(f"  beats.json created: BPM={beats_data.get('bpm', 'N/A')}")
            except Exception as e:
                errors.append(f"beats.json failed: {e}")
                logger.error(f"  beats.json failed: {e}")
                beats_data = self._create_fallback_beats()
                with open(beats_path, 'w', encoding='utf-8') as f:
                    json.dump(beats_data, f, indent=2, ensure_ascii=False)
        else:
            logger.warning("  No music file provided - using fallback beats.json")
            beats_data = self._create_fallback_beats()
            with open(beats_path, 'w', encoding='utf-8') as f:
                json.dump(beats_data, f, indent=2, ensure_ascii=False)

        # ====================================================================
        # STEP 3: Generate vo_timing.json
        # ====================================================================
        logger.info("Step 3/4: Analyzing voiceover timing...")
        if voiceover_path and voiceover_path.exists():
            try:
                vo_timing_data = await self._analyze_voiceover_timing(voiceover_path)
                with open(vo_timing_path, 'w', encoding='utf-8') as f:
                    json.dump(vo_timing_data, f, indent=2, ensure_ascii=False)
                logger.success(f"  vo_timing.json created: {len(vo_timing_data.get('segments', []))} segments")
            except Exception as e:
                errors.append(f"vo_timing.json failed: {e}")
                logger.error(f"  vo_timing.json failed: {e}")
                vo_timing_data = self._create_fallback_vo_timing()
                with open(vo_timing_path, 'w', encoding='utf-8') as f:
                    json.dump(vo_timing_data, f, indent=2, ensure_ascii=False)
        else:
            logger.warning("  No voiceover file provided - using fallback vo_timing.json")
            vo_timing_data = self._create_fallback_vo_timing()
            with open(vo_timing_path, 'w', encoding='utf-8') as f:
                json.dump(vo_timing_data, f, indent=2, ensure_ascii=False)

        # ====================================================================
        # STEP 4: Generate audio_levels.json
        # ====================================================================
        logger.info("Step 4/4: Analyzing audio levels...")
        if music_path and music_path.exists():
            try:
                audio_levels_data = await self._analyze_audio_levels(music_path, voiceover_path)
                with open(audio_levels_path, 'w', encoding='utf-8') as f:
                    json.dump(audio_levels_data, f, indent=2, ensure_ascii=False)
                logger.success(f"  audio_levels.json created")
            except Exception as e:
                errors.append(f"audio_levels.json failed: {e}")
                logger.error(f"  audio_levels.json failed: {e}")
                audio_levels_data = self._create_fallback_audio_levels()
                with open(audio_levels_path, 'w', encoding='utf-8') as f:
                    json.dump(audio_levels_data, f, indent=2, ensure_ascii=False)
        else:
            logger.warning("  No music file provided - using fallback audio_levels.json")
            audio_levels_data = self._create_fallback_audio_levels()
            with open(audio_levels_path, 'w', encoding='utf-8') as f:
                json.dump(audio_levels_data, f, indent=2, ensure_ascii=False)

        # ====================================================================
        # SUMMARY
        # ====================================================================
        logger.info("=" * 60)
        if errors:
            logger.warning(f"Preprocessing completed with {len(errors)} errors")
        else:
            logger.success("Preprocessing completed successfully")
        logger.info(f"  Work directory: {work_dir}")
        logger.info(f"  Videos: {[p.name for p in prepared_video_paths]}")
        logger.info("=" * 60)

        return PreprocessingResult(
            work_dir=work_dir,
            video_paths=prepared_video_paths,
            beats_json_path=beats_path,
            vo_timing_json_path=vo_timing_path,
            audio_levels_json_path=audio_levels_path,
            success=len(errors) == 0,
            errors=errors,
        )

    async def _analyze_beats(self, music_path: Path) -> Dict[str, Any]:
        """
        Analyze music beats using librosa.

        Returns beats.json format per GEN3a v1.6.0 spec:
        {
            "bpm": 120,
            "time_signature": "4/4",
            "duration_seconds": 32.5,
            "beats": [{"timestamp": 0.0, "strength": "STRONG", "beat_number": 1}, ...],
            "downbeats": [0.0, 2.0, 4.0, ...],
            "sections": [{"start": 0.0, "end": 8.0, "label": "intro"}, ...]
        }
        """
        import librosa
        import numpy as np

        # Load audio
        y, sr = librosa.load(str(music_path), sr=22050)
        duration = librosa.get_duration(y=y, sr=sr)

        # Get tempo and beat frames
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)

        # Handle tempo as array or scalar
        bpm = float(tempo[0]) if hasattr(tempo, '__len__') else float(tempo)

        # Create beats array with strength classification
        beats = []
        for i, timestamp in enumerate(beat_times):
            beat_number = (i % 4) + 1  # 1, 2, 3, 4 repeating

            # Classify strength based on beat position in measure
            if beat_number == 1:
                strength = "STRONG"  # Downbeat
            elif beat_number == 3:
                strength = "MEDIUM"  # Secondary accent
            else:
                strength = "WEAK"  # Offbeats (2, 4)

            beats.append({
                "timestamp": round(timestamp, 3),
                "strength": strength,
                "beat_number": beat_number,
            })

        # Extract downbeats (beat 1 of each measure)
        downbeats = [b["timestamp"] for b in beats if b["beat_number"] == 1]

        # Strong beats for cuts (beat 1 and 3)
        strong_beats_only = [b["timestamp"] for b in beats if b["strength"] in ["STRONG", "MEDIUM"]]

        # Create sections based on duration
        sections = self._create_music_sections(duration, bpm)

        return {
            "source": "librosa_preprocessing",
            "version": "1.0",
            "file": music_path.name,
            "total_duration": round(duration, 3),
            "bpm": round(bpm, 2),
            "time_signature": "4/4",
            "beats": beats,
            "strong_beats_only": strong_beats_only,
            "downbeats": downbeats,
            "sections": sections,
        }

    def _create_music_sections(self, duration: float, bpm: float) -> List[Dict[str, Any]]:
        """Create music sections based on duration."""
        # Typical section length: 8-16 bars
        bars_per_section = 8
        beats_per_bar = 4
        beat_duration = 60.0 / bpm
        section_duration = bars_per_section * beats_per_bar * beat_duration

        sections = []
        section_names = ["intro", "build", "main", "outro"]
        current_time = 0.0

        for i, name in enumerate(section_names):
            end_time = min(current_time + section_duration, duration)
            sections.append({
                "name": name.upper(),
                "start": round(current_time, 3),
                "end": round(end_time, 3),
                "energy": "HIGH" if name in ["main", "build"] else "MEDIUM",
            })
            current_time = end_time
            if current_time >= duration:
                break

        # Ensure last section goes to end
        if sections:
            sections[-1]["end"] = round(duration, 3)

        return sections

    async def _analyze_voiceover_timing(self, voiceover_path: Path) -> Dict[str, Any]:
        """
        Analyze voiceover to detect speech/pause segments.

        Returns vo_timing.json format per GEN3a v1.6.0 spec:
        {
            "total_duration_seconds": 8.5,
            "segments": [
                {"start": 0.0, "end": 2.1, "type": "SPEECH"},
                {"start": 2.1, "end": 2.6, "type": "PAUSE"},
                ...
            ],
            "speech_ratio": 0.75,
            "average_pause_duration": 0.4,
            "longest_pause": {"start": 5.2, "end": 5.8, "duration": 0.6}
        }
        """
        import librosa
        import numpy as np

        # Load audio
        y, sr = librosa.load(str(voiceover_path), sr=22050)
        duration = librosa.get_duration(y=y, sr=sr)

        # Compute RMS energy for speech detection
        frame_length = 2048
        hop_length = 512
        rms = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]
        times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop_length)

        # Normalize RMS
        rms_db = librosa.amplitude_to_db(rms, ref=np.max)

        # Threshold for speech detection (-40 dB is typical for speech vs silence)
        speech_threshold = -35  # dB below max

        # Detect speech segments
        is_speech = rms_db > speech_threshold

        # Convert to segments
        segments = []
        current_type = None
        segment_start = 0.0

        for i, (time, speech) in enumerate(zip(times, is_speech)):
            segment_type = "SPEECH" if speech else "PAUSE"

            if current_type is None:
                current_type = segment_type
                segment_start = time
            elif segment_type != current_type:
                # End current segment
                segments.append({
                    "start": round(segment_start, 3),
                    "end": round(time, 3),
                    "type": current_type,
                })
                current_type = segment_type
                segment_start = time

        # Add final segment
        if current_type:
            segments.append({
                "start": round(segment_start, 3),
                "end": round(duration, 3),
                "type": current_type,
            })

        # Merge short segments (< 0.1s)
        segments = self._merge_short_segments(segments, min_duration=0.1)

        # Calculate statistics
        speech_duration = sum(
            s["end"] - s["start"] for s in segments if s["type"] == "SPEECH"
        )
        pause_segments = [s for s in segments if s["type"] == "PAUSE"]

        pause_durations = [s["end"] - s["start"] for s in pause_segments]
        avg_pause = sum(pause_durations) / len(pause_durations) if pause_durations else 0.0

        longest_pause = None
        if pause_segments:
            longest = max(pause_segments, key=lambda s: s["end"] - s["start"])
            longest_pause = {
                "start": longest["start"],
                "end": longest["end"],
                "duration": round(longest["end"] - longest["start"], 3),
            }

        return {
            "source": "librosa_preprocessing",
            "version": "1.0",
            "file": voiceover_path.name,
            "total_duration_seconds": round(duration, 3),
            "segments": segments,
            "speech_ratio": round(speech_duration / duration, 3) if duration > 0 else 0.0,
            "average_pause_duration": round(avg_pause, 3),
            "longest_pause": longest_pause,
        }

    def _merge_short_segments(
        self,
        segments: List[Dict[str, Any]],
        min_duration: float
    ) -> List[Dict[str, Any]]:
        """Merge segments shorter than min_duration with neighbors."""
        if not segments:
            return segments

        merged = [segments[0]]

        for seg in segments[1:]:
            prev = merged[-1]
            seg_duration = seg["end"] - seg["start"]

            # If current segment is too short, merge with previous
            if seg_duration < min_duration:
                prev["end"] = seg["end"]
            # If same type as previous, merge
            elif seg["type"] == prev["type"]:
                prev["end"] = seg["end"]
            else:
                merged.append(seg)

        return merged

    async def _analyze_audio_levels(
        self,
        music_path: Path,
        voiceover_path: Path
    ) -> Dict[str, Any]:
        """
        Analyze audio levels for ducking recommendations.

        Returns audio_levels.json format per GEN3a v1.6.0 spec:
        {
            "music": {"peak_db": -3.2, "mean_db": -12.5},
            "voiceover": {"peak_db": -6.1, "mean_db": -18.3, "is_whisper_detected": true},
            "recommendations": {
                "music_ducking_normal_db": -10,
                "music_ducking_whisper_db": -18,
                "vo_boost_needed": false,
                "vo_boost_amount_db": 0
            }
        }
        """
        import librosa
        import numpy as np

        # Analyze music
        y_music, sr = librosa.load(str(music_path), sr=22050)
        music_rms = librosa.feature.rms(y=y_music)[0]
        music_peak_db = float(librosa.amplitude_to_db(np.max(np.abs(y_music))))
        music_mean_db = float(np.mean(librosa.amplitude_to_db(music_rms + 1e-10)))

        # Analyze voiceover
        y_vo, sr = librosa.load(str(voiceover_path), sr=22050)
        vo_rms = librosa.feature.rms(y=y_vo)[0]
        vo_peak_db = float(librosa.amplitude_to_db(np.max(np.abs(y_vo))))
        vo_mean_db = float(np.mean(librosa.amplitude_to_db(vo_rms + 1e-10)))

        # Detect whisper (quiet voiceover)
        # Whisper typically has mean_db < -22 dB
        is_whisper_detected = vo_mean_db < -22

        # Calculate ducking recommendations
        # Normal speech: music at -10 dB (about 31% volume)
        # Whisper: music at -18 dB (about 12% volume)
        music_ducking_normal_db = -10
        music_ducking_whisper_db = -18

        # Check if VO needs boost
        vo_boost_needed = vo_peak_db < -12  # Too quiet
        vo_boost_amount_db = max(0, -6 - vo_peak_db) if vo_boost_needed else 0

        return {
            "source": "librosa_preprocessing",
            "version": "1.0",
            "music": {
                "file": music_path.name,
                "peak_db": round(music_peak_db, 1),
                "mean_db": round(music_mean_db, 1),
            },
            "voiceover": {
                "file": voiceover_path.name,
                "peak_db": round(vo_peak_db, 1),
                "mean_db": round(vo_mean_db, 1),
                "is_whisper_detected": is_whisper_detected,
            },
            "recommendations": {
                "music_ducking_normal_db": music_ducking_normal_db,
                "music_ducking_whisper_db": music_ducking_whisper_db,
                "vo_boost_needed": vo_boost_needed,
                "vo_boost_amount_db": round(vo_boost_amount_db, 1),
            },
        }

    async def _reverse_video(self, input_path: Path, output_path: Path) -> Path:
        """
        Reverse video using FFmpeg.

        Scene 6 is reversed for seamless loop back to Scene 1.
        """
        ffmpeg_path = settings.TOPAZ_FFMPEG_PATH or "ffmpeg"
        cmd = [
            ffmpeg_path,
            "-y",  # Overwrite output
            "-i", str(input_path),
            "-vf", "reverse",
            "-af", "areverse",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-c:a", "aac",
            "-b:a", "192k",
            str(output_path),
        ]

        logger.debug(f"Running FFmpeg: {' '.join(cmd)}")

        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )

        if process.returncode != 0:
            raise RuntimeError(f"FFmpeg failed: {process.stderr}")

        if not output_path.exists():
            raise RuntimeError(f"Output file not created: {output_path}")

        return output_path

    def _create_fallback_beats(self) -> Dict[str, Any]:
        """Create fallback beats.json if librosa fails."""
        return {
            "source": "fallback",
            "version": "1.0",
            "bpm": 120,
            "time_signature": "4/4",
            "total_duration": 30.0,
            "beats": [
                {"timestamp": i * 0.5, "strength": "STRONG" if i % 4 == 0 else "WEAK", "beat_number": (i % 4) + 1}
                for i in range(60)
            ],
            "downbeats": [i * 2.0 for i in range(15)],
            "strong_beats_only": [i * 2.0 for i in range(15)],
            "sections": [
                {"name": "INTRO", "start": 0.0, "end": 8.0, "energy": "MEDIUM"},
                {"name": "MAIN", "start": 8.0, "end": 24.0, "energy": "HIGH"},
                {"name": "OUTRO", "start": 24.0, "end": 30.0, "energy": "MEDIUM"},
            ],
        }

    def _create_fallback_vo_timing(self) -> Dict[str, Any]:
        """Create fallback vo_timing.json if analysis fails."""
        return {
            "source": "fallback",
            "version": "1.0",
            "total_duration_seconds": 8.0,
            "segments": [
                {"start": 0.0, "end": 2.0, "type": "SPEECH"},
                {"start": 2.0, "end": 2.5, "type": "PAUSE"},
                {"start": 2.5, "end": 5.0, "type": "SPEECH"},
                {"start": 5.0, "end": 5.5, "type": "PAUSE"},
                {"start": 5.5, "end": 8.0, "type": "SPEECH"},
            ],
            "speech_ratio": 0.75,
            "average_pause_duration": 0.5,
            "longest_pause": {"start": 5.0, "end": 5.5, "duration": 0.5},
        }

    def _create_fallback_audio_levels(self) -> Dict[str, Any]:
        """Create fallback audio_levels.json if analysis fails."""
        return {
            "source": "fallback",
            "version": "1.0",
            "music": {
                "peak_db": -3.0,
                "mean_db": -12.0,
            },
            "voiceover": {
                "peak_db": -6.0,
                "mean_db": -18.0,
                "is_whisper_detected": False,
            },
            "recommendations": {
                "music_ducking_normal_db": -10,
                "music_ducking_whisper_db": -18,
                "vo_boost_needed": False,
                "vo_boost_amount_db": 0,
            },
        }


# ============================================================================
# EXPORT
# ============================================================================

__all__ = [
    "Gen3aPreprocessor",
    "PreprocessingResult",
    "BeatInfo",
    "VOSegment",
]
