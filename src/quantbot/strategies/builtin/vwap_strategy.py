"""VWAP reversion / trend strategy.

Uses the rolling VWAP as a fair-value anchor. In ``reversion`` mode (default) it
buys when price crosses back above VWAP from below and sells when it crosses back
below from above. Signal strength scales with the distance from VWAP, so a
stretched move reverting to the mean is treated as a stronger setup.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from quantbot.core.constants import Side, SignalType
from quantbot.core.models import Signal
from quantbot.indicators.volume import vwap
from quantbot.strategies.base import BaseStrategy, StrategyContext
from quantbot.strategies.registry import register_strategy


@register_strategy
class VWAPStrategy(BaseStrategy):
    """Rolling-VWAP crossover strategy."""

    name: ClassVar[str] = "VWAPStrategy"
    default_params: ClassVar[dict] = {
        "period": 20,
        "min_distance_pct": 0.0,
    }

    @property
    def min_candles(self) -> int:  # type: ignore[override]
        return int(self.param("period")) + 2

    async def on_candle(self, ctx: StrategyContext) -> Signal | None:
        period = int(self.param("period"))
        if not ctx.has(period + 2):
            return None
        vw = vwap(ctx.highs, ctx.lows, ctx.closes, ctx.volumes, period=period)
        if np.isnan(vw[-2]) or np.isnan(vw[-1]):
            return None

        prev_above = ctx.closes[-2] - vw[-2]
        curr_above = ctx.closes[-1] - vw[-1]
        price = float(ctx.price)
        distance_pct = abs(curr_above) / price if price else 0.0
        if distance_pct < float(self.param("min_distance_pct")):
            return None
        strength = min(1.0, 0.55 + distance_pct * 15.0)

        # Cross up through VWAP -> long.
        if prev_above <= 0 < curr_above:
            return self.make_signal(
                ctx, Side.BUY, signal_type=SignalType.ENTRY, strength=strength,
                reason="vwap_cross_up",
            )
        # Cross down through VWAP -> short/exit.
        if prev_above >= 0 > curr_above:
            return self.make_signal(
                ctx, Side.SELL, signal_type=SignalType.ENTRY, strength=strength,
                reason="vwap_cross_down",
            )
        return None


__all__ = ["VWAPStrategy"]
