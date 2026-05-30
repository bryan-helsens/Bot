"""Optimisation primitives: search space, objective and the Optimizer interface.

A :class:`SearchSpace` describes the parameters to tune (integer/float ranges and
categorical choices) and can enumerate a grid, draw random samples, or suggest
values to an Optuna trial. An *objective* maps a parameter dict to a score
(higher is better). :func:`make_backtest_objective` builds one that runs a
backtest and returns the chosen metric, so any optimizer can tune any strategy.

All optimizers **maximise**; to minimise a metric, negate it in the objective.
"""

from __future__ import annotations

import abc
import itertools
import random
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from quantbot.core.logging import LoggerMixin

#: An objective maps a parameter mapping to a scalar score (maximised).
Objective = Callable[[dict[str, Any]], float]


# ---------------------------------------------------------------------------
# Parameter definitions
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class IntRange:
    """An integer parameter over ``[low, high]`` with an inclusive *step*."""

    low: int
    high: int
    step: int = 1

    def values(self) -> list[int]:
        return list(range(self.low, self.high + 1, self.step))

    def sample(self, rng: random.Random) -> int:
        return rng.choice(self.values())


@dataclass(slots=True)
class FloatRange:
    """A float parameter over ``[low, high]`` with a discretisation *step*."""

    low: float
    high: float
    step: float = 0.0

    def values(self) -> list[float]:
        if self.step <= 0:
            return [self.low, (self.low + self.high) / 2, self.high]
        out, value = [], self.low
        while value <= self.high + 1e-12:
            out.append(round(value, 10))
            value += self.step
        return out

    def sample(self, rng: random.Random) -> float:
        if self.step <= 0:
            return rng.uniform(self.low, self.high)
        return rng.choice(self.values())


@dataclass(slots=True)
class Categorical:
    """A categorical parameter over a fixed set of *choices*."""

    choices: list[Any]

    def values(self) -> list[Any]:
        return list(self.choices)

    def sample(self, rng: random.Random) -> Any:
        return rng.choice(self.choices)


ParamSpec = IntRange | FloatRange | Categorical


class SearchSpace:
    """A named collection of parameter specifications."""

    def __init__(self, params: dict[str, ParamSpec]) -> None:
        self._params = params

    @property
    def names(self) -> list[str]:
        return list(self._params)

    def grid(self) -> Iterator[dict[str, Any]]:
        """Enumerate the full Cartesian product of all parameter values."""
        names = list(self._params)
        value_lists = [self._params[n].values() for n in names]
        for combo in itertools.product(*value_lists):
            yield dict(zip(names, combo, strict=True))

    def grid_size(self) -> int:
        size = 1
        for spec in self._params.values():
            size *= len(spec.values())
        return size

    def sample(self, rng: random.Random) -> dict[str, Any]:
        """Draw one random parameter combination."""
        return {name: spec.sample(rng) for name, spec in self._params.items()}

    def suggest_optuna(self, trial: Any) -> dict[str, Any]:
        """Suggest a parameter set from an Optuna trial."""
        out: dict[str, Any] = {}
        for name, spec in self._params.items():
            if isinstance(spec, IntRange):
                out[name] = trial.suggest_int(name, spec.low, spec.high, step=spec.step)
            elif isinstance(spec, FloatRange):
                if spec.step > 0:
                    out[name] = trial.suggest_float(name, spec.low, spec.high, step=spec.step)
                else:
                    out[name] = trial.suggest_float(name, spec.low, spec.high)
            else:
                out[name] = trial.suggest_categorical(name, spec.choices)
        return out


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Trial:
    """A single evaluated parameter set."""

    params: dict[str, Any]
    score: float


@dataclass(slots=True)
class OptimizationResult:
    """The outcome of an optimisation run."""

    best_params: dict[str, Any]
    best_score: float
    trials: list[Trial] = field(default_factory=list)
    metric: str = "score"

    def top(self, n: int = 5) -> list[Trial]:
        return sorted(self.trials, key=lambda t: t.score, reverse=True)[:n]


# ---------------------------------------------------------------------------
# Optimizer interface
# ---------------------------------------------------------------------------


class Optimizer(LoggerMixin, abc.ABC):
    """Base class for all optimizers (always maximises the objective)."""

    @abc.abstractmethod
    def optimize(
        self, objective: Objective, space: SearchSpace, *, metric: str = "score"
    ) -> OptimizationResult:
        """Search *space* to maximise *objective*."""

    @staticmethod
    def _best(trials: list[Trial], metric: str) -> OptimizationResult:
        if not trials:
            raise ValueError("No trials evaluated")
        best = max(trials, key=lambda t: t.score)
        return OptimizationResult(best.params, best.score, trials, metric)


# ---------------------------------------------------------------------------
# Backtest objective factory
# ---------------------------------------------------------------------------


def make_backtest_objective(
    *,
    strategy_cls: type,
    candles: list,
    settings: Any,
    metric: str = "sharpe_ratio",
    symbols: list[str] | None = None,
    timeframes: list | None = None,
    warmup: int = 50,
    minimise: bool = False,
    fixed_params: dict[str, Any] | None = None,
) -> Objective:
    """Build an objective that backtests *strategy_cls* and returns *metric*.

    The returned callable takes a params dict, runs a backtest and returns the
    requested metric (negated if *minimise*). Invalid parameter combinations
    (e.g. fast >= slow) score ``-inf`` so the optimizer avoids them.
    """
    from quantbot.backtest.engine import BacktestEngine

    fixed = fixed_params or {}

    def objective(params: dict[str, Any]) -> float:
        merged = {**fixed, **params}
        try:
            strategy = strategy_cls(symbols=symbols, timeframes=timeframes, params=merged)
            engine = BacktestEngine(settings=settings, strategies=[strategy], warmup=warmup)
            result = engine.run(candles)
        except Exception:  # noqa: BLE001 - invalid params -> worst score
            return float("-inf")
        value = float(result.summary().get(metric, 0.0))
        if value != value:  # NaN guard
            return float("-inf")
        return -value if minimise else value

    return objective


def _coerce_decimal(params: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    """Helper to convert selected params to Decimal (for risk-style params)."""
    out = dict(params)
    for key in keys:
        if key in out:
            out[key] = Decimal(str(out[key]))
    return out


__all__ = [
    "Categorical",
    "FloatRange",
    "IntRange",
    "Objective",
    "OptimizationResult",
    "Optimizer",
    "ParamSpec",
    "SearchSpace",
    "Trial",
    "make_backtest_objective",
]
