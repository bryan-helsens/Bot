<div align="center">

# 🤖 QuantBot

**Professionele, asynchrone cryptocurrency trading bot voor Binance**
*Spot · Futures · Testnet — productieklaar, modulair, veilig en getest.*

[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Typed: mypy strict](https://img.shields.io/badge/typed-mypy%20strict-blue.svg)](http://mypy-lang.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

</div>

> ⚠️ **Disclaimer.** Trading in cryptocurrency brengt aanzienlijke risico's met
> zich mee. Deze software wordt geleverd "as is", zonder enige garantie. Handel
> nooit met geld dat je niet kunt missen en begin **altijd** op het Binance
> testnet. De auteurs zijn niet aansprakelijk voor enig financieel verlies.

> 📘 **Nieuw hier? Begin met de [complete handleiding](docs/HANDLEIDING.md)** —
> één document dat alles samenbrengt: opstarten, de gevalideerde config, het
> dashboard, backtesten, 24/7 draaien, de weg naar echt geld en probleemoplossing.

---

## Inhoud

- [Kernfeatures](#kernfeatures)
- [Architectuur](#architectuur)
- [Snel starten](#snel-starten)
- [Configuratie](#configuratie)
- [Gebruik](#gebruik)
- [Docker](#docker)
- [Ontwikkeling](#ontwikkeling)
- [Veiligheid](#veiligheid)
- [Documentatie](#documentatie)
- [Handelsfilosofie](#handelsfilosofie)
- [Licentie](#licentie)

---

## Kernfeatures

| Domein | Mogelijkheden |
|--------|---------------|
| **Exchange** | Binance Spot & Futures, Testnet, auto-reconnect, rate-limit management, WebSocket-streams met REST-fallback, order-synchronisatie |
| **Strategieën** | 15 ingebouwde strategieën (EMA/SMA-cross, RSI, MACD, Bollinger, VWAP, Ichimoku, S/R, Breakout, Mean Reversion, Trend Following, Momentum, Scalping, Grid, DCA) + **plugin-systeem** voor eigen strategieën |
| **Multi-timeframe** | 1m, 3m, 5m, 15m, 30m, 1h, 4h, 12h, 1d |
| **Risicobeheer** | Stop-loss, trailing stop, multi-level take-profit, break-even, risk/Kelly/volatility-sizing, exposure- & verlieslimieten, drawdown-bescherming, correlatiecontrole, circuit breaker, emergency shutdown |
| **Portfolio** | Multi-asset, herbalancering, allocatie, equity- & performance-tracking |
| **AI/ML** *(optioneel)* | XGBoost, Random Forest, LightGBM, LSTM, marktregime-detectie, feature-engineering, sentiment, walk-forward-validatie — **alleen signalen**, altijd via de RiskEngine |
| **Backtesting** | Event-driven engine met commissie-, slippage- en spread-simulatie; Sharpe, Sortino, Calmar, Profit Factor, MaxDD, CAGR, Expectancy, e.v.a. |
| **Optimalisatie** | Grid, Random, Bayesian (Optuna), Walk-Forward, Monte-Carlo |
| **Scanners** | Trend, volume, breakout, volatility, liquidity, relative-strength |
| **Monitoring** | FastAPI-backend + React-dashboard (realtime trades, equity-curve, drawdown, strategie- & risicostatistieken) |
| **Notificaties** | Telegram, Discord, Email |
| **Opslag** | PostgreSQL + Redis |
| **DevOps** | Docker, Docker Compose, CI/CD, volledige test-suite |

---

## Architectuur

QuantBot gebruikt een **event-driven, gelaagde (Hexagonal) architectuur** met een
centrale `asyncio`-loop. De domeinlaag is volledig exchange-agnostisch; Binance is
slechts één adapter achter de `ExchangeGateway`-interface.

```
Binance WS → WebSocketManager → MarketDataService → StrategyManager + AI
                                                          │
                                                  SignalAggregator (confluence)
                                                          │
                                                     RiskEngine  ──reject──► AuditLog
                                                          │ approve
                                                     OrderExecutor → Binance
                                                          │
                                          Portfolio · Repositories · Notifier · Dashboard
```

Zie [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) voor het volledige overzicht en
diagrammen.

---

## Snel starten

> Vereisten: **Python 3.12+**, **PostgreSQL 16**, **Redis 7**. Of gebruik
> [Docker](#docker) — dan heb je alleen Docker nodig.

```bash
# 1. Repo klonen
git clone https://github.com/bryan-helsens/Bot.git quantbot && cd quantbot

# 2. Virtuele omgeving + dependencies
python3 -m venv .venv && source .venv/bin/activate
make install            # of: pip install -e ".[dev]"

# 3. Configuratie
make env                # kopieert .env.example -> .env
#   bewerk .env: zet BINANCE__TESTNET=true en vul testnet-API-keys in

# 4. Database migreren
make migrate

# 5. Starten in paper-modus (geen echt geld)
make run
```

Genereer benodigde geheimen:

```bash
# Fernet-encryptiesleutel (SECURITY__ENCRYPTION_KEY)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# JWT-secret voor de API (API__JWT_SECRET)
openssl rand -hex 32
```

---

## Configuratie

Alle instellingen lopen via **`.env`** (geladen door `quantbot.core.config.Settings`).
Geneste opties gebruiken `__` als scheidingsteken, bijvoorbeeld
`RISK__MAX_OPEN_TRADES=5`. Zie [`.env.example`](.env.example) voor de volledige,
gedocumenteerde lijst.

Actieve strategieën worden gedefinieerd in `config/strategies.yaml`
(zie `config/strategies.example.yaml`):

```yaml
strategies:
  - name: ema_fast_btc
    class: EMACrossoverStrategy
    market: spot
    symbols: [BTCUSDT]
    timeframes: [1h]
    params: { fast_period: 12, slow_period: 26 }
  - name: rsi_eth
    class: RSIStrategy
    market: spot
    symbols: [ETHUSDT]
    timeframes: [15m]
    params: { period: 14, oversold: 30, overbought: 70 }
```

---

## Gebruik

QuantBot heeft een Typer-CLI (`python -m quantbot ...` of `quantbot ...`):

```bash
quantbot run                       # live/paper engine (modus uit .env)
quantbot api                       # start FastAPI monitoring-backend
quantbot backtest --strategy rsi_eth --from 2024-01-01 --to 2024-06-01
quantbot optimize --strategy rsi_eth --method bayesian --trials 100
quantbot scan --scanner breakout --top 20
quantbot download --symbol BTCUSDT --timeframe 1h --from 2023-01-01
quantbot migrate                   # database-migraties
```

Volledige uitleg in [`docs/USAGE.md`](docs/USAGE.md).

---

## Docker

```bash
make env                 # configureer .env eerst
make up                  # bot + api + postgres + redis + dashboard
make logs                # volg de logs
make down                # stoppen
```

Het dashboard is bereikbaar op `http://localhost:5173`, de API op
`http://localhost:8000` (OpenAPI-docs op `/docs`).

---

## Ontwikkeling

```bash
make check               # ruff lint + mypy --strict
make test                # volledige test-suite
make cov                 # tests met coverage-rapport
make ci                  # lint + types + tests (CI-poort)
make format              # auto-format met ruff
```

Een nieuwe strategie toevoegen vereist **geen** wijziging aan de kerncode:

```python
from quantbot.strategies.base import BaseStrategy, StrategyContext
from quantbot.strategies.registry import register_strategy
from quantbot.core.models import Signal

@register_strategy
class MyStrategy(BaseStrategy):
    async def on_candle(self, ctx: StrategyContext) -> Signal | None:
        ...  # eigen logica → retourneer een Signal of None
```

---

## Veiligheid

- API-keys worden **versleuteld at rest** (Fernet) via de `SecretsManager`.
- Onveranderlijke **audit-logging** van alle handels- en systeemacties.
- Strikte **input-validatie** (Pydantic) op alle externe data en API-input.
- **Géén** martingale of onbeperkt averaging-down — hard geblokkeerd in de RiskEngine.
- Commit nooit je `.env`. Gebruik in productie een secret-store.

---

## Documentatie

| Document | Inhoud |
|----------|--------|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Systeemarchitectuur & diagrammen |
| [`docs/STRUCTURE.md`](docs/STRUCTURE.md) | Mappenstructuur |
| [`docs/DATABASE.md`](docs/DATABASE.md) | Database-schema |
| [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) | Implementatieplan |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Linux/VPS/Cloud-installatie |
| [`docs/USAGE.md`](docs/USAGE.md) | Gebruikshandleiding |
| [`docs/OPTIMIZATION.md`](docs/OPTIMIZATION.md) | Optimalisatiehandleiding |

---

## Handelsfilosofie

QuantBot is ontworpen rond **kapitaalbehoud**:

1. **Risk-first** — geen order zonder validatie door de RiskEngine.
2. **Confluence** — handel alleen wanneer meerdere signalen overeenkomen.
3. **Anti-overfitting** — walk-forward & Monte-Carlo-validatie standaard.
4. **Strenge risicocontrole** — exposure-, verlies- en drawdown-limieten.
5. **Geen "gegarandeerde winst"-aannames** — geen martingale, geen onbeperkt averaging.

---

## Licentie

MIT — zie [`LICENSE`](LICENSE).
