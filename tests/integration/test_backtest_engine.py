"""Integration test: full backtest through the live decision path."""

from __future__ import annotations

import pytest

from quantbot.backtest.engine import BacktestEngine
from quantbot.core.constants import Timeframe
from quantbot.strategies.registry import get_registry

pytestmark = pytest.mark.integration


def test_backtest_runs_end_to_end(settings, trending_candles) -> None:
    registry = get_registry()
    registry.load_builtins()
    strat = registry.create(
        "EMACrossoverStrategy", symbols=["BTCUSDT"], timeframes=[Timeframe.H1],
        params={"fast_period": 5, "slow_period": 15},
    )
    engine = BacktestEngine(settings=settings, strategies=[strat], warmup=20)
    result = engine.run(trending_candles)

    assert result.bars == len(trending_candles)
    assert len(result.equity_curve) == len(trending_candles) - 20 + 1
    assert -1.0 <= result.metrics.max_drawdown <= 1.0
    summary = result.summary()
    for key in ("sharpe_ratio", "profit_factor", "win_rate", "expectancy", "cagr"):
        assert key in summary


def test_backtest_requires_minimum_candles(settings, trending_candles) -> None:
    registry = get_registry()
    registry.load_builtins()
    strat = registry.create("EMACrossoverStrategy", symbols=["BTCUSDT"], timeframes=[Timeframe.H1])
    engine = BacktestEngine(settings=settings, strategies=[strat], warmup=20)
    with pytest.raises(ValueError):
        engine.run(trending_candles[:10])
