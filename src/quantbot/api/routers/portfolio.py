"""Portfolio summary and equity-curve endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter

from quantbot.api.dependencies import AuthDep, StateDep, trade_history
from quantbot.api.schemas import (
    AnalyticsSchema,
    CoinAnalytics,
    CoinDetailSchema,
    DailyPnlPoint,
    EquityPoint,
    PortfolioSchema,
    TradeSchema,
    TradingStatsSchema,
)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("", response_model=PortfolioSchema)
async def portfolio_summary(state: StateDep, _: AuthDep) -> PortfolioSchema:
    """Return the current portfolio summary."""
    pf = state.portfolio
    if pf is None:
        return _empty()
    return PortfolioSchema(
        equity=str(pf.equity()),
        cash=str(pf.cash),
        unrealized_pnl=str(pf.unrealized_pnl()),
        realized_pnl=str(pf.realized_pnl),
        exposure=str(pf.exposure()),
        exposure_pct=str(pf.exposure_pct()),
        total_return_pct=str(pf.total_return_pct()),
        open_positions=pf.positions.open_count,
        max_drawdown=str(pf.max_drawdown),
    )


@router.get("/equity-curve", response_model=list[EquityPoint])
async def equity_curve(state: StateDep, _: AuthDep) -> list[EquityPoint]:
    """Return the equity curve as time-stamped points."""
    pf = state.portfolio
    if pf is None:
        return []
    return [EquityPoint(timestamp=ts, equity=value) for ts, value in pf.equity_curve()]


@router.get("/stats", response_model=TradingStatsSchema)
async def trading_stats(state: StateDep, _: AuthDep) -> TradingStatsSchema:
    """Realised performance: today/week PnL, trade count, win rate, fees."""
    trades = trade_history(state)
    if not trades:
        return TradingStatsSchema()
    now = datetime.now(UTC)
    day_ago, week_ago = now - timedelta(days=1), now - timedelta(days=7)

    def _closed(t):
        ts = t.closed_at
        return ts if ts.tzinfo else ts.replace(tzinfo=UTC)

    today = [t for t in trades if _closed(t) >= day_ago]
    week = [t for t in trades if _closed(t) >= week_ago]
    wins = sum(1 for t in trades if t.net_pnl > 0)
    pnls = [t.net_pnl for t in trades]
    return TradingStatsSchema(
        today_pnl=str(sum((t.net_pnl for t in today), Decimal("0"))),
        week_pnl=str(sum((t.net_pnl for t in week), Decimal("0"))),
        today_trades=len(today),
        total_trades=len(trades),
        win_rate=round(wins / len(trades), 4),
        total_fees=str(sum((t.fees for t in trades), Decimal("0"))),
        best_trade=str(max(pnls)),
        worst_trade=str(min(pnls)),
    )


@router.get("/daily-pnl", response_model=list[DailyPnlPoint])
async def daily_pnl(state: StateDep, _: AuthDep, days: int = 30) -> list[DailyPnlPoint]:
    """Realised PnL per day (last *days*) from closed trades, for the bar chart."""
    trades = trade_history(state)
    if not trades:
        return []
    buckets: dict[str, list[Decimal]] = {}
    for t in trades:
        day = t.closed_at.date().isoformat()
        buckets.setdefault(day, []).append(t.net_pnl)
    points = [
        DailyPnlPoint(date=day, pnl=float(sum(pnls)), trades=len(pnls))
        for day, pnls in sorted(buckets.items())
    ]
    return points[-days:]


@router.get("/coin/{symbol}", response_model=CoinDetailSchema)
async def coin_detail(symbol: str, state: StateDep, _: AuthDep) -> CoinDetailSchema:
    """Everything the bot did with one coin: open position + trade history + stats."""
    symbol = symbol.upper()
    out = CoinDetailSchema(symbol=symbol)

    pf = state.portfolio
    if pf is not None:
        pos = pf.positions.get(symbol)
        if pos is not None and pos.is_open:
            mark = pf.price_of(symbol) or pos.mark_price or pos.entry_price
            out.has_position = True
            out.side = pos.side.value
            out.quantity = str(pos.quantity)
            out.entry_price = str(pos.entry_price)
            out.opened_at = pos.opened_at
            out.mark_price = str(mark)
            out.value = str(pos.quantity * mark)
            out.unrealized_pnl = str(pos.unrealized_pnl(mark))
            out.stop_loss = str(pos.stop_loss) if pos.stop_loss is not None else None

    engine = state.trading_engine
    if engine is not None and hasattr(engine, "coin_market_snapshot"):
        snap = engine.coin_market_snapshot(symbol)
        out.rsi = snap.get("rsi")
        out.prices = snap.get("prices", [])
        out.times = snap.get("times", [])
        out.price_timeframe = snap.get("price_timeframe")

    trades = [t for t in trade_history(state) if t.symbol == symbol]
    if trades:
        wins = sum(1 for t in trades if t.net_pnl > 0)
        out.realized_pnl = str(sum((t.net_pnl for t in trades), Decimal("0")))
        out.trade_count = len(trades)
        out.win_rate = round(wins / len(trades), 4)
        out.total_fees = str(sum((t.fees for t in trades), Decimal("0")))
        out.trades = [
            TradeSchema(
                id=t.id, symbol=t.symbol, side=t.side.value, strategy=t.strategy,
                quantity=str(t.quantity), entry_price=str(t.entry_price),
                exit_price=str(t.exit_price), net_pnl=str(t.net_pnl),
                return_pct=str(t.return_pct), exit_reason=t.exit_reason.value,
                opened_at=t.opened_at, closed_at=t.closed_at,
            )
            for t in reversed(trades)
        ]
    return out


def _hold_seconds(t) -> float:
    """Seconds a trade was held (opened_at → closed_at), tz-safe."""
    o, c = t.opened_at, t.closed_at
    if o.tzinfo is None:
        o = o.replace(tzinfo=UTC)
    if c.tzinfo is None:
        c = c.replace(tzinfo=UTC)
    return max(0.0, (c - o).total_seconds())


def _breakdown(name: str, trades: list) -> CoinAnalytics:
    """Aggregate a list of closed trades into a performance breakdown."""
    pnls = [t.net_pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_profit = sum(wins, Decimal("0"))
    gross_loss = abs(sum(losses, Decimal("0")))
    holds = [_hold_seconds(t) for t in trades]
    return CoinAnalytics(
        name=name,
        trades=len(trades),
        net_pnl=str(sum(pnls, Decimal("0"))),
        win_rate=round(len(wins) / len(trades), 4) if trades else 0.0,
        wins=len(wins),
        losses=len(losses),
        avg_win=str(gross_profit / len(wins)) if wins else "0",
        avg_loss=str(-gross_loss / len(losses)) if losses else "0",
        profit_factor=round(float(gross_profit / gross_loss), 3) if gross_loss > 0 else 0.0,
        total_fees=str(sum((t.fees for t in trades), Decimal("0"))),
        avg_hold_seconds=round(sum(holds) / len(holds), 1) if holds else 0.0,
        best=str(max(pnls)) if pnls else "0",
        worst=str(min(pnls)) if pnls else "0",
    )


@router.get("/analytics", response_model=AnalyticsSchema)
async def analytics(state: StateDep, _: AuthDep) -> AnalyticsSchema:
    """Deep realised-performance breakdown: overall + per coin + per strategy."""
    trades = trade_history(state)
    quote = state.settings.quote_asset
    if not trades:
        return AnalyticsSchema(quote_asset=quote)

    pnls = [t.net_pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_profit = sum(wins, Decimal("0"))
    gross_loss = abs(sum(losses, Decimal("0")))
    net = sum(pnls, Decimal("0"))
    holds = [_hold_seconds(t) for t in trades]

    by_coin: dict[str, list] = {}
    by_strategy: dict[str, list] = {}
    by_exit: dict[str, int] = {}
    for t in trades:
        by_coin.setdefault(t.symbol, []).append(t)
        by_strategy.setdefault(t.strategy or "manual", []).append(t)
        reason = t.exit_reason.value if hasattr(t.exit_reason, "value") else str(t.exit_reason)
        by_exit[reason] = by_exit.get(reason, 0) + 1

    coin_rows = sorted(
        (_breakdown(s, ts) for s, ts in by_coin.items()),
        key=lambda r: float(r.net_pnl), reverse=True,
    )
    strat_rows = sorted(
        (_breakdown(s, ts) for s, ts in by_strategy.items()),
        key=lambda r: float(r.net_pnl), reverse=True,
    )
    return AnalyticsSchema(
        quote_asset=quote,
        total_trades=len(trades),
        net_pnl=str(net),
        gross_profit=str(gross_profit),
        gross_loss=str(-gross_loss),
        win_rate=round(len(wins) / len(trades), 4),
        profit_factor=round(float(gross_profit / gross_loss), 3) if gross_loss > 0 else 0.0,
        expectancy=str(net / len(trades)),
        avg_hold_seconds=round(sum(holds) / len(holds), 1) if holds else 0.0,
        total_fees=str(sum((t.fees for t in trades), Decimal("0"))),
        by_coin=coin_rows,
        by_strategy=strat_rows,
        by_exit_reason=by_exit,
    )


@router.get("/allocation")
async def allocation(state: StateDep, _: AuthDep) -> dict[str, float]:
    """Return per-symbol allocation as fractions of equity."""
    pf = state.portfolio
    if pf is None:
        return {}
    return {symbol: float(frac) for symbol, frac in pf.allocation().items()}


def _empty() -> PortfolioSchema:
    z = str(Decimal("0"))
    return PortfolioSchema(
        equity=z, cash=z, unrealized_pnl=z, realized_pnl=z, exposure=z,
        exposure_pct=z, total_return_pct=z, open_positions=0, max_drawdown=z,
    )


__all__ = ["router"]
