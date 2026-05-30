# Database-schema — QuantBot

**RDBMS:** PostgreSQL 16 · **ORM:** SQLAlchemy 2.0 (async) · **Migraties:** Alembic
**Cache/PubSub:** Redis 7

Alle monetaire waarden worden opgeslagen als `NUMERIC(38, 18)` (geen floats) om
afrondingsfouten te vermijden. Tijdstempels zijn `TIMESTAMPTZ` (UTC).

---

## 1. ER-overzicht

```
 strategies ─┐
             ├──< signals
 symbols ────┤
             ├──< orders >── trades
             │       │
             └──< positions ──< position_events
                     │
 risk_events     equity_snapshots     strategy_performance
 audit_logs      system_logs          notifications
```

---

## 2. Tabellen

### `strategies`
Geregistreerde strategie-instanties (config-gestuurd).

| Kolom | Type | Constraints |
|-------|------|-------------|
| id | UUID | PK, default gen_random_uuid() |
| name | VARCHAR(100) | NOT NULL |
| class_name | VARCHAR(100) | NOT NULL |
| params | JSONB | NOT NULL default '{}' |
| symbols | JSONB | NOT NULL — lijst trading-pairs |
| timeframes | JSONB | NOT NULL |
| enabled | BOOLEAN | NOT NULL default true |
| market | VARCHAR(10) | NOT NULL (`spot`/`futures`) |
| created_at / updated_at | TIMESTAMPTZ | NOT NULL default now() |

UNIQUE(name).

### `symbols`
Cache van exchange-symboolinfo (filters, precisie).

| Kolom | Type | Constraints |
|-------|------|-------------|
| symbol | VARCHAR(30) | PK (bv. `BTCUSDT`) |
| base_asset | VARCHAR(15) | NOT NULL |
| quote_asset | VARCHAR(15) | NOT NULL |
| market | VARCHAR(10) | NOT NULL |
| price_precision | SMALLINT | NOT NULL |
| qty_precision | SMALLINT | NOT NULL |
| min_notional | NUMERIC(38,18) | NOT NULL |
| tick_size | NUMERIC(38,18) | NOT NULL |
| step_size | NUMERIC(38,18) | NOT NULL |
| filters | JSONB | NOT NULL default '{}' |
| updated_at | TIMESTAMPTZ | NOT NULL default now() |

### `signals`
Door strategieën/AI gegenereerde signalen (audit + analyse).

| Kolom | Type | Constraints |
|-------|------|-------------|
| id | UUID | PK |
| strategy_id | UUID | FK→strategies.id |
| symbol | VARCHAR(30) | NOT NULL, idx |
| timeframe | VARCHAR(5) | NOT NULL |
| side | VARCHAR(5) | NOT NULL (`buy`/`sell`) |
| signal_type | VARCHAR(20) | NOT NULL (`entry`/`exit`) |
| strength | NUMERIC(6,4) | confidence 0..1 |
| price | NUMERIC(38,18) | NOT NULL |
| meta | JSONB | NOT NULL default '{}' |
| created_at | TIMESTAMPTZ | NOT NULL default now(), idx |

INDEX(symbol, created_at), INDEX(strategy_id).

### `orders`
Alle ingediende orders (lokale spiegel van exchange).

| Kolom | Type | Constraints |
|-------|------|-------------|
| id | UUID | PK |
| client_order_id | VARCHAR(64) | NOT NULL, UNIQUE |
| exchange_order_id | VARCHAR(64) | NULL, idx |
| position_id | UUID | FK→positions.id NULL |
| strategy_id | UUID | FK→strategies.id NULL |
| symbol | VARCHAR(30) | NOT NULL, idx |
| market | VARCHAR(10) | NOT NULL |
| side | VARCHAR(5) | NOT NULL |
| type | VARCHAR(20) | NOT NULL (`market`/`limit`/`stop`/`take_profit`...) |
| status | VARCHAR(20) | NOT NULL (`new`/`partially_filled`/`filled`/`canceled`/`rejected`/`expired`) |
| quantity | NUMERIC(38,18) | NOT NULL |
| price | NUMERIC(38,18) | NULL |
| stop_price | NUMERIC(38,18) | NULL |
| filled_qty | NUMERIC(38,18) | NOT NULL default 0 |
| avg_fill_price | NUMERIC(38,18) | NULL |
| commission | NUMERIC(38,18) | NOT NULL default 0 |
| reduce_only | BOOLEAN | NOT NULL default false |
| role | VARCHAR(20) | NULL (`entry`/`stop_loss`/`take_profit`/`trailing`) |
| created_at / updated_at | TIMESTAMPTZ | NOT NULL default now() |

INDEX(status), INDEX(symbol, created_at).

### `positions`
Open/gesloten posities (aggregaat van fills).

| Kolom | Type | Constraints |
|-------|------|-------------|
| id | UUID | PK |
| strategy_id | UUID | FK→strategies.id NULL |
| symbol | VARCHAR(30) | NOT NULL, idx |
| market | VARCHAR(10) | NOT NULL |
| side | VARCHAR(5) | NOT NULL (`long`/`short`) |
| status | VARCHAR(10) | NOT NULL (`open`/`closed`) |
| quantity | NUMERIC(38,18) | NOT NULL |
| entry_price | NUMERIC(38,18) | NOT NULL |
| exit_price | NUMERIC(38,18) | NULL |
| stop_loss | NUMERIC(38,18) | NULL |
| take_profit | JSONB | NULL — multi-TP levels |
| leverage | SMALLINT | NOT NULL default 1 |
| realized_pnl | NUMERIC(38,18) | NOT NULL default 0 |
| unrealized_pnl | NUMERIC(38,18) | NOT NULL default 0 |
| fees_paid | NUMERIC(38,18) | NOT NULL default 0 |
| opened_at | TIMESTAMPTZ | NOT NULL default now() |
| closed_at | TIMESTAMPTZ | NULL |
| meta | JSONB | NOT NULL default '{}' |

INDEX(status), INDEX(symbol, status).

### `position_events`
Audit-trail per positiemutatie (SL-verplaatsing, partial TP, break-even).

| id UUID PK · position_id FK · event_type VARCHAR(30) · payload JSONB · created_at TIMESTAMPTZ |

### `trades`
Afgeronde (gerealiseerde) trades — bron voor performance.

| Kolom | Type | Constraints |
|-------|------|-------------|
| id | UUID | PK |
| position_id | UUID | FK→positions.id |
| strategy_id | UUID | FK→strategies.id NULL |
| symbol | VARCHAR(30) | NOT NULL, idx |
| side | VARCHAR(5) | NOT NULL |
| quantity | NUMERIC(38,18) | NOT NULL |
| entry_price | NUMERIC(38,18) | NOT NULL |
| exit_price | NUMERIC(38,18) | NOT NULL |
| gross_pnl | NUMERIC(38,18) | NOT NULL |
| net_pnl | NUMERIC(38,18) | NOT NULL |
| fees | NUMERIC(38,18) | NOT NULL |
| return_pct | NUMERIC(12,6) | NOT NULL |
| bars_held | INTEGER | NULL |
| exit_reason | VARCHAR(30) | NULL (`stop_loss`/`take_profit`/`signal`/`manual`/`liquidation`) |
| opened_at / closed_at | TIMESTAMPTZ | NOT NULL |

INDEX(strategy_id, closed_at), INDEX(symbol, closed_at).

### `equity_snapshots`
Periodieke equity-/balanssnapshots voor equity-curve & drawdown.

| id BIGSERIAL PK · timestamp TIMESTAMPTZ idx · equity NUMERIC · balance NUMERIC · unrealized_pnl NUMERIC · drawdown NUMERIC · open_positions INT |

### `strategy_performance`
Geaggregeerde metrics per strategie (rolling).

| id UUID PK · strategy_id FK · period VARCHAR(10) · net_profit NUMERIC · profit_factor NUMERIC · sharpe NUMERIC · sortino NUMERIC · calmar NUMERIC · max_drawdown NUMERIC · win_rate NUMERIC · expectancy NUMERIC · trades_count INT · updated_at TIMESTAMPTZ |

### `risk_events`
Door RiskEngine geblokkeerde/getriggerde gebeurtenissen.

| id UUID PK · event_type VARCHAR(40) · severity VARCHAR(10) · symbol VARCHAR(30) NULL · reason TEXT · payload JSONB · created_at TIMESTAMPTZ idx |

### `audit_logs`
Onveranderlijke audit-trail (security/compliance).

| id BIGSERIAL PK · actor VARCHAR(50) · action VARCHAR(60) · resource VARCHAR(60) · payload JSONB · ip VARCHAR(45) NULL · created_at TIMESTAMPTZ idx |

### `system_logs`
Gestructureerde applicatie-logs (optioneel naast stdout).

| id BIGSERIAL PK · level VARCHAR(10) · logger VARCHAR(80) · message TEXT · context JSONB · created_at TIMESTAMPTZ idx |

### `notifications`
Verzonden-meldingen-log (de-duplicatie + retry).

| id UUID PK · channel VARCHAR(20) · event_type VARCHAR(40) · status VARCHAR(15) · payload JSONB · error TEXT NULL · created_at TIMESTAMPTZ |

---

## 3. Indexen & retentie

- Hot-path queries gedekt door samengestelde indexen (zie per tabel).
- `equity_snapshots`, `system_logs`, `signals` → kandidaat voor **TimescaleDB
  hypertables** of partitionering per maand bij hoge volumes.
- Retentiebeleid (configureerbaar): logs 90d, signals 180d, snapshots 365d.

---

## 4. Redis-keyspace

| Key-patroon | Type | Doel | TTL |
|-------------|------|------|-----|
| `md:{symbol}:{tf}` | List/Stream | Rolling OHLCV-buffer | rolling |
| `ticker:{symbol}` | Hash | Laatste prijs/bid/ask | 10s |
| `lock:order:{client_id}` | String (SETNX) | Idempotente order-submit | 30s |
| `rl:{endpoint}` | String/ZSet | Rate-limit token-bucket | window |
| `pubsub:events` | Pub/Sub | Event-fanout naar API/dashboard | — |
| `state:engine` | Hash | Engine heartbeat/status | 30s |

---

## 5. Migratiestrategie

- Alembic autogenerate vanaf `infrastructure/db/models.py`.
- Eerste migratie `0001_initial` bevat alle bovenstaande tabellen + indexen +
  `CREATE EXTENSION IF NOT EXISTS "pgcrypto"` (voor `gen_random_uuid()`).
- Nul-downtime: additieve migraties; nooit destructief zonder backfill.
