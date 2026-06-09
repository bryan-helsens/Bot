"""The TradingEngine — live/paper orchestration loop.

Wires every component together and drives the per-candle decision cycle:

    candle closed
        → update prices (portfolio, risk correlation, paper broker)
        → manage open position (stop-loss / trailing / take-profit / break-even)
        → run every strategy matching (symbol, timeframe) → collect signals
        → aggregate by confluence
        → if actionable: RiskEngine validates & OrderExecutor places the order
        → periodic equity snapshot

The engine is exchange-agnostic (works with a live gateway or the
:class:`PaperTradingBroker`) and event-driven: it subscribes to the market-data
service's ``CANDLE_CLOSED`` events. :meth:`process_candle` is also callable
directly, which makes the whole cycle deterministically unit-testable.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

from quantbot.core.config import Settings, get_settings
from quantbot.core.constants import (
    EventType,
    ExitReason,
    MarketType,
    PositionSide,
    Side,
    Timeframe,
    TradingMode,
)
from quantbot.core.events import Event, EventBus
from quantbot.core.logging import LoggerMixin
from quantbot.core.models import Candle, Position
from quantbot.data.market_data import MarketDataService
from quantbot.engine.paper_broker import PaperTradingBroker
from quantbot.exchanges.base import ExchangeGateway
from quantbot.execution.executor import OrderExecutor
from quantbot.portfolio.manager import PortfolioManager
from quantbot.risk.engine import RiskEngine
from quantbot.strategies.aggregator import SignalAggregator
from quantbot.strategies.base import BaseStrategy, StrategyContext


class TradingEngine(LoggerMixin):
    """Central orchestrator running strategies, risk and execution per candle."""

    def __init__(
        self,
        *,
        settings: Settings,
        gateway: ExchangeGateway,
        market_data: MarketDataService,
        strategies: list[BaseStrategy],
        aggregator: SignalAggregator,
        risk_engine: RiskEngine,
        portfolio: PortfolioManager,
        executor: OrderExecutor,
        event_bus: EventBus,
    ) -> None:
        self._settings = settings
        self._gateway = gateway
        self._market_data = market_data
        self._strategies = strategies
        self._aggregator = aggregator
        self._risk = risk_engine
        self._portfolio = portfolio
        self._executor = executor
        self._bus = event_bus
        self._running = False
        self._snapshot_task: asyncio.Task[None] | None = None
        self._unsubscribe = None

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        """Connect, warm up data, subscribe to candles and begin trading."""
        self.log.info("engine_starting", mode=self._settings.trading_mode.value)
        # Initialise risk baseline from the (real or simulated) account.
        account = await self._gateway.get_account()
        equity = account.total_equity or self._settings.backtest.initial_capital
        self._risk.set_starting_equity(equity)

        symbols = self._settings.symbols
        timeframes = self._settings.timeframes
        await self._market_data.start(symbols, timeframes)

        self._unsubscribe = self._bus.subscribe(EventType.CANDLE_CLOSED, self._on_candle_event)
        self._running = True
        self._snapshot_task = asyncio.create_task(self._snapshot_loop(), name="equity-snapshots")
        await self._bus.publish(Event(EventType.ENGINE_STARTED, payload={"symbols": symbols}))
        self.log.info("engine_started", symbols=symbols, strategies=len(self._strategies))

    async def stop(self, *, close_positions: bool = False) -> None:
        """Stop the engine, optionally flattening all open positions."""
        self._running = False
        if self._unsubscribe is not None:
            self._unsubscribe()
        if self._snapshot_task is not None:
            self._snapshot_task.cancel()
            try:
                await self._snapshot_task
            except asyncio.CancelledError:
                pass
        await self._market_data.stop()
        if close_positions:
            await self._flatten_all()
        await self._bus.publish(Event(EventType.ENGINE_STOPPED, payload={}))
        self.log.info("engine_stopped")

    # ------------------------------------------------------------------ candle cycle

    async def _on_candle_event(self, event: Event) -> None:
        candle = event.get("candle")
        if isinstance(candle, Candle):
            await self.process_candle(candle)

    async def process_candle(self, candle: Candle) -> Position | None:
        """Run the full decision cycle for one freshly-closed candle."""
        symbol, timeframe, price = candle.symbol, candle.timeframe, candle.close

        # 1. Propagate the new price everywhere that needs it.
        self._portfolio.update_price(symbol, price)
        self._risk.update_price(symbol, price)
        if isinstance(self._gateway, PaperTradingBroker):
            self._gateway.feed_price(symbol, price)

        # 2. Manage an existing position before considering new entries.
        await self._manage_position(symbol, price)

        # 2b. Refresh equity-derived risk state (drawdown high-water mark and the
        #     emergency stop) on EVERY candle — not only on the 60s snapshot timer —
        #     so a fast drawdown halts new entries immediately rather than up to a
        #     minute late.
        self._risk.update_equity(self._portfolio.equity())

        # 3. Run strategies and aggregate their signals.
        signals = await self._run_strategies(candle)
        if not signals:
            return None
        result = self._aggregator.add_many(signals)
        if not result.actionable or result.signal is None:
            return None

        # 4. If we already hold a position, an opposite signal closes it (a sell
        #    exits a long, a buy exits a short); a same-side signal is ignored
        #    (no pyramiding). New entries only happen when flat.
        held = self._portfolio.positions.get(symbol)
        if held is not None and held.is_open:
            opposes = (
                result.signal.side is Side.SELL and held.side is PositionSide.LONG
            ) or (result.signal.side is Side.BUY and held.side is PositionSide.SHORT)
            if opposes:
                await self._executor.close_position(held, exit_price=price, reason=ExitReason.SIGNAL)
            return None

        # 5. Flat: open a long on a buy; open a short on a sell only where shorting
        #    is supported (futures). On spot, a sell with no position is a no-op.
        if result.signal.side is Side.SELL and self._gateway.market is not MarketType.FUTURES:
            return None

        atr = candle.range or None
        position = await self._executor.execute_signal(result.signal, atr=atr)
        return position

    async def _run_strategies(self, candle: Candle) -> list:
        """Build a context and evaluate every strategy matching this candle."""
        series = self._market_data.series(candle.symbol, candle.timeframe)
        if len(series) < 2:
            return []
        ctx = StrategyContext(
            symbol=candle.symbol,
            timeframe=candle.timeframe,
            candle=candle,
            opens=series.opens(),
            highs=series.highs(),
            lows=series.lows(),
            closes=series.closes(),
            volumes=series.volumes(),
        )
        signals = []
        for strategy in self._strategies:
            if not self._strategy_matches(strategy, candle.symbol, candle.timeframe):
                continue
            try:
                signal = await strategy.on_candle(ctx)
            except Exception as exc:  # noqa: BLE001 - one bad strategy must not halt trading
                self.log.error("strategy_error", strategy=strategy.instance_name, error=str(exc))
                continue
            if signal is not None and signal.is_actionable:
                signals.append(signal)
        return signals

    @staticmethod
    def _strategy_matches(strategy: BaseStrategy, symbol: str, timeframe: Timeframe) -> bool:
        symbol_ok = not strategy.symbols or symbol in strategy.symbols
        tf_ok = not strategy.timeframes or timeframe in strategy.timeframes
        return symbol_ok and tf_ok

    # ------------------------------------------------------------------ position management

    async def _manage_position(self, symbol: str, price: Decimal) -> None:
        """Evaluate protective levels for an open position and act on them."""
        position = self._portfolio.positions.get(symbol)
        if position is None or not position.is_open:
            return
        decision = self._risk.stops.evaluate(position, price)

        # Apply protective-level updates first.
        if decision.new_stop_loss is not None:
            self._portfolio.positions.update_stop(symbol, decision.new_stop_loss)
        if decision.new_trailing_stop is not None:
            self._portfolio.positions.update_trailing_stop(symbol, decision.new_trailing_stop)
        if decision.break_even_armed:
            self._portfolio.positions.arm_break_even(symbol)

        if not decision.should_exit:
            return

        if decision.exit_fraction >= Decimal("1"):
            await self._executor.close_position(position, exit_price=price, reason=decision.exit_reason)
        else:
            # Partial take-profit: place a REAL reduce order through the executor.
            # Reducing the books locally (without an order) would desync the bot's
            # view from the actual exchange holding — a live-trading hazard.
            await self._executor.reduce_position(
                position, fraction=decision.exit_fraction, exit_price=price,
                reason=decision.exit_reason, tp_index=decision.triggered_tp_index,
            )

    async def _flatten_all(self) -> None:
        for position in list(self._portfolio.positions.all_open()):
            price = self._portfolio.price_of(position.symbol) or position.entry_price
            from quantbot.core.constants import ExitReason

            await self._executor.close_position(position, exit_price=price, reason=ExitReason.MANUAL)

    # ------------------------------------------------------------------ snapshots

    async def _snapshot_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(60)
                equity = self._portfolio.equity()
                self._risk.update_equity(equity)
                snap = self._portfolio.snapshot()
                await self._bus.publish(
                    Event(EventType.TICKER_UPDATE, payload={"equity": float(snap.equity)}, source="engine")
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - snapshot must never crash the engine
                self.log.error("snapshot_error", error=str(exc))

    @property
    def running(self) -> bool:
        return self._running


def build_engine(
    *,
    settings: Settings | None = None,
    gateway: ExchangeGateway,
    strategies: list[BaseStrategy],
    event_bus: EventBus | None = None,
) -> TradingEngine:
    """Assemble a :class:`TradingEngine` with default wiring from *settings*.

    For paper mode the caller should pass a :class:`PaperTradingBroker` as
    *gateway*; for live mode a real gateway from the exchange factory.
    """
    settings = settings or get_settings()
    bus = event_bus or EventBus()
    portfolio = PortfolioManager(
        starting_balance=settings.backtest.initial_capital,
        quote_asset=settings.quote_asset,
    )
    risk_engine = RiskEngine(settings.risk, event_bus=bus)
    market_data = MarketDataService(gateway, event_bus=bus)
    aggregator = SignalAggregator(settings.aggregator)
    executor = OrderExecutor(
        gateway, risk_engine, portfolio, event_bus=bus,
        commission_rate=settings.backtest.commission,
    )
    return TradingEngine(
        settings=settings,
        gateway=gateway,
        market_data=market_data,
        strategies=strategies,
        aggregator=aggregator,
        risk_engine=risk_engine,
        portfolio=portfolio,
        executor=executor,
        event_bus=bus,
    )


__all__ = ["TradingEngine", "build_engine"]
