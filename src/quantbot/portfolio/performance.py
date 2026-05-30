"""Performance tracking and metrics.

:class:`PerformanceTracker` accumulates realised trades and an equity series and
computes the full suite of performance statistics used in the dashboard,
backtest reports and strategy-performance persistence:

    Net Profit · Profit Factor · Win Rate · Average Trade · Expectancy ·
    Sharpe · Sortino · Calmar · Maximum Drawdown · CAGR · Recovery Factor.

The metric functions are also exposed standalone so the backtester can reuse
them without instantiating the tracker.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal

from quantbot.core.constants import DEFAULT_RISK_FREE_RATE, TRADING_DAYS_PER_YEAR
from quantbot.core.models import Trade


@dataclass(slots=True)
class PerformanceMetrics:
    """A computed snapshot of performance statistics."""

    net_profit: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    profit_factor: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    average_trade: float = 0.0
    average_win: float = 0.0
    average_loss: float = 0.0
    expectancy: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    cagr: float = 0.0
    recovery_factor: float = 0.0
    total_fees: float = 0.0

    def as_dict(self) -> dict[str, float | int]:
        return {
            "net_profit": round(self.net_profit, 8),
            "gross_profit": round(self.gross_profit, 8),
            "gross_loss": round(self.gross_loss, 8),
            "profit_factor": round(self.profit_factor, 4),
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": round(self.win_rate, 4),
            "average_trade": round(self.average_trade, 8),
            "average_win": round(self.average_win, 8),
            "average_loss": round(self.average_loss, 8),
            "expectancy": round(self.expectancy, 8),
            "largest_win": round(self.largest_win, 8),
            "largest_loss": round(self.largest_loss, 8),
            "max_drawdown": round(self.max_drawdown, 6),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "sortino_ratio": round(self.sortino_ratio, 4),
            "calmar_ratio": round(self.calmar_ratio, 4),
            "cagr": round(self.cagr, 6),
            "recovery_factor": round(self.recovery_factor, 4),
            "total_fees": round(self.total_fees, 8),
        }


# ---------------------------------------------------------------------------
# Standalone metric functions
# ---------------------------------------------------------------------------


def max_drawdown(equity_curve: list[float]) -> float:
    """Maximum peak-to-trough drawdown of an equity curve (positive fraction)."""
    peak = -math.inf
    max_dd = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            dd = (peak - value) / peak
            max_dd = max(max_dd, dd)
    return max_dd


def sharpe_ratio(
    returns: list[float], *, risk_free: float = DEFAULT_RISK_FREE_RATE,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> float:
    """Annualised Sharpe ratio of a per-period return series."""
    if len(returns) < 2:
        return 0.0
    excess = [r - risk_free / periods_per_year for r in returns]
    mean = sum(excess) / len(excess)
    variance = sum((r - mean) ** 2 for r in excess) / (len(excess) - 1)
    std = math.sqrt(variance)
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(periods_per_year)


def sortino_ratio(
    returns: list[float], *, risk_free: float = DEFAULT_RISK_FREE_RATE,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> float:
    """Annualised Sortino ratio (downside-deviation denominator)."""
    if len(returns) < 2:
        return 0.0
    excess = [r - risk_free / periods_per_year for r in returns]
    mean = sum(excess) / len(excess)
    downside = [min(0.0, r) ** 2 for r in excess]
    downside_dev = math.sqrt(sum(downside) / len(downside))
    if downside_dev == 0:
        return 0.0
    return (mean / downside_dev) * math.sqrt(periods_per_year)


def cagr(equity_curve: list[float], *, periods: int, periods_per_year: int) -> float:
    """Compound annual growth rate from first to last equity value."""
    if len(equity_curve) < 2 or equity_curve[0] <= 0 or periods <= 0:
        return 0.0
    years = periods / periods_per_year
    if years <= 0:
        return 0.0
    ratio = equity_curve[-1] / equity_curve[0]
    if ratio <= 0:
        return -1.0
    return ratio ** (1 / years) - 1.0


def calmar_ratio(cagr_value: float, max_dd: float) -> float:
    """Calmar ratio = CAGR / max drawdown."""
    if max_dd == 0:
        return 0.0
    return cagr_value / max_dd


def profit_factor(gross_profit: float, gross_loss: float) -> float:
    """Profit factor = gross profit / gross loss (abs)."""
    loss = abs(gross_loss)
    if loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / loss


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------


class PerformanceTracker:
    """Accumulate trades and an equity series; compute full metrics on demand."""

    def __init__(
        self,
        *,
        starting_equity: float,
        periods_per_year: int = TRADING_DAYS_PER_YEAR,
        risk_free: float = DEFAULT_RISK_FREE_RATE,
    ) -> None:
        self._start = starting_equity
        self._periods_per_year = periods_per_year
        self._risk_free = risk_free
        self._trades: list[Trade] = []
        self._equity_curve: list[float] = [starting_equity]
        self._returns: list[float] = []

    def add_trade(self, trade: Trade) -> None:
        self._trades.append(trade)

    def record_equity(self, equity: float) -> None:
        """Append an equity observation and derive the period return."""
        prev = self._equity_curve[-1]
        self._equity_curve.append(equity)
        if prev > 0:
            self._returns.append((equity - prev) / prev)

    @property
    def trades(self) -> list[Trade]:
        return self._trades

    @property
    def equity_curve(self) -> list[float]:
        return self._equity_curve

    def compute(self) -> PerformanceMetrics:
        """Compute the full metric suite from the accumulated data."""
        m = PerformanceMetrics()
        pnls = [float(t.net_pnl) for t in self._trades]
        m.total_trades = len(pnls)
        m.total_fees = sum(float(t.fees) for t in self._trades)
        if not pnls:
            m.max_drawdown = max_drawdown(self._equity_curve)
            return m

        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        m.net_profit = sum(pnls)
        m.gross_profit = sum(wins)
        m.gross_loss = sum(losses)
        m.profit_factor = profit_factor(m.gross_profit, m.gross_loss)
        m.winning_trades = len(wins)
        m.losing_trades = len(losses)
        m.win_rate = len(wins) / len(pnls)
        m.average_trade = m.net_profit / len(pnls)
        m.average_win = (sum(wins) / len(wins)) if wins else 0.0
        m.average_loss = (sum(losses) / len(losses)) if losses else 0.0
        m.expectancy = m.win_rate * m.average_win + (1 - m.win_rate) * m.average_loss
        m.largest_win = max(wins, default=0.0)
        m.largest_loss = min(losses, default=0.0)

        m.max_drawdown = max_drawdown(self._equity_curve)
        m.sharpe_ratio = sharpe_ratio(
            self._returns, risk_free=self._risk_free, periods_per_year=self._periods_per_year
        )
        m.sortino_ratio = sortino_ratio(
            self._returns, risk_free=self._risk_free, periods_per_year=self._periods_per_year
        )
        m.cagr = cagr(
            self._equity_curve,
            periods=max(1, len(self._equity_curve) - 1),
            periods_per_year=self._periods_per_year,
        )
        m.calmar_ratio = calmar_ratio(m.cagr, m.max_drawdown)
        m.recovery_factor = (m.net_profit / (m.max_drawdown * self._start)) if m.max_drawdown > 0 else 0.0
        return m


__all__ = [
    "PerformanceMetrics",
    "PerformanceTracker",
    "cagr",
    "calmar_ratio",
    "max_drawdown",
    "profit_factor",
    "sharpe_ratio",
    "sortino_ratio",
]
