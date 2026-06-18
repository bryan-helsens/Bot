"""Historical replay backtester.

Drives the REAL :class:`~quantbot.engine.trading_engine.TradingEngine` over
historical candles, so a backtest reflects exactly what the live bot does — the
RSI trend filter, no-churn exits, the re-entry cooldown and every risk gate —
with realistic paper fills (slippage + commission, stops enforced per-candle).

This avoids the classic backtest trap of a *separate* engine with optimistic
fills that flatters results (see docs/REALISTIC_FILLS_REPORT.md). Data is real
mainnet history (public klines, no API key needed); orders are simulated locally.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from quantbot.core.config import Settings
from quantbot.core.constants import Timeframe, TradingMode
from quantbot.core.logging import get_logger
from quantbot.core.models import Candle

_log = get_logger("backtest.replay")


async def load_history(
    settings: Settings,
    symbols: list[str],
    timeframe: Timeframe,
    start: datetime,
    end: datetime,
) -> dict[str, list[Candle]]:
    """Fetch real MAINNET history for each symbol (klines are public, no keys)."""
    from quantbot.data.historical import HistoricalDataLoader
    from quantbot.exchanges.factory import create_gateway

    data_settings = settings.model_copy(deep=True)
    data_settings.binance.testnet = False  # real history, not the thin testnet
    gateway = create_gateway(data_settings)
    await gateway.connect()
    out: dict[str, list[Candle]] = {}
    try:
        loader = HistoricalDataLoader(gateway)
        for symbol in symbols:
            try:
                candles = await loader.load(symbol, timeframe, start, end)
            except Exception as exc:  # noqa: BLE001 - skip a symbol that won't load
                _log.warning("history_load_failed", symbol=symbol, error=str(exc))
                continue
            if len(candles) >= 120:
                out[symbol] = candles
            else:
                _log.warning("history_too_short", symbol=symbol, candles=len(candles))
    finally:
        await gateway.close()
    return out


async def replay_candles(
    settings: Settings,
    candles_by_symbol: dict[str, list[Candle]],
    timeframe: Timeframe,
    *,
    warmup: int = 120,
    param_overrides: dict | None = None,
) -> dict:
    """Replay pre-loaded candles through the real engine; return a result summary.

    *param_overrides* (e.g. ``{"oversold": 35, "trend_filter": False}``) is applied
    live to every loaded strategy that declares those params — used by the sweep to
    compare variants on identical history without editing config files.
    """
    from quantbot.engine.runtime import build_runtime

    settings = settings.model_copy(deep=True)
    settings.trading_mode = TradingMode.PAPER
    runtime = build_runtime(settings)
    engine = runtime.engine
    portfolio = runtime.portfolio
    runtime.executor.set_rate_limit(0.0)  # no real-time throttle in a backtest
    market_data = engine.market_data

    if param_overrides:
        for strat in runtime.strategies:
            applicable = {k: v for k, v in param_overrides.items() if k in strat.params}
            if applicable:
                strat.update_params(applicable)

    # Seed permissive symbol info so the executor's min-notional check never makes a
    # per-trade network call (orders are well above min-notional in a backtest anyway).
    from quantbot.core.models import SymbolInfo

    base_gateway = getattr(runtime.gateway, "_real", runtime.gateway)
    quote = settings.quote_asset
    symbol_cache = getattr(base_gateway, "_symbols", None)
    if isinstance(symbol_cache, dict):
        for symbol in candles_by_symbol:
            base = symbol[: -len(quote)] if symbol.endswith(quote) else symbol
            symbol_cache.setdefault(
                symbol, SymbolInfo(symbol=symbol, base_asset=base, quote_asset=quote)
            )

    # Seed each series with its warmup window (indicators need history) and collect
    # the rest as the tradeable stream, replayed in global time order.
    tradeable: list[Candle] = []
    for symbol, candles in candles_by_symbol.items():
        ordered = sorted(candles, key=lambda c: c.open_time)
        series = market_data.series(symbol, timeframe)
        for candle in ordered[:warmup]:
            series.append(candle)
        tradeable.extend(ordered[warmup:])
    tradeable.sort(key=lambda c: c.open_time)

    initial = float(settings.backtest.initial_capital)
    peak = initial
    max_dd = 0.0
    curve: list[tuple[str, float]] = []
    for i, candle in enumerate(tradeable):
        market_data.series(candle.symbol, timeframe).append(candle)
        await engine.process_candle(candle)
        equity = float(portfolio.equity())
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak)
        if i % 500 == 0:
            curve.append((candle.open_time.isoformat(), round(equity, 4)))

    return _summarize(settings, portfolio, candles_by_symbol, max_dd, curve, len(tradeable))


def _summarize(
    settings: Settings,
    portfolio,
    candles_by_symbol: dict[str, list[Candle]],
    max_dd: float,
    curve: list[tuple[str, float]],
    candles_replayed: int,
) -> dict:
    trades = list(portfolio.closed_trades)
    pnls = [t.net_pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_profit = sum(wins, Decimal("0"))
    gross_loss = abs(sum(losses, Decimal("0")))
    net = sum(pnls, Decimal("0"))
    fees = sum((t.fees for t in trades), Decimal("0"))
    initial = settings.backtest.initial_capital

    def _hold(t) -> float:
        o, c = t.opened_at, t.closed_at
        o = o if o.tzinfo else o.replace(tzinfo=UTC)
        c = c if c.tzinfo else c.replace(tzinfo=UTC)
        return max(0.0, (c - o).total_seconds())

    holds = [_hold(t) for t in trades]

    # Buy & hold benchmark: BTC if present, else the first symbol.
    bench_symbol = "BTCUSDT" if "BTCUSDT" in candles_by_symbol else next(iter(candles_by_symbol), None)
    benchmark_pct = None
    if bench_symbol:
        closes = [c.close for c in candles_by_symbol[bench_symbol]]
        if len(closes) >= 2 and closes[0] > 0:
            benchmark_pct = round(float((closes[-1] - closes[0]) / closes[0]) * 100, 2)

    by_strategy: dict[str, Decimal] = {}
    by_coin: dict[str, Decimal] = {}
    for t in trades:
        by_strategy[t.strategy or "?"] = by_strategy.get(t.strategy or "?", Decimal("0")) + t.net_pnl
        by_coin[t.symbol] = by_coin.get(t.symbol, Decimal("0")) + t.net_pnl

    bot_return = float(net / initial * 100) if initial > 0 else 0.0
    return {
        "symbols": len(candles_by_symbol),
        "candles_replayed": candles_replayed,
        "trades": len(trades),
        "net_pnl": float(net),
        "gross_profit": float(gross_profit),
        "gross_loss": float(-gross_loss),
        "fees": float(fees),
        "fees_pct_of_gross": round(float(fees / gross_profit * 100), 1) if gross_profit > 0 else None,
        "win_rate": round(len(wins) / len(trades), 4) if trades else 0.0,
        "profit_factor": round(float(gross_profit / gross_loss), 3) if gross_loss > 0 else 0.0,
        "expectancy": float(net / len(trades)) if trades else 0.0,
        "avg_hold_seconds": round(sum(holds) / len(holds), 1) if holds else 0.0,
        "bot_return_pct": round(bot_return, 2),
        "benchmark_symbol": bench_symbol,
        "benchmark_pct": benchmark_pct,
        "max_drawdown_pct": round(max_dd * 100, 2),
        "by_strategy": {k: float(v) for k, v in sorted(by_strategy.items(), key=lambda kv: kv[1])},
        "by_coin": {k: float(v) for k, v in sorted(by_coin.items(), key=lambda kv: kv[1])},
        "equity_curve": curve,
        "initial_capital": float(initial),
    }


async def run_replay(
    settings: Settings,
    *,
    symbols: list[str],
    timeframe: Timeframe,
    start: datetime,
    end: datetime,
    warmup: int = 120,
) -> dict:
    """Load real history then replay it through the engine. Returns a summary dict."""
    candles_by_symbol = await load_history(settings, symbols, timeframe, start, end)
    if not candles_by_symbol:
        raise ValueError("No usable history loaded for any symbol")
    return await replay_candles(settings, candles_by_symbol, timeframe, warmup=warmup)


__all__ = ["load_history", "replay_candles", "run_replay"]
