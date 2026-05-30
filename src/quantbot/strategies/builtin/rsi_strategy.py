"""RSI mean-reversion strategy.

Buys when RSI exits oversold territory (crosses up through the oversold
threshold) and sells when it exits overbought territory (crosses down through the
overbought threshold). Using a *cross* rather than a level avoids firing on every
candle while the market stays extreme.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from quantbot.core.constants import Side, SignalType
from quantbot.core.models import Signal
from quantbot.indicators.momentum import rsi
from quantbot.strategies.base import BaseStrategy, StrategyContext
from quantbot.strategies.registry import register_strategy


@register_strategy
class RSIStrategy(BaseStrategy):
    """Relative Strength Index reversal strategy."""

    name: ClassVar[str] = "RSIStrategy"
    default_params: ClassVar[dict] = {
        "period": 14,
        "oversold": 30.0,
        "overbought": 70.0,
    }

    @property
    def min_candles(self) -> int:  # type: ignore[override]
        return int(self.param("period")) + 3

    async def on_candle(self, ctx: StrategyContext) -> Signal | None:
        period = int(self.param("period"))
        if not ctx.has(period + 3):
            return None
        oversold = float(self.param("oversold"))
        overbought = float(self.param("overbought"))

        values = rsi(ctx.closes, period)
        prev, curr = values[-2], values[-1]
        if np.isnan(prev) or np.isnan(curr):
            return None

        # Cross up out of oversold -> bullish reversal.
        if prev <= oversold < curr:
            strength = min(1.0, 0.5 + (oversold - min(prev, oversold)) / 100.0 + 0.1)
            return self.make_signal(
                ctx, Side.BUY, signal_type=SignalType.ENTRY, strength=max(0.55, strength),
                reason="rsi_exit_oversold", rsi=round(float(curr), 2),
            )
        # Cross down out of overbought -> bearish reversal.
        if prev >= overbought > curr:
            strength = min(1.0, 0.5 + (max(prev, overbought) - overbought) / 100.0 + 0.1)
            return self.make_signal(
                ctx, Side.SELL, signal_type=SignalType.ENTRY, strength=max(0.55, strength),
                reason="rsi_exit_overbought", rsi=round(float(curr), 2),
            )
        return None


__all__ = ["RSIStrategy"]
