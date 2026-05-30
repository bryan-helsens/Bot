# Gebruikshandleiding

## Installatie

```bash
python3.12 -m venv .venv && source .venv/bin/activate
make install            # pip install -e ".[dev]"
make env                # kopieert .env.example -> .env
make migrate
```

## CLI-overzicht

QuantBot wordt bediend via `python -m quantbot <command>` (of `quantbot <command>`):

| Command | Beschrijving |
|---------|--------------|
| `run` | Start de trading-engine (live/paper volgens `TRADING_MODE`). |
| `api` | Start de FastAPI monitoring-backend. |
| `backtest` | Historische backtest van een strategie. |
| `optimize` | Parameter-optimalisatie (zie `OPTIMIZATION.md`). |
| `scan` | Markt-scanners over het symbool-universum. |
| `download` | Historische candles ophalen + cachen (parquet). |
| `migrate` | Database-migraties toepassen. |
| `version` | Versie tonen. |

`quantbot <command> --help` toont alle opties.

## Configuratie

Alles via `.env` (zie `.env.example` voor de volledige, becommentarieerde lijst).
Geneste opties gebruiken `__`, bv. `RISK__MAX_OPEN_TRADES=5`.

Actieve strategieën in `config/strategies.yaml`:

```yaml
strategies:
  - name: ema_btc_1h
    class: EMACrossoverStrategy
    symbols: [BTCUSDT]
    timeframes: [1h]
    params: { fast_period: 12, slow_period: 26 }
```

## Modi

- **Paper** (`TRADING_MODE=paper`) — echte marktdata, gesimuleerde orders. Risicovrij; start hier.
- **Live** (`TRADING_MODE=live`) — echte orders (gebruik `BINANCE__TESTNET=true` voor testnet).
- **Backtest** — via `quantbot backtest`.

## Voorbeelden

```bash
# Paper trading starten
quantbot run

# Backtest met rapport
quantbot backtest --strategy RSIStrategy --symbol ETHUSDT \
  --timeframe 15m --start 2024-01-01 --end 2024-06-01
# -> tabel in de terminal + HTML/JSON in backtest_results/

# Markt scannen op trending coins
quantbot scan --scanner trend --timeframe 4h --top 20

# Historische data ophalen
quantbot download --symbol BTCUSDT --timeframe 1h --start 2023-01-01

# Monitoring-backend + dashboard
quantbot api          # backend op :8000
# dashboard: cd dashboard && npm run dev  (of via docker compose)
```

## Eigen strategie toevoegen (plugin)

Geen kernwijziging nodig — maak een bestand (bv. in een `plugins/`-map) met:

```python
from quantbot.strategies.base import BaseStrategy, StrategyContext
from quantbot.strategies.registry import register_strategy
from quantbot.core.models import Signal
from quantbot.core.constants import Side

@register_strategy
class MyStrategy(BaseStrategy):
    name = "MyStrategy"
    default_params = {"lookback": 20}

    @property
    def min_candles(self) -> int:
        return int(self.param("lookback")) + 1

    async def on_candle(self, ctx: StrategyContext) -> Signal | None:
        if ctx.closes[-1] > ctx.closes[-2]:
            return self.make_signal(ctx, Side.BUY, strength=0.7, reason="up")
        return None
```

Laad plugins met `registry.load_plugin_dir("plugins")` of verwijs ernaar in de config.

## Dashboard

Het React-dashboard (`http://localhost:5173`) toont realtime: equity-curve,
drawdown, open posities, gesloten trades, PnL, strategie- en risicostatistieken,
en systeemstatus. De **Emergency Stop / Resume**-knoppen sturen de RiskEngine aan.

## Monitoring & notificaties

Zet kanalen aan in `.env` (`NOTIFICATIONS__TELEGRAM_ENABLED=true`, etc.). Je
ontvangt meldingen voor: nieuwe/gesloten trades, stop-loss/take-profit,
risk-rejects, verbindingsverlies/-herstel, grote drawdown en systeemfouten.

## Veiligheid & best practices

- Begin op **testnet** + **paper**; valideer wekenlang vóór live.
- Houd `RISK__*`-limieten conservatief; verlaag `RISK__RISK_PER_TRADE` bij twijfel.
- Commit nooit je `.env`. Gebruik in productie een secret-store.
- Volg de handelsregels: confluence-only, geen martingale, strikte stops.

## Probleemoplossing

| Symptoom | Oorzaak / oplossing |
|----------|---------------------|
| `AuthenticationError` | Verkeerde API-keys of klok-drift; controleer keys & systeemtijd. |
| Geen trades | Confluence-drempel te hoog of te weinig strategieën; verlaag `AGGREGATOR__MIN_CONSENSUS`. |
| `RateLimitError` | Te veel requests; de limiter pauzeert automatisch — verlaag het aantal symbolen/timeframes. |
| DB-connectiefouten | Controleer `DATABASE__*` en dat Postgres draait; run `make migrate`. |
| WS blijft herverbinden | Netwerk/firewall; controleer `BINANCE__WS_BASE_URL` en uitgaand verkeer. |
