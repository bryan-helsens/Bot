"""Liquidity scanner — ranks symbols by tradable liquidity.

Liquidity matters for execution quality: thin markets mean slippage. This
scanner scores symbols by their average quote-volume (turnover in the quote
asset) over the lookback, optionally enriched with live order-book depth when a
source providing ``get_order_book`` is available. Higher score = more liquid.
"""

from __future__ import annotations

import numpy as np

from quantbot.core.constants import Timeframe
from quantbot.core.logging import LoggerMixin
from quantbot.scanners.base import OHLCV, BaseScanner, ScanResult


class LiquidityScanner(BaseScanner):
    """Rank symbols by average quote-volume turnover."""

    def __init__(self, *args, min_quote_volume: float = 0.0, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._min_quote_volume = min_quote_volume

    def score(self, data: OHLCV) -> ScanResult | None:
        if len(data) < 2:
            return None
        # Quote volume per bar ≈ close * base volume; average over the window.
        quote_vol = data.closes * data.volumes
        avg_quote = float(np.mean(quote_vol))
        if avg_quote < self._min_quote_volume:
            return None
        # Penalise erratic volume (less reliable liquidity) via coefficient of variation.
        std = float(np.std(quote_vol))
        cv = std / avg_quote if avg_quote > 0 else 0.0
        score = avg_quote / (1.0 + cv)
        return ScanResult(
            symbol=data.symbol,
            score=score,
            metrics={
                "avg_quote_volume": round(avg_quote, 2),
                "volume_cv": round(cv, 3),
            },
        )


class OrderBookLiquidityScanner(LoggerMixin):
    """Score liquidity from live order-book depth (top-N levels) per symbol.

    Separate from :class:`LiquidityScanner` because it needs a source exposing
    ``get_order_book`` rather than only klines. Scores by the total quote value
    resting within a price band of the mid price (tighter band = stricter).
    """

    def __init__(self, source, *, depth: int = 50, band_pct: float = 0.005) -> None:
        self._source = source
        self._depth = depth
        self._band = band_pct

    async def scan(self, symbols, *, top: int | None = None) -> list[ScanResult]:
        results: list[ScanResult] = []
        for symbol in symbols:
            try:
                book = await self._source.get_order_book(symbol, depth=self._depth)
            except Exception as exc:  # noqa: BLE001
                self.log.warning("orderbook_scan_error", symbol=symbol, error=str(exc))
                continue
            mid = book.best_bid and book.best_ask
            if not mid:
                continue
            mid_price = (float(book.best_bid) + float(book.best_ask)) / 2  # type: ignore[arg-type]
            lower = mid_price * (1 - self._band)
            upper = mid_price * (1 + self._band)
            bid_value = sum(
                float(lvl.price) * float(lvl.quantity) for lvl in book.bids if float(lvl.price) >= lower
            )
            ask_value = sum(
                float(lvl.price) * float(lvl.quantity) for lvl in book.asks if float(lvl.price) <= upper
            )
            results.append(
                ScanResult(
                    symbol=symbol,
                    score=bid_value + ask_value,
                    metrics={"bid_depth": round(bid_value, 2), "ask_depth": round(ask_value, 2)},
                )
            )
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top] if top else results


__all__ = ["LiquidityScanner", "OrderBookLiquidityScanner"]
