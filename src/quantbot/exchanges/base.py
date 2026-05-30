"""The :class:`ExchangeGateway` port and its supporting datatypes.

This is the single boundary between QuantBot's domain logic and any exchange.
Everything the engine needs — market data, account state, order management and
real-time streams — is expressed here in terms of the domain models from
:mod:`quantbot.core.models`. Concrete adapters translate to/from Binance REST and
websocket payloads.

The interface is deliberately ``async`` end-to-end and stream-oriented: market
data and user events arrive via async generators, while request/response calls
(orders, balances) are awaited coroutines.
"""

from __future__ import annotations

import abc
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from quantbot.core.constants import (
    MarketType,
    OrderType,
    Side,
    TimeInForce,
    Timeframe,
)
from quantbot.core.logging import LoggerMixin
from quantbot.core.models import (
    Balance,
    Candle,
    Order,
    OrderBook,
    Position,
    SymbolInfo,
    Ticker,
)


# ---------------------------------------------------------------------------
# Request / event value objects
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class OrderRequest:
    """A normalised order-placement request handed to a gateway.

    Adapters are responsible for rounding ``quantity``/``price`` to the symbol's
    filters (via :class:`~quantbot.core.models.SymbolInfo`) before submission.
    """

    symbol: str
    side: Side
    type: OrderType
    quantity: Decimal
    price: Decimal | None = None
    stop_price: Decimal | None = None
    time_in_force: TimeInForce = TimeInForce.GTC
    reduce_only: bool = False
    client_order_id: str | None = None
    leverage: int | None = None


@dataclass(slots=True)
class AccountInfo:
    """A snapshot of account balances and (for futures) positions."""

    balances: dict[str, Balance] = field(default_factory=dict)
    positions: list[Position] = field(default_factory=list)
    total_equity: Decimal = Decimal("0")
    available_balance: Decimal = Decimal("0")
    quote_asset: str = "USDT"

    def balance_of(self, asset: str) -> Balance:
        """Return the :class:`Balance` for *asset* (zero if absent)."""
        return self.balances.get(asset, Balance(asset=asset))


@dataclass(slots=True)
class StreamEvent:
    """A typed wrapper for messages arriving on user/market streams."""

    kind: str
    payload: dict[str, object]
    received_at: datetime


# ---------------------------------------------------------------------------
# Gateway port
# ---------------------------------------------------------------------------


class ExchangeGateway(LoggerMixin, abc.ABC):
    """Abstract exchange port. Concrete adapters implement every method.

    Lifecycle: construct → :meth:`connect` → use → :meth:`close`. Adapters must
    be safe to use from a single asyncio event loop and should manage their own
    rate limiting, signing and reconnection internally.
    """

    market: MarketType

    # ------------------------------------------------------------------ lifecycle

    @abc.abstractmethod
    async def connect(self) -> None:
        """Open underlying HTTP/WS sessions and load exchange metadata."""

    @abc.abstractmethod
    async def close(self) -> None:
        """Release all sessions and background tasks."""

    @abc.abstractmethod
    async def ping(self) -> float:
        """Round-trip latency to the exchange in seconds (connectivity check)."""

    @abc.abstractmethod
    async def server_time(self) -> datetime:
        """Current exchange server time (for clock-drift correction)."""

    # ------------------------------------------------------------------ metadata

    @abc.abstractmethod
    async def load_symbols(self) -> dict[str, SymbolInfo]:
        """Fetch and cache trading rules for all symbols."""

    @abc.abstractmethod
    async def get_symbol_info(self, symbol: str) -> SymbolInfo:
        """Return cached/loaded :class:`SymbolInfo` for *symbol*."""

    # ------------------------------------------------------------------ market data

    @abc.abstractmethod
    async def get_klines(
        self,
        symbol: str,
        timeframe: Timeframe,
        *,
        limit: int = 500,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[Candle]:
        """Fetch historical candlesticks (most recent last)."""

    @abc.abstractmethod
    async def get_ticker(self, symbol: str) -> Ticker:
        """Fetch the latest ticker for *symbol*."""

    @abc.abstractmethod
    async def get_order_book(self, symbol: str, *, depth: int = 20) -> OrderBook:
        """Fetch an order-book snapshot up to *depth* levels per side."""

    # ------------------------------------------------------------------ account

    @abc.abstractmethod
    async def get_account(self) -> AccountInfo:
        """Fetch balances (and positions for futures)."""

    @abc.abstractmethod
    async def get_balance(self, asset: str) -> Balance:
        """Fetch the balance of a single asset."""

    @abc.abstractmethod
    async def get_positions(self, symbol: str | None = None) -> list[Position]:
        """Fetch open positions (futures); spot returns an empty list."""

    # ------------------------------------------------------------------ orders

    @abc.abstractmethod
    async def create_order(self, request: OrderRequest) -> Order:
        """Submit an order and return the resulting :class:`Order`."""

    @abc.abstractmethod
    async def cancel_order(self, symbol: str, *, order_id: str | None = None,
                           client_order_id: str | None = None) -> Order:
        """Cancel an order by exchange id or client id."""

    @abc.abstractmethod
    async def cancel_all_orders(self, symbol: str) -> list[Order]:
        """Cancel every open order for *symbol*."""

    @abc.abstractmethod
    async def get_order(self, symbol: str, *, order_id: str | None = None,
                        client_order_id: str | None = None) -> Order:
        """Fetch the current state of a single order."""

    @abc.abstractmethod
    async def get_open_orders(self, symbol: str | None = None) -> list[Order]:
        """Fetch all currently open orders (optionally for one symbol)."""

    # ------------------------------------------------------------------ futures-only

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        """Set leverage for *symbol* (futures only; spot is a no-op)."""
        # Default no-op so spot adapters need not implement it.
        _ = (symbol, leverage)

    async def set_margin_mode(self, symbol: str, isolated: bool) -> None:
        """Set isolated/cross margin (futures only; spot is a no-op)."""
        _ = (symbol, isolated)

    # ------------------------------------------------------------------ streams

    @abc.abstractmethod
    def stream_klines(
        self, symbol: str, timeframe: Timeframe
    ) -> AsyncIterator[Candle]:
        """Yield live candles for ``(symbol, timeframe)`` (closed candles only)."""

    @abc.abstractmethod
    def stream_tickers(self, symbols: Sequence[str]) -> AsyncIterator[Ticker]:
        """Yield live ticker updates for the given symbols."""

    @abc.abstractmethod
    def stream_user_events(self) -> AsyncIterator[StreamEvent]:
        """Yield account/order events from the authenticated user stream."""

    # ------------------------------------------------------------------ helpers

    async def __aenter__(self) -> ExchangeGateway:
        await self.connect()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    def __repr__(self) -> str:
        return f"<{type(self).__name__} market={getattr(self, 'market', '?')}>"


__all__ = [
    "AccountInfo",
    "ExchangeGateway",
    "OrderRequest",
    "StreamEvent",
]
