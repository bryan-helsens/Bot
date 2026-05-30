"""Monte-Carlo simulation of trade sequences.

Given the realised per-trade PnLs from a backtest, Monte-Carlo resampling builds
a distribution of possible equity paths by either **shuffling** the trade order
or **bootstrapping** (sampling trades with replacement). This reveals how much of
the backtest's outcome was luck of sequencing and quantifies tail risk:
percentile final equity, expected/worst max drawdown, and the probability of
ruin (equity falling below a threshold).
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from quantbot.core.logging import LoggerMixin


@dataclass(slots=True)
class MonteCarloResult:
    """Distribution statistics from a Monte-Carlo run."""

    simulations: int
    mean_final_equity: float
    median_final_equity: float
    p5_final_equity: float
    p95_final_equity: float
    mean_max_drawdown: float
    worst_max_drawdown: float
    p95_max_drawdown: float
    probability_of_ruin: float
    probability_of_profit: float

    def as_dict(self) -> dict[str, float | int]:
        return {
            "simulations": self.simulations,
            "mean_final_equity": round(self.mean_final_equity, 2),
            "median_final_equity": round(self.median_final_equity, 2),
            "p5_final_equity": round(self.p5_final_equity, 2),
            "p95_final_equity": round(self.p95_final_equity, 2),
            "mean_max_drawdown": round(self.mean_max_drawdown, 6),
            "worst_max_drawdown": round(self.worst_max_drawdown, 6),
            "p95_max_drawdown": round(self.p95_max_drawdown, 6),
            "probability_of_ruin": round(self.probability_of_ruin, 4),
            "probability_of_profit": round(self.probability_of_profit, 4),
        }


class MonteCarloSimulator(LoggerMixin):
    """Resample trade PnLs to estimate the distribution of outcomes."""

    def __init__(
        self,
        *,
        simulations: int = 1000,
        method: str = "shuffle",  # "shuffle" | "bootstrap"
        ruin_threshold: float = 0.5,  # fraction of starting equity = ruin
        seed: int | None = None,
    ) -> None:
        self._n = simulations
        self._method = method
        self._ruin_threshold = ruin_threshold
        self._rng = random.Random(seed)

    def run(self, trade_pnls: list[float], *, starting_equity: float) -> MonteCarloResult:
        """Run the simulation over the realised *trade_pnls*."""
        if not trade_pnls:
            raise ValueError("trade_pnls is empty")
        ruin_level = starting_equity * self._ruin_threshold
        final_equities: list[float] = []
        max_drawdowns: list[float] = []
        ruins = 0
        profits = 0

        for _ in range(self._n):
            sequence = self._resample(trade_pnls)
            equity = starting_equity
            peak = starting_equity
            max_dd = 0.0
            ruined = False
            for pnl in sequence:
                equity += pnl
                peak = max(peak, equity)
                if peak > 0:
                    max_dd = max(max_dd, (peak - equity) / peak)
                if equity <= ruin_level:
                    ruined = True
            final_equities.append(equity)
            max_drawdowns.append(max_dd)
            if ruined:
                ruins += 1
            if equity > starting_equity:
                profits += 1

        final_equities.sort()
        max_drawdowns.sort()
        return MonteCarloResult(
            simulations=self._n,
            mean_final_equity=sum(final_equities) / self._n,
            median_final_equity=_percentile(final_equities, 50),
            p5_final_equity=_percentile(final_equities, 5),
            p95_final_equity=_percentile(final_equities, 95),
            mean_max_drawdown=sum(max_drawdowns) / self._n,
            worst_max_drawdown=max_drawdowns[-1],
            p95_max_drawdown=_percentile(max_drawdowns, 95),
            probability_of_ruin=ruins / self._n,
            probability_of_profit=profits / self._n,
        )

    def _resample(self, pnls: list[float]) -> list[float]:
        if self._method == "bootstrap":
            return [self._rng.choice(pnls) for _ in range(len(pnls))]
        shuffled = list(pnls)
        self._rng.shuffle(shuffled)
        return shuffled


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Linear-interpolation percentile of an already-sorted list."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100) * (len(sorted_values) - 1)
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    frac = rank - low
    return sorted_values[low] * (1 - frac) + sorted_values[high] * frac


__all__ = ["MonteCarloResult", "MonteCarloSimulator"]
