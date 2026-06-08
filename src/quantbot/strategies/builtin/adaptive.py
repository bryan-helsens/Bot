"""Adaptive strategy — routes between trend-following and mean-reversion by regime.

Different market regimes reward different tactics (validated on real data):

* **Trending markets** (smooth up-trends, typical of large-caps) reward
  trend-following: enter on confirmation, ride the move, exit on trend break.
* **Ranging / choppy markets** (sharp dips that snap back, typical of small-caps)
  reward mean-reversion: buy oversold dips, sell into strength.
* **Down-trends** reward staying in cash.

This strategy detects the current regime with
:class:`~quantbot.ai.regime.MarketRegimeDetector` and switches its entry logic
accordingly — long-only on spot. It does NOT pick position size; pair it with
RISK-based sizing (see ``config/strategies.adaptive.example.yaml``), which the
meme/small-cap stress test showed is the dominant driver of survival on volatile
coins.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from quantbot.ai.regime import MarketRegimeDetector
from quantbot.core.constants import MarketRegime, Side, SignalType
from quantbot.core.models import Signal
from quantbot.indicators.momentum import rsi
from quantbot.indicators.trend import ema
from quantbot.indicators.volatility import bollinger_bands
from quantbot.strategies.base import BaseStrategy, StrategyContext
from quantbot.strategies.registry import register_strategy


@register_strategy
class AdaptiveStrategy(BaseStrategy):
    """Regime-routed strategy: trend-follow in trends, mean-revert in ranges."""

    name: ClassVar[str] = "AdaptiveStrategy"
    default_params: ClassVar[dict] = {
        # Trend leg
        "fast_period": 20,
        "slow_period": 50,
        "regime_ema": 100,
        # Mean-reversion leg
        "bb_period": 20,
        "bb_std": 2.0,
        "rsi_period": 14,
        "rsi_oversold": 35.0,
        "rsi_overbought": 65.0,
        # Regime detector
        "adx_threshold": 25.0,
    }

    @property
    def min_candles(self) -> int:  # type: ignore[override]
        return max(int(self.param("regime_ema")), 60) + 2

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._detector = MarketRegimeDetector(
            adx_trend_threshold=float(self.param("adx_threshold"))
        )

    async def on_candle(self, ctx: StrategyContext) -> Signal | None:
        if not ctx.has(self.min_candles):
            return None
        reading = self._detector.detect(ctx.highs, ctx.lows, ctx.closes)

        if reading.regime is MarketRegime.TRENDING_UP:
            return self._trend_leg(ctx, reading)
        if reading.regime in (MarketRegime.RANGING, MarketRegime.HIGH_VOLATILITY,
                              MarketRegime.LOW_VOLATILITY):
            return self._mean_reversion_leg(ctx, reading)
        # TRENDING_DOWN or UNKNOWN: exit to cash (signal a sell; ignored if flat).
        return self.make_signal(
            ctx, Side.SELL, signal_type=SignalType.EXIT, strength=1.0,
            reason=f"adaptive_exit_{reading.regime.value}",
        )

    # ------------------------------------------------------------------ legs

    def _trend_leg(self, ctx: StrategyContext, reading) -> Signal | None:
        """Stay long while the up-trend holds."""
        fast = ema(ctx.closes, int(self.param("fast_period")))
        slow = ema(ctx.closes, int(self.param("slow_period")))
        regime = ema(ctx.closes, int(self.param("regime_ema")))
        if np.isnan(fast[-1]) or np.isnan(slow[-1]) or np.isnan(regime[-1]):
            return None
        price = ctx.closes[-1]
        if fast[-1] > slow[-1] and price > regime[-1]:
            return self.make_signal(
                ctx, Side.BUY, signal_type=SignalType.ENTRY, strength=0.7,
                reason="adaptive_trend_long", regime=reading.regime.value,
            )
        return self.make_signal(
            ctx, Side.SELL, signal_type=SignalType.EXIT, strength=1.0,
            reason="adaptive_trend_exit",
        )

    def _mean_reversion_leg(self, ctx: StrategyContext, reading) -> Signal | None:
        """Buy oversold dips; sell into overbought strength."""
        bb = bollinger_bands(ctx.closes, int(self.param("bb_period")), float(self.param("bb_std")))
        rsi_vals = rsi(ctx.closes, int(self.param("rsi_period")))
        if np.isnan(bb.lower[-1]) or np.isnan(rsi_vals[-1]):
            return None
        price = ctx.closes[-1]
        rsi_now = rsi_vals[-1]
        # Buy: price at/below lower band AND oversold RSI (a real dip).
        if price <= bb.lower[-1] and rsi_now < float(self.param("rsi_oversold")):
            strength = min(1.0, 0.6 + (float(self.param("rsi_oversold")) - rsi_now) / 100.0)
            return self.make_signal(
                ctx, Side.BUY, signal_type=SignalType.ENTRY, strength=strength,
                reason="adaptive_meanrev_buy", rsi=round(float(rsi_now), 1),
                regime=reading.regime.value,
            )
        # Sell: price at/above upper band OR overbought RSI (take the bounce).
        if price >= bb.upper[-1] or rsi_now > float(self.param("rsi_overbought")):
            return self.make_signal(
                ctx, Side.SELL, signal_type=SignalType.EXIT, strength=1.0,
                reason="adaptive_meanrev_sell",
            )
        return None


__all__ = ["AdaptiveStrategy"]
