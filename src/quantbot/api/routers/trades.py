"""Trade-history endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from quantbot.api.dependencies import AuthDep, StateDep, trade_history
from quantbot.api.schemas import TradeSchema

router = APIRouter(prefix="/trades", tags=["trades"])


@router.get("", response_model=list[TradeSchema])
async def recent_trades(
    state: StateDep,
    _: AuthDep,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[TradeSchema]:
    """Return the most recent realised trades (from the DB if available)."""
    trades = []
    if state.database is not None:
        from quantbot.infrastructure.db.repositories import TradeRepository

        async with state.database.session() as session:
            trades = await TradeRepository(session).recent(limit=limit)
    else:
        trades = list(reversed(trade_history(state)))[:limit]

    return [
        TradeSchema(
            id=t.id, symbol=t.symbol, side=t.side.value, strategy=t.strategy,
            quantity=str(t.quantity), entry_price=str(t.entry_price),
            exit_price=str(t.exit_price), net_pnl=str(t.net_pnl),
            return_pct=str(t.return_pct), exit_reason=t.exit_reason.value,
            opened_at=t.opened_at, closed_at=t.closed_at,
        )
        for t in trades
    ]


__all__ = ["router"]
