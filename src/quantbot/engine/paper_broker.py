"""Paper-trading broker — a simulated :class:`ExchangeGateway`.

Wraps a *real* gateway for all market data (symbols, klines, tickers, streams)
so the bot trades on genuine live prices, but **simulates order execution**
locally: market orders fill immediately at the latest price plus configurable
slippage; protective stop/limit orders are accepted as working orders and left
for the engine's :class:`~quantbot.risk.stops.StopManager` to trigger via market
closes (mirroring how exits are driven in live mode). No order ever reaches the
real exchange, so paper mode is risk-free yet behaviourally identical.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from decimal import Decimal

from quantbot.core.constants import MarketType, OrderStatus, OrderType, Side
from quantbot.core.exceptions import ExchangeError
from quantbot.core.logging import LoggerMixin
from quantbot.core.models import (
    Balance,
    Candle,
    Order,
    OrderBook,
    Position,
    SymbolInfo,
    Ticker,
    utcnow,
)
from quantbot.exchanges.base import AccountInfo, ExchangeGateway, OrderRequest, StreamEvent


class PaperTradingBroker(ExchangeGateway):
    """Simulated gateway: real market data, locally-simulated order fills."""

    def __init__(
        self,
        real_gateway: ExchangeGateway,
        *,
        starting_balance: Decimal,
        quote_asset: str = "USDT",
        slippage: Decimal = Decimal("0.0005"),
        commission: Decimal = Decimal("0.001"),
    ) -> None:
        self._real = real_gateway
        self.market = real_gateway.market
        self._quote = quote_asset
        self._balance = starting_balance
        self._slippage = slippage
        self._commission = commission
        self._prices: dict[str, Decimal] = {}
        self._working: dict[str, Order] = {}
        self._seq = 0

    # ------------------------------------------------------------------ price feed

    def feed_price(self, symbol: str, price: Decimal) -> None:
        """Update the broker's view of the latest price (driven by the engine)."""
        self._prices[symbol] = price

    def _price(self, symbol: str) -> Decimal:
        price = self._prices.get(symbol)
        if price is None:
            # Raise a typed ExchangeError (not a bare KeyError) so the executor's
            # error handling catches it instead of letting it crash the candle loop.
            raise ExchangeError(f"No price known for {symbol}; feed_price() first")
        return price

    # ------------------------------------------------------------------ lifecycle (delegate)

    async def connect(self) -> None:
        await self._real.connect()

    async def close(self) -> None:
        await self._real.close()

    async def ping(self) -> float:
        return await self._real.ping()

    async def server_time(self) -> datetime:
        return await self._real.server_time()

    # ------------------------------------------------------------------ metadata (delegate)

    async def load_symbols(self) -> dict[str, SymbolInfo]:
        return await self._real.load_symbols()

    async def get_symbol_info(self, symbol: str) -> SymbolInfo:
        return await self._real.get_symbol_info(symbol)

    # ------------------------------------------------------------------ market data (delegate)

    async def get_klines(
        self, symbol: str, timeframe, *, limit: int = 500,
        start_time: datetime | None = None, end_time: datetime | None = None,
    ) -> list[Candle]:
        return await self._real.get_klines(
            symbol, timeframe, limit=limit, start_time=start_time, end_time=end_time
        )

    async def get_ticker(self, symbol: str) -> Ticker:
        ticker = await self._real.get_ticker(symbol)
        self.feed_price(symbol, ticker.last_price)
        return ticker

    async def get_order_book(self, symbol: str, *, depth: int = 20) -> OrderBook:
        return await self._real.get_order_book(symbol, depth=depth)

    def stream_klines(self, symbol: str, timeframe) -> AsyncIterator[Candle]:
        return self._real.stream_klines(symbol, timeframe)

    def stream_tickers(self, symbols: Sequence[str]) -> AsyncIterator[Ticker]:
        return self._real.stream_tickers(symbols)

    def stream_user_events(self) -> AsyncIterator[StreamEvent]:
        return self._real.stream_user_events()

    def parse_user_event(self, event):
        # Paper fills happen synchronously in create_order; delegate parsing so the
        # shape matches the wrapped gateway (a real one yields no events here).
        return self._real.parse_user_event(event)

    # ------------------------------------------------------------------ account (simulated)

    async def get_account(self) -> AccountInfo:
        return AccountInfo(
            balances={self._quote: Balance(asset=self._quote, free=self._balance)},
            positions=[],
            total_equity=self._balance,
            available_balance=self._balance,
            quote_asset=self._quote,
        )

    async def get_balance(self, asset: str) -> Balance:
        if asset == self._quote:
            return Balance(asset=asset, free=self._balance)
        return Balance(asset=asset)

    async def get_positions(self, symbol: str | None = None) -> list[Position]:
        return []

    # ------------------------------------------------------------------ orders (simulated)

    async def create_order(self, request: OrderRequest) -> Order:
        """Simulate an order: market orders fill instantly with slippage."""
        self._seq += 1
        coid = request.client_order_id or f"paper_{self._seq}"
        order = Order(
            client_order_id=coid,
            exchange_order_id=f"paper_e{self._seq}",
            symbol=request.symbol,
            market=self.market,
            side=request.side,
            type=request.type,
            quantity=request.quantity,
            price=request.price,
            stop_price=request.stop_price,
            reduce_only=request.reduce_only,
        )
        if request.type is OrderType.MARKET:
            fill_price = self._apply_slippage(request.symbol, request.side)
            order.status = OrderStatus.FILLED
            order.filled_qty = request.quantity
            order.avg_fill_price = fill_price
            order.commission = fill_price * request.quantity * self._commission
        else:
            # Protective/limit orders rest as working; the StopManager drives exits.
            order.status = OrderStatus.NEW
            self._working[coid] = order
        return order

    def _apply_slippage(self, symbol: str, side: Side) -> Decimal:
        price = self._price(symbol)
        # Buyers pay up, sellers receive less.
        if side is Side.BUY:
            return price * (Decimal(1) + self._slippage)
        return price * (Decimal(1) - self._slippage)

    async def cancel_order(
        self, symbol: str, *, order_id: str | None = None, client_order_id: str | None = None
    ) -> Order:
        coid = client_order_id or order_id or ""
        order = self._working.pop(coid, None)
        if order is None:
            return Order(
                client_order_id=coid or "unknown", symbol=symbol, side=Side.SELL,
                quantity=Decimal("0.00000001"), status=OrderStatus.CANCELED,
            )
        order.status = OrderStatus.CANCELED
        order.touch()
        return order

    async def cancel_all_orders(self, symbol: str) -> list[Order]:
        canceled: list[Order] = []
        for coid in [c for c, o in self._working.items() if o.symbol == symbol]:
            canceled.append(await self.cancel_order(symbol, client_order_id=coid))
        return canceled

    async def get_order(
        self, symbol: str, *, order_id: str | None = None, client_order_id: str | None = None
    ) -> Order:
        coid = client_order_id or order_id or ""
        order = self._working.get(coid)
        if order is None:
            return Order(
                client_order_id=coid or "unknown", symbol=symbol, side=Side.SELL,
                quantity=Decimal("0.00000001"), status=OrderStatus.FILLED,
            )
        return order

    async def get_open_orders(self, symbol: str | None = None) -> list[Order]:
        return [o for o in self._working.values() if symbol is None or o.symbol == symbol]

    # ------------------------------------------------------------------ balance

    def apply_pnl(self, pnl: Decimal) -> None:
        """Adjust the simulated balance by a realised PnL (engine callback)."""
        self._balance += pnl

    @property
    def balance(self) -> Decimal:
        return self._balance


__all__ = ["PaperTradingBroker"]
