"""Repository pattern over the ORM models.

Each repository wraps an :class:`AsyncSession` and exposes intent-revealing
methods (``save_trade``, ``recent_trades``, ``open_positions`` …) that map between
the rich domain models in :mod:`quantbot.core.models` and the ORM rows. The rest
of the application depends only on these repositories, never on raw SQL or ORM
internals, keeping persistence swappable and the domain pure.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from quantbot.core.models import (
    AccountSnapshot,
    Order,
    Position,
    Signal,
    Trade,
)
from quantbot.infrastructure.db.models import (
    EquitySnapshotORM,
    OrderORM,
    PositionORM,
    RiskEventORM,
    SignalORM,
    TradeORM,
)


class TradeRepository:
    """Persistence for realised trades."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def save(self, trade: Trade) -> None:
        self._s.add(_trade_to_orm(trade))

    async def get(self, trade_id: str) -> Trade | None:
        row = await self._s.get(TradeORM, trade_id)
        return _trade_from_orm(row) if row else None

    async def recent(self, limit: int = 100) -> list[Trade]:
        stmt = select(TradeORM).order_by(TradeORM.closed_at.desc()).limit(limit)
        rows = (await self._s.execute(stmt)).scalars().all()
        return [_trade_from_orm(r) for r in rows]

    async def by_strategy(self, strategy: str, *, limit: int = 500) -> list[Trade]:
        stmt = (
            select(TradeORM)
            .where(TradeORM.strategy == strategy)
            .order_by(TradeORM.closed_at.desc())
            .limit(limit)
        )
        rows = (await self._s.execute(stmt)).scalars().all()
        return [_trade_from_orm(r) for r in rows]

    async def by_symbol(self, symbol: str, *, limit: int = 500) -> list[Trade]:
        stmt = (
            select(TradeORM)
            .where(TradeORM.symbol == symbol)
            .order_by(TradeORM.closed_at.desc())
            .limit(limit)
        )
        rows = (await self._s.execute(stmt)).scalars().all()
        return [_trade_from_orm(r) for r in rows]


class OrderRepository:
    """Persistence for orders."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def save(self, order: Order) -> None:
        existing = await self._by_client_id(order.client_order_id)
        if existing is None:
            self._s.add(_order_to_orm(order))
        else:
            _update_order_orm(existing, order)

    async def _by_client_id(self, client_order_id: str) -> OrderORM | None:
        stmt = select(OrderORM).where(OrderORM.client_order_id == client_order_id)
        return (await self._s.execute(stmt)).scalar_one_or_none()

    async def get(self, client_order_id: str) -> Order | None:
        row = await self._by_client_id(client_order_id)
        return _order_from_orm(row) if row else None

    async def open_orders(self) -> list[Order]:
        stmt = select(OrderORM).where(
            OrderORM.status.in_(("pending", "new", "partially_filled"))
        )
        rows = (await self._s.execute(stmt)).scalars().all()
        return [_order_from_orm(r) for r in rows]


class PositionRepository:
    """Persistence for positions."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def save(self, position: Position) -> None:
        existing = await self._s.get(PositionORM, position.id)
        if existing is None:
            self._s.add(_position_to_orm(position))
        else:
            _update_position_orm(existing, position)

    async def get(self, position_id: str) -> Position | None:
        row = await self._s.get(PositionORM, position_id)
        return _position_from_orm(row) if row else None

    async def open_positions(self) -> list[Position]:
        stmt = select(PositionORM).where(PositionORM.status == "open")
        rows = (await self._s.execute(stmt)).scalars().all()
        return [_position_from_orm(r) for r in rows]


class SignalRepository:
    """Persistence for signals (audit/analysis)."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def save(self, signal: Signal) -> None:
        self._s.add(
            SignalORM(
                id=signal.id,
                strategy=signal.strategy,
                symbol=signal.symbol,
                timeframe=signal.timeframe.value,
                side=signal.side.value,
                signal_type=signal.signal_type.value,
                strength=__import__("decimal").Decimal(str(signal.strength)),
                price=signal.price,
                meta=signal.meta,
                created_at=signal.created_at,
            )
        )

    async def recent(self, symbol: str | None = None, *, limit: int = 200) -> list[SignalORM]:
        stmt = select(SignalORM).order_by(SignalORM.created_at.desc()).limit(limit)
        if symbol is not None:
            stmt = stmt.where(SignalORM.symbol == symbol)
        return list((await self._s.execute(stmt)).scalars().all())


class EquitySnapshotRepository:
    """Persistence for equity snapshots."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def save(self, snap: AccountSnapshot) -> None:
        self._s.add(
            EquitySnapshotORM(
                timestamp=snap.timestamp,
                equity=snap.equity,
                balance=snap.balance,
                unrealized_pnl=snap.unrealized_pnl,
                drawdown=snap.drawdown,
                open_positions=snap.open_positions,
            )
        )

    async def curve(self, *, limit: int = 5000) -> list[EquitySnapshotORM]:
        stmt = select(EquitySnapshotORM).order_by(EquitySnapshotORM.timestamp.asc()).limit(limit)
        return list((await self._s.execute(stmt)).scalars().all())


class RiskEventRepository:
    """Persistence for risk events."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def save(
        self, *, event_type: str, severity: str, reason: str,
        symbol: str | None = None, payload: dict | None = None,
    ) -> None:
        self._s.add(
            RiskEventORM(
                event_type=event_type, severity=severity, reason=reason,
                symbol=symbol, payload=payload or {},
            )
        )

    async def recent(self, *, limit: int = 200) -> list[RiskEventORM]:
        stmt = select(RiskEventORM).order_by(RiskEventORM.created_at.desc()).limit(limit)
        return list((await self._s.execute(stmt)).scalars().all())


class RepositoryFactory:
    """Bundle of repositories sharing one session (a lightweight unit of work)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.trades = TradeRepository(session)
        self.orders = OrderRepository(session)
        self.positions = PositionRepository(session)
        self.signals = SignalRepository(session)
        self.equity = EquitySnapshotRepository(session)
        self.risk_events = RiskEventRepository(session)


# ---------------------------------------------------------------------------
# Domain <-> ORM mappers
# ---------------------------------------------------------------------------


def _trade_to_orm(t: Trade) -> TradeORM:
    return TradeORM(
        id=t.id, position_id=t.position_id, strategy=t.strategy, symbol=t.symbol,
        side=t.side.value, quantity=t.quantity, entry_price=t.entry_price,
        exit_price=t.exit_price, gross_pnl=t.gross_pnl, net_pnl=t.net_pnl,
        fees=t.fees, return_pct=t.return_pct, bars_held=t.bars_held,
        exit_reason=t.exit_reason.value, opened_at=t.opened_at, closed_at=t.closed_at,
    )


def _trade_from_orm(r: TradeORM) -> Trade:
    from quantbot.core.constants import ExitReason, PositionSide

    return Trade(
        id=r.id, position_id=r.position_id, strategy=r.strategy, symbol=r.symbol,
        side=PositionSide(r.side), quantity=r.quantity, entry_price=r.entry_price,
        exit_price=r.exit_price, fees=r.fees,
        exit_reason=ExitReason(r.exit_reason) if r.exit_reason else ExitReason.SIGNAL,
        bars_held=r.bars_held, opened_at=r.opened_at, closed_at=r.closed_at,
    )


def _order_to_orm(o: Order) -> OrderORM:
    return OrderORM(
        id=o.id, client_order_id=o.client_order_id, exchange_order_id=o.exchange_order_id,
        position_id=o.position_id, strategy=o.strategy, symbol=o.symbol,
        market=o.market.value, side=o.side.value, type=o.type.value, status=o.status.value,
        role=o.role.value, quantity=o.quantity, price=o.price, stop_price=o.stop_price,
        filled_qty=o.filled_qty, avg_fill_price=o.avg_fill_price, commission=o.commission,
        reduce_only=o.reduce_only, created_at=o.created_at, updated_at=o.updated_at,
    )


def _update_order_orm(orm: OrderORM, o: Order) -> None:
    orm.status = o.status.value
    orm.filled_qty = o.filled_qty
    orm.avg_fill_price = o.avg_fill_price
    orm.commission = o.commission
    orm.exchange_order_id = o.exchange_order_id
    orm.updated_at = o.updated_at


def _order_from_orm(r: OrderORM) -> Order:
    from quantbot.core.constants import MarketType, OrderRole, OrderStatus, OrderType, Side

    return Order(
        id=r.id, client_order_id=r.client_order_id, exchange_order_id=r.exchange_order_id,
        position_id=r.position_id, strategy=r.strategy, symbol=r.symbol,
        market=MarketType(r.market), side=Side(r.side), type=OrderType(r.type),
        role=OrderRole(r.role) if r.role else OrderRole.ENTRY, status=OrderStatus(r.status),
        quantity=r.quantity, price=r.price, stop_price=r.stop_price, filled_qty=r.filled_qty,
        avg_fill_price=r.avg_fill_price, commission=r.commission, reduce_only=r.reduce_only,
        created_at=r.created_at, updated_at=r.updated_at,
    )


def _position_to_orm(p: Position) -> PositionORM:
    return PositionORM(
        id=p.id, strategy=p.strategy, symbol=p.symbol, market=p.market.value,
        side=p.side.value, status=p.status.value, quantity=p.quantity,
        entry_price=p.entry_price, exit_price=p.exit_price, stop_loss=p.stop_loss,
        take_profit={"levels": [{"price": str(tp.price), "size": str(tp.size_fraction),
                                 "triggered": tp.triggered} for tp in p.take_profit_levels]},
        leverage=p.leverage, realized_pnl=p.realized_pnl, fees_paid=p.fees_paid,
        opened_at=p.opened_at, closed_at=p.closed_at, meta=p.meta,
    )


def _update_position_orm(orm: PositionORM, p: Position) -> None:
    orm.status = p.status.value
    orm.quantity = p.quantity
    orm.exit_price = p.exit_price
    orm.stop_loss = p.stop_loss
    orm.realized_pnl = p.realized_pnl
    orm.fees_paid = p.fees_paid
    orm.closed_at = p.closed_at
    orm.meta = p.meta


def _position_from_orm(r: PositionORM) -> Position:
    from quantbot.core.constants import MarketType, PositionSide, PositionStatus

    return Position(
        id=r.id, strategy=r.strategy, symbol=r.symbol, market=MarketType(r.market),
        side=PositionSide(r.side), status=PositionStatus(r.status), quantity=r.quantity,
        entry_price=r.entry_price, exit_price=r.exit_price, stop_loss=r.stop_loss,
        leverage=r.leverage, realized_pnl=r.realized_pnl, fees_paid=r.fees_paid,
        opened_at=r.opened_at, closed_at=r.closed_at, meta=r.meta or {},
    )


__all__ = [
    "EquitySnapshotRepository",
    "OrderRepository",
    "PositionRepository",
    "RepositoryFactory",
    "RiskEventRepository",
    "SignalRepository",
    "TradeRepository",
]
