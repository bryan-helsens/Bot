# Systeemarchitectuur — QuantBot

> Professionele, asynchrone, modulaire cryptocurrency trading bot voor Binance
> (Spot, Futures, Testnet). Productieklaar, schaalbaar, veilig en getest.

---

## 1. Architectuuroverzicht

QuantBot is opgebouwd volgens een **event-driven, gelaagde (layered) architectuur**
met een centrale asynchrone `asyncio`-event loop. Elke laag heeft één
verantwoordelijkheid (Single Responsibility) en communiceert via duidelijk
gedefinieerde interfaces (Ports & Adapters / Hexagonal pattern). Hierdoor zijn
exchanges, strategieën, notificaties en opslag onderling vervangbaar zonder de
kerncode aan te raken.

### Kernprincipes

| Principe | Toepassing |
|----------|-----------|
| **Hexagonal / Ports & Adapters** | De `core` kent geen Binance-specifieke details; alles loopt via `ExchangeGateway`-interfaces. |
| **Plugin-architectuur** | Strategieën worden dynamisch geladen via een `StrategyRegistry` + entry points. Nieuwe strategie = nieuw bestand, geen kernwijziging. |
| **Event-driven** | Een interne `EventBus` koppelt market-data, signalen, orders en risk-events losjes. |
| **Fail-safe by design** | Elke externe call is omgeven door retries, circuit breakers en een globale `EmergencyShutdown`. |
| **Risk-first** | Géén order bereikt de exchange zonder validatie door de `RiskEngine`. AI/strategie produceert alléén signalen. |
| **12-factor** | Config via env, stateless processen, logs als event-streams, disposability. |

---

## 2. Lagen (Layers)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  PRESENTATION LAYER                                                        │
│  FastAPI REST/WebSocket API  ·  React Dashboard  ·  Telegram/Discord bots  │
├──────────────────────────────────────────────────────────────────────────┤
│  APPLICATION LAYER (Orchestration)                                         │
│  TradingEngine · StrategyManager · BacktestEngine · Optimizer · Scanners   │
├──────────────────────────────────────────────────────────────────────────┤
│  DOMAIN LAYER (Business logic — exchange-agnostisch)                       │
│  Strategies · RiskEngine · PortfolioManager · PositionManager · Signals    │
│  AI/ML Module · Indicators · MarketRegime                                  │
├──────────────────────────────────────────────────────────────────────────┤
│  INFRASTRUCTURE LAYER (Adapters)                                           │
│  BinanceSpot/Futures Gateway · WebSocketManager · Repositories (Postgres)  │
│  RedisCache · Notifier-adapters · SecretsManager                           │
├──────────────────────────────────────────────────────────────────────────┤
│  CROSS-CUTTING                                                             │
│  Config · Logging · Metrics · EventBus · Exceptions · Security/Audit       │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Hoofdcomponenten

### 3.1 Exchange-integratie (`exchanges/`)
- `ExchangeGateway` (abstracte basis): `get_klines`, `create_order`, `cancel_order`,
  `get_balance`, `get_positions`, `stream_klines`, `stream_user_data`.
- `BinanceSpotGateway`, `BinanceFuturesGateway`: concrete adapters (REST + WS).
- `WebSocketManager`: auto-reconnect met exponentiële backoff, heartbeat/ping-pong,
  resubscribe-on-reconnect, REST-fallback bij stream-gaten.
- `RateLimiter`: token-bucket per endpoint-gewicht (Binance weight-based limits).
- `OrderSynchronizer`: reconcilieert lokale state met exchange (bij herstart / drift).

### 3.2 Trading-framework (`strategies/`)
- `BaseStrategy` (ABC): lifecycle `on_init → on_candle → on_tick → generate_signal`.
- `StrategyRegistry`: decorator-gebaseerde registratie + dynamische plugin-loader.
- 15 ingebouwde strategieën (EMA/SMA cross, RSI, MACD, Bollinger, VWAP, Ichimoku,
  S/R, Breakout, Mean Reversion, Trend Following, Momentum, Scalping, Grid, DCA).
- `SignalAggregator`: combineert meerdere strategieën; trade alléén bij **confluence**
  (instelbare consensus-drempel) → voorkomt false positives.

### 3.3 Multi-timeframe (`data/`)
- `MarketDataService`: houdt rolling OHLCV-buffers per (symbol, timeframe) in Redis.
- Ondersteunde timeframes: `1m, 3m, 5m, 15m, 30m, 1h, 4h, 12h, 1d`.
- `TimeframeAggregator`: bouwt hogere TF's uit lagere indien stream ontbreekt.

### 3.4 Risicobeheer (`risk/`)
Centrale, niet-omzeilbare `RiskEngine`:
- Per-trade: stop-loss, trailing SL, take-profit (multi-level), break-even.
- Sizing: fixed-risk %, Kelly-criterion (capped), volatility-adjusted (ATR).
- Limieten: max open trades, max exposure/coin, max portfolio exposure,
  dagelijkse/wekelijkse verlieslimiet, max drawdown.
- Beschermingen: correlation control, `CircuitBreaker`, `EmergencyShutdown`.
- **Géén** martingale / onbeperkte averaging-down (hard geblokkeerd in validatie).

### 3.5 Portfolio (`portfolio/`)
- `PortfolioManager`: multi-asset state, equity tracking, allocatie, herbalancering.
- `PerformanceTracker`: realtime metrics (PnL, win rate, Sharpe, drawdown).

### 3.6 AI/ML (`ai/`, optioneel)
- Modellen: XGBoost, RandomForest, LightGBM, LSTM (PyTorch).
- `FeatureEngineer`, `MarketRegimeDetector`, `SentimentAnalyzer`, `WalkForwardValidator`.
- Output = **signaal met confidence**, gaat verplicht door `RiskEngine`.

### 3.7 Backtesting & Optimalisatie (`backtest/`, `optimize/`)
- Event-driven `BacktestEngine` met commission/slippage/spread-simulatie, tick-support.
- Metrics: Net Profit, Profit Factor, Sharpe, Sortino, Calmar, MaxDD, CAGR, Win Rate,
  Avg Trade, Expectancy, Recovery Factor.
- Optimizers: Grid, Random, Bayesian (Optuna), Walk-Forward, Monte-Carlo.

### 3.8 Scanners (`scanners/`)
- Trend, High-Volume, Breakout, Volatility, Liquidity, Relative-Strength scanners.

### 3.9 Monitoring (`api/`, `dashboard/`)
- FastAPI backend (REST + WebSocket push) + React/Vite dashboard.

### 3.10 Persistentie (`infrastructure/db`, `infrastructure/cache`)
- PostgreSQL (SQLAlchemy 2.0 async + Alembic) voor trades/orders/posities/logs/metrics.
- Redis voor caching, pub/sub event-fanout en rolling market-data buffers.

### 3.11 Notificaties (`notifications/`)
- Telegram, Discord, Email adapters achter één `Notifier`-interface + router.

### 3.12 Security (`security/`)
- `SecretsManager` (Fernet-encryptie van API keys at rest), `AuditLogger`,
  input-validatie (Pydantic), veilige credential-opslag, recovery-procedures.

---

## 4. Datastromen (runtime flow)

```
Binance WS ──► WebSocketManager ──► MarketDataService ──► EventBus("candle")
                                                              │
                          ┌───────────────────────────────────┤
                          ▼                                   ▼
                   StrategyManager                      AI/ML Module
                  (alle strategieën)                  (optioneel signaal)
                          │                                   │
                          └────────────► SignalAggregator ◄───┘
                                              │ (confluence?)
                                              ▼
                                         RiskEngine  ──reject──► AuditLog/Notifier
                                              │ approve
                                              ▼
                                       OrderExecutor ──► ExchangeGateway ──► Binance
                                              │
                                              ▼
                        PositionManager / PortfolioManager / Repositories
                                              │
                                              ▼
                              EventBus("trade") ──► Notifier + Dashboard(WS) + Metrics
```

---

## 5. Concurrency-model

- Eén `asyncio` event loop per proces; CPU-intensieve taken (ML-training,
  backtest-sweeps) draaien in een `ProcessPoolExecutor`.
- Componenten zijn `async` services met een `start()/stop()` lifecycle, beheerd door
  een `TaskSupervisor` die gecrashte taken herstart met backoff.
- Graceful shutdown: signal handlers (SIGINT/SIGTERM) → posities optioneel sluiten →
  flush DB/Redis → close WS.

---

## 6. Deployment-topologie

```
                ┌────────────── Docker Compose / K8s ──────────────┐
                │                                                   │
  ┌──────────┐  │  ┌──────────────┐   ┌──────────────┐   ┌───────┐ │
  │  React   │◄─┼─►│  FastAPI API │◄─►│ Trading Engine│◄─►│ Redis │ │
  │ Dashboard│  │  │  (uvicorn)   │   │   (worker)    │   └───────┘ │
  └──────────┘  │  └──────┬───────┘   └──────┬───────┘             │
                │         │                  │      ┌────────────┐ │
                │         └──────────────────┴─────►│ PostgreSQL │ │
                │                                    └────────────┘ │
                │  Notifiers (Telegram/Discord/Email)  ·  Prometheus│
                └───────────────────────────────────────────────────┘
```

Zie `docs/DEPLOYMENT.md` voor Linux/VPS/Cloud-installatie.
