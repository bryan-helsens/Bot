"""RSI dip-buyer trend filter: only buy oversold dips in an up/sideways regime,
never catch a falling knife in a downtrend."""

from __future__ import annotations

import numpy as np
import pytest

from quantbot.core.constants import Side, Timeframe
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


def _rsi() :
    registry = get_registry()
    registry.load_builtins()
    return registry


def test_trend_ok_blocks_falling_sma_allows_rising(make_candle) -> None:
    reg = _rsi()
    strat = reg.create("RSIStrategy", params={"trend_filter": True, "trend_period": 50})
    falling = list(range(200, 0, -1))  # SMA strictly falling -> downtrend
    assert strat._trend_ok(_ctx(falling, make_candle)) is False
    rising = list(range(1, 201))  # SMA strictly rising -> uptrend
    assert strat._trend_ok(_ctx(rising, make_candle)) is True


def test_trend_ok_allows_flat_sideways(make_candle) -> None:
    reg = _rsi()
    strat = reg.create("RSIStrategy", params={"trend_filter": True, "trend_period": 50})
    flat = [100.0] * 120  # dead-flat SMA (not falling) -> mean-reversion allowed
    assert strat._trend_ok(_ctx(flat, make_candle)) is True


def test_trend_filter_off_always_allows(make_candle) -> None:
    reg = _rsi()
    strat = reg.create("RSIStrategy", params={"trend_filter": False})
    falling = list(range(200, 0, -1))
    assert strat._trend_ok(_ctx(falling, make_candle)) is True


def test_min_candles_accounts_for_trend_period() -> None:
    reg = _rsi()
    on = reg.create("RSIStrategy", params={"trend_filter": True, "trend_period": 50})
    off = reg.create("RSIStrategy", params={"trend_filter": False, "period": 14})
    assert on.min_candles >= 61  # trend_period + slope lookback + 1
    assert off.min_candles == 17


async def test_no_buy_in_downtrend_but_buys_in_uptrend(make_candle) -> None:
    """A sawtooth dip-and-bounce produces RSI oversold crosses; the filter must
    suppress them in a downtrend and allow them in an uptrend."""
    reg = _rsi()
    osc = 5.0 * np.sin(np.arange(120) * 1.1)

    async def _count_buys(closes, *, trend_filter):
        strat = reg.create(
            "RSIStrategy",
            params={"oversold": 35, "trend_filter": trend_filter, "trend_period": 50},
        )
        buys = 0
        for i in range(strat.min_candles, len(closes) + 1):
            sig = await strat.on_candle(_ctx(list(closes[:i]), make_candle))
            if sig is not None and sig.side is Side.BUY:
                buys += 1
        return buys

    downtrend = np.linspace(200, 100, 120) + osc
    # Uptrend then a deep, sharp pullback that reaches oversold while the slow SMA
    # is still rising — the legitimate "buy the dip in an uptrend" case.
    uptrend = list(np.linspace(100, 240, 120)) + [
        238, 232, 226, 221, 217, 214, 212, 213, 216, 220, 225, 231, 238, 245,
    ]

    # Sanity: with the filter OFF the downtrend DOES produce oversold-cross buys,
    # proving the crosses exist — so the filter suppressing them is meaningful.
    assert await _count_buys(downtrend, trend_filter=False) >= 1
    assert await _count_buys(downtrend, trend_filter=True) == 0
    assert await _count_buys(uptrend, trend_filter=True) >= 1
