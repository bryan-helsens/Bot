"""Walk-forward validation for ML models.

Time-series data must never be validated with random shuffling (it leaks future
information). :class:`WalkForwardValidator` instead uses expanding or rolling
forward splits: train on the past, test on the immediately following block, step
forward, repeat. It reports out-of-sample classification metrics aggregated
across folds — the honest estimate of how a model would have performed live.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from quantbot.ai.models.base import BaseModel
from quantbot.core.logging import LoggerMixin

FloatArray = npt.NDArray[np.float64]


@dataclass(slots=True)
class FoldResult:
    """Metrics for one validation fold."""

    fold: int
    train_size: int
    test_size: int
    accuracy: float
    precision: float
    recall: float
    f1: float


@dataclass(slots=True)
class ValidationReport:
    """Aggregated walk-forward validation metrics."""

    folds: list[FoldResult] = field(default_factory=list)

    @property
    def mean_accuracy(self) -> float:
        return _mean(f.accuracy for f in self.folds)

    @property
    def mean_precision(self) -> float:
        return _mean(f.precision for f in self.folds)

    @property
    def mean_recall(self) -> float:
        return _mean(f.recall for f in self.folds)

    @property
    def mean_f1(self) -> float:
        return _mean(f.f1 for f in self.folds)

    def summary(self) -> dict[str, float | int]:
        return {
            "folds": len(self.folds),
            "mean_accuracy": round(self.mean_accuracy, 4),
            "mean_precision": round(self.mean_precision, 4),
            "mean_recall": round(self.mean_recall, 4),
            "mean_f1": round(self.mean_f1, 4),
        }


class WalkForwardValidator(LoggerMixin):
    """Expanding-window walk-forward validation for a :class:`BaseModel`."""

    def __init__(
        self, *, n_splits: int = 5, expanding: bool = True, threshold: float = 0.5, min_train: int = 100
    ) -> None:
        self._n_splits = n_splits
        self._expanding = expanding
        self._threshold = threshold
        self._min_train = min_train

    def validate(
        self, model_factory: type[BaseModel] | object, x: FloatArray, y: FloatArray, **model_params
    ) -> ValidationReport:
        """Run walk-forward validation, returning aggregated OOS metrics.

        Args:
            model_factory: A :class:`BaseModel` subclass (instantiated per fold so
                each fold trains a fresh model) or a zero-arg callable returning one.
            x: Feature matrix.
            y: Binary labels (0/1).
            **model_params: Passed to the model constructor each fold.
        """
        n = x.shape[0]
        report = ValidationReport()
        fold_size = (n - self._min_train) // self._n_splits
        if fold_size <= 0:
            raise ValueError("Not enough samples for the requested number of splits")

        for fold in range(self._n_splits):
            test_start = self._min_train + fold * fold_size
            test_end = test_start + fold_size if fold < self._n_splits - 1 else n
            train_start = 0 if self._expanding else max(0, test_start - self._min_train * 2)
            x_train, y_train = x[train_start:test_start], y[train_start:test_start]
            x_test, y_test = x[test_start:test_end], y[test_start:test_end]
            if x_train.shape[0] < self._min_train or x_test.shape[0] == 0:
                continue

            model = self._instantiate(model_factory, model_params)
            model.fit(x_train, y_train)
            preds = model.predict(x_test, threshold=self._threshold)
            # Drop NaN predictions (e.g. LSTM warm-up rows).
            mask = np.isfinite(preds)
            metrics = _classification_metrics(y_test[mask], preds[mask])
            report.folds.append(
                FoldResult(
                    fold=fold, train_size=int(x_train.shape[0]), test_size=int(mask.sum()),
                    **metrics,
                )
            )
            self.log.info("validation_fold", fold=fold, accuracy=round(metrics["accuracy"], 3))
        return report

    @staticmethod
    def _instantiate(factory, params) -> BaseModel:
        if isinstance(factory, type):
            return factory(**params)
        return factory()  # zero-arg callable


def _classification_metrics(y_true: FloatArray, y_pred: FloatArray) -> dict[str, float]:
    """Accuracy/precision/recall/F1 for binary labels (no sklearn dependency)."""
    if y_true.size == 0:
        return {"accuracy": 0.0, "precision": 0.0, "recall": 0.0, "f1": 0.0}
    tp = float(np.sum((y_pred == 1) & (y_true == 1)))
    tn = float(np.sum((y_pred == 0) & (y_true == 0)))
    fp = float(np.sum((y_pred == 1) & (y_true == 0)))
    fn = float(np.sum((y_pred == 0) & (y_true == 1)))
    accuracy = (tp + tn) / y_true.size
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {"accuracy": accuracy, "precision": precision, "recall": recall, "f1": f1}


def _mean(values) -> float:
    vals = list(values)
    return sum(vals) / len(vals) if vals else 0.0


__all__ = ["FoldResult", "ValidationReport", "WalkForwardValidator"]
