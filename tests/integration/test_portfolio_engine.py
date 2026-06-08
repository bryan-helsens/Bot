"""Faithfulness tests for the multi-symbol PortfolioBacktestEngine.

Two guarantees are asserted, independent of any indicator logic:

1. **Accounting parity** — feeding a single symbol to the portfolio engine yields
   exactly the same realised equity as the proven single-symbol BacktestEngine.
2. **Portfolio caps bind** — ``max_open_trades`` and ``max_portfolio_exposure``
   (enforced by the shared RiskEngine over a portfolio-wide view) actually limit
   the number of concurrent positions, so the shared capital pool behaves like one
   real account rather than N independent ones.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from quantbot.backtest.engine import BacktestEngine
from quantbot.backtest.portfolio_engine import PortfolioBacktestEngine
from quantbot.core.config import (
    AggregatorSettings,
    BacktestSettings,
    RiskSettings,
    Settings,
)
from quantbot.core.constants import Side, SignalType, SizingMethod, Timeframe
from quantbot.core.models import Candle
from quantbot.strategies.base import BaseStrategy
from quantbot.strategies.registry import register_strategy

pytestmark = pytest.mark.integration


@register_strategy
class _BuyOnceAt25(BaseStrategy):
    """Emit a single BUY at bar 25 on every symbol; never sells."""

    name = "BuyOnceAt25"

    @property
    def min_candles(self) -> int:  # type: ignore[override]
        return 2

    async def on_candle(self, ctx):
        if ctx.length - 1 == 25:
            return self.make_signal(ctx, Side.BUY, signal_type=SignalType.ENTRY, strength=1.0)
        return None


def _flat_then_drift(symbol: str, *, n: int = 40, start: float = 100.0) -> list[Candle]:
    """A gently rising series so an opened long is never stopped out before exit."""
    out = []
    for i in range(n):
        p = Decimal(str(start * (1.0 + 0.01 * i)))
        ot = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=i)
        out.append(Candle(symbol=symbol, timeframe=Timeframe.D1, open_time=ot,
                          close_time=ot + timedelta(days=1), open=p, high=p, low=p, close=p,
                          volume=Decimal("1000")))
    return out


def _settings(*, max_open_trades: int, max_portfolio_exposure: str) -> Settings:
    s = Settings(_env_file=None)
    s.timeframes = [Timeframe.D1]
    s.backtest = BacktestSettings(
        initial_capital=Decimal("10000"), commission=Decimal("0.0"),
        slippage=Decimal("0.0"), spread=Decimal("0.0"),
    )
    # RISK sizing: notional/position = equity * risk_per_trade / stop = 20% here,
    # so several positions fit in cash — the caps (not cash) must be what binds.
    s.risk = RiskSettings(
        sizing_method=SizingMethod.RISK, risk_per_trade=Decimal("0.02"),
        max_open_trades=max_open_trades, max_exposure_per_coin=Decimal("1.0"),
        max_portfolio_exposure=Decimal(max_portfolio_exposure),
        default_stop_loss_pct=Decimal("0.10"), trailing_stop_pct=Decimal("0.0"),
        break_even_trigger_pct=Decimal("0.0"), take_profit_levels=[],
        max_daily_loss=Decimal("0.95"), max_weekly_loss=Decimal("0.95"),
        max_drawdown=Decimal("0.95"), max_correlation=Decimal("1.0"),
        circuit_breaker_losses=99, emergency_stop_enabled=False,
    )
    s.aggregator = AggregatorSettings(min_consensus=1, min_strength=0.5, window_seconds=999999)
    return s


def test_portfolio_accounting_matches_single_symbol() -> None:
    """One symbol through the portfolio engine == the single-symbol engine."""
    candles = _flat_then_drift("AAAUSDT")
    settings = _settings(max_open_trades=5, max_portfolio_exposure="1.0")

    single = BacktestEngine(
        settings=settings, strategies=[_BuyOnceAt25(timeframes=[Timeframe.D1])],
        warmup=2, allow_short=False,
    ).run(candles)
    multi = PortfolioBacktestEngine(
        settings=settings, strategies=[_BuyOnceAt25(timeframes=[Timeframe.D1])],
        warmup=2, allow_short=False,
    ).run_portfolio({"AAAUSDT": candles})

    assert len(multi.trades) == len(single.trades) == 1
    assert float(multi.final_equity) == pytest.approx(float(single.final_equity), abs=1e-6)


@pytest.mark.parametrize(
    ("max_open_trades", "max_exposure", "expected_concurrent"),
    [
        (1, "1.0", 1),   # open-trade cap binds at 1
        (3, "1.0", 3),   # open-trade cap binds at 3 (cash/exposure allow more)
        (5, "0.30", 1),  # exposure cap binds: 2 x 20% = 40% > 30% -> only 1 fits
        (5, "0.50", 2),  # exposure cap binds: 3 x 20% = 60% > 50% -> only 2 fit
    ],
)
def test_portfolio_caps_limit_concurrent_positions(
    max_open_trades: int, max_exposure: str, expected_concurrent: int
) -> None:
    """The shared RiskEngine caps concurrent positions across the whole account."""
    symbols = [f"C{i}USDT" for i in range(5)]
    series = {s: _flat_then_drift(s) for s in symbols}
    settings = _settings(max_open_trades=max_open_trades, max_portfolio_exposure=max_exposure)

    result = PortfolioBacktestEngine(
        settings=settings, strategies=[_BuyOnceAt25(timeframes=[Timeframe.D1])],
        warmup=2, allow_short=False,
    ).run_portfolio(series)

    # All entries fire on the same bar and never close until liquidation, so the
    # number of distinct positions ever opened equals the concurrent cap.
    assert len(result.trades) == expected_concurrent
