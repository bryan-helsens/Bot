"""Risk status and risk-event endpoints."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter

from quantbot.api.dependencies import AuthDep, StateDep
from quantbot.api.schemas import RiskEventSchema, RiskStatusSchema

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("/status", response_model=RiskStatusSchema)
async def risk_status(state: StateDep, _: AuthDep) -> RiskStatusSchema:
    """Return the current risk-engine status."""
    risk = state.risk_engine
    pf = state.portfolio
    if risk is None:
        return _empty(state)
    cb = risk.circuit_breaker.state()
    equity = pf.equity() if pf is not None else Decimal("0")
    return RiskStatusSchema(
        circuit_breaker_active=cb.tripped,
        circuit_breaker_cooldown=cb.cooldown_remaining,
        emergency_shutdown=risk.emergency.active,
        emergency_reason=risk.emergency.reason,
        daily_pnl=str(risk.limits.daily_pnl()),
        weekly_pnl=str(risk.limits.weekly_pnl()),
        current_drawdown=str(risk.limits.current_drawdown(equity)),
        open_trades=pf.positions.open_count if pf is not None else 0,
        max_open_trades=state.settings.risk.max_open_trades,
    )


@router.get("/events", response_model=list[RiskEventSchema])
async def risk_events(state: StateDep, _: AuthDep) -> list[RiskEventSchema]:
    """Return recent risk events from the database, if available."""
    if state.database is None:
        return []
    from quantbot.infrastructure.db.repositories import RiskEventRepository

    async with state.database.session() as session:
        rows = await RiskEventRepository(session).recent(limit=200)
    return [
        RiskEventSchema(
            event_type=r.event_type, severity=r.severity, symbol=r.symbol,
            reason=r.reason, created_at=r.created_at,
        )
        for r in rows
    ]


def _empty(state) -> RiskStatusSchema:
    z = str(Decimal("0"))
    return RiskStatusSchema(
        circuit_breaker_active=False, circuit_breaker_cooldown=0.0,
        emergency_shutdown=False, emergency_reason="", daily_pnl=z, weekly_pnl=z,
        current_drawdown=z, open_trades=0, max_open_trades=state.settings.risk.max_open_trades,
    )


__all__ = ["router"]
