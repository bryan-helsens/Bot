"""Volatility indicators: True Range / ATR, Bollinger Bands, Keltner Channels,
rolling standard deviation and annualised historical volatility.

Same conventions as the other indicator modules: array-like inputs, ``float64``
NaN-padded outputs, pure functions.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from quantbot.core.constants import TRADING_DAYS_PER_YEAR
from quantbot.indicators.trend import ArrayLike, FloatArray, _as_array, _require, ema


def true_range(high: ArrayLike, low: ArrayLike, close: ArrayLike) -> FloatArray:
    """True Range: ``max(h-l, |h-prev_close|, |l-prev_close|)``.

    The first element uses ``high - low`` (no previous close available).
    """
    h = _as_array(high, name="high")
    low_arr = _as_array(low, name="low")
    c = _as_array(close, name="close")
    if not (h.size == low_arr.size == c.size):
        raise ValueError("high, low and close must have equal length")
    prev_close = np.empty(c.size, dtype=np.float64)
    prev_close[0] = c[0]
    prev_close[1:] = c[:-1]
    tr = np.maximum.reduce(
        [h - low_arr, np.abs(h - prev_close), np.abs(low_arr - prev_close)]
    )
    tr[0] = h[0] - low_arr[0]
    return tr


def atr(high: ArrayLike, low: ArrayLike, close: ArrayLike, period: int = 14) -> FloatArray:
    """Average True Range using Wilder's smoothing."""
    h = _as_array(high, name="high")
    _require(h.size, period + 1, name="ATR")
    tr = true_range(high, low, close)
    out = np.full(tr.size, np.nan, dtype=np.float64)
    seed = tr[1 : period + 1].mean()
    out[period] = seed
    prev = seed
    for i in range(period + 1, tr.size):
        prev = (prev * (period - 1) + tr[i]) / period
        out[i] = prev
    return out


def std_dev(values: ArrayLike, period: int = 20, *, ddof: int = 0) -> FloatArray:
    """Rolling standard deviation over *period* (population ddof=0 by default)."""
    arr = _as_array(values)
    _require(arr.size, period, name="StdDev")
    out = np.full(arr.size, np.nan, dtype=np.float64)
    for i in range(period - 1, arr.size):
        out[i] = arr[i - period + 1 : i + 1].std(ddof=ddof)
    return out


@dataclass(slots=True)
class BollingerResult:
    """Bollinger Bands: upper/middle/lower plus %B and bandwidth (NaN-padded)."""

    upper: FloatArray
    middle: FloatArray
    lower: FloatArray
    percent_b: FloatArray
    bandwidth: FloatArray


def bollinger_bands(
    values: ArrayLike, period: int = 20, num_std: float = 2.0
) -> BollingerResult:
    """Bollinger Bands around an SMA with ``num_std`` standard deviations.

    Also returns ``%B`` (position of price within the bands) and ``bandwidth``
    (band width normalised by the middle band) which are useful for squeeze and
    mean-reversion logic.
    """
    arr = _as_array(values)
    _require(arr.size, period, name="Bollinger")
    middle = np.full(arr.size, np.nan, dtype=np.float64)
    sigma = np.full(arr.size, np.nan, dtype=np.float64)
    for i in range(period - 1, arr.size):
        window = arr[i - period + 1 : i + 1]
        middle[i] = window.mean()
        sigma[i] = window.std(ddof=0)
    upper = middle + num_std * sigma
    lower = middle - num_std * sigma
    band_span = upper - lower
    with np.errstate(divide="ignore", invalid="ignore"):
        percent_b = np.where(band_span > 0, (arr - lower) / band_span, np.nan)
        bandwidth = np.where(middle != 0, band_span / middle, np.nan)
    return BollingerResult(
        upper=upper, middle=middle, lower=lower, percent_b=percent_b, bandwidth=bandwidth
    )


@dataclass(slots=True)
class KeltnerResult:
    """Keltner Channels: upper/middle/lower (NaN-padded)."""

    upper: FloatArray
    middle: FloatArray
    lower: FloatArray


def keltner_channels(
    high: ArrayLike,
    low: ArrayLike,
    close: ArrayLike,
    period: int = 20,
    atr_period: int = 10,
    multiplier: float = 2.0,
) -> KeltnerResult:
    """Keltner Channels: EMA mid-line +/- ``multiplier * ATR``."""
    c = _as_array(close, name="close")
    middle = ema(c, period)
    atr_vals = atr(high, low, close, atr_period)
    upper = middle + multiplier * atr_vals
    lower = middle - multiplier * atr_vals
    return KeltnerResult(upper=upper, middle=middle, lower=lower)


def historical_volatility(
    values: ArrayLike,
    period: int = 20,
    *,
    annualize: bool = True,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> FloatArray:
    """Annualised historical volatility from log returns over a rolling window."""
    arr = _as_array(values)
    _require(arr.size, period + 1, name="HistVol")
    with np.errstate(divide="ignore", invalid="ignore"):
        log_returns = np.log(arr[1:] / arr[:-1])
    out = np.full(arr.size, np.nan, dtype=np.float64)
    scale = np.sqrt(periods_per_year) if annualize else 1.0
    for i in range(period, arr.size):
        window = log_returns[i - period : i]
        out[i] = window.std(ddof=0) * scale
    return out


def bollinger_squeeze(
    bb: BollingerResult, kc: KeltnerResult
) -> np.ndarray:
    """Boolean array: True where Bollinger Bands sit inside Keltner Channels.

    A classic low-volatility "squeeze" precedes expansion/breakouts.
    """
    with np.errstate(invalid="ignore"):
        inside = (bb.upper < kc.upper) & (bb.lower > kc.lower)
    return np.where(np.isnan(bb.upper) | np.isnan(kc.upper), False, inside)


__all__ = [
    "BollingerResult",
    "KeltnerResult",
    "atr",
    "bollinger_bands",
    "bollinger_squeeze",
    "historical_volatility",
    "keltner_channels",
    "std_dev",
    "true_range",
]
