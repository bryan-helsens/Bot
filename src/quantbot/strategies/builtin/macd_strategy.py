"""MACD crossover strategy.

Enters long when the MACD line crosses above its signal line (histogram turns
positive) and short/exit when it crosses below. An optional ``zero_line_filter``
only takes longs while the MACD line is above zero (and shorts below), aligning
entries with the prevailing momentum regime.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from quantbot.core.constants import Side, SignalType
from quantbot.core.models import Signal
from quantbot.indicators.trend import macd
from quantbot.strategies.base import BaseStrategy, StrategyContext
from quantbot.strategies.registry import register_strategy


@register_strategy
class MACDStrategy(BaseStrategy):
    """MACD signal-line crossover strategy."""

    name: ClassVar[str] = "MACDStrategy"
    default_params: ClassVar[dict] = {
        "fast_period": 12,
        "slow_period": 26,
        "signal_period": 9,
        "zero_line_filter": False,
    }

    @property
    def min_candles(self) -> int:  # type: ignore[override]
        return int(self.param("slow_period")) + int(self.param("signal_period")) + 2

    async def on_candle(self, ctx: StrategyContext) -> Signal | None:
        fast_p = int(self.param("fast_period"))
        slow_p = int(self.param("slow_period"))
        signal_p = int(self.param("signal_period"))
        if fast_p >= slow_p or not ctx.has(self.min_candles):
            return None

        result = macd(ctx.closes, fast_p, slow_p, signal_p)
        hist = result.histogram
        macd_line = result.macd
        if np.isnan(hist[-2]) or np.isnan(hist[-1]):
            return None

        zero_filter = bool(self.param("zero_line_filter"))
        price = float(ctx.price)
        strength = min(1.0, 0.5 + abs(hist[-1]) / price * 30.0 if price else 0.5)

        # Bullish crossover: histogram turns positive.
        if hist[-2] <= 0 < hist[-1]:
            if zero_filter and macd_line[-1] < 0:
                return None
            return self.make_signal(
                ctx, Side.BUY, signal_type=SignalType.ENTRY, strength=max(0.55, strength),
                reason="macd_bullish_cross",
            )
        # Bearish crossover: histogram turns negative.
        if hist[-2] >= 0 > hist[-1]:
            if zero_filter and macd_line[-1] > 0:
                return None
            return self.make_signal(
                ctx, Side.SELL, signal_type=SignalType.ENTRY, strength=max(0.55, strength),
                reason="macd_bearish_cross",
            )
        return None


__all__ = ["MACDStrategy"]
