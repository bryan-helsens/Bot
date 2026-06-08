"""Event-driven backtesting engine.

Replays historical candles bar by bar through the *same* domain components used
in live trading — strategies, :class:`SignalAggregator`, :class:`RiskEngine`,
:class:`PositionManager` and :class:`StopManager` — with a
:class:`SimulatedBroker` applying commission, slippage and spread. Because the
decision path is identical to production, a strategy that backtests well behaves
the same live (subject to real-market fills).

Accounting is explicit spot-style cash management:

    equity = free_cash + (open position marked to the current close)

so the equity curve, drawdown and returns are unambiguous. The engine returns a
:class:`BacktestResult` with the full metric suite.
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np

from quantbot.backtest.broker import Fill, SimulatedBroker
from quantbot.backtest.metrics import BacktestResult, compute_result
from quantbot.core.config import Settings, get_settings
from quantbot.core.constants import ExitReason, MarketType, PositionSide, Side, Timeframe
from quantbot.core.logging import LoggerMixin
from quantbot.core.models import Candle, Position, Signal
from quantbot.portfolio.position import PositionManager
from quantbot.risk.engine import PortfolioView, RiskEngine
from quantbot.strategies.aggregator import SignalAggregator
from quantbot.strategies.base import BaseStrategy, StrategyContext


class BacktestEngine(LoggerMixin):
    """Replay candles through the live decision path with simulated fills."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        strategies: list[BaseStrategy],
        risk_engine: RiskEngine | None = None,
        aggregator: SignalAggregator | None = None,
        broker: SimulatedBroker | None = None,
        warmup: int = 50,
        allow_short: bool | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._strategies = strategies
        # Drive the risk engine's circuit-breaker cooldown by *simulation* time
        # (candle clock), not wall-clock — otherwise a cooldown set in
        # milliseconds of real time never expires and freezes the backtest.
        self._sim_time = 0.0
        self._risk = risk_engine or RiskEngine(
            self._settings.risk, clock=lambda: self._sim_time
        )
        self._aggregator = aggregator or SignalAggregator(self._settings.aggregator)
        bt = self._settings.backtest
        self._broker = broker or SimulatedBroker(
            commission=bt.commission, slippage=bt.slippage, spread=bt.spread
        )
        self._warmup = warmup
        # On spot you cannot short: a sell with no position is flat, and a sell
        # while long is an exit. Only futures may open shorts. Default from market.
        self._allow_short = (
            allow_short
            if allow_short is not None
            else self._settings.binance.market is MarketType.FUTURES
        )

    def run(self, candles: list[Candle], *, symbol: str | None = None) -> BacktestResult:
        """Backtest over *candles* (a single symbol/timeframe series)."""
        if len(candles) < self._warmup + 2:
            raise ValueError(
                f"Need at least {self._warmup + 2} candles, got {len(candles)}"
            )
        symbol = symbol or candles[0].symbol
        timeframe = candles[0].timeframe

        for strategy in self._strategies:
            strategy.reset()

        positions = PositionManager()
        initial = float(self._settings.backtest.initial_capital)
        cash = Decimal(str(self._settings.backtest.initial_capital))
        self._risk.set_starting_equity(cash)

        # Precompute arrays once; slice cheap numpy views per bar.
        opens = np.array([float(c.open) for c in candles], dtype=np.float64)
        highs = np.array([float(c.high) for c in candles], dtype=np.float64)
        lows = np.array([float(c.low) for c in candles], dtype=np.float64)
        closes = np.array([float(c.close) for c in candles], dtype=np.float64)
        volumes = np.array([float(c.volume) for c in candles], dtype=np.float64)

        trades = []
        equity_curve = [initial]
        timestamps = [candles[self._warmup].open_time.isoformat()]
        entry_bar: dict[str, int] = {}

        tf_seconds = float(timeframe.seconds)
        for i in range(self._warmup, len(candles)):
            candle = candles[i]
            price = candle.close
            # Advance the simulation clock so circuit-breaker cooldowns elapse
            # in candle time rather than (frozen) wall-clock time.
            self._sim_time += tf_seconds

            # 1. Mark and manage an open position (intrabar high/low for stops).
            position = positions.get(symbol)
            if position is not None and position.is_open:
                positions.update_mark_price(symbol, price)
                cash, exited = self._manage_position(
                    positions, position, candle, cash, trades, entry_bar, i
                )

            # 2. Generate & aggregate signals.
            signal = self._evaluate_strategies(
                candle, opens, highs, lows, closes, volumes, i
            )
            if signal is not None:
                held = positions.get(symbol)
                if held is not None and held.is_open:
                    # A signal opposite to the open position closes it (a sell
                    # exits a long; a buy exits a short). Same-direction signals
                    # are ignored (no pyramiding here).
                    opposes = (
                        signal.side is Side.SELL and held.side is PositionSide.LONG
                    ) or (signal.side is Side.BUY and held.side is PositionSide.SHORT)
                    if opposes:
                        cash, _ = self._close(
                            positions, held, candle.close, ExitReason.SIGNAL,
                            cash, trades, entry_bar, i,
                        )
                else:
                    # No position: open a long on a buy; open a short on a sell
                    # only if shorting is allowed (futures). On spot a sell is flat.
                    if signal.side is Side.BUY or self._allow_short:
                        cash = self._try_open(
                            signal, positions, symbol, cash, candle, entry_bar, i
                        )

            # 3. Record equity (cash + open position marked to close).
            equity_curve.append(float(self._equity(cash, positions, symbol, price)))
            timestamps.append(candle.open_time.isoformat())
            self._risk.update_equity(self._equity(cash, positions, symbol, price))

        # Close any residual position at the final close.
        final = candles[-1]
        residual = positions.get(symbol)
        if residual is not None and residual.is_open:
            cash, _ = self._close(
                positions, residual, final.close, ExitReason.SIGNAL, cash, trades,
                entry_bar, len(candles) - 1,
            )
            equity_curve[-1] = float(cash)

        result = compute_result(
            trades=trades,
            equity_curve=equity_curve,
            timestamps=timestamps,
            initial_capital=initial,
            periods_per_year=_periods_per_year(timeframe),
            symbol=symbol,
            strategy="+".join(s.instance_name for s in self._strategies),
            start=candles[0].open_time.isoformat(),
            end=candles[-1].close_time.isoformat(),
            bars=len(candles),
        )
        self.log.info("backtest_complete", **{k: result.summary()[k] for k in
                       ("total_return_pct", "total_trades", "win_rate", "max_drawdown")})
        return result

    # ------------------------------------------------------------------ internals

    def _evaluate_strategies(
        self, candle: Candle, opens, highs, lows, closes, volumes, i: int
    ) -> Signal | None:
        ctx = StrategyContext(
            symbol=candle.symbol,
            timeframe=candle.timeframe,
            candle=candle,
            opens=opens[: i + 1],
            highs=highs[: i + 1],
            lows=lows[: i + 1],
            closes=closes[: i + 1],
            volumes=volumes[: i + 1],
        )
        signals = []
        for strategy in self._strategies:
            if strategy.symbols and candle.symbol not in strategy.symbols:
                continue
            try:
                sig = _run_sync(strategy, ctx)
            except Exception as exc:  # noqa: BLE001
                self.log.warning("strategy_error", strategy=strategy.instance_name, error=str(exc))
                continue
            if sig is not None and sig.is_actionable:
                signals.append(sig)
        if not signals:
            return None
        result = self._aggregator.add_many(signals)
        return result.signal if result.actionable else None

    def _try_open(
        self, signal: Signal, positions: PositionManager, symbol: str,
        cash: Decimal, candle: Candle, entry_bar: dict, i: int,
    ) -> Decimal:
        # Equity (not raw cash) is the correct basis for sizing; with no open
        # position here, equity equals cash.
        view = PortfolioView(equity=cash, available_balance=cash, open_positions=[])
        proposal = _run_risk(self._risk, signal, view, candle.range or None)
        if not proposal.approved or proposal.quantity <= 0:
            return cash
        fill = self._broker.fill(signal.side, proposal.quantity, candle.close)
        # A spot position cannot cost more cash than is available. Slippage/spread
        # can push the fill notional slightly above the sized notional, so scale
        # the quantity down to the fill price so the cost fits the cash budget (an
        # exchange fills only what you can afford) rather than silently dropping
        # the whole trade.
        max_notional = cash / (Decimal(1) + self._settings.backtest.commission)
        if fill.notional > max_notional and fill.price > 0:
            scaled_qty = max_notional / fill.price
            fill = Fill(price=fill.price, quantity=scaled_qty,
                        commission=fill.price * scaled_qty * self._broker.commission_rate)
        if fill.quantity <= 0:
            return cash
        positions.open_position(
            symbol=symbol, side=signal.side, quantity=fill.quantity,
            entry_price=fill.price, strategy=signal.strategy,
            stop_loss=proposal.stop_loss, take_profit_levels=proposal.take_profit_levels,
            fee=fill.commission,
        )
        entry_bar[symbol] = i
        # PnL-based accounting: opening does not move cash; the entry fee is
        # carried on the position and realised (in net_pnl) on close.
        return cash

    def _manage_position(
        self, positions: PositionManager, position: Position, candle: Candle,
        cash: Decimal, trades: list, entry_bar: dict, i: int,
    ) -> tuple[Decimal, bool]:
        """Evaluate stops/TP using intrabar extremes; execute any exit."""
        # Use the adverse extreme to test the stop, the favourable for TP.
        decision_price = candle.low if position.side is PositionSide.LONG else candle.high
        decision = self._risk.stops.evaluate(position, decision_price)
        if decision.new_stop_loss is not None:
            positions.update_stop(position.symbol, decision.new_stop_loss)
        if decision.new_trailing_stop is not None:
            positions.update_trailing_stop(position.symbol, decision.new_trailing_stop)
        if decision.break_even_armed:
            positions.arm_break_even(position.symbol)

        if not decision.should_exit:
            # Re-check take-profit against the favourable extreme separately.
            tp_price = candle.high if position.side is PositionSide.LONG else candle.low
            tp_decision = self._risk.stops.evaluate(position, tp_price)
            if not (tp_decision.should_exit and tp_decision.exit_reason == ExitReason.TAKE_PROFIT):
                return cash, False
            decision = tp_decision

        exit_price = position.stop_loss if decision.exit_reason in (
            ExitReason.STOP_LOSS, ExitReason.TRAILING_STOP
        ) else candle.close
        if decision.exit_fraction >= Decimal("1"):
            cash, _ = self._close(
                positions, position, exit_price or candle.close, decision.exit_reason,
                cash, trades, entry_bar, i,
            )
            return cash, True
        # Partial take-profit.
        cash = self._reduce(
            positions, position, decision.exit_fraction, exit_price or candle.close,
            decision.exit_reason, decision.triggered_tp_index, cash, trades,
        )
        return cash, False

    def _close(
        self, positions: PositionManager, position: Position, price: Decimal,
        reason: ExitReason, cash: Decimal, trades: list, entry_bar: dict, i: int,
    ) -> tuple[Decimal, bool]:
        exit_side = Side.SELL if position.side is PositionSide.LONG else Side.BUY
        fill = self._broker.fill_at(exit_side, position.quantity, price)
        bars = i - entry_bar.get(position.symbol, i)
        trade = positions.close_position(
            position.symbol, exit_price=fill.price, reason=reason,
            fee=fill.commission, bars_held=bars,
        )
        if trade is not None:
            trades.append(trade)
            self._risk.record_trade_result(position, trade.net_pnl)
            cash += trade.net_pnl  # realise PnL (already net of all fees)
        return cash, True

    def _reduce(
        self, positions: PositionManager, position: Position, fraction: Decimal,
        price: Decimal, reason: ExitReason, tp_index, cash: Decimal, trades: list,
    ) -> Decimal:
        exit_side = Side.SELL if position.side is PositionSide.LONG else Side.BUY
        close_qty = position.quantity * fraction
        fill = self._broker.fill_at(exit_side, close_qty, price)
        trade = positions.reduce_position(
            position.symbol, fraction=fraction, exit_price=fill.price,
            reason=reason, fee=fill.commission, tp_index=tp_index,
        )
        if trade is not None:
            trades.append(trade)
            self._risk.record_trade_result(position, trade.net_pnl)
            cash += trade.net_pnl  # realise the partial PnL (net of fees)
        return cash

    @staticmethod
    def _equity(cash: Decimal, positions: PositionManager, symbol: str, price: Decimal) -> Decimal:
        position = positions.get(symbol)
        if position is None or not position.is_open:
            return cash
        # Side-agnostic, PnL-based: cash + unrealised PnL − fees already accrued.
        return cash + position.unrealized_pnl(price) - position.fees_paid


def _run_sync(strategy: BaseStrategy, ctx: StrategyContext) -> Signal | None:
    """Execute a strategy's async ``on_candle`` synchronously for backtests."""
    import asyncio

    coro = strategy.on_candle(ctx)
    try:
        coro.send(None)
    except StopIteration as stop:
        return stop.value
    # Strategy awaited something (rare); fall back to a fresh loop.
    return asyncio.run(strategy.on_candle(ctx))


def _run_risk(risk: RiskEngine, signal: Signal, view: PortfolioView, atr):
    import asyncio

    coro = risk.evaluate(signal, view, atr=atr)
    try:
        coro.send(None)
    except StopIteration as stop:
        return stop.value
    return asyncio.run(risk.evaluate(signal, view, atr=atr))


def _periods_per_year(timeframe: Timeframe) -> int:
    """Annualisation factor: number of candles of this timeframe per year."""
    seconds_per_year = 365 * 24 * 3600
    return max(1, seconds_per_year // timeframe.seconds)


__all__ = ["BacktestEngine"]
