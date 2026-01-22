"""
Configuration Manager для Edible House Automator
Використовує Pydantic Settings для автозавантаження з .env
Підтримує multi-model (Gemini/Claude для ContentBrain)
"""

from pathlib import Path
from typing import Literal
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Централізована конфігурація з автозавантаженням з .env
    Всі paths автоматично адаптуються під поточну машину
    """

    # ========================================================================
    # PATHS (автоматично адаптуються під поточну машину)
    # ========================================================================

    BASE_DIR: Path = Field(
        default_factory=lambda: Path(__file__).parent.parent.parent.resolve(),
        description="Корінь проєкту (YTAuto)"
    )

    @property
    def PROJECTS_DIR(self) -> Path:
        """Директорія з генерованими проєктами"""
        return self.BASE_DIR / "projects"

    @property
    def LOGS_DIR(self) -> Path:
        """Директорія з логами"""
        return self.BASE_DIR / "logs"

    @property
    def DATA_DIR(self) -> Path:
        """Директорія з базою даних"""
        return self.BASE_DIR / "data"

    @property
    def CONFIG_DIR(self) -> Path:
        """Директорія з конфігураційними файлами"""
        return self.BASE_DIR / "config"

    # ========================================================================
    # API KEYS
    # ========================================================================

    # Higgsfield
    HIGGSFIELD_API_KEY: str = Field(
        default="",
        description="Higgsfield API key"
    )
    HIGGSFIELD_API_SECRET: str = Field(
        default="",
        description="Higgsfield API secret"
    )

    # Google Gemini
    GOOGLE_GEMINI_API_KEY: str = Field(
        default="",
        description="Google Gemini API key"
    )

    # Anthropic Claude (optional для ContentBrain)
    ANTHROPIC_API_KEY: str = Field(
        default="",
        description="Anthropic Claude API key (optional)"
    )

    # ElevenLabs TTS
    ELEVENLABS_API_KEY: str = Field(
        default="",
        description="ElevenLabs API key for text-to-speech"
    )

    # Replicate (Stable Audio Open 1.0)
    REPLICATE_API_TOKEN: str = Field(
        default="",
        description="Replicate API token for music generation"
    )


    # ========================================================================
    # AI MODELS CONFIGURATION
    # ========================================================================

    # ContentBrain - вибір моделі для генерації сценаріїв
    CONTENTBRAIN_PROVIDER: Literal["gemini", "claude"] = Field(
        default="gemini",
        description="AI provider для ContentBrain (gemini або claude)"
    )

    CONTENTBRAIN_MODEL: str = Field(
        default="gemini-3-pro",
        description="Модель для ContentBrain (gemini-3-pro або claude-3-5-sonnet-20241022)"
    )

    # Gemini Validator
    GEMINI_VALIDATOR_MODEL: str = Field(
        default="gemini-3-pro",
        description="Модель Gemini для валідації зображень"
    )

    GEMINI_TEMPERATURE: float = Field(
        default=0.3,
        ge=0.0,
        le=2.0,
        description="Temperature для Gemini (0.0-2.0)"
    )

    # ========================================================================
    # ELEVENLABS TTS SETTINGS
    # ========================================================================

    ELEVENLABS_MODEL: str = Field(
        default="eleven_multilingual_v2",
        description="Модель ElevenLabs (eleven_multilingual_v2, eleven_flash_v2_5, eleven_turbo_v2_5)"
    )

    ELEVENLABS_DEFAULT_VOICE_ID: str = Field(
        default="pNInz6obpgDQGcFmaJgB",
        description="Voice ID за замовчуванням (Adam)"
    )

    ELEVENLABS_OUTPUT_FORMAT: str = Field(
        default="mp3_44100_128",
        description="Формат виводу (mp3_44100_128, mp3_44100_192)"
    )

    # ========================================================================
    # REPLICATE MUSIC GENERATION (Stable Audio Open 1.0)
    # ========================================================================

    REPLICATE_MUSIC_MODEL: str = Field(
        default="stackadoc/stable-audio-open-1.0",
        description="Replicate model for music generation"
    )

    REPLICATE_MUSIC_DURATION: float = Field(
        default=30.0,
        ge=1.0,
        le=47.0,
        description="Duration of generated music in seconds (max 47s)"
    )

    REPLICATE_MUSIC_SAMPLE_RATE: int = Field(
        default=44100,
        description="Sample rate for generated audio"
    )

    # ========================================================================
    # HIGGSFIELD SETTINGS
    # ========================================================================

    HIGGSFIELD_BASE_URL: str = Field(
        default="https://platform.higgsfield.ai",
        description="Base URL для Higgsfield API"
    )

    HIGGSFIELD_IMAGE_MODEL: str = Field(
        default="nano-banana-pro",
        description="Модель для генерації зображень (Nano Banana Pro - Google Gemini 3 Pro)"
    )

    HIGGSFIELD_VIDEO_MODEL: str = Field(
        default="kling-video/v2.6/pro/image-to-video",
        description="Модель для генерації відео (Kling v2.6 з Native Audio)"
    )

    HIGGSFIELD_ASPECT_RATIO: str = Field(
        default="16:9",
        description="Співвідношення сторін для зображень"
    )

    HIGGSFIELD_RESOLUTION: str = Field(
        default="2k",
        description="Роздільна здатність зображень (1k | 2k | 4k для Nano Banana Pro)"
    )

    HIGGSFIELD_VIDEO_DURATION: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Тривалість відео в секундах (1-10)"
    )

    # ========================================================================
    # PROCESSING SETTINGS
    # ========================================================================

    MAX_RETRIES: int = Field(
        default=2,
        ge=0,
        le=5,
        description="Максимальна кількість retry при помилках"
    )

    TOPAZ_QUEUE_LIMIT: int = Field(
        default=1,
        ge=1,
        le=3,
        description="Кількість одночасних Topaz процесів (1 рекомендовано)"
    )

    CONCURRENT_SCENES: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Кількість сцен для паралельної обробки"
    )

    REQUEST_TIMEOUT: int = Field(
        default=300,
        ge=30,
        le=600,
        description="Timeout для HTTP запитів в секундах"
    )

    POLLING_INTERVAL: int = Field(
        default=5,
        ge=1,
        le=30,
        description="Інтервал polling для перевірки статусу (секунди)"
    )

    TOPIC_MEMORY_LIMIT: int = Field(
        default=20,
        ge=5,
        le=100,
        description="Кількість останніх тем для blacklist (5-100)"
    )

    # ========================================================================
    # TOPAZ VIDEO AI SETTINGS
    # ========================================================================

    TOPAZ_ENABLED: bool = Field(
        default=True,
        description="Enable Topaz Video AI post-processing (FPS interpolation + upscaling)"
    )

    TOPAZ_FFMPEG_PATH: Path = Field(
        default=Path(r"C:\Program Files\Topaz Labs LLC\Topaz Video AI\ffmpeg.exe"),
        description="Шлях до Topaz FFmpeg executable"
    )

    # Frame Interpolation (Step 1: FPS Boost)
    TOPAZ_FPS_MODEL: str = Field(
        default="apf-1",
        description="Модель для frame interpolation (apf-1 Apollo Fast, apo-8 Apollo, chf-3 Chronos Fast, chr-2 Chronos)"
    )

    TOPAZ_TARGET_FPS: int = Field(
        default=60,
        ge=24,
        le=120,
        description="Цільовий FPS після інтерполяції"
    )

    # Upscaling (Step 2: 4K Enhancement)
    TOPAZ_UPSCALE_MODEL: str = Field(
        default="prob-3",
        description="Модель для upscaling (prob-3 Proteus v3, alq-13 Artemis, iris-3, nyx-3)"
    )

    TOPAZ_SCALE: int = Field(
        default=2,
        ge=1,
        le=4,
        description="Коефіцієнт масштабування (1-4x)"
    )

    # Output Resolution (4K Portrait: 2160x3840)
    TOPAZ_OUTPUT_WIDTH: int = Field(
        default=2160,
        description="Ширина вихідного відео (для 4K portrait)"
    )

    TOPAZ_OUTPUT_HEIGHT: int = Field(
        default=3840,
        description="Висота вихідного відео (для 4K portrait)"
    )

    # Encoding Settings
    TOPAZ_CODEC: str = Field(
        default="hevc_nvenc",
        description="Кодек для вихідного відео (hevc_nvenc/h264_nvenc для NVIDIA, hevc_amf/h264_amf для AMD)"
    )

    TOPAZ_BITRATE: str = Field(
        default="65M",
        description="Bitrate для вихідного відео (65M для 4K 60fps)"
    )

    TOPAZ_QUALITY: int = Field(
        default=15,
        ge=1,
        le=51,
        description="Якість CRF/CQ (менше = краще, 15-18 рекомендовано для 4K)"
    )

    # Processing Settings
    TOPAZ_MAX_RETRIES: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Максимум спроб при помилці Topaz"
    )

    TOPAZ_TIMEOUT: int = Field(
        default=3600,
        ge=300,
        le=7200,
        description="Timeout для одного етапу обробки (секунди)"
    )

    # Enhancement Parameters
    TOPAZ_COMPRESSION: float = Field(
        default=0.0,
        ge=-1.0,
        le=1.0,
        description="Компресія артефактів (-1 до 1)"
    )

    TOPAZ_DETAILS: float = Field(
        default=0.0,
        ge=-1.0,
        le=1.0,
        description="Деталізація (-1 до 1)"
    )

    TOPAZ_BLUR: float = Field(
        default=0.0,
        ge=-1.0,
        le=1.0,
        description="Розмиття (-1 до 1)"
    )

    TOPAZ_NOISE: float = Field(
        default=0.0,
        ge=-1.0,
        le=1.0,
        description="Шумоподавлення (-1 до 1)"
    )


    # ========================================================================
    # ADSPOWER SETTINGS (для HiggsFieldWebClient)
    # ========================================================================

    ADSPOWER_API_KEY: str = Field(
        default="",
        description="AdsPower API ключ"
    )

    ADSPOWER_BASE_URL: str = Field(
        default="http://local.adspower.net:50325",
        description="AdsPower Local API URL"
    )

    ADSPOWER_PROFILE_ID: str = Field(
        default="",
        description="AdsPower профіль ID для Higgsfield"
    )

    # Higgsfield Web Settings (через AdsPower)
    HIGGSFIELD_WEB_ENABLED: bool = Field(
        default=False,
        description="Використовувати Higgsfield Web замість API"
    )

    HIGGSFIELD_WEB_ASPECT_RATIO: str = Field(
        default="9:16",
        description="Aspect ratio для веб-генерації"
    )

    HIGGSFIELD_WEB_IMAGE_RESOLUTION: str = Field(
        default="2K",
        description="Роздільна здатність зображень (1K, 2K)"
    )

    HIGGSFIELD_WEB_VIDEO_MODEL: str = Field(
        default="Kling 2.6",
        description="Модель для відео генерації"
    )

    HIGGSFIELD_WEB_VIDEO_DURATION: int = Field(
        default=10,
        ge=5,
        le=10,
        description="Тривалість відео в секундах (5 або 10)"
    )

    # Використовувати SimpleVideoGenerator замість складної паралельної логіки
    USE_SIMPLE_VIDEO_GENERATOR: bool = Field(
        default=True,
        description="Використовувати просту послідовну генерацію відео (рекомендовано)"
    )

    # Higgsfield Web Login (для автологіну)
    HIGGSFIELD_WEB_EMAIL: str = Field(
        default="",
        description="Email для автологіну в Higgsfield"
    )

    HIGGSFIELD_WEB_PASSWORD: str = Field(
        default="",
        description="Пароль для автологіну в Higgsfield"
    )

    # ========================================================================
    # WEB UI SETTINGS
    # ========================================================================

    WEB_HOST: str = Field(
        default="127.0.0.1",
        description="Host для FastAPI сервера"
    )

    WEB_PORT: int = Field(
        default=8000,
        ge=1024,
        le=65535,
        description="Port для FastAPI сервера"
    )

    # ========================================================================
    # LOGGING SETTINGS
    # ========================================================================

    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        description="Рівень логування"
    )

    LOG_ROTATION: str = Field(
        default="10 MB",
        description="Розмір файлу для ротації логів"
    )

    LOG_RETENTION: str = Field(
        default="1 week",
        description="Час зберігання старих логів"
    )

    # ========================================================================
    # VALIDATORS
    # ========================================================================

    @field_validator("TOPAZ_FFMPEG_PATH")
    @classmethod
    def validate_topaz_path(cls, v: Path) -> Path:
        """Перевіряє що Topaz FFmpeg існує (warning якщо ні)"""
        if not v.exists():
            import warnings
            warnings.warn(
                f"Topaz FFmpeg не знайдено за шляхом: {v}\n"
                f"Переконайся що Topaz Video AI встановлено, або зміни шлях в .env\n"
                f"Очікуваний шлях: C:\\Program Files\\Topaz Labs LLC\\Topaz Video AI\\ffmpeg.exe"
            )
        return v

    @field_validator("TOPAZ_CODEC")
    @classmethod
    def validate_topaz_codec(cls, v: str) -> str:
        """Перевіряє що кодек підтримується"""
        supported_codecs = [
            "hevc_nvenc",  # NVIDIA HEVC
            "h264_nvenc",  # NVIDIA H.264
            "hevc_amf",    # AMD HEVC
            "h264_amf",    # AMD H.264
            "libx265",     # CPU HEVC
            "libx264",     # CPU H.264
        ]
        if v not in supported_codecs:
            import warnings
            warnings.warn(
                f"Кодек '{v}' може не підтримуватись. "
                f"Рекомендовані: {', '.join(supported_codecs)}"
            )
        return v

    @field_validator("CONTENTBRAIN_MODEL")
    @classmethod
    def validate_contentbrain_model(cls, v: str, info) -> str:
        """Перевіряє відповідність моделі та провайдера"""
        provider = info.data.get("CONTENTBRAIN_PROVIDER", "gemini")

        if provider == "gemini" and not v.startswith("gemini"):
            raise ValueError(
                f"CONTENTBRAIN_PROVIDER=gemini, але модель '{v}' не є Gemini моделлю"
            )
        if provider == "claude" and not v.startswith("claude"):
            raise ValueError(
                f"CONTENTBRAIN_PROVIDER=claude, але модель '{v}' не є Claude моделлю"
            )

        return v

    # ========================================================================
    # PYDANTIC SETTINGS CONFIG
    # ========================================================================

    model_config = SettingsConfigDict(
        env_file="config/.env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"  # Ігнорує зайві поля в .env
    )

    # ========================================================================
    # HELPER METHODS
    # ========================================================================

    def ensure_directories(self) -> None:
        """Створює всі необхідні директорії якщо їх немає"""
        for dir_path in [
            self.PROJECTS_DIR,
            self.LOGS_DIR,
            self.DATA_DIR,
            self.CONFIG_DIR,
        ]:
            dir_path.mkdir(parents=True, exist_ok=True)

    def get_project_dir(self, project_id: str) -> Path:
        """Повертає директорію конкретного проєкту"""
        return self.PROJECTS_DIR / project_id

    def get_scene_dir(self, project_id: str, scene_number: int) -> Path:
        """Повертає директорію конкретної сцени"""
        return self.get_project_dir(project_id) / f"scene_{scene_number}"

    def get_higgsfield_auth_header(self) -> str:
        """Формує Authorization header для Higgsfield"""
        return f"Key {self.HIGGSFIELD_API_KEY}:{self.HIGGSFIELD_API_SECRET}"


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

# Створюємо глобальний екземпляр settings
try:
    settings = Settings()
    # Автоматично створюємо директорії при імпорті
    settings.ensure_directories()
except Exception as e:
    # Якщо .env не існує або невалідний, використовуємо defaults
    import warnings
    warnings.warn(
        f"Не вдалося завантажити .env: {e}\n"
        f"Використовуються значення за замовчуванням. "
        f"Створи config/.env файл з API keys!"
    )
    # Fallback до defaults (без .env)
    settings = Settings(_env_file=None)


# ============================================================================
# EXPORT
# ============================================================================

__all__ = ["Settings", "settings"]
