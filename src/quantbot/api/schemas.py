"""Pydantic schemas for the API (request/response models)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TokenResponse(BaseModel):
    """JWT access-token response."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class LoginRequest(BaseModel):
    """Login credentials."""

    username: str
    password: str


class TestOrderRequest(BaseModel):
    """A manual test order from the dashboard (buy/sell a symbol at market)."""

    symbol: str
    side: str  # "buy" | "sell"


class LogEntry(BaseModel):
    """A single recent log line for the dashboard log panel."""

    ts: str | None = None
    level: str = "info"
    event: str = ""
    logger: str = ""
    data: dict[str, str] = {}


class HealthResponse(BaseModel):
    """Service health summary."""

    status: str
    version: str
    trading_mode: str
    uptime_seconds: float
    database: bool
    redis: bool


class TradeSchema(BaseModel):
    """A realised trade."""

    id: str
    symbol: str
    side: str
    strategy: str | None = None
    quantity: str
    entry_price: str
    exit_price: str
    net_pnl: str
    return_pct: str
    exit_reason: str
    opened_at: datetime
    closed_at: datetime


class PositionSchema(BaseModel):
    """An open position."""

    id: str
    symbol: str
    side: str
    quantity: str
    entry_price: str
    mark_price: str | None = None
    unrealized_pnl: str
    stop_loss: str | None = None
    leverage: int
    opened_at: datetime


class PortfolioSchema(BaseModel):
    """Portfolio-level summary."""

    equity: str
    cash: str
    unrealized_pnl: str
    realized_pnl: str
    exposure: str
    exposure_pct: str
    total_return_pct: str
    open_positions: int
    max_drawdown: str


class EquityPoint(BaseModel):
    """One point on the equity curve."""

    timestamp: str
    equity: float


class StrategyPerformanceSchema(BaseModel):
    """Performance metrics for one strategy."""

    strategy: str
    net_profit: float
    profit_factor: float
    win_rate: float
    sharpe_ratio: float
    max_drawdown: float
    total_trades: int


class RiskStatusSchema(BaseModel):
    """Current risk-engine status."""

    circuit_breaker_active: bool
    circuit_breaker_cooldown: float
    emergency_shutdown: bool
    emergency_reason: str
    daily_pnl: str
    weekly_pnl: str
    current_drawdown: str
    open_trades: int
    max_open_trades: int


class RiskEventSchema(BaseModel):
    """A recorded risk event."""

    event_type: str
    severity: str
    symbol: str | None = None
    reason: str
    created_at: datetime


class SystemStatusSchema(BaseModel):
    """Engine/system status snapshot."""

    running: bool
    trading_mode: str
    symbols: list[str]
    strategies: int
    connected: bool
    started_at: datetime | None = None


class MessageResponse(BaseModel):
    """A simple message acknowledgement."""

    detail: str
    ok: bool = True


class ActionRequest(BaseModel):
    """A control action (e.g. emergency stop)."""

    reason: str = Field(default="manual", max_length=200)


__all__ = [
    "ActionRequest",
    "EquityPoint",
    "HealthResponse",
    "LoginRequest",
    "MessageResponse",
    "PortfolioSchema",
    "PositionSchema",
    "RiskEventSchema",
    "RiskStatusSchema",
    "StrategyPerformanceSchema",
    "SystemStatusSchema",
    "TokenResponse",
    "TradeSchema",
]
