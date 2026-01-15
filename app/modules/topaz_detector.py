"""
Topaz Video AI Auto-Detection Module

Автоматично знаходить встановлений Topaz Video AI на системі.
Перевіряє стандартні шляхи встановлення на Windows.

Використання:
    from app.modules.topaz_detector import topaz_detector

    if topaz_detector.is_available:
        print(f"Topaz found: {topaz_detector.ffmpeg_path}")
    else:
        print("Topaz not installed")
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class TopazInstallation:
    """Інформація про встановлений Topaz Video AI"""
    is_available: bool
    install_path: Optional[Path]
    ffmpeg_path: Optional[Path]
    models_path: Optional[Path]
    version_hint: Optional[str]
    error_message: Optional[str] = None


class TopazDetector:
    """
    Автоматично знаходить Topaz Video AI.

    Перевіряє шляхи:
    1. Змінна середовища TOPAZ_FFMPEG_PATH
    2. Стандартні шляхи встановлення Windows
    3. Program Files (x86) як fallback
    """

    # Стандартні шляхи встановлення Topaz Video AI на Windows
    STANDARD_PATHS = [
        # Primary installation paths
        Path(r"C:\Program Files\Topaz Labs LLC\Topaz Video AI"),
        Path(r"D:\Program Files\Topaz Labs LLC\Topaz Video AI"),
        Path(r"E:\Program Files\Topaz Labs LLC\Topaz Video AI"),
        # x86 variant (unlikely but possible)
        Path(r"C:\Program Files (x86)\Topaz Labs LLC\Topaz Video AI"),
        # User-specific installations
        Path(os.path.expandvars(r"%LOCALAPPDATA%\Programs\Topaz Labs LLC\Topaz Video AI")),
    ]

    # Шлях до моделей Topaz (в ProgramData)
    MODELS_PATH = Path(r"C:\ProgramData\Topaz Labs LLC\Topaz Video AI\models")

    def __init__(self):
        self._installation: Optional[TopazInstallation] = None
        self._detected = False

    def detect(self) -> TopazInstallation:
        """
        Виконує детекцію Topaz Video AI.
        Кешує результат для наступних викликів.

        Returns:
            TopazInstallation з інформацією про встановлення
        """
        if self._detected and self._installation:
            return self._installation

        self._installation = self._do_detection()
        self._detected = True
        return self._installation

    def _do_detection(self) -> TopazInstallation:
        """Внутрішня логіка детекції"""

        # 1. Перевіряємо змінну середовища
        env_path = os.environ.get("TOPAZ_FFMPEG_PATH")
        if env_path:
            ffmpeg_path = Path(env_path)
            if ffmpeg_path.exists():
                return self._create_installation_from_ffmpeg(ffmpeg_path)

        # 2. Перевіряємо стандартні шляхи
        for install_path in self.STANDARD_PATHS:
            if not install_path.exists():
                continue

            ffmpeg_path = install_path / "ffmpeg.exe"
            if ffmpeg_path.exists():
                return self._create_installation(install_path, ffmpeg_path)

        # 3. Topaz не знайдено
        return TopazInstallation(
            is_available=False,
            install_path=None,
            ffmpeg_path=None,
            models_path=None,
            version_hint=None,
            error_message="Topaz Video AI not found. Please install from https://www.topazlabs.com/topaz-video-ai"
        )

    def _create_installation_from_ffmpeg(self, ffmpeg_path: Path) -> TopazInstallation:
        """Створює TopazInstallation з шляху до ffmpeg"""
        install_path = ffmpeg_path.parent
        return self._create_installation(install_path, ffmpeg_path)

    def _create_installation(self, install_path: Path, ffmpeg_path: Path) -> TopazInstallation:
        """Створює TopazInstallation з повною перевіркою"""

        # Перевіряємо наявність моделей
        models_path = self.MODELS_PATH if self.MODELS_PATH.exists() else None

        # Визначаємо версію з назви папки або файлів
        version_hint = self._detect_version(install_path)

        # Перевіряємо що ffmpeg справжній Topaz (має tvai фільтри)
        is_topaz_ffmpeg = self._verify_topaz_ffmpeg(ffmpeg_path)

        if not is_topaz_ffmpeg:
            return TopazInstallation(
                is_available=False,
                install_path=install_path,
                ffmpeg_path=ffmpeg_path,
                models_path=models_path,
                version_hint=version_hint,
                error_message=f"FFmpeg at {ffmpeg_path} is not Topaz Video AI FFmpeg"
            )

        return TopazInstallation(
            is_available=True,
            install_path=install_path,
            ffmpeg_path=ffmpeg_path,
            models_path=models_path,
            version_hint=version_hint,
            error_message=None
        )

    def _detect_version(self, install_path: Path) -> Optional[str]:
        """Спроба визначити версію Topaz"""
        try:
            # Шукаємо version.txt або подібний файл
            version_file = install_path / "version.txt"
            if version_file.exists():
                return version_file.read_text().strip()

            # Перевіряємо чи є uninstaller з версією в назві
            for file in install_path.glob("unins*.exe"):
                # Можемо спробувати витягти версію з метаданих
                pass

            return "Unknown"
        except Exception:
            return None

    def _verify_topaz_ffmpeg(self, ffmpeg_path: Path) -> bool:
        """
        Перевіряє що FFmpeg це дійсно Topaz версія з tvai фільтрами.

        Запускає ffmpeg -filters і шукає tvai_fi / tvai_up.
        """
        import subprocess

        try:
            result = subprocess.run(
                [str(ffmpeg_path), "-filters"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            output = result.stdout + result.stderr

            # Шукаємо Topaz-специфічні фільтри
            has_tvai_fi = "tvai_fi" in output  # Frame interpolation
            has_tvai_up = "tvai_up" in output  # Upscaling

            return has_tvai_fi or has_tvai_up

        except Exception:
            # Якщо не вдалося перевірити - припускаємо що це Topaz
            # (краще false positive ніж пропустити робочу інсталяцію)
            return True

    # ========================================================================
    # PUBLIC PROPERTIES (для зручності)
    # ========================================================================

    @property
    def is_available(self) -> bool:
        """Чи доступний Topaz Video AI"""
        return self.detect().is_available

    @property
    def ffmpeg_path(self) -> Optional[Path]:
        """Шлях до Topaz FFmpeg або None"""
        installation = self.detect()
        return installation.ffmpeg_path if installation.is_available else None

    @property
    def models_path(self) -> Optional[Path]:
        """Шлях до моделей Topaz або None"""
        installation = self.detect()
        return installation.models_path if installation.is_available else None

    @property
    def install_path(self) -> Optional[Path]:
        """Шлях до директорії встановлення або None"""
        installation = self.detect()
        return installation.install_path if installation.is_available else None

    def get_status(self) -> Dict[str, Any]:
        """
        Повертає детальний статус для логування/діагностики.

        Returns:
            dict з інформацією про Topaz
        """
        installation = self.detect()

        return {
            "available": installation.is_available,
            "install_path": str(installation.install_path) if installation.install_path else None,
            "ffmpeg_path": str(installation.ffmpeg_path) if installation.ffmpeg_path else None,
            "models_path": str(installation.models_path) if installation.models_path else None,
            "version": installation.version_hint,
            "error": installation.error_message,
        }

    def refresh(self) -> TopazInstallation:
        """
        Примусово перевіряє Topaz заново (скидає кеш).

        Returns:
            Оновлена TopazInstallation
        """
        self._detected = False
        self._installation = None
        return self.detect()


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

topaz_detector = TopazDetector()


# ============================================================================
# EXPORT
# ============================================================================

__all__ = ["TopazDetector", "TopazInstallation", "topaz_detector"]
