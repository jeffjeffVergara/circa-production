"""
Realtime fan-out for the support console.

- Sin ``REDIS_URL``: envío directo a todos los WebSockets del proceso.
- Con ``REDIS_URL``: ``emit`` publica en Redis; cada réplica reenvía a sus sockets locales
  (ver ``realtime_redis.py`` + lifespan en ``main.py``).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.websockets import WebSocket

logger = logging.getLogger("circa.support.ws")


class SupportRealtimeHub:
    """Broadcast support inbox events to connected dashboard clients."""

    __slots__ = ("_lock", "_connections")

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._connections: list[WebSocket] = []

    async def register(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.append(websocket)

    async def unregister(self, websocket: WebSocket) -> None:
        async with self._lock:
            try:
                self._connections.remove(websocket)
            except ValueError:
                pass

    async def deliver_local(self, envelope: dict) -> None:
        """Entrega un mensaje ya serializado ``{"event": str, "payload": dict}``."""
        async with self._lock:
            targets = list(self._connections)

        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(envelope)
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                self._connections = [w for w in self._connections if w not in dead]

    async def emit(self, event: str, payload: dict) -> None:
        envelope = {"event": event, "payload": payload}
        use_redis = bool(os.getenv("REDIS_URL", "").strip())
        if use_redis:
            try:
                from app.support.realtime_redis import publish_support_event

                await publish_support_event(envelope)
                return
            except Exception:
                logger.exception("Redis publish failed; falling back to local fan-out")

        await self.deliver_local(envelope)


hub = SupportRealtimeHub()
