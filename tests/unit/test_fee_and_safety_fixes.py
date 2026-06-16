"""Fee-reduction + safety fixes after the 2-day live testnet review:

* opposite-signal flips no longer churn (configurable),
* order submissions are rate-limited so protective stops can't fail with -1015,
* trades carry their contributing strategy name for honest per-strategy stats.
"""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal

import pytest

from quantbot.core.config import AggregatorSettings
from quantbot.core.constants import Side, SignalType, Timeframe
from quantbot.core.models import Signal
from quantbot.execution.executor import _OrderRateLimiter
from quantbot.strategies.aggregator import SignalAggregator

pytestmark = pytest.mark.unit


def _sig(strategy: str, side: Side = Side.BUY) -> Signal:
    return Signal(
        strategy=strategy, symbol="BTCUSDT", timeframe=Timeframe.M5, side=side,
        signal_type=SignalType.ENTRY, strength=0.8, price=Decimal("100"),
    )


def test_exit_on_opposite_signal_defaults_off() -> None:
    """Default: don't churn on flips — let positions run to TP/SL/trailing."""
    from quantbot.core.config import RiskSettings

    assert RiskSettings().exit_on_opposite_signal is False


def test_aggregator_keeps_contributing_strategy_names() -> None:
    agg = SignalAggregator(
        AggregatorSettings(min_consensus=1, min_strength=0.5, window_seconds=999999)
    )
    result = agg.add_many([_sig("rsi_dip_buyer"), _sig("ema_trend")])
    assert result.signal is not None
    # Both contributors are preserved (sorted, '+'-joined) — not a generic name.
    assert result.signal.strategy == "ema_trend+rsi_dip_buyer"


def test_aggregator_single_strategy_name_passes_through() -> None:
    agg = SignalAggregator(
        AggregatorSettings(min_consensus=1, min_strength=0.5, window_seconds=999999)
    )
    result = agg.add_many([_sig("rsi_dip_buyer")])
    assert result.signal is not None
    assert result.signal.strategy == "rsi_dip_buyer"


async def test_rate_limiter_spaces_submissions() -> None:
    limiter = _OrderRateLimiter(min_interval=0.05)
    start = time.perf_counter()
    for _ in range(5):
        await limiter.acquire()
    elapsed = time.perf_counter() - start
    # 5 acquisitions, ~4 gaps of 0.05s -> at least ~0.2s total (never instant).
    assert elapsed >= 0.18


async def test_rate_limiter_serialises_concurrent_callers() -> None:
    limiter = _OrderRateLimiter(min_interval=0.05)
    start = time.perf_counter()
    await asyncio.gather(*(limiter.acquire() for _ in range(4)))
    elapsed = time.perf_counter() - start
    # Even fired concurrently, they must be spaced out, not all at once.
    assert elapsed >= 0.13
