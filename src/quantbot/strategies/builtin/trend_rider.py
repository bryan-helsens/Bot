"""Trend-rider strategy — capture and ride sustained up-trends (long-only).

Designed for assets with strong secular trends (e.g. crypto). The philosophy is
"let winners run, cut losers": enter only when a real up-trend is confirmed, then
hold while it persists, exiting only when the trend breaks. It does *not* emit
take-profit signals — the win is captured by riding the move and letting the
engine's trailing stop lock in gains.

Entry (long): fast EMA above slow EMA **and** price above the long "regime" EMA
(so we only buy in established up-trends, avoiding bear-market chop).
Exit: the fast EMA crosses back below the slow EMA (trend break). On spot this is
treated by the engine as a long exit; the trailing stop handles adverse moves
before the cross.

Pair with a wide trailing stop and no take-profit cap (see the recommended config
in ``config/strategies.example.yaml``).
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
class TrendRiderStrategy(BaseStrategy):
    """Long-only, regime-filtered trend-following with run-the-winner exits."""

    name: ClassVar[str] = "TrendRiderStrategy"
    default_params: ClassVar[dict] = {
        "fast_period": 20,
        "slow_period": 50,
        "regime_period": 100,
    }

    @property
    def min_candles(self) -> int:  # type: ignore[override]
        return int(self.param("regime_period")) + 2

    async def on_candle(self, ctx: StrategyContext) -> Signal | None:
        fast_p = int(self.param("fast_period"))
        slow_p = int(self.param("slow_period"))
        regime_p = int(self.param("regime_period"))
        if fast_p >= slow_p or not ctx.has(regime_p + 2):
            return None

        fast = ema(ctx.closes, fast_p)
        slow = ema(ctx.closes, slow_p)
        regime = ema(ctx.closes, regime_p)
        if np.isnan(fast[-1]) or np.isnan(slow[-1]) or np.isnan(regime[-1]):
            return None
        if np.isnan(fast[-2]) or np.isnan(slow[-2]):
            return None

        price = ctx.closes[-1]
        prev_diff = fast[-2] - slow[-2]
        curr_diff = fast[-1] - slow[-1]

        # Entry: fast crosses above slow while price is above the regime EMA
        # (confirmed up-trend). Strength scales with distance above the regime.
        if prev_diff <= 0 < curr_diff and price > regime[-1]:
            distance = (price - regime[-1]) / regime[-1] if regime[-1] else 0.0
            strength = min(1.0, 0.6 + distance * 2.0)
            return self.make_signal(
                ctx, Side.BUY, signal_type=SignalType.ENTRY, strength=strength,
                reason="trend_rider_entry", regime_distance=round(float(distance), 4),
            )

        # Also enter when price crosses up through the regime EMA while already in
        # an up-trend (fast > slow). This catches trends already underway when the
        # bot starts watching, without waiting for the next fast/slow cross.
        prev_regime = regime[-2]
        if (
            curr_diff > 0
            and not np.isnan(prev_regime)
            and ctx.closes[-2] <= prev_regime
            and price > regime[-1]
        ):
            return self.make_signal(
                ctx, Side.BUY, signal_type=SignalType.ENTRY, strength=0.6,
                reason="trend_rider_regime_breakout",
            )

        # Exit: trend break (fast crosses below slow). The engine treats this as
        # a long exit on spot; the trailing stop covers adverse moves beforehand.
        if prev_diff >= 0 > curr_diff:
            return self.make_signal(
                ctx, Side.SELL, signal_type=SignalType.EXIT, strength=1.0,
                reason="trend_rider_exit",
            )
        return None


__all__ = ["TrendRiderStrategy"]
