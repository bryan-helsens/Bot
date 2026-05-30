"""Trend-following strategy (ADX-filtered moving-average direction).

Only trades in the direction of an established trend: requires ADX above a
threshold (a real trend, not chop) and price on the correct side of a long EMA,
entering when the +DI/-DI directional lines confirm. This keeps the strategy out
of ranging markets where trend signals whipsaw.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from quantbot.core.constants import Side, SignalType
from quantbot.core.models import Signal
from quantbot.indicators.trend import adx, ema
from quantbot.strategies.base import BaseStrategy, StrategyContext
from quantbot.strategies.registry import register_strategy


@register_strategy
class TrendFollowingStrategy(BaseStrategy):
    """ADX-filtered EMA trend-following strategy."""

    name: ClassVar[str] = "TrendFollowingStrategy"
    default_params: ClassVar[dict] = {
        "ema_period": 50,
        "adx_period": 14,
        "adx_threshold": 25.0,
    }

    @property
    def min_candles(self) -> int:  # type: ignore[override]
        return max(int(self.param("ema_period")), int(self.param("adx_period")) * 2) + 2

    async def on_candle(self, ctx: StrategyContext) -> Signal | None:
        if not ctx.has(self.min_candles):
            return None
        ema_period = int(self.param("ema_period"))
        adx_period = int(self.param("adx_period"))
        trend_ema = ema(ctx.closes, ema_period)
        adx_res = adx(ctx.highs, ctx.lows, ctx.closes, adx_period)
        if np.isnan(trend_ema[-1]) or np.isnan(adx_res.adx[-1]):
            return None

        threshold = float(self.param("adx_threshold"))
        adx_val = adx_res.adx[-1]

        # A "strong trend state" requires price/EMA side, DI direction and ADX
        # all agreeing. We signal on the *transition* into that state, which
        # fires whether ADX crossing the threshold or the directional alignment
        # completed the setup last.
        def strong_bull(i: int) -> bool:
            return (
                ctx.closes[i] > trend_ema[i]
                and adx_res.plus_di[i] > adx_res.minus_di[i]
                and adx_res.adx[i] >= threshold
            )

        def strong_bear(i: int) -> bool:
            return (
                ctx.closes[i] < trend_ema[i]
                and adx_res.minus_di[i] > adx_res.plus_di[i]
                and adx_res.adx[i] >= threshold
            )

        strength = min(1.0, 0.5 + (adx_val - threshold) / 100.0 + 0.15)
        if strong_bull(-1) and not strong_bull(-2):
            return self.make_signal(
                ctx, Side.BUY, signal_type=SignalType.ENTRY, strength=strength,
                reason="trend_following_long", adx=round(float(adx_val), 1),
            )
        if strong_bear(-1) and not strong_bear(-2):
            return self.make_signal(
                ctx, Side.SELL, signal_type=SignalType.ENTRY, strength=strength,
                reason="trend_following_short", adx=round(float(adx_val), 1),
            )
        return None


__all__ = ["TrendFollowingStrategy"]
