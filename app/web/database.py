"""
Database module for Web UI.
SQLite database for channels, projects, scenes, logs, and stats.
"""

import aiosqlite
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
import json

from app.core.config import settings
from app.utils.logger import logger


# Database path
DB_PATH = settings.DATA_DIR / "web_ui.db"


async def get_db_connection() -> aiosqlite.Connection:
    """Get async database connection."""
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db


async def init_database() -> None:
    """Initialize database with schema."""
    logger.info(f"Initializing Web UI database at {DB_PATH}")

    async with aiosqlite.connect(DB_PATH) as db:
        # Channels table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                folder_path TEXT NOT NULL,
                default_format TEXT DEFAULT '9:16',
                default_engine TEXT DEFAULT 'higgsfield',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Projects table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS web_projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                orchestrator_project_id TEXT,
                name TEXT NOT NULL,
                topic TEXT,
                format TEXT NOT NULL,
                duration_seconds INTEGER NOT NULL,
                engine TEXT NOT NULL,
                selected_script TEXT,
                status TEXT DEFAULT 'generating',
                progress INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (channel_id) REFERENCES channels(id)
            )
        """)

        # Scenes table (for UI display, synced with orchestrator)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS web_scenes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                scene_number INTEGER NOT NULL,
                prompt TEXT,
                status TEXT DEFAULT 'pending',
                image_path TEXT,
                video_path TEXT,
                upscaled_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES web_projects(id)
            )
        """)

        # Logs table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS web_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                message TEXT NOT NULL,
                level TEXT DEFAULT 'info',
                FOREIGN KEY (project_id) REFERENCES web_projects(id)
            )
        """)

        # Stats table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS web_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                project_id INTEGER NOT NULL,
                generation_time_seconds INTEGER,
                api_cost REAL DEFAULT 0,
                manual_interventions INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (channel_id) REFERENCES channels(id),
                FOREIGN KEY (project_id) REFERENCES web_projects(id)
            )
        """)

        await db.commit()
        logger.info("Web UI database initialized successfully")


# =============================================================================
# Channel Operations
# =============================================================================

async def create_channel(
    name: str,
    folder_path: str,
    default_format: str = "9:16",
    default_engine: str = "higgsfield"
) -> int:
    """Create a new channel and return its ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO channels (name, folder_path, default_format, default_engine)
            VALUES (?, ?, ?, ?)
            """,
            (name, folder_path, default_format, default_engine)
        )
        await db.commit()
        return cursor.lastrowid


async def get_channel(channel_id: int) -> Optional[Dict[str, Any]]:
    """Get channel by ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM channels WHERE id = ?",
            (channel_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_all_channels() -> List[Dict[str, Any]]:
    """Get all channels with stats."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT
                c.*,
                COUNT(p.id) as total_projects,
                SUM(CASE WHEN p.status = 'generating' OR p.status = 'reviewing' THEN 1 ELSE 0 END) as active_projects,
                SUM(CASE WHEN p.status = 'ready' THEN 1 ELSE 0 END) as ready_projects
            FROM channels c
            LEFT JOIN web_projects p ON c.id = p.channel_id
            GROUP BY c.id
            ORDER BY c.created_at DESC
        """)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def delete_channel(channel_id: int) -> bool:
    """Delete a channel."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
        await db.commit()
        return True


# =============================================================================
# Project Operations
# =============================================================================

async def create_project(
    channel_id: int,
    name: str,
    topic: str,
    format: str,
    duration_seconds: int,
    engine: str,
    selected_script: str = None,
    orchestrator_project_id: str = None
) -> int:
    """Create a new project and return its ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO web_projects
            (channel_id, orchestrator_project_id, name, topic, format, duration_seconds, engine, selected_script, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'generating')
            """,
            (channel_id, orchestrator_project_id, name, topic, format, duration_seconds, engine, selected_script)
        )
        await db.commit()
        return cursor.lastrowid


async def get_project(project_id: int) -> Optional[Dict[str, Any]]:
    """Get project by ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM web_projects WHERE id = ?",
            (project_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_channel_projects(
    channel_id: int,
    sort: str = "date_desc",
    status_filter: str = None
) -> List[Dict[str, Any]]:
    """Get all projects for a channel."""
    order_by = "created_at DESC" if sort == "date_desc" else "created_at ASC"

    query = "SELECT * FROM web_projects WHERE channel_id = ?"
    params = [channel_id]

    if status_filter:
        query += " AND status = ?"
        params.append(status_filter)

    query += f" ORDER BY {order_by}"

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def update_project_status(
    project_id: int,
    status: str,
    progress: int = None
) -> None:
    """Update project status and progress."""
    async with aiosqlite.connect(DB_PATH) as db:
        if progress is not None:
            await db.execute(
                "UPDATE web_projects SET status = ?, progress = ? WHERE id = ?",
                (status, progress, project_id)
            )
        else:
            await db.execute(
                "UPDATE web_projects SET status = ? WHERE id = ?",
                (status, project_id)
            )

        if status == 'ready':
            await db.execute(
                "UPDATE web_projects SET completed_at = ? WHERE id = ?",
                (datetime.now().isoformat(), project_id)
            )

        await db.commit()


# =============================================================================
# Scene Operations
# =============================================================================

async def create_scene(
    project_id: int,
    scene_number: int,
    prompt: str = None
) -> int:
    """Create a new scene."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO web_scenes (project_id, scene_number, prompt)
            VALUES (?, ?, ?)
            """,
            (project_id, scene_number, prompt)
        )
        await db.commit()
        return cursor.lastrowid


async def get_project_scenes(project_id: int) -> List[Dict[str, Any]]:
    """Get all scenes for a project."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM web_scenes WHERE project_id = ? ORDER BY scene_number",
            (project_id,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def update_scene_status(
    scene_id: int,
    status: str,
    image_path: str = None,
    video_path: str = None,
    upscaled_path: str = None
) -> None:
    """Update scene status and paths."""
    async with aiosqlite.connect(DB_PATH) as db:
        updates = ["status = ?"]
        params = [status]

        if image_path:
            updates.append("image_path = ?")
            params.append(image_path)
        if video_path:
            updates.append("video_path = ?")
            params.append(video_path)
        if upscaled_path:
            updates.append("upscaled_path = ?")
            params.append(upscaled_path)

        params.append(scene_id)

        await db.execute(
            f"UPDATE web_scenes SET {', '.join(updates)} WHERE id = ?",
            params
        )
        await db.commit()


# =============================================================================
# Log Operations
# =============================================================================

async def add_log(
    project_id: int,
    message: str,
    level: str = "info"
) -> int:
    """Add a log entry."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO web_logs (project_id, message, level)
            VALUES (?, ?, ?)
            """,
            (project_id, message, level)
        )
        await db.commit()
        return cursor.lastrowid


async def get_project_logs(
    project_id: int,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """Get logs for a project."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM web_logs
            WHERE project_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (project_id, limit)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


# =============================================================================
# Stats Operations
# =============================================================================

async def get_channel_stats(channel_id: int) -> Dict[str, Any]:
    """Get statistics for a channel."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Total projects
        cursor = await db.execute(
            "SELECT COUNT(*) as count FROM web_projects WHERE channel_id = ?",
            (channel_id,)
        )
        total = (await cursor.fetchone())['count']

        # Active projects
        cursor = await db.execute(
            """
            SELECT COUNT(*) as count FROM web_projects
            WHERE channel_id = ? AND status IN ('generating', 'reviewing', 'upscaling')
            """,
            (channel_id,)
        )
        active = (await cursor.fetchone())['count']

        # Ready projects
        cursor = await db.execute(
            "SELECT COUNT(*) as count FROM web_projects WHERE channel_id = ? AND status = 'ready'",
            (channel_id,)
        )
        ready = (await cursor.fetchone())['count']

        # Weekly projects (last 7 days)
        cursor = await db.execute(
            """
            SELECT COUNT(*) as count FROM web_projects
            WHERE channel_id = ? AND created_at >= datetime('now', '-7 days')
            """,
            (channel_id,)
        )
        weekly = (await cursor.fetchone())['count']

        # Success rate
        cursor = await db.execute(
            """
            SELECT
                COUNT(CASE WHEN status = 'ready' THEN 1 END) * 100.0 /
                NULLIF(COUNT(CASE WHEN status IN ('ready', 'failed') THEN 1 END), 0) as rate
            FROM web_projects WHERE channel_id = ?
            """,
            (channel_id,)
        )
        row = await cursor.fetchone()
        success_rate = row['rate'] if row['rate'] else 100

        # Average generation time
        cursor = await db.execute(
            """
            SELECT AVG(generation_time_seconds) / 60.0 as avg_time
            FROM web_stats WHERE channel_id = ?
            """,
            (channel_id,)
        )
        row = await cursor.fetchone()
        avg_time = row['avg_time'] if row['avg_time'] else 0

        # Total API cost
        cursor = await db.execute(
            "SELECT SUM(api_cost) as total FROM web_stats WHERE channel_id = ?",
            (channel_id,)
        )
        row = await cursor.fetchone()
        api_cost = row['total'] if row['total'] else 0

        return {
            "total_projects": total,
            "active_projects": active,
            "ready_projects": ready,
            "weekly_projects": weekly,
            "success_rate": round(success_rate, 1),
            "avg_time_minutes": round(avg_time, 1),
            "api_cost": round(api_cost, 2)
        }
