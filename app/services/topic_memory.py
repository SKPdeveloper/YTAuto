"""
Topic Memory Module for Glaze City Automation

Tracks last N video topics to prevent repetition.
FIFO queue - newest topics push out oldest.

Usage:
    from app.services.topic_memory import topic_memory

    # Get blacklist for GEN1
    blacklist = topic_memory.generate_blacklist_markdown()

    # After successful generation
    topic_memory.add_topic(gen1_output)
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Dict, List

from app.core.config import settings
from app.utils.logger import logger


class TopicMemory:
    """
    FIFO queue (First In, First Out) для останніх N тем.
    Зберігає окремо blocked_subjects і blocked_foods.

    Attributes:
        max_slots: Maximum number of topics to remember (from settings)
        storage_path: Path to JSON storage file
        topics: List of topic dictionaries
    """

    DEFAULT_STORAGE_PATH = Path("data/topic_memory.json")

    def __init__(self, storage_path: Optional[Path] = None):
        """
        Ініціалізація з опціональним кастомним шляхом для тестування.

        Args:
            storage_path: Custom path for storage (default: data/topic_memory.json)
        """
        self.storage_path = storage_path or self.DEFAULT_STORAGE_PATH
        self.topics: List[Dict] = []
        self._load()

        logger.debug(f"TopicMemory initialized: {len(self.topics)}/{self.max_slots} topics")

    @property
    def max_slots(self) -> int:
        """Get max slots from settings (configurable via UI)."""
        return getattr(settings, 'TOPIC_MEMORY_LIMIT', 20)

    def _load(self) -> None:
        """Завантажує topics з JSON файлу."""
        try:
            if self.storage_path.exists():
                with open(self.storage_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.topics = data.get("topics", [])
                    logger.debug(f"Loaded {len(self.topics)} topics from {self.storage_path}")
            else:
                self.topics = []
                logger.debug(f"No existing topic memory at {self.storage_path}")
        except Exception as e:
            logger.error(f"Failed to load topic memory: {e}")
            self.topics = []

    def _save(self) -> None:
        """Зберігає topics в JSON файл."""
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump({
                    "version": "1.0",
                    "max_slots": self.max_slots,
                    "current_count": len(self.topics),
                    "updated_at": datetime.now().isoformat(),
                    "topics": self.topics
                }, f, indent=2, ensure_ascii=False)
            logger.debug(f"Saved {len(self.topics)} topics to {self.storage_path}")
        except Exception as e:
            logger.error(f"Failed to save topic memory: {e}")

    def add_topic(self, gen1_output: Dict) -> None:
        """
        Додає нову тему з GEN1 output.
        FIFO: нова тема на початок, найстаріша видаляється якщо > max_slots.

        Args:
            gen1_output: Повний JSON output від GEN1
        """
        try:
            # Extract data from GEN1 output
            metadata = gen1_output.get("metadata", {})
            concept = metadata.get("concept", {})
            food_identity = gen1_output.get("food_identity", {})

            topic = {
                "title": metadata.get("title", "Unknown"),
                "category": concept.get("category", "UNKNOWN"),
                "primary_food": food_identity.get("primary_food", "unknown").lower().strip(),
                "subject": concept.get("subject", "unknown").lower().strip(),
                "created_at": datetime.now().isoformat()
            }

            # FIFO: додаємо на початок
            self.topics.insert(0, topic)

            # Видаляємо найстарішу якщо перевищили ліміт
            while len(self.topics) > self.max_slots:
                removed = self.topics.pop()
                logger.debug(f"Removed old topic: {removed['title']}")

            self._save()

            logger.info(f"TopicMemory: Added '{topic['title']}' ({len(self.topics)}/{self.max_slots})")

        except Exception as e:
            logger.error(f"Failed to add topic to memory: {e}")

    def get_blocked_subjects(self) -> List[str]:
        """
        Повертає список унікальних subjects з останніх N відео.

        Returns:
            list: ["dam", "library", "submarine", ...]
        """
        return list(set(t["subject"] for t in self.topics if t.get("subject")))

    def get_blocked_foods(self) -> List[str]:
        """
        Повертає список унікальних foods з останніх N відео.

        Returns:
            list: ["peanut butter", "lasagna", "jelly", ...]
        """
        return list(set(t["primary_food"] for t in self.topics if t.get("primary_food")))

    def get_category_counts(self) -> Dict[str, int]:
        """
        Повертає кількість відео по категоріях.

        Returns:
            dict: {"INFRASTRUCTURE": 5, "LANDMARKS": 3, ...}
        """
        counts: Dict[str, int] = {}
        for t in self.topics:
            cat = t.get("category", "UNKNOWN")
            counts[cat] = counts.get(cat, 0) + 1
        return dict(sorted(counts.items(), key=lambda x: -x[1]))

    def _extract_keywords(self, subjects: List[str]) -> List[str]:
        """
        Витягує ключові слова з subjects для більш агресивного блокування.

        "hydro-electric dam" → ["dam", "hydro", "hydroelectric", "hydro-electric"]
        """
        keywords = set()

        # Стоп-слова які не блокуємо
        stop_words = {'the', 'a', 'an', 'of', 'in', 'on', 'at', 'to', 'for', 'with', 'and', 'or'}

        for subject in subjects:
            # Додаємо повний subject
            keywords.add(subject.lower())

            # Розбиваємо на слова
            words = subject.lower().replace('-', ' ').replace('_', ' ').split()
            for word in words:
                if word not in stop_words and len(word) > 2:
                    keywords.add(word)

            # Також додаємо з дефісами як є
            if '-' in subject:
                keywords.add(subject.lower())

        return sorted(keywords)

    def generate_blacklist_markdown(self) -> str:
        """
        Генерує markdown для injection в GEN1 prompt.

        Returns:
            str: Форматований markdown з blocked subjects, foods, і таблицею
        """
        if not self.topics:
            return "No recent topics. Full creative freedom!"

        blocked_subjects = self.get_blocked_subjects()
        blocked_foods = self.get_blocked_foods()
        category_counts = self.get_category_counts()

        # Витягуємо ключові слова для більш агресивного блокування
        blocked_keywords = self._extract_keywords(blocked_subjects)

        # Format lists
        subjects_str = ", ".join(sorted(blocked_subjects)) if blocked_subjects else "None"
        keywords_str = ", ".join(blocked_keywords) if blocked_keywords else "None"
        foods_str = ", ".join(sorted(blocked_foods)) if blocked_foods else "None"

        # Category warnings (overused = 3+ times)
        overused_categories = [cat for cat, count in category_counts.items() if count >= 3]
        category_warning = ""
        if overused_categories:
            category_warning = f"\n\n### ⚠️ OVERUSED CATEGORIES (avoid if possible):\n{', '.join(overused_categories)}"

        lines = [
            f"## 🚫 ABSOLUTE BLACKLIST — Last {len(self.topics)} Videos",
            "",
            "### 🚫🚫🚫 BANNED KEYWORDS — NEVER USE THESE WORDS IN ANY FORM:",
            keywords_str,
            "",
            "### 🚫 BLOCKED SUBJECTS (full phrases):",
            subjects_str,
            "",
            "### 🚫 BLOCKED FOODS — DO NOT USE:",
            foods_str,
            category_warning,
            "",
            "⛔ ANY concept containing the banned keywords above will be IMMEDIATELY REJECTED.",
            "⛔ This includes synonyms, variations, and related concepts.",
            "⛔ Choose a COMPLETELY DIFFERENT type of structure/building/infrastructure.",
            "",
            "### 📋 Recent Videos (for reference):",
            "| # | Title | Food | Subject | Category |",
            "|---|-------|------|---------|----------|",
        ]

        for i, t in enumerate(self.topics, 1):
            title = t.get('title', 'N/A')[:30]
            food = t.get('primary_food', 'N/A')
            subject = t.get('subject', 'N/A')
            category = t.get('category', 'N/A')
            lines.append(f"| {i} | {title} | {food} | {subject} | {category} |")

        return "\n".join(lines)

    def is_blocked(self, food: str, subject: str) -> Tuple[bool, str]:
        """
        Перевіряє чи комбінація заблокована.

        Args:
            food: Назва їжі (наприклад "peanut butter")
            subject: Назва об'єкта (наприклад "dam")

        Returns:
            tuple: (is_blocked: bool, reason: str)
        """
        food_lower = food.lower().strip()
        subject_lower = subject.lower().strip()

        blocked_subjects = [t["subject"] for t in self.topics]
        blocked_foods = [t["primary_food"] for t in self.topics]

        if subject_lower in blocked_subjects:
            return True, f"Subject '{subject}' was used recently"

        if food_lower in blocked_foods:
            return True, f"Food '{food}' was used recently"

        return False, "OK"

    def clear(self) -> None:
        """Очищає всю пам'ять (для тестування)."""
        self.topics = []
        self._save()
        logger.info("TopicMemory cleared")

    def get_stats(self) -> Dict:
        """
        Повертає статистику для UI.

        Returns:
            dict: Statistics about topic memory
        """
        return {
            "total_topics": len(self.topics),
            "max_slots": self.max_slots,
            "blocked_subjects_count": len(self.get_blocked_subjects()),
            "blocked_foods_count": len(self.get_blocked_foods()),
            "category_distribution": self.get_category_counts(),
            "oldest_topic": self.topics[-1]["title"] if self.topics else None,
            "newest_topic": self.topics[0]["title"] if self.topics else None,
        }

    def __len__(self) -> int:
        return len(self.topics)

    def __repr__(self) -> str:
        return f"TopicMemory(topics={len(self.topics)}/{self.max_slots})"


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

# Global instance for use across the application
topic_memory = TopicMemory()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["TopicMemory", "topic_memory"]
