"""Historical OHLCV loader with pagination and an on-disk parquet cache.

Backtests and optimisation need long, contiguous histories that exceed a single
REST page (Binance caps klines at 1000 per call). :class:`HistoricalDataLoader`:

* Pages through ``get_klines`` from a start to an end date, respecting the
  per-call limit and de-duplicating overlaps.
* Caches each ``(symbol, timeframe)`` range to a parquet file (if ``pyarrow`` is
  installed) so repeated backtests are instant and offline-capable.
* Returns either a list of :class:`Candle` models or a ready-to-use pandas
  ``DataFrame`` indexed by open time.

The loader is exchange-agnostic: it only needs an object exposing the
``get_klines`` coroutine, so it works against any :class:`ExchangeGateway`.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import pandas as pd

from quantbot.core.constants import Timeframe
from quantbot.core.logging import LoggerMixin
from quantbot.core.models import Candle
from quantbot.core.utils import from_millis, to_decimal, utcnow

if TYPE_CHECKING:
    from collections.abc import Sequence

#: Columns of the canonical OHLCV dataframe.
OHLCV_COLUMNS = ["open_time", "open", "high", "low", "close", "volume", "quote_volume", "trades"]


class _KlineSource(Protocol):
    """Minimal protocol the loader needs from a gateway."""

    async def get_klines(
        self,
        symbol: str,
        timeframe: Timeframe,
        *,
        limit: int = 500,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[Candle]: ...


class HistoricalDataLoader(LoggerMixin):
    """Load and cache long OHLCV histories from an exchange gateway."""

    def __init__(
        self,
        source: _KlineSource,
        *,
        cache_dir: str | Path = "data/historical",
        page_limit: int = 1000,
        use_cache: bool = True,
    ) -> None:
        self._source = source
        self._cache_dir = Path(cache_dir)
        self._page_limit = page_limit
        self._use_cache = use_cache

    # ------------------------------------------------------------------ public

    async def load(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime | None = None,
    ) -> list[Candle]:
        """Load candles for ``[start, end]`` (end defaults to now)."""
        end = end or utcnow()
        if start >= end:
            raise ValueError("start must be before end")

        cached = self._read_cache(symbol, timeframe) if self._use_cache else None
        if cached is not None and self._covers(cached, start, end):
            self.log.debug("history_cache_hit", symbol=symbol, timeframe=timeframe.value)
            return self._slice(cached, start, end)

        candles = await self._fetch_range(symbol, timeframe, start, end)
        if self._use_cache and candles:
            self._write_cache(symbol, timeframe, self._merge_cached(cached, candles))
        return candles

    async def load_dataframe(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        """Load history as a pandas DataFrame indexed by open time (UTC)."""
        candles = await self.load(symbol, timeframe, start, end)
        return self.to_dataframe(candles)

    # ------------------------------------------------------------------ fetching

    async def _fetch_range(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Candle]:
        """Page through the REST API collecting candles in ``[start, end]``."""
        out: list[Candle] = []
        cursor = start
        step = timedelta(seconds=timeframe.seconds)
        last_open: datetime | None = None
        while cursor < end:
            page = await self._source.get_klines(
                symbol, timeframe, limit=self._page_limit, start_time=cursor, end_time=end
            )
            if not page:
                break
            # Drop any overlap with the previous page.
            fresh = [c for c in page if last_open is None or c.open_time > last_open]
            if not fresh:
                break
            out.extend(fresh)
            last_open = fresh[-1].open_time
            cursor = last_open + step
            if len(page) < self._page_limit:
                break  # reached the end of available data
        self.log.info(
            "history_loaded",
            symbol=symbol,
            timeframe=timeframe.value,
            candles=len(out),
            start=start.isoformat(),
            end=end.isoformat(),
        )
        return out

    # ------------------------------------------------------------------ dataframe

    @staticmethod
    def to_dataframe(candles: Sequence[Candle]) -> pd.DataFrame:
        """Convert candles to a DataFrame indexed by open time."""
        if not candles:
            return pd.DataFrame(columns=OHLCV_COLUMNS).set_index("open_time")
        rows = [
            {
                "open_time": c.open_time,
                "open": float(c.open),
                "high": float(c.high),
                "low": float(c.low),
                "close": float(c.close),
                "volume": float(c.volume),
                "quote_volume": float(c.quote_volume),
                "trades": c.trades,
            }
            for c in candles
        ]
        df = pd.DataFrame(rows)
        df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
        return df.set_index("open_time").sort_index()

    @staticmethod
    def from_dataframe(df: pd.DataFrame, symbol: str, timeframe: Timeframe) -> list[Candle]:
        """Reconstruct candles from a cached DataFrame."""
        candles: list[Candle] = []
        step = timedelta(seconds=timeframe.seconds)
        for open_time, row in df.iterrows():
            ot = open_time.to_pydatetime()
            candles.append(
                Candle(
                    symbol=symbol,
                    timeframe=timeframe,
                    open_time=ot,
                    close_time=ot + step - timedelta(milliseconds=1),
                    open=to_decimal(row["open"]),
                    high=to_decimal(row["high"]),
                    low=to_decimal(row["low"]),
                    close=to_decimal(row["close"]),
                    volume=to_decimal(row["volume"]),
                    quote_volume=to_decimal(row.get("quote_volume", 0)),
                    trades=int(row.get("trades", 0)),
                    is_closed=True,
                )
            )
        return candles

    # ------------------------------------------------------------------ cache

    def _cache_path(self, symbol: str, timeframe: Timeframe) -> Path:
        return self._cache_dir / f"{symbol}_{timeframe.value}.parquet"

    def _read_cache(self, symbol: str, timeframe: Timeframe) -> list[Candle] | None:
        path = self._cache_path(symbol, timeframe)
        if not path.exists():
            return None
        try:
            df = pd.read_parquet(path)
        except Exception as exc:  # noqa: BLE001 - corrupt cache is non-fatal
            self.log.warning("cache_read_failed", path=str(path), error=str(exc))
            return None
        return self.from_dataframe(df, symbol, timeframe)

    def _write_cache(self, symbol: str, timeframe: Timeframe, candles: list[Candle]) -> None:
        if not candles:
            return
        path = self._cache_path(symbol, timeframe)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.to_dataframe(candles).to_parquet(path)
        except Exception as exc:  # noqa: BLE001 - missing pyarrow etc. is non-fatal
            self.log.warning("cache_write_failed", path=str(path), error=str(exc))

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _covers(candles: list[Candle], start: datetime, end: datetime) -> bool:
        return bool(candles) and candles[0].open_time <= start and candles[-1].open_time >= end - timedelta(days=1)

    @staticmethod
    def _slice(candles: list[Candle], start: datetime, end: datetime) -> list[Candle]:
        return [c for c in candles if start <= c.open_time <= end]

    @staticmethod
    def _merge_cached(cached: list[Candle] | None, fresh: list[Candle]) -> list[Candle]:
        """Merge cached and freshly-fetched candles, de-duplicated by open time."""
        by_time: dict[datetime, Candle] = {}
        for candle in (*(cached or []), *fresh):
            by_time[candle.open_time] = candle
        return [by_time[t] for t in sorted(by_time)]


__all__ = ["HistoricalDataLoader", "OHLCV_COLUMNS"]
