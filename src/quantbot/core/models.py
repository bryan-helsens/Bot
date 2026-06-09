"""Core domain models for QuantBot.

These Pydantic v2 models are the lingua franca exchanged between every layer:
market data, signals, orders, positions and trades. They are deliberately
*behaviour-rich* (computed properties, small helpers) but free of side effects —
no I/O, no exchange calls — so they are trivially unit-testable and safe to copy
between async tasks.

Monetary fields use :class:`decimal.Decimal` to avoid binary floating-point
rounding error. Quantities and prices are always non-negative; direction is
encoded by :class:`~quantbot.core.constants.Side` / ``PositionSide``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from quantbot.core.constants import (
    ExitReason,
    MarketType,
    OrderRole,
    OrderStatus,
    OrderType,
    PositionSide,
    PositionStatus,
    Side,
    SignalType,
    Timeframe,
    TimeInForce,
)

# ---------------------------------------------------------------------------
# Type aliases & helpers
# ---------------------------------------------------------------------------

#: A non-negative monetary/quantity decimal.
NonNegativeDecimal = Annotated[Decimal, Field(ge=0)]

#: A strictly positive decimal.
PositiveDecimal = Annotated[Decimal, Field(gt=0)]


def utcnow() -> datetime:
    """Timezone-aware current UTC timestamp (single source of truth)."""
    return datetime.now(UTC)


def new_id() -> str:
    """Generate a new opaque UUID4 string identifier."""
    return str(uuid.uuid4())


class _Base(BaseModel):
    """Shared model configuration."""

    model_config = ConfigDict(
        extra="ignore",
        frozen=False,
        populate_by_name=True,
        use_enum_values=False,
        ser_json_inf_nan="constants",
        validate_assignment=True,
    )


# ---------------------------------------------------------------------------
# Symbol / exchange metadata
# ---------------------------------------------------------------------------


class SymbolInfo(_Base):
    """Exchange trading rules for a symbol (filters, precision, limits)."""

    symbol: str
    base_asset: str
    quote_asset: str
    market: MarketType = MarketType.SPOT
    price_precision: int = 8
    qty_precision: int = 8
    tick_size: PositiveDecimal = Decimal("0.00000001")
    step_size: PositiveDecimal = Decimal("0.00000001")
    min_qty: NonNegativeDecimal = Decimal("0")
    max_qty: NonNegativeDecimal = Decimal("0")
    min_notional: NonNegativeDecimal = Decimal("0")
    filters: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=utcnow)

    def round_price(self, price: Decimal) -> Decimal:
        """Quantise *price* down to the symbol's tick size."""
        return _quantize_to_step(price, self.tick_size)

    def round_qty(self, qty: Decimal) -> Decimal:
        """Quantise *qty* down to the symbol's step size."""
        return _quantize_to_step(qty, self.step_size)

    def is_valid_notional(self, price: Decimal, qty: Decimal) -> bool:
        """Whether ``price * qty`` meets the minimum notional filter."""
        return self.min_notional <= 0 or price * qty >= self.min_notional


def _quantize_to_step(value: Decimal, step: Decimal) -> Decimal:
    """Floor *value* to the nearest multiple of *step* (step > 0)."""
    if step <= 0:
        return value
    return (value // step) * step


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------


class Candle(_Base):
    """A single OHLCV candlestick for a ``(symbol, timeframe)``."""

    symbol: str
    timeframe: Timeframe
    open_time: datetime
    close_time: datetime
    open: NonNegativeDecimal
    high: NonNegativeDecimal
    low: NonNegativeDecimal
    close: NonNegativeDecimal
    volume: NonNegativeDecimal
    quote_volume: NonNegativeDecimal = Decimal("0")
    trades: int = 0
    is_closed: bool = True

    @model_validator(mode="after")
    def _check_ohlc(self) -> Candle:
        """Validate OHLC internal consistency (high ≥ low, etc.)."""
        if self.high < self.low:
            raise ValueError(f"high {self.high} < low {self.low} for {self.symbol}")
        if not (self.low <= self.open <= self.high):
            raise ValueError(f"open {self.open} outside [low, high] for {self.symbol}")
        if not (self.low <= self.close <= self.high):
            raise ValueError(f"close {self.close} outside [low, high] for {self.symbol}")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_bullish(self) -> bool:
        """Whether the candle closed above its open."""
        return self.close > self.open

    @computed_field  # type: ignore[prop-decorator]
    @property
    def range(self) -> Decimal:
        """High-low range of the candle."""
        return self.high - self.low

    @property
    def typical_price(self) -> Decimal:
        """``(high + low + close) / 3`` — used by VWAP and others."""
        return (self.high + self.low + self.close) / 3


class Ticker(_Base):
    """Latest best bid/ask and last price for a symbol."""

    symbol: str
    last_price: NonNegativeDecimal
    bid_price: NonNegativeDecimal = Decimal("0")
    ask_price: NonNegativeDecimal = Decimal("0")
    bid_qty: NonNegativeDecimal = Decimal("0")
    ask_qty: NonNegativeDecimal = Decimal("0")
    volume_24h: NonNegativeDecimal = Decimal("0")
    quote_volume_24h: NonNegativeDecimal = Decimal("0")
    price_change_pct_24h: Decimal = Decimal("0")
    timestamp: datetime = Field(default_factory=utcnow)

    @property
    def mid_price(self) -> Decimal:
        """Mid-point of the spread, falling back to last price."""
        if self.bid_price > 0 and self.ask_price > 0:
            return (self.bid_price + self.ask_price) / 2
        return self.last_price

    @property
    def spread(self) -> Decimal:
        """Absolute bid/ask spread (0 if either side missing)."""
        if self.bid_price > 0 and self.ask_price > 0:
            return self.ask_price - self.bid_price
        return Decimal("0")


class OrderBookLevel(_Base):
    """A single price level in the order book."""

    price: PositiveDecimal
    quantity: NonNegativeDecimal


class OrderBook(_Base):
    """Top-of-book snapshot with bids (desc) and asks (asc)."""

    symbol: str
    bids: list[OrderBookLevel] = Field(default_factory=list)
    asks: list[OrderBookLevel] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=utcnow)

    @property
    def best_bid(self) -> Decimal | None:
        """Highest bid price, if any."""
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Decimal | None:
        """Lowest ask price, if any."""
        return self.asks[0].price if self.asks else None


class Balance(_Base):
    """Free/locked balance for a single asset."""

    asset: str
    free: NonNegativeDecimal = Decimal("0")
    locked: NonNegativeDecimal = Decimal("0")

    @property
    def total(self) -> Decimal:
        """Free plus locked."""
        return self.free + self.locked


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------


class Signal(_Base):
    """A trading intent emitted by a strategy or the AI module.

    A signal is *advice*, never an order. It must pass through the risk engine
    before any order is created.
    """

    id: str = Field(default_factory=new_id)
    strategy: str
    symbol: str
    timeframe: Timeframe
    side: Side
    signal_type: SignalType = SignalType.ENTRY
    strength: Annotated[float, Field(ge=0.0, le=1.0)] = 0.5
    price: PositiveDecimal
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    reason: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)

    @field_validator("stop_loss", "take_profit")
    @classmethod
    def _non_negative_optional(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v < 0:
            raise ValueError("stop_loss/take_profit must be non-negative")
        return v

    @property
    def is_actionable(self) -> bool:
        """Whether the signal represents an order-producing intent."""
        return self.signal_type is not SignalType.NONE and self.strength > 0


# ---------------------------------------------------------------------------
# Take-profit ladder
# ---------------------------------------------------------------------------


class TakeProfitLevel(_Base):
    """One rung of a multi-level take-profit ladder."""

    price: PositiveDecimal
    #: Fraction of the *original* position size to close at this level (0..1].
    size_fraction: Annotated[Decimal, Field(gt=0, le=1)]
    triggered: bool = False


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


class Order(_Base):
    """A local mirror of an exchange order."""

    id: str = Field(default_factory=new_id)
    client_order_id: str = Field(default_factory=lambda: f"qb_{uuid.uuid4().hex[:24]}")
    exchange_order_id: str | None = None
    position_id: str | None = None
    strategy: str | None = None
    symbol: str
    market: MarketType = MarketType.SPOT
    side: Side
    type: OrderType = OrderType.MARKET
    role: OrderRole = OrderRole.ENTRY
    status: OrderStatus = OrderStatus.PENDING
    time_in_force: TimeInForce = TimeInForce.GTC
    quantity: PositiveDecimal
    price: Decimal | None = None
    stop_price: Decimal | None = None
    filled_qty: NonNegativeDecimal = Decimal("0")
    avg_fill_price: Decimal | None = None
    commission: NonNegativeDecimal = Decimal("0")
    commission_asset: str | None = None
    reduce_only: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def remaining_qty(self) -> Decimal:
        """Quantity still to be filled."""
        return max(self.quantity - self.filled_qty, Decimal("0"))

    @property
    def is_open(self) -> bool:
        """Whether the order is still working on the exchange."""
        return self.status.is_open

    @property
    def is_filled(self) -> bool:
        """Whether the order is fully filled."""
        return self.status is OrderStatus.FILLED

    def touch(self) -> None:
        """Bump :attr:`updated_at` to now (after a state mutation)."""
        self.updated_at = utcnow()


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------


class Position(_Base):
    """An open or closed position aggregated from one or more fills."""

    id: str = Field(default_factory=new_id)
    strategy: str | None = None
    symbol: str
    market: MarketType = MarketType.SPOT
    side: PositionSide
    status: PositionStatus = PositionStatus.OPEN
    quantity: NonNegativeDecimal
    entry_price: PositiveDecimal
    mark_price: Decimal | None = None
    exit_price: Decimal | None = None
    stop_loss: Decimal | None = None
    take_profit_levels: list[TakeProfitLevel] = Field(default_factory=list)
    trailing_stop_price: Decimal | None = None
    break_even_armed: bool = False
    leverage: Annotated[int, Field(ge=1)] = 1
    realized_pnl: Decimal = Decimal("0")
    fees_paid: NonNegativeDecimal = Decimal("0")
    averaging_entries: Annotated[int, Field(ge=1)] = 1
    opened_at: datetime = Field(default_factory=utcnow)
    closed_at: datetime | None = None
    meta: dict[str, Any] = Field(default_factory=dict)

    def unrealized_pnl(self, price: Decimal | None = None) -> Decimal:
        """Unrealised PnL at *price* (defaults to :attr:`mark_price`)."""
        ref = price if price is not None else self.mark_price
        if ref is None or self.status is PositionStatus.CLOSED:
            return Decimal("0")
        return (ref - self.entry_price) * self.quantity * self.side.sign

    def notional(self, price: Decimal | None = None) -> Decimal:
        """Position notional value at *price* (defaults to mark price, then entry).

        Defaulting to the current mark price (like :meth:`unrealized_pnl`) means
        exposure/risk-limit checks measure CURRENT value, not entry cost — so a
        position that has run up cannot silently push the portfolio past its
        exposure cap.
        """
        ref = price if price is not None else (self.mark_price or self.entry_price)
        return ref * self.quantity

    @property
    def is_open(self) -> bool:
        """Whether the position is still open."""
        return self.status is PositionStatus.OPEN

    @property
    def is_long(self) -> bool:
        """Whether this is a long position."""
        return self.side is PositionSide.LONG


# ---------------------------------------------------------------------------
# Trades (realised)
# ---------------------------------------------------------------------------


class Trade(_Base):
    """A realised (closed) trade — the unit of performance accounting."""

    id: str = Field(default_factory=new_id)
    position_id: str
    strategy: str | None = None
    symbol: str
    side: PositionSide
    quantity: PositiveDecimal
    entry_price: PositiveDecimal
    exit_price: PositiveDecimal
    fees: NonNegativeDecimal = Decimal("0")
    exit_reason: ExitReason = ExitReason.SIGNAL
    bars_held: int | None = None
    opened_at: datetime
    closed_at: datetime = Field(default_factory=utcnow)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def gross_pnl(self) -> Decimal:
        """PnL before fees."""
        return (self.exit_price - self.entry_price) * self.quantity * self.side.sign

    @computed_field  # type: ignore[prop-decorator]
    @property
    def net_pnl(self) -> Decimal:
        """PnL after fees."""
        return self.gross_pnl - self.fees

    @computed_field  # type: ignore[prop-decorator]
    @property
    def return_pct(self) -> Decimal:
        """Net return as a fraction of the entry notional."""
        notional = self.entry_price * self.quantity
        if notional == 0:
            return Decimal("0")
        return self.net_pnl / notional

    @property
    def is_winner(self) -> bool:
        """Whether the trade was net profitable."""
        return self.net_pnl > 0

    @property
    def duration_seconds(self) -> float:
        """Holding period in seconds."""
        return (self.closed_at - self.opened_at).total_seconds()


# ---------------------------------------------------------------------------
# Account snapshot
# ---------------------------------------------------------------------------


class AccountSnapshot(_Base):
    """A point-in-time view of equity, balance and exposure."""

    timestamp: datetime = Field(default_factory=utcnow)
    equity: Decimal
    balance: Decimal
    unrealized_pnl: Decimal = Decimal("0")
    used_margin: Decimal = Decimal("0")
    open_positions: int = 0
    drawdown: Decimal = Decimal("0")


__all__ = [
    "AccountSnapshot",
    "Balance",
    "Candle",
    "NonNegativeDecimal",
    "Order",
    "OrderBook",
    "OrderBookLevel",
    "PositiveDecimal",
    "Position",
    "Signal",
    "SymbolInfo",
    "TakeProfitLevel",
    "Ticker",
    "Trade",
    "new_id",
    "utcnow",
]
