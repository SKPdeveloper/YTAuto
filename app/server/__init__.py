"""
WebSocket Server Module

Provides real-time communication between the pipeline and web clients.
Replaces Telegram notifications with push notifications via WebSocket.

Usage:
    from app.server import ConnectionManager, Events

    manager = ConnectionManager()
    await manager.broadcast(Events.SCENE_UPDATED, {"scene": 1, "status": "ready"})
"""

from app.server.websocket import ConnectionManager, get_connection_manager
from app.server.events import Events, EventData
from app.server.notifications import NotificationService

__all__ = [
    "ConnectionManager",
    "get_connection_manager",
    "Events",
    "EventData",
    "NotificationService",
]
