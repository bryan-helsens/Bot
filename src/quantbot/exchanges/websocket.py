"""Resilient WebSocket manager for Binance market & user data streams.

Responsibilities:
    * Maintain a single multiplexed websocket connection to a base URL.
    * Auto-reconnect with exponential backoff + jitter on any drop.
    * **Resubscribe** every active stream after a reconnect (Binance forgets
      subscriptions on a new connection).
    * Heartbeat: respond to server pings and detect a *stale* connection (no
      data within ``stale_timeout``) to force a reconnect.
    * Fan out parsed messages to per-stream async queues consumed as async
      iterators, so callers simply ``async for msg in manager.subscribe(...)``.
    * Emit connection lost/restored events for notifications.

This module is transport-only: it knows nothing about candle/ticker schemas.
The Binance adapters map raw payloads to domain models.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import random
from collections.abc import AsyncIterator
from typing import Any

import aiohttp

from quantbot.core.config import WebSocketSettings
from quantbot.core.events import Event, EventBus
from quantbot.core.constants import EventType
from quantbot.core.logging import LoggerMixin
from quantbot.core.utils import utcnow

_SENTINEL = object()


class _StreamQueue:
    """A bounded async queue exposed as an async iterator for one stream."""

    def __init__(self, name: str, maxsize: int = 1000) -> None:
        self.name = name
        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=maxsize)
        self._closed = False

    async def put(self, item: Any) -> None:
        if self._closed:
            return
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            # Drop the oldest item to favour fresh market data over stale.
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                self._queue.put_nowait(item)

    def close(self) -> None:
        self._closed = True
        # Guarantee the sentinel is enqueued so the async iterator terminates,
        # making room by dropping the oldest item if the queue is full.
        while True:
            try:
                self._queue.put_nowait(_SENTINEL)
                return
            except asyncio.QueueFull:
                with contextlib.suppress(asyncio.QueueEmpty):
                    self._queue.get_nowait()

    async def __aiter__(self) -> AsyncIterator[Any]:
        while True:
            item = await self._queue.get()
            if item is _SENTINEL:
                return
            yield item


class WebSocketManager(LoggerMixin):
    """Manage one resilient multiplexed Binance websocket connection."""

    def __init__(
        self,
        base_url: str,
        settings: WebSocketSettings,
        *,
        event_bus: EventBus | None = None,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._cfg = settings
        self._bus = event_bus
        self._session = session
        self._owns_session = session is None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._streams: dict[str, _StreamQueue] = {}
        self._sub_id = 0
        self._run_task: asyncio.Task[None] | None = None
        self._connected = asyncio.Event()
        self._closing = False
        self._last_message_at = 0.0
        # Batch live subscribes: Binance allows only ~5 inbound messages/sec, so a
        # large basket (60+ coins x timeframes) subscribing one-by-one would get
        # the connection dropped. Pending streams are flushed in ONE message.
        self._pending_subs: set[str] = set()
        self._flush_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        """Start the connection/run loop in the background."""
        if self._run_task is not None:
            return
        if self._session is None:
            self._session = aiohttp.ClientSession()
        self._closing = False
        self._run_task = asyncio.create_task(self._run_loop(), name="ws-manager")

    async def close(self) -> None:
        """Stop the manager, close all streams and the underlying session."""
        self._closing = True
        if self._run_task is not None:
            self._run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._run_task
            self._run_task = None
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        for queue in self._streams.values():
            queue.close()
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    # ------------------------------------------------------------------ subscribe

    def subscribe(self, stream: str) -> _StreamQueue:
        """Register interest in *stream* and return its iterable queue.

        If already connected, the subscription is sent immediately; otherwise it
        will be (re)sent on the next (re)connect.
        """
        queue = self._streams.get(stream)
        if queue is None:
            queue = _StreamQueue(stream)
            self._streams[stream] = queue
            if self._connected.is_set():
                # Debounced batch: collect a burst of subscribes into one message
                # (Binance drops connections that send >~5 messages/sec).
                self._pending_subs.add(stream)
                if self._flush_task is None or self._flush_task.done():
                    self._flush_task = asyncio.create_task(self._flush_subscribes())
        return queue

    async def _flush_subscribes(self) -> None:
        await asyncio.sleep(0.25)  # let the burst accumulate
        pending = sorted(self._pending_subs)
        self._pending_subs.clear()
        if pending and self._connected.is_set():
            await self._send_subscribe(pending)

    async def unsubscribe(self, stream: str) -> None:
        """Remove a subscription and close its queue."""
        queue = self._streams.pop(stream, None)
        if queue is not None:
            queue.close()
            if self._connected.is_set():
                await self._send({"method": "UNSUBSCRIBE", "params": [stream], "id": self._next_id()})

    async def wait_connected(self, timeout: float | None = None) -> bool:
        """Await until connected; return False on timeout."""
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False

    @property
    def connected(self) -> bool:
        """Whether the websocket is currently connected."""
        return self._connected.is_set()

    # ------------------------------------------------------------------ run loop

    async def _run_loop(self) -> None:
        delay = self._cfg.reconnect_initial_delay
        first = True
        while not self._closing:
            try:
                await self._connect_and_listen(announce_restored=not first)
                delay = self._cfg.reconnect_initial_delay  # reset after clean session
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - manager must survive any error
                self.log.warning("ws_connection_error", error=str(exc))
            finally:
                first = False

            if self._closing:
                break
            self._connected.clear()
            await self._emit(EventType.CONNECTION_LOST, {"url": self._base_url})
            sleep_for = min(delay, self._cfg.reconnect_max_delay)
            sleep_for = random.uniform(0, sleep_for)  # noqa: S311 - jitter, not crypto
            self.log.info("ws_reconnecting", delay=round(sleep_for, 2))
            await asyncio.sleep(sleep_for)
            delay = min(delay * self._cfg.reconnect_factor, self._cfg.reconnect_max_delay)

    async def _connect_and_listen(self, *, announce_restored: bool) -> None:
        assert self._session is not None
        url = f"{self._base_url}/ws"
        async with self._session.ws_connect(
            url,
            heartbeat=self._cfg.ping_interval,
            receive_timeout=self._cfg.stale_timeout,
            autoping=True,
        ) as ws:
            self._ws = ws
            self._last_message_at = asyncio.get_running_loop().time()
            self._connected.set()
            self.log.info("ws_connected", url=url, streams=len(self._streams))
            if announce_restored:
                await self._emit(EventType.CONNECTION_RESTORED, {"url": self._base_url})
            if self._streams:
                await self._send_subscribe(list(self._streams))

            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    self._last_message_at = asyncio.get_running_loop().time()
                    self._dispatch(msg.data)
                elif msg.type == aiohttp.WSMsgType.PING:
                    await ws.pong(msg.data)
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    self.log.warning("ws_closed", type=str(msg.type))
                    break
        self._ws = None

    # ------------------------------------------------------------------ messaging

    def _dispatch(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            self.log.warning("ws_bad_json")
            return
        # Combined-stream envelope: {"stream": "...", "data": {...}}
        if isinstance(data, dict) and "stream" in data:
            stream = data["stream"]
            payload = data.get("data", {})
        else:
            # Single-stream connection: route by the event's stream name if any.
            stream = self._infer_stream(data)
            payload = data
        if stream is None:
            return
        queue = self._streams.get(stream)
        if queue is not None:
            asyncio.create_task(queue.put(payload))  # noqa: RUF006

    @staticmethod
    def _infer_stream(data: Any) -> str | None:
        """Best-effort stream name for a single-stream message."""
        if not isinstance(data, dict):
            return None
        event_type = data.get("e")
        symbol = data.get("s")
        if event_type == "kline" and symbol:
            interval = data.get("k", {}).get("i")
            return f"{symbol.lower()}@kline_{interval}" if interval else None
        if event_type == "24hrTicker" and symbol:
            return f"{symbol.lower()}@ticker"
        return None

    async def _send_subscribe(self, streams: list[str]) -> None:
        await self._send({"method": "SUBSCRIBE", "params": streams, "id": self._next_id()})
        self.log.debug("ws_subscribed", streams=streams)

    async def _send(self, message: dict[str, Any]) -> None:
        if self._ws is None or self._ws.closed:
            return
        await self._ws.send_str(json.dumps(message))

    def _next_id(self) -> int:
        self._sub_id += 1
        return self._sub_id

    async def _emit(self, event_type: EventType, payload: dict[str, Any]) -> None:
        if self._bus is not None:
            await self._bus.publish(
                Event(event_type, payload={**payload, "ts": utcnow().isoformat()}, source="ws")
            )

    async def __aenter__(self) -> WebSocketManager:
        await self.start()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()


__all__ = ["WebSocketManager"]
