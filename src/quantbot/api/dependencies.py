"""API dependencies: shared application state and JWT authentication."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from quantbot.core.config import Settings, get_settings

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)
_ALGORITHM = "HS256"


@dataclass
class AppState:
    """Shared references the API reads from the running engine.

    Populated by the application factory / engine at startup. Routes access this
    via :func:`get_state`; everything is optional so the API can start before the
    engine is fully wired (returning empty/placeholder data).
    """

    settings: Settings
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    portfolio: Any | None = None
    risk_engine: Any | None = None
    trading_engine: Any | None = None
    performance: Any | None = None
    database: Any | None = None
    redis: Any | None = None
    strategies: list[Any] = field(default_factory=list)


# Module-level singleton set by create_app(); kept simple and explicit.
_state: AppState | None = None


def set_state(state: AppState) -> None:
    """Install the shared application state (called by the app factory)."""
    global _state
    _state = state


def get_state() -> AppState:
    """Return the shared application state (raises if not initialised)."""
    if _state is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready"
        )
    return _state


def trade_history(state: AppState) -> list:
    """Closed-trade history from the (persisted) portfolio, else the perf tracker."""
    pf = state.portfolio
    if pf is not None and hasattr(pf, "closed_trades"):
        return pf.closed_trades
    if state.performance is not None:
        return list(state.performance.trades)
    return []


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def create_access_token(subject: str, settings: Settings | None = None) -> tuple[str, int]:
    """Create a signed JWT for *subject*; return ``(token, expires_in_seconds)``."""
    settings = settings or get_settings()
    expire_minutes = settings.api.jwt_expire_minutes
    expire = datetime.now(UTC) + timedelta(minutes=expire_minutes)
    payload = {"sub": subject, "exp": expire, "iat": datetime.now(UTC)}
    token = jwt.encode(
        payload, settings.api.jwt_secret.get_secret_value(), algorithm=_ALGORITHM
    )
    return token, expire_minutes * 60


def verify_token(token: str, settings: Settings) -> str:
    """Decode and validate a JWT, returning the subject."""
    try:
        payload = jwt.decode(
            token, settings.api.jwt_secret.get_secret_value(), algorithms=[_ALGORITHM]
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        ) from exc
    subject = payload.get("sub")
    if not subject:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return str(subject)


async def require_auth(
    token: Annotated[str | None, Depends(_oauth2_scheme)],
    state: Annotated[AppState, Depends(get_state)],
) -> str:
    """FastAPI dependency enforcing a valid bearer token; returns the subject."""
    # Auth can be disabled in development by leaving the default JWT secret.
    if not state.settings.is_production and state.settings.api.jwt_secret.get_secret_value() == "change_me":
        return "dev"
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return verify_token(token, state.settings)


StateDep = Annotated[AppState, Depends(get_state)]
AuthDep = Annotated[str, Depends(require_auth)]


__all__ = [
    "AppState",
    "AuthDep",
    "StateDep",
    "create_access_token",
    "get_state",
    "require_auth",
    "set_state",
    "verify_token",
]
