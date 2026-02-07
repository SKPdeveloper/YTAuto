"""
SFX Library Service

Centralized storage for sound effects with metadata indexing.
Allows reuse of SFX across projects without regenerating.

Library Structure:
    assets/sfx/
    ├── library.json          # Index of all SFX with metadata
    ├── impact/               # Impact sounds (hits, punches)
    ├── ambient/              # Ambient sounds (wind, rain)
    ├── whoosh/               # Whoosh/transition sounds
    ├── nature/               # Nature sounds (birds, water)
    ├── mechanical/           # Mechanical sounds (engines, gears)
    ├── food/                 # Food sounds (sizzle, crunch, pour)
    ├── ui/                   # UI sounds (clicks, notifications)
    └── misc/                 # Uncategorized sounds
"""

import json
import shutil
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field, asdict

from loguru import logger


# Category keywords for auto-classification
CATEGORY_KEYWORDS = {
    "impact": ["hit", "punch", "slam", "crash", "bang", "thud", "impact", "explosion", "boom"],
    "ambient": ["ambient", "background", "atmosphere", "room tone", "drone"],
    "whoosh": ["whoosh", "swish", "swoosh", "transition", "sweep", "fly by", "pass by"],
    "nature": ["wind", "rain", "thunder", "bird", "water", "ocean", "forest", "animal"],
    "mechanical": ["engine", "motor", "gear", "machine", "metal", "clank", "industrial"],
    "food": ["sizzle", "crunch", "chew", "pour", "drip", "bubble", "fry", "boil", "cooking"],
    "ui": ["click", "beep", "notification", "alert", "button", "interface"],
}


@dataclass
class SFXEntry:
    """Single SFX entry in the library"""
    id: str                           # Unique ID (sfx_xxxx)
    file: str                         # Relative path from assets/sfx/
    tags: List[str] = field(default_factory=list)
    category: str = "misc"
    description: str = ""             # Original generation prompt
    duration_ms: int = 0
    mood: str = ""
    source_project: str = ""          # Project ID where it was generated
    created_at: str = ""              # ISO timestamp
    usage_count: int = 0              # How many times used

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SFXEntry":
        return cls(**data)


@dataclass
class SFXLibraryData:
    """Full library data structure"""
    version: str = "1.0.0"
    total_count: int = 0
    last_updated: str = ""
    entries: Dict[str, SFXEntry] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "total_count": self.total_count,
            "last_updated": self.last_updated,
            "entries": {k: v.to_dict() for k, v in self.entries.items()}
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SFXLibraryData":
        entries = {
            k: SFXEntry.from_dict(v)
            for k, v in data.get("entries", {}).items()
        }
        return cls(
            version=data.get("version", "1.0.0"),
            total_count=data.get("total_count", 0),
            last_updated=data.get("last_updated", ""),
            entries=entries
        )


class SFXLibrary:
    """
    Centralized SFX library manager.

    Usage:
        library = SFXLibrary()

        # Add SFX from project
        entry = await library.add_sfx(
            source_path=Path("projects/proj_xxx/sfx/scene_1_sfx.mp3"),
            description="Loud sizzle + siren blip",
            tags=["sizzle", "alarm", "impact"],
            source_project="proj_xxx"
        )

        # Search for SFX
        results = library.search(tags=["sizzle"], category="food")

        # Get SFX for reuse
        sfx_path = library.get_sfx_path("sfx_0001")
    """

    def __init__(self, base_path: Optional[Path] = None):
        """
        Initialize SFX Library.

        Args:
            base_path: Base path for assets/sfx/ directory.
                       Defaults to project root/assets/sfx/
        """
        if base_path:
            self.base_path = Path(base_path)
        else:
            # Auto-detect project root
            self.base_path = Path(__file__).parent.parent.parent / "assets" / "sfx"

        self.library_file = self.base_path / "library.json"
        self._data: Optional[SFXLibraryData] = None

        # Ensure directory structure exists
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        """Create directory structure if not exists"""
        self.base_path.mkdir(parents=True, exist_ok=True)

        # Create category subdirectories
        categories = list(CATEGORY_KEYWORDS.keys()) + ["misc"]
        for category in categories:
            (self.base_path / category).mkdir(exist_ok=True)

        # Create library.json if not exists
        if not self.library_file.exists():
            self._save_library(SFXLibraryData())

    def _load_library(self) -> SFXLibraryData:
        """Load library from JSON file"""
        if self._data is not None:
            return self._data

        try:
            with open(self.library_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._data = SFXLibraryData.from_dict(data)
        except (FileNotFoundError, json.JSONDecodeError):
            self._data = SFXLibraryData()

        return self._data

    def _save_library(self, data: Optional[SFXLibraryData] = None) -> None:
        """Save library to JSON file"""
        if data is None:
            data = self._data or SFXLibraryData()

        data.last_updated = datetime.now().isoformat()
        data.total_count = len(data.entries)

        with open(self.library_file, "w", encoding="utf-8") as f:
            json.dump(data.to_dict(), f, indent=2, ensure_ascii=False)

        self._data = data

    def _generate_id(self) -> str:
        """Generate unique SFX ID"""
        data = self._load_library()

        # Find next available ID
        existing_nums = []
        for entry_id in data.entries.keys():
            if entry_id.startswith("sfx_"):
                try:
                    num = int(entry_id.split("_")[1])
                    existing_nums.append(num)
                except (IndexError, ValueError):
                    pass

        next_num = max(existing_nums, default=0) + 1
        return f"sfx_{next_num:04d}"

    def _classify_category(self, description: str, tags: List[str]) -> str:
        """Auto-classify SFX into category based on description and tags"""
        text = (description + " " + " ".join(tags)).lower()

        for category, keywords in CATEGORY_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                return category

        return "misc"

    async def _get_audio_duration_ms(self, file_path: Path) -> int:
        """Get audio duration in milliseconds using ffprobe"""
        try:
            import asyncio
            process = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(file_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return 0

            if process.returncode == 0:
                duration_sec = float(stdout.decode().strip())
                return int(duration_sec * 1000)
        except Exception:
            pass

        return 0

    async def add_sfx(
        self,
        source_path: Path,
        description: str,
        tags: Optional[List[str]] = None,
        category: Optional[str] = None,
        mood: str = "",
        source_project: str = ""
    ) -> Optional[SFXEntry]:
        """
        Add SFX file to library.

        Args:
            source_path: Path to source SFX file
            description: Original generation prompt / description
            tags: List of tags for searching
            category: Category (auto-detected if not provided)
            mood: Mood descriptor (energetic, calm, etc.)
            source_project: Project ID where SFX was generated

        Returns:
            SFXEntry if successful, None if failed
        """
        if not source_path.exists():
            logger.error(f"[SFXLibrary] Source file not found: {source_path}")
            return None

        # Generate tags from description if not provided
        if tags is None:
            tags = self._extract_tags(description)

        # Auto-classify category
        if category is None:
            category = self._classify_category(description, tags)

        # Generate unique ID
        sfx_id = self._generate_id()

        # Create filename with ID
        ext = source_path.suffix or ".mp3"
        filename = f"{sfx_id}{ext}"

        # Destination path
        dest_path = self.base_path / category / filename

        # Copy file
        try:
            shutil.copy2(source_path, dest_path)
            logger.info(f"[SFXLibrary] Copied {source_path.name} -> {category}/{filename}")
        except Exception as e:
            logger.error(f"[SFXLibrary] Failed to copy file: {e}")
            return None

        # Get duration
        duration_ms = await self._get_audio_duration_ms(dest_path)

        # Create entry
        entry = SFXEntry(
            id=sfx_id,
            file=f"{category}/{filename}",
            tags=tags,
            category=category,
            description=description,
            duration_ms=duration_ms,
            mood=mood,
            source_project=source_project,
            created_at=datetime.now().isoformat(),
            usage_count=0
        )

        # Add to library
        data = self._load_library()
        data.entries[sfx_id] = entry
        self._save_library(data)

        logger.success(f"[SFXLibrary] Added {sfx_id}: {description[:50]}...")
        return entry

    def _extract_tags(self, description: str) -> List[str]:
        """Extract tags from description text"""
        # Common sound-related words to use as tags
        sound_words = [
            "sizzle", "crunch", "whoosh", "boom", "click", "drip", "splash",
            "wind", "rain", "thunder", "bell", "alarm", "siren", "engine",
            "door", "footstep", "voice", "scream", "laugh", "whisper",
            "hit", "punch", "crash", "explosion", "fire", "water", "metal",
            "wood", "glass", "paper", "fabric", "electric", "digital",
            "bubble", "pour", "fry", "boil", "chop", "slice", "stir"
        ]

        desc_lower = description.lower()
        tags = []

        for word in sound_words:
            if word in desc_lower:
                tags.append(word)

        # Add mood words
        mood_words = ["loud", "soft", "intense", "gentle", "sharp", "smooth",
                      "fast", "slow", "deep", "high", "echo", "reverb"]
        for word in mood_words:
            if word in desc_lower:
                tags.append(word)

        return tags[:10]  # Limit to 10 tags

    def search(
        self,
        tags: Optional[List[str]] = None,
        category: Optional[str] = None,
        description_contains: Optional[str] = None,
        min_duration_ms: Optional[int] = None,
        max_duration_ms: Optional[int] = None,
        limit: int = 20
    ) -> List[SFXEntry]:
        """
        Search SFX library.

        Args:
            tags: Tags to match (any of)
            category: Category to filter
            description_contains: Text to search in description
            min_duration_ms: Minimum duration
            max_duration_ms: Maximum duration
            limit: Maximum results

        Returns:
            List of matching SFXEntry
        """
        data = self._load_library()
        results = []

        for entry in data.entries.values():
            # Category filter
            if category and entry.category != category:
                continue

            # Tags filter (match any)
            if tags:
                if not any(tag.lower() in [t.lower() for t in entry.tags] for tag in tags):
                    continue

            # Description filter
            if description_contains:
                if description_contains.lower() not in entry.description.lower():
                    continue

            # Duration filters
            if min_duration_ms and entry.duration_ms < min_duration_ms:
                continue
            if max_duration_ms and entry.duration_ms > max_duration_ms:
                continue

            results.append(entry)

            if len(results) >= limit:
                break

        # Sort by usage count (most used first)
        results.sort(key=lambda x: x.usage_count, reverse=True)

        return results

    def get_sfx(self, sfx_id: str) -> Optional[SFXEntry]:
        """Get SFX entry by ID"""
        data = self._load_library()
        return data.entries.get(sfx_id)

    def get_sfx_path(self, sfx_id: str) -> Optional[Path]:
        """Get full path to SFX file"""
        entry = self.get_sfx(sfx_id)
        if entry:
            return self.base_path / entry.file
        return None

    def increment_usage(self, sfx_id: str) -> None:
        """Increment usage counter for SFX"""
        data = self._load_library()
        if sfx_id in data.entries:
            data.entries[sfx_id].usage_count += 1
            self._save_library(data)

    def get_stats(self) -> Dict[str, Any]:
        """Get library statistics"""
        data = self._load_library()

        # Count by category
        by_category = {}
        total_duration_ms = 0

        for entry in data.entries.values():
            by_category[entry.category] = by_category.get(entry.category, 0) + 1
            total_duration_ms += entry.duration_ms

        return {
            "total_count": data.total_count,
            "by_category": by_category,
            "total_duration_seconds": total_duration_ms / 1000,
            "last_updated": data.last_updated
        }

    async def import_from_project(
        self,
        project_dir: Path,
        project_id: str,
        project_brief: Optional[dict] = None
    ) -> List[SFXEntry]:
        """
        Import all SFX from a project into the library.

        Args:
            project_dir: Path to project directory
            project_id: Project ID for reference
            project_brief: Optional project brief for extracting descriptions

        Returns:
            List of added SFXEntry
        """
        sfx_dir = project_dir / "sfx"
        if not sfx_dir.exists():
            logger.warning(f"[SFXLibrary] No sfx directory in project: {project_dir}")
            return []

        added = []

        # Load project brief if not provided
        if project_brief is None:
            brief_path = project_dir / "project_brief.json"
            if brief_path.exists():
                with open(brief_path, "r", encoding="utf-8") as f:
                    project_brief = json.load(f)

        # Build scene descriptions map
        scene_descriptions = {}
        if project_brief:
            for scene in project_brief.get("scenes", []):
                scene_num = scene.get("scene_number", 0)
                desc = scene.get("audio_sfx") or scene.get("audio_moment") or ""
                if desc:
                    scene_descriptions[scene_num] = desc

            # Sonic hook description
            sonic_hook = project_brief.get("audio", {}).get("sonic_hook", {})
            if sonic_hook.get("description"):
                scene_descriptions["sonic_hook"] = sonic_hook["description"]

        # Process each SFX file
        for sfx_file in sfx_dir.glob("*.mp3"):
            # Determine description
            description = ""

            if sfx_file.stem == "sonic_hook":
                description = scene_descriptions.get("sonic_hook", "Sonic hook intro sound")
            elif sfx_file.stem.startswith("scene_"):
                try:
                    scene_num = int(sfx_file.stem.split("_")[1])
                    description = scene_descriptions.get(scene_num, f"Scene {scene_num} SFX")
                except (IndexError, ValueError):
                    description = f"SFX from {sfx_file.stem}"
            else:
                description = f"SFX: {sfx_file.stem}"

            # Add to library
            entry = await self.add_sfx(
                source_path=sfx_file,
                description=description,
                source_project=project_id
            )

            if entry:
                added.append(entry)

        logger.success(f"[SFXLibrary] Imported {len(added)} SFX from project {project_id}")
        return added


# Singleton instance
_library: Optional[SFXLibrary] = None


def get_sfx_library() -> SFXLibrary:
    """Get the global SFXLibrary instance"""
    global _library
    if _library is None:
        _library = SFXLibrary()
    return _library


__all__ = ["SFXLibrary", "SFXEntry", "get_sfx_library"]
