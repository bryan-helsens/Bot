"""Integration test: database repositories round-trip on SQLite."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantbot.core.constants import (
    ExitReason,
    OrderStatus,
    OrderType,
    PositionSide,
    Side,
    Timeframe,
)
from quantbot.core.models import AccountSnapshot, Order, Position, Signal, Trade
from quantbot.infrastructure.db import models  # noqa: F401 - register tables
from quantbot.infrastructure.db.database import Database
from quantbot.infrastructure.db.repositories import RepositoryFactory

pytestmark = pytest.mark.integration


@pytest.fixture
async def database():
    db = Database(url="sqlite+aiosqlite:///:memory:")
    db.connect()
    await db.create_all()
    yield db
    await db.dispose()


async def test_trade_roundtrip(database: Database) -> None:
    trade = Trade(
        position_id="p1", strategy="ema", symbol="BTCUSDT", side=PositionSide.LONG,
        quantity=Decimal("2"), entry_price=Decimal("100"), exit_price=Decimal("110"),
        fees=Decimal("1"), exit_reason=ExitReason.TAKE_PROFIT, opened_at=datetime.now(UTC),
    )
    async with database.session() as session:
        await RepositoryFactory(session).trades.save(trade)
    async with database.session() as session:
        repos = RepositoryFactory(session)
        trades = await repos.trades.recent()
        assert len(trades) == 1
        assert trades[0].net_pnl == Decimal("19")
        assert trades[0].exit_reason is ExitReason.TAKE_PROFIT
        assert len(await repos.trades.by_strategy("ema")) == 1


async def test_order_position_signal_equity(database: Database) -> None:
    async with database.session() as session:
        repos = RepositoryFactory(session)
        await repos.orders.save(
            Order(client_order_id="c1", symbol="BTCUSDT", side=Side.BUY,
                  quantity=Decimal("2"), status=OrderStatus.FILLED, type=OrderType.MARKET)
        )
        await repos.positions.save(
            Position(symbol="BTCUSDT", side=PositionSide.LONG, quantity=Decimal("2"),
                     entry_price=Decimal("100"))
        )
        await repos.signals.save(
            Signal(strategy="ema", symbol="BTCUSDT", timeframe=Timeframe.H1,
                   side=Side.BUY, price=Decimal("100"))
        )
        await repos.equity.save(AccountSnapshot(equity=Decimal("10000"), balance=Decimal("10000")))
        await repos.risk_events.save(event_type="max_drawdown", severity="critical", reason="dd")

    async with database.session() as session:
        repos = RepositoryFactory(session)
        order = await repos.orders.get("c1")
        assert order is not None and order.status is OrderStatus.FILLED
        assert len(await repos.positions.open_positions()) == 1
        assert len(await repos.equity.curve()) == 1
        assert len(await repos.risk_events.recent()) == 1
        assert len(await repos.signals.recent("BTCUSDT")) == 1
