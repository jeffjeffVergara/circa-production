"""
Realtime fan-out for the support console.

Single-process hub suitable for one uvicorn worker. For multi-pod deployments,
replace `emit()` internals with Redis Pub/Sub (or Supabase Realtime) — keep the
same event envelope: ``{"event": str, "payload": dict}``.
"""

from __future__ import annotations

import asyncio
import logging
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

    async def emit(self, event: str, payload: dict) -> None:
        """
        Fan-out to every connected socket. Failed sends drop the socket.

        Redis scaling sketch:
          publish channel ``circa:support`` JSON ``{"event","payload"}``;
          each pod subscribes and forwards to local `_connections`.
        """
        message = {"event": event, "payload": payload}
        async with self._lock:
            targets = list(self._connections)

        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                self._connections = [w for w in self._connections if w not in dead]


hub = SupportRealtimeHub()
