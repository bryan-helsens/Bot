"""SQLAlchemy ORM models mirroring the schema in ``docs/DATABASE.md``.

Portable column types are used (``JSON`` rather than ``JSONB``, ``Numeric`` for
money, timezone-aware ``DateTime``) so the same models run on PostgreSQL in
production and SQLite in tests. Money columns use ``Numeric(38, 18)`` to preserve
exact decimal values.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from quantbot.core.models import new_id, utcnow
from quantbot.infrastructure.db.database import Base

# Reusable column type aliases.
_Money = Numeric(38, 18)


def _pk() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=new_id)


def _ts(index: bool = False) -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=utcnow, index=index)


class StrategyORM(Base):
    """Registered strategy instances."""

    __tablename__ = "strategies"

    id: Mapped[str] = _pk()
    name: Mapped[str] = mapped_column(String(100), unique=True)
    class_name: Mapped[str] = mapped_column(String(100))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    symbols: Mapped[list] = mapped_column(JSON, default=list)
    timeframes: Mapped[list] = mapped_column(JSON, default=list)
    market: Mapped[str] = mapped_column(String(10), default="spot")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SymbolORM(Base):
    """Cached exchange symbol metadata."""

    __tablename__ = "symbols"

    symbol: Mapped[str] = mapped_column(String(30), primary_key=True)
    base_asset: Mapped[str] = mapped_column(String(15))
    quote_asset: Mapped[str] = mapped_column(String(15))
    market: Mapped[str] = mapped_column(String(10), default="spot")
    price_precision: Mapped[int] = mapped_column(Integer, default=8)
    qty_precision: Mapped[int] = mapped_column(Integer, default=8)
    min_notional: Mapped[Decimal] = mapped_column(_Money, default=Decimal("0"))
    tick_size: Mapped[Decimal] = mapped_column(_Money, default=Decimal("0"))
    step_size: Mapped[Decimal] = mapped_column(_Money, default=Decimal("0"))
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SignalORM(Base):
    """Strategy/AI signals (audit + analysis)."""

    __tablename__ = "signals"

    id: Mapped[str] = _pk()
    strategy_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    strategy: Mapped[str] = mapped_column(String(100))
    symbol: Mapped[str] = mapped_column(String(30), index=True)
    timeframe: Mapped[str] = mapped_column(String(5))
    side: Mapped[str] = mapped_column(String(5))
    signal_type: Mapped[str] = mapped_column(String(20), default="entry")
    strength: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=Decimal("0"))
    price: Mapped[Decimal] = mapped_column(_Money)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = _ts(index=True)

    __table_args__ = (Index("ix_signals_symbol_created", "symbol", "created_at"),)


class OrderORM(Base):
    """Submitted orders (local mirror of the exchange)."""

    __tablename__ = "orders"

    id: Mapped[str] = _pk()
    client_order_id: Mapped[str] = mapped_column(String(64), unique=True)
    exchange_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    position_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    strategy: Mapped[str | None] = mapped_column(String(100), nullable=True)
    symbol: Mapped[str] = mapped_column(String(30), index=True)
    market: Mapped[str] = mapped_column(String(10), default="spot")
    side: Mapped[str] = mapped_column(String(5))
    type: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(_Money)
    price: Mapped[Decimal | None] = mapped_column(_Money, nullable=True)
    stop_price: Mapped[Decimal | None] = mapped_column(_Money, nullable=True)
    filled_qty: Mapped[Decimal] = mapped_column(_Money, default=Decimal("0"))
    avg_fill_price: Mapped[Decimal | None] = mapped_column(_Money, nullable=True)
    commission: Mapped[Decimal] = mapped_column(_Money, default=Decimal("0"))
    reduce_only: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (Index("ix_orders_symbol_created", "symbol", "created_at"),)


class PositionORM(Base):
    """Open/closed positions."""

    __tablename__ = "positions"

    id: Mapped[str] = _pk()
    strategy: Mapped[str | None] = mapped_column(String(100), nullable=True)
    symbol: Mapped[str] = mapped_column(String(30), index=True)
    market: Mapped[str] = mapped_column(String(10), default="spot")
    side: Mapped[str] = mapped_column(String(5))
    status: Mapped[str] = mapped_column(String(10), default="open", index=True)
    quantity: Mapped[Decimal] = mapped_column(_Money)
    entry_price: Mapped[Decimal] = mapped_column(_Money)
    exit_price: Mapped[Decimal | None] = mapped_column(_Money, nullable=True)
    stop_loss: Mapped[Decimal | None] = mapped_column(_Money, nullable=True)
    take_profit: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    leverage: Mapped[int] = mapped_column(Integer, default=1)
    realized_pnl: Mapped[Decimal] = mapped_column(_Money, default=Decimal("0"))
    unrealized_pnl: Mapped[Decimal] = mapped_column(_Money, default=Decimal("0"))
    fees_paid: Mapped[Decimal] = mapped_column(_Money, default=Decimal("0"))
    opened_at: Mapped[datetime] = _ts()
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class TradeORM(Base):
    """Realised (closed) trades — source for performance."""

    __tablename__ = "trades"

    id: Mapped[str] = _pk()
    position_id: Mapped[str] = mapped_column(String(36))
    strategy: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(30), index=True)
    side: Mapped[str] = mapped_column(String(5))
    quantity: Mapped[Decimal] = mapped_column(_Money)
    entry_price: Mapped[Decimal] = mapped_column(_Money)
    exit_price: Mapped[Decimal] = mapped_column(_Money)
    gross_pnl: Mapped[Decimal] = mapped_column(_Money)
    net_pnl: Mapped[Decimal] = mapped_column(_Money)
    fees: Mapped[Decimal] = mapped_column(_Money, default=Decimal("0"))
    return_pct: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal("0"))
    bars_held: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime] = _ts(index=True)

    __table_args__ = (Index("ix_trades_strategy_closed", "strategy", "closed_at"),)


class EquitySnapshotORM(Base):
    """Periodic equity snapshots for the equity curve & drawdown."""

    __tablename__ = "equity_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = _ts(index=True)
    equity: Mapped[Decimal] = mapped_column(_Money)
    balance: Mapped[Decimal] = mapped_column(_Money)
    unrealized_pnl: Mapped[Decimal] = mapped_column(_Money, default=Decimal("0"))
    drawdown: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0"))
    open_positions: Mapped[int] = mapped_column(Integer, default=0)


class StrategyPerformanceORM(Base):
    """Aggregated per-strategy performance metrics."""

    __tablename__ = "strategy_performance"

    id: Mapped[str] = _pk()
    strategy: Mapped[str] = mapped_column(String(100), index=True)
    period: Mapped[str] = mapped_column(String(10), default="all")
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    trades_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class RiskEventORM(Base):
    """Risk events recorded for auditing and alerting."""

    __tablename__ = "risk_events"

    id: Mapped[str] = _pk()
    event_type: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10), default="warning")
    symbol: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = _ts(index=True)


class AuditLogORM(Base):
    """Immutable audit trail."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(50))
    action: Mapped[str] = mapped_column(String(60))
    resource: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = _ts(index=True)


class NotificationORM(Base):
    """Sent-notification log (de-duplication + retry)."""

    __tablename__ = "notifications"

    id: Mapped[str] = _pk()
    channel: Mapped[str] = mapped_column(String(20))
    event_type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(15), default="pending")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _ts()


__all__ = [
    "AuditLogORM",
    "EquitySnapshotORM",
    "NotificationORM",
    "OrderORM",
    "PositionORM",
    "RiskEventORM",
    "SignalORM",
    "StrategyORM",
    "StrategyPerformanceORM",
    "SymbolORM",
    "TradeORM",
]
