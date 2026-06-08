"""Unit tests for the AdaptiveStrategy (regime-routed)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import numpy as np
import pytest

from quantbot.core.constants import Side, Timeframe
from quantbot.core.models import Candle
from quantbot.strategies.base import StrategyContext
from quantbot.strategies.registry import get_registry

pytestmark = pytest.mark.unit


def _ctx(closes: list[float]) -> StrategyContext:
    arr = np.array(closes, dtype=float)
    last = float(arr[-1])
    candle = Candle(
        symbol="BTCUSDT", timeframe=Timeframe.D1,
        open_time=datetime(2024, 1, 1, tzinfo=UTC), close_time=datetime(2024, 1, 1, tzinfo=UTC),
        open=Decimal(str(last)), high=Decimal(str(last + 1)), low=Decimal(str(last - 1)),
        close=Decimal(str(last)), volume=Decimal("1000"),
    )
    return StrategyContext(
        symbol="BTCUSDT", timeframe=Timeframe.D1, candle=candle,
        opens=arr, highs=arr + 1, lows=arr - 1, closes=arr, volumes=np.full(arr.size, 1000.0),
    )


def _strategy():
    registry = get_registry()
    registry.load_builtins()
    return registry.create("AdaptiveStrategy", symbols=["BTCUSDT"], timeframes=[Timeframe.D1])


def test_registers() -> None:
    registry = get_registry()
    registry.load_builtins()
    assert "AdaptiveStrategy" in registry.names()


async def test_goes_long_in_strong_uptrend() -> None:
    strat = _strategy()
    rng = np.random.RandomState(1)
    # noisy but clear up-trend -> trend leg should buy at some point
    closes = list(100 + np.cumsum(np.abs(rng.randn(160)) * 0.4 + 0.4))
    buys = 0
    for i in range(strat.min_candles, len(closes) + 1):
        sig = await strat.on_candle(_ctx(closes[:i]))
        if sig is not None and sig.side is Side.BUY:
            buys += 1
    assert buys >= 1


async def test_no_long_in_downtrend() -> None:
    strat = _strategy()
    closes = list(np.linspace(200, 100, 160))
    buys = 0
    for i in range(strat.min_candles, len(closes) + 1):
        sig = await strat.on_candle(_ctx(closes[:i]))
        if sig is not None and sig.side is Side.BUY:
            buys += 1
    assert buys == 0


async def test_runs_without_error_on_choppy() -> None:
    """In a ranging market the mean-reversion leg must execute without crashing."""
    strat = _strategy()
    rng = np.random.RandomState(2)
    closes = list(100 + np.cumsum(rng.randn(160) * 0.5))
    fired = 0
    for i in range(strat.min_candles, len(closes) + 1):
        sig = await strat.on_candle(_ctx(closes[:i]))
        if sig is not None:
            fired += 1
    assert fired >= 0  # no exception; signals are optional
