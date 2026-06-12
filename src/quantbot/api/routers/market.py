"""Market scanner: live per-coin indicators so you can see WHY the bot trades
(or waits) and which coins are closest to a signal."""

from __future__ import annotations

from fastapi import APIRouter

from quantbot.api.dependencies import AuthDep, StateDep
from quantbot.api.schemas import ScannerRow

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/scanner", response_model=list[ScannerRow])
async def scanner(state: StateDep, _: AuthDep) -> list[ScannerRow]:
    """Live RSI / EMA / trend snapshot for every warmed-up coin."""
    engine = state.trading_engine
    if engine is None or not hasattr(engine, "market_scanner"):
        return []
    return [ScannerRow(**row) for row in engine.market_scanner()]


__all__ = ["router"]
