"""Volume indicators: VWAP, OBV, MFI, Accumulation/Distribution, Chaikin Money
Flow and a volume SMA.

Same conventions as the other indicator modules: array-like inputs, ``float64``
NaN-padded (or zero-seeded, where natural) outputs, pure functions.
"""

from __future__ import annotations

import numpy as np

from quantbot.indicators.trend import ArrayLike, FloatArray, _as_array, _require, sma


def _ohlcv(
    high: ArrayLike, low: ArrayLike, close: ArrayLike, volume: ArrayLike
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray]:
    """Coerce and length-check the four OHLCV arrays."""
    h = _as_array(high, name="high")
    low_arr = _as_array(low, name="low")
    c = _as_array(close, name="close")
    vol = _as_array(volume, name="volume")
    if not (h.size == low_arr.size == c.size == vol.size):
        raise ValueError("high, low, close and volume must have equal length")
    return h, low_arr, c, vol


def vwap(
    high: ArrayLike,
    low: ArrayLike,
    close: ArrayLike,
    volume: ArrayLike,
    period: int | None = None,
) -> FloatArray:
    """Volume-Weighted Average Price.

    Args:
        period: If ``None`` the VWAP is *cumulative* (session VWAP); otherwise a
            rolling VWAP over the last *period* bars is computed.
    """
    h, low_arr, c, vol = _ohlcv(high, low, close, volume)
    typical = (h + low_arr + c) / 3.0
    pv = typical * vol
    out = np.full(c.size, np.nan, dtype=np.float64)

    if period is None:
        cum_pv = np.cumsum(pv)
        cum_vol = np.cumsum(vol)
        with np.errstate(divide="ignore", invalid="ignore"):
            out = np.where(cum_vol > 0, cum_pv / cum_vol, np.nan)
        return out

    _require(c.size, period, name="VWAP")
    cum_pv = np.cumsum(np.insert(pv, 0, 0.0))
    cum_vol = np.cumsum(np.insert(vol, 0, 0.0))
    window_pv = cum_pv[period:] - cum_pv[:-period]
    window_vol = cum_vol[period:] - cum_vol[:-period]
    with np.errstate(divide="ignore", invalid="ignore"):
        out[period - 1 :] = np.where(window_vol > 0, window_pv / window_vol, np.nan)
    return out


def obv(close: ArrayLike, volume: ArrayLike) -> FloatArray:
    """On-Balance Volume (cumulative signed volume)."""
    c = _as_array(close, name="close")
    vol = _as_array(volume, name="volume")
    if c.size != vol.size:
        raise ValueError("close and volume must have equal length")
    out = np.zeros(c.size, dtype=np.float64)
    direction = np.sign(np.diff(c))
    out[1:] = np.cumsum(direction * vol[1:])
    return out


def money_flow_index(
    high: ArrayLike,
    low: ArrayLike,
    close: ArrayLike,
    volume: ArrayLike,
    period: int = 14,
) -> FloatArray:
    """Money Flow Index (volume-weighted RSI), range 0-100."""
    h, low_arr, c, vol = _ohlcv(high, low, close, volume)
    _require(c.size, period + 1, name="MFI")
    typical = (h + low_arr + c) / 3.0
    raw_flow = typical * vol
    tp_diff = np.diff(typical)
    positive = np.where(tp_diff > 0, raw_flow[1:], 0.0)
    negative = np.where(tp_diff < 0, raw_flow[1:], 0.0)

    out = np.full(c.size, np.nan, dtype=np.float64)
    for i in range(period, c.size):
        pos = positive[i - period : i].sum()
        neg = negative[i - period : i].sum()
        if neg == 0:
            out[i] = 100.0 if pos > 0 else 50.0
        else:
            ratio = pos / neg
            out[i] = 100.0 - (100.0 / (1.0 + ratio))
    return out


def accumulation_distribution(
    high: ArrayLike, low: ArrayLike, close: ArrayLike, volume: ArrayLike
) -> FloatArray:
    """Accumulation/Distribution line (cumulative money-flow volume)."""
    h, low_arr, c, vol = _ohlcv(high, low, close, volume)
    span = h - low_arr
    with np.errstate(divide="ignore", invalid="ignore"):
        clv = np.where(span > 0, ((c - low_arr) - (h - c)) / span, 0.0)
    return np.cumsum(clv * vol).astype(np.float64)


def chaikin_money_flow(
    high: ArrayLike,
    low: ArrayLike,
    close: ArrayLike,
    volume: ArrayLike,
    period: int = 20,
) -> FloatArray:
    """Chaikin Money Flow over *period*, range roughly -1..1."""
    h, low_arr, c, vol = _ohlcv(high, low, close, volume)
    _require(c.size, period, name="CMF")
    span = h - low_arr
    with np.errstate(divide="ignore", invalid="ignore"):
        mfv = np.where(span > 0, ((c - low_arr) - (h - c)) / span, 0.0) * vol
    out = np.full(c.size, np.nan, dtype=np.float64)
    for i in range(period - 1, c.size):
        vol_sum = vol[i - period + 1 : i + 1].sum()
        out[i] = 0.0 if vol_sum == 0 else mfv[i - period + 1 : i + 1].sum() / vol_sum
    return out


def volume_sma(volume: ArrayLike, period: int = 20) -> FloatArray:
    """Simple moving average of volume (for relative-volume comparisons)."""
    return sma(volume, period)


def relative_volume(volume: ArrayLike, period: int = 20) -> FloatArray:
    """Current volume divided by its *period* SMA (1.0 == average)."""
    vol = _as_array(volume, name="volume")
    avg = sma(vol, period)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(avg > 0, vol / avg, np.nan)


__all__ = [
    "accumulation_distribution",
    "chaikin_money_flow",
    "money_flow_index",
    "obv",
    "relative_volume",
    "volume_sma",
    "vwap",
]
