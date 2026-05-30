# Mappenstructuur — QuantBot

Volledige, definitieve projectstructuur. Elke module is een Python-package met een
`__init__.py`. Bestanden worden in deze volgorde geïmplementeerd (zie
`IMPLEMENTATION_PLAN.md`).

```
Bot/
├── README.md
├── pyproject.toml                 # Build, deps, tooling (ruff/mypy/pytest) config
├── .env.example                   # Alle configuratievariabelen (gedocumenteerd)
├── .gitignore
├── .dockerignore
├── Makefile                       # Dev shortcuts (lint/test/run/migrate)
├── alembic.ini                    # DB-migratie config
├── docker-compose.yml             # bot + api + postgres + redis + dashboard
├── docker-compose.dev.yml         # Dev-overrides (hot reload, exposed ports)
├── Dockerfile                     # Multi-stage build (bot + api)
│
├── docs/
│   ├── ARCHITECTURE.md            # (1)(4) Architectuur + diagrammen
│   ├── STRUCTURE.md               # (2) Deze file
│   ├── DATABASE.md                # (3) Database-schema
│   ├── IMPLEMENTATION_PLAN.md     # (5) Implementatieplan
│   ├── DEPLOYMENT.md              # (10) Linux/VPS/Cloud
│   ├── USAGE.md                   # (11) Gebruikshandleiding
│   └── OPTIMIZATION.md            # (12) Optimalisatiehandleiding
│
├── src/
│   └── quantbot/
│       ├── __init__.py
│       ├── __main__.py            # `python -m quantbot` entrypoint
│       ├── cli.py                 # Typer CLI (run/backtest/optimize/scan/migrate)
│       │
│       ├── core/                  # Cross-cutting kern
│       │   ├── __init__.py
│       │   ├── config.py          # Pydantic Settings (laadt .env)
│       │   ├── logging.py         # Structured logging (structlog/json)
│       │   ├── events.py          # EventBus (async pub/sub)
│       │   ├── exceptions.py      # Exception-hiërarchie
│       │   ├── constants.py       # Enums: Side, OrderType, Timeframe, Market, ...
│       │   ├── models.py          # Pydantic domain-modellen (Candle/Order/Trade/...)
│       │   ├── supervisor.py      # TaskSupervisor (auto-restart async tasks)
│       │   └── utils.py           # Tijd, decimal-helpers, retry-decorator
│       │
│       ├── exchanges/             # Exchange-adapters (infrastructure)
│       │   ├── __init__.py
│       │   ├── base.py            # ExchangeGateway (ABC) + datatypes
│       │   ├── rate_limiter.py    # Token-bucket weight-based limiter
│       │   ├── websocket.py       # WebSocketManager (reconnect/backoff)
│       │   ├── binance_spot.py    # BinanceSpotGateway
│       │   ├── binance_futures.py # BinanceFuturesGateway
│       │   ├── synchronizer.py    # OrderSynchronizer (reconciliation)
│       │   └── factory.py         # Gateway-factory (spot/futures/testnet)
│       │
│       ├── data/                  # Market data
│       │   ├── __init__.py
│       │   ├── market_data.py     # MarketDataService (rolling buffers)
│       │   ├── aggregator.py      # TimeframeAggregator
│       │   └── historical.py      # HistoricalDataLoader (REST + cache/parquet)
│       │
│       ├── indicators/            # Technische indicatoren (vectorized)
│       │   ├── __init__.py
│       │   ├── trend.py           # EMA, SMA, MACD, Ichimoku, ADX
│       │   ├── momentum.py        # RSI, Stochastic, ROC
│       │   ├── volatility.py      # ATR, Bollinger, Keltner, StdDev
│       │   ├── volume.py          # VWAP, OBV, MFI
│       │   └── levels.py          # Support/Resistance, pivots
│       │
│       ├── strategies/            # Plugin-strategieën
│       │   ├── __init__.py
│       │   ├── base.py            # BaseStrategy (ABC) + StrategyContext
│       │   ├── registry.py        # StrategyRegistry + plugin-loader
│       │   ├── aggregator.py      # SignalAggregator (confluence)
│       │   └── builtin/
│       │       ├── __init__.py
│       │       ├── ema_crossover.py
│       │       ├── sma_crossover.py
│       │       ├── rsi_strategy.py
│       │       ├── macd_strategy.py
│       │       ├── bollinger_bands.py
│       │       ├── vwap_strategy.py
│       │       ├── ichimoku.py
│       │       ├── support_resistance.py
│       │       ├── breakout.py
│       │       ├── mean_reversion.py
│       │       ├── trend_following.py
│       │       ├── momentum.py
│       │       ├── scalping.py
│       │       ├── grid_trading.py
│       │       └── dca.py
│       │
│       ├── risk/                  # Risicobeheer (niet-omzeilbaar)
│       │   ├── __init__.py
│       │   ├── engine.py          # RiskEngine (validatie-pipeline)
│       │   ├── position_sizing.py # Fixed/Kelly/Volatility sizing
│       │   ├── stops.py           # SL/TSL/TP/break-even berekening
│       │   ├── limits.py          # Exposure/loss/drawdown limieten
│       │   ├── correlation.py     # Correlation control
│       │   └── circuit_breaker.py # CircuitBreaker + EmergencyShutdown
│       │
│       ├── portfolio/             # Portfolio & performance
│       │   ├── __init__.py
│       │   ├── manager.py         # PortfolioManager
│       │   ├── position.py        # Position + PositionManager
│       │   └── performance.py     # PerformanceTracker + metrics
│       │
│       ├── execution/             # Order-uitvoering
│       │   ├── __init__.py
│       │   ├── executor.py        # OrderExecutor (risk→exchange)
│       │   └── order_manager.py   # OrderManager (lifecycle/state machine)
│       │
│       ├── engine/                # Application orchestration
│       │   ├── __init__.py
│       │   ├── trading_engine.py  # TradingEngine (live/paper orchestrator)
│       │   └── paper_broker.py    # PaperTradingBroker (simulatie)
│       │
│       ├── ai/                    # Optionele ML-module
│       │   ├── __init__.py
│       │   ├── features.py        # FeatureEngineer
│       │   ├── regime.py          # MarketRegimeDetector
│       │   ├── sentiment.py       # SentimentAnalyzer
│       │   ├── models/
│       │   │   ├── __init__.py
│       │   │   ├── base.py        # BaseModel-interface
│       │   │   ├── xgboost_model.py
│       │   │   ├── random_forest.py
│       │   │   ├── lightgbm_model.py
│       │   │   └── lstm_model.py
│       │   ├── validation.py      # WalkForwardValidator
│       │   └── ai_strategy.py     # AIStrategy (signaal-adapter)
│       │
│       ├── backtest/              # Backtesting-engine
│       │   ├── __init__.py
│       │   ├── engine.py          # BacktestEngine (event-driven)
│       │   ├── broker.py          # SimulatedBroker (commission/slippage/spread)
│       │   ├── metrics.py         # Alle performance-metrics
│       │   └── report.py          # HTML/JSON-rapportgenerator
│       │
│       ├── optimize/              # Parameter-optimalisatie
│       │   ├── __init__.py
│       │   ├── base.py            # Optimizer-interface + search space
│       │   ├── grid_search.py
│       │   ├── random_search.py
│       │   ├── bayesian.py        # Optuna
│       │   ├── walk_forward.py
│       │   └── monte_carlo.py
│       │
│       ├── scanners/              # Markt-scanners
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── trend_scanner.py
│       │   ├── volume_scanner.py
│       │   ├── breakout_scanner.py
│       │   ├── volatility_scanner.py
│       │   ├── liquidity_scanner.py
│       │   └── relative_strength.py
│       │
│       ├── notifications/         # Notificatie-adapters
│       │   ├── __init__.py
│       │   ├── base.py            # Notifier-interface + NotificationRouter
│       │   ├── telegram.py
│       │   ├── discord.py
│       │   └── email.py
│       │
│       ├── security/              # Security & audit
│       │   ├── __init__.py
│       │   ├── secrets.py         # SecretsManager (Fernet)
│       │   ├── audit.py           # AuditLogger
│       │   └── validation.py      # Input-validators
│       │
│       ├── infrastructure/        # DB + cache adapters
│       │   ├── __init__.py
│       │   ├── db/
│       │   │   ├── __init__.py
│       │   │   ├── database.py    # Async engine/session factory
│       │   │   ├── models.py      # SQLAlchemy ORM-modellen
│       │   │   └── repositories.py# Repository-pattern (Trade/Order/Position/...)
│       │   └── cache/
│       │       ├── __init__.py
│       │       └── redis_cache.py # RedisCache + pub/sub
│       │
│       └── api/                   # FastAPI backend
│           ├── __init__.py
│           ├── app.py             # FastAPI-app factory
│           ├── dependencies.py    # DI (auth, sessions)
│           ├── websocket.py       # WS push (realtime updates)
│           ├── schemas.py         # API Pydantic-schemas
│           └── routers/
│               ├── __init__.py
│               ├── trades.py
│               ├── positions.py
│               ├── portfolio.py
│               ├── strategies.py
│               ├── risk.py
│               └── system.py
│
├── dashboard/                     # React frontend (Vite + TS)
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   ├── Dockerfile
│   ├── nginx.conf
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── api/client.ts
│       ├── hooks/useWebSocket.ts
│       └── components/
│           ├── EquityCurve.tsx
│           ├── OpenPositions.tsx
│           ├── ClosedTrades.tsx
│           ├── PnLPanel.tsx
│           ├── DrawdownChart.tsx
│           ├── StrategyPerformance.tsx
│           ├── RiskStats.tsx
│           └── SystemStatus.tsx
│
├── migrations/                    # Alembic
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 0001_initial.py
│
├── config/
│   ├── default.yaml               # Strategie/risk defaults
│   └── strategies.example.yaml    # Voorbeeld actieve-strategieconfig
│
├── scripts/
│   ├── install_vps.sh             # VPS bootstrap
│   ├── download_data.py           # Historische data ophalen
│   └── healthcheck.py             # Container healthcheck
│
└── tests/
    ├── __init__.py
    ├── conftest.py                # Fixtures (mock-exchange, db, redis)
    ├── unit/
    │   ├── test_indicators.py
    │   ├── test_strategies.py
    │   ├── test_risk_engine.py
    │   ├── test_position_sizing.py
    │   ├── test_rate_limiter.py
    │   ├── test_signal_aggregator.py
    │   ├── test_backtest_metrics.py
    │   └── test_config.py
    └── integration/
        ├── test_exchange_gateway.py
        ├── test_trading_engine.py
        ├── test_backtest_engine.py
        ├── test_repositories.py
        └── test_api.py
```

## Aantal kernmodules

- **Exchanges:** 7 bestanden · **Strategieën:** 15 builtin + 4 framework
- **Risk:** 7 · **Indicators:** 5 · **AI:** 11 · **Backtest:** 4 · **Optimize:** 6
- **Scanners:** 7 · **Notifications:** 4 · **API:** 12 · **DB/Cache:** 5
- **Tests:** 13 modules (unit + integratie)
