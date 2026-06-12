# QuantBot op een OVHcloud VPS — stap-voor-stap

Een complete, afvinkbare checklist om de bot 24/7 op een **OVHcloud VPS** te
draaien met het dashboard, veilig te bekijken via een SSH-tunnel. Paden zijn al
ingevuld voor de standaard OVH-gebruiker **`debian`**.

> Draait alles op **testnet** (nepgeld) zolang `BINANCE__TESTNET=true`. Ga pas
> naar echt geld als het Profitability Report over weken eerlijk positief is —
> en zet dán eerst het dashboard-wachtwoord aan (stap 7).

---

## 1. SSH-sleutel maken (op je eigen pc)

Zo log je zonder wachtwoord in. Eenmalig:

```bash
ssh-keygen -t ed25519 -C "quantbot"      # enter, enter
cat ~/.ssh/id_ed25519.pub                # kopieer deze hele regel
```

## 2. VPS bestellen

- Ga naar https://www.ovhcloud.com → **Bare Metal & VPS → VPS**.
- Plan: het instap-**VPS** (~€5–6/mnd, 2 vCPU / 2–4 GB RAM) is ruim genoeg
  (de bot gebruikt < 300 MB RAM).
- **Datacenter**: Gravelines/Roubaix (FR) of Frankfurt/Londen — EU, dichtbij.
- **OS**: **Debian 12**.
- **SSH-sleutel**: plak je publieke sleutel uit stap 1 (of voeg later toe).
- Afrekenen → OVH mailt je het **IP-adres** en de login.

## 3. Inloggen

OVH logt bij Debian in als gebruiker **`debian`** (met `sudo`), niet als root:

```bash
ssh debian@JOUW_SERVER_IP        # eerste keer: typ 'yes'
```

## 4. Systeem klaarmaken

```bash
sudo apt update && sudo apt install -y git python3-venv python3-pip curl
# Node.js (voor het dashboard):
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash -
sudo apt install -y nodejs
```

## 5. Bot installeren

```bash
cd ~
git clone https://github.com/bryan-helsens/Bot.git
cd Bot
git checkout claude/binance-trading-bot-build-bBmx6

python3 -m venv .venv
.venv/bin/pip install -e ".[api]"

cp .env.testnet.example .env
cp config/strategies.paper.example.yaml config/strategies.yaml

# Vul je 2 TESTNET-keys in (van https://testnet.binance.vision):
nano .env        # BINANCE__API_KEY / BINANCE__API_SECRET

# Dashboard bouwen:
cd dashboard && npm install && npm run build && cd ..
```

Snelle rooktest (optioneel, Ctrl-C om te stoppen):

```bash
.venv/bin/quantbot serve
```

## 6. 24/7 draaien met systemd

De repo bevat `deploy/quantbot.service`. Voor de OVH-`debian`-gebruiker zijn de
paden `/home/debian/Bot`. Plaats dit kant-en-klare bestand:

```bash
sudo tee /etc/systemd/system/quantbot.service >/dev/null <<'UNIT'
[Unit]
Description=QuantBot trading engine + dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=debian
WorkingDirectory=/home/debian/Bot
ExecStart=/home/debian/Bot/.venv/bin/quantbot serve
Restart=always
RestartSec=5
TimeoutStopSec=20
StandardOutput=journal
StandardError=journal
SyslogIdentifier=quantbot
NoNewPrivileges=true
ProtectSystem=full

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now quantbot
systemctl status quantbot          # moet "active (running)" tonen
journalctl -u quantbot -f          # live logs
```

In de logs hoor je te zien: `strategies_loaded count=2`,
`market_data_started`, `reconciliation_clean` (geen `reconcile_failed`).
De `warmup_skip_symbol`-regels voor coins die niet op testnet bestaan zijn
normaal.

## 7. Dashboard-beveiliging aanzetten (vóór echt geld / publieke toegang)

Achter de SSH-tunnel (stap 8) is het al veilig. Zet je het breder open, of ga je
naar echt geld, voeg dan in `.env` toe:

```bash
nano .env
#   API__DASHBOARD_USER=admin
#   API__DASHBOARD_PASSWORD=kies-een-sterk-wachtwoord
#   API__JWT_SECRET=een-lange-willekeurige-string
sudo systemctl restart quantbot
```

Daarna vraagt het dashboard om in te loggen.

## 8. Dashboard veilig bekijken (SSH-tunnel)

Het dashboard bindt op `127.0.0.1:8000` (niet publiek). Vanaf je eigen pc:

```bash
ssh -L 8000:localhost:8000 debian@JOUW_SERVER_IP
```

Laat dat venster open en open in je browser: **http://localhost:8000**

---

## Dagelijks gebruik

| Wil je… | Commando (op de server) |
|---|---|
| Live logs zien | `journalctl -u quantbot -f` |
| Herstarten | `sudo systemctl restart quantbot` |
| Stoppen | `sudo systemctl stop quantbot` |
| Status | `systemctl status quantbot` |
| Updaten | `cd ~/Bot && git pull && .venv/bin/pip install -e ".[api]" && (cd dashboard && npm run build) && sudo systemctl restart quantbot` |
| Test opnieuw beginnen | `rm ~/Bot/data/state.json && sudo systemctl restart quantbot` |

## Veelvoorkomende fouten

- **`git pull`: insufficient permission … .git/objects** — je hebt eerder git met
  `sudo` gedraaid. Fix: `sudo chown -R debian:debian ~/Bot`. Draai git **nooit**
  met `sudo`.
- **Dashboard laadt niet** — heb je `npm run build` gedraaid? Het wordt uit
  `dashboard/dist` geserveerd (die map staat in `.gitignore`, dus bouw 'm op de
  server).
- **`ModuleNotFoundError: uvicorn`** — installeer met de extra: `.venv/bin/pip
  install -e ".[api]"`.

## Veiligheid

- Houd `API__HOST=127.0.0.1` (staat al zo in `.env.testnet.example`) zodat het
  dashboard niet publiek staat; gebruik de SSH-tunnel.
- Gebruik **alleen testnet-keys** met **Reading + Spot Trading** rechten —
  **nooit** withdrawal-rechten.
- Commit je `.env` nooit (staat in `.gitignore`).
