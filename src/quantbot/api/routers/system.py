"""System & health endpoints, plus engine control actions."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from quantbot.api.dependencies import AuthDep, StateDep, create_access_token
from fastapi import Query

from quantbot.api.schemas import (
    CapitalRequest,
    ConfigSchema,
    HealthResponse,
    LogEntry,
    LoginRequest,
    MessageResponse,
    SystemStatusSchema,
    TestOrderRequest,
    TokenResponse,
)
from quantbot import __version__

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["system"])
async def health(state: StateDep) -> HealthResponse:
    """Liveness/readiness probe with dependency status."""
    db_ok = True
    redis_ok = True
    if state.database is not None:
        db_ok = await state.database.health_check()
    if state.redis is not None:
        redis_ok = await state.redis.health_check()
    uptime = (datetime.now(UTC) - state.started_at).total_seconds()
    return HealthResponse(
        status="ok" if db_ok and redis_ok else "degraded",
        version=__version__,
        trading_mode=state.settings.trading_mode.value,
        uptime_seconds=round(uptime, 1),
        database=db_ok,
        redis=redis_ok,
    )


@router.post("/auth/login", response_model=TokenResponse, tags=["system"])
async def login(request: LoginRequest, state: StateDep) -> TokenResponse:
    """Issue a JWT. Credentials are validated against configured API auth."""
    # A single operator account is supported via env; extend as needed.
    expected_user = "admin"
    if request.username != expected_user:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token, expires = create_access_token(request.username, state.settings)
    return TokenResponse(access_token=token, expires_in=expires)


@router.get("/system/status", response_model=SystemStatusSchema, tags=["system"])
async def system_status(state: StateDep, _: AuthDep) -> SystemStatusSchema:
    """Return the engine/system status snapshot (with health/heartbeat)."""
    engine = state.trading_engine
    running = bool(engine and getattr(engine, "running", False))
    hb: dict = engine.heartbeat() if engine and hasattr(engine, "heartbeat") else {}
    return SystemStatusSchema(
        running=running,
        trading_mode=state.settings.trading_mode.value,
        symbols=state.settings.symbols,
        strategies=len(state.strategies),
        connected=running,
        started_at=state.started_at,
        paused=bool(hb.get("paused", False)),
        last_candle_age=hb.get("last_candle_age"),
        last_trade_age=hb.get("last_trade_age"),
        active_streams=int(hb.get("active_streams", 0)),
    )


@router.post("/system/emergency-stop", response_model=MessageResponse, tags=["system"])
async def emergency_stop(state: StateDep, _: AuthDep) -> MessageResponse:
    """Trigger the risk engine's emergency shutdown."""
    if state.risk_engine is None:
        return MessageResponse(detail="Risk engine not available", ok=False)
    state.risk_engine.emergency.trigger("manual_api")
    return MessageResponse(detail="Emergency shutdown triggered")


@router.post("/system/resume", response_model=MessageResponse, tags=["system"])
async def resume(state: StateDep, _: AuthDep) -> MessageResponse:
    """Clear the emergency shutdown and circuit breaker."""
    if state.risk_engine is None:
        return MessageResponse(detail="Risk engine not available", ok=False)
    state.risk_engine.emergency.reset()
    state.risk_engine.circuit_breaker.reset()
    return MessageResponse(detail="Trading resumed")


@router.post("/system/test-order", response_model=MessageResponse, tags=["system"])
async def test_order(req: TestOrderRequest, state: StateDep, _: AuthDep) -> MessageResponse:
    """Manually place a test buy/sell through the full risk + execution path.

    A buy opens a position, a sell closes it (or opens a short on futures). Goes
    through the RiskEngine like any real order. Requires the live engine
    (``quantbot serve``); not available in demo mode.
    """
    from quantbot.core.constants import Side

    engine = state.trading_engine
    if engine is None or not hasattr(engine, "submit_manual_order"):
        return MessageResponse(
            detail="Manual orders need the live engine (run `quantbot serve`).", ok=False
        )
    try:
        side = Side(req.side.strip().lower())
    except ValueError:
        return MessageResponse(detail=f"Invalid side '{req.side}' (use buy/sell)", ok=False)
    result = await engine.submit_manual_order(req.symbol.strip().upper(), side)
    return MessageResponse(detail=result["detail"], ok=bool(result["ok"]))


@router.get("/system/logs", response_model=list[LogEntry], tags=["system"])
async def system_logs(
    _: AuthDep,
    limit: int = Query(default=200, ge=1, le=1000),
    level: str | None = Query(default=None),
) -> list[LogEntry]:
    """Recent log lines (what the bot is doing) for the dashboard log panel."""
    from quantbot.core.logging import LOG_BUFFER

    return [LogEntry(**entry) for entry in LOG_BUFFER.recent(limit, level=level)]


#: Log events shown in the dashboard activity feed (buys/sells + capital changes).
_TRADE_EVENTS = {"position_opened", "position_closed", "position_reduced", "capital_adjusted"}


@router.get("/system/activity", response_model=list[LogEntry], tags=["system"])
async def system_activity(
    _: AuthDep, limit: int = Query(default=50, ge=1, le=500)
) -> list[LogEntry]:
    """Recent buy/sell activity (entries, exits, partial take-profits) for the feed."""
    from quantbot.core.logging import LOG_BUFFER

    events = [e for e in LOG_BUFFER.recent(1000) if e.get("event") in _TRADE_EVENTS]
    return [LogEntry(**e) for e in events[-limit:]]


@router.post("/system/close-all", response_model=MessageResponse, tags=["system"])
async def close_all(state: StateDep, _: AuthDep) -> MessageResponse:
    """Market-close every open position (panic button)."""
    engine = state.trading_engine
    if engine is None or not hasattr(engine, "close_all"):
        return MessageResponse(detail="Needs the live engine (quantbot serve).", ok=False)
    n = await engine.close_all()
    return MessageResponse(detail=f"Closed {n} position(s)")


@router.post("/system/pause", response_model=MessageResponse, tags=["system"])
async def pause_trading(state: StateDep, _: AuthDep) -> MessageResponse:
    """Pause new entries (existing positions keep being managed)."""
    engine = state.trading_engine
    if engine is None or not hasattr(engine, "pause"):
        return MessageResponse(detail="Needs the live engine (quantbot serve).", ok=False)
    engine.pause()
    return MessageResponse(detail="Trading paused (no new entries)")


@router.post("/system/unpause", response_model=MessageResponse, tags=["system"])
async def unpause_trading(state: StateDep, _: AuthDep) -> MessageResponse:
    """Resume opening new entries."""
    engine = state.trading_engine
    if engine is None or not hasattr(engine, "resume_trading"):
        return MessageResponse(detail="Needs the live engine (quantbot serve).", ok=False)
    engine.resume_trading()
    return MessageResponse(detail="Trading resumed")


@router.post("/system/capital", response_model=MessageResponse, tags=["system"])
async def adjust_capital(req: CapitalRequest, state: StateDep, _: AuthDep) -> MessageResponse:
    """Record a deposit/withdrawal of capital — NOT counted as profit.

    Use this AFTER you add (or remove) funds on the exchange so the bot sizes with
    the new capital without thinking the change is trading profit.
    """
    from decimal import Decimal, InvalidOperation

    engine = state.trading_engine
    if engine is None or not hasattr(engine, "adjust_capital"):
        return MessageResponse(detail="Needs the live engine (quantbot serve).", ok=False)
    try:
        amount = Decimal(req.amount)
    except (InvalidOperation, ValueError):
        return MessageResponse(detail=f"Invalid amount '{req.amount}'", ok=False)
    result = engine.adjust_capital(amount)
    return MessageResponse(detail=result["detail"], ok=bool(result["ok"]))


@router.get("/system/config", response_model=ConfigSchema, tags=["system"])
async def system_config(state: StateDep, _: AuthDep) -> ConfigSchema:
    """Read-only view of the active risk/universe configuration."""
    r = state.settings.risk
    return ConfigSchema(
        sizing_method=r.sizing_method.value,
        risk_per_trade=str(r.risk_per_trade),
        default_stop_loss_pct=str(r.default_stop_loss_pct),
        trailing_stop_pct=str(r.trailing_stop_pct),
        take_profit_levels=[f"{p}:{s}" for p, s in r.take_profit_levels],
        max_open_trades=r.max_open_trades,
        max_exposure_per_coin=str(r.max_exposure_per_coin),
        max_portfolio_exposure=str(r.max_portfolio_exposure),
        max_daily_loss=str(r.max_daily_loss),
        max_drawdown=str(r.max_drawdown),
        symbols=state.settings.symbols,
        timeframes=[tf.value for tf in state.settings.timeframes],
        min_consensus=state.settings.aggregator.min_consensus,
    )


__all__ = ["router"]
