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


class CapitalRequest(BaseModel):
    """Record a deposit (positive) or withdrawal (negative) of capital — NOT profit."""

    amount: str


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


class CoinDetailSchema(BaseModel):
    """Everything the bot did with one coin: position + trade history + stats."""

    symbol: str
    has_position: bool = False
    side: str | None = None
    quantity: str = "0"
    entry_price: str | None = None
    opened_at: datetime | None = None
    mark_price: str | None = None
    value: str = "0"
    unrealized_pnl: str = "0"
    stop_loss: str | None = None
    realized_pnl: str = "0"
    trade_count: int = 0
    win_rate: float = 0.0
    total_fees: str = "0"
    trades: list[TradeSchema] = []
    rsi: float | None = None
    prices: list[float] = []
    times: list[str] = []
    price_timeframe: str | None = None


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


class DailyPnlPoint(BaseModel):
    """Realised PnL aggregated for one day."""

    date: str
    pnl: float
    trades: int


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
    paused: bool = False
    last_candle_age: float | None = None
    last_trade_age: float | None = None
    active_streams: int = 0
    open_positions: int = 0
    candle_stale: bool = False


class TradingStatsSchema(BaseModel):
    """Realised performance summary for the dashboard."""

    today_pnl: str = "0"
    week_pnl: str = "0"
    today_trades: int = 0
    total_trades: int = 0
    win_rate: float = 0.0
    total_fees: str = "0"
    best_trade: str = "0"
    worst_trade: str = "0"


class ConfigSchema(BaseModel):
    """Read-only view of the active risk/universe configuration."""

    sizing_method: str
    risk_per_trade: str
    default_stop_loss_pct: str
    trailing_stop_pct: str
    take_profit_levels: list[str]
    max_open_trades: int
    max_exposure_per_coin: str
    max_portfolio_exposure: str
    max_daily_loss: str
    max_drawdown: str
    symbols: list[str]
    timeframes: list[str]
    min_consensus: int


class MessageResponse(BaseModel):
    """A simple message acknowledgement."""

    detail: str
    ok: bool = True


class ActionRequest(BaseModel):
    """A control action (e.g. emergency stop)."""

    reason: str = Field(default="manual", max_length=200)


class ScannerRow(BaseModel):
    """One coin's live indicator snapshot for the market scanner."""

    symbol: str
    price: float
    rsi: float | None = None
    ema_fast: float | None = None
    ema_slow: float | None = None
    trend: str | None = None
    ema_gap_pct: float | None = None
    signal: str = "neutral"
    timeframe: str | None = None
    has_position: bool = False
    muted: bool = False


class CoinAnalytics(BaseModel):
    """Per-coin or per-strategy realised-performance breakdown (amounts in quote)."""

    name: str
    trades: int = 0
    net_pnl: str = "0"
    win_rate: float = 0.0
    wins: int = 0
    losses: int = 0
    avg_win: str = "0"
    avg_loss: str = "0"
    profit_factor: float = 0.0
    total_fees: str = "0"
    avg_hold_seconds: float = 0.0
    best: str = "0"
    worst: str = "0"


class AnalyticsSchema(BaseModel):
    """Full trade-analytics payload: overall totals + per-coin + per-strategy."""

    quote_asset: str = "USDT"
    total_trades: int = 0
    net_pnl: str = "0"
    gross_profit: str = "0"
    gross_loss: str = "0"
    win_rate: float = 0.0
    profit_factor: float = 0.0
    expectancy: str = "0"
    avg_hold_seconds: float = 0.0
    total_fees: str = "0"
    by_coin: list[CoinAnalytics] = Field(default_factory=list)
    by_strategy: list[CoinAnalytics] = Field(default_factory=list)
    by_exit_reason: dict[str, int] = Field(default_factory=dict)


class AssetBalance(BaseModel):
    """A single asset's exchange balance."""

    asset: str
    free: float = 0.0
    locked: float = 0.0
    total: float = 0.0


class CapitalEntry(BaseModel):
    """A recorded deposit/withdrawal (NOT profit)."""

    ts: str | None = None
    amount: float = 0.0
    equity_after: float | None = None


class AccountSchema(BaseModel):
    """Account overview: exchange wallet vs bot equity + per-asset balances."""

    quote_asset: str = "USDT"
    wallet_equity: float | None = None
    bot_equity: float = 0.0
    bot_cash: float = 0.0
    assets: list[AssetBalance] = Field(default_factory=list)
    capital_history: list[CapitalEntry] = Field(default_factory=list)


__all__ = [
    "AccountSchema",
    "ActionRequest",
    "AnalyticsSchema",
    "AssetBalance",
    "CapitalEntry",
    "CoinAnalytics",
    "EquityPoint",
    "HealthResponse",
    "LoginRequest",
    "MessageResponse",
    "PortfolioSchema",
    "PositionSchema",
    "RiskEventSchema",
    "RiskStatusSchema",
    "ScannerRow",
    "StrategyPerformanceSchema",
    "SystemStatusSchema",
    "TokenResponse",
    "TradeSchema",
]
