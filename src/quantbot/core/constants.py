"""Core enumerations and constants shared across every layer of QuantBot.

All enums derive from :class:`str` (or :class:`~enum.IntEnum` where ordering is
meaningful) so they serialise cleanly to JSON, database columns and Pydantic
models without custom encoders. Wherever the bot interacts with the Binance API,
the canonical exchange string is used as the enum *value* so mapping is a no-op.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum, IntEnum
from typing import Final

# ---------------------------------------------------------------------------
# Numeric / precision constants
# ---------------------------------------------------------------------------

#: Decimal context precision used for all monetary maths.
DECIMAL_PRECISION: Final[int] = 28

#: A convenient zero of the correct type for accumulators.
ZERO: Final[Decimal] = Decimal("0")

#: Number of trading days per year used for annualising metrics.
TRADING_DAYS_PER_YEAR: Final[int] = 365

#: Default annual risk-free rate (fraction) for Sharpe/Sortino computations.
DEFAULT_RISK_FREE_RATE: Final[float] = 0.0


# ---------------------------------------------------------------------------
# Environment / runtime
# ---------------------------------------------------------------------------


class Environment(str, Enum):
    """Deployment environment."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class TradingMode(str, Enum):
    """How the engine routes orders."""

    LIVE = "live"
    """Orders are sent to the real (or testnet) exchange."""
    PAPER = "paper"
    """Orders are simulated locally against live market data."""
    BACKTEST = "backtest"
    """Orders are simulated against historical data."""


class LogFormat(str, Enum):
    """Log rendering format."""

    JSON = "json"
    CONSOLE = "console"


# ---------------------------------------------------------------------------
# Exchange / market
# ---------------------------------------------------------------------------


class MarketType(str, Enum):
    """Binance market segment."""

    SPOT = "spot"
    FUTURES = "futures"


class MarginMode(str, Enum):
    """Futures margin mode."""

    ISOLATED = "isolated"
    CROSS = "cross"


class ContractType(str, Enum):
    """Futures contract type."""

    PERPETUAL = "perpetual"
    CURRENT_QUARTER = "current_quarter"
    NEXT_QUARTER = "next_quarter"


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


class Side(str, Enum):
    """Order side."""

    BUY = "buy"
    SELL = "sell"

    @property
    def opposite(self) -> Side:
        """Return the opposing side (used when closing positions)."""
        return Side.SELL if self is Side.BUY else Side.BUY

    @property
    def sign(self) -> int:
        """+1 for BUY, -1 for SELL — handy for signed quantity maths."""
        return 1 if self is Side.BUY else -1


class PositionSide(str, Enum):
    """Direction of an open position."""

    LONG = "long"
    SHORT = "short"
    FLAT = "flat"

    @property
    def sign(self) -> int:
        """+1 for LONG, -1 for SHORT, 0 for FLAT."""
        if self is PositionSide.LONG:
            return 1
        if self is PositionSide.SHORT:
            return -1
        return 0

    @classmethod
    def from_side(cls, side: Side) -> PositionSide:
        """Map an entry order side to the resulting position side."""
        return cls.LONG if side is Side.BUY else cls.SHORT


class OrderType(str, Enum):
    """Supported order types."""

    MARKET = "market"
    LIMIT = "limit"
    STOP_LOSS = "stop_loss"
    STOP_LOSS_LIMIT = "stop_loss_limit"
    TAKE_PROFIT = "take_profit"
    TAKE_PROFIT_LIMIT = "take_profit_limit"
    TRAILING_STOP = "trailing_stop"


class OrderStatus(str, Enum):
    """Lifecycle state of an order."""

    PENDING = "pending"
    """Created locally, not yet acknowledged by the exchange."""
    NEW = "new"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"

    @property
    def is_open(self) -> bool:
        """Whether the order is still working on the book."""
        return self in (OrderStatus.PENDING, OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED)

    @property
    def is_terminal(self) -> bool:
        """Whether no further state changes are expected."""
        return self in (
            OrderStatus.FILLED,
            OrderStatus.CANCELED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        )


class OrderRole(str, Enum):
    """Functional role of an order within a position's lifecycle."""

    ENTRY = "entry"
    EXIT = "exit"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    TRAILING = "trailing"
    SCALE_IN = "scale_in"
    SCALE_OUT = "scale_out"


class TimeInForce(str, Enum):
    """Order time-in-force policy."""

    GTC = "gtc"  # good-till-cancelled
    IOC = "ioc"  # immediate-or-cancel
    FOK = "fok"  # fill-or-kill
    GTX = "gtx"  # good-till-crossing (post-only)


# ---------------------------------------------------------------------------
# Signals & positions
# ---------------------------------------------------------------------------


class SignalType(str, Enum):
    """The intent of a strategy signal."""

    ENTRY = "entry"
    EXIT = "exit"
    INCREASE = "increase"
    REDUCE = "reduce"
    NONE = "none"


class SignalStrength(IntEnum):
    """Discrete strength buckets (also usable as an ordered score)."""

    WEAK = 1
    MODERATE = 2
    STRONG = 3
    VERY_STRONG = 4


class PositionStatus(str, Enum):
    """Whether a position is open or closed."""

    OPEN = "open"
    CLOSED = "closed"


class ExitReason(str, Enum):
    """Why a position/trade was closed."""

    STOP_LOSS = "stop_loss"
    TRAILING_STOP = "trailing_stop"
    TAKE_PROFIT = "take_profit"
    SIGNAL = "signal"
    MANUAL = "manual"
    LIQUIDATION = "liquidation"
    EMERGENCY = "emergency"
    EXPIRED = "expired"


# ---------------------------------------------------------------------------
# Timeframes
# ---------------------------------------------------------------------------


class Timeframe(str, Enum):
    """Candle timeframes supported by the bot (values match Binance intervals)."""

    M1 = "1m"
    M3 = "3m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H4 = "4h"
    H12 = "12h"
    D1 = "1d"

    @property
    def seconds(self) -> int:
        """Duration of one candle of this timeframe in seconds."""
        return _TIMEFRAME_SECONDS[self]

    @property
    def milliseconds(self) -> int:
        """Duration of one candle of this timeframe in milliseconds."""
        return _TIMEFRAME_SECONDS[self] * 1000

    @property
    def minutes(self) -> int:
        """Duration of one candle of this timeframe in whole minutes."""
        return _TIMEFRAME_SECONDS[self] // 60

    @classmethod
    def from_string(cls, value: str) -> Timeframe:
        """Parse a timeframe from its Binance string (e.g. ``"15m"``)."""
        try:
            return cls(value.strip().lower())
        except ValueError as exc:  # pragma: no cover - defensive
            raise ValueError(
                f"Unsupported timeframe {value!r}; valid: {[tf.value for tf in cls]}"
            ) from exc


_TIMEFRAME_SECONDS: Final[dict[Timeframe, int]] = {
    Timeframe.M1: 60,
    Timeframe.M3: 180,
    Timeframe.M5: 300,
    Timeframe.M15: 900,
    Timeframe.M30: 1800,
    Timeframe.H1: 3600,
    Timeframe.H4: 14400,
    Timeframe.H12: 43200,
    Timeframe.D1: 86400,
}


# ---------------------------------------------------------------------------
# Risk
# ---------------------------------------------------------------------------


class SizingMethod(str, Enum):
    """Position-sizing strategy."""

    FIXED = "fixed"
    """Fixed notional/quantity per trade."""
    RISK = "risk"
    """Size so that the stop-loss equals a fixed fraction of equity."""
    KELLY = "kelly"
    """Kelly criterion (capped) based on historical win/loss stats."""
    VOLATILITY = "volatility"
    """ATR/volatility-adjusted sizing for constant risk units."""


class RiskDecision(str, Enum):
    """Outcome of the risk-engine validation pipeline."""

    APPROVED = "approved"
    REJECTED = "rejected"
    ADJUSTED = "adjusted"
    """Approved but with a reduced size / modified parameters."""


class RiskEventType(str, Enum):
    """Categories of risk events recorded for auditing and alerting."""

    ORDER_REJECTED = "order_rejected"
    SIZE_ADJUSTED = "size_adjusted"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    WEEKLY_LOSS_LIMIT = "weekly_loss_limit"
    MAX_DRAWDOWN = "max_drawdown"
    MAX_EXPOSURE = "max_exposure"
    MAX_OPEN_TRADES = "max_open_trades"
    CORRELATION_BLOCK = "correlation_block"
    CIRCUIT_BREAKER = "circuit_breaker"
    EMERGENCY_SHUTDOWN = "emergency_shutdown"
    MARTINGALE_BLOCKED = "martingale_blocked"
    AVERAGING_LIMIT = "averaging_limit"


class Severity(str, Enum):
    """Severity level for notifications and risk events."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        """Numeric ordering for threshold comparisons."""
        return _SEVERITY_RANK[self]

    def __ge__(self, other: object) -> bool:  # type: ignore[override]
        if not isinstance(other, Severity):
            return NotImplemented
        return self.rank >= other.rank

    def __gt__(self, other: object) -> bool:  # type: ignore[override]
        if not isinstance(other, Severity):
            return NotImplemented
        return self.rank > other.rank

    def __le__(self, other: object) -> bool:  # type: ignore[override]
        if not isinstance(other, Severity):
            return NotImplemented
        return self.rank <= other.rank

    def __lt__(self, other: object) -> bool:  # type: ignore[override]
        if not isinstance(other, Severity):
            return NotImplemented
        return self.rank < other.rank


_SEVERITY_RANK: Final[dict[Severity, int]] = {
    Severity.INFO: 0,
    Severity.WARNING: 1,
    Severity.ERROR: 2,
    Severity.CRITICAL: 3,
}


# ---------------------------------------------------------------------------
# Events & notifications
# ---------------------------------------------------------------------------


class EventType(str, Enum):
    """Topics published on the internal event bus."""

    # Market data
    CANDLE_CLOSED = "candle.closed"
    TICKER_UPDATE = "ticker.update"
    ORDERBOOK_UPDATE = "orderbook.update"
    # Signals
    SIGNAL_GENERATED = "signal.generated"
    SIGNAL_AGGREGATED = "signal.aggregated"
    # Orders & trades
    ORDER_SUBMITTED = "order.submitted"
    ORDER_UPDATED = "order.updated"
    ORDER_FILLED = "order.filled"
    ORDER_CANCELED = "order.canceled"
    TRADE_OPENED = "trade.opened"
    TRADE_CLOSED = "trade.closed"
    # Risk
    RISK_REJECTED = "risk.rejected"
    RISK_EVENT = "risk.event"
    # Connection
    CONNECTION_LOST = "connection.lost"
    CONNECTION_RESTORED = "connection.restored"
    # System
    ENGINE_STARTED = "engine.started"
    ENGINE_STOPPED = "engine.stopped"
    SYSTEM_ERROR = "system.error"


class NotificationChannel(str, Enum):
    """Available notification transports."""

    TELEGRAM = "telegram"
    DISCORD = "discord"
    EMAIL = "email"


class NotificationStatus(str, Enum):
    """Delivery status of a notification."""

    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SUPPRESSED = "suppressed"


# ---------------------------------------------------------------------------
# AI / market regime
# ---------------------------------------------------------------------------


class MarketRegime(str, Enum):
    """Detected market regime used to gate or weight strategies."""

    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"
    UNKNOWN = "unknown"


class ModelType(str, Enum):
    """Supported machine-learning model backends."""

    XGBOOST = "xgboost"
    RANDOM_FOREST = "random_forest"
    LIGHTGBM = "lightgbm"
    LSTM = "lstm"


# ---------------------------------------------------------------------------
# Convenience collections
# ---------------------------------------------------------------------------

#: All timeframes ordered from shortest to longest.
ALL_TIMEFRAMES: Final[tuple[Timeframe, ...]] = (
    Timeframe.M1,
    Timeframe.M3,
    Timeframe.M5,
    Timeframe.M15,
    Timeframe.M30,
    Timeframe.H1,
    Timeframe.H4,
    Timeframe.H12,
    Timeframe.D1,
)

#: Stable quote assets the bot recognises for balance/PnL reporting.
STABLE_QUOTE_ASSETS: Final[frozenset[str]] = frozenset(
    {"USDT", "USDC", "BUSD", "FDUSD", "TUSD", "DAI"}
)
