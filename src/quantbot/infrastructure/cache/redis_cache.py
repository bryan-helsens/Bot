"""Redis cache, pub/sub and distributed-lock adapter.

Wraps ``redis.asyncio`` behind a small, intention-revealing API used across the
bot:

* **Key/value cache** with JSON (de)serialisation and TTLs.
* **Ticker hash** — latest price per symbol with a short TTL.
* **Rolling market-data buffers** — capped lists per ``(symbol, timeframe)``.
* **Pub/sub** — bridge the in-process :class:`EventBus` to other processes
  (API/dashboard) by publishing/subscribing on Redis channels.
* **Distributed lock** — ``SET NX EX`` based idempotency lock for order submit.

A fake client (e.g. ``fakeredis.aioredis``) can be injected for tests.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from quantbot.core.config import Settings, get_settings
from quantbot.core.exceptions import CacheError
from quantbot.core.logging import get_logger

_log = get_logger(__name__)


def _default(obj: Any) -> Any:
    """JSON serialiser for Decimals/datetimes."""
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


class RedisCache:
    """Async Redis adapter for caching, streaming buffers and pub/sub."""

    def __init__(self, settings: Settings | None = None, *, client: Any | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client
        self._owns_client = client is None

    # ------------------------------------------------------------------ lifecycle

    async def connect(self) -> None:
        """Create the Redis client if one was not injected."""
        if self._client is not None:
            return
        import redis.asyncio as aioredis

        self._client = aioredis.from_url(
            self._settings.redis.resolved_url,
            encoding="utf-8",
            decode_responses=True,
        )
        await self._client.ping()
        _log.info("redis_connected")

    @property
    def client(self) -> Any:
        if self._client is None:
            raise CacheError("Redis not connected; call connect() first")
        return self._client

    async def close(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def health_check(self) -> bool:
        try:
            return bool(await self.client.ping())
        except Exception as exc:  # noqa: BLE001
            _log.warning("redis_health_check_failed", error=str(exc))
            return False

    # ------------------------------------------------------------------ key/value

    async def set_json(self, key: str, value: Any, *, ttl: int | None = None) -> None:
        data = json.dumps(value, default=_default)
        await self.client.set(key, data, ex=ttl)

    async def get_json(self, key: str) -> Any | None:
        data = await self.client.get(key)
        if data is None:
            return None
        try:
            return json.loads(data)
        except (ValueError, TypeError) as exc:
            raise CacheError(f"Corrupt JSON at key {key}") from exc

    async def delete(self, *keys: str) -> int:
        if not keys:
            return 0
        return int(await self.client.delete(*keys))

    async def exists(self, key: str) -> bool:
        return bool(await self.client.exists(key))

    # ------------------------------------------------------------------ tickers

    async def set_ticker(self, symbol: str, price: float, *, ttl: int = 10) -> None:
        await self.client.set(f"ticker:{symbol}", json.dumps({"price": price}), ex=ttl)

    async def get_ticker_price(self, symbol: str) -> float | None:
        data = await self.client.get(f"ticker:{symbol}")
        return float(json.loads(data)["price"]) if data else None

    # ------------------------------------------------------------------ md buffers

    async def push_candle(self, symbol: str, timeframe: str, candle: dict, *, maxlen: int = 1000) -> None:
        """Append a candle to a capped rolling buffer."""
        key = f"md:{symbol}:{timeframe}"
        pipe = self.client.pipeline()
        pipe.rpush(key, json.dumps(candle, default=_default))
        pipe.ltrim(key, -maxlen, -1)
        await pipe.execute()

    async def get_candles(self, symbol: str, timeframe: str, *, count: int = 200) -> list[dict]:
        key = f"md:{symbol}:{timeframe}"
        raw = await self.client.lrange(key, -count, -1)
        return [json.loads(item) for item in raw]

    # ------------------------------------------------------------------ pub/sub

    async def publish(self, channel: str, message: Any) -> int:
        return int(await self.client.publish(channel, json.dumps(message, default=_default)))

    async def subscribe(
        self, channel: str, handler: Callable[[dict], Any]
    ) -> AsyncIterator[None]:
        """Subscribe to *channel*, invoking *handler* for each decoded message."""
        pubsub = self.client.pubsub()
        await pubsub.subscribe(channel)
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                try:
                    payload = json.loads(message["data"])
                except (ValueError, TypeError):
                    payload = {"raw": message["data"]}
                result = handler(payload)
                if hasattr(result, "__await__"):
                    await result
                yield None
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    # ------------------------------------------------------------------ locks

    @asynccontextmanager
    async def lock(self, name: str, *, ttl: int = 30) -> AsyncIterator[bool]:
        """Acquire a best-effort distributed lock (``SET NX EX``).

        Yields ``True`` if acquired, ``False`` otherwise. Always releases the
        lock on exit if it was acquired.
        """
        key = f"lock:{name}"
        acquired = bool(await self.client.set(key, "1", nx=True, ex=ttl))
        try:
            yield acquired
        finally:
            if acquired:
                await self.client.delete(key)

    # ------------------------------------------------------------------ engine state

    async def set_engine_heartbeat(self, status: dict, *, ttl: int = 30) -> None:
        await self.set_json("state:engine", status, ttl=ttl)

    async def get_engine_heartbeat(self) -> dict | None:
        return await self.get_json("state:engine")

    async def __aenter__(self) -> RedisCache:
        await self.connect()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()


__all__ = ["RedisCache"]
