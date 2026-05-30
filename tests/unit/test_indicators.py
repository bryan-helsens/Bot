"""Unit tests for technical indicators."""

from __future__ import annotations

import numpy as np
import pytest

from quantbot.core.exceptions import InsufficientDataError
from quantbot.indicators import levels, momentum, trend, volatility, volume

pytestmark = pytest.mark.unit


def test_sma_known_values() -> None:
    x = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    s = trend.sma(x, 3)
    assert np.isnan(s[1])
    assert s[2] == pytest.approx(2.0)
    assert s[9] == pytest.approx(9.0)


def test_ema_constant_series() -> None:
    e = trend.ema([5.0] * 20, 10)
    assert e[-1] == pytest.approx(5.0)


def test_macd_shapes_and_histogram() -> None:
    prices = np.cumsum(np.random.RandomState(0).randn(200)) + 100
    result = trend.macd(prices)
    assert result.macd.shape == result.signal.shape == result.histogram.shape == (200,)
    mask = ~np.isnan(result.signal)
    assert np.allclose(result.histogram[mask], (result.macd - result.signal)[mask])


def test_adx_trend_direction() -> None:
    up = np.arange(1, 101, dtype=float)
    res = trend.adx(up + 0.5, up - 0.5, up, 14)
    valid = ~np.isnan(res.plus_di)
    assert np.nanmean(res.plus_di[valid]) > np.nanmean(res.minus_di[valid])


def test_rsi_bounds_and_extremes() -> None:
    assert trend.sma is not None
    rising = list(range(1, 30))
    assert momentum.rsi(rising, 14)[-1] == pytest.approx(100.0)
    falling = list(range(30, 1, -1))
    assert momentum.rsi(falling, 14)[-1] == pytest.approx(0.0)


def test_atr_positive() -> None:
    prices = np.cumsum(np.random.RandomState(2).randn(100)) + 100
    a = volatility.atr(prices + 1, prices - 1, prices, 14)
    valid = ~np.isnan(a)
    assert (a[valid] > 0).all()


def test_bollinger_band_ordering() -> None:
    prices = np.cumsum(np.random.RandomState(3).randn(100)) + 100
    bb = volatility.bollinger_bands(prices, 20, 2.0)
    i = 50
    assert bb.upper[i] > bb.middle[i] > bb.lower[i]


def test_vwap_cumulative() -> None:
    h, low_, c, v = [10, 11, 12], [8, 9, 10], [9, 10, 11], [100, 100, 100]
    w = volume.vwap(h, low_, c, v)
    tp = [(10 + 8 + 9) / 3, (11 + 9 + 10) / 3, (12 + 10 + 11) / 3]
    assert w[0] == pytest.approx(tp[0])
    assert w[2] == pytest.approx(np.mean(tp))


def test_pivot_points_and_support_resistance() -> None:
    pp = levels.pivot_points(110, 90, 100)
    assert pp.pivot == pytest.approx(100.0)
    highs, lows = [], []
    for _ in range(10):
        highs += [98, 99, 100, 99, 98]
        lows += [92, 91, 90, 91, 92]
    sr = levels.support_resistance(highs, lows, left=2, right=2, tolerance=0.01, min_touches=2)
    assert sr.resistance and abs(sr.resistance[0].price - 100) < 1.0


def test_insufficient_data_raises() -> None:
    with pytest.raises(InsufficientDataError):
        trend.sma([1, 2], 5)
