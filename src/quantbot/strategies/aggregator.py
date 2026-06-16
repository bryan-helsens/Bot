"""Signal aggregation by confluence.

A core trading rule of QuantBot is *only trade when multiple signals agree*.
The :class:`SignalAggregator` collects signals emitted by every strategy for a
symbol within a short time window and combines them into at most one consolidated
signal per side, applying:

* **Consensus** — require at least ``min_consensus`` strategies on the same side.
* **Strength** — require the combined (weighted) strength to clear
  ``min_strength``.
* **Conflict resolution** — if both buy and sell signals exist, the side with
  the greater aggregate strength wins; ties cancel out (no trade).

The consolidated signal carries provenance (which strategies agreed) in its
``meta`` so the risk engine and audit log can record *why* a trade was taken.
This reduces false positives and discourages over-fitting to any single
indicator.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from quantbot.core.config import AggregatorSettings
from quantbot.core.constants import Side, SignalType
from quantbot.core.logging import LoggerMixin
from quantbot.core.models import Signal, utcnow


@dataclass(slots=True)
class _WindowedSignal:
    """A signal tagged with its monotonic arrival time."""

    signal: Signal
    arrived: float


@dataclass(slots=True)
class AggregationResult:
    """Outcome of an aggregation evaluation."""

    signal: Signal | None
    reason: str
    contributors: list[str] = field(default_factory=list)
    buy_strength: float = 0.0
    sell_strength: float = 0.0

    @property
    def actionable(self) -> bool:
        """Whether a tradable consolidated signal was produced."""
        return self.signal is not None


class SignalAggregator(LoggerMixin):
    """Combine per-strategy signals into confluence-gated consolidated signals."""

    def __init__(
        self,
        settings: AggregatorSettings,
        *,
        weights: dict[str, float] | None = None,
    ) -> None:
        """Create an aggregator.

        Args:
            settings: Consensus/strength/window thresholds.
            weights: Optional per-strategy strength weights (defaults to 1.0).
        """
        self._cfg = settings
        self._weights = weights or {}
        # Buffer of recent signals per symbol.
        self._buffer: dict[str, list[_WindowedSignal]] = defaultdict(list)

    # ------------------------------------------------------------------ ingest

    def add(self, signal: Signal) -> AggregationResult:
        """Add a *signal* and immediately evaluate confluence for its symbol."""
        if not signal.is_actionable:
            return AggregationResult(None, "non_actionable")
        now = time.monotonic()
        self._prune(signal.symbol, now)
        self._buffer[signal.symbol].append(_WindowedSignal(signal, now))
        return self.evaluate(signal.symbol)

    def add_many(self, signals: list[Signal]) -> AggregationResult:
        """Add several simultaneously-produced signals, then evaluate once."""
        now = time.monotonic()
        symbol: str | None = None
        for signal in signals:
            if not signal.is_actionable:
                continue
            symbol = signal.symbol
            self._prune(symbol, now)
            self._buffer[symbol].append(_WindowedSignal(signal, now))
        if symbol is None:
            return AggregationResult(None, "non_actionable")
        return self.evaluate(symbol)

    # ------------------------------------------------------------------ evaluate

    def evaluate(self, symbol: str) -> AggregationResult:
        """Evaluate confluence for *symbol* over the current window."""
        now = time.monotonic()
        self._prune(symbol, now)
        windowed = self._buffer.get(symbol, [])
        if not windowed:
            return AggregationResult(None, "empty")

        # Keep only the latest signal per (strategy, side) within the window.
        latest: dict[tuple[str, Side], Signal] = {}
        for item in windowed:
            sig = item.signal
            key = (sig.strategy, sig.side)
            prev = latest.get(key)
            if prev is None or sig.created_at >= prev.created_at:
                latest[key] = sig

        buy = [s for (_strategy, side), s in _items(latest) if side is Side.BUY]
        sell = [s for (_strategy, side), s in _items(latest) if side is Side.SELL]

        buy_strength = self._weighted_strength(buy)
        sell_strength = self._weighted_strength(sell)

        result = self._decide(symbol, buy, sell, buy_strength, sell_strength)
        return result

    def _decide(
        self,
        symbol: str,
        buy: list[Signal],
        sell: list[Signal],
        buy_strength: float,
        sell_strength: float,
    ) -> AggregationResult:
        buy_n = len({s.strategy for s in buy})
        sell_n = len({s.strategy for s in sell})
        min_consensus = self._cfg.min_consensus
        min_strength = self._cfg.min_strength

        buy_ok = buy_n >= min_consensus and buy_strength >= min_strength
        sell_ok = sell_n >= min_consensus and sell_strength >= min_strength

        if buy_ok and sell_ok:
            # Conflict: stronger side wins; a tie cancels out.
            if abs(buy_strength - sell_strength) < 1e-9:
                return AggregationResult(
                    None, "conflict_tie", buy_strength=buy_strength, sell_strength=sell_strength
                )
            if buy_strength > sell_strength:
                return self._consolidate(symbol, Side.BUY, buy, buy_strength, sell_strength)
            return self._consolidate(symbol, Side.SELL, sell, buy_strength, sell_strength)
        if buy_ok:
            return self._consolidate(symbol, Side.BUY, buy, buy_strength, sell_strength)
        if sell_ok:
            return self._consolidate(symbol, Side.SELL, sell, buy_strength, sell_strength)

        return AggregationResult(
            None,
            "below_threshold",
            buy_strength=buy_strength,
            sell_strength=sell_strength,
        )

    def _consolidate(
        self,
        symbol: str,
        side: Side,
        signals: list[Signal],
        buy_strength: float,
        sell_strength: float,
    ) -> AggregationResult:
        """Build the consolidated signal for the winning *side*."""
        contributors = sorted({s.strategy for s in signals})
        # Volume-weighted-ish average of entry prices for robustness.
        ref_price = signals[0].price
        # Aggregate strength is capped at 1.0.
        agg_strength = min(1.0, (buy_strength if side is Side.BUY else sell_strength))
        # Use the tightest stop and the furthest take-profit among contributors.
        stops = [s.stop_loss for s in signals if s.stop_loss is not None]
        tps = [s.take_profit for s in signals if s.take_profit is not None]
        stop_loss = _tightest_stop(side, stops, ref_price)
        take_profit = _furthest_tp(side, tps, ref_price)

        consolidated = Signal(
            # Keep the contributing strategy name(s) so trades are attributable in
            # analytics (e.g. "rsi_dip_buyer" or "ema_trend+rsi_dip_buyer"), instead
            # of a generic "aggregator" that hides which edge actually pays.
            strategy="+".join(contributors) if contributors else "aggregator",
            symbol=symbol,
            timeframe=signals[0].timeframe,
            side=side,
            signal_type=SignalType.ENTRY,
            strength=agg_strength,
            price=ref_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            reason=f"confluence:{len(contributors)}",
            meta={
                "contributors": contributors,
                "consensus": len(contributors),
                "buy_strength": round(buy_strength, 4),
                "sell_strength": round(sell_strength, 4),
            },
            created_at=utcnow(),
        )
        self.log.info(
            "confluence_signal",
            symbol=symbol,
            side=side.value,
            consensus=len(contributors),
            strength=round(agg_strength, 3),
            contributors=contributors,
        )
        # Once consolidated, clear the window so the same signals don't re-fire.
        self._buffer[symbol] = []
        return AggregationResult(
            consolidated,
            "confluence",
            contributors=contributors,
            buy_strength=buy_strength,
            sell_strength=sell_strength,
        )

    # ------------------------------------------------------------------ helpers

    def _weighted_strength(self, signals: list[Signal]) -> float:
        """Sum of per-strategy weighted strengths (one vote per strategy)."""
        by_strategy: dict[str, float] = {}
        for sig in signals:
            weight = self._weights.get(sig.strategy, 1.0)
            contribution = sig.strength * weight
            # Keep the strongest contribution per strategy.
            by_strategy[sig.strategy] = max(by_strategy.get(sig.strategy, 0.0), contribution)
        return sum(by_strategy.values())

    def _prune(self, symbol: str, now: float) -> None:
        """Drop signals older than the configured window."""
        window = self._cfg.window_seconds
        items = self._buffer.get(symbol)
        if not items:
            return
        self._buffer[symbol] = [i for i in items if now - i.arrived <= window]

    def clear(self, symbol: str | None = None) -> None:
        """Clear buffered signals (for one symbol or all)."""
        if symbol is None:
            self._buffer.clear()
        else:
            self._buffer.pop(symbol, None)


def _items(mapping: dict[tuple[str, Side], Signal]):
    """Yield ``(key, value)`` pairs (kept tiny for readability in comprehensions)."""
    return mapping.items()


def _tightest_stop(side: Side, stops: list[Decimal], price: Decimal) -> Decimal | None:
    """Choose the most conservative stop-loss among contributors."""
    if not stops:
        return None
    # For a long, the tightest stop is the highest (closest below price).
    return max(stops) if side is Side.BUY else min(stops)


def _furthest_tp(side: Side, tps: list[Decimal], price: Decimal) -> Decimal | None:
    """Choose the most ambitious take-profit among contributors."""
    if not tps:
        return None
    return max(tps) if side is Side.BUY else min(tps)


__all__ = ["AggregationResult", "SignalAggregator"]
