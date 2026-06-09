"""Binance Spot exchange adapter.

Implements :class:`~quantbot.exchanges.base.ExchangeGateway` against the Binance
Spot REST + websocket APIs. Responsibilities:

* Signed/unsigned REST calls with rate limiting, retries and error mapping.
* HMAC-SHA256 request signing and timestamp/recv-window handling.
* Mapping raw Binance payloads to/from the domain models.
* Live candle / ticker / user-data streams via :class:`WebSocketManager`.

The futures adapter subclasses this one and overrides the endpoint-specific
pieces (see :mod:`quantbot.exchanges.binance_futures`).
"""

from __future__ import annotations

import hashlib
import hmac
import time
import urllib.parse
from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

import aiohttp

from quantbot.core.config import Settings, get_settings
from quantbot.core.constants import (
    MarketType,
    OrderStatus,
    OrderType,
    Side,
    TimeInForce,
    Timeframe,
)
from quantbot.core.events import EventBus
from quantbot.core.exceptions import (
    AuthenticationError,
    ExchangeConnectionError,
    ExchangeError,
    InsufficientBalanceError,
    InvalidOrderError,
    OrderNotFoundError,
    RateLimitError,
    SymbolNotFoundError,
)
from quantbot.core.models import (
    Balance,
    Candle,
    Order,
    OrderBook,
    OrderBookLevel,
    Position,
    SymbolInfo,
    Ticker,
    utcnow,
)
from quantbot.core.utils import async_retry, from_millis, to_decimal, to_millis
from quantbot.exchanges.base import (
    AccountInfo,
    ExchangeGateway,
    OrderRequest,
    OrderUpdate,
    StreamEvent,
)
from quantbot.exchanges.rate_limiter import RateLimiter
from quantbot.exchanges.websocket import WebSocketManager

# Map domain enums to Binance API strings.
_ORDER_TYPE_TO_BINANCE: dict[OrderType, str] = {
    OrderType.MARKET: "MARKET",
    OrderType.LIMIT: "LIMIT",
    OrderType.STOP_LOSS: "STOP_LOSS",
    OrderType.STOP_LOSS_LIMIT: "STOP_LOSS_LIMIT",
    OrderType.TAKE_PROFIT: "TAKE_PROFIT",
    OrderType.TAKE_PROFIT_LIMIT: "TAKE_PROFIT_LIMIT",
    OrderType.TRAILING_STOP: "TAKE_PROFIT",  # spot has no native trailing; emulated
}
_BINANCE_TO_STATUS: dict[str, OrderStatus] = {
    "NEW": OrderStatus.NEW,
    "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
    "FILLED": OrderStatus.FILLED,
    "CANCELED": OrderStatus.CANCELED,
    "PENDING_CANCEL": OrderStatus.NEW,
    "REJECTED": OrderStatus.REJECTED,
    "EXPIRED": OrderStatus.EXPIRED,
    "EXPIRED_IN_MATCH": OrderStatus.EXPIRED,
}
# Binance error codes that map to specific domain exceptions.
_CODE_BALANCE = -2010
_CODE_UNKNOWN_ORDER = -2011, -2013
_CODE_BAD_SYMBOL = -1121


class BinanceSpotGateway(ExchangeGateway):
    """Concrete Binance Spot adapter."""

    market: MarketType = MarketType.SPOT

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        event_bus: EventBus | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._cfg = self._settings.binance
        self._bus = event_bus
        self._rest_url = self._cfg.resolved_rest_url
        self._ws_url = self._cfg.resolved_ws_url
        self._session: aiohttp.ClientSession | None = None
        self._ws: WebSocketManager | None = None
        self._rate = RateLimiter(
            max_weight_per_minute=self._settings.rate_limit.max_weight_per_minute,
            max_orders_per_10s=self._settings.rate_limit.max_orders_per_10s,
            max_orders_per_day=self._settings.rate_limit.max_orders_per_day,
        )
        self._symbols: dict[str, SymbolInfo] = {}
        self._time_offset_ms = 0
        self._listen_key: str | None = None

    # ------------------------------------------------------------------ endpoints

    @property
    def _api_prefix(self) -> str:
        """REST path prefix (overridden by the futures adapter)."""
        return "/api/v3"

    @property
    def _exchange_info_path(self) -> str:
        return f"{self._api_prefix}/exchangeInfo"

    # ------------------------------------------------------------------ lifecycle

    async def connect(self) -> None:
        self._session = aiohttp.ClientSession(
            headers={"X-MBX-APIKEY": self._cfg.api_key} if self._cfg.api_key else {}
        )
        await self._sync_time()
        await self.load_symbols()
        self._ws = WebSocketManager(self._ws_url, self._settings.websocket, event_bus=self._bus)
        await self._ws.start()
        self.log.info("binance_connected", market=self.market.value, testnet=self._cfg.testnet)

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def ping(self) -> float:
        start = time.perf_counter()
        await self._request("GET", f"{self._api_prefix}/ping", weight=1)
        return time.perf_counter() - start

    async def server_time(self) -> datetime:
        data = await self._request("GET", f"{self._api_prefix}/time", weight=1)
        return from_millis(int(data["serverTime"]))

    async def _sync_time(self) -> None:
        """Compute the offset between local and exchange clocks."""
        data = await self._request("GET", f"{self._api_prefix}/time", weight=1)
        server_ms = int(data["serverTime"])
        self._time_offset_ms = server_ms - int(time.time() * 1000)

    # ------------------------------------------------------------------ metadata

    async def load_symbols(self) -> dict[str, SymbolInfo]:
        data = await self._request("GET", self._exchange_info_path, weight=20)
        symbols: dict[str, SymbolInfo] = {}
        for item in data.get("symbols", []):
            if item.get("status") not in (None, "TRADING"):
                continue
            symbols[item["symbol"]] = self._parse_symbol_info(item)
        self._symbols = symbols
        self.log.info("symbols_loaded", count=len(symbols))
        return symbols

    def _parse_symbol_info(self, item: dict[str, Any]) -> SymbolInfo:
        filters = {f["filterType"]: f for f in item.get("filters", [])}
        price_filter = filters.get("PRICE_FILTER", {})
        lot = filters.get("LOT_SIZE", {})
        notional = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL") or {}
        return SymbolInfo(
            symbol=item["symbol"],
            base_asset=item["baseAsset"],
            quote_asset=item["quoteAsset"],
            market=self.market,
            price_precision=int(item.get("quotePrecision", item.get("quoteAssetPrecision", 8))),
            qty_precision=int(item.get("baseAssetPrecision", 8)),
            tick_size=to_decimal(price_filter.get("tickSize", "0.00000001")),
            step_size=to_decimal(lot.get("stepSize", "0.00000001")),
            min_qty=to_decimal(lot.get("minQty", "0")),
            max_qty=to_decimal(lot.get("maxQty", "0")),
            min_notional=to_decimal(notional.get("minNotional", "0")),
            filters=filters,
        )

    async def get_symbol_info(self, symbol: str) -> SymbolInfo:
        info = self._symbols.get(symbol)
        if info is None:
            await self.load_symbols()
            info = self._symbols.get(symbol)
        if info is None:
            raise SymbolNotFoundError(f"Unknown symbol {symbol}", context={"symbol": symbol})
        return info

    # ------------------------------------------------------------------ market data

    async def get_klines(
        self,
        symbol: str,
        timeframe: Timeframe,
        *,
        limit: int = 500,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[Candle]:
        params: dict[str, Any] = {
            "symbol": symbol,
            "interval": timeframe.value,
            "limit": min(limit, 1000),
        }
        if start_time is not None:
            params["startTime"] = to_millis(start_time)
        if end_time is not None:
            params["endTime"] = to_millis(end_time)
        raw = await self._request("GET", f"{self._api_prefix}/klines", params=params, weight=2)
        return [self._parse_kline(symbol, timeframe, row) for row in raw]

    def _parse_kline(self, symbol: str, timeframe: Timeframe, row: list[Any]) -> Candle:
        return Candle(
            symbol=symbol,
            timeframe=timeframe,
            open_time=from_millis(int(row[0])),
            close_time=from_millis(int(row[6])),
            open=to_decimal(row[1]),
            high=to_decimal(row[2]),
            low=to_decimal(row[3]),
            close=to_decimal(row[4]),
            volume=to_decimal(row[5]),
            quote_volume=to_decimal(row[7]),
            trades=int(row[8]),
            is_closed=True,
        )

    async def get_ticker(self, symbol: str) -> Ticker:
        data = await self._request(
            "GET", f"{self._api_prefix}/ticker/24hr", params={"symbol": symbol}, weight=2
        )
        book = await self._request(
            "GET", f"{self._api_prefix}/ticker/bookTicker", params={"symbol": symbol}, weight=2
        )
        return Ticker(
            symbol=symbol,
            last_price=to_decimal(data["lastPrice"]),
            bid_price=to_decimal(book.get("bidPrice", "0")),
            ask_price=to_decimal(book.get("askPrice", "0")),
            bid_qty=to_decimal(book.get("bidQty", "0")),
            ask_qty=to_decimal(book.get("askQty", "0")),
            volume_24h=to_decimal(data.get("volume", "0")),
            quote_volume_24h=to_decimal(data.get("quoteVolume", "0")),
            price_change_pct_24h=to_decimal(data.get("priceChangePercent", "0")),
        )

    async def get_order_book(self, symbol: str, *, depth: int = 20) -> OrderBook:
        data = await self._request(
            "GET", f"{self._api_prefix}/depth",
            params={"symbol": symbol, "limit": depth}, weight=1,
        )
        return OrderBook(
            symbol=symbol,
            bids=[OrderBookLevel(price=to_decimal(p), quantity=to_decimal(q)) for p, q in data["bids"]],
            asks=[OrderBookLevel(price=to_decimal(p), quantity=to_decimal(q)) for p, q in data["asks"]],
        )

    # ------------------------------------------------------------------ account

    async def get_account(self) -> AccountInfo:
        data = await self._request(
            "GET", f"{self._api_prefix}/account", weight=20, signed=True
        )
        balances: dict[str, Balance] = {}
        for bal in data.get("balances", []):
            free = to_decimal(bal["free"])
            locked = to_decimal(bal["locked"])
            if free > 0 or locked > 0:
                balances[bal["asset"]] = Balance(asset=bal["asset"], free=free, locked=locked)
        quote = self._settings.quote_asset
        available = balances.get(quote, Balance(asset=quote)).free
        equity = sum((b.total for b in balances.values() if b.asset == quote), Decimal("0"))
        return AccountInfo(
            balances=balances,
            positions=[],
            total_equity=equity or available,
            available_balance=available,
            quote_asset=quote,
        )

    async def get_balance(self, asset: str) -> Balance:
        account = await self.get_account()
        return account.balance_of(asset)

    async def get_positions(self, symbol: str | None = None) -> list[Position]:
        # Spot has no leveraged positions; positions are derived from balances.
        _ = symbol
        return []

    # ------------------------------------------------------------------ orders

    async def create_order(self, request: OrderRequest) -> Order:
        info = await self.get_symbol_info(request.symbol)
        qty = info.round_qty(request.quantity)
        if qty <= 0:
            raise InvalidOrderError(
                "Quantity rounds to zero", context={"symbol": request.symbol, "qty": str(request.quantity)}
            )
        # Spot has no reduce-only flag, so a protective SELL is clamped to the free
        # base balance — any residual desync then under-sells instead of selling
        # assets we don't hold (which would error or sell unrelated holdings).
        if request.reduce_only and request.side is Side.SELL:
            try:
                free = info.round_qty((await self.get_balance(info.base_asset)).free)
            except Exception as exc:  # noqa: BLE001 - best-effort clamp; fall back to requested
                self.log.warning("reduce_balance_lookup_failed", symbol=request.symbol, error=str(exc))
                free = qty
            if 0 < free < qty:
                self.log.info("reduce_clamped_to_balance", symbol=request.symbol,
                              requested=float(qty), free=float(free))
                qty = free
            if qty <= 0:
                raise InvalidOrderError(
                    "No free base balance to reduce",
                    context={"symbol": request.symbol, "base": info.base_asset},
                )
        params: dict[str, Any] = {
            "symbol": request.symbol,
            "side": request.side.value.upper(),
            "type": _ORDER_TYPE_TO_BINANCE[request.type],
            "quantity": _fmt(qty),
        }
        if request.client_order_id:
            params["newClientOrderId"] = request.client_order_id
        if request.type not in (OrderType.MARKET,):
            if request.price is not None:
                params["price"] = _fmt(info.round_price(request.price))
            params["timeInForce"] = request.time_in_force.value.upper()
        if request.stop_price is not None:
            params["stopPrice"] = _fmt(info.round_price(request.stop_price))
        data = await self._request(
            "POST", f"{self._api_prefix}/order", params=params, weight=1, signed=True, is_order=True
        )
        return self._parse_order(data, request)

    async def cancel_order(
        self, symbol: str, *, order_id: str | None = None, client_order_id: str | None = None
    ) -> Order:
        params = self._order_ident(symbol, order_id, client_order_id)
        data = await self._request(
            "DELETE", f"{self._api_prefix}/order", params=params, weight=1, signed=True
        )
        return self._parse_order(data)

    async def cancel_all_orders(self, symbol: str) -> list[Order]:
        data = await self._request(
            "DELETE", f"{self._api_prefix}/openOrders",
            params={"symbol": symbol}, weight=1, signed=True,
        )
        return [self._parse_order(item) for item in data]

    async def get_order(
        self, symbol: str, *, order_id: str | None = None, client_order_id: str | None = None
    ) -> Order:
        params = self._order_ident(symbol, order_id, client_order_id)
        data = await self._request(
            "GET", f"{self._api_prefix}/order", params=params, weight=4, signed=True
        )
        return self._parse_order(data)

    async def get_open_orders(self, symbol: str | None = None) -> list[Order]:
        params = {"symbol": symbol} if symbol else {}
        weight = 6 if symbol else 80
        data = await self._request(
            "GET", f"{self._api_prefix}/openOrders", params=params, weight=weight, signed=True
        )
        return [self._parse_order(item) for item in data]

    @staticmethod
    def _order_ident(
        symbol: str, order_id: str | None, client_order_id: str | None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"symbol": symbol}
        if order_id is not None:
            params["orderId"] = order_id
        elif client_order_id is not None:
            params["origClientOrderId"] = client_order_id
        else:
            raise InvalidOrderError("order_id or client_order_id is required")
        return params

    def _parse_order(self, data: dict[str, Any], request: OrderRequest | None = None) -> Order:
        side = Side(data["side"].lower()) if "side" in data else (request.side if request else Side.BUY)
        order_type = _from_binance_type(data.get("type", "MARKET"))
        executed = to_decimal(data.get("executedQty", "0"))
        cumm_quote = to_decimal(data.get("cummulativeQuoteQty", "0"))
        avg = (cumm_quote / executed) if executed > 0 else None
        return Order(
            client_order_id=data.get("clientOrderId") or (request.client_order_id if request else None) or "",
            exchange_order_id=str(data["orderId"]) if "orderId" in data else None,
            symbol=data.get("symbol", request.symbol if request else ""),
            market=self.market,
            side=side,
            type=order_type,
            status=_BINANCE_TO_STATUS.get(data.get("status", "NEW"), OrderStatus.NEW),
            time_in_force=_tif(data.get("timeInForce")),
            quantity=to_decimal(data.get("origQty", request.quantity if request else "0")),
            price=to_decimal(data["price"]) if data.get("price") not in (None, "0", "0.00000000") else None,
            stop_price=to_decimal(data["stopPrice"]) if data.get("stopPrice") not in (None, "0", "0.00000000") else None,
            filled_qty=executed,
            avg_fill_price=avg,
        )

    # ------------------------------------------------------------------ streams

    async def stream_klines(self, symbol: str, timeframe: Timeframe) -> AsyncIterator[Candle]:
        assert self._ws is not None, "connect() first"
        stream = f"{symbol.lower()}@kline_{timeframe.value}"
        queue = self._ws.subscribe(stream)
        async for msg in queue:
            k = msg.get("k", {})
            if not k.get("x"):  # only closed candles
                continue
            yield Candle(
                symbol=symbol,
                timeframe=timeframe,
                open_time=from_millis(int(k["t"])),
                close_time=from_millis(int(k["T"])),
                open=to_decimal(k["o"]),
                high=to_decimal(k["h"]),
                low=to_decimal(k["l"]),
                close=to_decimal(k["c"]),
                volume=to_decimal(k["v"]),
                quote_volume=to_decimal(k.get("q", "0")),
                trades=int(k.get("n", 0)),
                is_closed=True,
            )

    async def stream_tickers(self, symbols: Sequence[str]) -> AsyncIterator[Ticker]:
        assert self._ws is not None, "connect() first"
        queues = [self._ws.subscribe(f"{s.lower()}@ticker") for s in symbols]
        import asyncio

        async def _drain(q: Any) -> AsyncIterator[Ticker]:
            async for msg in q:
                yield Ticker(
                    symbol=msg["s"],
                    last_price=to_decimal(msg["c"]),
                    bid_price=to_decimal(msg.get("b", "0")),
                    ask_price=to_decimal(msg.get("a", "0")),
                    volume_24h=to_decimal(msg.get("v", "0")),
                    quote_volume_24h=to_decimal(msg.get("q", "0")),
                    price_change_pct_24h=to_decimal(msg.get("P", "0")),
                )

        merged: asyncio.Queue[Ticker] = asyncio.Queue()

        async def _pump(q: Any) -> None:
            async for ticker in _drain(q):
                await merged.put(ticker)

        tasks = [asyncio.create_task(_pump(q)) for q in queues]
        try:
            while True:
                yield await merged.get()
        finally:
            for task in tasks:
                task.cancel()

    async def stream_user_events(self) -> AsyncIterator[StreamEvent]:
        assert self._ws is not None, "connect() first"
        self._listen_key = await self._create_listen_key()
        queue = self._ws.subscribe(self._listen_key)
        async for msg in queue:
            yield StreamEvent(
                kind=msg.get("e", "unknown"), payload=msg, received_at=utcnow()
            )

    def parse_user_event(self, event: StreamEvent) -> OrderUpdate | None:
        """Translate a spot ``executionReport`` into a normalized OrderUpdate."""
        if event.kind != "executionReport":
            return None
        m = event.payload
        status = _BINANCE_TO_STATUS.get(str(m.get("X", "")))
        if status is None:
            return None
        last_price = to_decimal(str(m.get("L", "0")))
        return OrderUpdate(
            client_order_id=str(m.get("c", "")),
            exchange_order_id=str(m.get("i", "")) or None,
            symbol=str(m.get("s", "")),
            status=status,
            filled_qty=to_decimal(str(m.get("z", "0"))),
            fill_price=last_price if last_price > 0 else None,
            commission=to_decimal(str(m.get("n", "0"))),
            side=Side(str(m.get("S", "BUY")).lower()),
        )

    async def _create_listen_key(self) -> str:
        data = await self._request(
            "POST", f"{self._api_prefix}/userDataStream", weight=2, send_api_key=True
        )
        return str(data["listenKey"])

    # ------------------------------------------------------------------ REST core

    @async_retry(max_attempts=4, base_delay=0.5, retry_on=(ExchangeConnectionError, RateLimitError))
    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        weight: int = 1,
        signed: bool = False,
        send_api_key: bool = False,
        is_order: bool = False,
    ) -> Any:
        if self._session is None:
            raise ExchangeConnectionError("Gateway not connected; call connect() first")
        await self._rate.acquire(weight, is_order=is_order)
        params = dict(params or {})
        if signed:
            params["timestamp"] = int(time.time() * 1000) + self._time_offset_ms
            params["recvWindow"] = self._cfg.recv_window
            query = urllib.parse.urlencode(params, doseq=True)
            params_signature = self._sign(query)
            params["signature"] = params_signature
        url = f"{self._rest_url}{path}"
        headers = {}
        if (signed or send_api_key) and self._cfg.api_key:
            headers["X-MBX-APIKEY"] = self._cfg.api_key
        try:
            async with self._session.request(method, url, params=params, headers=headers) as resp:
                self._track_weight(resp.headers)
                body = await resp.json(content_type=None)
                if resp.status >= 400:
                    self._raise_for_error(resp.status, body)
                return body
        except aiohttp.ClientError as exc:
            raise ExchangeConnectionError(f"HTTP request failed: {exc}") from exc

    def _sign(self, query: str) -> str:
        secret = self._cfg.api_secret.get_secret_value().encode()
        return hmac.new(secret, query.encode(), hashlib.sha256).hexdigest()

    def _track_weight(self, headers: Any) -> None:
        for key, value in headers.items():
            if key.lower().startswith("x-mbx-used-weight"):
                with __import__("contextlib").suppress(ValueError):
                    self._rate.update_used_weight(int(value))

    def _raise_for_error(self, status: int, body: Any) -> None:
        code = body.get("code") if isinstance(body, dict) else None
        msg = body.get("msg", "Unknown error") if isinstance(body, dict) else str(body)
        ctx = {"status": status, "code": code}
        if status == 429 or status == 418:
            retry_after = 1.0
            self._rate.pause_until(retry_after)
            raise RateLimitError(msg, retry_after=retry_after, code=code, context=ctx)
        if status in (401, 403) or code == -2014 or code == -1022:
            raise AuthenticationError(msg, code=code, context=ctx)
        if code == _CODE_BALANCE:
            raise InsufficientBalanceError(msg, code=code, context=ctx)
        if code in _CODE_UNKNOWN_ORDER:
            raise OrderNotFoundError(msg, code=code, context=ctx)
        if code == _CODE_BAD_SYMBOL:
            raise SymbolNotFoundError(msg, code=code, context=ctx)
        if status >= 500:
            raise ExchangeConnectionError(msg, code=code, context=ctx)
        raise InvalidOrderError(msg, code=code, context=ctx)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt(value: Decimal) -> str:
    """Format a Decimal without scientific notation for the API."""
    return format(value.normalize(), "f")


def _from_binance_type(value: str) -> OrderType:
    for ot, name in _ORDER_TYPE_TO_BINANCE.items():
        if name == value:
            return ot
    return OrderType.LIMIT


def _tif(value: str | None) -> TimeInForce:
    mapping = {"GTC": TimeInForce.GTC, "IOC": TimeInForce.IOC, "FOK": TimeInForce.FOK, "GTX": TimeInForce.GTX}
    return mapping.get(value or "GTC", TimeInForce.GTC)


__all__ = ["BinanceSpotGateway"]
