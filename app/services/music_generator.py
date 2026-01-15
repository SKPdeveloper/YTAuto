"""
Music Generator - Replicate Stable Audio Open 1.0 Integration

Generates background music for Glaze City videos using Stable Audio Open 1.0.
Replaces SUNO for music generation in the 5-layer audio system.

Features:
- Prompt-based music generation
- Up to 47 seconds of audio
- Various styles (cinematic, epic, ambient, etc.)
- Automatic download and save

API: https://replicate.com/stackadoc/stable-audio-open-1.0
"""

import asyncio
import httpx
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass

from app.core.config import settings
from app.utils.logger import logger


@dataclass
class MusicGenerationResult:
    """Result of music generation."""
    success: bool
    file_path: Optional[Path] = None
    duration: float = 0.0
    prompt: str = ""
    error: Optional[str] = None


class MusicGenerator:
    """
    Replicate Stable Audio Open 1.0 Music Generator

    Generates background music for Glaze City video pipeline.
    Part of the 5-layer audio system (MUSIC layer).

    Usage:
        generator = MusicGenerator()
        result = await generator.generate(
            prompt="epic cinematic orchestral music, dramatic",
            duration=30.0,
            output_path=Path("project/music.mp3")
        )
    """

    # Pre-defined music styles for Glaze City
    MUSIC_STYLES = {
        "cinematic": "cinematic orchestral music, epic, dramatic, film score",
        "ambient": "ambient electronic music, atmospheric, dreamy, soundscape",
        "upbeat": "upbeat electronic music, energetic, positive, modern",
        "mysterious": "mysterious dark ambient music, suspenseful, ethereal",
        "epic": "epic orchestral trailer music, powerful, heroic, brass",
        "playful": "playful whimsical music, cheerful, lighthearted, quirky",
        "dramatic": "dramatic tension music, intense, building, cinematic",
        "chill": "chill lo-fi beats, relaxing, mellow, smooth",
    }

    def __init__(self):
        """Initialize MusicGenerator with Replicate API."""
        self.api_token = settings.REPLICATE_API_TOKEN
        self.model = settings.REPLICATE_MUSIC_MODEL
        self.default_duration = settings.REPLICATE_MUSIC_DURATION
        self.sample_rate = settings.REPLICATE_MUSIC_SAMPLE_RATE

        # API endpoints
        self.base_url = "https://api.replicate.com/v1"
        self.predictions_url = f"{self.base_url}/predictions"

        # Validate API token
        if not self.api_token:
            logger.warning("Replicate API token not configured. Set REPLICATE_API_TOKEN in .env")

        logger.info("MusicGenerator initialized:")
        logger.info(f"  Model: {self.model}")
        logger.info(f"  Default duration: {self.default_duration}s")
        logger.info(f"  Sample rate: {self.sample_rate}")

    async def generate(
        self,
        prompt: str,
        output_path: Path,
        duration: Optional[float] = None,
        negative_prompt: Optional[str] = None,
    ) -> MusicGenerationResult:
        """
        Generate music from a text prompt.

        Args:
            prompt: Text description of the desired music
            output_path: Path to save the generated audio
            duration: Duration in seconds (default: 30, max: 47)
            negative_prompt: What to avoid in the generation

        Returns:
            MusicGenerationResult with success status and file path

        Example:
            >>> result = await generator.generate(
            ...     prompt="epic cinematic orchestral music",
            ...     output_path=Path("music.mp3"),
            ...     duration=25.0
            ... )
        """
        if not self.api_token:
            return MusicGenerationResult(
                success=False,
                prompt=prompt,
                error="Replicate API token not configured"
            )

        duration = duration or self.default_duration
        duration = min(duration, 47.0)  # Max 47 seconds

        logger.info(f"Generating music ({duration}s)...")
        logger.info(f"  Prompt: {prompt[:100]}...")

        try:
            # Create prediction
            prediction = await self._create_prediction(
                prompt=prompt,
                duration=duration,
                negative_prompt=negative_prompt,
            )

            if not prediction:
                return MusicGenerationResult(
                    success=False,
                    prompt=prompt,
                    error="Failed to create prediction"
                )

            # Poll for completion
            prediction_id = prediction.get("id")
            logger.info(f"  Prediction ID: {prediction_id}")

            result = await self._wait_for_completion(prediction_id)

            if not result:
                return MusicGenerationResult(
                    success=False,
                    prompt=prompt,
                    error="Prediction failed or timed out"
                )

            # Download the audio
            output_url = result.get("output")
            if not output_url:
                return MusicGenerationResult(
                    success=False,
                    prompt=prompt,
                    error="No output URL in result"
                )

            await self._download_audio(output_url, output_path)

            logger.success(f"Music generated: {output_path}")

            return MusicGenerationResult(
                success=True,
                file_path=output_path,
                duration=duration,
                prompt=prompt,
            )

        except Exception as e:
            logger.error(f"Music generation failed: {e}")
            return MusicGenerationResult(
                success=False,
                prompt=prompt,
                error=str(e)
            )

    async def generate_for_project(
        self,
        project_dir: Path,
        atmosphere: str = "cinematic",
        duration: float = 30.0,
        custom_prompt: Optional[str] = None,
    ) -> MusicGenerationResult:
        """
        Generate music for a Glaze City project.

        Args:
            project_dir: Project directory to save music
            atmosphere: Music style from MUSIC_STYLES
            duration: Duration in seconds
            custom_prompt: Override the style prompt

        Returns:
            MusicGenerationResult
        """
        output_path = project_dir / "music.mp3"

        # Build prompt
        if custom_prompt:
            prompt = custom_prompt
        else:
            base_style = self.MUSIC_STYLES.get(atmosphere, self.MUSIC_STYLES["cinematic"])
            prompt = f"{base_style}, {duration} seconds, high quality, no vocals"

        return await self.generate(
            prompt=prompt,
            output_path=output_path,
            duration=duration,
        )

    async def generate_ambient_bed(
        self,
        project_dir: Path,
        duration: float = 30.0,
    ) -> MusicGenerationResult:
        """
        Generate ambient bed audio for the BED layer.

        This is a quieter, atmospheric track for background ambiance.
        """
        output_path = project_dir / "ambient.mp3"

        prompt = (
            "soft ambient soundscape, atmospheric, subtle, "
            "gentle drone, peaceful, background texture, no melody, "
            f"{duration} seconds"
        )

        return await self.generate(
            prompt=prompt,
            output_path=output_path,
            duration=duration,
            negative_prompt="loud, drums, vocals, speech",
        )

    # Model version hash for stable-audio-open-1.0
    MODEL_VERSION = "9aff84a639f96d0f7e6081cdea002d15133d0043727f849c40abdd166b7c75a8"

    async def _create_prediction(
        self,
        prompt: str,
        duration: float,
        negative_prompt: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Create a prediction on Replicate."""
        headers = {
            "Authorization": f"Token {self.api_token}",
            "Content-Type": "application/json",
        }

        # Build input according to Stable Audio Open 1.0 API
        # Note: seconds_total must be an integer, sampler_type not sampler
        input_data = {
            "prompt": prompt,
            "seconds_total": int(duration),
            "sampler_type": "dpmpp-3m-sde",  # Recommended sampler
            "cfg_scale": 6,  # Guidance scale (default)
            "steps": 100,  # Number of steps
            "seed": -1,  # Random seed
        }

        if negative_prompt:
            input_data["negative_prompt"] = negative_prompt

        # Use /predictions endpoint with version hash (not /models/{model}/predictions)
        payload = {
            "version": self.MODEL_VERSION,
            "input": input_data,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                self.predictions_url,  # Use /v1/predictions
                headers=headers,
                json=payload,
            )

            if response.status_code == 201:
                return response.json()
            else:
                logger.error(f"Failed to create prediction: {response.status_code}")
                logger.error(f"Response: {response.text}")
                return None

    async def _wait_for_completion(
        self,
        prediction_id: str,
        timeout: int = 300,
        poll_interval: int = 5,
    ) -> Optional[Dict[str, Any]]:
        """Poll for prediction completion."""
        headers = {
            "Authorization": f"Token {self.api_token}",
        }

        url = f"{self.predictions_url}/{prediction_id}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            elapsed = 0

            while elapsed < timeout:
                response = await client.get(url, headers=headers)

                if response.status_code != 200:
                    logger.error(f"Failed to get prediction: {response.status_code}")
                    return None

                data = response.json()
                status = data.get("status")

                logger.debug(f"  Prediction status: {status}")

                if status == "succeeded":
                    return data
                elif status == "failed":
                    error = data.get("error", "Unknown error")
                    logger.error(f"Prediction failed: {error}")
                    return None
                elif status == "canceled":
                    logger.warning("Prediction was canceled")
                    return None

                # Still processing
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

        logger.error(f"Prediction timed out after {timeout}s")
        return None

    async def _download_audio(
        self,
        url: str,
        output_path: Path,
    ) -> None:
        """Download audio file from URL."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(url)

            if response.status_code == 200:
                output_path.write_bytes(response.content)
                logger.info(f"  Downloaded: {len(response.content) / 1024:.1f} KB")
            else:
                raise Exception(f"Failed to download audio: {response.status_code}")

    def get_style_prompt(self, style: str) -> str:
        """Get the prompt for a predefined style."""
        return self.MUSIC_STYLES.get(style, self.MUSIC_STYLES["cinematic"])

    def list_styles(self) -> Dict[str, str]:
        """List all available music styles."""
        return self.MUSIC_STYLES.copy()


# ============================================================================
# EXPORT
# ============================================================================

__all__ = ["MusicGenerator", "MusicGenerationResult"]
