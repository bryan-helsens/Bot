"""Mean-reversion strategy (z-score of price vs a moving average).

Computes the z-score of price relative to a rolling mean/standard deviation and
fades extremes: buy when the z-score falls below ``-entry_z`` (price unusually
cheap) and sell when it rises above ``+entry_z`` (price unusually rich). Works
best in ranging regimes; pair with a regime filter for trending markets.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from quantbot.core.constants import Side, SignalType
from quantbot.core.models import Signal
from quantbot.indicators.trend import sma
from quantbot.indicators.volatility import std_dev
from quantbot.strategies.base import BaseStrategy, StrategyContext
from quantbot.strategies.registry import register_strategy


@register_strategy
class MeanReversionStrategy(BaseStrategy):
    """Z-score mean-reversion strategy."""

    name: ClassVar[str] = "MeanReversionStrategy"
    default_params: ClassVar[dict] = {
        "period": 20,
        "entry_z": 2.0,
        "max_z": 4.0,  # ignore blow-off moves beyond this (likely a breakout)
    }

    @property
    def min_candles(self) -> int:  # type: ignore[override]
        return int(self.param("period")) + 2

    async def on_candle(self, ctx: StrategyContext) -> Signal | None:
        period = int(self.param("period"))
        if not ctx.has(period + 2):
            return None
        mean = sma(ctx.closes, period)
        sigma = std_dev(ctx.closes, period)
        if np.isnan(mean[-1]) or np.isnan(sigma[-1]) or sigma[-1] == 0:
            return None

        z = (ctx.closes[-1] - mean[-1]) / sigma[-1]
        entry_z = float(self.param("entry_z"))
        max_z = float(self.param("max_z"))
        abs_z = abs(z)
        if abs_z < entry_z or abs_z > max_z:
            return None
        strength = min(1.0, 0.5 + (abs_z - entry_z) / 4.0 + 0.1)

        # Price unusually cheap -> expect reversion up -> buy.
        if z <= -entry_z:
            return self.make_signal(
                ctx, Side.BUY, signal_type=SignalType.ENTRY, strength=max(0.55, strength),
                reason="mean_reversion_long", zscore=round(float(z), 2),
            )
        # Price unusually rich -> expect reversion down -> sell.
        return self.make_signal(
            ctx, Side.SELL, signal_type=SignalType.ENTRY, strength=max(0.55, strength),
            reason="mean_reversion_short", zscore=round(float(z), 2),
        )


__all__ = ["MeanReversionStrategy"]
