"""Scalping strategy (fast EMA pullback on a short timeframe).

A high-frequency strategy intended for 1m/5m candles. It rides a short-term
trend (defined by a fast/slow EMA pair) and enters on shallow pullbacks to the
fast EMA, aiming for small, frequent gains with tight stops. The RSI guard avoids
buying into already-overbought spikes (or selling oversold dips).
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from quantbot.core.constants import Side, SignalType
from quantbot.core.models import Signal
from quantbot.indicators.momentum import rsi
from quantbot.indicators.trend import ema
from quantbot.strategies.base import BaseStrategy, StrategyContext
from quantbot.strategies.registry import register_strategy


@register_strategy
class ScalpingStrategy(BaseStrategy):
    """Fast-EMA pullback scalping strategy."""

    name: ClassVar[str] = "ScalpingStrategy"
    default_params: ClassVar[dict] = {
        "fast_period": 8,
        "slow_period": 21,
        "rsi_period": 7,
        "rsi_upper": 75.0,
        "rsi_lower": 25.0,
        "pullback_pct": 0.001,
    }

    @property
    def min_candles(self) -> int:  # type: ignore[override]
        return int(self.param("slow_period")) + 2

    async def on_candle(self, ctx: StrategyContext) -> Signal | None:
        fast_p = int(self.param("fast_period"))
        slow_p = int(self.param("slow_period"))
        if fast_p >= slow_p or not ctx.has(slow_p + 2):
            return None
        fast = ema(ctx.closes, fast_p)
        slow = ema(ctx.closes, slow_p)
        rsi_vals = rsi(ctx.closes, int(self.param("rsi_period")))
        if np.isnan(fast[-1]) or np.isnan(slow[-1]) or np.isnan(rsi_vals[-1]):
            return None

        price = ctx.closes[-1]
        low = ctx.lows[-1]
        high = ctx.highs[-1]
        pullback = float(self.param("pullback_pct"))
        rsi_now = rsi_vals[-1]

        uptrend = fast[-1] > slow[-1]
        downtrend = fast[-1] < slow[-1]

        # Uptrend pullback: price dipped to the fast EMA and closed back above it.
        if (
            uptrend
            and low <= fast[-1] * (1 + pullback)
            and price > fast[-1]
            and rsi_now < float(self.param("rsi_upper"))
        ):
            return self.make_signal(
                ctx, Side.BUY, signal_type=SignalType.ENTRY, strength=0.6,
                reason="scalp_uptrend_pullback",
            )
        # Downtrend pullback: price rallied to the fast EMA and closed back below.
        if (
            downtrend
            and high >= fast[-1] * (1 - pullback)
            and price < fast[-1]
            and rsi_now > float(self.param("rsi_lower"))
        ):
            return self.make_signal(
                ctx, Side.SELL, signal_type=SignalType.ENTRY, strength=0.6,
                reason="scalp_downtrend_pullback",
            )
        return None


__all__ = ["ScalpingStrategy"]
