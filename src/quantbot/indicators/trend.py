"""Trend indicators: SMA, EMA, WMA, DEMA, MACD, Ichimoku and ADX/DI.

Conventions:
    * Inputs are array-like (list / numpy array / pandas Series) of prices.
    * Outputs are ``float64`` numpy arrays aligned to the input length, with the
      warm-up region filled with ``NaN``.
    * Functions never mutate their inputs.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from quantbot.core.exceptions import InsufficientDataError

#: Public alias for the array-like inputs accepted by indicators.
ArrayLike = Sequence[float] | npt.NDArray[np.float64]
FloatArray = npt.NDArray[np.float64]


def _as_array(values: ArrayLike, *, name: str = "values") -> FloatArray:
    """Coerce *values* to a 1-D float64 numpy array."""
    arr = np.asarray(values, dtype=np.float64)
    if arr.ndim != 1:
        raise ValueError(f"{name} must be 1-dimensional, got shape {arr.shape}")
    return arr


def _require(length: int, period: int, *, name: str) -> None:
    """Raise if there are fewer than *period* observations."""
    if period <= 0:
        raise ValueError(f"{name} period must be positive, got {period}")
    if length < period:
        raise InsufficientDataError(
            f"{name} needs at least {period} values, got {length}",
            context={"required": period, "available": length},
        )


# ---------------------------------------------------------------------------
# Moving averages
# ---------------------------------------------------------------------------


def sma(values: ArrayLike, period: int) -> FloatArray:
    """Simple Moving Average."""
    arr = _as_array(values)
    _require(arr.size, period, name="SMA")
    out = np.full(arr.size, np.nan, dtype=np.float64)
    cumsum = np.cumsum(np.insert(arr, 0, 0.0))
    out[period - 1 :] = (cumsum[period:] - cumsum[:-period]) / period
    return out


def ema(values: ArrayLike, period: int) -> FloatArray:
    """Exponential Moving Average (Wilder-style seeding with an SMA).

    The first valid value (index ``period-1``) is seeded with the SMA of the
    first *period* samples; subsequent values use ``alpha = 2/(period+1)``.
    """
    arr = _as_array(values)
    _require(arr.size, period, name="EMA")
    alpha = 2.0 / (period + 1.0)
    out = np.full(arr.size, np.nan, dtype=np.float64)
    seed = arr[:period].mean()
    out[period - 1] = seed
    prev = seed
    for i in range(period, arr.size):
        prev = alpha * arr[i] + (1.0 - alpha) * prev
        out[i] = prev
    return out


def wma(values: ArrayLike, period: int) -> FloatArray:
    """Weighted Moving Average (linearly increasing weights)."""
    arr = _as_array(values)
    _require(arr.size, period, name="WMA")
    weights = np.arange(1, period + 1, dtype=np.float64)
    denom = weights.sum()
    out = np.full(arr.size, np.nan, dtype=np.float64)
    for i in range(period - 1, arr.size):
        window = arr[i - period + 1 : i + 1]
        out[i] = np.dot(window, weights) / denom
    return out


def dema(values: ArrayLike, period: int) -> FloatArray:
    """Double Exponential Moving Average: ``2*EMA - EMA(EMA)``."""
    arr = _as_array(values)
    _require(arr.size, period, name="DEMA")
    e1 = ema(arr, period)
    # EMA of EMA computed only over the valid region.
    valid = e1[~np.isnan(e1)]
    e2_valid = ema(valid, period)
    out = np.full(arr.size, np.nan, dtype=np.float64)
    start = arr.size - valid.size
    out[start:] = 2.0 * e1[start:] - _align(e2_valid, valid.size)
    return out


def _align(values: FloatArray, length: int) -> FloatArray:
    """Right-align *values* into a length-*length* array padded with NaN."""
    out = np.full(length, np.nan, dtype=np.float64)
    out[length - values.size :] = values
    return out


def hma(values: ArrayLike, period: int) -> FloatArray:
    """Hull Moving Average: ``WMA(2*WMA(n/2) - WMA(n), sqrt(n))``."""
    arr = _as_array(values)
    _require(arr.size, period, name="HMA")
    half = max(int(period / 2), 1)
    sqrt_p = max(int(period**0.5), 1)
    wma_half = wma(arr, half)
    wma_full = wma(arr, period)
    raw = 2.0 * wma_half - wma_full
    valid = raw[~np.isnan(raw)]
    smoothed = wma(valid, sqrt_p)
    return _align(smoothed, arr.size)


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MACDResult:
    """MACD line, signal line and histogram (all NaN-padded arrays)."""

    macd: FloatArray
    signal: FloatArray
    histogram: FloatArray


def macd(
    values: ArrayLike,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> MACDResult:
    """Moving Average Convergence Divergence.

    Args:
        values: Price series.
        fast_period: Fast EMA period.
        slow_period: Slow EMA period (must exceed *fast_period*).
        signal_period: EMA period of the MACD line.
    """
    if fast_period >= slow_period:
        raise ValueError("fast_period must be < slow_period")
    arr = _as_array(values)
    _require(arr.size, slow_period + signal_period, name="MACD")
    fast = ema(arr, fast_period)
    slow = ema(arr, slow_period)
    macd_line = fast - slow
    valid = macd_line[~np.isnan(macd_line)]
    signal_valid = ema(valid, signal_period)
    signal_line = _align(signal_valid, arr.size)
    histogram = macd_line - signal_line
    return MACDResult(macd=macd_line, signal=signal_line, histogram=histogram)


# ---------------------------------------------------------------------------
# Ichimoku Cloud
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class IchimokuResult:
    """The five Ichimoku lines (NaN-padded arrays).

    Note: ``senkou_span_a/b`` are returned *un-shifted* (computed values aligned
    to the bar they were derived from). Callers that plot the cloud forward by
    ``kijun_period`` can apply the shift; signal logic typically compares price
    to the current spans, so the un-shifted form is the practical default.
    """

    tenkan_sen: FloatArray
    kijun_sen: FloatArray
    senkou_span_a: FloatArray
    senkou_span_b: FloatArray
    chikou_span: FloatArray


def _midpoint(high: FloatArray, low: FloatArray, period: int) -> FloatArray:
    """Rolling ``(highest_high + lowest_low) / 2`` over *period*."""
    out = np.full(high.size, np.nan, dtype=np.float64)
    for i in range(period - 1, high.size):
        window_high = high[i - period + 1 : i + 1].max()
        window_low = low[i - period + 1 : i + 1].min()
        out[i] = (window_high + window_low) / 2.0
    return out


def ichimoku(
    high: ArrayLike,
    low: ArrayLike,
    close: ArrayLike,
    tenkan_period: int = 9,
    kijun_period: int = 26,
    senkou_b_period: int = 52,
) -> IchimokuResult:
    """Ichimoku Kinko Hyo cloud components."""
    h = _as_array(high, name="high")
    low_arr = _as_array(low, name="low")
    c = _as_array(close, name="close")
    if not (h.size == low_arr.size == c.size):
        raise ValueError("high, low and close must have equal length")
    _require(h.size, senkou_b_period, name="Ichimoku")

    tenkan = _midpoint(h, low_arr, tenkan_period)
    kijun = _midpoint(h, low_arr, kijun_period)
    senkou_a = (tenkan + kijun) / 2.0
    senkou_b = _midpoint(h, low_arr, senkou_b_period)
    # Chikou span: close shifted back by kijun_period (lagging line).
    chikou = np.full(c.size, np.nan, dtype=np.float64)
    if c.size > kijun_period:
        chikou[: c.size - kijun_period] = c[kijun_period:]
    return IchimokuResult(
        tenkan_sen=tenkan,
        kijun_sen=kijun,
        senkou_span_a=senkou_a,
        senkou_span_b=senkou_b,
        chikou_span=chikou,
    )


# ---------------------------------------------------------------------------
# ADX / Directional Movement
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ADXResult:
    """Average Directional Index with +DI/-DI lines."""

    adx: FloatArray
    plus_di: FloatArray
    minus_di: FloatArray


def _wilder_smooth(values: FloatArray, period: int) -> FloatArray:
    """Wilder's smoothing (RMA) of *values* over *period*."""
    out = np.full(values.size, np.nan, dtype=np.float64)
    if values.size < period:
        return out
    seed = values[:period].sum()
    out[period - 1] = seed
    prev = seed
    for i in range(period, values.size):
        prev = prev - (prev / period) + values[i]
        out[i] = prev
    return out


def adx(
    high: ArrayLike,
    low: ArrayLike,
    close: ArrayLike,
    period: int = 14,
) -> ADXResult:
    """Average Directional Index (ADX) and the +DI / -DI directional lines."""
    h = _as_array(high, name="high")
    low_arr = _as_array(low, name="low")
    c = _as_array(close, name="close")
    if not (h.size == low_arr.size == c.size):
        raise ValueError("high, low and close must have equal length")
    _require(h.size, 2 * period, name="ADX")

    n = h.size
    up_move = np.diff(h, prepend=h[0])
    down_move = -np.diff(low_arr, prepend=low_arr[0])
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    prev_close = np.empty(n, dtype=np.float64)
    prev_close[0] = c[0]
    prev_close[1:] = c[:-1]
    true_range = np.maximum.reduce(
        [h - low_arr, np.abs(h - prev_close), np.abs(low_arr - prev_close)]
    )

    tr_s = _wilder_smooth(true_range, period)
    plus_dm_s = _wilder_smooth(plus_dm, period)
    minus_dm_s = _wilder_smooth(minus_dm, period)

    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100.0 * np.where(tr_s > 0, plus_dm_s / tr_s, np.nan)
        minus_di = 100.0 * np.where(tr_s > 0, minus_dm_s / tr_s, np.nan)
        di_sum = plus_di + minus_di
        dx = 100.0 * np.where(di_sum > 0, np.abs(plus_di - minus_di) / di_sum, np.nan)

    # ADX is Wilder's smoothing of DX (averaged) -> use EMA-like RMA over period.
    adx_line = np.full(n, np.nan, dtype=np.float64)
    valid_idx = np.where(~np.isnan(dx))[0]
    if valid_idx.size >= period:
        first = valid_idx[0]
        seed_slice = dx[first : first + period]
        prev = float(np.nanmean(seed_slice))
        adx_line[first + period - 1] = prev
        for i in range(first + period, n):
            if np.isnan(dx[i]):
                continue
            prev = (prev * (period - 1) + dx[i]) / period
            adx_line[i] = prev
    return ADXResult(adx=adx_line, plus_di=plus_di, minus_di=minus_di)


__all__ = [
    "ADXResult",
    "ArrayLike",
    "FloatArray",
    "IchimokuResult",
    "MACDResult",
    "adx",
    "dema",
    "ema",
    "hma",
    "ichimoku",
    "macd",
    "sma",
    "wma",
]
