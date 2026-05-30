"""Volatility scanner — ranks symbols by recent volatility.

Uses ATR expressed as a percentage of price (so it is comparable across symbols
of different absolute prices). High ATR% surfaces fast-moving coins suited to
breakout/momentum strategies; combine with a low-volatility filter to find
"coiled spring" squeeze candidates instead.
"""

from __future__ import annotations

import numpy as np

from quantbot.indicators.volatility import atr, historical_volatility
from quantbot.scanners.base import OHLCV, BaseScanner, ScanResult


class VolatilityScanner(BaseScanner):
    """Rank symbols by ATR percentage (and annualised historical volatility)."""

    def __init__(self, *args, atr_period: int = 14, hv_period: int = 20, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._atr_period = atr_period
        self._hv_period = hv_period

    def score(self, data: OHLCV) -> ScanResult | None:
        if len(data) < max(self._atr_period, self._hv_period) + 2:
            return None
        atr_vals = atr(data.highs, data.lows, data.closes, self._atr_period)
        price = data.closes[-1]
        if np.isnan(atr_vals[-1]) or price <= 0:
            return None
        atr_pct = float(atr_vals[-1] / price)
        hv = historical_volatility(data.closes, self._hv_period)
        hv_last = float(hv[-1]) if not np.isnan(hv[-1]) else 0.0
        return ScanResult(
            symbol=data.symbol,
            score=atr_pct,
            metrics={
                "atr_pct": round(atr_pct * 100, 4),
                "hist_vol_annualised": round(hv_last, 4),
            },
        )


__all__ = ["VolatilityScanner"]
