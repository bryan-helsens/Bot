"""Bayesian optimisation via Optuna (optional dependency)."""

from __future__ import annotations

from typing import Any

from quantbot.core.exceptions import DependencyError
from quantbot.optimize.base import (
    Objective,
    OptimizationResult,
    Optimizer,
    SearchSpace,
    Trial,
)


class BayesianOptimizer(Optimizer):
    """Tree-structured Parzen Estimator (TPE) optimisation using Optuna.

    Bayesian optimisation models the objective and focuses sampling on promising
    regions, typically finding good parameters in far fewer evaluations than grid
    or random search. Requires the optional ``optuna`` dependency
    (``pip install 'quantbot[optimize]'``).
    """

    def __init__(self, *, n_trials: int = 100, seed: int | None = None, timeout: float | None = None) -> None:
        self._n = n_trials
        self._seed = seed
        self._timeout = timeout

    def optimize(
        self, objective: Objective, space: SearchSpace, *, metric: str = "score"
    ) -> OptimizationResult:
        optuna = _import_optuna()
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        sampler = optuna.samplers.TPESampler(seed=self._seed)
        study = optuna.create_study(direction="maximize", sampler=sampler)

        def _objective(trial: Any) -> float:
            params = space.suggest_optuna(trial)
            return objective(params)

        study.optimize(_objective, n_trials=self._n, timeout=self._timeout, show_progress_bar=False)

        trials = [
            Trial(params=dict(t.params), score=float(t.value))
            for t in study.trials
            if t.value is not None
        ]
        self.log.info("bayesian_search_complete", evaluated=len(trials), best=study.best_value)
        return OptimizationResult(
            best_params=dict(study.best_params),
            best_score=float(study.best_value),
            trials=trials,
            metric=metric,
        )


def _import_optuna() -> Any:
    try:
        import optuna  # type: ignore

        return optuna
    except ImportError as exc:  # pragma: no cover - exercised when optuna absent
        raise DependencyError(
            "Bayesian optimisation requires optuna. Install with: pip install 'quantbot[optimize]'"
        ) from exc


__all__ = ["BayesianOptimizer"]
