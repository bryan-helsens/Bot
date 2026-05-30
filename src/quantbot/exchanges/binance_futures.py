"""Binance USD-M Futures exchange adapter.

Subclasses :class:`~quantbot.exchanges.binance_spot.BinanceSpotGateway`, reusing
its REST core, signing, rate limiting and streaming machinery, and overriding the
pieces that differ on the futures API (``/fapi/v1`` & ``/fapi/v2`` endpoints,
leverage / margin mode, and real leveraged positions).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from quantbot.core.constants import MarketType, PositionSide, PositionStatus
from quantbot.core.models import Balance, Position
from quantbot.core.utils import to_decimal
from quantbot.exchanges.base import AccountInfo
from quantbot.exchanges.binance_spot import BinanceSpotGateway


class BinanceFuturesGateway(BinanceSpotGateway):
    """Concrete Binance USD-M Futures adapter."""

    market: MarketType = MarketType.FUTURES

    # ------------------------------------------------------------------ endpoints

    @property
    def _api_prefix(self) -> str:
        return "/fapi/v1"

    @property
    def _account_prefix(self) -> str:
        """Futures account/position data lives under ``/fapi/v2``."""
        return "/fapi/v2"

    @property
    def _exchange_info_path(self) -> str:
        return f"{self._api_prefix}/exchangeInfo"

    # ------------------------------------------------------------------ metadata

    def _parse_symbol_info(self, item: dict[str, Any]) -> Any:
        # Futures exposes precision directly and uses a different notional filter.
        filters = {f["filterType"]: f for f in item.get("filters", [])}
        price_filter = filters.get("PRICE_FILTER", {})
        lot = filters.get("LOT_SIZE", {})
        market_lot = filters.get("MARKET_LOT_SIZE", {})
        notional = filters.get("MIN_NOTIONAL", {})
        from quantbot.core.models import SymbolInfo

        return SymbolInfo(
            symbol=item["symbol"],
            base_asset=item["baseAsset"],
            quote_asset=item["quoteAsset"],
            market=self.market,
            price_precision=int(item.get("pricePrecision", 8)),
            qty_precision=int(item.get("quantityPrecision", 8)),
            tick_size=to_decimal(price_filter.get("tickSize", "0.00000001")),
            step_size=to_decimal(lot.get("stepSize", market_lot.get("stepSize", "0.00000001"))),
            min_qty=to_decimal(lot.get("minQty", "0")),
            max_qty=to_decimal(lot.get("maxQty", "0")),
            min_notional=to_decimal(notional.get("notional", "0")),
            filters=filters,
        )

    # ------------------------------------------------------------------ account

    async def get_account(self) -> AccountInfo:
        data = await self._request(
            "GET", f"{self._account_prefix}/account", weight=5, signed=True
        )
        quote = self._settings.quote_asset
        balances: dict[str, Balance] = {}
        for asset in data.get("assets", []):
            wallet = to_decimal(asset.get("walletBalance", "0"))
            if wallet > 0:
                balances[asset["asset"]] = Balance(
                    asset=asset["asset"],
                    free=to_decimal(asset.get("availableBalance", "0")),
                    locked=wallet - to_decimal(asset.get("availableBalance", "0")),
                )
        positions = [
            self._parse_position(p)
            for p in data.get("positions", [])
            if to_decimal(p.get("positionAmt", "0")) != 0
        ]
        return AccountInfo(
            balances=balances,
            positions=positions,
            total_equity=to_decimal(data.get("totalMarginBalance", "0")),
            available_balance=to_decimal(data.get("availableBalance", "0")),
            quote_asset=quote,
        )

    async def get_positions(self, symbol: str | None = None) -> list[Position]:
        params = {"symbol": symbol} if symbol else {}
        data = await self._request(
            "GET", f"{self._account_prefix}/positionRisk", params=params, weight=5, signed=True
        )
        return [
            self._parse_position(p)
            for p in data
            if to_decimal(p.get("positionAmt", "0")) != 0
        ]

    def _parse_position(self, data: dict[str, Any]) -> Position:
        amount = to_decimal(data.get("positionAmt", "0"))
        side = PositionSide.LONG if amount > 0 else PositionSide.SHORT
        entry = to_decimal(data.get("entryPrice", "0"))
        mark = to_decimal(data.get("markPrice", "0")) or None
        leverage = int(to_decimal(data.get("leverage", "1")))
        return Position(
            symbol=data["symbol"],
            market=self.market,
            side=side,
            status=PositionStatus.OPEN,
            quantity=abs(amount),
            entry_price=entry if entry > 0 else Decimal("0.00000001"),
            mark_price=mark,
            leverage=max(leverage, 1),
            realized_pnl=to_decimal(data.get("unRealizedProfit", "0")),
            meta={"isolated": data.get("isolated", False)},
        )

    # ------------------------------------------------------------------ leverage / margin

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        await self._request(
            "POST", f"{self._api_prefix}/leverage",
            params={"symbol": symbol, "leverage": int(leverage)}, weight=1, signed=True,
        )
        self.log.info("leverage_set", symbol=symbol, leverage=leverage)

    async def set_margin_mode(self, symbol: str, isolated: bool) -> None:
        from quantbot.core.exceptions import ExchangeError

        try:
            await self._request(
                "POST", f"{self._api_prefix}/marginType",
                params={"symbol": symbol, "marginType": "ISOLATED" if isolated else "CROSSED"},
                weight=1, signed=True,
            )
        except ExchangeError as exc:
            # -4046: "No need to change margin type" is benign and idempotent.
            if exc.code == -4046:
                return
            raise
        self.log.info("margin_mode_set", symbol=symbol, isolated=isolated)

    # ------------------------------------------------------------------ user stream

    async def _create_listen_key(self) -> str:
        data = await self._request(
            "POST", f"{self._api_prefix}/listenKey", weight=1, send_api_key=True
        )
        return str(data["listenKey"])


__all__ = ["BinanceFuturesGateway"]
