"""Breakout scanner — finds symbols breaking (or about to break) a range.

Measures how close the latest close is to the high (or low) of a Donchian
channel over the lookback. A close above the prior channel high scores positive
(bullish breakout), below the prior low scores negative; near-but-not-through
scores between, surfacing imminent breakout candidates too.
"""

from __future__ import annotations

import numpy as np

from quantbot.scanners.base import OHLCV, BaseScanner, ScanResult


class BreakoutScanner(BaseScanner):
    """Rank symbols by proximity to / breach of a Donchian channel edge."""

    def __init__(self, *args, channel: int = 20, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._channel = channel

    def score(self, data: OHLCV) -> ScanResult | None:
        if len(data) < self._channel + 2:
            return None
        prior_high = float(np.max(data.highs[-self._channel - 1 : -1]))
        prior_low = float(np.min(data.lows[-self._channel - 1 : -1]))
        close = float(data.closes[-1])
        span = prior_high - prior_low
        if span <= 0:
            return None
        # Position within the channel: >1 = broke out up, <0 = broke out down.
        position = (close - prior_low) / span
        if position >= 1.0:
            score = 1.0 + (close - prior_high) / prior_high  # bullish breakout
            kind = "breakout_up"
        elif position <= 0.0:
            score = -1.0 - (prior_low - close) / prior_low  # bearish breakdown
            kind = "breakout_down"
        else:
            score = position - 0.5  # proximity, centred at 0
            kind = "in_range"
        return ScanResult(
            symbol=data.symbol,
            score=float(score),
            metrics={
                "channel_position": round(position, 3),
                "prior_high": round(prior_high, 8),
                "prior_low": round(prior_low, 8),
                "kind": kind,  # type: ignore[dict-item]
            },
        )

    higher_is_better = True


__all__ = ["BreakoutScanner"]
