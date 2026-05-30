"""Regression tests for equity/PnL accounting consistency.

These guard against the class of bug where equity accounting conflates notional
reservation with PnL — which silently breaks for short positions. The invariant
checked here is the single source of truth for correctness:

    final_equity == initial_capital + sum(trade.net_pnl)

and the equity curve must stay finite and side-agnostic (correct for both long
and short trades).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest

from quantbot.backtest.engine import BacktestEngine
from quantbot.core.config import BacktestSettings
from quantbot.core.constants import Side, Timeframe
from quantbot.core.models import Candle
from quantbot.portfolio.manager import PortfolioManager
from quantbot.strategies.registry import get_registry

pytestmark = pytest.mark.integration


def _multi_regime_candles(n: int = 600, seed: int = 7) -> list[Candle]:
    """Bull -> chop -> bear -> recovery, so both longs and shorts are exercised."""
    rng = np.random.RandomState(seed)
    prices: list[float] = []
    p = 100.0
    for i in range(n):
        drift = 0.004 if i < 150 else 0.0 if i < 300 else -0.004 if i < 450 else 0.003
        p *= 1 + drift + rng.randn() * 0.015
        prices.append(max(p, 1.0))
    out: list[Candle] = []
    for i, px in enumerate(prices):
        ot = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=i)
        hi = px * (1 + abs(rng.randn()) * 0.004)
        lo = px * (1 - abs(rng.randn()) * 0.004)
        out.append(Candle(
            symbol="BTCUSDT", timeframe=Timeframe.H1, open_time=ot,
            close_time=ot + timedelta(hours=1), open=Decimal(str(px)),
            high=Decimal(str(max(px, hi))), low=Decimal(str(min(px, lo))),
            close=Decimal(str(px)), volume=Decimal(str(1000 + abs(rng.randn()) * 500)),
        ))
    return out


@pytest.mark.parametrize(
    "strategy",
    [
        "EMACrossoverStrategy", "RSIStrategy", "MACDStrategy",
        "BollingerBandsStrategy", "MeanReversionStrategy",
        "MomentumStrategy", "TrendFollowingStrategy",
    ],
)
def test_backtest_equity_matches_sum_of_trades(settings, strategy: str) -> None:
    settings.backtest = BacktestSettings(
        initial_capital=Decimal("10000"), commission=Decimal("0.001"),
        slippage=Decimal("0.0005"), spread=Decimal("0.0002"),
    )
    settings.risk.trailing_stop_pct = Decimal("0.02")
    settings.risk.break_even_trigger_pct = Decimal("0.02")
    settings.risk.take_profit_levels = [(Decimal("0.06"), Decimal("0.5")), (Decimal("0.12"), Decimal("0.5"))]

    registry = get_registry()
    registry.load_builtins()
    strat = registry.create(strategy, symbols=["BTCUSDT"], timeframes=[Timeframe.H1])
    result = BacktestEngine(settings=settings, strategies=[strat], warmup=60).run(
        _multi_regime_candles()
    )

    net = sum(float(t.net_pnl) for t in result.trades)
    # The core invariant: equity is exactly explained by realised PnL.
    assert result.final_equity == pytest.approx(result.initial_capital + net, abs=1e-3)
    expected_return = net / result.initial_capital
    assert result.total_return_pct == pytest.approx(expected_return, abs=1e-9)
    # Equity curve is finite throughout.
    assert all(np.isfinite(v) for v in result.equity_curve)


def test_short_position_equity_is_side_correct() -> None:
    """A short losing as price rises must REDUCE equity (the historical bug)."""
    pf = PortfolioManager(starting_balance=Decimal("10000"))
    pf.positions.open_position(
        symbol="BTCUSDT", side=Side.SELL, quantity=Decimal("2"),
        entry_price=Decimal("100"), fee=Decimal("0"),
    )
    pf.update_price("BTCUSDT", Decimal("110"))  # price up => short loses
    # equity = 10000 + (-20) - 0 fees = 9980
    assert pf.equity() == Decimal("9980")
    pf.update_price("BTCUSDT", Decimal("90"))  # price down => short profits
    assert pf.equity() == Decimal("10020")


def test_long_position_equity_is_side_correct() -> None:
    pf = PortfolioManager(starting_balance=Decimal("10000"))
    pf.positions.open_position(
        symbol="BTCUSDT", side=Side.BUY, quantity=Decimal("2"),
        entry_price=Decimal("100"), fee=Decimal("0"),
    )
    pf.update_price("BTCUSDT", Decimal("110"))
    assert pf.equity() == Decimal("10020")
    pf.update_price("BTCUSDT", Decimal("90"))
    assert pf.equity() == Decimal("9980")
