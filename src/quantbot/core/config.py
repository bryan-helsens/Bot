"""Application configuration via environment variables / ``.env``.

Settings are loaded by `pydantic-settings`. Nested sections use ``__`` as the
delimiter, e.g. ``RISK__MAX_OPEN_TRADES=5`` maps to ``settings.risk.max_open_trades``.

Comma-separated environment values (symbol lists, timeframes, CORS origins) are
parsed with :class:`~pydantic_settings.NoDecode` so the raw string reaches the
``BeforeValidator`` instead of pydantic attempting JSON decoding first.

Call :func:`get_settings` to obtain a process-wide cached instance.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field, SecretStr, computed_field, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from quantbot.core.constants import (
    Environment,
    LogFormat,
    MarginMode,
    MarketType,
    Severity,
    SizingMethod,
    Timeframe,
    TradingMode,
)

# ---------------------------------------------------------------------------
# Parsing helpers for comma-separated env values
# ---------------------------------------------------------------------------


def _split_csv(value: Any) -> Any:
    """Split a comma-separated string into a trimmed list (pass-through lists)."""
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


def _parse_tp_levels(value: Any) -> Any:
    """Parse ``"price_frac:size_frac,..."`` into a list of ``[Decimal, Decimal]``."""
    if not isinstance(value, str):
        return value
    levels: list[list[Decimal]] = []
    for chunk in value.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        price_str, _, size_str = chunk.partition(":")
        if not size_str:
            raise ValueError(f"Invalid take-profit level {chunk!r}; expected 'price:size'")
        levels.append([Decimal(price_str.strip()), Decimal(size_str.strip())])
    return levels


CsvStrList = Annotated[list[str], NoDecode, BeforeValidator(_split_csv)]
CsvTimeframeList = Annotated[list[Timeframe], NoDecode, BeforeValidator(_split_csv)]
TpLevelList = Annotated[list[tuple[Decimal, Decimal]], NoDecode, BeforeValidator(_parse_tp_levels)]


# ---------------------------------------------------------------------------
# Nested sections
# ---------------------------------------------------------------------------


class BitvavoSettings(BaseModel):
    """Bitvavo API connectivity (EU/Belgium-friendly spot exchange).

    Bitvavo has NO testnet: LIVE mode there is always real money and therefore
    requires the ALLOW_LIVE_REAL_ORDERS opt-in. Validate with TRADING_MODE=paper
    (real market data, simulated fills) first.
    """

    api_key: str = ""
    api_secret: SecretStr = SecretStr("")
    rest_base_url: str = "https://api.bitvavo.com/v2"
    access_window_ms: Annotated[int, Field(gt=0)] = 10000
    #: Audit id sent with orders (required by Bitvavo's MiCA-era API rules).
    operator_id: int = 1001


class BinanceSettings(BaseModel):
    """Binance API connectivity and trading defaults."""

    market: MarketType = MarketType.SPOT
    testnet: bool = True
    api_key: str = ""
    api_secret: SecretStr = SecretStr("")
    rest_base_url: str = ""
    ws_base_url: str = ""
    recv_window: int = 5000
    default_leverage: Annotated[int, Field(ge=1)] = 1
    margin_mode: MarginMode = MarginMode.ISOLATED

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resolved_rest_url(self) -> str:
        """Effective REST base URL (explicit override wins)."""
        if self.rest_base_url:
            return self.rest_base_url.rstrip("/")
        return _BINANCE_REST_URLS[(self.market, self.testnet)]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resolved_ws_url(self) -> str:
        """Effective WebSocket base URL (explicit override wins)."""
        if self.ws_base_url:
            return self.ws_base_url.rstrip("/")
        return _BINANCE_WS_URLS[(self.market, self.testnet)]


_BINANCE_REST_URLS: dict[tuple[MarketType, bool], str] = {
    (MarketType.SPOT, False): "https://api.binance.com",
    (MarketType.SPOT, True): "https://testnet.binance.vision",
    (MarketType.FUTURES, False): "https://fapi.binance.com",
    (MarketType.FUTURES, True): "https://testnet.binancefuture.com",
}

_BINANCE_WS_URLS: dict[tuple[MarketType, bool], str] = {
    (MarketType.SPOT, False): "wss://stream.binance.com:9443",
    (MarketType.SPOT, True): "wss://stream.testnet.binance.vision",
    (MarketType.FUTURES, False): "wss://fstream.binance.com",
    (MarketType.FUTURES, True): "wss://stream.binancefuture.com",
}


class RateLimitSettings(BaseModel):
    """Client-side rate-limit guards (kept below Binance hard limits)."""

    max_weight_per_minute: Annotated[int, Field(gt=0)] = 5500
    max_orders_per_10s: Annotated[int, Field(gt=0)] = 45
    max_orders_per_day: Annotated[int, Field(gt=0)] = 150_000


class WebSocketSettings(BaseModel):
    """WebSocket reconnect/heartbeat tuning."""

    reconnect_initial_delay: Annotated[float, Field(gt=0)] = 1.0
    reconnect_max_delay: Annotated[float, Field(gt=0)] = 60.0
    reconnect_factor: Annotated[float, Field(gt=1)] = 2.0
    ping_interval: Annotated[float, Field(gt=0)] = 20.0
    ping_timeout: Annotated[float, Field(gt=0)] = 10.0
    stale_timeout: Annotated[float, Field(gt=0)] = 90.0


class AggregatorSettings(BaseModel):
    """Signal-confluence aggregation thresholds."""

    min_consensus: Annotated[int, Field(ge=1)] = 2
    # Minimum *combined* weighted strength across agreeing strategies. Because
    # strengths are summed (one vote per strategy), this may exceed 1.0.
    min_strength: Annotated[float, Field(ge=0)] = 0.5
    window_seconds: Annotated[int, Field(gt=0)] = 60


class RiskSettings(BaseModel):
    """The full risk-management configuration."""

    sizing_method: SizingMethod = SizingMethod.RISK
    risk_per_trade: Annotated[Decimal, Field(gt=0, le=1)] = Decimal("0.01")
    kelly_cap: Annotated[Decimal, Field(gt=0, le=1)] = Decimal("0.25")
    default_stop_loss_pct: Annotated[Decimal, Field(gt=0, lt=1)] = Decimal("0.02")
    default_take_profit_pct: Annotated[Decimal, Field(gt=0)] = Decimal("0.04")
    trailing_stop_pct: Annotated[Decimal, Field(ge=0, lt=1)] = Decimal("0.015")
    break_even_trigger_pct: Annotated[Decimal, Field(ge=0)] = Decimal("0.01")
    take_profit_levels: TpLevelList = Field(
        default_factory=lambda: [
            (Decimal("0.02"), Decimal("0.5")),
            (Decimal("0.04"), Decimal("0.3")),
            (Decimal("0.06"), Decimal("0.2")),
        ]
    )
    max_open_trades: Annotated[int, Field(ge=1)] = 5
    # When True, an opposite signal closes an open position. Default False: let
    # winners/losers run to TP/SL/trailing instead of churning on every flip — the
    # signal-flip exits were tiny round-trips that just bled fees (43% of gross).
    exit_on_opposite_signal: bool = False
    # After a LOSING exit on a symbol, ignore new entry signals for it for this many
    # seconds. Stops the bot re-buying a coin that just stopped out (live data showed
    # coins re-entered and lost 3-4 times in a row). 0 disables it.
    reentry_cooldown_seconds: Annotated[int, Field(ge=0)] = 0
    max_exposure_per_coin: Annotated[Decimal, Field(gt=0, le=1)] = Decimal("0.20")
    max_portfolio_exposure: Annotated[Decimal, Field(gt=0, le=1)] = Decimal("0.60")
    max_daily_loss: Annotated[Decimal, Field(gt=0, le=1)] = Decimal("0.05")
    max_weekly_loss: Annotated[Decimal, Field(gt=0, le=1)] = Decimal("0.10")
    max_drawdown: Annotated[Decimal, Field(gt=0, le=1)] = Decimal("0.20")
    max_correlation: Annotated[Decimal, Field(gt=0, le=1)] = Decimal("0.80")
    correlation_lookback: Annotated[int, Field(ge=10)] = 200
    circuit_breaker_losses: Annotated[int, Field(ge=1)] = 4
    circuit_breaker_cooldown: Annotated[int, Field(ge=0)] = 3600
    emergency_stop_enabled: bool = True
    allow_martingale: bool = False
    allow_unlimited_averaging: bool = False
    max_averaging_entries: Annotated[int, Field(ge=1)] = 3

    @model_validator(mode="after")
    def _validate_tp_levels(self) -> RiskSettings:
        """Ensure the take-profit size fractions do not exceed the full position."""
        total = sum((size for _, size in self.take_profit_levels), Decimal("0"))
        if total > Decimal("1"):
            raise ValueError(
                f"take_profit_levels size fractions sum to {total} (> 1.0)"
            )
        return self


class BacktestSettings(BaseModel):
    """Simulation cost model and starting capital."""

    initial_capital: Annotated[Decimal, Field(gt=0)] = Decimal("10000")
    commission: Annotated[Decimal, Field(ge=0, lt=1)] = Decimal("0.001")
    slippage: Annotated[Decimal, Field(ge=0, lt=1)] = Decimal("0.0005")
    spread: Annotated[Decimal, Field(ge=0, lt=1)] = Decimal("0.0002")


class DatabaseSettings(BaseModel):
    """PostgreSQL connection settings."""

    host: str = "localhost"
    port: int = 5432
    name: str = "quantbot"
    user: str = "quantbot"
    password: SecretStr = SecretStr("")
    dsn: str = ""
    pool_size: Annotated[int, Field(ge=1)] = 10
    max_overflow: Annotated[int, Field(ge=0)] = 20
    echo: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def url(self) -> str:
        """Async SQLAlchemy DSN (explicit ``dsn`` wins)."""
        if self.dsn:
            return self.dsn
        pwd = self.password.get_secret_value()
        return (
            f"postgresql+asyncpg://{self.user}:{pwd}"
            f"@{self.host}:{self.port}/{self.name}"
        )

    @property
    def sync_url(self) -> str:
        """Synchronous DSN (psycopg) used by Alembic migrations."""
        return self.url.replace("+asyncpg", "+psycopg")


class RedisSettings(BaseModel):
    """Redis connection settings."""

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: SecretStr = SecretStr("")
    url: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resolved_url(self) -> str:
        """Effective Redis URL (explicit ``url`` wins)."""
        if self.url:
            return self.url
        pwd = self.password.get_secret_value()
        auth = f":{pwd}@" if pwd else ""
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"


class ApiSettings(BaseModel):
    """FastAPI monitoring-backend settings."""

    enabled: bool = True
    host: str = "0.0.0.0"  # noqa: S104 - intended to bind all interfaces in container
    port: int = 8000
    jwt_secret: SecretStr = SecretStr("change_me")
    jwt_expire_minutes: Annotated[int, Field(gt=0)] = 1440
    cors_origins: CsvStrList = Field(default_factory=lambda: ["http://localhost:5173"])
    # Dashboard login. When a password is set, the API requires authentication even
    # in development — set this (plus a real JWT secret) before exposing the
    # dashboard beyond an SSH tunnel or going to real money.
    dashboard_user: str = "admin"
    dashboard_password: SecretStr = SecretStr("")


class SecuritySettings(BaseModel):
    """Encryption and auditing settings."""

    encryption_key: SecretStr = SecretStr("")
    audit_enabled: bool = True


class NotificationSettings(BaseModel):
    """Notification channels and thresholds."""

    enabled: bool = True
    min_severity: Severity = Severity.INFO

    telegram_enabled: bool = False
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_chat_id: str = ""

    discord_enabled: bool = False
    discord_webhook_url: SecretStr = SecretStr("")

    email_enabled: bool = False
    email_smtp_host: str = "smtp.gmail.com"
    email_smtp_port: int = 587
    email_username: str = ""
    email_password: SecretStr = SecretStr("")
    email_from: str = ""
    email_to: CsvStrList = Field(default_factory=list)


class AiSettings(BaseModel):
    """Optional machine-learning module settings."""

    enabled: bool = False
    model_dir: str = "models"
    min_confidence: Annotated[float, Field(ge=0, le=1)] = 0.6
    walk_forward_folds: Annotated[int, Field(ge=2)] = 5

    model_config = {"protected_namespaces": ()}


# ---------------------------------------------------------------------------
# Root settings
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    """Top-level application settings (singleton via :func:`get_settings`)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Environment = Environment.DEVELOPMENT
    log_level: str = "INFO"
    log_format: LogFormat = LogFormat.CONSOLE
    timezone: str = "UTC"
    trading_mode: TradingMode = TradingMode.PAPER
    # Safety interlock for REAL-money live trading. Live mode currently lacks
    # exchange-fill reconciliation (see docs/LIVE_SAFETY.md); paper/testnet is safe,
    # but the runtime refuses to start LIVE mode unless this is explicitly set true,
    # so a config slip can never put real money at risk by accident.
    allow_live_real_orders: bool = False

    #: Which exchange adapter to trade through: "binance" or "bitvavo".
    exchange: str = "binance"
    #: Auto-detect exchange deposits/withdrawals of the quote asset while running
    #: and fold them into the bot's capital WITHOUT counting them as profit.
    auto_sync_deposits: bool = True

    symbols: CsvStrList = Field(default_factory=lambda: ["BTCUSDT"])
    timeframes: CsvTimeframeList = Field(default_factory=lambda: [Timeframe.H1])
    quote_asset: str = "USDT"
    strategies_config: str = "config/strategies.yaml"
    # Where live/paper engine state (cash, positions, equity curve) is persisted so
    # a restart resumes seamlessly. Empty disables persistence.
    state_file: str = "data/state.json"

    binance: BinanceSettings = Field(default_factory=BinanceSettings)
    bitvavo: BitvavoSettings = Field(default_factory=BitvavoSettings)
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings)
    websocket: WebSocketSettings = Field(default_factory=WebSocketSettings)
    aggregator: AggregatorSettings = Field(default_factory=AggregatorSettings)
    risk: RiskSettings = Field(default_factory=RiskSettings)
    backtest: BacktestSettings = Field(default_factory=BacktestSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    api: ApiSettings = Field(default_factory=ApiSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)
    ai: AiSettings = Field(default_factory=AiSettings)

    @property
    def is_production(self) -> bool:
        """Whether running in the production environment."""
        return self.environment is Environment.PRODUCTION

    @property
    def is_live(self) -> bool:
        """Whether the engine routes real (or testnet) orders."""
        return self.trading_mode is TradingMode.LIVE

    @property
    def uses_fake_money(self) -> bool:
        """Whether LIVE orders would hit fake money (Binance testnet only).

        Bitvavo has no testnet, so LIVE there is always real money and needs the
        ALLOW_LIVE_REAL_ORDERS opt-in.
        """
        return self.exchange == "binance" and self.binance.testnet

    @model_validator(mode="after")
    def _production_safety(self) -> Settings:
        """Refuse unsafe production configurations early."""
        if self.environment is Environment.PRODUCTION and self.is_live:
            if not self.binance.api_key or not self.binance.api_secret.get_secret_value():
                raise ValueError("Live production trading requires Binance API credentials")
            if self.api.jwt_secret.get_secret_value() in ("", "change_me"):
                raise ValueError("Refusing to start production API with the default JWT secret")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached :class:`Settings` instance."""
    return Settings()


def reload_settings() -> Settings:
    """Clear the cache and reload settings (useful in tests)."""
    get_settings.cache_clear()
    return get_settings()


__all__ = [
    "AggregatorSettings",
    "AiSettings",
    "ApiSettings",
    "BacktestSettings",
    "BinanceSettings",
    "DatabaseSettings",
    "NotificationSettings",
    "RateLimitSettings",
    "RedisSettings",
    "RiskSettings",
    "SecuritySettings",
    "Settings",
    "WebSocketSettings",
    "get_settings",
    "reload_settings",
]
