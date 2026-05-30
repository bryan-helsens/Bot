"""Backtest result aggregation and the full metric suite.

Reuses the metric primitives from :mod:`quantbot.portfolio.performance` (so live
and backtest report identical numbers) and packages them into a
:class:`BacktestResult` that the engine returns and the report renders.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from quantbot.core.models import Trade
from quantbot.portfolio.performance import (
    PerformanceMetrics,
    PerformanceTracker,
)


@dataclass(slots=True)
class BacktestResult:
    """The complete output of a backtest run."""

    metrics: PerformanceMetrics
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    timestamps: list[str] = field(default_factory=list)
    initial_capital: float = 0.0
    final_equity: float = 0.0
    symbol: str = ""
    strategy: str = ""
    start: str = ""
    end: str = ""
    bars: int = 0

    @property
    def total_return_pct(self) -> float:
        if self.initial_capital <= 0:
            return 0.0
        return (self.final_equity - self.initial_capital) / self.initial_capital

    def summary(self) -> dict[str, object]:
        """A flat dict summarising the run (for logging / JSON export)."""
        return {
            "strategy": self.strategy,
            "symbol": self.symbol,
            "start": self.start,
            "end": self.end,
            "bars": self.bars,
            "initial_capital": round(self.initial_capital, 2),
            "final_equity": round(self.final_equity, 2),
            "total_return_pct": round(self.total_return_pct, 4),
            **self.metrics.as_dict(),
        }

    def headline(self) -> str:
        """A one-line human-readable summary."""
        m = self.metrics
        return (
            f"{self.strategy} on {self.symbol}: "
            f"return={self.total_return_pct:.2%} "
            f"trades={m.total_trades} winrate={m.win_rate:.1%} "
            f"PF={m.profit_factor:.2f} Sharpe={m.sharpe_ratio:.2f} "
            f"MaxDD={m.max_drawdown:.2%}"
        )


def compute_result(
    *,
    trades: list[Trade],
    equity_curve: list[float],
    timestamps: list[str],
    initial_capital: float,
    periods_per_year: int,
    symbol: str = "",
    strategy: str = "",
    start: str = "",
    end: str = "",
    bars: int = 0,
) -> BacktestResult:
    """Build a :class:`BacktestResult` from raw trades and the equity curve."""
    tracker = PerformanceTracker(
        starting_equity=initial_capital, periods_per_year=periods_per_year
    )
    for trade in trades:
        tracker.add_trade(trade)
    # Feed the equity curve so drawdown/Sharpe/CAGR use the real path.
    for equity in equity_curve[1:]:
        tracker.record_equity(equity)
    metrics = tracker.compute()
    final_equity = equity_curve[-1] if equity_curve else initial_capital
    return BacktestResult(
        metrics=metrics,
        trades=trades,
        equity_curve=equity_curve,
        timestamps=timestamps,
        initial_capital=initial_capital,
        final_equity=final_equity,
        symbol=symbol,
        strategy=strategy,
        start=start,
        end=end,
        bars=bars,
    )


__all__ = ["BacktestResult", "compute_result"]
