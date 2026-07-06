# 🇧🇪 QuantBot op Bitvavo — stap-voor-stap

Bitvavo is de makkelijkste beurs voor Belgen (SEPA/Bancontact-storten werkt
gewoon, EUR-paren, MiCA-gelicentieerd). De bot ondersteunt het volledig via
`EXCHANGE=bitvavo`.

> ⚠️ **Bitvavo heeft GEEN testnet.** Alles hieronder draait daarom in
> **paper-modus**: echte koersen, maar orders worden lokaal gesimuleerd — er kan
> geen cent bewegen, ook niet per ongeluk. LIVE op Bitvavo is altijd echt geld en
> wordt door de bot geweigerd zonder `ALLOW_LIVE_REAL_ORDERS=true`.
> Ook goed om te weten: Bitvavo's fee is ~0,25% (Binance: 0,1%). De paper-config
> simuleert die 0,25% bewust, zodat de resultaten eerlijk blijven.

---

## 1. API-keys aanmaken op Bitvavo

1. bitvavo.com → account → **API** → nieuwe key.
2. Rechten: **View + Trade** aanvinken — **Withdraw NOOIT aanvinken.**
3. Stel een **IP-whitelist** in (het IP van je server).
4. Bewaar key + secret — die vul je zo in `.env` in.

Voor paper-modus zijn keys strikt genomen alleen nodig voor de balans-weergave;
de bot draait ook zonder (dan blijft de Account-pagina leeg).

## 2A. Optie A — Bitvavo NAAST je lopende Binance-testnet-test (aanrader)

Tweede checkout + eigen service, zodat de bevroren lange-termijntest ongestoord
doorloopt:

```bash
git clone https://github.com/bryan-helsens/Bot.git ~/Bot-bitvavo
cd ~/Bot-bitvavo && git checkout claude/binance-trading-bot-build-bBmx6
python3 -m venv .venv && .venv/bin/pip install -e ".[api]"
cp .env.bitvavo.example .env
nano .env             # Bitvavo-keys invullen + API__PORT=8001
cp config/strategies.paper.example.yaml config/strategies.yaml
cd dashboard && npm install && npm run build && cd ..

# preflight (leest alleen, plaatst nooit orders):
.venv/bin/python scripts/test_bitvavo.py

sudo cp deploy/quantbot-bitvavo.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now quantbot-bitvavo
journalctl -u quantbot-bitvavo -f
```

Dashboard van de Bitvavo-instance: `ssh -L 8001:localhost:8001 debian@SERVER`
→ http://localhost:8001 (de testnet-instance blijft op :8000).

## 2B. Optie B — je bestaande instance omzetten naar Bitvavo

```bash
cd ~/Bot
cp .env.bitvavo.example .env      # keys + evt. dashboard-wachtwoord invullen
cp config/strategies.paper.example.yaml config/strategies.yaml
rm data/state.json
.venv/bin/python scripts/test_bitvavo.py
sudo systemctl restart quantbot
```

⚠️ Dit stopt de Binance-testnet-test (de bevroren lange-termijnmeting). Alleen
doen als je die bewust opgeeft.

## 3. Wat je in de logs hoort te zien

```
gateway_created exchange=bitvavo adapter=BitvavoGateway testnet=False
bitvavo_connected markets=...
strategies_loaded count=1
market_data_started series=...
```

`warmup_skip_symbol` voor een enkele coin is normaal (die staat dan niet op
Bitvavo). Er is geen user-event-stream (polling-adapter) — de lokale StopManager
bewaakt de stops, zoals ook op het testnet.

## 4. Backtesten op Bitvavo-data

`quantbot replay` en `quantbot sweep` werken ook met `EXCHANGE=bitvavo`: ze
halen dan EUR-historie van Bitvavo op (publiek, geen keys nodig) en simuleren
met 0,25% fee. Handig om te zien wat de hogere fees met de strategie doen.

## 5. Ooit live op Bitvavo (echt geld)

Zelfde trechter als altijd (zie `docs/LANGE_TERMIJN_TEST.md`): pas na maanden
aantoonbaar groene paper-cijfers. Dan: `TRADING_MODE=live` +
`ALLOW_LIVE_REAL_ORDERS=true`, klein beginnen, dashboard-wachtwoord aan.
De eerste weken extra opletten: de order-uitvoering op Bitvavo is nieuwer dan
die op Binance.
