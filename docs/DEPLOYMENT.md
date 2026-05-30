# Deployment-handleiding

Drie deployment-paden: **Docker (aanbevolen)**, **Linux (bare-metal/systemd)** en
**Cloud/VPS**. Begin altijd op het **Binance testnet** in **paper-modus**.

> ⚠️ Zet `BINANCE__TESTNET=true` en `TRADING_MODE=paper` tot je de bot volledig
> hebt gevalideerd. Schakel pas daarna stapsgewijs naar live.

---

## 0. Voorbereiding (alle paden)

```bash
cp .env.example .env
# Genereer geheimen:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # -> SECURITY__ENCRYPTION_KEY
openssl rand -hex 32                                                                        # -> API__JWT_SECRET
```

Vul in `.env` minimaal in: `BINANCE__API_KEY`, `BINANCE__API_SECRET`,
`DATABASE__PASSWORD`, `SECURITY__ENCRYPTION_KEY`, `API__JWT_SECRET`, en je
`SYMBOLS`/`TIMEFRAMES`. Definieer strategieën in `config/strategies.yaml`
(kopieer van `config/strategies.example.yaml`).

---

## 1. Docker (aanbevolen)

Vereist alleen Docker + Docker Compose.

```bash
make up          # of: docker compose up -d --build
make logs        # volg logs
make ps          # status
make down        # stoppen
```

De stack start vijf services: `postgres`, `redis`, `migrate` (eenmalig,
draait Alembic), `api`, `bot` en `dashboard`.

- Dashboard: `http://<host>:5173`
- API + OpenAPI-docs: `http://<host>:8000/docs`

**Development** (hot-reload source-mounts, exposed DB/Redis-poorten):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

**Optionele extras in de image** (AI/optimize) via build-arg:

```bash
docker compose build --build-arg EXTRAS="api,notify,report,ai,optimize"
```

---

## 2. Linux (bare-metal, systemd)

Vereist: Python 3.12+, PostgreSQL 16, Redis 7.

```bash
sudo apt-get install -y python3.12 python3.12-venv postgresql redis-server
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[api,notify,report]"

# Database voorbereiden
sudo -u postgres createuser quantbot --pwprompt
sudo -u postgres createdb quantbot -O quantbot
make migrate
```

**systemd-units** — `/etc/systemd/system/quantbot.service`:

```ini
[Unit]
Description=QuantBot trading engine
After=network.target postgresql.service redis-server.service

[Service]
Type=simple
User=quantbot
WorkingDirectory=/opt/quantbot
EnvironmentFile=/opt/quantbot/.env
ExecStart=/opt/quantbot/.venv/bin/python -m quantbot run
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/quantbot-api.service` (zelfde, met `ExecStart=… -m quantbot api`).

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now quantbot quantbot-api
journalctl -u quantbot -f
```

Serveer het dashboard met nginx (build met `cd dashboard && npm ci && npm run build`,
serveer `dashboard/dist` en proxy `/api` + `/ws` naar `:8000` — zie `dashboard/nginx.conf`).

---

## 3. VPS / Cloud

**Snelle VPS-bootstrap** (Ubuntu/Debian):

```bash
curl -fsSL https://raw.githubusercontent.com/bryan-helsens/Bot/main/scripts/install_vps.sh | bash
```

Het script installeert Docker, kloont de repo, genereert geheimen, configureert
de firewall (SSH/5173/8000) en start de stack.

**Cloud-providers:**

| Provider | Aanpak |
|----------|--------|
| **AWS** | ECS/Fargate met de image; RDS (Postgres) + ElastiCache (Redis); secrets via Secrets Manager → injecteer als env. |
| **GCP** | Cloud Run (api) + een VM/GKE voor de bot-worker; Cloud SQL + Memorystore. |
| **DigitalOcean / Hetzner** | Eén VPS met `docker compose` (gebruik `install_vps.sh`). |
| **Kubernetes** | Deployments voor `api` en `bot`, StatefulSets voor Postgres/Redis, Secrets voor `.env`, liveness via `/health` (api) en `scripts/healthcheck.py` (bot). |

**Productie-checklist:**

- [ ] `ENVIRONMENT=production`, sterke `API__JWT_SECRET` (geen default).
- [ ] Secrets via een secret-store, niet in platte `.env`.
- [ ] TLS-terminatie (reverse proxy / load balancer) vóór de API/dashboard.
- [ ] Database-backups (pg_dump cron) + Redis-persistentie (AOF, al aan).
- [ ] Monitoring/alerting op `/health` en de notificatiekanalen.
- [ ] Resource-limieten op containers; restart-policy `unless-stopped`.
- [ ] Eerst weken paper-trading op testnet vóór live kapitaal.

---

## Database-migraties

```bash
make migrate                 # upgrade naar laatste (alembic upgrade head)
make migration MSG="..."     # genereer nieuwe migratie (autogenerate)
make downgrade               # één stap terug
```

In Docker draait de `migrate`-service dit automatisch vóór `api`/`bot` starten.
