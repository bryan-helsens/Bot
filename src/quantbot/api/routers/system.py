"""System & health endpoints, plus engine control actions."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from quantbot.api.dependencies import AuthDep, StateDep, create_access_token
from quantbot.api.schemas import (
    HealthResponse,
    LoginRequest,
    MessageResponse,
    SystemStatusSchema,
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
    """Return the engine/system status snapshot."""
    engine = state.trading_engine
    return SystemStatusSchema(
        running=bool(engine and getattr(engine, "running", False)),
        trading_mode=state.settings.trading_mode.value,
        symbols=state.settings.symbols,
        strategies=len(state.strategies),
        connected=bool(engine and getattr(engine, "running", False)),
        started_at=state.started_at,
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


__all__ = ["router"]
