"""The replay backtester drives the REAL engine over candles, offline, and
produces a coherent performance summary — the fast iteration loop."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest

from quantbot.backtest.replay import replay_candles
from quantbot.core.config import BacktestSettings, Settings
from quantbot.core.constants import Timeframe
from quantbot.core.models import Candle

pytestmark = pytest.mark.integration


def _candles(symbol: str, prices: list[float]) -> list[Candle]:
    tf = Timeframe.M5
    start = datetime(2024, 1, 1, tzinfo=UTC)
    out = []
    for i, p in enumerate(prices):
        ot = start + timedelta(seconds=tf.seconds * i)
        d = Decimal(str(round(p, 6)))
        out.append(Candle(
            symbol=symbol, timeframe=tf, open_time=ot,
            close_time=ot + timedelta(seconds=tf.seconds),
            open=d, high=d * Decimal("1.003"), low=d * Decimal("0.997"),
            close=d, volume=Decimal("100"),
        ))
    return out


def _settings() -> Settings:
    s = Settings(_env_file=None)
    s.strategies_config = "config/strategies.paper.example.yaml"  # RSI-only, trend filter
    s.symbols = ["BTCUSDT", "ETHUSDT"]
    s.timeframes = [Timeframe.M5]
    s.backtest = BacktestSettings(
        initial_capital=Decimal("1000"), commission=Decimal("0.001"),
        slippage=Decimal("0.0005"), spread=Decimal("0"),
    )
    return s


async def test_replay_runs_and_summarises() -> None:
    rng = np.random.RandomState(7)
    # Up-drifting series with dips — gives the dip-buyer something to trade.
    def series(base):
        p = base
        out = []
        for _ in range(400):
            p *= 1 + rng.randn() * 0.01 + 0.0008
            out.append(max(p, base * 0.5))
        return out

    candles = {"BTCUSDT": _candles("BTCUSDT", series(100.0)),
               "ETHUSDT": _candles("ETHUSDT", series(50.0))}

    result = await replay_candles(_settings(), candles, Timeframe.M5, warmup=80)

    # Structure + sanity, regardless of how many trades the random walk produced.
    assert result["symbols"] == 2
    assert result["candles_replayed"] == 2 * (400 - 80)
    for key in ("net_pnl", "profit_factor", "win_rate", "fees", "max_drawdown_pct", "benchmark_pct"):
        assert key in result
    assert result["benchmark_symbol"] == "BTCUSDT"
    assert result["fees"] >= 0.0
    assert 0.0 <= result["win_rate"] <= 1.0


async def test_replay_accepts_param_overrides() -> None:
    """The sweep relies on overriding strategy params live without editing files."""
    candles = {"BTCUSDT": _candles("BTCUSDT", list(np.linspace(100, 130, 300)))}
    result = await replay_candles(
        _settings(), candles, Timeframe.M5, warmup=80,
        param_overrides={"trend_filter": False, "oversold": 35},
    )
    assert result["symbols"] == 1
    assert "profit_factor" in result and "net_pnl" in result


async def test_replay_empty_history_is_zero_trades() -> None:
    result = await replay_candles(_settings(), {}, Timeframe.M5, warmup=80)
    assert result["candles_replayed"] == 0
    assert result["trades"] == 0
    assert result["benchmark_symbol"] is None
