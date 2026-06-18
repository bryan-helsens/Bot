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
    SignalType,
    Timeframe,
    TradingMode,
)
from quantbot.core.events import Event, EventBus
from quantbot.core.logging import LoggerMixin
from quantbot.core.models import Candle, Position, Signal, utcnow
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
        self._paused = False  # when True: manage existing positions but open no new ones
        self._muted: set[str] = set()  # symbols excluded from NEW automated entries
        self._last_loss_at: dict[str, datetime] = {}  # symbol -> time of last losing exit
        self._last_candle_at: datetime | None = None
        self._last_trade_at: datetime | None = None
        self._snapshot_task: asyncio.Task[None] | None = None
        self._user_task: asyncio.Task[None] | None = None
        self._synchronizer = OrderSynchronizer(gateway)
        self._unsubscribe = None

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        """Connect, warm up data, subscribe to candles and begin trading."""
        self.log.info("engine_starting", mode=self._settings.trading_mode.value)
        # Restore persisted state (cash, positions, equity curve) so a restart
        # resumes where it left off. Done before the risk baseline + reconcile so
        # restored positions are checked against the exchange.
        from quantbot.engine.state_store import load_state

        if load_state(self._portfolio, self._settings.state_file):
            self.log.info(
                "state_restored", positions=self._portfolio.positions.open_count,
                equity=float(self._portfolio.equity()),
            )
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

        # Warn up-front which configured coins can't be traded with this capital
        # (their exchange minimum order exceeds the bot's typical order size).
        await self._warn_unaffordable_symbols()

        self._unsubscribe = self._bus.subscribe(EventType.CANDLE_CLOSED, self._on_candle_event)
        self._bus.subscribe(EventType.TRADE_OPENED, self._on_trade_event)
        self._bus.subscribe(EventType.TRADE_CLOSED, self._on_trade_event)
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
        self._save_state()  # persist final state for a seamless next start
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
        self._last_candle_at = utcnow()  # heartbeat

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

        # 4. If we already hold a position: by default we let it run to its
        #    TP/SL/trailing exit rather than closing on every opposite signal —
        #    those signal-flips were tiny round-trips that bled fees. Only close
        #    here when explicitly enabled (RISK__EXIT_ON_OPPOSITE_SIGNAL=true).
        #    A same-side signal is always ignored (no pyramiding).
        held = self._portfolio.positions.get(symbol)
        if held is not None and held.is_open:
            opposes = (
                result.signal.side is Side.SELL and held.side is PositionSide.LONG
            ) or (result.signal.side is Side.BUY and held.side is PositionSide.SHORT)
            if opposes and self._settings.risk.exit_on_opposite_signal:
                await self._executor.close_position(held, exit_price=price, reason=ExitReason.SIGNAL)
            return None

        # 5. Flat: open a long on a buy; open a short on a sell only where shorting
        #    is supported (futures). On spot, a sell with no position is a no-op.
        if result.signal.side is Side.SELL and self._gateway.market is not MarketType.FUTURES:
            return None
        if self._paused:
            return None  # paused: keep managing existing positions, open no new ones
        if symbol in self._muted:
            return None  # this coin is muted: no automated entries (manual still allowed)
        if self._in_reentry_cooldown(symbol):
            self.log.info("entry_skipped_cooldown", symbol=symbol)
            return None  # just lost on this coin — wait before re-entering

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

    # ------------------------------------------------------------------ control & health

    @property
    def paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        """Stop opening NEW positions; existing ones keep being managed."""
        self._paused = True
        self.log.info("trading_paused")

    def resume_trading(self) -> None:
        self._paused = False
        self.log.info("trading_resumed")

    async def close_all(self) -> int:
        """Market-close every open position. Returns how many were closed."""
        positions = list(self._portfolio.positions.all_open())
        for position in positions:
            price = self._latest_price(position.symbol) or position.mark_price or position.entry_price
            try:
                await self._executor.close_position(position, exit_price=price, reason=ExitReason.MANUAL)
            except Exception as exc:  # noqa: BLE001 - keep closing the rest
                self.log.error("close_all_failed", symbol=position.symbol, error=str(exc))
        return len(positions)

    async def close_symbol(self, symbol: str) -> dict:
        """Market-close a single open position."""
        position = self._portfolio.positions.get(symbol)
        if position is None or not position.is_open:
            return {"ok": False, "detail": f"No open position for {symbol}"}
        price = self._latest_price(symbol) or position.mark_price or position.entry_price
        await self._executor.close_position(position, exit_price=price, reason=ExitReason.MANUAL)
        return {"ok": True, "detail": f"Closed {symbol} @ {price}"}

    def adjust_capital(self, amount: Decimal) -> dict:
        """Record a deposit/withdrawal of capital (NOT profit) and persist it."""
        try:
            equity = self._portfolio.adjust_capital(amount)
        except ValueError as exc:
            return {"ok": False, "detail": str(exc)}
        self._risk.update_equity(equity)  # refresh drawdown high-water mark
        self._save_state()
        verb = "Deposited" if amount >= 0 else "Withdrew"
        return {"ok": True, "detail": f"{verb} {abs(amount)} — equity now {equity:.2f}"}

    async def _on_trade_event(self, event: Event) -> None:
        self._last_trade_at = utcnow()
        # Record losing exits so we can cool down before re-entering the same coin.
        if event.type is EventType.TRADE_CLOSED:
            payload = event.payload or {}
            symbol = payload.get("symbol")
            try:
                pnl = Decimal(str(payload.get("net_pnl", "0")))
            except (ArithmeticError, ValueError, TypeError):
                pnl = Decimal("0")
            if symbol and pnl < 0:
                self._last_loss_at[symbol] = utcnow()

    def _in_reentry_cooldown(self, symbol: str) -> bool:
        """True if *symbol* had a losing exit within the configured cooldown."""
        cooldown = self._settings.risk.reentry_cooldown_seconds
        if cooldown <= 0:
            return False
        last_loss = self._last_loss_at.get(symbol)
        if last_loss is None:
            return False
        return (utcnow() - last_loss).total_seconds() < cooldown

    def coin_market_snapshot(self, symbol: str) -> dict:
        """Recent closes (+ timestamps) and current RSI(14) for a coin."""
        import numpy as np

        from quantbot.indicators.momentum import rsi as rsi_fn

        if not self._settings.timeframes:
            return {"rsi": None, "prices": [], "times": [], "price_timeframe": None}
        tf = min(self._settings.timeframes, key=lambda t: t.seconds)
        series = self._market_data.series(symbol, tf)
        candles = series.candles(60)
        prices = [round(float(c.close), 8) for c in candles]
        times = [c.open_time.isoformat() for c in candles]
        rsi_val: float | None = None
        closes = series.closes()
        if len(closes) >= 15:
            try:
                last = rsi_fn(closes, period=14)[-1]
                if last is not None and not np.isnan(last):
                    rsi_val = round(float(last), 1)
            except Exception:  # noqa: BLE001
                rsi_val = None
        return {"rsi": rsi_val, "prices": prices, "times": times, "price_timeframe": tf.value}

    # ------------------------------------------------------------------ per-coin mute

    def muted_symbols(self) -> list[str]:
        """Symbols currently excluded from new automated entries."""
        return sorted(self._muted)

    def mute_symbol(self, symbol: str) -> dict:
        """Stop the bot opening NEW automated positions on *symbol* (manual still works)."""
        symbol = symbol.upper()
        self._muted.add(symbol)
        self.log.info("symbol_muted", symbol=symbol)
        return {"ok": True, "detail": f"{symbol} muted — no new automated entries"}

    def unmute_symbol(self, symbol: str) -> dict:
        """Re-enable automated entries on *symbol*."""
        symbol = symbol.upper()
        self._muted.discard(symbol)
        self.log.info("symbol_unmuted", symbol=symbol)
        return {"ok": True, "detail": f"{symbol} unmuted — automated entries allowed"}

    # ------------------------------------------------------------------ market scanner

    def market_scanner(self) -> list[dict]:
        """Live per-coin snapshot for the dashboard scanner.

        For every warmed-up symbol: latest price, RSI(14), fast/slow EMA and their
        relationship, plus a coarse ``signal`` label so you can see at a glance WHY
        the bot is (not yet) trading a coin and which ones are closest to an entry.
        """
        import numpy as np

        from quantbot.indicators.momentum import rsi as rsi_fn
        from quantbot.indicators.trend import ema as ema_fn

        if not self._settings.timeframes:
            return []
        tf = min(self._settings.timeframes, key=lambda t: t.seconds)
        rows: list[dict] = []
        for symbol in self._market_data.active_symbols():
            series = self._market_data.series(symbol, tf)
            closes = series.closes()
            if len(closes) < 22:
                continue
            price = float(closes[-1])

            def _last(fn, *a) -> float | None:
                try:
                    val = fn(*a)[-1]
                    return None if val is None or np.isnan(val) else float(val)
                except Exception:  # noqa: BLE001 - indicator robustness
                    return None

            rsi_val = _last(rsi_fn, closes, 14)
            ema_fast = _last(ema_fn, closes, 9)
            ema_slow = _last(ema_fn, closes, 21)

            trend = None
            gap_pct = None
            if ema_fast is not None and ema_slow is not None and price:
                trend = "up" if ema_fast >= ema_slow else "down"
                gap_pct = round((ema_fast - ema_slow) / price * 100, 3)

            # Coarse signal label, mirroring the shipped strategies' logic.
            signal = "neutral"
            if rsi_val is not None:
                if rsi_val < 30:
                    signal = "oversold"
                elif rsi_val < 40:
                    signal = "dip-watch"
                elif rsi_val > 70:
                    signal = "overbought"
            if trend == "up" and gap_pct is not None and 0 < gap_pct < 0.15:
                signal = "trend-cross"

            pos = self._portfolio.positions.get(symbol)
            rows.append({
                "symbol": symbol,
                "price": round(price, 8),
                "rsi": None if rsi_val is None else round(rsi_val, 1),
                "ema_fast": None if ema_fast is None else round(ema_fast, 8),
                "ema_slow": None if ema_slow is None else round(ema_slow, 8),
                "trend": trend,
                "ema_gap_pct": gap_pct,
                "signal": signal,
                "timeframe": tf.value,
                "has_position": bool(pos is not None and pos.is_open),
                "muted": symbol in self._muted,
            })
        rows.sort(key=lambda r: (r["rsi"] if r["rsi"] is not None else 999))
        return rows

    # ------------------------------------------------------------------ account overview

    async def account_overview(self) -> dict:
        """Real exchange balances per asset + bot-equity vs wallet-equity.

        The wallet is the exchange truth (on testnet: faucet play-money); the bot's
        equity is its own tracked capital. They legitimately differ — this surfaces
        both side by side so the difference is never mistaken for a bug.
        """
        assets: list[dict] = []
        wallet_equity = None
        quote = self._settings.quote_asset
        try:
            account = await self._gateway.get_account()
            wallet_equity = float(account.total_equity)
            for asset, bal in sorted(account.balances.items()):
                total = float(bal.total)
                if total <= 0:
                    continue
                assets.append({
                    "asset": asset,
                    "free": float(bal.free),
                    "locked": float(bal.locked),
                    "total": total,
                })
        except Exception as exc:  # noqa: BLE001 - account fetch is best-effort
            self.log.warning("account_overview_failed", error=str(exc))
        return {
            "quote_asset": quote,
            "wallet_equity": wallet_equity,
            "bot_equity": float(self._portfolio.equity()),
            "bot_cash": float(self._portfolio.cash),
            "assets": assets,
        }

    def heartbeat(self) -> dict:
        """Liveness signals for the dashboard health panel."""
        now = utcnow()
        last_candle_age = (now - self._last_candle_at).total_seconds() if self._last_candle_at else None
        # A 5m candle only closes every 5 min, so "stale" must be relative to the
        # smallest configured timeframe — not a fixed 3 min (which false-alarms).
        tf_secs = min((tf.seconds for tf in self._settings.timeframes), default=300)
        stale_threshold = tf_secs * 2.5 + 60
        return {
            "paused": self._paused,
            "last_candle_age": last_candle_age,
            "last_trade_age": (now - self._last_trade_at).total_seconds() if self._last_trade_at else None,
            "active_streams": self._market_data.stream_count(),
            "open_positions": self._portfolio.positions.open_count,
            "candle_stale": last_candle_age is not None and last_candle_age > stale_threshold,
        }

    # ------------------------------------------------------------------ manual / test orders

    def _latest_price(self, symbol: str) -> Decimal | None:
        """Most recent known price for *symbol* (latest candle, then mark price)."""
        for timeframe in self._settings.timeframes:
            series = self._market_data.series(symbol, timeframe)
            if series.last is not None:
                return series.last.close
        return self._portfolio.price_of(symbol)

    async def submit_manual_order(self, symbol: str, side: Side) -> dict:
        """Place a manual market order through the FULL risk + execution path.

        Used by the dashboard's test button to exercise the whole pipeline on
        demand (no waiting for a strategy signal). A buy opens a long; a sell closes
        an open long (or opens a short on futures). Goes through the RiskEngine like
        any other order — it can be adjusted or rejected.
        """
        price = self._latest_price(symbol)
        if price is None or price <= 0:
            return {"ok": False, "detail": f"No live price for {symbol} yet — wait for data."}

        held = self._portfolio.positions.get(symbol)
        if held is not None and held.is_open:
            opposes = (
                side is Side.SELL and held.side is PositionSide.LONG
            ) or (side is Side.BUY and held.side is PositionSide.SHORT)
            if opposes:
                await self._executor.close_position(held, exit_price=price, reason=ExitReason.MANUAL)
                return {"ok": True, "detail": f"Closed {symbol} @ {price}"}
            return {"ok": False, "detail": f"Already holding {symbol}; opposite side closes it."}

        if side is Side.SELL and self._gateway.market is not MarketType.FUTURES:
            return {"ok": False, "detail": f"No {symbol} position to sell (spot)."}

        signal = Signal(
            strategy="manual", symbol=symbol,
            timeframe=self._settings.timeframes[0] if self._settings.timeframes else Timeframe.M5,
            side=side, signal_type=SignalType.ENTRY, strength=1.0, price=price,
            reason="manual_test",
        )
        position = await self._executor.execute_signal(signal, atr=None)
        if position is None:
            return {"ok": False, "detail": f"{symbol} {side.value} rejected by risk engine (see logs)."}
        return {"ok": True, "detail": f"Opened {symbol} {side.value} {position.quantity} @ {position.entry_price}"}

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

        # An exit failure on ONE symbol must not crash the whole candle cycle (other
        # positions still need managing); log it and move on.
        try:
            if decision.exit_fraction >= Decimal("1"):
                await self._executor.close_position(position, exit_price=price, reason=decision.exit_reason)
            else:
                await self._executor.reduce_position(
                    position, fraction=decision.exit_fraction, exit_price=price,
                    reason=decision.exit_reason, tp_index=decision.triggered_tp_index,
                )
        except Exception as exc:  # noqa: BLE001 - isolate per-symbol exit failures
            self.log.error("position_exit_failed", symbol=symbol, error=str(exc))

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
            # Query ONLY symbols that actually warmed up. Asking the exchange about
            # a coin it doesn't list (e.g. MATIC/FTM/MKR/RNDR off the testnet)
            # raises -1121 Invalid symbol and previously aborted the whole pass.
            symbols = self._market_data.active_symbols() or list(self._settings.symbols)
            result = await self._synchronizer.reconcile(
                local_orders, local_positions, symbols=symbols
            )
            # Only act on "stale" positions for FUTURES, where get_positions() is
            # authoritative. On SPOT it always returns [] (spot has no position
            # concept — holdings are balances), so EVERY restored position would
            # look stale and get wrongly closed on restart. Spot positions are
            # verified against base-asset balances instead.
            if self._gateway.market is MarketType.FUTURES:
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
            else:
                await self._reconcile_spot_positions()
            if result.orphan_positions or result.orphan_orders:
                self.log.warning(
                    "reconcile_orphans_detected",
                    positions=len(result.orphan_positions), orders=len(result.orphan_orders),
                )
        except Exception as exc:  # noqa: BLE001 - reconciliation must never crash startup
            self.log.error("reconcile_failed", error=str(exc))

    async def _warn_unaffordable_symbols(self) -> None:
        """Log which configured symbols can't meet the exchange minimum order size.

        Typical order notional = equity * risk_per_trade / stop. A symbol whose
        MIN_NOTIONAL exceeds that will have every entry either bumped up (slightly
        more risk) or skipped — better to know that at startup than wonder later
        why a coin never trades.
        """
        try:
            equity = self._portfolio.equity()
            cfg = self._settings.risk
            typical = equity * cfg.risk_per_trade / cfg.default_stop_loss_pct
            too_small: list[str] = []
            # Only warn about coins that actually warmed up; unlisted ones were
            # already skipped (warmup_skip_symbol) and never trade anyway.
            symbols = self._market_data.active_symbols() or list(self._settings.symbols)
            for symbol in symbols:
                try:
                    info = await self._gateway.get_symbol_info(symbol)
                except Exception:  # noqa: BLE001 - unknown symbol: already skipped elsewhere
                    continue
                if info.min_notional > 0 and info.min_notional > typical:
                    too_small.append(f"{symbol}(min {info.min_notional})")
            if too_small:
                self.log.warning(
                    "symbols_below_min_notional",
                    typical_order=float(typical),
                    symbols=", ".join(too_small),
                    hint="orders for these are bumped to the minimum or skipped; "
                         "raise RISK__RISK_PER_TRADE or remove them from SYMBOLS",
                )
        except Exception as exc:  # noqa: BLE001 - advisory only, never block startup
            self.log.debug("min_notional_check_skipped", error=str(exc))

    async def _reconcile_spot_positions(self) -> None:
        """Verify spot positions against base-asset balances; close locally ONLY
        those whose balance is effectively gone (e.g. sold manually). Conservative
        on purpose — it must never close a position we genuinely still hold."""
        try:
            account = await self._gateway.get_account()
        except Exception as exc:  # noqa: BLE001 - skip if the account can't be read
            self.log.warning("spot_reconcile_skipped", error=str(exc))
            return
        quote = self._settings.quote_asset
        for position in list(self._portfolio.positions.all_open()):
            sym = position.symbol
            base = sym[: -len(quote)] if sym.endswith(quote) else sym
            held = account.balance_of(base).total if base else position.quantity
            # We hold <1% of what the books say -> the position is really gone.
            if held < position.quantity * Decimal("0.01"):
                price = self._portfolio.price_of(sym) or position.mark_price or position.entry_price
                self.log.info("spot_position_gone", symbol=sym, held=float(held),
                              expected=float(position.quantity))
                await self._executor.apply_external_close(position, fill_price=price, reason=ExitReason.MANUAL)

    async def _user_event_loop(self) -> None:
        """Apply exchange-side order fills (a fired stop) to the local books.

        Reconnects with backoff if the user-data stream errors (e.g. a flaky
        listen-key). If it keeps failing it degrades gracefully — the local
        StopManager still enforces stops on each candle, so trading is unaffected;
        only the live exchange-fill reconciliation is unavailable.
        """
        delay = 2.0
        failures = 0
        while self._running:
            got_event = False
            try:
                async for event in self._gateway.stream_user_events():
                    got_event = True
                    failures, delay = 0, 2.0  # healthy stream resets the backoff
                    try:
                        update = self._gateway.parse_user_event(event)
                    except Exception as exc:  # noqa: BLE001 - one bad event must not stop the stream
                        self.log.warning("user_event_parse_error", error=str(exc))
                        continue
                    if update is not None:
                        await self._on_order_update(update)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - reconnect with backoff
                failures += 1
                if failures == 1:
                    self.log.warning("user_event_stream_error", error=str(exc))
            else:
                # Stream ended without error. If it never yielded anything (no user
                # stream available, e.g. on this testnet), count it toward giving up
                # rather than busy-reconnecting.
                if not got_event:
                    failures += 1
            if failures >= 5:
                self.log.warning(
                    "user_event_stream_unavailable",
                    detail="exchange-fill reconciliation disabled; the local "
                           "StopManager remains the backstop",
                )
                return
            if failures:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)

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
                self._save_state()
                await self._bus.publish(
                    Event(EventType.TICKER_UPDATE, payload={"equity": float(snap.equity)}, source="engine")
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - snapshot must never crash the engine
                self.log.error("snapshot_error", error=str(exc))

    def _save_state(self) -> None:
        """Persist account state so a restart resumes seamlessly (best-effort)."""
        from quantbot.engine.state_store import save_state

        save_state(self._portfolio, self._settings.state_file)

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
