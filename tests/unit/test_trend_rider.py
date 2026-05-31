"""Unit tests for the TrendRiderStrategy (long-only, regime-filtered)."""

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
    return registry.create(
        "TrendRiderStrategy", symbols=["BTCUSDT"], timeframes=[Timeframe.D1],
        params={"fast_period": 5, "slow_period": 15, "regime_period": 30},
    )


def test_registers() -> None:
    assert "TrendRiderStrategy" in get_registry().names()


async def test_long_while_uptrend_holds() -> None:
    """Emits BUY on every bar the uptrend state holds (ride-the-trend)."""
    strat = _strategy()
    closes = [100.0] * 35 + list(np.linspace(100, 200, 40))
    buys = 0
    for i in range(strat.min_candles, len(closes) + 1):
        sig = await strat.on_candle(_ctx(closes[:i]))
        if sig is not None and sig.side is Side.BUY:
            buys += 1
    assert buys >= 1


async def test_no_long_in_downtrend() -> None:
    """In a sustained downtrend (price below regime EMA) it never goes long."""
    strat = _strategy()
    closes = [200.0] * 35 + list(np.linspace(200, 100, 40))
    buys = 0
    for i in range(strat.min_candles, len(closes) + 1):
        sig = await strat.on_candle(_ctx(closes[:i]))
        if sig is not None and sig.side is Side.BUY:
            buys += 1
    assert buys == 0


async def test_exits_when_trend_breaks() -> None:
    strat = _strategy()
    closes = [100.0] * 35 + list(np.linspace(100, 200, 30)) + list(np.linspace(200, 120, 30))
    sides = []
    for i in range(strat.min_candles, len(closes) + 1):
        sig = await strat.on_candle(_ctx(closes[:i]))
        if sig is not None:
            sides.append(sig.side)
    assert Side.BUY in sides and Side.SELL in sides
