"""Strategy listing and performance endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from quantbot.api.dependencies import AuthDep, StateDep
from quantbot.api.schemas import StrategyPerformanceSchema

router = APIRouter(prefix="/strategies", tags=["strategies"])


@router.get("")
async def list_strategies(state: StateDep, _: AuthDep) -> list[dict]:
    """List active strategy instances with their configuration."""
    return [
        {
            "name": s.instance_name,
            "class": type(s).__name__,
            "symbols": s.symbols,
            "timeframes": [tf.value for tf in s.timeframes],
            "params": s.params,
        }
        for s in state.strategies
    ]


@router.get("/performance", response_model=list[StrategyPerformanceSchema])
async def strategy_performance(state: StateDep, _: AuthDep) -> list[StrategyPerformanceSchema]:
    """Aggregate realised performance per strategy from trade history."""
    perf = state.performance
    if perf is None:
        return []
    by_strategy: dict[str, list] = {}
    for trade in perf.trades:
        by_strategy.setdefault(trade.strategy or "unknown", []).append(trade)

    from quantbot.portfolio.performance import PerformanceTracker

    out: list[StrategyPerformanceSchema] = []
    for strategy, trades in by_strategy.items():
        tracker = PerformanceTracker(starting_equity=1.0)
        for trade in trades:
            tracker.add_trade(trade)
        metrics = tracker.compute()
        out.append(
            StrategyPerformanceSchema(
                strategy=strategy,
                net_profit=metrics.net_profit,
                profit_factor=metrics.profit_factor,
                win_rate=metrics.win_rate,
                sharpe_ratio=metrics.sharpe_ratio,
                max_drawdown=metrics.max_drawdown,
                total_trades=metrics.total_trades,
            )
        )
    return out


__all__ = ["router"]
