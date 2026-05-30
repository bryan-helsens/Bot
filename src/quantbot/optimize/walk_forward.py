"""Walk-forward analysis — the primary anti-overfitting validation.

Splits the historical series into consecutive windows, each with an *in-sample*
(IS) segment used to optimise parameters and an *out-of-sample* (OOS) segment
used to evaluate those parameters on unseen data. Parameters that only work
in-sample (curve-fitted) collapse out-of-sample, so the aggregated OOS
performance is a far more honest estimate of live expectancy than a single
optimisation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from quantbot.backtest.engine import BacktestEngine
from quantbot.core.logging import LoggerMixin
from quantbot.optimize.base import (
    Optimizer,
    SearchSpace,
    make_backtest_objective,
)


@dataclass(slots=True)
class WalkForwardWindow:
    """Result for one walk-forward window."""

    index: int
    is_range: tuple[str, str]
    oos_range: tuple[str, str]
    best_params: dict[str, Any]
    is_score: float
    oos_score: float
    oos_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WalkForwardResult:
    """Aggregated walk-forward analysis result."""

    windows: list[WalkForwardWindow]
    metric: str

    @property
    def avg_oos_score(self) -> float:
        if not self.windows:
            return 0.0
        return sum(w.oos_score for w in self.windows) / len(self.windows)

    @property
    def avg_is_score(self) -> float:
        if not self.windows:
            return 0.0
        return sum(w.is_score for w in self.windows) / len(self.windows)

    @property
    def efficiency(self) -> float:
        """OOS/IS score ratio — closer to 1 means less overfitting."""
        if self.avg_is_score == 0:
            return 0.0
        return self.avg_oos_score / self.avg_is_score

    @property
    def robust(self) -> bool:
        """Heuristic: positive average OOS score and efficiency above 0.5."""
        return self.avg_oos_score > 0 and self.efficiency >= 0.5


class WalkForwardAnalysis(LoggerMixin):
    """Run rolling in-sample/out-of-sample optimisation over a candle series."""

    def __init__(
        self,
        *,
        strategy_cls: type,
        settings: Any,
        space: SearchSpace,
        optimizer: Optimizer,
        metric: str = "sharpe_ratio",
        n_splits: int = 4,
        is_ratio: float = 0.7,
        warmup: int = 50,
        symbols: list[str] | None = None,
        timeframes: list | None = None,
    ) -> None:
        self._strategy_cls = strategy_cls
        self._settings = settings
        self._space = space
        self._optimizer = optimizer
        self._metric = metric
        self._n_splits = n_splits
        self._is_ratio = is_ratio
        self._warmup = warmup
        self._symbols = symbols
        self._timeframes = timeframes

    def run(self, candles: list) -> WalkForwardResult:
        """Execute the walk-forward analysis over *candles*."""
        windows = self._make_windows(len(candles))
        results: list[WalkForwardWindow] = []
        for idx, (is_slice, oos_slice) in enumerate(windows):
            is_candles = candles[is_slice[0] : is_slice[1]]
            oos_candles = candles[oos_slice[0] : oos_slice[1]]
            if len(is_candles) < self._warmup + 2 or len(oos_candles) < self._warmup + 2:
                continue

            # Optimise on the in-sample segment.
            is_objective = make_backtest_objective(
                strategy_cls=self._strategy_cls, candles=is_candles, settings=self._settings,
                metric=self._metric, symbols=self._symbols, timeframes=self._timeframes,
                warmup=self._warmup,
            )
            opt = self._optimizer.optimize(is_objective, self._space, metric=self._metric)

            # Evaluate the winning params out-of-sample.
            oos_summary, oos_score = self._evaluate(oos_candles, opt.best_params)
            results.append(
                WalkForwardWindow(
                    index=idx,
                    is_range=(is_candles[0].open_time.isoformat(), is_candles[-1].close_time.isoformat()),
                    oos_range=(oos_candles[0].open_time.isoformat(), oos_candles[-1].close_time.isoformat()),
                    best_params=opt.best_params,
                    is_score=opt.best_score,
                    oos_score=oos_score,
                    oos_summary=oos_summary,
                )
            )
            self.log.info(
                "walk_forward_window", index=idx, is_score=round(opt.best_score, 3),
                oos_score=round(oos_score, 3),
            )
        return WalkForwardResult(windows=results, metric=self._metric)

    def _evaluate(self, candles: list, params: dict[str, Any]) -> tuple[dict[str, Any], float]:
        strategy = self._strategy_cls(
            symbols=self._symbols, timeframes=self._timeframes, params=params
        )
        engine = BacktestEngine(settings=self._settings, strategies=[strategy], warmup=self._warmup)
        result = engine.run(candles)
        summary = result.summary()
        return summary, float(summary.get(self._metric, 0.0))

    def _make_windows(self, n: int) -> list[tuple[tuple[int, int], tuple[int, int]]]:
        """Compute rolling (IS, OOS) index ranges across the series."""
        windows: list[tuple[tuple[int, int], tuple[int, int]]] = []
        segment = n // (self._n_splits + 1)
        if segment < self._warmup + 2:
            # Fall back to anchored splits if data is short.
            segment = max(self._warmup + 2, n // max(2, self._n_splits))
        is_len = int(segment * (1 + self._is_ratio))
        for i in range(self._n_splits):
            start = i * segment
            is_end = min(start + is_len, n)
            oos_end = min(is_end + segment, n)
            if oos_end <= is_end:
                break
            windows.append(((start, is_end), (is_end, oos_end)))
        return windows


__all__ = ["WalkForwardAnalysis", "WalkForwardResult", "WalkForwardWindow"]
