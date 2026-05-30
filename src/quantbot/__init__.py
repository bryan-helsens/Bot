"""QuantBot — professional asynchronous cryptocurrency trading bot for Binance.

Top-level package. Submodules are organised by architectural layer:

* :mod:`quantbot.core` — cross-cutting concerns (config, logging, events, models).
* :mod:`quantbot.exchanges` — exchange adapters (Binance spot/futures, websocket).
* :mod:`quantbot.data` — market data services and historical loaders.
* :mod:`quantbot.indicators` — vectorised technical indicators.
* :mod:`quantbot.strategies` — pluggable trading strategies.
* :mod:`quantbot.risk` — the non-bypassable risk-management engine.
* :mod:`quantbot.portfolio` — portfolio, positions and performance tracking.
* :mod:`quantbot.execution` — order execution and lifecycle management.
* :mod:`quantbot.engine` — live/paper trading orchestration.
* :mod:`quantbot.backtest` — event-driven backtesting engine.
* :mod:`quantbot.optimize` — parameter optimisation.
* :mod:`quantbot.scanners` — market scanners.
* :mod:`quantbot.ai` — optional machine-learning signal module.
* :mod:`quantbot.notifications` — Telegram/Discord/Email notifiers.
* :mod:`quantbot.security` — secrets management and auditing.
* :mod:`quantbot.infrastructure` — database and cache adapters.
* :mod:`quantbot.api` — FastAPI monitoring backend.
"""

from __future__ import annotations

__version__ = "1.0.0"
__all__ = ["__version__"]
