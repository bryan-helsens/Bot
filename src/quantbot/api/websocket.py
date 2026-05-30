"""WebSocket push: broadcast live engine events to connected dashboards.

A :class:`ConnectionManager` tracks connected clients and broadcasts JSON
messages. The :class:`EventBroadcaster` subscribes to the engine's
:class:`EventBus` and forwards relevant events (trades, risk, equity updates) to
all clients, so the React dashboard updates in real time without polling.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

from fastapi import WebSocket

from quantbot.core.constants import EventType
from quantbot.core.events import Event, EventBus
from quantbot.core.logging import get_logger
from quantbot.core.models import utcnow

_log = get_logger(__name__)

# Events forwarded to dashboard clients.
_BROADCAST_EVENTS = (
    EventType.TRADE_OPENED,
    EventType.TRADE_CLOSED,
    EventType.RISK_REJECTED,
    EventType.RISK_EVENT,
    EventType.CONNECTION_LOST,
    EventType.CONNECTION_RESTORED,
    EventType.ENGINE_STARTED,
    EventType.ENGINE_STOPPED,
    EventType.TICKER_UPDATE,
)


class ConnectionManager:
    """Track connected WebSocket clients and broadcast to them."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._clients.add(websocket)
        _log.info("ws_client_connected", clients=len(self._clients))

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(websocket)
        _log.info("ws_client_disconnected", clients=len(self._clients))

    async def broadcast(self, message: dict[str, Any]) -> None:
        data = json.dumps(message, default=str)
        dead: list[WebSocket] = []
        for client in list(self._clients):
            try:
                await client.send_text(data)
            except Exception:  # noqa: BLE001 - drop broken connections
                dead.append(client)
        if dead:
            async with self._lock:
                for client in dead:
                    self._clients.discard(client)

    @property
    def client_count(self) -> int:
        return len(self._clients)


class EventBroadcaster:
    """Bridge the engine EventBus to WebSocket clients."""

    def __init__(self, manager: ConnectionManager) -> None:
        self._manager = manager
        self._unsubscribers: list = []

    def subscribe(self, bus: EventBus) -> None:
        for event_type in _BROADCAST_EVENTS:
            self._unsubscribers.append(bus.subscribe(event_type, self._forward))

    async def _forward(self, event: Event) -> None:
        await self._manager.broadcast(
            {
                "type": event.type.value,
                "payload": event.payload,
                "ts": utcnow().isoformat(),
            }
        )

    def unsubscribe(self) -> None:
        for unsub in self._unsubscribers:
            with contextlib.suppress(Exception):
                unsub()
        self._unsubscribers.clear()


__all__ = ["ConnectionManager", "EventBroadcaster"]
