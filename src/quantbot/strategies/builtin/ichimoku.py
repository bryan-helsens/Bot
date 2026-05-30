"""Ichimoku Cloud strategy.

A multi-condition trend strategy that signals on the *transition into full
alignment* rather than a single crossover. A long signal fires the moment all
bullish conditions first hold together:
    * Tenkan-sen above Kijun-sen, and
    * price trading above the cloud (above both senkou spans).
The mirror conditions produce a short/exit signal. Detecting the transition
(alignment now true, but not on the previous bar) means the entry triggers
whether it was the TK cross or the cloud breakout that completed the setup,
making the strategy fire reliably on real trends while still requiring full
confluence.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from quantbot.core.constants import Side, SignalType
from quantbot.core.models import Signal
from quantbot.indicators.trend import ichimoku
from quantbot.strategies.base import BaseStrategy, StrategyContext
from quantbot.strategies.registry import register_strategy


@register_strategy
class IchimokuStrategy(BaseStrategy):
    """Ichimoku Kinko Hyo trend strategy with cloud confirmation."""

    name: ClassVar[str] = "IchimokuStrategy"
    default_params: ClassVar[dict] = {
        "tenkan_period": 9,
        "kijun_period": 26,
        "senkou_b_period": 52,
    }

    @property
    def min_candles(self) -> int:  # type: ignore[override]
        return int(self.param("senkou_b_period")) + 2

    async def on_candle(self, ctx: StrategyContext) -> Signal | None:
        if not ctx.has(self.min_candles):
            return None
        result = ichimoku(
            ctx.highs, ctx.lows, ctx.closes,
            int(self.param("tenkan_period")),
            int(self.param("kijun_period")),
            int(self.param("senkou_b_period")),
        )
        tenkan, kijun = result.tenkan_sen, result.kijun_sen
        span_a, span_b = result.senkou_span_a, result.senkou_span_b
        if any(np.isnan(x[-2]) or np.isnan(x[-1]) for x in (tenkan, kijun, span_a, span_b)):
            return None

        def bull(i: int) -> bool:
            top = max(span_a[i], span_b[i])
            return ctx.closes[i] > top and tenkan[i] > kijun[i]

        def bear(i: int) -> bool:
            bottom = min(span_a[i], span_b[i])
            return ctx.closes[i] < bottom and tenkan[i] < kijun[i]

        # Transition into full bullish alignment.
        if bull(-1) and not bull(-2):
            return self.make_signal(
                ctx, Side.BUY, signal_type=SignalType.ENTRY, strength=0.7,
                reason="ichimoku_bull_alignment",
            )
        # Transition into full bearish alignment.
        if bear(-1) and not bear(-2):
            return self.make_signal(
                ctx, Side.SELL, signal_type=SignalType.ENTRY, strength=0.7,
                reason="ichimoku_bear_alignment",
            )
        return None


__all__ = ["IchimokuStrategy"]
