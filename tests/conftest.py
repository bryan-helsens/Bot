"""Shared pytest fixtures for the QuantBot test suite."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest

from quantbot.core.config import (
    AggregatorSettings,
    BacktestSettings,
    RiskSettings,
    Settings,
)
from quantbot.core.constants import (
    MarketType,
    OrderStatus,
    SizingMethod,
    Timeframe,
)
from quantbot.core.models import Candle, Order, SymbolInfo
from quantbot.exchanges.base import AccountInfo, ExchangeGateway, OrderRequest, StreamEvent


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@pytest.fixture
def risk_settings() -> RiskSettings:
    """A deterministic risk configuration for tests."""
    return RiskSettings(
        sizing_method=SizingMethod.RISK,
        risk_per_trade=Decimal("0.02"),
        max_open_trades=5,
        max_exposure_per_coin=Decimal("1.0"),
        max_portfolio_exposure=Decimal("1.0"),
        max_daily_loss=Decimal("0.5"),
        max_weekly_loss=Decimal("0.5"),
        max_drawdown=Decimal("0.5"),
        default_stop_loss_pct=Decimal("0.05"),
        take_profit_levels=[(Decimal("0.10"), Decimal("1.0"))],
        max_correlation=Decimal("1.0"),
    )


@pytest.fixture
def settings(risk_settings: RiskSettings) -> Settings:
    """A test Settings instance not bound to any .env file."""
    s = Settings(_env_file=None)
    s.symbols = ["BTCUSDT"]
    s.timeframes = [Timeframe.H1]
    s.risk = risk_settings
    s.aggregator = AggregatorSettings(min_consensus=1, min_strength=0.5, window_seconds=60)
    s.backtest = BacktestSettings(
        initial_capital=Decimal("10000"), commission=Decimal("0.001"),
        slippage=Decimal("0.0005"), spread=Decimal("0.0002"),
    )
    return s


# ---------------------------------------------------------------------------
# Candle factories
# ---------------------------------------------------------------------------


@pytest.fixture
def make_candle() -> Callable[..., Candle]:
    """Factory producing a single valid candle at index *i* and price *p*."""

    def _make(
        i: int, price: float, *, symbol: str = "BTCUSDT", timeframe: Timeframe = Timeframe.H1
    ) -> Candle:
        ot = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(seconds=timeframe.seconds * i)
        p = Decimal(str(price))
        return Candle(
            symbol=symbol, timeframe=timeframe, open_time=ot,
            close_time=ot + timedelta(seconds=timeframe.seconds),
            open=p, high=p * Decimal("1.01"), low=p * Decimal("0.99"),
            close=p, volume=Decimal("100"),
        )

    return _make


@pytest.fixture
def trending_candles(make_candle: Callable[..., Candle]) -> list[Candle]:
    """A noisy up-trending candle series suitable for strategy/backtest tests."""
    rng = np.random.RandomState(42)
    prices = []
    p = 100.0
    for _ in range(300):
        p *= 1 + rng.randn() * 0.012 + 0.001
        prices.append(max(p, 1.0))
    return [make_candle(i, prices[i]) for i in range(len(prices))]


# ---------------------------------------------------------------------------
# Mock exchange gateway
# ---------------------------------------------------------------------------


class MockGateway(ExchangeGateway):
    """A fully in-memory exchange gateway for integration tests."""

    market = MarketType.SPOT

    def __init__(self, candles: dict[str, list[Candle]] | None = None) -> None:
        self._candles = candles or {}
        self.created_orders: list[OrderRequest] = []
        self._prices: dict[str, Decimal] = {}

    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def ping(self) -> float:
        return 0.0

    async def server_time(self) -> datetime:
        return datetime.now(UTC)

    async def load_symbols(self) -> dict[str, SymbolInfo]:
        return {}

    async def get_symbol_info(self, symbol: str) -> SymbolInfo:
        return SymbolInfo(symbol=symbol, base_asset="BTC", quote_asset="USDT")

    async def get_klines(
        self, symbol: str, timeframe: Timeframe, *, limit: int = 500,
        start_time: datetime | None = None, end_time: datetime | None = None,
    ) -> list[Candle]:
        return self._candles.get(symbol, [])[-limit:]

    async def get_ticker(self, symbol: str):  # pragma: no cover - unused in tests
        raise NotImplementedError

    async def get_order_book(self, symbol: str, *, depth: int = 20):  # pragma: no cover
        raise NotImplementedError

    async def get_account(self) -> AccountInfo:
        return AccountInfo(total_equity=Decimal("10000"), available_balance=Decimal("10000"))

    async def get_balance(self, asset: str):  # pragma: no cover
        from quantbot.core.models import Balance

        return Balance(asset=asset, free=Decimal("10000"))

    async def get_positions(self, symbol: str | None = None):
        return []

    async def create_order(self, request: OrderRequest) -> Order:
        self.created_orders.append(request)
        price = self._prices.get(request.symbol, Decimal("100"))
        return Order(
            client_order_id=request.client_order_id or f"mock_{len(self.created_orders)}",
            exchange_order_id=f"e{len(self.created_orders)}", symbol=request.symbol,
            side=request.side, type=request.type, quantity=request.quantity,
            status=OrderStatus.FILLED, filled_qty=request.quantity, avg_fill_price=price,
        )

    async def cancel_order(self, symbol: str, *, order_id=None, client_order_id=None) -> Order:
        return Order(
            client_order_id=client_order_id or "x", symbol=symbol,
            side=__import__("quantbot.core.constants", fromlist=["Side"]).Side.SELL,
            quantity=Decimal("0.00000001"), status=OrderStatus.CANCELED,
        )

    async def cancel_all_orders(self, symbol: str):
        return []

    async def get_order(self, symbol: str, *, order_id=None, client_order_id=None):  # pragma: no cover
        raise NotImplementedError

    async def get_open_orders(self, symbol: str | None = None):
        return []

    def feed_price(self, symbol: str, price: Decimal) -> None:
        self._prices[symbol] = price

    async def stream_klines(self, symbol: str, timeframe: Timeframe) -> AsyncIterator[Candle]:
        for candle in self._candles.get(symbol, []):
            yield candle

    async def stream_tickers(self, symbols: Sequence[str]):  # pragma: no cover
        if False:
            yield None

    async def stream_user_events(self) -> AsyncIterator[StreamEvent]:  # pragma: no cover
        if False:
            yield None


@pytest.fixture
def mock_gateway() -> MockGateway:
    return MockGateway()
