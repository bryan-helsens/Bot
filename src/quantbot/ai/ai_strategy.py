"""AI strategy adapter.

Wraps a fitted ML model and the :class:`FeatureEngineer` as a normal
:class:`~quantbot.strategies.base.BaseStrategy`, so AI predictions flow through
the *exact same* pipeline as rule-based strategies: the model produces a
probability, the adapter turns a sufficiently-confident prediction into a
:class:`Signal`, and that signal is aggregated and **validated by the risk
engine** before any order. The AI never bypasses risk control.

A regime detector can optionally gate signals (e.g. ignore predictions in
``HIGH_VOLATILITY`` regimes). The model is injected via :meth:`set_model` or
lazily loaded from ``params['model_path']``.
"""

from __future__ import annotations

from typing import Any, ClassVar

import numpy as np

from quantbot.ai.features import FeatureEngineer
from quantbot.ai.regime import MarketRegimeDetector
from quantbot.core.constants import MarketRegime, Side, SignalType
from quantbot.core.models import Signal
from quantbot.strategies.base import BaseStrategy, StrategyContext
from quantbot.strategies.registry import register_strategy


@register_strategy
class AIStrategy(BaseStrategy):
    """Model-driven strategy producing risk-validated signals."""

    name: ClassVar[str] = "AIStrategy"
    default_params: ClassVar[dict] = {
        "min_confidence": 0.6,   # probability distance from 0.5 required to act
        "horizon": 5,
        "model_path": "",
        "model_type": "",        # xgboost | random_forest | lightgbm | lstm
        "use_regime_filter": True,
        "blocked_regimes": ["high_volatility"],
    }

    @property
    def min_candles(self) -> int:  # type: ignore[override]
        return 80

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._engineer = FeatureEngineer(horizon=int(self.param("horizon")))
        self._regime = MarketRegimeDetector()
        self._model: Any | None = None

    # ------------------------------------------------------------------ model

    def set_model(self, model: Any) -> None:
        """Inject a fitted model exposing ``predict_proba(X) -> probabilities``."""
        self._model = model

    async def on_init(self) -> None:
        if self._model is None and self.param("model_path"):
            self._model = self._load_model()

    def _load_model(self) -> Any:
        model_type = str(self.param("model_type")).lower()
        path = str(self.param("model_path"))
        registry = {
            "xgboost": "quantbot.ai.models.xgboost_model:XGBoostModel",
            "random_forest": "quantbot.ai.models.random_forest:RandomForestModel",
            "lightgbm": "quantbot.ai.models.lightgbm_model:LightGBMModel",
            "lstm": "quantbot.ai.models.lstm_model:LSTMModel",
        }
        target = registry.get(model_type)
        if target is None:
            raise ValueError(f"Unknown model_type {model_type!r}")
        module_name, _, cls_name = target.partition(":")
        import importlib

        cls = getattr(importlib.import_module(module_name), cls_name)
        return cls.load(path)

    # ------------------------------------------------------------------ signal

    async def on_candle(self, ctx: StrategyContext) -> Signal | None:
        if self._model is None or not ctx.has(self.min_candles):
            return None

        if self.param("use_regime_filter") and self._regime_blocked(ctx):
            return None

        proba = self._latest_probability(ctx)
        if proba is None:
            return None

        min_conf = float(self.param("min_confidence"))
        confidence = abs(proba - 0.5) * 2.0  # 0..1
        if confidence < (min_conf * 2 - 1):  # map min_conf prob-threshold to confidence
            return None

        if proba > 0.5:
            return self.make_signal(
                ctx, Side.BUY, signal_type=SignalType.ENTRY, strength=min(1.0, confidence),
                reason="ai_bullish", probability=round(float(proba), 4),
            )
        return self.make_signal(
            ctx, Side.SELL, signal_type=SignalType.ENTRY, strength=min(1.0, confidence),
            reason="ai_bearish", probability=round(float(proba), 4),
        )

    def _latest_probability(self, ctx: StrategyContext) -> float | None:
        matrix = self._engineer.build(
            ctx.opens, ctx.highs, ctx.lows, ctx.closes, ctx.volumes, with_labels=False
        )
        features = matrix.features[-1:]  # latest row only
        if not np.all(np.isfinite(features)):
            return None
        try:
            proba = self._model.predict_proba(features)
        except Exception as exc:  # noqa: BLE001 - a model error must not crash trading
            self.log.warning("ai_predict_error", error=str(exc))
            return None
        value = float(np.asarray(proba).ravel()[-1])
        if not np.isfinite(value):
            return None
        return value

    def _regime_blocked(self, ctx: StrategyContext) -> bool:
        reading = self._regime.detect(ctx.highs, ctx.lows, ctx.closes)
        blocked = {str(r).lower() for r in self.param("blocked_regimes")}
        return reading.regime.value in blocked or reading.regime is MarketRegime.UNKNOWN


__all__ = ["AIStrategy"]
