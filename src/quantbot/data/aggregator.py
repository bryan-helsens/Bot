"""Timeframe aggregation: build higher-timeframe candles from a lower one.

Useful when an exchange stream for a given interval is unavailable or to derive
several higher timeframes from a single 1m subscription (saving websocket
connections). Aggregation is *boundary-aligned*: a higher-timeframe candle for,
say, 15m always starts at minute 0/15/30/45 — never at an arbitrary offset — so
results match the exchange's native candles exactly.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import timedelta

from quantbot.core.constants import Timeframe
from quantbot.core.exceptions import DataError
from quantbot.core.logging import LoggerMixin
from quantbot.core.models import Candle
from quantbot.core.utils import floor_to_timeframe


def can_aggregate(source: Timeframe, target: Timeframe) -> bool:
    """Whether *target* candles can be exactly built from *source* candles.

    Requires the target interval to be a whole multiple of the source interval.
    """
    if target.seconds <= source.seconds:
        return False
    return target.seconds % source.seconds == 0


def aggregate_candles(
    candles: Sequence[Candle], target: Timeframe, *, only_closed: bool = True
) -> list[Candle]:
    """Aggregate a sequence of lower-timeframe *candles* into *target* candles.

    Args:
        candles: Source candles, assumed ordered by open time and all of the
            same (lower) timeframe.
        target: The higher timeframe to build.
        only_closed: If ``True`` (default) a partially-filled trailing bucket is
            omitted; set to ``False`` to include the in-progress bar.

    Returns:
        The aggregated higher-timeframe candles.
    """
    if not candles:
        return []
    source = candles[0].timeframe
    if not can_aggregate(source, target):
        raise DataError(
            f"Cannot aggregate {source.value} -> {target.value}",
            context={"source": source.value, "target": target.value},
        )
    ratio = target.seconds // source.seconds
    symbol = candles[0].symbol

    buckets: dict = {}
    order: list = []
    for candle in candles:
        bucket_start = floor_to_timeframe(candle.open_time, target)
        if bucket_start not in buckets:
            buckets[bucket_start] = [candle]
            order.append(bucket_start)
        else:
            buckets[bucket_start].append(candle)

    out: list[Candle] = []
    for start in order:
        group = buckets[start]
        if only_closed and len(group) < ratio:
            continue  # incomplete trailing bucket
        out.append(_merge(symbol, target, start, group))
    return out


def _merge(symbol: str, target: Timeframe, start, group: list[Candle]) -> Candle:
    """Merge a group of same-bucket candles into one higher-timeframe candle."""
    close_time = start + timedelta(seconds=target.seconds) - timedelta(milliseconds=1)
    return Candle(
        symbol=symbol,
        timeframe=target,
        open_time=start,
        close_time=close_time,
        open=group[0].open,
        high=max(c.high for c in group),
        low=min(c.low for c in group),
        close=group[-1].close,
        volume=sum((c.volume for c in group), start=type(group[0].volume)(0)),
        quote_volume=sum((c.quote_volume for c in group), start=type(group[0].quote_volume)(0)),
        trades=sum(c.trades for c in group),
        is_closed=True,
    )


class TimeframeAggregator(LoggerMixin):
    """Stateful streaming aggregator: feed source candles, emit target candles.

    Maintains one open bucket per target timeframe. Each completed bucket is
    returned exactly once (when the first candle of the next bucket arrives, or
    via :meth:`flush`).
    """

    def __init__(self, source: Timeframe, targets: Iterable[Timeframe]) -> None:
        targets = list(targets)
        for target in targets:
            if not can_aggregate(source, target):
                raise DataError(
                    f"Cannot aggregate {source.value} -> {target.value}",
                    context={"source": source.value, "target": target.value},
                )
        self._source = source
        self._targets = targets
        self._open: dict[Timeframe, list[Candle]] = {t: [] for t in targets}
        self._bucket_start: dict[Timeframe, object] = {}

    def feed(self, candle: Candle) -> dict[Timeframe, Candle]:
        """Feed one source candle; return any target candles that just closed.

        Returns:
            A mapping ``{target_timeframe: closed_candle}`` for every target
            whose bucket completed on this candle (may be empty).
        """
        if candle.timeframe != self._source:
            raise DataError(
                f"Expected {self._source.value} candle, got {candle.timeframe.value}"
            )
        closed: dict[Timeframe, Candle] = {}
        for target in self._targets:
            ratio = target.seconds // self._source.seconds
            bucket_start = floor_to_timeframe(candle.open_time, target)
            current_start = self._bucket_start.get(target)

            if current_start is not None and bucket_start != current_start:
                # New bucket begins → emit the completed previous bucket.
                group = self._open[target]
                if group:
                    closed[target] = _merge(
                        candle.symbol, target, current_start, group
                    )
                self._open[target] = []

            self._bucket_start[target] = bucket_start
            self._open[target].append(candle)

            # Emit immediately if the bucket is now exactly full.
            if len(self._open[target]) == ratio:
                closed[target] = _merge(candle.symbol, target, bucket_start, self._open[target])
                self._open[target] = []
                self._bucket_start[target] = None
        return closed

    def flush(self, symbol: str | None = None) -> dict[Timeframe, Candle]:
        """Emit all currently-open (partial) buckets and reset state."""
        out: dict[Timeframe, Candle] = {}
        for target in self._targets:
            group = self._open[target]
            start = self._bucket_start.get(target)
            if group and start is not None:
                out[target] = _merge(symbol or group[0].symbol, target, start, group)
            self._open[target] = []
            self._bucket_start[target] = None
        return out


__all__ = ["TimeframeAggregator", "aggregate_candles", "can_aggregate"]
