"""Correlation control.

Concentrated, highly-correlated positions defeat diversification: three "different"
longs that all move together are really one oversized bet. :class:`CorrelationMonitor`
maintains a rolling buffer of returns per symbol and, before a new position is
opened, checks whether the candidate is too correlated with the symbols already
held — rejecting it if the average (or maximum) Pearson correlation exceeds the
configured cap.
"""

from __future__ import annotations

from collections import deque
from decimal import Decimal

import numpy as np

from quantbot.core.config import RiskSettings
from quantbot.core.constants import RiskEventType
from quantbot.core.logging import LoggerMixin
from quantbot.risk.limits import LimitCheck


class CorrelationMonitor(LoggerMixin):
    """Track per-symbol returns and gate new positions on correlation."""

    def __init__(self, settings: RiskSettings) -> None:
        self._cfg = settings
        self._lookback = settings.correlation_lookback
        self._returns: dict[str, deque[float]] = {}
        self._last_price: dict[str, float] = {}

    # ------------------------------------------------------------------ ingest

    def update_price(self, symbol: str, price: float | Decimal) -> None:
        """Feed a new price; converts to a log return and buffers it."""
        price = float(price)
        if price <= 0:
            return
        prev = self._last_price.get(symbol)
        self._last_price[symbol] = price
        if prev is None or prev <= 0:
            return
        ret = float(np.log(price / prev))
        buffer = self._returns.setdefault(symbol, deque(maxlen=self._lookback))
        buffer.append(ret)

    def update_prices(self, prices: dict[str, float | Decimal]) -> None:
        """Feed a batch of symbol→price updates."""
        for symbol, price in prices.items():
            self.update_price(symbol, price)

    def seed_returns(self, symbol: str, returns: list[float]) -> None:
        """Directly seed a return series (e.g. from historical warmup)."""
        self._returns[symbol] = deque(returns[-self._lookback :], maxlen=self._lookback)

    # ------------------------------------------------------------------ query

    def correlation(self, symbol_a: str, symbol_b: str) -> float | None:
        """Pearson correlation between two symbols' aligned return series."""
        a = self._returns.get(symbol_a)
        b = self._returns.get(symbol_b)
        if not a or not b:
            return None
        n = min(len(a), len(b))
        if n < 20:  # too few points to be meaningful
            return None
        arr_a = np.array(list(a)[-n:], dtype=np.float64)
        arr_b = np.array(list(b)[-n:], dtype=np.float64)
        if arr_a.std() == 0 or arr_b.std() == 0:
            return None
        corr = float(np.corrcoef(arr_a, arr_b)[0, 1])
        return corr

    def max_correlation(self, candidate: str, held: list[str]) -> tuple[float, str | None]:
        """Highest absolute correlation of *candidate* against any *held* symbol."""
        worst = 0.0
        worst_symbol: str | None = None
        for symbol in held:
            if symbol == candidate:
                continue
            corr = self.correlation(candidate, symbol)
            if corr is None:
                continue
            if abs(corr) > abs(worst):
                worst = corr
                worst_symbol = symbol
        return worst, worst_symbol

    # ------------------------------------------------------------------ check

    def check(self, candidate: str, held: list[str]) -> LimitCheck:
        """Reject *candidate* if too correlated with any currently-held symbol."""
        cap = float(self._cfg.max_correlation)
        if cap >= 1.0 or not held:
            return LimitCheck.ok()
        worst, worst_symbol = self.max_correlation(candidate, held)
        if worst_symbol is not None and abs(worst) > cap:
            return LimitCheck.fail(
                RiskEventType.CORRELATION_BLOCK,
                f"{candidate} correlation {worst:.2f} with {worst_symbol} exceeds cap {cap:.2f}",
                candidate=candidate, correlated_with=worst_symbol, correlation=round(worst, 3),
            )
        return LimitCheck.ok()


__all__ = ["CorrelationMonitor"]
