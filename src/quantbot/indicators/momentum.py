"""Momentum / oscillator indicators: RSI, Stochastic, ROC, Williams %R, CCI.

Same conventions as :mod:`quantbot.indicators.trend`: array-like inputs,
``float64`` NaN-padded outputs, pure functions.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from quantbot.indicators.trend import ArrayLike, FloatArray, _as_array, _require, sma


def rsi(values: ArrayLike, period: int = 14) -> FloatArray:
    """Relative Strength Index (Wilder's smoothing), range 0-100.

    The first valid value is at index *period*; the warm-up is NaN. A flat or
    rising-only series yields 100, a falling-only series yields 0.
    """
    arr = _as_array(values)
    _require(arr.size, period + 1, name="RSI")
    deltas = np.diff(arr)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    out = np.full(arr.size, np.nan, dtype=np.float64)
    avg_gain = gains[:period].mean()
    avg_loss = losses[:period].mean()
    out[period] = _rsi_value(avg_gain, avg_loss)
    for i in range(period + 1, arr.size):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        out[i] = _rsi_value(avg_gain, avg_loss)
    return out


def _rsi_value(avg_gain: float, avg_loss: float) -> float:
    """RSI from average gain/loss, handling the zero-loss edge case."""
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


@dataclass(slots=True)
class StochasticResult:
    """Stochastic oscillator %K and %D lines (0-100, NaN-padded)."""

    k: FloatArray
    d: FloatArray


def stochastic(
    high: ArrayLike,
    low: ArrayLike,
    close: ArrayLike,
    k_period: int = 14,
    d_period: int = 3,
    smooth: int = 3,
) -> StochasticResult:
    """Stochastic oscillator (slow %K smoothed, %D = SMA of %K)."""
    h = _as_array(high, name="high")
    low_arr = _as_array(low, name="low")
    c = _as_array(close, name="close")
    if not (h.size == low_arr.size == c.size):
        raise ValueError("high, low and close must have equal length")
    _require(h.size, k_period, name="Stochastic")

    raw_k = np.full(c.size, np.nan, dtype=np.float64)
    for i in range(k_period - 1, c.size):
        window_high = h[i - k_period + 1 : i + 1].max()
        window_low = low_arr[i - k_period + 1 : i + 1].min()
        span = window_high - window_low
        raw_k[i] = 50.0 if span == 0 else 100.0 * (c[i] - window_low) / span

    k = _smooth_valid(raw_k, smooth) if smooth > 1 else raw_k
    d = _smooth_valid(k, d_period)
    return StochasticResult(k=k, d=d)


def _smooth_valid(values: FloatArray, period: int) -> FloatArray:
    """Apply an SMA over the non-NaN region, re-aligned to the original length."""
    mask = ~np.isnan(values)
    valid = values[mask]
    if valid.size < period:
        return np.full(values.size, np.nan, dtype=np.float64)
    smoothed = sma(valid, period)
    out = np.full(values.size, np.nan, dtype=np.float64)
    out[np.where(mask)[0]] = smoothed
    return out


def roc(values: ArrayLike, period: int = 10) -> FloatArray:
    """Rate of Change as a percentage: ``100 * (p[t] - p[t-n]) / p[t-n]``."""
    arr = _as_array(values)
    _require(arr.size, period + 1, name="ROC")
    out = np.full(arr.size, np.nan, dtype=np.float64)
    past = arr[:-period]
    with np.errstate(divide="ignore", invalid="ignore"):
        out[period:] = np.where(past != 0, 100.0 * (arr[period:] - past) / past, np.nan)
    return out


def momentum(values: ArrayLike, period: int = 10) -> FloatArray:
    """Raw momentum: ``p[t] - p[t-n]``."""
    arr = _as_array(values)
    _require(arr.size, period + 1, name="Momentum")
    out = np.full(arr.size, np.nan, dtype=np.float64)
    out[period:] = arr[period:] - arr[:-period]
    return out


def williams_r(
    high: ArrayLike, low: ArrayLike, close: ArrayLike, period: int = 14
) -> FloatArray:
    """Williams %R oscillator, range -100 (low) to 0 (high)."""
    h = _as_array(high, name="high")
    low_arr = _as_array(low, name="low")
    c = _as_array(close, name="close")
    if not (h.size == low_arr.size == c.size):
        raise ValueError("high, low and close must have equal length")
    _require(h.size, period, name="Williams %R")
    out = np.full(c.size, np.nan, dtype=np.float64)
    for i in range(period - 1, c.size):
        hh = h[i - period + 1 : i + 1].max()
        ll = low_arr[i - period + 1 : i + 1].min()
        span = hh - ll
        out[i] = -50.0 if span == 0 else -100.0 * (hh - c[i]) / span
    return out


def cci(
    high: ArrayLike, low: ArrayLike, close: ArrayLike, period: int = 20
) -> FloatArray:
    """Commodity Channel Index using the standard 0.015 scaling constant."""
    h = _as_array(high, name="high")
    low_arr = _as_array(low, name="low")
    c = _as_array(close, name="close")
    if not (h.size == low_arr.size == c.size):
        raise ValueError("high, low and close must have equal length")
    _require(h.size, period, name="CCI")
    typical = (h + low_arr + c) / 3.0
    out = np.full(c.size, np.nan, dtype=np.float64)
    for i in range(period - 1, c.size):
        window = typical[i - period + 1 : i + 1]
        mean = window.mean()
        mean_dev = np.abs(window - mean).mean()
        out[i] = 0.0 if mean_dev == 0 else (typical[i] - mean) / (0.015 * mean_dev)
    return out


__all__ = [
    "StochasticResult",
    "cci",
    "momentum",
    "roc",
    "rsi",
    "stochastic",
    "williams_r",
]
