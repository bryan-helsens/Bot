"""Vectorised technical indicators.

All indicators operate on array-like inputs (lists, numpy arrays or pandas
Series) and return ``numpy.ndarray`` of ``float64`` with ``NaN`` padding for the
warm-up period, so they compose cleanly and stay fast. They are pure functions
with no I/O, making them trivial to unit-test and reuse in both the live engine
and the backtester.

Submodules:
    * :mod:`quantbot.indicators.trend` — EMA, SMA, WMA, MACD, Ichimoku, ADX.
    * :mod:`quantbot.indicators.momentum` — RSI, Stochastic, ROC, Williams %R.
    * :mod:`quantbot.indicators.volatility` — ATR, Bollinger, Keltner, std-dev.
    * :mod:`quantbot.indicators.volume` — VWAP, OBV, MFI.
    * :mod:`quantbot.indicators.levels` — support/resistance & pivot points.
"""

from __future__ import annotations
