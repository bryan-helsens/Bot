"""Momentum strategy (rate-of-change with confirmation).

Trades in the direction of strong, accelerating momentum: buys when the
rate-of-change crosses above a positive threshold and ROC is rising, sells when
it crosses below a negative threshold and ROC is falling. The acceleration
requirement filters out stalling moves.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from quantbot.core.constants import Side, SignalType
from quantbot.core.models import Signal
from quantbot.indicators.momentum import roc
from quantbot.strategies.base import BaseStrategy, StrategyContext
from quantbot.strategies.registry import register_strategy


@register_strategy
class MomentumStrategy(BaseStrategy):
    """Rate-of-change momentum strategy with acceleration confirmation."""

    name: ClassVar[str] = "MomentumStrategy"
    default_params: ClassVar[dict] = {
        "period": 10,
        "threshold": 2.0,  # ROC percentage threshold
    }

    @property
    def min_candles(self) -> int:  # type: ignore[override]
        return int(self.param("period")) + 3

    async def on_candle(self, ctx: StrategyContext) -> Signal | None:
        period = int(self.param("period"))
        if not ctx.has(period + 3):
            return None
        values = roc(ctx.closes, period)
        prev, curr = values[-2], values[-1]
        if np.isnan(prev) or np.isnan(curr):
            return None
        threshold = float(self.param("threshold"))

        rising = curr > prev
        strength = min(1.0, 0.5 + abs(curr) / 20.0 + 0.1)

        # Cross up through +threshold with rising momentum -> long.
        if prev <= threshold < curr and rising:
            return self.make_signal(
                ctx, Side.BUY, signal_type=SignalType.ENTRY, strength=max(0.55, strength),
                reason="momentum_long", roc=round(float(curr), 2),
            )
        # Cross down through -threshold with falling momentum -> short.
        if prev >= -threshold > curr and not rising:
            return self.make_signal(
                ctx, Side.SELL, signal_type=SignalType.ENTRY, strength=max(0.55, strength),
                reason="momentum_short", roc=round(float(curr), 2),
            )
        return None


__all__ = ["MomentumStrategy"]
