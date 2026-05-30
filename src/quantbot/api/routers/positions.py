"""Open-positions endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from quantbot.api.dependencies import AuthDep, StateDep
from quantbot.api.schemas import PositionSchema

router = APIRouter(prefix="/positions", tags=["positions"])


@router.get("", response_model=list[PositionSchema])
async def open_positions(state: StateDep, _: AuthDep) -> list[PositionSchema]:
    """List all currently-open positions."""
    pf = state.portfolio
    if pf is None:
        return []
    out: list[PositionSchema] = []
    for p in pf.positions.all_open():
        out.append(
            PositionSchema(
                id=p.id,
                symbol=p.symbol,
                side=p.side.value,
                quantity=str(p.quantity),
                entry_price=str(p.entry_price),
                mark_price=str(p.mark_price) if p.mark_price is not None else None,
                unrealized_pnl=str(p.unrealized_pnl()),
                stop_loss=str(p.stop_loss) if p.stop_loss is not None else None,
                leverage=p.leverage,
                opened_at=p.opened_at,
            )
        )
    return out


__all__ = ["router"]
