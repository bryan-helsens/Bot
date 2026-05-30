"""Price-level analysis: pivot points, swing highs/lows (fractals) and
clustered support/resistance levels.

Unlike the streaming indicators in the sibling modules, these helpers return
discrete *levels* (lists / dataclasses) rather than aligned arrays, because
support/resistance is inherently about a handful of significant prices rather
than a value-per-bar series.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from quantbot.indicators.trend import ArrayLike, FloatArray, _as_array, _require


# ---------------------------------------------------------------------------
# Classic floor-trader pivot points
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class PivotPoints:
    """Standard pivot point with three support and three resistance levels."""

    pivot: float
    r1: float
    r2: float
    r3: float
    s1: float
    s2: float
    s3: float

    def as_dict(self) -> dict[str, float]:
        """Return the levels as an ordered mapping (high to low)."""
        return {
            "r3": self.r3,
            "r2": self.r2,
            "r1": self.r1,
            "pivot": self.pivot,
            "s1": self.s1,
            "s2": self.s2,
            "s3": self.s3,
        }


def pivot_points(high: float, low: float, close: float) -> PivotPoints:
    """Classic (floor-trader) pivot points from the prior period's HLC."""
    pivot = (high + low + close) / 3.0
    r1 = 2.0 * pivot - low
    s1 = 2.0 * pivot - high
    rng = high - low
    return PivotPoints(
        pivot=pivot,
        r1=r1,
        r2=pivot + rng,
        r3=high + 2.0 * (pivot - low),
        s1=s1,
        s2=pivot - rng,
        s3=low - 2.0 * (high - pivot),
    )


def fibonacci_pivots(high: float, low: float, close: float) -> PivotPoints:
    """Fibonacci-based pivot points."""
    pivot = (high + low + close) / 3.0
    rng = high - low
    return PivotPoints(
        pivot=pivot,
        r1=pivot + 0.382 * rng,
        r2=pivot + 0.618 * rng,
        r3=pivot + 1.000 * rng,
        s1=pivot - 0.382 * rng,
        s2=pivot - 0.618 * rng,
        s3=pivot - 1.000 * rng,
    )


# ---------------------------------------------------------------------------
# Swing highs / lows (Williams fractals)
# ---------------------------------------------------------------------------


def swing_highs(high: ArrayLike, left: int = 2, right: int = 2) -> list[int]:
    """Indices of swing-high pivots (a bar higher than *left*/*right* neighbours)."""
    h = _as_array(high, name="high")
    out: list[int] = []
    for i in range(left, h.size - right):
        window = h[i - left : i + right + 1]
        if h[i] == window.max() and np.argmax(window) == left:
            out.append(i)
    return out


def swing_lows(low: ArrayLike, left: int = 2, right: int = 2) -> list[int]:
    """Indices of swing-low pivots (a bar lower than *left*/*right* neighbours)."""
    low_arr = _as_array(low, name="low")
    out: list[int] = []
    for i in range(left, low_arr.size - right):
        window = low_arr[i - left : i + right + 1]
        if low_arr[i] == window.min() and np.argmin(window) == left:
            out.append(i)
    return out


# ---------------------------------------------------------------------------
# Clustered support / resistance
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Level:
    """A clustered price level with a strength score (touch count)."""

    price: float
    touches: int
    is_support: bool
    members: list[float] = field(default_factory=list)


@dataclass(slots=True)
class SupportResistance:
    """Detected support and resistance levels, strongest first."""

    support: list[Level]
    resistance: list[Level]

    def nearest_support(self, price: float) -> Level | None:
        """Strongest support at or below *price*, if any."""
        below = [lvl for lvl in self.support if lvl.price <= price]
        return max(below, key=lambda level: level.price, default=None)

    def nearest_resistance(self, price: float) -> Level | None:
        """Strongest resistance at or above *price*, if any."""
        above = [lvl for lvl in self.resistance if lvl.price >= price]
        return min(above, key=lambda level: level.price, default=None)


def support_resistance(
    high: ArrayLike,
    low: ArrayLike,
    *,
    left: int = 2,
    right: int = 2,
    tolerance: float = 0.005,
    min_touches: int = 2,
) -> SupportResistance:
    """Detect support/resistance by clustering swing pivots.

    Args:
        high: High prices.
        low: Low prices.
        left/right: Fractal window for swing detection.
        tolerance: Relative price distance (fraction) within which pivots are
            merged into the same level (e.g. ``0.005`` == 0.5%).
        min_touches: Minimum pivots required for a cluster to count as a level.

    Returns:
        A :class:`SupportResistance` with levels ranked by touch count.
    """
    h = _as_array(high, name="high")
    low_arr = _as_array(low, name="low")
    if h.size != low_arr.size:
        raise ValueError("high and low must have equal length")
    _require(h.size, left + right + 1, name="SupportResistance")

    res_prices = [float(h[i]) for i in swing_highs(h, left, right)]
    sup_prices = [float(low_arr[i]) for i in swing_lows(low_arr, left, right)]
    resistance = _cluster(res_prices, tolerance, min_touches, is_support=False)
    support = _cluster(sup_prices, tolerance, min_touches, is_support=True)
    return SupportResistance(support=support, resistance=resistance)


def _cluster(
    prices: list[float], tolerance: float, min_touches: int, *, is_support: bool
) -> list[Level]:
    """Greedily cluster nearby *prices* into levels within *tolerance*."""
    if not prices:
        return []
    ordered = sorted(prices)
    clusters: list[list[float]] = [[ordered[0]]]
    for price in ordered[1:]:
        anchor = clusters[-1][0]
        if anchor > 0 and abs(price - anchor) / anchor <= tolerance:
            clusters[-1].append(price)
        else:
            clusters.append([price])

    levels = [
        Level(
            price=float(np.mean(members)),
            touches=len(members),
            is_support=is_support,
            members=members,
        )
        for members in clusters
        if len(members) >= min_touches
    ]
    levels.sort(key=lambda level: level.touches, reverse=True)
    return levels


def fibonacci_retracements(swing_high: float, swing_low: float) -> dict[str, float]:
    """Fibonacci retracement levels between a swing high and swing low."""
    diff = swing_high - swing_low
    return {
        "0.0": swing_high,
        "0.236": swing_high - 0.236 * diff,
        "0.382": swing_high - 0.382 * diff,
        "0.5": swing_high - 0.5 * diff,
        "0.618": swing_high - 0.618 * diff,
        "0.786": swing_high - 0.786 * diff,
        "1.0": swing_low,
    }


def recent_high_low(high: ArrayLike, low: ArrayLike, period: int = 20) -> tuple[float, float]:
    """Highest high and lowest low over the last *period* bars."""
    h: FloatArray = _as_array(high, name="high")
    low_arr: FloatArray = _as_array(low, name="low")
    _require(h.size, period, name="recent_high_low")
    return float(h[-period:].max()), float(low_arr[-period:].min())


__all__ = [
    "Level",
    "PivotPoints",
    "SupportResistance",
    "fibonacci_pivots",
    "fibonacci_retracements",
    "pivot_points",
    "recent_high_low",
    "support_resistance",
    "swing_highs",
    "swing_lows",
]
