"""Unit tests for performance/backtest metrics."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantbot.core.constants import PositionSide
from quantbot.core.models import Trade
from quantbot.portfolio.performance import (
    PerformanceTracker,
    calmar_ratio,
    cagr,
    max_drawdown,
    profit_factor,
    sharpe_ratio,
)

pytestmark = pytest.mark.unit


def test_max_drawdown() -> None:
    assert max_drawdown([100, 120, 90, 110, 80]) == pytest.approx(40 / 120)


def test_profit_factor() -> None:
    assert profit_factor(300, -100) == pytest.approx(3.0)
    assert profit_factor(0, 0) == 0.0


def test_cagr_and_calmar() -> None:
    c = cagr([10000, 12100], periods=365, periods_per_year=365)
    assert c == pytest.approx(0.21, abs=1e-3)
    assert calmar_ratio(0.2, 0.1) == pytest.approx(2.0)


def test_sharpe_nonzero() -> None:
    assert sharpe_ratio([0.01, 0.02, -0.01, 0.015, 0.005]) != 0.0


def _trade(pnl: float) -> Trade:
    entry = Decimal("100")
    return Trade(
        position_id="p", symbol="X", side=PositionSide.LONG, quantity=Decimal("1"),
        entry_price=entry, exit_price=entry + Decimal(str(pnl)), fees=Decimal("0"),
        opened_at=datetime.now(UTC),
    )


def test_performance_tracker_aggregates() -> None:
    tracker = PerformanceTracker(starting_equity=10000)
    equity = 10000.0
    for pnl in (50, -30, 40, -20, 60):
        tracker.add_trade(_trade(pnl))
        equity += pnl
        tracker.record_equity(equity)
    metrics = tracker.compute()
    assert metrics.total_trades == 5
    assert metrics.winning_trades == 3
    assert metrics.win_rate == pytest.approx(0.6)
    assert metrics.net_profit == pytest.approx(100.0)
    assert metrics.profit_factor > 1
