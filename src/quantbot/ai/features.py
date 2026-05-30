"""Feature engineering for the ML module.

Transforms raw OHLCV into a numeric feature matrix combining returns, technical
indicators, volatility and volume statistics. Also builds supervised-learning
labels (the sign of the forward return over a horizon). Pure numpy/pandas — no
ML dependency — so it is fast and fully unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from quantbot.indicators.momentum import rsi, stochastic
from quantbot.indicators.trend import adx, ema, macd
from quantbot.indicators.volatility import atr, bollinger_bands
from quantbot.indicators.volume import relative_volume

FloatArray = npt.NDArray[np.float64]


@dataclass(slots=True)
class FeatureMatrix:
    """A feature matrix with named columns and aligned labels."""

    features: FloatArray  # shape (n_samples, n_features)
    labels: FloatArray | None  # shape (n_samples,)
    feature_names: list[str]
    valid_from: int  # first row index that is fully warmed up

    def trimmed(self) -> tuple[FloatArray, FloatArray | None]:
        """Return features/labels with the warm-up rows removed and finite-only."""
        feats = self.features[self.valid_from :]
        labels = self.labels[self.valid_from :] if self.labels is not None else None
        mask = np.all(np.isfinite(feats), axis=1)
        if labels is not None:
            mask &= np.isfinite(labels)
        return feats[mask], (labels[mask] if labels is not None else None)


class FeatureEngineer:
    """Build feature matrices and labels from OHLCV arrays."""

    def __init__(
        self,
        *,
        horizon: int = 5,
        rsi_period: int = 14,
        ema_periods: tuple[int, ...] = (10, 20, 50),
        label_threshold: float = 0.0,
    ) -> None:
        self._horizon = horizon
        self._rsi_period = rsi_period
        self._ema_periods = ema_periods
        self._label_threshold = label_threshold

    def build(
        self,
        opens: FloatArray,
        highs: FloatArray,
        lows: FloatArray,
        closes: FloatArray,
        volumes: FloatArray,
        *,
        with_labels: bool = True,
    ) -> FeatureMatrix:
        """Construct the feature matrix (and optionally labels) from OHLCV."""
        closes = np.asarray(closes, dtype=np.float64)
        n = closes.size
        cols: dict[str, FloatArray] = {}

        # Returns and lagged returns.
        ret = np.zeros(n)
        ret[1:] = np.diff(closes) / closes[:-1]
        cols["return_1"] = ret
        for lag in (2, 3, 5, 10):
            lagged = np.zeros(n)
            lagged[lag:] = (closes[lag:] - closes[:-lag]) / closes[:-lag]
            cols[f"return_{lag}"] = lagged

        # Trend / momentum indicators.
        cols[f"rsi_{self._rsi_period}"] = rsi(closes, self._rsi_period)
        for period in self._ema_periods:
            ema_vals = ema(closes, period)
            cols[f"ema_dist_{period}"] = (closes - ema_vals) / np.where(ema_vals != 0, ema_vals, np.nan)
        macd_res = macd(closes)
        cols["macd_hist"] = macd_res.histogram
        adx_res = adx(highs, lows, closes)
        cols["adx"] = adx_res.adx
        cols["di_diff"] = adx_res.plus_di - adx_res.minus_di
        stoch = stochastic(highs, lows, closes)
        cols["stoch_k"] = stoch.k

        # Volatility.
        atr_vals = atr(highs, lows, closes)
        cols["atr_pct"] = atr_vals / np.where(closes != 0, closes, np.nan)
        bb = bollinger_bands(closes)
        cols["bb_pct_b"] = bb.percent_b
        cols["bb_bandwidth"] = bb.bandwidth

        # Volume.
        cols["rel_volume"] = relative_volume(volumes, 20)
        cols["hl_range"] = (highs - lows) / np.where(closes != 0, closes, np.nan)

        feature_names = list(cols)
        feature_matrix = np.column_stack([cols[name] for name in feature_names])

        labels: FloatArray | None = None
        if with_labels:
            labels = self._make_labels(closes)

        valid_from = self._warmup_rows()
        return FeatureMatrix(
            features=feature_matrix,
            labels=labels,
            feature_names=feature_names,
            valid_from=valid_from,
        )

    def _make_labels(self, closes: FloatArray) -> FloatArray:
        """Label = 1 if forward return over horizon exceeds threshold, else 0."""
        n = closes.size
        labels = np.full(n, np.nan)
        future = np.full(n, np.nan)
        future[: n - self._horizon] = closes[self._horizon :]
        with np.errstate(invalid="ignore"):
            fwd_ret = (future - closes) / closes
        labels = np.where(fwd_ret > self._label_threshold, 1.0, 0.0)
        labels[n - self._horizon :] = np.nan  # no future data for the tail
        return labels

    def _warmup_rows(self) -> int:
        """Rows to discard so all indicators are warmed up."""
        return max(max(self._ema_periods) + 5, 50)

    @property
    def horizon(self) -> int:
        return self._horizon


__all__ = ["FeatureEngineer", "FeatureMatrix"]
