"""Volume scanner — ranks symbols by relative volume surge.

Compares the latest volume to its rolling average to surface coins seeing
unusual activity (often preceding or accompanying significant moves). Score is
the relative-volume multiple (e.g. 3.0 = trading at 3x its average).
"""

from __future__ import annotations

import numpy as np

from quantbot.indicators.volume import relative_volume
from quantbot.scanners.base import OHLCV, BaseScanner, ScanResult


class VolumeScanner(BaseScanner):
    """Rank symbols by current volume relative to their average."""

    def __init__(self, *args, avg_period: int = 20, min_multiple: float = 1.5, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._avg_period = avg_period
        self._min_multiple = min_multiple

    def score(self, data: OHLCV) -> ScanResult | None:
        if len(data) < self._avg_period + 1:
            return None
        rv = relative_volume(data.volumes, self._avg_period)
        current = rv[-1]
        if np.isnan(current) or current < self._min_multiple:
            return None
        avg_quote = float(np.mean(data.closes[-self._avg_period:] * data.volumes[-self._avg_period:]))
        return ScanResult(
            symbol=data.symbol,
            score=float(current),
            metrics={
                "rel_volume": round(float(current), 2),
                "avg_quote_volume": round(avg_quote, 2),
            },
        )


__all__ = ["VolumeScanner"]
