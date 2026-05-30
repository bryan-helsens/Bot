"""Client-side rate limiting for the Binance API.

Binance enforces two independent budgets:

* **Request weight** — every REST endpoint costs a weight; the sum per rolling
  minute must stay under a cap (e.g. 6000 for spot).
* **Order count** — a separate budget per 10 seconds and per day.

:class:`RateLimiter` models both with token buckets that refill continuously, so
calls are throttled smoothly rather than in bursts. Callers ``await`` an
:meth:`acquire` before each request; if the budget is exhausted the coroutine
sleeps just long enough for enough tokens to refill. The limiter also honours a
server-driven cooldown (set via :meth:`pause_until`) after a 429/418 response.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from quantbot.core.logging import get_logger

_log = get_logger(__name__)


@dataclass(slots=True)
class _Bucket:
    """A continuously-refilling token bucket."""

    capacity: float
    refill_per_sec: float
    tokens: float
    updated_at: float

    def _refill(self, now: float) -> None:
        elapsed = now - self.updated_at
        if elapsed > 0:
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_sec)
            self.updated_at = now

    def time_until(self, cost: float, now: float) -> float:
        """Seconds until *cost* tokens are available (0 if already available)."""
        self._refill(now)
        if self.tokens >= cost:
            return 0.0
        deficit = cost - self.tokens
        return deficit / self.refill_per_sec if self.refill_per_sec > 0 else float("inf")

    def consume(self, cost: float, now: float) -> None:
        """Deduct *cost* tokens (call only when available)."""
        self._refill(now)
        self.tokens -= cost


class RateLimiter:
    """Weight- and order-count rate limiter with server-cooldown support."""

    def __init__(
        self,
        *,
        max_weight_per_minute: int = 5500,
        max_orders_per_10s: int = 45,
        max_orders_per_day: int = 150_000,
        safety_factor: float = 1.0,
    ) -> None:
        """Create a limiter.

        Args:
            max_weight_per_minute: Request-weight budget per rolling minute.
            max_orders_per_10s: Order budget per rolling 10 seconds.
            max_orders_per_day: Order budget per rolling day.
            safety_factor: Scale (<1) to keep a margin below the hard limits.
        """
        now = time.monotonic()
        weight_cap = max_weight_per_minute * safety_factor
        o10_cap = max_orders_per_10s * safety_factor
        oday_cap = max_orders_per_day * safety_factor
        self._weight = _Bucket(weight_cap, weight_cap / 60.0, weight_cap, now)
        self._orders_10s = _Bucket(o10_cap, o10_cap / 10.0, o10_cap, now)
        self._orders_day = _Bucket(oday_cap, oday_cap / 86_400.0, oday_cap, now)
        self._lock = asyncio.Lock()
        self._paused_until = 0.0

    async def acquire(self, weight: int = 1, *, is_order: bool = False) -> None:
        """Block until budget for a request of *weight* (and an order) is free."""
        async with self._lock:
            while True:
                now = time.monotonic()
                wait = self._cooldown_remaining(now)
                wait = max(wait, self._weight.time_until(weight, now))
                if is_order:
                    wait = max(
                        wait,
                        self._orders_10s.time_until(1, now),
                        self._orders_day.time_until(1, now),
                    )
                if wait <= 0:
                    self._weight.consume(weight, now)
                    if is_order:
                        self._orders_10s.consume(1, now)
                        self._orders_day.consume(1, now)
                    return
                _log.debug("rate_limit_wait", seconds=round(wait, 3), weight=weight)
                await asyncio.sleep(min(wait, 5.0))

    def _cooldown_remaining(self, now: float) -> float:
        return max(0.0, self._paused_until - now)

    def pause_until(self, seconds_from_now: float) -> None:
        """Impose a hard cooldown (after a 429/418) for *seconds_from_now*."""
        self._paused_until = max(self._paused_until, time.monotonic() + seconds_from_now)
        _log.warning("rate_limit_cooldown", seconds=round(seconds_from_now, 2))

    def update_used_weight(self, used_weight: int) -> None:
        """Reconcile the weight bucket with the exchange-reported usage.

        Binance returns the authoritative used weight in response headers; if the
        server thinks we have used more than our local estimate, we drain tokens
        to match so we never overshoot.
        """
        now = time.monotonic()
        self._weight._refill(now)
        server_remaining = max(0.0, self._weight.capacity - used_weight)
        if server_remaining < self._weight.tokens:
            self._weight.tokens = server_remaining

    @property
    def available_weight(self) -> float:
        """Currently available request-weight tokens."""
        self._weight._refill(time.monotonic())
        return self._weight.tokens

    @property
    def is_paused(self) -> bool:
        """Whether a server-driven cooldown is currently active."""
        return self._cooldown_remaining(time.monotonic()) > 0


__all__ = ["RateLimiter"]
