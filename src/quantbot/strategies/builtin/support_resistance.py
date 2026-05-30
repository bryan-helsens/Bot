"""Support & Resistance bounce strategy.

Detects clustered support/resistance levels from swing pivots and trades bounces:
buy when price dips to a support level and closes back above it, sell when price
rallies into a resistance level and closes back below it. Level strength (touch
count) scales the signal strength.
"""

from __future__ import annotations

from typing import ClassVar

from quantbot.core.constants import Side, SignalType
from quantbot.core.models import Signal
from quantbot.indicators.levels import support_resistance
from quantbot.strategies.base import BaseStrategy, StrategyContext
from quantbot.strategies.registry import register_strategy


@register_strategy
class SupportResistanceStrategy(BaseStrategy):
    """Trade bounces off clustered support/resistance levels."""

    name: ClassVar[str] = "SupportResistanceStrategy"
    default_params: ClassVar[dict] = {
        "lookback": 100,
        "left": 3,
        "right": 3,
        "tolerance": 0.005,
        "min_touches": 2,
        "proximity_pct": 0.005,  # how close to a level counts as a touch
    }

    @property
    def min_candles(self) -> int:  # type: ignore[override]
        return int(self.param("lookback"))

    async def on_candle(self, ctx: StrategyContext) -> Signal | None:
        lookback = int(self.param("lookback"))
        if not ctx.has(lookback):
            return None
        highs = ctx.highs[-lookback:]
        lows = ctx.lows[-lookback:]
        sr = support_resistance(
            highs, lows,
            left=int(self.param("left")),
            right=int(self.param("right")),
            tolerance=float(self.param("tolerance")),
            min_touches=int(self.param("min_touches")),
        )
        price = float(ctx.price)
        prox = float(self.param("proximity_pct"))
        prev_low = float(ctx.lows[-1])
        prev_high = float(ctx.highs[-1])

        support = sr.nearest_support(price)
        if support is not None and prev_low <= support.price * (1 + prox) and price > support.price:
            strength = min(1.0, 0.55 + 0.1 * support.touches)
            return self.make_signal(
                ctx, Side.BUY, signal_type=SignalType.ENTRY, strength=strength,
                reason="sr_support_bounce", level=round(support.price, 4),
                touches=support.touches,
            )

        resistance = sr.nearest_resistance(price)
        if (
            resistance is not None
            and prev_high >= resistance.price * (1 - prox)
            and price < resistance.price
        ):
            strength = min(1.0, 0.55 + 0.1 * resistance.touches)
            return self.make_signal(
                ctx, Side.SELL, signal_type=SignalType.ENTRY, strength=strength,
                reason="sr_resistance_reject", level=round(resistance.price, 4),
                touches=resistance.touches,
            )
        return None


__all__ = ["SupportResistanceStrategy"]
