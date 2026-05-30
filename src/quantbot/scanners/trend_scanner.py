"""Trend scanner — ranks symbols by trend strength and direction.

Combines ADX (trend strength) with the slope of a long EMA (direction) to score
how strongly and cleanly each symbol is trending. The score is signed: strong
up-trends score high positive, strong down-trends high negative; the magnitude
reflects trend strength so ``abs(score)`` ranks "most trending".
"""

from __future__ import annotations

import numpy as np

from quantbot.indicators.trend import adx, ema
from quantbot.scanners.base import OHLCV, BaseScanner, ScanResult


class TrendScanner(BaseScanner):
    """Rank symbols by ADX-confirmed trend (signed by direction)."""

    def __init__(self, *args, ema_period: int = 50, adx_period: int = 14,
                 adx_threshold: float = 20.0, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._ema_period = ema_period
        self._adx_period = adx_period
        self._adx_threshold = adx_threshold

    def score(self, data: OHLCV) -> ScanResult | None:
        if len(data) < max(self._ema_period, self._adx_period * 2) + 2:
            return None
        ema_vals = ema(data.closes, self._ema_period)
        adx_res = adx(data.highs, data.lows, data.closes, self._adx_period)
        adx_val = adx_res.adx[-1]
        if np.isnan(adx_val) or np.isnan(ema_vals[-1]) or np.isnan(ema_vals[-5]):
            return None
        if adx_val < self._adx_threshold:
            return None
        slope = (ema_vals[-1] - ema_vals[-5]) / ema_vals[-5] if ema_vals[-5] else 0.0
        direction = 1.0 if data.closes[-1] > ema_vals[-1] else -1.0
        score = direction * float(adx_val) * (1.0 + abs(slope) * 10.0)
        return ScanResult(
            symbol=data.symbol,
            score=score,
            metrics={
                "adx": round(float(adx_val), 2),
                "ema_slope_pct": round(float(slope) * 100, 3),
                "direction": direction,
            },
        )


__all__ = ["TrendScanner"]
