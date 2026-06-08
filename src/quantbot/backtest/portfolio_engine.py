"""Multi-symbol portfolio backtesting engine.

The single-symbol :class:`BacktestEngine` replays one ``(symbol, timeframe)``
series. Live, the bot does not run N independent accounts — it runs **one
capital pool** across many coins at once, with the :class:`RiskEngine` capping
the number of concurrent positions (``max_open_trades``) and the total deployed
capital (``max_portfolio_exposure``).

This engine replays a *unified timeline* across many symbols through the **same**
domain components (strategies, :class:`SignalAggregator`, :class:`RiskEngine`,
:class:`PositionManager`, :class:`StopManager`, :class:`SimulatedBroker`) with a
single shared cash balance, so the portfolio-level result is engine-faithful
rather than a separate prototype. It subclasses :class:`BacktestEngine` purely to
reuse its position-management/exit helpers; the only new logic is the
portfolio-wide entry path that builds a :class:`PortfolioView` over *all* open
positions so the exposure and open-trade caps actually bind.

Accounting mirrors the single-symbol engine exactly:

    equity = free_cash + Σ(unrealised PnL of open positions) − Σ(fees accrued)
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np

from quantbot.backtest.broker import Fill
from quantbot.backtest.engine import BacktestEngine
from quantbot.backtest.metrics import BacktestResult, compute_result
from quantbot.core.constants import ExitReason, PositionSide, Side
from quantbot.core.models import Candle, Signal
from quantbot.portfolio.position import PositionManager
from quantbot.risk.engine import PortfolioView


class PortfolioBacktestEngine(BacktestEngine):
    """Replay many symbols through one shared account on a unified timeline."""

    def run_portfolio(self, series: dict[str, list[Candle]]) -> BacktestResult:
        """Backtest *series* (``symbol -> candles``) as a single portfolio.

        All series should share the same timeframe. Bars are processed in
        timestamp order; at each timestamp every symbol with a candle is first
        managed (stops/TP), then evaluated for new entries, with entries
        competing for one shared cash pool under the portfolio risk caps.
        """
        if not series:
            raise ValueError("no series provided")
        timeframe = next(iter(series.values()))[0].timeframe

        for strategy in self._strategies:
            strategy.reset()

        # Per-symbol precomputed arrays + a timestamp -> bar-index map.
        data: dict[str, dict] = {}
        all_times: set = set()
        for symbol, candles in series.items():
            opens = np.array([float(c.open) for c in candles], dtype=np.float64)
            highs = np.array([float(c.high) for c in candles], dtype=np.float64)
            lows = np.array([float(c.low) for c in candles], dtype=np.float64)
            closes = np.array([float(c.close) for c in candles], dtype=np.float64)
            volumes = np.array([float(c.volume) for c in candles], dtype=np.float64)
            tmap = {c.open_time: j for j, c in enumerate(candles)}
            data[symbol] = {
                "candles": candles, "opens": opens, "highs": highs, "lows": lows,
                "closes": closes, "volumes": volumes, "tmap": tmap,
            }
            all_times.update(tmap)
        timeline = sorted(all_times)

        positions = PositionManager()
        initial = float(self._settings.backtest.initial_capital)
        cash = Decimal(str(self._settings.backtest.initial_capital))
        self._risk.set_starting_equity(cash)

        trades: list = []
        entry_bar: dict[str, int] = {}
        equity_curve = [initial]
        timestamps = [timeline[0].isoformat()]
        tf_seconds = float(timeframe.seconds)

        for t in timeline:
            self._sim_time += tf_seconds
            present = [s for s in series if t in data[s]["tmap"]]

            # 1. Mark & manage every open position that trades this bar.
            for symbol in present:
                d = data[symbol]
                candle = d["candles"][d["tmap"][t]]
                position = positions.get(symbol)
                if position is not None and position.is_open:
                    positions.update_mark_price(symbol, candle.close)
                    cash, _ = self._manage_position(
                        positions, position, candle, cash, trades,
                        entry_bar, d["tmap"][t],
                    )

            prices = self._mark_prices(positions, data, t)
            equity = self._portfolio_equity(cash, positions, prices)

            # 2. Collect actionable signals across all present symbols, then fund
            #    the strongest first while the shared budget and caps allow.
            candidates: list[tuple[float, str, Signal, Candle, int]] = []
            for symbol in present:
                d = data[symbol]
                j = d["tmap"][t]
                candle = d["candles"][j]
                signal = self._evaluate_strategies(
                    candle, d["opens"], d["highs"], d["lows"], d["closes"],
                    d["volumes"], j,
                )
                if signal is None:
                    continue
                held = positions.get(symbol)
                if held is not None and held.is_open:
                    opposes = (
                        signal.side is Side.SELL and held.side is PositionSide.LONG
                    ) or (signal.side is Side.BUY and held.side is PositionSide.SHORT)
                    if opposes:
                        cash, _ = self._close(
                            positions, held, candle.close, ExitReason.SIGNAL,
                            cash, trades, entry_bar, j,
                        )
                elif signal.side is Side.BUY or self._allow_short:
                    candidates.append((float(signal.strength), symbol, signal, candle, j))

            candidates.sort(key=lambda c: c[0], reverse=True)  # strongest dip first
            for _, symbol, signal, candle, j in candidates:
                prices = self._mark_prices(positions, data, t)
                equity = self._portfolio_equity(cash, positions, prices)
                cash = self._try_open_portfolio(
                    signal, positions, symbol, cash, candle, entry_bar, j, equity,
                )

            prices = self._mark_prices(positions, data, t)
            equity = self._portfolio_equity(cash, positions, prices)
            equity_curve.append(float(equity))
            timestamps.append(t.isoformat())
            self._risk.update_equity(equity)

        # Liquidate residual positions at each symbol's last available close.
        for symbol in series:
            position = positions.get(symbol)
            if position is not None and position.is_open:
                last = series[symbol][-1]
                cash, _ = self._close(
                    positions, position, last.close, ExitReason.SIGNAL, cash,
                    trades, entry_bar, len(series[symbol]) - 1,
                )
        equity_curve[-1] = float(cash)

        result = compute_result(
            trades=trades,
            equity_curve=equity_curve,
            timestamps=timestamps,
            initial_capital=initial,
            periods_per_year=_periods_per_year(timeframe),
            symbol=f"PORTFOLIO({len(series)})",
            strategy="+".join(s.instance_name for s in self._strategies),
            start=timeline[0].isoformat(),
            end=timeline[-1].isoformat(),
            bars=len(timeline),
        )
        self.log.info("portfolio_backtest_complete", symbols=len(series),
                      **{k: result.summary()[k] for k in
                         ("total_return_pct", "total_trades", "win_rate", "max_drawdown")})
        return result

    # ------------------------------------------------------------------ internals

    def _try_open_portfolio(
        self, signal: Signal, positions: PositionManager, symbol: str,
        cash: Decimal, candle: Candle, entry_bar: dict, i: int, equity: Decimal,
    ) -> Decimal:
        """Open a position sized on portfolio equity, gated by the portfolio caps."""
        # The view reflects *all* open positions so exposure / open-trade caps bind.
        view = PortfolioView(
            equity=equity, available_balance=cash, open_positions=positions.all_open(),
        )
        proposal = _run_risk(self._risk, signal, view, candle.range or None)
        if not proposal.approved or proposal.quantity <= 0:
            return cash
        fill = self._broker.fill(signal.side, proposal.quantity, candle.close)
        # Cannot spend more cash than is free (slippage/spread can nudge the fill
        # notional over the sized notional): scale the quantity to the cash budget.
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
        return cash  # PnL-based: opening does not move cash; fee carried on position

    @staticmethod
    def _mark_prices(positions: PositionManager, data: dict, t) -> dict[str, Decimal]:
        """Current close per open symbol that trades at *t* (fallback: mark price)."""
        prices: dict[str, Decimal] = {}
        for position in positions.all_open():
            d = data.get(position.symbol)
            if d is not None and t in d["tmap"]:
                prices[position.symbol] = d["candles"][d["tmap"][t]].close
            else:
                prices[position.symbol] = position.mark_price
        return prices

    @staticmethod
    def _portfolio_equity(
        cash: Decimal, positions: PositionManager, prices: dict[str, Decimal]
    ) -> Decimal:
        """cash + Σ unrealised PnL − Σ fees accrued (mirrors single-symbol engine)."""
        equity = cash
        for position in positions.all_open():
            price = prices.get(position.symbol, position.mark_price)
            equity += position.unrealized_pnl(price) - position.fees_paid
        return equity


# Reuse the single-symbol module's private helpers (identical decision path).
from quantbot.backtest.engine import _periods_per_year, _run_risk  # noqa: E402

__all__ = ["PortfolioBacktestEngine"]
