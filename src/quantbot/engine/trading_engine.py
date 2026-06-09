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
from quantbot.exchanges.base import ExchangeGateway, OrderUpdate
from quantbot.exchanges.synchronizer import OrderSynchronizer
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
        self._user_task: asyncio.Task[None] | None = None
        self._synchronizer = OrderSynchronizer(gateway)
        self._unsubscribe = None

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        """Connect, warm up data, subscribe to candles and begin trading."""
        self.log.info("engine_starting", mode=self._settings.trading_mode.value)
        # Baseline the risk engine from the bot's OWN tracked equity — the exact
        # quantity `update_equity` feeds it later — NOT the raw exchange wallet. A
        # pre-funded testnet wallet (large faucet balance) vs the bot's configured
        # capital would otherwise look like a ~100% instant drawdown and trip the
        # emergency stop the moment trading starts.
        try:
            account = await self._gateway.get_account()
            self.log.info("account_loaded", wallet_equity=float(account.total_equity))
        except Exception as exc:  # noqa: BLE001 - account fetch is informational only
            self.log.warning("account_fetch_failed", error=str(exc))
        self._risk.set_starting_equity(self._portfolio.equity())

        symbols = self._settings.symbols
        timeframes = self._settings.timeframes
        await self._market_data.start(symbols, timeframes)

        # Reconcile local books against the exchange before trading: a stop may have
        # fired or an order filled while we were down/disconnected.
        await self._reconcile_with_exchange()

        self._unsubscribe = self._bus.subscribe(EventType.CANDLE_CLOSED, self._on_candle_event)
        self._running = True
        self._snapshot_task = asyncio.create_task(self._snapshot_loop(), name="equity-snapshots")
        # Consume the authenticated user-data stream so exchange-side fills (notably
        # a resting protective stop firing mid-candle) are reflected immediately.
        self._user_task = asyncio.create_task(self._user_event_loop(), name="user-events")
        await self._bus.publish(Event(EventType.ENGINE_STARTED, payload={"symbols": symbols}))
        self.log.info("engine_started", symbols=symbols, strategies=len(self._strategies))

    async def stop(self, *, close_positions: bool = False) -> None:
        """Stop the engine, optionally flattening all open positions."""
        self._running = False
        if self._unsubscribe is not None:
            self._unsubscribe()
        for task in (self._snapshot_task, self._user_task):
            if task is not None:
                task.cancel()
                try:
                    await task
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

        atr = self._atr_for(candle)
        position = await self._executor.execute_signal(result.signal, atr=atr)
        return position

    def _atr_for(self, candle: Candle) -> Decimal | None:
        """True ATR(14) from the series for volatility sizing.

        Falls back to the single-candle range only when there is too little history
        (a one-bar high-low is a noisy, usually-too-small volatility estimate that
        produces oversized positions on quiet bars).
        """
        series = self._market_data.series(candle.symbol, candle.timeframe)
        if len(series) < 16:
            return candle.range or None
        import numpy as np

        from quantbot.indicators.volatility import atr as atr_fn

        try:
            values = atr_fn(series.highs(), series.lows(), series.closes(), period=14)
        except Exception:  # noqa: BLE001 - any indicator failure -> safe fallback
            return candle.range or None
        last = values[-1]
        if last is None or np.isnan(last) or last <= 0:
            return candle.range or None
        return Decimal(str(float(last)))

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

    # ------------------------------------------------------------------ exchange reconciliation

    async def _reconcile_with_exchange(self) -> None:
        """Reconcile local orders/positions with the exchange on (re)connect.

        A position the exchange has already closed (a stop that fired while we were
        disconnected) is reflected in the books so the engine stops managing a
        phantom position. Never places orders — only updates bookkeeping.
        """
        try:
            local_orders = [
                o for o in self._executor.orders.all_orders() if not o.status.is_terminal
            ]
            local_positions = list(self._portfolio.positions.all_open())
            result = await self._synchronizer.reconcile(
                local_orders, local_positions, symbols=self._settings.symbols
            )
            for position in result.stale_positions:
                held = self._portfolio.positions.get(position.symbol)
                if held is not None and held.is_open:
                    price = (
                        self._portfolio.price_of(position.symbol)
                        or held.mark_price or held.entry_price
                    )
                    await self._executor.apply_external_close(
                        held, fill_price=price, reason=ExitReason.MANUAL
                    )
            if result.orphan_positions or result.orphan_orders:
                self.log.warning(
                    "reconcile_orphans_detected",
                    positions=len(result.orphan_positions), orders=len(result.orphan_orders),
                )
        except Exception as exc:  # noqa: BLE001 - reconciliation must never crash startup
            self.log.error("reconcile_failed", error=str(exc))

    async def _user_event_loop(self) -> None:
        """Apply exchange-side order fills (a fired stop) to the local books."""
        try:
            async for event in self._gateway.stream_user_events():
                try:
                    update = self._gateway.parse_user_event(event)
                except Exception as exc:  # noqa: BLE001 - one bad event must not stop the stream
                    self.log.warning("user_event_parse_error", error=str(exc))
                    continue
                if update is not None:
                    await self._on_order_update(update)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - log and exit; reconnect handled elsewhere
            self.log.error("user_event_loop_error", error=str(exc))

    async def _on_order_update(self, update: OrderUpdate) -> None:
        """React to an exchange order update — reconcile a fired protective stop."""
        from quantbot.core.constants import OrderStatus

        if update.filled_qty <= 0 or update.status not in (
            OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED
        ):
            return
        # A resting protective stop firing is the critical case: we placed it as a
        # working order and would otherwise never learn it executed. Match by id.
        for position in list(self._portfolio.positions.all_open()):
            if position.meta.get("stop_order_id") == update.client_order_id:
                price = (
                    update.fill_price or position.stop_loss
                    or position.mark_price or position.entry_price
                )
                await self._executor.apply_external_close(
                    position, fill_price=price, fee=update.commission,
                    reason=ExitReason.STOP_LOSS,
                )
                return

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
