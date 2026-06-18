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
from quantbot.indicators.trend import sma
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
        # Trend filter: only buy an oversold dip when the medium-term trend is NOT
        # falling (its SMA is flat or rising). Buying dips in a confirmed downtrend
        # is catching a falling knife — live data showed coins in downtrends
        # (ZIL/VET/...) stopped out repeatedly. It still allows dip-buys in
        # up/sideways markets (where mean-reversion works). Set trend_filter=false
        # to disable.
        "trend_filter": True,
        "trend_period": 50,
    }

    def _trend_lookback(self) -> int:
        """Candles over which the trend SMA's slope is measured."""
        return max(5, int(self.param("trend_period")) // 5)

    @property
    def min_candles(self) -> int:  # type: ignore[override]
        need = int(self.param("period")) + 3
        if bool(self.param("trend_filter")):
            need = max(need, int(self.param("trend_period")) + self._trend_lookback() + 1)
        return need

    async def on_candle(self, ctx: StrategyContext) -> Signal | None:
        period = int(self.param("period"))
        if not ctx.has(self.min_candles):
            return None
        oversold = float(self.param("oversold"))
        overbought = float(self.param("overbought"))

        values = rsi(ctx.closes, period)
        prev, curr = values[-2], values[-1]
        if np.isnan(prev) or np.isnan(curr):
            return None

        # Cross up out of oversold -> bullish reversal.
        if prev <= oversold < curr:
            if not self._trend_ok(ctx):
                return None  # oversold, but in a downtrend — skip the falling knife
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

    def _trend_ok(self, ctx: StrategyContext) -> bool:
        """True if buying is allowed: filter off, or the trend SMA is not falling."""
        if not bool(self.param("trend_filter")):
            return True
        trend_period = int(self.param("trend_period"))
        lookback = self._trend_lookback()
        closes = ctx.closes
        if len(closes) < trend_period + lookback + 1:
            return False  # not enough history to confirm the regime -> stay out
        trend = sma(closes, trend_period)
        now, past = trend[-1], trend[-1 - lookback]
        if np.isnan(now) or np.isnan(past):
            return False
        return float(now) >= float(past)  # SMA flat/rising = not a downtrend


__all__ = ["RSIStrategy"]
