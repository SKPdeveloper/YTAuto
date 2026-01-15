"""
State Manager для Edible House Automator
Async SQLite для збереження стану проєктів між рестартами
"""

import aiosqlite
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from app.core.config import settings
from app.utils.logger import logger


# ============================================================================
# DATABASE SCHEMA
# ============================================================================

DB_SCHEMA = """
-- Projects table
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    num_scenes INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata TEXT  -- JSON для додаткових даних
);

-- Scenes table
CREATE TABLE IF NOT EXISTS scenes (
    project_id TEXT NOT NULL,
    scene_number INTEGER NOT NULL,
    prompt TEXT NOT NULL,
    script_description TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    retry_count INTEGER DEFAULT 0,
    selected_image_idx INTEGER,
    model TEXT DEFAULT 'kling',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata TEXT,  -- JSON для додаткових даних
    PRIMARY KEY (project_id, scene_number),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

-- Scene images table
CREATE TABLE IF NOT EXISTS scene_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    scene_number INTEGER NOT NULL,
    image_index INTEGER NOT NULL,
    image_url TEXT,
    local_path TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id, scene_number) REFERENCES scenes(project_id, scene_number) ON DELETE CASCADE
);

-- Scene videos table
CREATE TABLE IF NOT EXISTS scene_videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    scene_number INTEGER NOT NULL,
    video_type TEXT NOT NULL,  -- raw | upscaled
    video_url TEXT,
    local_path TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id, scene_number) REFERENCES scenes(project_id, scene_number) ON DELETE CASCADE
);

-- API requests log (для debugging)
CREATE TABLE IF NOT EXISTS api_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service TEXT NOT NULL,  -- higgsfield | gemini | claude
    request_id TEXT,
    project_id TEXT,
    scene_number INTEGER,
    status TEXT NOT NULL,  -- pending | success | failed
    request_data TEXT,  -- JSON
    response_data TEXT,  -- JSON
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Generic key-value storage для довільних даних (ProjectData, etc.)
CREATE TABLE IF NOT EXISTS state_storage (
    key TEXT PRIMARY KEY,
    data TEXT NOT NULL,  -- JSON
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Indexes для швидкого пошуку
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);
CREATE INDEX IF NOT EXISTS idx_scenes_status ON scenes(project_id, status);
CREATE INDEX IF NOT EXISTS idx_api_requests_status ON api_requests(service, status);
"""


# ============================================================================
# STATE MANAGER CLASS
# ============================================================================

class StateManager:
    """
    Менеджер стану проєктів з async SQLite
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        Args:
            db_path: Шлях до SQLite файлу (за замовчуванням data/state.db)
        """
        self.db_path = db_path or (settings.DATA_DIR / "state.db")
        self._initialized = False

    async def initialize(self) -> None:
        """Створює таблиці якщо їх немає"""
        if self._initialized:
            return

        logger.info(f"Initializing database: {self.db_path}")

        # Створюємо директорію якщо не існує
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(DB_SCHEMA)
            await db.commit()

        self._initialized = True
        logger.success("Database initialized successfully")

    # ========================================================================
    # PROJECTS CRUD
    # ========================================================================

    async def create_project(
        self,
        project_id: str,
        topic: str,
        num_scenes: int,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Створює новий проєкт"""
        now = datetime.utcnow().isoformat()

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO projects (id, topic, num_scenes, status, created_at, updated_at, metadata)
                VALUES (?, ?, ?, 'pending', ?, ?, ?)
                """,
                (
                    project_id,
                    topic,
                    num_scenes,
                    now,
                    now,
                    json.dumps(metadata) if metadata else None
                )
            )
            await db.commit()

        logger.info(f"Project created: {project_id} - {topic}")

    async def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Отримує проєкт за ID"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM projects WHERE id = ?",
                (project_id,)
            ) as cursor:
                row = await cursor.fetchone()

                if row:
                    project = dict(row)
                    if project.get("metadata"):
                        project["metadata"] = json.loads(project["metadata"])
                    return project

        return None

    async def update_project_status(
        self,
        project_id: str,
        status: str
    ) -> None:
        """Оновлює статус проєкту"""
        now = datetime.utcnow().isoformat()

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE projects SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, project_id)
            )
            await db.commit()

        logger.debug(f"Project {project_id} status updated: {status}")

    async def get_all_projects(self) -> List[Dict[str, Any]]:
        """Повертає всі проєкти"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM projects ORDER BY created_at DESC"
            ) as cursor:
                rows = await cursor.fetchall()
                projects = []

                for row in rows:
                    project = dict(row)
                    if project.get("metadata"):
                        project["metadata"] = json.loads(project["metadata"])
                    projects.append(project)

                return projects

    # ========================================================================
    # SCENES CRUD
    # ========================================================================

    async def create_scene(
        self,
        project_id: str,
        scene_number: int,
        prompt: str,
        script_description: str,
        model: str = "kling",
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Створює нову сцену"""
        now = datetime.utcnow().isoformat()

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO scenes
                (project_id, scene_number, prompt, script_description, status, model, created_at, updated_at, metadata)
                VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)
                """,
                (
                    project_id,
                    scene_number,
                    prompt,
                    script_description,
                    model,
                    now,
                    now,
                    json.dumps(metadata) if metadata else None
                )
            )
            await db.commit()

        logger.debug(f"Scene created: {project_id} scene #{scene_number}")

    async def get_scene(
        self,
        project_id: str,
        scene_number: int
    ) -> Optional[Dict[str, Any]]:
        """Отримує сцену"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM scenes WHERE project_id = ? AND scene_number = ?",
                (project_id, scene_number)
            ) as cursor:
                row = await cursor.fetchone()

                if row:
                    scene = dict(row)
                    if scene.get("metadata"):
                        scene["metadata"] = json.loads(scene["metadata"])
                    return scene

        return None

    async def update_scene(
        self,
        project_id: str,
        scene_number: int,
        **kwargs
    ) -> None:
        """
        Оновлює поля сцени

        Args:
            project_id: ID проєкту
            scene_number: Номер сцени
            **kwargs: Поля для оновлення (status, retry_count, selected_image_idx, etc.)
        """
        now = datetime.utcnow().isoformat()
        kwargs["updated_at"] = now

        # Формуємо SET clause
        set_clause = ", ".join(f"{key} = ?" for key in kwargs.keys())
        values = list(kwargs.values()) + [project_id, scene_number]

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                f"UPDATE scenes SET {set_clause} WHERE project_id = ? AND scene_number = ?",
                values
            )
            await db.commit()

        logger.debug(f"Scene {project_id} #{scene_number} updated")

    async def get_project_scenes(
        self,
        project_id: str
    ) -> List[Dict[str, Any]]:
        """Повертає всі сцени проєкту"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM scenes WHERE project_id = ? ORDER BY scene_number",
                (project_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                scenes = []

                for row in rows:
                    scene = dict(row)
                    if scene.get("metadata"):
                        scene["metadata"] = json.loads(scene["metadata"])
                    scenes.append(scene)

                return scenes

    # ========================================================================
    # IMAGES & VIDEOS
    # ========================================================================

    async def add_scene_image(
        self,
        project_id: str,
        scene_number: int,
        image_index: int,
        image_url: str,
        local_path: Optional[str] = None
    ) -> None:
        """Додає зображення до сцени"""
        now = datetime.utcnow().isoformat()

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO scene_images
                (project_id, scene_number, image_index, image_url, local_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (project_id, scene_number, image_index, image_url, local_path, now)
            )
            await db.commit()

    async def add_scene_video(
        self,
        project_id: str,
        scene_number: int,
        video_type: str,
        video_url: Optional[str] = None,
        local_path: Optional[str] = None
    ) -> None:
        """Додає відео до сцени"""
        now = datetime.utcnow().isoformat()

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO scene_videos
                (project_id, scene_number, video_type, video_url, local_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (project_id, scene_number, video_type, video_url, local_path, now)
            )
            await db.commit()

    # ========================================================================
    # API REQUESTS LOG
    # ========================================================================

    async def log_api_request(
        self,
        service: str,
        request_id: Optional[str] = None,
        project_id: Optional[str] = None,
        scene_number: Optional[int] = None,
        status: str = "pending",
        request_data: Optional[Dict] = None,
        response_data: Optional[Dict] = None,
        error_message: Optional[str] = None
    ) -> int:
        """Логує API запит"""
        now = datetime.utcnow().isoformat()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO api_requests
                (service, request_id, project_id, scene_number, status,
                 request_data, response_data, error_message, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    service,
                    request_id,
                    project_id,
                    scene_number,
                    status,
                    json.dumps(request_data) if request_data else None,
                    json.dumps(response_data) if response_data else None,
                    error_message,
                    now,
                    now
                )
            )
            await db.commit()
            return cursor.lastrowid

    # ========================================================================
    # GENERIC STATE STORAGE (для Orchestrator ProjectData)
    # ========================================================================

    async def save_state(self, key: str, data: Dict[str, Any]) -> None:
        """
        Зберігає довільні дані як JSON

        Args:
            key: Унікальний ключ (наприклад, "project:proj_abc123")
            data: Словник з даними для збереження
        """
        now = datetime.utcnow().isoformat()

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO state_storage (key, data, created_at, updated_at)
                VALUES (?, ?, COALESCE((SELECT created_at FROM state_storage WHERE key = ?), ?), ?)
                """,
                (key, json.dumps(data), key, now, now)
            )
            await db.commit()

        logger.debug(f"State saved: {key}")

    async def get_state(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Отримує збережені дані за ключем

        Args:
            key: Унікальний ключ

        Returns:
            Словник з даними або None якщо не знайдено
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT data FROM state_storage WHERE key = ?",
                (key,)
            ) as cursor:
                row = await cursor.fetchone()

                if row:
                    return json.loads(row["data"])

        return None


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

state_manager = StateManager()


# ============================================================================
# EXPORT
# ============================================================================

__all__ = ["StateManager", "state_manager"]
