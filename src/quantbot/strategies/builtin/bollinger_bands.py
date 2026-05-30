"""Bollinger Bands mean-reversion strategy.

Fades extremes: buys when price closes back inside the lower band after piercing
it (oversold snap-back) and sells when it closes back inside the upper band.
Using a re-entry (close was below the band, now back above) avoids catching a
falling knife while price walks the band.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from quantbot.core.constants import Side, SignalType
from quantbot.core.models import Signal
from quantbot.indicators.volatility import bollinger_bands
from quantbot.strategies.base import BaseStrategy, StrategyContext
from quantbot.strategies.registry import register_strategy


@register_strategy
class BollingerBandsStrategy(BaseStrategy):
    """Bollinger Bands mean-reversion (snap-back) strategy."""

    name: ClassVar[str] = "BollingerBandsStrategy"
    default_params: ClassVar[dict] = {
        "period": 20,
        "num_std": 2.0,
    }

    @property
    def min_candles(self) -> int:  # type: ignore[override]
        return int(self.param("period")) + 2

    async def on_candle(self, ctx: StrategyContext) -> Signal | None:
        period = int(self.param("period"))
        if not ctx.has(period + 2):
            return None
        bands = bollinger_bands(ctx.closes, period, float(self.param("num_std")))
        upper, lower = bands.upper, bands.lower
        if np.isnan(lower[-2]) or np.isnan(upper[-2]):
            return None

        prev_close, curr_close = ctx.closes[-2], ctx.closes[-1]
        # Snap back up across the lower band -> long.
        if prev_close < lower[-2] and curr_close >= lower[-1]:
            pb = bands.percent_b[-1]
            strength = 0.6 if np.isnan(pb) else min(1.0, 0.55 + abs(0.0 - pb) * 0.3)
            return self.make_signal(
                ctx, Side.BUY, signal_type=SignalType.ENTRY, strength=strength,
                reason="bb_lower_reversion",
            )
        # Snap back down across the upper band -> short/exit.
        if prev_close > upper[-2] and curr_close <= upper[-1]:
            return self.make_signal(
                ctx, Side.SELL, signal_type=SignalType.ENTRY, strength=0.6,
                reason="bb_upper_reversion",
            )
        return None


__all__ = ["BollingerBandsStrategy"]
