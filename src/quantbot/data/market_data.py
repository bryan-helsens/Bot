"""In-memory market-data service maintaining rolling OHLCV buffers.

:class:`MarketDataService` is the single source of recent market data for the
whole engine. It:

* Warms up each ``(symbol, timeframe)`` buffer from REST history on start.
* Ingests live closed candles from the gateway websocket streams.
* Keeps a fixed-length rolling buffer per series (a deque) and exposes it as
  numpy arrays for the indicator functions, or as :class:`Candle` objects.
* Publishes a :data:`EventType.CANDLE_CLOSED` event for every new closed candle
  so strategies, the aggregator and persistence react in a decoupled way.
* De-duplicates and gap-detects candles to guarantee a clean, monotonic series.

It deliberately holds only *recent* data (bounded memory); long history for
backtests is served by :mod:`quantbot.data.historical`.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Iterable

import numpy as np
import numpy.typing as npt

from quantbot.core.constants import EventType, Timeframe
from quantbot.core.events import Event, EventBus
from quantbot.core.exceptions import InsufficientDataError
from quantbot.core.logging import LoggerMixin
from quantbot.core.models import Candle
from quantbot.exchanges.base import ExchangeGateway

FloatArray = npt.NDArray[np.float64]


class CandleSeries:
    """A bounded, gap-aware rolling buffer of candles for one series."""

    def __init__(self, symbol: str, timeframe: Timeframe, maxlen: int = 1000) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self._buffer: deque[Candle] = deque(maxlen=maxlen)

    def __len__(self) -> int:
        return len(self._buffer)

    @property
    def last(self) -> Candle | None:
        """Most recent candle, or ``None`` if empty."""
        return self._buffer[-1] if self._buffer else None

    def append(self, candle: Candle) -> bool:
        """Append *candle*, de-duplicating by open time.

        Returns:
            ``True`` if the candle was newly added, ``False`` if it was a
            duplicate/older candle that was ignored or an in-place update of the
            current (unclosed→closed) candle.
        """
        last = self.last
        if last is not None:
            if candle.open_time < last.open_time:
                return False  # stale/out-of-order
            if candle.open_time == last.open_time:
                self._buffer[-1] = candle  # update the latest bar in place
                return False
        self._buffer.append(candle)
        return True

    def extend(self, candles: Iterable[Candle]) -> int:
        """Append many candles in order; return the count newly added."""
        added = 0
        for candle in candles:
            if self.append(candle):
                added += 1
        return added

    def has_gap(self) -> bool:
        """Whether the last two candles are not exactly one interval apart."""
        if len(self._buffer) < 2:
            return False
        expected = self.timeframe.seconds
        delta = (self._buffer[-1].open_time - self._buffer[-2].open_time).total_seconds()
        return abs(delta - expected) > 1.0

    def candles(self, n: int | None = None) -> list[Candle]:
        """Return the last *n* candles (all if ``None``)."""
        if n is None:
            return list(self._buffer)
        return list(self._buffer)[-n:]

    # ------------------------------------------------------------------ arrays

    def _column(self, attr: str, n: int | None) -> FloatArray:
        data = self.candles(n)
        return np.array([float(getattr(c, attr)) for c in data], dtype=np.float64)

    def opens(self, n: int | None = None) -> FloatArray:
        return self._column("open", n)

    def highs(self, n: int | None = None) -> FloatArray:
        return self._column("high", n)

    def lows(self, n: int | None = None) -> FloatArray:
        return self._column("low", n)

    def closes(self, n: int | None = None) -> FloatArray:
        return self._column("close", n)

    def volumes(self, n: int | None = None) -> FloatArray:
        return self._column("volume", n)


class MarketDataService(LoggerMixin):
    """Maintain live rolling OHLCV buffers across many symbols/timeframes."""

    def __init__(
        self,
        gateway: ExchangeGateway,
        *,
        event_bus: EventBus | None = None,
        buffer_size: int = 1000,
        warmup: int = 200,
    ) -> None:
        self._gateway = gateway
        self._bus = event_bus
        self._buffer_size = buffer_size
        self._warmup = warmup
        self._series: dict[tuple[str, Timeframe], CandleSeries] = {}
        self._tasks: list[asyncio.Task[None]] = []
        self._active: list[tuple[str, Timeframe]] = []
        self._running = False

    # ------------------------------------------------------------------ access

    def series(self, symbol: str, timeframe: Timeframe) -> CandleSeries:
        """Return (creating if needed) the buffer for ``(symbol, timeframe)``."""
        key = (symbol, timeframe)
        series = self._series.get(key)
        if series is None:
            series = CandleSeries(symbol, timeframe, maxlen=self._buffer_size)
            self._series[key] = series
        return series

    def get_closes(self, symbol: str, timeframe: Timeframe, n: int | None = None) -> FloatArray:
        """Convenience accessor for the close-price array of a series."""
        return self.series(symbol, timeframe).closes(n)

    def latest_price(self, symbol: str, timeframe: Timeframe) -> float | None:
        """Most recent close price for ``(symbol, timeframe)``, if available."""
        last = self.series(symbol, timeframe).last
        return float(last.close) if last is not None else None

    # ------------------------------------------------------------------ lifecycle

    async def warmup(self, symbols: Iterable[str], timeframes: Iterable[Timeframe]) -> None:
        """Pre-fill buffers from REST history for every symbol/timeframe.

        Resilient per symbol: a pair the exchange doesn't list (common when a
        configured meme/low-cap coin isn't on the testnet) is logged and SKIPPED
        instead of crashing startup. Only pairs that returned data are recorded in
        :attr:`_active` and get a live consumer.
        """
        self._active = []
        for symbol in symbols:
            for timeframe in timeframes:
                try:
                    candles = await self._gateway.get_klines(
                        symbol, timeframe, limit=self._warmup
                    )
                except Exception as exc:  # noqa: BLE001 - skip unavailable symbol, keep the rest
                    self.log.warning(
                        "warmup_skip_symbol", symbol=symbol,
                        timeframe=timeframe.value, error=str(exc),
                    )
                    continue
                series = self.series(symbol, timeframe)
                added = series.extend(candles)
                self._active.append((symbol, timeframe))
                self.log.debug(
                    "warmup_loaded", symbol=symbol, timeframe=timeframe.value, candles=added
                )
        if not self._active:
            self.log.warning("warmup_no_active_symbols")

    async def start(self, symbols: Iterable[str], timeframes: Iterable[Timeframe]) -> None:
        """Warm up and begin consuming live candle streams (skipping bad symbols)."""
        symbols = list(symbols)
        timeframes = list(timeframes)
        await self.warmup(symbols, timeframes)
        self._running = True
        for symbol, timeframe in self._active:
            task = asyncio.create_task(
                self._consume(symbol, timeframe),
                name=f"md:{symbol}:{timeframe.value}",
            )
            self._tasks.append(task)
        self.log.info("market_data_started", series=len(self._tasks))

    async def stop(self) -> None:
        """Stop all stream consumers."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        self.log.info("market_data_stopped")

    async def _consume(self, symbol: str, timeframe: Timeframe) -> None:
        """Consume a single live candle stream into its buffer."""
        series = self.series(symbol, timeframe)
        try:
            async for candle in self._gateway.stream_klines(symbol, timeframe):
                is_new = series.append(candle)
                if not is_new:
                    continue
                if series.has_gap():
                    self.log.warning(
                        "candle_gap_detected", symbol=symbol, timeframe=timeframe.value
                    )
                    await self._backfill(series)
                await self._publish_candle(candle)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - one stream dying must not crash others
            self.log.warning(
                "stream_consume_failed", symbol=symbol, timeframe=timeframe.value, error=str(exc)
            )

    async def _backfill(self, series: CandleSeries) -> None:
        """Refetch recent history to repair a detected gap."""
        try:
            candles = await self._gateway.get_klines(
                series.symbol, series.timeframe, limit=self._warmup
            )
            series.extend(candles)
        except Exception as exc:  # noqa: BLE001 - backfill is best-effort
            self.log.warning("backfill_failed", symbol=series.symbol, error=str(exc))

    async def _publish_candle(self, candle: Candle) -> None:
        if self._bus is not None:
            await self._bus.publish(
                Event(
                    EventType.CANDLE_CLOSED,
                    payload={
                        "symbol": candle.symbol,
                        "timeframe": candle.timeframe.value,
                        "candle": candle,
                    },
                    source="market_data",
                )
            )

    def require(self, symbol: str, timeframe: Timeframe, minimum: int) -> CandleSeries:
        """Return a series, raising if it holds fewer than *minimum* candles."""
        series = self.series(symbol, timeframe)
        if len(series) < minimum:
            raise InsufficientDataError(
                f"{symbol} {timeframe.value} has {len(series)} candles, need {minimum}",
                context={"have": len(series), "need": minimum},
            )
        return series

    async def __aenter__(self) -> MarketDataService:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.stop()


__all__ = ["CandleSeries", "MarketDataService"]
