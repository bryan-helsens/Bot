"""Random-search optimisation."""

from __future__ import annotations

import random

from quantbot.optimize.base import (
    Objective,
    OptimizationResult,
    Optimizer,
    SearchSpace,
    Trial,
)


class RandomSearchOptimizer(Optimizer):
    """Sample *n_trials* random parameter combinations and keep the best.

    Random search is often more efficient than grid search for high-dimensional
    spaces where only a few parameters matter.
    """

    def __init__(self, *, n_trials: int = 100, seed: int | None = None) -> None:
        self._n = n_trials
        self._rng = random.Random(seed)

    def optimize(
        self, objective: Objective, space: SearchSpace, *, metric: str = "score"
    ) -> OptimizationResult:
        trials: list[Trial] = []
        seen: set[tuple] = set()
        attempts = 0
        max_attempts = self._n * 5
        while len(trials) < self._n and attempts < max_attempts:
            attempts += 1
            params = space.sample(self._rng)
            key = tuple(sorted(params.items()))
            if key in seen:
                continue
            seen.add(key)
            trials.append(Trial(params=params, score=objective(params)))
        self.log.info("random_search_complete", evaluated=len(trials))
        return self._best(trials, metric)


__all__ = ["RandomSearchOptimizer"]
