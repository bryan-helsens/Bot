"""Runtime assembly: wire a fully-configured engine from settings + config.

Centralises the dependency wiring that the CLI's ``run`` command needs:

* create the exchange gateway (live) or wrap it in the paper broker (paper),
* load strategies from the YAML strategies file (or the configured symbols),
* build the :class:`TradingEngine` with risk, portfolio, executor, market data,
* optionally attach the notification router and persistence.

Keeping this here (not in the CLI) keeps the CLI thin and makes the runtime
reusable from tests and the API process.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from quantbot.core.config import Settings, get_settings
from quantbot.core.constants import TradingMode
from quantbot.core.events import EventBus
from quantbot.core.logging import get_logger
from quantbot.engine.paper_broker import PaperTradingBroker
from quantbot.engine.trading_engine import TradingEngine
from quantbot.exchanges.base import ExchangeGateway
from quantbot.exchanges.factory import create_gateway
from quantbot.execution.executor import OrderExecutor
from quantbot.portfolio.manager import PortfolioManager
from quantbot.risk.engine import RiskEngine
from quantbot.strategies.aggregator import SignalAggregator
from quantbot.strategies.base import BaseStrategy
from quantbot.strategies.registry import get_registry

_log = get_logger(__name__)


@dataclass
class Runtime:
    """A fully-wired runtime ready to start."""

    settings: Settings
    event_bus: EventBus
    gateway: ExchangeGateway
    portfolio: PortfolioManager
    risk_engine: RiskEngine
    executor: OrderExecutor
    engine: TradingEngine
    strategies: list[BaseStrategy]


def load_strategies(settings: Settings) -> list[BaseStrategy]:
    """Load strategy instances from the YAML config, or a sensible default.

    If the strategies file is missing, a default EMA-crossover strategy is
    created for each configured symbol so the bot can run out of the box.
    """
    registry = get_registry()
    registry.load_builtins()
    path = Path(settings.strategies_config)
    if not path.exists():
        _log.warning("strategies_config_missing", path=str(path))
        return [
            registry.create(
                "EMACrossoverStrategy",
                symbols=[symbol],
                timeframes=settings.timeframes,
                instance_name=f"ema_{symbol.lower()}",
            )
            for symbol in settings.symbols
        ]
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries: list[dict[str, Any]] = raw.get("strategies", [])
    strategies = [registry.create_from_config(entry) for entry in entries if entry.get("enabled", True)]
    _log.info("strategies_loaded", count=len(strategies), source=str(path))
    return strategies


def build_runtime(
    settings: Settings | None = None, *, event_bus: EventBus | None = None
) -> Runtime:
    """Assemble a :class:`Runtime` from *settings*."""
    settings = settings or get_settings()
    bus = event_bus or EventBus()

    base_gateway = create_gateway(settings, event_bus=bus)
    if settings.trading_mode is TradingMode.PAPER:
        gateway: ExchangeGateway = PaperTradingBroker(
            base_gateway,
            starting_balance=settings.backtest.initial_capital,
            quote_asset=settings.quote_asset,
            slippage=settings.backtest.slippage,
            commission=settings.backtest.commission,
        )
    else:
        gateway = base_gateway

    portfolio = PortfolioManager(
        starting_balance=settings.backtest.initial_capital,
        quote_asset=settings.quote_asset,
    )
    risk_engine = RiskEngine(settings.risk, event_bus=bus)
    aggregator = SignalAggregator(settings.aggregator)
    executor = OrderExecutor(
        gateway, risk_engine, portfolio, event_bus=bus,
        commission_rate=settings.backtest.commission,
    )
    strategies = load_strategies(settings)

    from quantbot.data.market_data import MarketDataService

    market_data = MarketDataService(gateway, event_bus=bus)
    engine = TradingEngine(
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
    _log.info(
        "runtime_built", mode=settings.trading_mode.value,
        strategies=len(strategies), symbols=settings.symbols,
    )
    return Runtime(
        settings=settings, event_bus=bus, gateway=gateway, portfolio=portfolio,
        risk_engine=risk_engine, executor=executor, engine=engine, strategies=strategies,
    )


async def run_forever(runtime: Runtime) -> None:
    """Connect the gateway, start the engine and run until interrupted."""
    import asyncio
    import signal

    await runtime.gateway.connect()
    await runtime.engine.start()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):  # pragma: no cover - Windows
            pass
    try:
        await stop.wait()
    finally:
        close_positions = runtime.settings.trading_mode is not TradingMode.PAPER
        await runtime.engine.stop(close_positions=False)
        await runtime.gateway.close()
        _ = close_positions


__all__ = ["Runtime", "build_runtime", "load_strategies", "run_forever"]
