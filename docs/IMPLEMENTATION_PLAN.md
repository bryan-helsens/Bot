# Implementatieplan — QuantBot

Gefaseerde, bestand-voor-bestand opbouw. Elke fase is zelfstandig testbaar.
Bestanden worden in deze volgorde geleverd; na elk bestand wacht ik op **"VERDER"**.

---

## Fase 0 — Projectfundament (scaffolding)
1. `pyproject.toml` — dependencies, build, tooling
2. `.env.example` — alle config-variabelen
3. `.gitignore`, `.dockerignore`, `Makefile`
4. `README.md` — projectoverzicht

## Fase 1 — Core (cross-cutting kern)
5. `core/constants.py` — enums
6. `core/exceptions.py` — exception-hiërarchie
7. `core/models.py` — Pydantic domain-modellen
8. `core/config.py` — Settings
9. `core/logging.py` — structured logging
10. `core/events.py` — EventBus
11. `core/utils.py` — helpers (retry, decimal, tijd)
12. `core/supervisor.py` — TaskSupervisor

## Fase 2 — Indicatoren
13. `indicators/trend.py`
14. `indicators/momentum.py`
15. `indicators/volatility.py`
16. `indicators/volume.py`
17. `indicators/levels.py`

## Fase 3 — Exchange-laag
18. `exchanges/base.py`
19. `exchanges/rate_limiter.py`
20. `exchanges/websocket.py`
21. `exchanges/binance_spot.py`
22. `exchanges/binance_futures.py`
23. `exchanges/synchronizer.py`
24. `exchanges/factory.py`

## Fase 4 — Data
25. `data/market_data.py`
26. `data/aggregator.py`
27. `data/historical.py`

## Fase 5 — Strategie-framework
28. `strategies/base.py`
29. `strategies/registry.py`
30. `strategies/aggregator.py`
31–45. `strategies/builtin/*` (15 strategieën)

## Fase 6 — Risicobeheer
46. `risk/position_sizing.py`
47. `risk/stops.py`
48. `risk/limits.py`
49. `risk/correlation.py`
50. `risk/circuit_breaker.py`
51. `risk/engine.py`

## Fase 7 — Portfolio & Execution
52. `portfolio/position.py`
53. `portfolio/manager.py`
54. `portfolio/performance.py`
55. `execution/order_manager.py`
56. `execution/executor.py`

## Fase 8 — Engine
57. `engine/paper_broker.py`
58. `engine/trading_engine.py`

## Fase 9 — Persistentie
59. `infrastructure/db/database.py`
60. `infrastructure/db/models.py`
61. `infrastructure/db/repositories.py`
62. `infrastructure/cache/redis_cache.py`

## Fase 10 — Backtesting & Optimalisatie
63. `backtest/broker.py`
64. `backtest/metrics.py`
65. `backtest/engine.py`
66. `backtest/report.py`
67. `optimize/base.py`
68–72. `optimize/{grid,random,bayesian,walk_forward,monte_carlo}.py`

## Fase 11 — Scanners
73–79. `scanners/*`

## Fase 12 — AI/ML (optioneel)
80. `ai/features.py`
81. `ai/regime.py`
82. `ai/sentiment.py`
83–87. `ai/models/*`
88. `ai/validation.py`
89. `ai/ai_strategy.py`

## Fase 13 — Notificaties & Security
90–93. `notifications/*`
94–96. `security/*`

## Fase 14 — API + Dashboard
97. `api/app.py` + `dependencies.py` + `schemas.py` + `websocket.py`
98. `api/routers/*`
99. `dashboard/*` (React)

## Fase 15 — CLI & entrypoint
100. `cli.py`, `__main__.py`

## Fase 16 — Tests
101–113. `tests/unit/*`, `tests/integration/*`, `conftest.py`

## Fase 17 — Deployment
114. `Dockerfile`, `docker-compose.yml`, `docker-compose.dev.yml`
115. `migrations/*`, `alembic.ini`
116. `scripts/*`
117. `docs/{DEPLOYMENT,USAGE,OPTIMIZATION}.md`

---

## Kwaliteitspoorten (per fase)
- `ruff check` + `ruff format` schoon
- `mypy --strict` op gewijzigde modules
- `pytest` groen voor de bijbehorende tests
- Geen placeholders / TODO's / `pass`-stubs in geleverde code
- Elk bestand compileert (`python -m py_compile`)

## Volgorde van leveren in chat
1. ✅ Systeemarchitectuur (`ARCHITECTURE.md`)
2. ✅ Mappenstructuur (`STRUCTURE.md`)
3. ✅ Database-schema (`DATABASE.md`)
4. ✅ Architectuurdiagram (in `ARCHITECTURE.md`)
5. ✅ Implementatieplan (dit document)
6. ⏭ Broncode per bestand → start bij `pyproject.toml` op commando **VERDER**
