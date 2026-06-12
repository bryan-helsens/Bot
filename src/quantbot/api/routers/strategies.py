"""Strategy listing and performance endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from quantbot.api.dependencies import AuthDep, StateDep, trade_history
from quantbot.api.schemas import MessageResponse, StrategyPerformanceSchema

router = APIRouter(prefix="/strategies", tags=["strategies"])


class ParamUpdate(BaseModel):
    """A live strategy-parameter change."""

    params: dict[str, str | float | int | bool]


def _describe(s) -> dict:
    return {
        "name": s.instance_name,
        "class": type(s).__name__,
        "symbols": s.symbols,
        "timeframes": [tf.value for tf in s.timeframes],
        "params": s.params,
        "default_params": getattr(s, "default_params", {}),
    }


@router.get("")
async def list_strategies(state: StateDep, _: AuthDep) -> list[dict]:
    """List active strategy instances with their configuration + tunable params."""
    return [_describe(s) for s in state.strategies]


@router.post("/{name}/params", response_model=MessageResponse)
async def update_strategy_params(
    name: str, body: ParamUpdate, state: StateDep, _: AuthDep
) -> MessageResponse:
    """Live-tune a strategy's parameters (effective next candle; not persisted)."""
    target = next((s for s in state.strategies if s.instance_name == name), None)
    if target is None:
        return MessageResponse(detail=f"No strategy named {name!r}", ok=False)
    if not hasattr(target, "update_params"):
        return MessageResponse(detail="Strategy does not support live tuning", ok=False)
    try:
        target.update_params(dict(body.params))
    except Exception as exc:  # noqa: BLE001 - surface validation errors to the UI
        return MessageResponse(detail=str(exc), ok=False)
    return MessageResponse(detail=f"Updated {name}: {body.params}")


@router.get("/performance", response_model=list[StrategyPerformanceSchema])
async def strategy_performance(state: StateDep, _: AuthDep) -> list[StrategyPerformanceSchema]:
    """Aggregate realised performance per strategy from trade history."""
    history = trade_history(state)
    if not history:
        return []
    by_strategy: dict[str, list] = {}
    for trade in history:
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
                net_profit=_finite(metrics.net_profit),
                profit_factor=_finite(metrics.profit_factor),
                win_rate=_finite(metrics.win_rate),
                sharpe_ratio=_finite(metrics.sharpe_ratio),
                max_drawdown=_finite(metrics.max_drawdown),
                total_trades=metrics.total_trades,
            )
        )
    return out


def _finite(value: float, default: float = 0.0) -> float:
    """Coerce NaN/inf to a JSON-safe number.

    Metrics like profit factor are infinite when there are no losing trades, and
    Sharpe is NaN with too few returns; both break JSON serialization (and the
    dashboard panel) unless sanitised.
    """
    import math

    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


__all__ = ["router"]
