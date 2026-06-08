#!/usr/bin/env python3
"""Reproducible multi-symbol portfolio backtest on local daily-close JSON data.

Runs the OOS-validated winning config through the real :class:`PortfolioBacktestEngine`
(the same RiskEngine/PositionManager/broker as live) over a basket of coins, and
prints full + out-of-sample results against an equal-weight buy & hold benchmark.

Usage::

    python scripts/backtest_portfolio.py                # all coins in data/all
    python scripts/backtest_portfolio.py btc eth bnb    # a chosen basket
    python scripts/backtest_portfolio.py --oos 0.55     # OOS split fraction

Data format: ``data/all/<sym>_daily_close.json`` = ``[["YYYY-MM-DD", close], ...]``.
Only daily closes are available, so OHLC are set equal to the close (intrabar
stop/TP precision is therefore limited — the documented daily-data caveat).
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

# Example config. NOTE: NOT proven profitable — under realistic stop fills (the
# engine default) this loses on daily data. See docs/REALISTIC_FILLS_REPORT.md.
WINNING = {
    "risk_per_trade": Decimal("0.015"),
    "max_portfolio_exposure": Decimal("0.80"),
    "max_open_trades": 5,
    "stop": Decimal("0.08"),
    "target": Decimal("0.06"),
    "trail": Decimal("0.15"),
    "oversold": 35.0,
    "overbought": 70.0,
    "rsi_period": 14,
}


def _load_candles(path: str, symbol: str):
    from quantbot.core.constants import Timeframe
    from quantbot.core.models import Candle

    out = []
    for date_str, close in json.load(open(path)):
        d = datetime.fromisoformat(date_str).replace(tzinfo=UTC)
        p = Decimal(str(close))
        out.append(Candle(
            symbol=symbol, timeframe=Timeframe.D1, open_time=d,
            close_time=d + timedelta(days=1), open=p, high=p, low=p, close=p,
            volume=Decimal("100"),
        ))
    return out


def _settings():
    from quantbot.core.config import (
        AggregatorSettings, BacktestSettings, RiskSettings, Settings,
    )
    from quantbot.core.constants import MarketType, SizingMethod

    s = Settings(_env_file=None)
    s.binance.market = MarketType.SPOT
    s.risk = RiskSettings(
        sizing_method=SizingMethod.RISK, risk_per_trade=WINNING["risk_per_trade"],
        max_open_trades=WINNING["max_open_trades"], max_exposure_per_coin=Decimal("1.0"),
        max_portfolio_exposure=WINNING["max_portfolio_exposure"],
        default_stop_loss_pct=WINNING["stop"], trailing_stop_pct=WINNING["trail"],
        break_even_trigger_pct=Decimal("0"),
        take_profit_levels=[(WINNING["target"], Decimal("1.0"))],
        max_daily_loss=Decimal("0.95"), max_weekly_loss=Decimal("0.95"),
        max_drawdown=Decimal("0.95"), max_correlation=Decimal("1.0"),
        circuit_breaker_losses=999, emergency_stop_enabled=False,
    )
    s.aggregator = AggregatorSettings(min_consensus=1, min_strength=0.5, window_seconds=60)
    s.backtest = BacktestSettings(
        initial_capital=Decimal("10000"), commission=Decimal("0.001"),
        slippage=Decimal("0.0005"), spread=Decimal("0.0002"),
    )
    return s


def _run(series, oos_frac=None):
    from quantbot.backtest.portfolio_engine import PortfolioBacktestEngine
    from quantbot.core.constants import Timeframe
    from quantbot.strategies.builtin.rsi_strategy import RSIStrategy

    if oos_frac:
        series = {k: v[int(len(v) * oos_frac):] for k, v in series.items()}
        series = {k: v for k, v in series.items() if len(v) > 20}
    strat = RSIStrategy(symbols=[], timeframes=[Timeframe.D1], params={
        "period": WINNING["rsi_period"], "oversold": WINNING["oversold"],
        "overbought": WINNING["overbought"]})
    sm = PortfolioBacktestEngine(
        settings=_settings(), strategies=[strat], warmup=2).run_portfolio(series).summary()
    return sm


def _buyhold(series, oos_frac=None):
    rets = []
    for candles in series.values():
        c = candles[int(len(candles) * oos_frac):] if oos_frac else candles
        if len(c) >= 2:
            rets.append(float(c[-1].close) / float(c[0].close) - 1)
    return sum(rets) / len(rets) * 100 if rets else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbols", nargs="*", help="coin tickers (default: all in data/all)")
    parser.add_argument("--oos", type=float, default=0.55, help="OOS split fraction")
    parser.add_argument("--data", default="data/all", help="data directory")
    args = parser.parse_args()

    from quantbot.core.logging import configure_logging
    configure_logging(level="ERROR")

    if args.symbols:
        paths = [os.path.join(args.data, f"{s.lower()}_daily_close.json") for s in args.symbols]
    else:
        paths = sorted(glob.glob(os.path.join(args.data, "*_daily_close.json")))
    series = {}
    for p in paths:
        if not os.path.exists(p):
            print(f"  (skip missing {p})")
            continue
        sym = os.path.basename(p).replace("_daily_close.json", "").upper() + "USDT"
        series[sym] = _load_candles(p, sym)

    print(f"Portfolio backtest — {len(series)} coins, config: rpt"
          f"{float(WINNING['risk_per_trade']):.1%} exp{float(WINNING['max_portfolio_exposure']):.0%} "
          f"pos{WINNING['max_open_trades']} os{WINNING['oversold']:.0f} "
          f"tgt{float(WINNING['target']):.0%} stop{float(WINNING['stop']):.0%}")
    print("=" * 84)
    for label, oos in [("FULL", None), (f"OOS ({1 - args.oos:.0%} unseen)", args.oos)]:
        sm = _run(series, oos_frac=oos)
        bh = _buyhold(series, oos_frac=oos)
        ret = sm["total_return_pct"] * 100
        print(f"{label:18s} ret={ret:+7.1f}%  CAGR={sm['cagr'] * 100:+6.1f}%  "
              f"DD={sm['max_drawdown'] * 100:3.0f}%  trades={sm['total_trades']:>3}  "
              f"win={sm['win_rate'] * 100:.0f}%  | buy&hold={bh:+.1f}%  edge={ret - bh:+.1f}pp")


if __name__ == "__main__":
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
    main()
