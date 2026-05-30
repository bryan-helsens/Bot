"""Market-regime detection.

Classifies the current market into a :class:`~quantbot.core.constants.MarketRegime`
(trending up/down, ranging, high/low volatility) from indicator readings. A
robust, rule-based detector is the default (no ML dependency); an optional
KMeans-based detector is provided for unsupervised regime discovery when
scikit-learn is available.

The engine can use the regime to gate or weight strategies — e.g. only run
mean-reversion in ``RANGING`` and trend-following in ``TRENDING_*``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from quantbot.core.constants import MarketRegime
from quantbot.core.exceptions import DependencyError
from quantbot.indicators.trend import adx, ema
from quantbot.indicators.volatility import historical_volatility

FloatArray = npt.NDArray[np.float64]


@dataclass(slots=True)
class RegimeReading:
    """A regime classification with the metrics that produced it."""

    regime: MarketRegime
    adx: float
    trend_slope: float
    volatility: float
    confidence: float


class MarketRegimeDetector:
    """Rule-based market-regime detector."""

    def __init__(
        self,
        *,
        adx_period: int = 14,
        ema_period: int = 50,
        vol_period: int = 20,
        adx_trend_threshold: float = 25.0,
        high_vol_quantile: float = 0.8,
        low_vol_quantile: float = 0.2,
    ) -> None:
        self._adx_period = adx_period
        self._ema_period = ema_period
        self._vol_period = vol_period
        self._adx_threshold = adx_trend_threshold
        self._high_q = high_vol_quantile
        self._low_q = low_vol_quantile

    def detect(
        self, highs: FloatArray, lows: FloatArray, closes: FloatArray
    ) -> RegimeReading:
        """Classify the regime at the latest bar."""
        closes = np.asarray(closes, dtype=np.float64)
        if closes.size < max(self._adx_period * 2, self._ema_period, self._vol_period) + 2:
            return RegimeReading(MarketRegime.UNKNOWN, 0.0, 0.0, 0.0, 0.0)

        adx_res = adx(highs, lows, closes, self._adx_period)
        adx_val = float(adx_res.adx[-1]) if not np.isnan(adx_res.adx[-1]) else 0.0
        ema_vals = ema(closes, self._ema_period)
        slope = float((ema_vals[-1] - ema_vals[-5]) / ema_vals[-5]) if ema_vals[-5] else 0.0

        vol_series = historical_volatility(closes, self._vol_period)
        vol_valid = vol_series[~np.isnan(vol_series)]
        current_vol = float(vol_valid[-1]) if vol_valid.size else 0.0
        high_vol = float(np.quantile(vol_valid, self._high_q)) if vol_valid.size else 0.0
        low_vol = float(np.quantile(vol_valid, self._low_q)) if vol_valid.size else 0.0

        regime, confidence = self._classify(adx_val, slope, current_vol, high_vol, low_vol)
        return RegimeReading(
            regime=regime, adx=round(adx_val, 2), trend_slope=round(slope, 4),
            volatility=round(current_vol, 4), confidence=round(confidence, 3),
        )

    def _classify(
        self, adx_val: float, slope: float, vol: float, high_vol: float, low_vol: float
    ) -> tuple[MarketRegime, float]:
        # A strong trend dominates: describe it as trending regardless of where its
        # volatility sits. Volatility regimes are only meaningful in the absence of
        # a clear trend (choppy markets).
        if adx_val >= self._adx_threshold:
            conf = min(1.0, adx_val / 50.0)
            if slope > 0:
                return MarketRegime.TRENDING_UP, conf
            return MarketRegime.TRENDING_DOWN, conf
        # No clear trend → distinguish high/low-volatility chop from a calm range.
        if high_vol > 0 and vol >= high_vol:
            return MarketRegime.HIGH_VOLATILITY, min(1.0, 0.5 + (vol / high_vol - 1.0))
        if low_vol > 0 and vol <= low_vol:
            return MarketRegime.LOW_VOLATILITY, 0.6
        return MarketRegime.RANGING, min(1.0, 1.0 - adx_val / self._adx_threshold)


class ClusterRegimeDetector:
    """Unsupervised regime discovery via KMeans (requires scikit-learn)."""

    def __init__(self, *, n_regimes: int = 3, seed: int | None = None) -> None:
        self._n = n_regimes
        self._seed = seed
        self._model = None

    def fit(self, features: FloatArray) -> ClusterRegimeDetector:
        kmeans_cls = _import_kmeans()
        self._model = kmeans_cls(n_clusters=self._n, random_state=self._seed, n_init=10)
        self._model.fit(features)
        return self

    def predict(self, features: FloatArray) -> npt.NDArray[np.int_]:
        if self._model is None:
            raise DependencyError("ClusterRegimeDetector.fit() must be called first")
        return self._model.predict(features)


def _import_kmeans():
    try:
        from sklearn.cluster import KMeans  # type: ignore

        return KMeans
    except ImportError as exc:  # pragma: no cover - exercised when sklearn absent
        raise DependencyError(
            "ClusterRegimeDetector requires scikit-learn. Install with: pip install 'quantbot[ai]'"
        ) from exc


__all__ = ["ClusterRegimeDetector", "MarketRegimeDetector", "RegimeReading"]
