"""Breakout strategy (Donchian-style channel breakout).

Goes long when price closes above the highest high of the last ``channel``
candles and short when it closes below the lowest low. An optional volume filter
requires the breakout candle's volume to exceed a multiple of the average volume,
helping avoid low-conviction fakeouts.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from quantbot.core.constants import Side, SignalType
from quantbot.core.models import Signal
from quantbot.indicators.volume import relative_volume
from quantbot.strategies.base import BaseStrategy, StrategyContext
from quantbot.strategies.registry import register_strategy


@register_strategy
class BreakoutStrategy(BaseStrategy):
    """Donchian channel breakout strategy with optional volume confirmation."""

    name: ClassVar[str] = "BreakoutStrategy"
    default_params: ClassVar[dict] = {
        "channel": 20,
        "volume_filter": True,
        "volume_multiple": 1.5,
    }

    @property
    def min_candles(self) -> int:  # type: ignore[override]
        return int(self.param("channel")) + 2

    async def on_candle(self, ctx: StrategyContext) -> Signal | None:
        channel = int(self.param("channel"))
        if not ctx.has(channel + 2):
            return None
        # Channel computed over the candles *before* the current one.
        prior_highs = ctx.highs[-channel - 1 : -1]
        prior_lows = ctx.lows[-channel - 1 : -1]
        highest = float(prior_highs.max())
        lowest = float(prior_lows.min())
        close = float(ctx.closes[-1])

        if self.param("volume_filter"):
            rv = relative_volume(ctx.volumes, channel)
            rv_last = rv[-1]
            if not np.isnan(rv_last) and rv_last < float(self.param("volume_multiple")):
                return None

        if close > highest:
            strength = min(1.0, 0.6 + (close - highest) / highest * 20.0)
            return self.make_signal(
                ctx, Side.BUY, signal_type=SignalType.ENTRY, strength=strength,
                reason="breakout_up", level=round(highest, 4),
            )
        if close < lowest:
            strength = min(1.0, 0.6 + (lowest - close) / lowest * 20.0)
            return self.make_signal(
                ctx, Side.SELL, signal_type=SignalType.ENTRY, strength=strength,
                reason="breakout_down", level=round(lowest, 4),
            )
        return None


__all__ = ["BreakoutStrategy"]
