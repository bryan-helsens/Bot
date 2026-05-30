"""Unit tests for the confluence signal aggregator."""

from __future__ import annotations

from decimal import Decimal

import pytest

from quantbot.core.config import AggregatorSettings
from quantbot.core.constants import Side, Timeframe
from quantbot.core.models import Signal
from quantbot.strategies.aggregator import SignalAggregator

pytestmark = pytest.mark.unit


def _sig(strategy: str, side: Side, strength: float = 0.6) -> Signal:
    return Signal(
        strategy=strategy, symbol="BTCUSDT", timeframe=Timeframe.H1,
        side=side, strength=strength, price=Decimal("100"),
    )


@pytest.fixture
def cfg() -> AggregatorSettings:
    return AggregatorSettings(min_consensus=2, min_strength=0.5, window_seconds=60)


def test_single_strategy_no_confluence(cfg: AggregatorSettings) -> None:
    agg = SignalAggregator(cfg)
    assert not agg.add(_sig("ema", Side.BUY, 0.9)).actionable


def test_two_agree_triggers(cfg: AggregatorSettings) -> None:
    agg = SignalAggregator(cfg)
    agg.add(_sig("ema", Side.BUY))
    result = agg.add(_sig("rsi", Side.BUY))
    assert result.actionable and result.signal is not None
    assert result.signal.meta["consensus"] == 2


def test_conflict_stronger_side_wins(cfg: AggregatorSettings) -> None:
    agg = SignalAggregator(cfg)
    result = agg.add_many([
        _sig("ema", Side.BUY, 0.9), _sig("macd", Side.BUY, 0.9),
        _sig("rsi", Side.SELL, 0.5), _sig("bb", Side.SELL, 0.5),
    ])
    assert result.actionable and result.signal.side is Side.BUY


def test_conflict_tie_no_trade(cfg: AggregatorSettings) -> None:
    agg = SignalAggregator(cfg)
    result = agg.add_many([
        _sig("a", Side.BUY, 0.6), _sig("b", Side.BUY, 0.6),
        _sig("c", Side.SELL, 0.6), _sig("d", Side.SELL, 0.6),
    ])
    assert not result.actionable and result.reason == "conflict_tie"


def test_same_strategy_counts_once(cfg: AggregatorSettings) -> None:
    agg = SignalAggregator(cfg)
    result = agg.add_many([_sig("ema", Side.BUY, 0.9), _sig("ema", Side.BUY, 0.9)])
    assert not result.actionable
