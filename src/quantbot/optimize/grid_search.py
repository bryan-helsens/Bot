"""Exhaustive grid-search optimisation."""

from __future__ import annotations

from quantbot.optimize.base import (
    Objective,
    OptimizationResult,
    Optimizer,
    SearchSpace,
    Trial,
)


class GridSearchOptimizer(Optimizer):
    """Evaluate every point in the parameter grid (exhaustive, deterministic)."""

    def __init__(self, *, max_evaluations: int | None = None) -> None:
        self._max = max_evaluations

    def optimize(
        self, objective: Objective, space: SearchSpace, *, metric: str = "score"
    ) -> OptimizationResult:
        total = space.grid_size()
        if self._max is not None and total > self._max:
            raise ValueError(
                f"Grid has {total} points exceeding max_evaluations={self._max}; "
                "use RandomSearch or BayesianOptimizer instead."
            )
        trials: list[Trial] = []
        for i, params in enumerate(space.grid(), start=1):
            score = objective(params)
            trials.append(Trial(params=params, score=score))
            if i % 25 == 0:
                self.log.debug("grid_progress", evaluated=i, total=total)
        self.log.info("grid_search_complete", evaluated=len(trials))
        return self._best(trials, metric)


__all__ = ["GridSearchOptimizer"]
