"""Assorted utilities: retry/backoff, decimal & time helpers, async primitives.

Everything here is pure (no global state) and heavily reused across the codebase,
so it is kept small, well-typed and individually unit-tested.
"""

from __future__ import annotations

import asyncio
import functools
import random
import time
from collections.abc import Awaitable, Callable, Iterable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, ParamSpec, TypeVar, cast

from quantbot.core.constants import Timeframe
from quantbot.core.exceptions import QuantBotError, TransientError
from quantbot.core.logging import get_logger

_log = get_logger(__name__)

P = ParamSpec("P")
T = TypeVar("T")


# ---------------------------------------------------------------------------
# Retry / backoff
# ---------------------------------------------------------------------------


def _compute_delay(attempt: int, base: float, factor: float, maximum: float, jitter: bool) -> float:
    """Exponential backoff delay for *attempt* (1-based) with optional jitter."""
    delay = min(base * (factor ** (attempt - 1)), maximum)
    if jitter:
        # Full jitter: random in [0, delay] avoids thundering-herd retries.
        delay = random.uniform(0, delay)  # noqa: S311 - not used for crypto
    return delay


def async_retry(
    *,
    max_attempts: int = 4,
    base_delay: float = 1.0,
    factor: float = 2.0,
    max_delay: float = 60.0,
    jitter: bool = True,
    retry_on: tuple[type[BaseException], ...] = (TransientError,),
    respect_retryable: bool = True,
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """Decorate an async function with exponential-backoff retries.

    Args:
        max_attempts: Total attempts before giving up (>= 1).
        base_delay: Initial delay in seconds.
        factor: Exponential growth factor between attempts.
        max_delay: Upper bound for any single delay.
        jitter: Apply full jitter to spread out retries.
        retry_on: Exception types that trigger a retry.
        respect_retryable: If a :class:`QuantBotError` exposes ``retryable=False``,
            do not retry it even if its type matches *retry_on*.

    A :class:`~quantbot.core.exceptions.RateLimitError` carrying ``retry_after``
    overrides the computed delay with the exchange-suggested wait.
    """

    def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            last_exc: BaseException | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except retry_on as exc:
                    last_exc = exc
                    if respect_retryable and isinstance(exc, QuantBotError) and not exc.retryable:
                        raise
                    if attempt >= max_attempts:
                        break
                    delay = _retry_after(exc) or _compute_delay(
                        attempt, base_delay, factor, max_delay, jitter
                    )
                    _log.warning(
                        "retrying",
                        func=func.__qualname__,
                        attempt=attempt,
                        max_attempts=max_attempts,
                        delay=round(delay, 3),
                        error=str(exc),
                    )
                    await asyncio.sleep(delay)
            assert last_exc is not None  # noqa: S101 - loop guarantees this
            raise last_exc

        return wrapper

    return decorator


def _retry_after(exc: BaseException) -> float | None:
    """Extract an exchange-suggested ``retry_after`` (seconds) if present."""
    value = getattr(exc, "retry_after", None)
    return float(value) if value else None


async def gather_limited(
    *aws: Awaitable[T], limit: int = 10, return_exceptions: bool = False
) -> list[T]:
    """Like :func:`asyncio.gather` but bounded by a concurrency *limit*."""
    semaphore = asyncio.Semaphore(limit)

    async def _run(aw: Awaitable[T]) -> T:
        async with semaphore:
            return await aw

    return await asyncio.gather(
        *(_run(aw) for aw in aws), return_exceptions=return_exceptions
    )  # type: ignore[return-value]


async def with_timeout(aw: Awaitable[T], timeout: float, *, default: T | None = None) -> T | None:
    """Await *aw* with a timeout, returning *default* instead of raising on timeout."""
    try:
        return await asyncio.wait_for(aw, timeout=timeout)
    except TimeoutError:
        return default


# ---------------------------------------------------------------------------
# Decimal helpers
# ---------------------------------------------------------------------------


def to_decimal(value: Any) -> Decimal:
    """Convert *value* to :class:`Decimal` robustly (via ``str`` for floats)."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise QuantBotError(f"Cannot convert {value!r} to Decimal") from exc


def round_down(value: Decimal, step: Decimal) -> Decimal:
    """Floor *value* to the nearest multiple of *step* (step > 0)."""
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def round_to_precision(value: Decimal, precision: int, *, rounding: str = ROUND_DOWN) -> Decimal:
    """Quantise *value* to *precision* decimal places."""
    if precision < 0:
        return value
    quant = Decimal(1).scaleb(-precision)
    return value.quantize(quant, rounding=rounding)


def pct_change(old: Decimal, new: Decimal) -> Decimal:
    """Fractional change from *old* to *new* (0 if *old* is 0)."""
    if old == 0:
        return Decimal("0")
    return (new - old) / old


def clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    """Clamp *value* into the inclusive ``[low, high]`` range."""
    return max(low, min(value, high))


def safe_div(numerator: Decimal, denominator: Decimal, default: Decimal = Decimal("0")) -> Decimal:
    """Divide guarding against division by zero."""
    if denominator == 0:
        return default
    return numerator / denominator


def money(value: Any, places: int = 2) -> Decimal:
    """Round a value to *places* decimals using half-up (display formatting)."""
    return round_to_precision(to_decimal(value), places, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def utcnow() -> datetime:
    """Timezone-aware current UTC time."""
    return datetime.now(UTC)


def to_millis(dt: datetime) -> int:
    """Convert a datetime to Unix epoch milliseconds."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp() * 1000)


def from_millis(ms: int | float) -> datetime:
    """Convert Unix epoch milliseconds to a timezone-aware UTC datetime."""
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def floor_to_timeframe(dt: datetime, timeframe: Timeframe) -> datetime:
    """Floor *dt* to the start of its candle for *timeframe*."""
    seconds = timeframe.seconds
    epoch = int(dt.replace(tzinfo=dt.tzinfo or UTC).timestamp())
    floored = (epoch // seconds) * seconds
    return datetime.fromtimestamp(floored, tz=UTC)


def candle_open_times(start: datetime, end: datetime, timeframe: Timeframe) -> list[datetime]:
    """All candle open-times in ``[start, end)`` for *timeframe*."""
    step = timedelta(seconds=timeframe.seconds)
    current = floor_to_timeframe(start, timeframe)
    out: list[datetime] = []
    while current < end:
        out.append(current)
        current += step
    return out


def parse_timeframe_to_ms(timeframe: Timeframe | str) -> int:
    """Return the millisecond duration of a timeframe."""
    tf = timeframe if isinstance(timeframe, Timeframe) else Timeframe.from_string(timeframe)
    return tf.milliseconds


# ---------------------------------------------------------------------------
# Collection / misc helpers
# ---------------------------------------------------------------------------


def chunked(seq: Sequence[T], size: int) -> list[Sequence[T]]:
    """Split *seq* into consecutive chunks of at most *size* items."""
    if size <= 0:
        raise ValueError("size must be > 0")
    return [seq[i : i + size] for i in range(0, len(seq), size)]


def first(iterable: Iterable[T], default: T | None = None) -> T | None:
    """Return the first item of *iterable* or *default* if empty."""
    return next(iter(iterable), default)


def coalesce(*values: T | None) -> T | None:
    """Return the first non-``None`` argument, or ``None``."""
    for value in values:
        if value is not None:
            return value
    return None


class Timer:
    """Context manager measuring wall-clock elapsed seconds."""

    __slots__ = ("_start", "elapsed")

    def __init__(self) -> None:
        self._start = 0.0
        self.elapsed = 0.0

    def __enter__(self) -> Timer:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.elapsed = time.perf_counter() - self._start


def truncate(text: str, length: int = 120, suffix: str = "…") -> str:
    """Truncate *text* to *length* characters, appending *suffix* if shortened."""
    if len(text) <= length:
        return text
    return text[: length - len(suffix)] + suffix


__all__ = [
    "Timer",
    "async_retry",
    "candle_open_times",
    "chunked",
    "clamp",
    "coalesce",
    "first",
    "floor_to_timeframe",
    "from_millis",
    "gather_limited",
    "money",
    "parse_timeframe_to_ms",
    "pct_change",
    "round_down",
    "round_to_precision",
    "safe_div",
    "to_decimal",
    "to_millis",
    "truncate",
    "utcnow",
    "with_timeout",
]


# Internal export for typed callers needing the cast helper (kept private).
_cast = cast
