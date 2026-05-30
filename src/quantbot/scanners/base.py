"""Scanner framework.

A scanner sweeps a universe of symbols, fetches recent candles for each, scores
them by a criterion and returns a ranked list of :class:`ScanResult`. Concrete
scanners only implement :meth:`BaseScanner.score`, which receives the OHLCV
arrays for one symbol and returns a score (or ``None`` to exclude it). The base
class handles concurrent fetching (bounded), error isolation and ranking.
"""

from __future__ import annotations

import abc
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from quantbot.core.constants import Timeframe
from quantbot.core.logging import LoggerMixin
from quantbot.core.models import Candle
from quantbot.core.utils import gather_limited

FloatArray = npt.NDArray[np.float64]


@dataclass(slots=True)
class OHLCV:
    """Plain numpy OHLCV bundle passed to scanners."""

    symbol: str
    opens: FloatArray
    highs: FloatArray
    lows: FloatArray
    closes: FloatArray
    volumes: FloatArray

    def __len__(self) -> int:
        return int(self.closes.size)


@dataclass(slots=True)
class ScanResult:
    """One scored symbol."""

    symbol: str
    score: float
    metrics: dict[str, float | str] = field(default_factory=dict)


class _KlineSource:
    """Structural type: anything with an async ``get_klines``."""

    async def get_klines(self, symbol: str, timeframe: Timeframe, *, limit: int = 500) -> list[Candle]:
        raise NotImplementedError


class BaseScanner(LoggerMixin, abc.ABC):
    """Base class for market scanners."""

    #: Higher score = better when ``True``; lower is better when ``False``.
    higher_is_better: bool = True

    def __init__(
        self,
        source: _KlineSource,
        *,
        timeframe: Timeframe = Timeframe.H1,
        lookback: int = 100,
        concurrency: int = 10,
    ) -> None:
        self._source = source
        self._timeframe = timeframe
        self._lookback = lookback
        self._concurrency = concurrency

    @abc.abstractmethod
    def score(self, data: OHLCV) -> ScanResult | None:
        """Score one symbol's OHLCV, or return ``None`` to exclude it."""

    async def scan(
        self, symbols: Sequence[str], *, top: int | None = None, min_score: float | None = None
    ) -> list[ScanResult]:
        """Scan *symbols* and return ranked results (best first)."""
        fetches = [self._fetch(symbol) for symbol in symbols]
        datasets = await gather_limited(*fetches, limit=self._concurrency, return_exceptions=True)

        results: list[ScanResult] = []
        for symbol, data in zip(symbols, datasets, strict=True):
            if isinstance(data, BaseException) or data is None:
                continue
            try:
                result = self.score(data)
            except Exception as exc:  # noqa: BLE001 - one bad symbol must not break the scan
                self.log.warning("scan_error", symbol=symbol, error=str(exc))
                continue
            if result is not None:
                results.append(result)

        results.sort(key=lambda r: r.score, reverse=self.higher_is_better)
        if min_score is not None:
            cmp = (lambda s: s >= min_score) if self.higher_is_better else (lambda s: s <= min_score)
            results = [r for r in results if cmp(r.score)]
        self.log.info("scan_complete", scanner=type(self).__name__, found=len(results))
        return results[:top] if top else results

    async def _fetch(self, symbol: str) -> OHLCV | None:
        candles = await self._source.get_klines(symbol, self._timeframe, limit=self._lookback)
        if len(candles) < 2:
            return None
        return OHLCV(
            symbol=symbol,
            opens=np.array([float(c.open) for c in candles], dtype=np.float64),
            highs=np.array([float(c.high) for c in candles], dtype=np.float64),
            lows=np.array([float(c.low) for c in candles], dtype=np.float64),
            closes=np.array([float(c.close) for c in candles], dtype=np.float64),
            volumes=np.array([float(c.volume) for c in candles], dtype=np.float64),
        )


__all__ = ["BaseScanner", "OHLCV", "ScanResult"]
