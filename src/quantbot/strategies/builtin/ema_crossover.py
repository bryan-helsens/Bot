"""EMA crossover strategy.

A classic trend-following entry: go long when a fast EMA crosses above a slow
EMA (golden cross) and short/exit when it crosses below (death cross). Signal
strength scales with the normalised gap between the two EMAs so a decisive cross
yields a stronger signal than a marginal one.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from quantbot.core.constants import Side, SignalType
from quantbot.core.models import Signal
from quantbot.indicators.trend import ema
from quantbot.strategies.base import BaseStrategy, StrategyContext
from quantbot.strategies.registry import register_strategy


@register_strategy
class EMACrossoverStrategy(BaseStrategy):
    """Fast/slow EMA crossover trend-following strategy."""

    name: ClassVar[str] = "EMACrossoverStrategy"
    default_params: ClassVar[dict] = {
        "fast_period": 12,
        "slow_period": 26,
        "min_gap_pct": 0.0,  # minimum |fast-slow|/price to act (noise filter)
    }

    @property
    def min_candles(self) -> int:  # type: ignore[override]
        return int(self.param("slow_period")) + 2

    async def on_candle(self, ctx: StrategyContext) -> Signal | None:
        fast_p = int(self.param("fast_period"))
        slow_p = int(self.param("slow_period"))
        if fast_p >= slow_p:
            return None
        if not ctx.has(slow_p + 2):
            return None

        fast = ema(ctx.closes, fast_p)
        slow = ema(ctx.closes, slow_p)
        if np.isnan(fast[-2]) or np.isnan(slow[-2]):
            return None

        prev_diff = fast[-2] - slow[-2]
        curr_diff = fast[-1] - slow[-1]
        price = float(ctx.price)
        gap_pct = abs(curr_diff) / price if price else 0.0
        if gap_pct < float(self.param("min_gap_pct")):
            return None

        strength = min(1.0, 0.5 + gap_pct * 20.0)

        # Golden cross: fast crosses above slow -> long entry.
        if prev_diff <= 0 < curr_diff:
            return self.make_signal(
                ctx, Side.BUY, signal_type=SignalType.ENTRY, strength=strength,
                reason="ema_golden_cross", fast=fast_p, slow=slow_p,
            )
        # Death cross: fast crosses below slow -> short/exit.
        if prev_diff >= 0 > curr_diff:
            return self.make_signal(
                ctx, Side.SELL, signal_type=SignalType.ENTRY, strength=strength,
                reason="ema_death_cross", fast=fast_p, slow=slow_p,
            )
        return None


__all__ = ["EMACrossoverStrategy"]
