"""Portfolio summary and equity-curve endpoints."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter

from quantbot.api.dependencies import AuthDep, StateDep
from quantbot.api.schemas import EquityPoint, PortfolioSchema

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
