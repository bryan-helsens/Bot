"""Bitvavo spot exchange adapter (EU/Belgium-friendly: SEPA & Bancontact deposits).

Implements the :class:`~quantbot.exchanges.base.ExchangeGateway` port against the
Bitvavo REST API (https://docs.bitvavo.com). Design notes:

* **Symbols** — the bot uses concatenated symbols (``BTCEUR``); Bitvavo uses
  dash-separated markets (``BTC-EUR``). Translation happens ONLY inside this
  adapter, so the rest of the system keeps one symbol format.
* **Streams via polling** — Bitvavo's websocket protocol differs from Binance's
  and the shared WebSocketManager is Binance-shaped, so live candles/tickers are
  produced by polling REST at a rate well inside Bitvavo's 1000 weight/min
  budget. For 5m/15m candles a 20-60s poll adds negligible latency.
* **No user-event stream** — :meth:`stream_user_events` yields nothing; the
  engine already degrades gracefully (local StopManager is the backstop), the
  same path used when the Binance testnet user stream is unavailable.
* **No testnet** — Bitvavo has no sandbox. LIVE mode here is ALWAYS real money
  and is blocked by the ALLOW_LIVE_REAL_ORDERS interlock; validate with
  TRADING_MODE=paper (real market data, simulated fills) first.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import aiohttp

from quantbot.core.config import Settings
from quantbot.core.constants import (
    MarketType,
    OrderStatus,
    OrderType,
    Side,
    Timeframe,
)
from quantbot.core.events import EventBus
from quantbot.core.exceptions import ExchangeError, InvalidOrderError, SymbolNotFoundError
from quantbot.core.models import (
    Balance,
    Candle,
    Order,
    OrderBook,
    OrderBookLevel,
    Position,
    SymbolInfo,
    Ticker,
)
from quantbot.exchanges.base import AccountInfo, ExchangeGateway, OrderRequest, StreamEvent

#: Bitvavo-supported candle intervals (subset the bot may request).
_SUPPORTED_INTERVALS = {"1m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d"}

_STATUS_MAP: dict[str, OrderStatus] = {
    "new": OrderStatus.NEW,
    "awaitingtrigger": OrderStatus.NEW,
    "partiallyfilled": OrderStatus.PARTIALLY_FILLED,
    "filled": OrderStatus.FILLED,
    "canceled": OrderStatus.CANCELED,
    "canceledauction": OrderStatus.CANCELED,
    "canceledselftradeprevention": OrderStatus.CANCELED,
    "canceledioc": OrderStatus.CANCELED,
    "canceledfok": OrderStatus.CANCELED,
    "canceledmarketprotection": OrderStatus.CANCELED,
    "canceledpostonly": OrderStatus.CANCELED,
    "expired": OrderStatus.EXPIRED,
    "rejected": OrderStatus.REJECTED,
}

_ORDER_TYPE_MAP: dict[OrderType, str] = {
    OrderType.MARKET: "market",
    OrderType.LIMIT: "limit",
    OrderType.STOP_LOSS: "stopLoss",
    OrderType.STOP_LOSS_LIMIT: "stopLossLimit",
    OrderType.TAKE_PROFIT: "takeProfit",
    OrderType.TAKE_PROFIT_LIMIT: "takeProfitLimit",
}


def _fmt(value: Decimal) -> str:
    """Serialize a Decimal without scientific notation or trailing zeros."""
    text = format(value.normalize(), "f")
    return text if text else "0"


class BitvavoGateway(ExchangeGateway):
    """Bitvavo spot adapter (REST + polling streams)."""

    market = MarketType.SPOT

    def __init__(self, settings: Settings, *, event_bus: EventBus | None = None) -> None:
        self._settings = settings
        self._cfg = settings.bitvavo
        self._bus = event_bus
        self._base_url = self._cfg.rest_base_url.rstrip("/")
        self._session: aiohttp.ClientSession | None = None
        self._symbols: dict[str, SymbolInfo] = {}
        # Bitvavo identifies orders by exchange orderId only; remember our
        # client ids so cancel/get by client_order_id still works.
        self._client_ids: dict[str, str] = {}
        self._closing = False

    # ------------------------------------------------------------------ symbols

    def _to_market(self, symbol: str) -> str:
        """``BTCEUR`` -> ``BTC-EUR`` (quote asset from settings)."""
        quote = self._settings.quote_asset
        if symbol.endswith(quote):
            return f"{symbol[: -len(quote)]}-{quote}"
        raise SymbolNotFoundError(
            f"Symbol {symbol!r} does not end with quote asset {quote!r}",
            context={"symbol": symbol, "quote": quote},
        )

    def _from_market(self, market: str) -> str:
        """``BTC-EUR`` -> ``BTCEUR``."""
        return market.replace("-", "")

    # ------------------------------------------------------------------ transport

    async def connect(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        await self.load_symbols()
        self.log.info("bitvavo_connected", markets=len(self._symbols))

    async def close(self) -> None:
        self._closing = True
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    def _sign(self, timestamp: int, method: str, path: str, body: str) -> str:
        message = f"{timestamp}{method}/v2{path}{body}"
        return hmac.new(
            self._cfg.api_secret.get_secret_value().encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        signed: bool = False,
    ) -> Any:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        query = ""
        if params:
            from urllib.parse import urlencode

            query = "?" + urlencode(params)
        payload = json.dumps(body, separators=(",", ":")) if body is not None else ""
        headers: dict[str, str] = {}
        if signed:
            if not self._cfg.api_key:
                raise ExchangeError("Bitvavo API key not configured")
            ts = int(time.time() * 1000)
            headers = {
                "bitvavo-access-key": self._cfg.api_key,
                "bitvavo-access-timestamp": str(ts),
                "bitvavo-access-signature": self._sign(ts, method, path + query, payload),
                "bitvavo-access-window": str(self._cfg.access_window_ms),
            }
        if payload:
            headers["Content-Type"] = "application/json"

        async with self._session.request(
            method,
            f"{self._base_url}{path}{query}",
            data=payload if payload else None,
            headers=headers,
        ) as resp:
            text = await resp.text()
            data = json.loads(text) if text else {}
            if resp.status >= 400 or (isinstance(data, dict) and "errorCode" in data):
                code = data.get("errorCode") if isinstance(data, dict) else None
                message = data.get("error") if isinstance(data, dict) else text
                raise ExchangeError(
                    f"{message} (status={resp.status}, code={code})",
                    context={"path": path, "code": code},
                )
            return data

    # ------------------------------------------------------------------ lifecycle info

    async def ping(self) -> float:
        started = time.monotonic()
        await self._request("GET", "/time")
        return time.monotonic() - started

    async def server_time(self) -> datetime:
        data = await self._request("GET", "/time")
        return datetime.fromtimestamp(int(data["time"]) / 1000, tz=UTC)

    # ------------------------------------------------------------------ metadata

    async def load_symbols(self) -> dict[str, SymbolInfo]:
        data = await self._request("GET", "/markets")
        symbols: dict[str, SymbolInfo] = {}
        for entry in data:
            if entry.get("status") != "trading":
                continue
            market = entry["market"]
            symbol = self._from_market(market)
            amount_decimals = entry.get("amountPrecision")
            step = Decimal(1).scaleb(-int(amount_decimals)) if amount_decimals is not None else Decimal("0.00000001")
            symbols[symbol] = SymbolInfo(
                symbol=symbol,
                base_asset=entry.get("base", ""),
                quote_asset=entry.get("quote", ""),
                market=MarketType.SPOT,
                step_size=step,
                min_qty=Decimal(str(entry.get("minOrderInBaseAsset", "0") or "0")),
                min_notional=Decimal(str(entry.get("minOrderInQuoteAsset", "0") or "0")),
            )
        self._symbols = symbols
        self.log.info("symbols_loaded", count=len(symbols))
        return symbols

    async def get_symbol_info(self, symbol: str) -> SymbolInfo:
        info = self._symbols.get(symbol)
        if info is None:
            await self.load_symbols()
            info = self._symbols.get(symbol)
        if info is None:
            raise SymbolNotFoundError(f"Unknown symbol {symbol}", context={"symbol": symbol})
        return info

    # ------------------------------------------------------------------ market data

    def _parse_candle(self, symbol: str, timeframe: Timeframe, row: list) -> Candle:
        open_time = datetime.fromtimestamp(int(row[0]) / 1000, tz=UTC)
        return Candle(
            symbol=symbol,
            timeframe=timeframe,
            open_time=open_time,
            close_time=open_time + timedelta(seconds=timeframe.seconds),
            open=Decimal(str(row[1])),
            high=Decimal(str(row[2])),
            low=Decimal(str(row[3])),
            close=Decimal(str(row[4])),
            volume=Decimal(str(row[5])),
        )

    async def get_klines(
        self,
        symbol: str,
        timeframe: Timeframe,
        *,
        limit: int = 500,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[Candle]:
        if timeframe.value not in _SUPPORTED_INTERVALS:
            raise ExchangeError(f"Bitvavo does not support the {timeframe.value} interval")
        params: dict[str, Any] = {"interval": timeframe.value, "limit": min(limit, 1440)}
        if start_time is not None:
            params["start"] = int(start_time.timestamp() * 1000)
        if end_time is not None:
            params["end"] = int(end_time.timestamp() * 1000)
        data = await self._request("GET", f"/{self._to_market(symbol)}/candles", params=params)
        # Bitvavo returns candles NEWEST FIRST; the port contract is oldest first.
        candles = [self._parse_candle(symbol, timeframe, row) for row in data]
        candles.sort(key=lambda c: c.open_time)
        return candles

    async def get_ticker(self, symbol: str) -> Ticker:
        market = self._to_market(symbol)
        price = await self._request("GET", "/ticker/price", params={"market": market})
        book = await self._request("GET", "/ticker/book", params={"market": market})
        return Ticker(
            symbol=symbol,
            last_price=Decimal(str(price.get("price", "0"))),
            bid_price=Decimal(str(book.get("bid") or "0")),
            ask_price=Decimal(str(book.get("ask") or "0")),
            bid_qty=Decimal(str(book.get("bidSize") or "0")),
            ask_qty=Decimal(str(book.get("askSize") or "0")),
        )

    async def get_order_book(self, symbol: str, *, depth: int = 20) -> OrderBook:
        data = await self._request(
            "GET", f"/{self._to_market(symbol)}/book", params={"depth": depth}
        )
        return OrderBook(
            symbol=symbol,
            bids=[OrderBookLevel(price=Decimal(p), quantity=Decimal(q)) for p, q in data.get("bids", [])],
            asks=[OrderBookLevel(price=Decimal(p), quantity=Decimal(q)) for p, q in data.get("asks", [])],
        )

    # ------------------------------------------------------------------ account

    async def _fetch_balances(self) -> dict[str, Balance]:
        data = await self._request("GET", "/balance", signed=True)
        out: dict[str, Balance] = {}
        for entry in data:
            free = Decimal(str(entry.get("available", "0")))
            locked = Decimal(str(entry.get("inOrder", "0")))
            if free > 0 or locked > 0:
                out[entry["symbol"]] = Balance(asset=entry["symbol"], free=free, locked=locked)
        return out

    async def get_account(self) -> AccountInfo:
        balances = await self._fetch_balances()
        quote = self._settings.quote_asset
        equity = balances.get(quote, Balance(asset=quote)).total
        # Value held base assets of CONFIGURED symbols using one bulk price call.
        held_bases = {
            self._symbols[s].base_asset: s
            for s in self._settings.symbols
            if s in self._symbols and balances.get(self._symbols[s].base_asset, Balance(asset="x")).total > 0
        }
        if held_bases:
            try:
                prices = await self._request("GET", "/ticker/price")
                by_market = {p["market"]: Decimal(str(p["price"])) for p in prices}
                for base, symbol in held_bases.items():
                    price = by_market.get(self._to_market(symbol))
                    if price is not None:
                        equity += balances[base].total * price
            except Exception as exc:  # noqa: BLE001 - valuation is best-effort
                self.log.warning("base_valuation_failed", error=str(exc))
        return AccountInfo(
            balances=balances,
            positions=[],
            total_equity=equity,
            available_balance=balances.get(quote, Balance(asset=quote)).free,
            quote_asset=quote,
        )

    async def get_balance(self, asset: str) -> Balance:
        balances = await self._fetch_balances()
        return balances.get(asset, Balance(asset=asset))

    async def get_positions(self, symbol: str | None = None) -> list[Position]:
        return []  # spot: holdings are balances, not positions

    # ------------------------------------------------------------------ orders

    def _build_order_body(self, request: OrderRequest, qty: Decimal) -> dict[str, Any]:
        body: dict[str, Any] = {
            "market": self._to_market(request.symbol),
            "side": request.side.value.lower(),
            "orderType": _ORDER_TYPE_MAP.get(request.type, "market"),
            "amount": _fmt(qty),
            "operatorId": self._cfg.operator_id,
        }
        if request.type in (OrderType.LIMIT, OrderType.STOP_LOSS_LIMIT, OrderType.TAKE_PROFIT_LIMIT):
            if request.price is not None:
                body["price"] = _fmt(request.price)
            body["timeInForce"] = request.time_in_force.value.upper()
        if request.type in (
            OrderType.STOP_LOSS, OrderType.STOP_LOSS_LIMIT,
            OrderType.TAKE_PROFIT, OrderType.TAKE_PROFIT_LIMIT,
        ) and request.stop_price is not None:
            body["triggerAmount"] = _fmt(request.stop_price)
            body["triggerType"] = "price"
            body["triggerReference"] = "lastTrade"
        return body

    async def create_order(self, request: OrderRequest) -> Order:
        info = await self.get_symbol_info(request.symbol)
        qty = info.round_qty(request.quantity)
        if qty <= 0:
            raise InvalidOrderError(
                "Quantity rounds to zero",
                context={"symbol": request.symbol, "qty": str(request.quantity)},
            )
        # Spot has no reduce-only: clamp protective SELLs to the free base balance
        # (same behaviour as the Binance spot adapter).
        if request.reduce_only and request.side is Side.SELL:
            try:
                free = info.round_qty((await self.get_balance(info.base_asset)).free)
            except Exception as exc:  # noqa: BLE001 - best-effort clamp
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
        body = self._build_order_body(request, qty)
        data = await self._request("POST", "/order", body=body, signed=True)
        order = self._parse_order(data, request)
        if request.client_order_id:
            self._client_ids[request.client_order_id] = order.exchange_order_id or ""
        return order

    def _parse_order(self, data: dict, request: OrderRequest | None = None) -> Order:
        status = _STATUS_MAP.get(str(data.get("status", "new")).lower(), OrderStatus.NEW)
        filled = Decimal(str(data.get("filledAmount", "0") or "0"))
        filled_quote = Decimal(str(data.get("filledAmountQuote", "0") or "0"))
        avg_price = (filled_quote / filled) if filled > 0 and filled_quote > 0 else None
        symbol = self._from_market(data.get("market", "")) or (request.symbol if request else "")
        side = Side(str(data.get("side", request.side.value if request else "buy")).lower())
        qty = Decimal(str(data.get("amount", "0") or "0"))
        if qty <= 0 and request is not None:
            qty = request.quantity
        return Order(
            client_order_id=(request.client_order_id if request and request.client_order_id
                             else f"bv_{data.get('orderId', 'unknown')}"),
            exchange_order_id=str(data["orderId"]) if data.get("orderId") else None,
            symbol=symbol,
            side=side,
            type=request.type if request else OrderType.MARKET,
            quantity=qty if qty > 0 else Decimal("0.00000001"),
            status=status,
            filled_qty=filled,
            avg_fill_price=avg_price,
            commission=Decimal(str(data.get("feePaid", "0") or "0")),
        )

    def _resolve_order_id(self, order_id: str | None, client_order_id: str | None) -> str:
        exchange_id = order_id or (self._client_ids.get(client_order_id or "") or None)
        if not exchange_id:
            raise ExchangeError(
                "Bitvavo requires the exchange orderId (unknown client id)",
                context={"client_order_id": client_order_id},
            )
        return exchange_id

    async def cancel_order(
        self, symbol: str, *, order_id: str | None = None, client_order_id: str | None = None
    ) -> Order:
        exchange_id = self._resolve_order_id(order_id, client_order_id)
        data = await self._request(
            "DELETE", "/order",
            params={"market": self._to_market(symbol), "orderId": exchange_id,
                    "operatorId": self._cfg.operator_id},
            signed=True,
        )
        return Order(
            client_order_id=client_order_id or f"bv_{exchange_id}",
            exchange_order_id=str(data.get("orderId", exchange_id)),
            symbol=symbol, side=Side.SELL, quantity=Decimal("0.00000001"),
            status=OrderStatus.CANCELED,
        )

    async def cancel_all_orders(self, symbol: str) -> list[Order]:
        data = await self._request(
            "DELETE", "/orders",
            params={"market": self._to_market(symbol), "operatorId": self._cfg.operator_id},
            signed=True,
        )
        return [
            Order(client_order_id=f"bv_{item.get('orderId')}",
                  exchange_order_id=str(item.get("orderId")), symbol=symbol,
                  side=Side.SELL, quantity=Decimal("0.00000001"), status=OrderStatus.CANCELED)
            for item in data
        ]

    async def get_order(
        self, symbol: str, *, order_id: str | None = None, client_order_id: str | None = None
    ) -> Order:
        exchange_id = self._resolve_order_id(order_id, client_order_id)
        data = await self._request(
            "GET", "/order",
            params={"market": self._to_market(symbol), "orderId": exchange_id},
            signed=True,
        )
        return self._parse_order(data)

    async def get_open_orders(self, symbol: str | None = None) -> list[Order]:
        params = {"market": self._to_market(symbol)} if symbol else {}
        data = await self._request("GET", "/ordersOpen", params=params, signed=True)
        return [self._parse_order(item) for item in data]

    # ------------------------------------------------------------------ streams (polling)

    def _poll_interval(self, timeframe: Timeframe) -> float:
        """Seconds between candle polls: fast enough for low latency, far under
        Bitvavo's 1000 weight/min budget even with ~60 streams."""
        return min(60.0, max(15.0, timeframe.seconds / 10))

    async def stream_klines(
        self, symbol: str, timeframe: Timeframe
    ) -> AsyncIterator[Candle]:
        last_open: datetime | None = None
        interval = self._poll_interval(timeframe)
        while not self._closing:
            try:
                candles = await self.get_klines(symbol, timeframe, limit=3)
                # The newest row may still be forming; everything before it is closed.
                for candle in candles[:-1]:
                    if last_open is None or candle.open_time > last_open:
                        last_open = candle.open_time
                        yield candle
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - keep polling through hiccups
                self.log.warning("kline_poll_failed", symbol=symbol, error=str(exc))
            await asyncio.sleep(interval)

    async def stream_tickers(self, symbols: Sequence[str]) -> AsyncIterator[Ticker]:
        wanted = {self._to_market(s): s for s in symbols}
        while not self._closing:
            try:
                data = await self._request("GET", "/ticker/price")
                for entry in data:
                    symbol = wanted.get(entry.get("market", ""))
                    if symbol:
                        yield Ticker(symbol=symbol, last_price=Decimal(str(entry["price"])))
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.log.warning("ticker_poll_failed", error=str(exc))
            await asyncio.sleep(5)

    async def stream_user_events(self) -> AsyncIterator[StreamEvent]:
        """No user-event stream (polling adapter) — the engine's reconcile +
        local StopManager cover exchange-side fills, the same degraded path used
        when the Binance testnet user stream is unavailable."""
        return
        yield  # pragma: no cover - makes this an async generator


__all__ = ["BitvavoGateway"]
