"""
Structural Memory — Anti-Pattern Diversification for Glaze City Automation

Tracks structural fingerprints of last N videos to prevent template-cloned patterns.
FIFO queue — newest fingerprints push out oldest.

YouTube (Jan 2026+) bans "template-cloned" AI content.
This module enforces structural diversity beyond topic diversity (TopicMemory).

Usage:
    from app.services.structural_memory import structural_memory

    # Get structural context for GEN1 prompt
    context = structural_memory.generate_structural_context()

    # Get recent textures for {{RECENT_TEXTURES}} placeholder
    textures = structural_memory.generate_recent_textures()

    # After successful GEN1 generation
    structural_memory.add_fingerprint(gen1_dict)
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List

from app.core.config import settings
from app.utils.logger import logger


# Texture group classification — comprehensive mapping from real project data
# Groups: CRISPY (hard/crunchy/dry), SMOOTH (soft/creamy/liquid), CHEWY (elastic/sticky/moist)
_TEXTURE_GROUPS: dict = {
    # CRISPY group — hard, crunchy, dry, fried, crystalline
    "crispy": "CRISPY", "crunchy": "CRISPY", "brittle": "CRISPY",
    "crunchy-wet": "CRISPY", "flaky": "CRISPY", "flakey": "CRISPY",
    "dry": "CRISPY", "crumbly": "CRISPY", "crusty": "CRISPY",
    "blistered": "CRISPY", "toasted": "CRISPY", "caramelized": "CRISPY",
    "shattered": "CRISPY", "shattering": "CRISPY", "snappy": "CRISPY",
    "crackling": "CRISPY", "wafer-thin": "CRISPY", "golden-brown": "CRISPY",
    "charred": "CRISPY", "fried": "CRISPY", "roasted": "CRISPY",
    "burnt": "CRISPY", "crystalline": "CRISPY", "glassy": "CRISPY",
    "hard": "CRISPY", "craggy": "CRISPY", "granular": "CRISPY",
    "laminated": "CRISPY", "puffed": "CRISPY", "dusted": "CRISPY",
    "sugared": "CRISPY", "sugar-crusted": "CRISPY", "ridged": "CRISPY",
    "seeded": "CRISPY", "salty": "CRISPY", "layered": "CRISPY",
    # SMOOTH group — soft, creamy, liquid, oily, glossy
    "creamy": "SMOOTH", "smooth": "SMOOTH", "silky": "SMOOTH",
    "velvety": "SMOOTH", "soft": "SMOOTH", "melty": "SMOOTH",
    "buttery": "SMOOTH", "rich": "SMOOTH", "dense": "SMOOTH",
    "whipped": "SMOOTH", "glossy": "SMOOTH", "molten": "SMOOTH",
    "liquid": "SMOOTH", "runny": "SMOOTH", "flowing": "SMOOTH",
    "frozen": "SMOOTH", "icy": "SMOOTH", "cold": "SMOOTH",
    "wet": "SMOOTH", "oily": "SMOOTH", "greasy": "SMOOTH",
    "glazed": "SMOOTH", "syrupy": "SMOOTH", "viscous": "SMOOTH",
    "juicy": "SMOOTH", "milky": "SMOOTH", "condensed": "SMOOTH",
    "oozing": "SMOOTH", "fatty": "SMOOTH", "bursting": "SMOOTH",
    "glistening": "SMOOTH",
    # CHEWY group — elastic, sticky, moist, springy, doughy
    "chewy": "CHEWY", "gooey": "CHEWY", "sticky": "CHEWY",
    "elastic": "CHEWY", "stretchy": "CHEWY", "gelatinous": "CHEWY",
    "rubbery": "CHEWY", "doughy": "CHEWY", "springy": "CHEWY",
    "translucent": "CHEWY", "jiggly": "CHEWY", "bouncy": "CHEWY",
    "taffy-like": "CHEWY", "glutinous": "CHEWY", "spongy": "CHEWY",
    "tender": "CHEWY", "moist": "CHEWY", "pillowy": "CHEWY",
    "marshmallow": "CHEWY", "stringy": "CHEWY", "fibrous": "CHEWY",
    "soaked": "CHEWY", "damp": "CHEWY", "raw": "CHEWY",
    "fleshy": "CHEWY", "fluffy-interior": "CHEWY",
}

# Warning line format detection patterns
_WARNING_FORMATS: list = [
    ("A", re.compile(r"was never meant", re.IGNORECASE)),
    ("B", re.compile(r"^don['\u2019]t\b", re.IGNORECASE)),
    ("C", re.compile(r"should(n['\u2019]t| not)\b", re.IGNORECASE)),
    ("D", re.compile(r"(no one|nobody)\b", re.IGNORECASE)),
    ("E", re.compile(r"(last|only|final)\b", re.IGNORECASE)),
    ("F", re.compile(r"(they|we|you) (said|told|warned)\b", re.IGNORECASE)),
]

# Narrative structure detection: map narrative_purpose sequences to structure labels
_NARRATIVE_STRUCTURES = ["A", "B", "C", "D", "E"]


class StructuralMemory:
    """
    FIFO queue of structural fingerprints for last N videos.

    Each fingerprint captures 17 structural dimensions of a video,
    enabling frequency tracking and diversity enforcement.

    Attributes:
        fingerprints: List of fingerprint dicts (newest first)
        storage_path: Path to JSON storage file
    """

    DEFAULT_STORAGE_PATH = Path("data/structural_memory.json")

    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path or self.DEFAULT_STORAGE_PATH
        self.fingerprints: List[Dict] = []
        self._load()

        logger.debug(f"StructuralMemory initialized: {len(self.fingerprints)}/{self.max_slots} fingerprints")

    @property
    def max_slots(self) -> int:
        """Get max slots from settings."""
        return getattr(settings, 'STRUCTURAL_MEMORY_LIMIT', 10)

    # ========================================================================
    # STORAGE
    # ========================================================================

    def _load(self) -> None:
        """Load fingerprints from JSON file."""
        try:
            if self.storage_path.exists():
                with open(self.storage_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.fingerprints = data.get("fingerprints", [])
                    logger.debug(f"Loaded {len(self.fingerprints)} fingerprints from {self.storage_path}")
            else:
                self.fingerprints = []
                logger.debug(f"No existing structural memory at {self.storage_path}")
        except Exception as e:
            logger.error(f"Failed to load structural memory: {e}")
            self.fingerprints = []

    def _save(self) -> None:
        """Save fingerprints to JSON file."""
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump({
                    "version": "1.0",
                    "max_slots": self.max_slots,
                    "current_count": len(self.fingerprints),
                    "updated_at": datetime.now().isoformat(),
                    "fingerprints": self.fingerprints,
                }, f, indent=2, ensure_ascii=False)
            logger.debug(f"Saved {len(self.fingerprints)} fingerprints to {self.storage_path}")
        except Exception as e:
            logger.error(f"Failed to save structural memory: {e}")

    # ========================================================================
    # EXTRACTION
    # ========================================================================

    def add_fingerprint(self, gen1_output: Dict) -> None:
        """
        Extract fingerprint from GEN1 dict, FIFO insert, trim to max_slots, save.

        Args:
            gen1_output: Full GEN1 JSON output as dict (with optional _project_id).
        """
        try:
            fp = self._extract_fingerprint(gen1_output)

            # FIFO: newest first
            self.fingerprints.insert(0, fp)

            # Trim to max_slots
            while len(self.fingerprints) > self.max_slots:
                self.fingerprints.pop()

            self._save()

            title = gen1_output.get("metadata", {}).get("title", fp.get("project_id", "unknown"))
            logger.info(f"StructuralMemory: Added fingerprint ({len(self.fingerprints)}/{self.max_slots}): {title}")

        except Exception as e:
            logger.error(f"Failed to add structural fingerprint: {e}")

    def _extract_fingerprint(self, data: Dict, file_mtime: Optional[str] = None) -> Dict:
        """Extract 17-field fingerprint from raw GEN1 JSON or merged GlazeCityProject.

        Handles both:
        - Raw GEN1 output (from prompt_router.add_fingerprint): fields at root
        - Merged project_brief.json (from backfill): some fields inside gen1_raw
        """
        # For merged output (project_brief.json), some fields are inside gen1_raw
        gen1_raw = data.get("gen1_raw", {})
        if not isinstance(gen1_raw, dict):
            gen1_raw = {}

        # Fields that exist at root in both raw and merged formats
        hook = data.get("hook", {})
        loop = data.get("loop", {})
        scenes = data.get("scenes", [])
        lighting = data.get("lighting_master", {})
        food_id = data.get("food_identity", {})
        warning_line = data.get("warning_line", "")

        # Fields that may be at root (raw GEN1) or inside gen1_raw (merged)
        metadata = data.get("metadata", {})
        if not isinstance(metadata, dict) or not metadata.get("concept"):
            # Try gen1_metadata for merged output
            metadata = data.get("gen1_metadata", gen1_raw.get("metadata", {}))
        concept = metadata.get("concept", {}) if isinstance(metadata, dict) else {}

        engagement = data.get("engagement", gen1_raw.get("engagement", {}))
        if not isinstance(engagement, dict):
            engagement = {}

        controversy_seed = data.get("controversy_seed", gen1_raw.get("controversy_seed", {}))
        if not isinstance(controversy_seed, dict):
            controversy_seed = {}

        # SP values from scenes
        sp_values = []
        for s in scenes:
            sp = s.get("sensory_pressure")
            if isinstance(sp, (int, float)):
                sp_values.append((s.get("scene_number", 0), int(sp)))

        sp_scene_1 = 7  # default
        sp_peak_scene = 5  # default
        if sp_values:
            for sn, sp in sp_values:
                if sn == 1:
                    sp_scene_1 = sp
                    break
            peak = max(sp_values, key=lambda x: x[1])
            sp_peak_scene = peak[0]

        # Warning format detection
        warning_format = self._detect_warning_format(warning_line)

        # Controversy technique
        controversy = controversy_seed.get("technique", "UNKNOWN")

        # Series hook — locations vary:
        #   raw GEN1: engagement.series_hook or series_identity.series_hook
        #   merged:   series_identity.series_hook or gen1_raw.series_identity.series_hook
        series_hook_obj = None
        for container in [
            engagement,
            data.get("series_identity", {}),
            gen1_raw.get("series_identity", {}),
        ]:
            if isinstance(container, dict):
                candidate = container.get("series_hook")
                if isinstance(candidate, dict):
                    series_hook_obj = candidate
                    break
        if not isinstance(series_hook_obj, dict):
            series_hook_obj = {}
        series_hook = series_hook_obj.get("technique", "UNKNOWN")

        # Narrative structure
        purposes = [s.get("narrative_purpose", "") for s in scenes if isinstance(s, dict)]
        narrative_structure = self._detect_narrative_structure(purposes)

        return {
            "project_id": data.get("_project_id", "unknown"),
            "created_at": file_mtime or datetime.now().isoformat(),
            "hook_type": hook.get("type", "UNKNOWN") if isinstance(hook, dict) else "UNKNOWN",
            "scene_1_entry_type": hook.get("scene_1_entry_type", "MACRO_ENTRY") if isinstance(hook, dict) else "MACRO_ENTRY",
            "body_trigger": hook.get("body_trigger", "UNKNOWN") if isinstance(hook, dict) else "UNKNOWN",
            "psychological_trigger": hook.get("psychological_trigger", "UNKNOWN") if isinstance(hook, dict) else "UNKNOWN",
            "scene_count": len(scenes),
            "texture_group": self._get_texture_group(food_id),
            "sp_scene_1": sp_scene_1,
            "sp_peak_scene": sp_peak_scene,
            "loop_technique": (loop.get("connection") or loop.get("technique") or "UNKNOWN") if isinstance(loop, dict) else "UNKNOWN",
            "controversy": controversy,
            "lighting_preset": lighting.get("preset", "UNKNOWN") if isinstance(lighting, dict) else "UNKNOWN",
            "warning_format": warning_format,
            "series_hook": series_hook,
            "category": concept.get("category", "UNKNOWN") if isinstance(concept, dict) else "UNKNOWN",
            "narrative_structure": narrative_structure,
        }

    # ========================================================================
    # QUERY METHODS (for autocorrect)
    # ========================================================================

    def get_recent(self, n: int = 5) -> List[Dict]:
        """Return last N fingerprints (newest first)."""
        return self.fingerprints[:n]

    def count_in_window(self, field: str, value: str, window: int) -> int:
        """Count occurrences of field=value in last `window` fingerprints."""
        count = 0
        for fp in self.fingerprints[:window]:
            if str(fp.get(field, "")).upper() == str(value).upper():
                count += 1
        return count

    def last_value(self, field: str) -> Optional[str]:
        """Return value of `field` from most recent fingerprint, or None."""
        if not self.fingerprints:
            return None
        return self.fingerprints[0].get(field)

    def consecutive_count(self, field: str, value: str) -> int:
        """Count consecutive occurrences of field=value from newest."""
        count = 0
        for fp in self.fingerprints:
            if str(fp.get(field, "")).upper() == str(value).upper():
                count += 1
            else:
                break
        return count

    # ========================================================================
    # PROMPT INJECTION
    # ========================================================================

    def generate_recent_textures(self) -> str:
        """
        For {{RECENT_TEXTURES}} placeholder in GEN1.txt.

        Returns:
            str: "CRISPY, CHEWY, CRISPY" or "" if no history.
        """
        if not self.fingerprints:
            return ""

        textures = []
        for fp in self.fingerprints[:5]:
            tg = fp.get("texture_group", "").upper()
            if tg:
                textures.append(tg)

        return ", ".join(textures) if textures else ""

    def generate_structural_context(self) -> str:
        """
        Generate markdown structural context for GEN1 user prompt.

        Returns:
            str: Markdown table + FREQUENCY ALERTS.
        """
        if not self.fingerprints:
            return "No structural history yet. Full creative freedom!"

        recent = self.fingerprints[:self.max_slots]

        lines = [
            f"## STRUCTURAL DIVERSITY — Last {len(recent)} Videos",
            "",
            "| # | Hook | Entry | Body | Loop | Texture | Controversy | SP1 | SPpeak | Warn | Structure |",
            "|---|------|-------|------|------|---------|-------------|-----|--------|------|-----------|",
        ]

        for i, fp in enumerate(recent, 1):
            lines.append(
                f"| {i} "
                f"| {fp.get('hook_type', '?')} "
                f"| {fp.get('scene_1_entry_type', '?')} "
                f"| {fp.get('body_trigger', '?')} "
                f"| {fp.get('loop_technique', '?')} "
                f"| {fp.get('texture_group', '?')} "
                f"| {fp.get('controversy', '?')} "
                f"| {fp.get('sp_scene_1', '?')} "
                f"| S{fp.get('sp_peak_scene', '?')} "
                f"| {fp.get('warning_format', '?')} "
                f"| {fp.get('narrative_structure', '?')} |"
            )

        # Frequency alerts
        alerts = self._generate_frequency_alerts(recent)
        if alerts:
            lines.append("")
            lines.append("### FREQUENCY ALERTS (auto-detected patterns):")
            for alert in alerts:
                lines.append(f"- {alert}")

        lines.append("")
        lines.append("IMPORTANT: Maximize structural diversity. Avoid repeating the same hook/entry/body/loop patterns.")

        return "\n".join(lines)

    def _generate_frequency_alerts(self, recent: List[Dict]) -> List[str]:
        """Generate frequency alert strings for common patterns."""
        alerts = []

        if len(recent) < 2:
            return alerts

        # Check consecutive same values
        _TRACKED_FIELDS = [
            ("hook_type", "Hook type"),
            ("scene_1_entry_type", "Entry type"),
            ("body_trigger", "Body trigger"),
            ("loop_technique", "Loop technique"),
            ("texture_group", "Texture group"),
            ("lighting_preset", "Lighting preset"),
            ("warning_format", "Warning format"),
        ]

        for field, label in _TRACKED_FIELDS:
            last = recent[0].get(field)
            if last and len(recent) >= 2 and recent[1].get(field) == last:
                streak = self.consecutive_count(field, last)
                if streak >= 2:
                    alerts.append(f"{label} '{last}' used {streak}x in a row — CHANGE IT")

        # Specific HARD LIMIT alerts (warn when at limit — next use would exceed)
        window_4 = recent[:4]
        if len(window_4) >= 4:
            for hook_val in ["THE_IMPOSSIBLE", "THE_SENSORY_ATTACK"]:
                cnt = sum(1 for fp in window_4 if fp.get("hook_type") == hook_val)
                if cnt >= 1:
                    alerts.append(f"Hook '{hook_val}' already at limit ({cnt} in last 4) — DO NOT USE AGAIN")

            fog_cnt = sum(1 for fp in window_4 if fp.get("loop_technique") == "FOG_GATE")
            if fog_cnt >= 1:
                alerts.append(f"Loop 'FOG_GATE' already at limit ({fog_cnt} in last 4) — DO NOT USE AGAIN")

        return alerts

    # ========================================================================
    # HELPERS
    # ========================================================================

    @staticmethod
    def _get_texture_group(food_identity: dict) -> str:
        """Classify food texture into group (CRISPY/SMOOTH/CHEWY)."""
        if not isinstance(food_identity, dict):
            return "CRISPY"

        tex_kws = food_identity.get("texture_keywords", [])
        if not isinstance(tex_kws, list):
            return "CRISPY"

        for kw in tex_kws:
            if isinstance(kw, str):
                group = _TEXTURE_GROUPS.get(kw.lower().strip())
                if group:
                    return group

        return "CRISPY"  # safe default

    @staticmethod
    def _detect_warning_format(warning_line: str) -> str:
        """Detect warning line format (A-F) via regex patterns."""
        if not warning_line or not isinstance(warning_line, str):
            return "X"

        for fmt, pattern in _WARNING_FORMATS:
            if pattern.search(warning_line):
                return fmt

        return "X"  # unknown format

    @staticmethod
    def _detect_narrative_structure(purposes: List[str]) -> str:
        """
        Classify narrative arc from sequence of narrative_purposes.

        Maps purpose sequence hash to structure label A-E.
        """
        if not purposes:
            return "A"

        # Simple hash of the sequence
        key = "|".join(p.upper() for p in purposes if p)
        h = sum(ord(c) for c in key)
        return _NARRATIVE_STRUCTURES[h % len(_NARRATIVE_STRUCTURES)]

    # ========================================================================
    # BACKFILL
    # ========================================================================

    def backfill_from_projects(self, projects_dir: Path) -> int:
        """
        One-time scan of existing project_brief.json files.

        Args:
            projects_dir: Path to projects/ directory.

        Returns:
            int: Number of fingerprints backfilled.
        """
        if not projects_dir.exists():
            logger.warning(f"Projects directory not found: {projects_dir}")
            return 0

        briefs = sorted(projects_dir.glob("*/project_brief.json"), key=lambda p: p.stat().st_mtime)
        count = 0

        for brief_path in briefs:
            try:
                with open(brief_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # Skip if already tracked
                project_id = brief_path.parent.name
                if any(fp.get("project_id") == project_id for fp in self.fingerprints):
                    continue

                # Use file modification time for correct chronological ordering
                file_mtime = datetime.fromtimestamp(brief_path.stat().st_mtime).isoformat()

                data["_project_id"] = project_id
                fp = self._extract_fingerprint(data, file_mtime=file_mtime)
                self.fingerprints.append(fp)
                count += 1
                logger.debug(f"Backfilled: {project_id}")

            except Exception as e:
                logger.debug(f"Skipped {brief_path.name}: {e}")

        if count > 0:
            # Sort by created_at (newest first), trim
            self.fingerprints.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            while len(self.fingerprints) > self.max_slots:
                self.fingerprints.pop()
            self._save()
            logger.info(f"StructuralMemory: Backfilled {count} fingerprints from {projects_dir}")

        return count

    # ========================================================================
    # UTILITY
    # ========================================================================

    def clear(self) -> None:
        """Clear all fingerprints (for testing)."""
        self.fingerprints = []
        self._save()
        logger.info("StructuralMemory cleared")

    def get_stats(self) -> Dict:
        """Return stats for UI."""
        return {
            "total_fingerprints": len(self.fingerprints),
            "max_slots": self.max_slots,
            "newest": self.fingerprints[0].get("project_id") if self.fingerprints else None,
            "oldest": self.fingerprints[-1].get("project_id") if self.fingerprints else None,
        }

    def __len__(self) -> int:
        return len(self.fingerprints)

    def __repr__(self) -> str:
        return f"StructuralMemory(fingerprints={len(self.fingerprints)}/{self.max_slots})"


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

structural_memory = StructuralMemory()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["StructuralMemory", "structural_memory"]
