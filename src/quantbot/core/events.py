"""In-process asynchronous event bus.

A lightweight publish/subscribe hub that decouples producers (market data,
strategies, execution) from consumers (risk, persistence, notifications,
dashboard). It is intentionally simple and dependency-free:

* Subscribers are ``async`` callables receiving an :class:`Event`.
* Publishing never blocks the publisher on slow subscribers: each subscriber is
  invoked concurrently and exceptions are isolated (one failing handler never
  breaks delivery to the others, nor the publisher).
* Optional bounded back-pressure via a per-bus worker queue (``dispatch`` mode)
  so a burst of events cannot starve the event loop.

For cross-process fan-out (API/dashboard) the Redis pub/sub adapter bridges to
this bus; see :mod:`quantbot.infrastructure.cache.redis_cache`.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from quantbot.core.constants import EventType
from quantbot.core.logging import get_logger
from quantbot.core.models import utcnow

_log = get_logger(__name__)

#: Type of an async event handler.
EventHandler = Callable[["Event"], Awaitable[None]]


@dataclass(slots=True)
class Event:
    """An event flowing through the :class:`EventBus`.

    Attributes:
        type: The topic this event belongs to.
        payload: Arbitrary structured data for subscribers.
        source: Optional name of the producing component.
        timestamp: Creation time (UTC).
    """

    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    source: str | None = None
    timestamp: Any = field(default_factory=utcnow)

    def get(self, key: str, default: Any = None) -> Any:
        """Convenience accessor for a payload field."""
        return self.payload.get(key, default)


@dataclass(slots=True)
class _Subscription:
    """Internal record of a single subscription."""

    handler: EventHandler
    once: bool = False


class EventBus:
    """Async in-process pub/sub event bus.

    Two delivery strategies are supported:

    * **Immediate** (default) — :meth:`publish` awaits concurrent delivery to all
      subscribers and returns once they complete.
    * **Queued** — :meth:`start` launches a background worker; :meth:`emit`
      enqueues an event and returns instantly, decoupling producers entirely.
    """

    def __init__(self, *, max_queue: int = 10_000) -> None:
        self._subs: dict[EventType, list[_Subscription]] = defaultdict(list)
        self._global_subs: list[_Subscription] = []
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=max_queue)
        self._worker: asyncio.Task[None] | None = None
        self._running = False
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ subscribe

    def subscribe(self, event_type: EventType, handler: EventHandler) -> Callable[[], None]:
        """Subscribe *handler* to a specific event type.

        Returns:
            An ``unsubscribe`` callable that removes the subscription.
        """
        sub = _Subscription(handler=handler)
        self._subs[event_type].append(sub)
        return lambda: self._remove(self._subs[event_type], sub)

    def subscribe_all(self, handler: EventHandler) -> Callable[[], None]:
        """Subscribe *handler* to every event type (wildcard)."""
        sub = _Subscription(handler=handler)
        self._global_subs.append(sub)
        return lambda: self._remove(self._global_subs, sub)

    def once(self, event_type: EventType, handler: EventHandler) -> Callable[[], None]:
        """Subscribe *handler* to fire at most once for *event_type*."""
        sub = _Subscription(handler=handler, once=True)
        self._subs[event_type].append(sub)
        return lambda: self._remove(self._subs[event_type], sub)

    @staticmethod
    def _remove(bucket: list[_Subscription], sub: _Subscription) -> None:
        try:
            bucket.remove(sub)
        except ValueError:  # pragma: no cover - already removed
            pass

    async def wait_for(
        self, event_type: EventType, *, timeout: float | None = None
    ) -> Event:
        """Await the next event of *event_type* and return it.

        Raises:
            asyncio.TimeoutError: If *timeout* elapses first.
        """
        future: asyncio.Future[Event] = asyncio.get_running_loop().create_future()

        async def _resolver(event: Event) -> None:
            if not future.done():
                future.set_result(event)

        unsubscribe = self.once(event_type, _resolver)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            unsubscribe()

    # ------------------------------------------------------------------ publish

    async def publish(self, event: Event) -> None:
        """Deliver *event* to all matching subscribers concurrently and await them."""
        handlers = self._collect(event.type)
        if not handlers:
            return
        results = await asyncio.gather(
            *(self._invoke(sub, event) for sub in handlers),
            return_exceptions=True,
        )
        for sub, result in zip(handlers, results, strict=True):
            if isinstance(result, Exception):
                _log.error(
                    "event_handler_failed",
                    event_type=event.type.value,
                    handler=getattr(sub.handler, "__qualname__", repr(sub.handler)),
                    error=str(result),
                )

    def publish_nowait(self, event: Event) -> None:
        """Fire-and-forget delivery, scheduling :meth:`publish` as a task."""
        asyncio.create_task(self.publish(event))  # noqa: RUF006 - intentional detach

    async def emit(self, event: Event) -> None:
        """Enqueue *event* for the background worker (requires :meth:`start`).

        Falls back to :meth:`publish` if the worker is not running.
        """
        if not self._running:
            await self.publish(event)
            return
        await self._queue.put(event)

    def _collect(self, event_type: EventType) -> list[_Subscription]:
        """Return all subscriptions matching *event_type*, pruning one-shots."""
        specific = self._subs.get(event_type, [])
        matched = [*specific, *self._global_subs]
        # Remove fired one-shot subscriptions for this type.
        if any(s.once for s in specific):
            self._subs[event_type] = [s for s in specific if not s.once]
            # Re-append the still-living global subs handled separately.
        return matched

    async def _invoke(self, sub: _Subscription, event: Event) -> None:
        await sub.handler(event)

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        """Start the background dispatch worker (enables :meth:`emit` queuing)."""
        async with self._lock:
            if self._running:
                return
            self._running = True
            self._worker = asyncio.create_task(self._run(), name="eventbus-worker")
            _log.debug("eventbus_started")

    async def stop(self, *, drain: bool = True) -> None:
        """Stop the worker, optionally draining queued events first."""
        async with self._lock:
            if not self._running:
                return
            self._running = False
            if drain:
                await self._queue.join()
            if self._worker is not None:
                self._worker.cancel()
                try:
                    await self._worker
                except asyncio.CancelledError:
                    pass
                self._worker = None
            _log.debug("eventbus_stopped")

    async def _run(self) -> None:
        while self._running or not self._queue.empty():
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except TimeoutError:
                continue
            try:
                await self.publish(event)
            finally:
                self._queue.task_done()

    # ------------------------------------------------------------------ helpers

    def subscriber_count(self, event_type: EventType | None = None) -> int:
        """Number of subscribers for *event_type* (or all, including globals)."""
        if event_type is None:
            return sum(len(v) for v in self._subs.values()) + len(self._global_subs)
        return len(self._subs.get(event_type, [])) + len(self._global_subs)

    async def __aenter__(self) -> EventBus:
        await self.start()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.stop()


__all__ = ["Event", "EventBus", "EventHandler"]
