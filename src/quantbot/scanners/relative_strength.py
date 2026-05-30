"""Relative-strength scanner — ranks symbols vs a benchmark.

Computes each symbol's return over the lookback relative to a benchmark's return
(typically BTCUSDT). A relative-strength ratio above 1 means the symbol is
outperforming the benchmark; below 1, underperforming. Useful for rotating into
leaders (momentum) or fading laggards.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from quantbot.core.constants import Timeframe
from quantbot.core.logging import LoggerMixin
from quantbot.scanners.base import OHLCV, BaseScanner, ScanResult


class RelativeStrengthScanner(LoggerMixin):
    """Rank symbols by performance relative to a benchmark symbol."""

    def __init__(
        self,
        source,
        *,
        benchmark: str = "BTCUSDT",
        timeframe: Timeframe = Timeframe.H1,
        lookback: int = 100,
    ) -> None:
        self._source = source
        self._benchmark = benchmark
        self._timeframe = timeframe
        self._lookback = lookback

    async def scan(
        self, symbols: Sequence[str], *, top: int | None = None, min_ratio: float | None = None
    ) -> list[ScanResult]:
        bench_return = await self._symbol_return(self._benchmark)
        if bench_return is None:
            raise ValueError(f"Could not compute benchmark return for {self._benchmark}")

        results: list[ScanResult] = []
        for symbol in symbols:
            if symbol == self._benchmark:
                continue
            sym_return = await self._symbol_return(symbol)
            if sym_return is None:
                continue
            # Relative strength as ratio of growth factors (robust to sign).
            ratio = (1.0 + sym_return) / (1.0 + bench_return) if bench_return != -1 else 0.0
            results.append(
                ScanResult(
                    symbol=symbol,
                    score=ratio,
                    metrics={
                        "symbol_return_pct": round(sym_return * 100, 3),
                        "benchmark_return_pct": round(bench_return * 100, 3),
                        "rs_ratio": round(ratio, 4),
                    },
                )
            )
        results.sort(key=lambda r: r.score, reverse=True)
        if min_ratio is not None:
            results = [r for r in results if r.score >= min_ratio]
        self.log.info("relative_strength_complete", benchmark=self._benchmark, found=len(results))
        return results[:top] if top else results

    async def _symbol_return(self, symbol: str) -> float | None:
        candles = await self._source.get_klines(symbol, self._timeframe, limit=self._lookback)
        if len(candles) < 2:
            return None
        first = float(candles[0].close)
        last = float(candles[-1].close)
        if first <= 0:
            return None
        return (last - first) / first


__all__ = ["RelativeStrengthScanner"]
