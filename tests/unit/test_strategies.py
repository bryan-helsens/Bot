"""Unit tests for the strategy framework and a sample of built-in strategies."""

from __future__ import annotations

import numpy as np
import pytest

from quantbot.core.constants import Side, Timeframe
from quantbot.core.exceptions import StrategyConfigError
from quantbot.strategies.base import StrategyContext
from quantbot.strategies.registry import get_registry

pytestmark = pytest.mark.unit


def _ctx(closes: list[float], make_candle) -> StrategyContext:
    arr = np.array(closes, dtype=float)
    candle = make_candle(0, float(arr[-1]))
    return StrategyContext(
        symbol="BTCUSDT", timeframe=Timeframe.H1, candle=candle,
        opens=arr, highs=arr + 1, lows=arr - 1, closes=arr,
        volumes=np.full(arr.size, 10.0),
    )


def test_all_builtin_strategies_register() -> None:
    registry = get_registry()
    registry.load_builtins()
    expected = {
        "EMACrossoverStrategy", "SMACrossoverStrategy", "RSIStrategy", "MACDStrategy",
        "BollingerBandsStrategy", "VWAPStrategy", "IchimokuStrategy",
        "SupportResistanceStrategy", "BreakoutStrategy", "MeanReversionStrategy",
        "TrendFollowingStrategy", "MomentumStrategy", "ScalpingStrategy",
        "GridTradingStrategy", "DCAStrategy",
    }
    assert expected <= set(registry.names())


def test_strategy_param_validation_rejects_unknown() -> None:
    registry = get_registry()
    registry.load_builtins()
    with pytest.raises(StrategyConfigError):
        registry.create("RSIStrategy", params={"bogus": 1})


async def test_ema_crossover_detects_golden_cross(make_candle) -> None:
    registry = get_registry()
    registry.load_builtins()
    strat = registry.create(
        "EMACrossoverStrategy", symbols=["BTCUSDT"], timeframes=[Timeframe.H1],
        params={"fast_period": 3, "slow_period": 6},
    )
    closes = list(np.linspace(100, 80, 15)) + list(np.linspace(80, 140, 15))
    found = None
    for i in range(strat.min_candles, len(closes) + 1):
        signal = await strat.on_candle(_ctx(closes[:i], make_candle))
        if signal is not None and signal.side is Side.BUY:
            found = signal
            break
    assert found is not None


async def test_dca_respects_max_entries(make_candle) -> None:
    registry = get_registry()
    registry.load_builtins()
    strat = registry.create(
        "DCAStrategy", symbols=["BTCUSDT"], timeframes=[Timeframe.H1],
        params={"mode": "interval", "interval_candles": 2, "max_entries": 3},
    )
    prices = [100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 90]
    signals = []
    for i in range(1, len(prices)):
        signal = await strat.on_candle(_ctx(prices[: i + 1], make_candle))
        if signal is not None:
            signals.append(signal)
    assert len(signals) == 3  # hard cap, no martingale beyond
