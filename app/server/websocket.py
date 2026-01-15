"""
WebSocket Connection Manager

Manages WebSocket connections and broadcasts messages to all connected clients.
"""

import json
import asyncio
from typing import Set, Optional, Any, Dict
from datetime import datetime
from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

from config.timeouts import USER


class ConnectionManager:
    """
    Manages WebSocket connections for real-time updates.

    Features:
    - Multiple client support
    - Automatic reconnection handling
    - JSON message serialization
    - Ping/pong heartbeat

    Usage:
        manager = ConnectionManager()

        @app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await manager.connect(websocket)
            try:
                while True:
                    data = await websocket.receive_text()
                    # Handle incoming messages
            except WebSocketDisconnect:
                manager.disconnect(websocket)

        # From anywhere in the app:
        await manager.broadcast("scene_updated", {"scene": 1, "status": "ready"})
    """

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self.subscriptions: Dict[str, Set[WebSocket]] = {}  # project_id -> set of websockets
        self._lock = asyncio.Lock()
        self._ping_task: Optional[asyncio.Task] = None
        self._running = False

    @property
    def connection_count(self) -> int:
        """Number of active connections"""
        return len(self.active_connections)

    async def connect(self, websocket: WebSocket) -> None:
        """
        Accept and register a new WebSocket connection.

        Args:
            websocket: The WebSocket connection to register
        """
        await websocket.accept()
        async with self._lock:
            self.active_connections.add(websocket)

        logger.info(f"WebSocket connected. Total connections: {self.connection_count}")

        # Send welcome message
        await self._send_to_client(websocket, "connected", {
            "message": "Connected to Edible House Automator",
            "timestamp": datetime.now().isoformat(),
            "client_id": id(websocket),
        })

        # Start ping task if not running
        if not self._running:
            self._running = True
            self._ping_task = asyncio.create_task(self._ping_loop())

    def disconnect(self, websocket: WebSocket) -> None:
        """
        Remove a WebSocket connection.

        Args:
            websocket: The WebSocket connection to remove
        """
        self.active_connections.discard(websocket)

        # Remove from all subscriptions
        for project_id, subscribers in list(self.subscriptions.items()):
            subscribers.discard(websocket)
            if not subscribers:
                del self.subscriptions[project_id]

        logger.info(f"WebSocket disconnected. Total connections: {self.connection_count}")

        # Stop ping task if no connections
        if self.connection_count == 0 and self._ping_task:
            self._running = False
            self._ping_task.cancel()
            self._ping_task = None

    def subscribe(self, websocket: WebSocket, project_id: str) -> None:
        """
        Subscribe a WebSocket to project updates.

        Args:
            websocket: The WebSocket connection
            project_id: Project ID to subscribe to
        """
        if project_id not in self.subscriptions:
            self.subscriptions[project_id] = set()
        self.subscriptions[project_id].add(websocket)
        logger.debug(f"WebSocket subscribed to project {project_id}")

    def unsubscribe(self, websocket: WebSocket, project_id: str) -> None:
        """
        Unsubscribe a WebSocket from project updates.

        Args:
            websocket: The WebSocket connection
            project_id: Project ID to unsubscribe from
        """
        if project_id in self.subscriptions:
            self.subscriptions[project_id].discard(websocket)
            if not self.subscriptions[project_id]:
                del self.subscriptions[project_id]
        logger.debug(f"WebSocket unsubscribed from project {project_id}")

    async def broadcast_to_project(
        self,
        project_id: str,
        event: str,
        data: Dict[str, Any]
    ) -> None:
        """
        Send a message to all clients subscribed to a specific project.

        Args:
            project_id: Project ID
            event: Event type
            data: Event payload
        """
        if project_id not in self.subscriptions:
            # Fall back to broadcast if no specific subscribers
            await self.broadcast(event, {**data, "project_id": project_id})
            return

        subscribers = self.subscriptions.get(project_id, set())
        if not subscribers:
            return

        message = self._create_message(event, {**data, "project_id": project_id})

        disconnected = []
        for connection in subscribers.copy():
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.warning(f"Failed to send to subscriber: {e}")
                disconnected.append(connection)

        for conn in disconnected:
            self.disconnect(conn)

        logger.debug(f"Broadcast '{event}' to {len(subscribers)} project subscribers")

    async def broadcast(self, event: str, data: Dict[str, Any]) -> None:
        """
        Send a message to all connected clients.

        Args:
            event: Event type (e.g., "scene_updated", "project_created")
            data: Event payload as dictionary
        """
        if not self.active_connections:
            logger.debug(f"No clients connected, skipping broadcast: {event}")
            return

        message = self._create_message(event, data)

        # Send to all clients, handle disconnections
        disconnected = []
        for connection in self.active_connections.copy():
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.warning(f"Failed to send to client: {e}")
                disconnected.append(connection)

        # Remove disconnected clients
        for conn in disconnected:
            self.disconnect(conn)

        logger.debug(f"Broadcast '{event}' to {self.connection_count} clients")

    async def send_to_client(
        self,
        websocket: WebSocket,
        event: str,
        data: Dict[str, Any]
    ) -> bool:
        """
        Send a message to a specific client.

        Args:
            websocket: Target WebSocket connection
            event: Event type
            data: Event payload

        Returns:
            True if sent successfully, False otherwise
        """
        return await self._send_to_client(websocket, event, data)

    async def _send_to_client(
        self,
        websocket: WebSocket,
        event: str,
        data: Dict[str, Any]
    ) -> bool:
        """Internal method to send to a client"""
        try:
            message = self._create_message(event, data)
            await websocket.send_text(message)
            return True
        except Exception as e:
            logger.warning(f"Failed to send to client: {e}")
            return False

    def _create_message(self, event: str, data: Dict[str, Any]) -> str:
        """Create JSON message with event wrapper"""
        return json.dumps({
            "event": event,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }, ensure_ascii=False, default=str)

    async def _ping_loop(self) -> None:
        """Send periodic pings to keep connections alive"""
        while self._running:
            try:
                await asyncio.sleep(USER.WEBSOCKET_PING)

                if not self.active_connections:
                    continue

                # Send ping to all clients
                disconnected = []
                for connection in self.active_connections.copy():
                    try:
                        await connection.send_text(
                            json.dumps({"event": "ping", "timestamp": datetime.now().isoformat()})
                        )
                    except Exception:
                        disconnected.append(connection)

                for conn in disconnected:
                    self.disconnect(conn)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ping loop error: {e}")

    async def shutdown(self) -> None:
        """Close all connections and stop ping task"""
        self._running = False

        if self._ping_task:
            self._ping_task.cancel()
            self._ping_task = None

        # Close all connections
        for connection in self.active_connections.copy():
            try:
                await connection.close()
            except Exception:
                pass

        self.active_connections.clear()
        logger.info("WebSocket manager shutdown complete")


# Singleton instance
_manager: Optional[ConnectionManager] = None


def get_connection_manager() -> ConnectionManager:
    """Get the global ConnectionManager instance"""
    global _manager
    if _manager is None:
        _manager = ConnectionManager()
    return _manager
