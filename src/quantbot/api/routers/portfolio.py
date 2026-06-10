"""Portfolio summary and equity-curve endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter

from quantbot.api.dependencies import AuthDep, StateDep
from quantbot.api.schemas import EquityPoint, PortfolioSchema, TradingStatsSchema

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("", response_model=PortfolioSchema)
async def portfolio_summary(state: StateDep, _: AuthDep) -> PortfolioSchema:
    """Return the current portfolio summary."""
    pf = state.portfolio
    if pf is None:
        return _empty()
    return PortfolioSchema(
        equity=str(pf.equity()),
        cash=str(pf.cash),
        unrealized_pnl=str(pf.unrealized_pnl()),
        realized_pnl=str(pf.realized_pnl),
        exposure=str(pf.exposure()),
        exposure_pct=str(pf.exposure_pct()),
        total_return_pct=str(pf.total_return_pct()),
        open_positions=pf.positions.open_count,
        max_drawdown=str(pf.max_drawdown),
    )


@router.get("/equity-curve", response_model=list[EquityPoint])
async def equity_curve(state: StateDep, _: AuthDep) -> list[EquityPoint]:
    """Return the equity curve as time-stamped points."""
    pf = state.portfolio
    if pf is None:
        return []
    return [EquityPoint(timestamp=ts, equity=value) for ts, value in pf.equity_curve()]


@router.get("/stats", response_model=TradingStatsSchema)
async def trading_stats(state: StateDep, _: AuthDep) -> TradingStatsSchema:
    """Realised performance: today/week PnL, trade count, win rate, fees."""
    trades = list(state.performance.trades) if state.performance is not None else []
    if not trades:
        return TradingStatsSchema()
    now = datetime.now(UTC)
    day_ago, week_ago = now - timedelta(days=1), now - timedelta(days=7)

    def _closed(t):
        ts = t.closed_at
        return ts if ts.tzinfo else ts.replace(tzinfo=UTC)

    today = [t for t in trades if _closed(t) >= day_ago]
    week = [t for t in trades if _closed(t) >= week_ago]
    wins = sum(1 for t in trades if t.net_pnl > 0)
    pnls = [t.net_pnl for t in trades]
    return TradingStatsSchema(
        today_pnl=str(sum((t.net_pnl for t in today), Decimal("0"))),
        week_pnl=str(sum((t.net_pnl for t in week), Decimal("0"))),
        today_trades=len(today),
        total_trades=len(trades),
        win_rate=round(wins / len(trades), 4),
        total_fees=str(sum((t.fees for t in trades), Decimal("0"))),
        best_trade=str(max(pnls)),
        worst_trade=str(min(pnls)),
    )


@router.get("/allocation")
async def allocation(state: StateDep, _: AuthDep) -> dict[str, float]:
    """Return per-symbol allocation as fractions of equity."""
    pf = state.portfolio
    if pf is None:
        return {}
    return {symbol: float(frac) for symbol, frac in pf.allocation().items()}


def _empty() -> PortfolioSchema:
    z = str(Decimal("0"))
    return PortfolioSchema(
        equity=z, cash=z, unrealized_pnl=z, realized_pnl=z, exposure=z,
        exposure_pct=z, total_return_pct=z, open_positions=0, max_drawdown=z,
    )


__all__ = ["router"]
