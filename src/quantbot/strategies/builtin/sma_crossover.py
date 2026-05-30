"""SMA crossover strategy.

Trend-following entry using two simple moving averages: long when the fast SMA
crosses above the slow SMA, sell when it crosses below. Strength scales with the
normalised distance between the averages at the crossover.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from quantbot.core.constants import Side, SignalType
from quantbot.core.models import Signal
from quantbot.indicators.trend import sma
from quantbot.strategies.base import BaseStrategy, StrategyContext
from quantbot.strategies.registry import register_strategy


@register_strategy
class SMACrossoverStrategy(BaseStrategy):
    """Fast/slow SMA crossover strategy."""

    name: ClassVar[str] = "SMACrossoverStrategy"
    default_params: ClassVar[dict] = {
        "fast_period": 20,
        "slow_period": 50,
        "min_gap_pct": 0.0,
    }

    @property
    def min_candles(self) -> int:  # type: ignore[override]
        return int(self.param("slow_period")) + 2

    async def on_candle(self, ctx: StrategyContext) -> Signal | None:
        fast_p = int(self.param("fast_period"))
        slow_p = int(self.param("slow_period"))
        if fast_p >= slow_p or not ctx.has(slow_p + 2):
            return None

        fast = sma(ctx.closes, fast_p)
        slow = sma(ctx.closes, slow_p)
        if np.isnan(fast[-2]) or np.isnan(slow[-2]):
            return None

        prev = fast[-2] - slow[-2]
        curr = fast[-1] - slow[-1]
        price = float(ctx.price)
        gap_pct = abs(curr) / price if price else 0.0
        if gap_pct < float(self.param("min_gap_pct")):
            return None
        strength = min(1.0, 0.5 + gap_pct * 20.0)

        if prev <= 0 < curr:
            return self.make_signal(
                ctx, Side.BUY, signal_type=SignalType.ENTRY, strength=strength,
                reason="sma_golden_cross",
            )
        if prev >= 0 > curr:
            return self.make_signal(
                ctx, Side.SELL, signal_type=SignalType.ENTRY, strength=strength,
                reason="sma_death_cross",
            )
        return None


__all__ = ["SMACrossoverStrategy"]
