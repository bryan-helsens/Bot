# 📘 QuantBot — Complete Handleiding

Dit is het **centrale document**: alles wat je nodig hebt om de bot te begrijpen,
te draaien, te testen en (voorzichtig) naar echt geld te brengen — in één plek.
Voor diepere details verwijst elk onderdeel naar de bijbehorende doc.

---

## 0. Eerlijke status (lees dit eerst)

- **De software is af en productieklaar.** 175 tests groen, geharde
  order-uitvoering, risk-management, dashboard, backtester, deployment,
  beveiliging en monitoring. Als product is dit compleet.
- **Niemand kan garanderen dat een tradingbot winst maakt** — de markt is
  onzeker. Wat we wél hebben: een strategie met een *aantoonbare backtest-edge
  over meerdere marktregimes*, en een streng proces om die eerlijk te valideren
  vóór er echt geld aan te pas komt.
- **De weg naar echt geld is een trechter, geen knop:**
  `backtest ✅ → grote sample → 1-2 weken testnet paper-live → pas dán klein echt geld`.

---

## 1. Wat de bot doet

Een asynchrone spot-tradingbot voor Binance die:
- live candles van een mandje coins binnenhaalt,
- per coin een **RSI dip-buyer**-strategie draait (koopt oversold-bounces),
- elke order door een **risk-engine** haalt (positiegrootte, stops, exposure-caps,
  circuit breaker, emergency stop),
- posities beheert met stop-loss / trailing / take-profit,
- alles toont in een **dashboard** en bijhoudt voor een herstart.

Standaard draait alles op het **Binance testnet** (nepgeld) tot je bewust omschakelt.

---

## 2. Snelstart (lokaal of server)

```bash
git clone https://github.com/bryan-helsens/Bot.git
cd Bot
git checkout claude/binance-trading-bot-build-bBmx6

python3 -m venv .venv
.venv/bin/pip install -e ".[api]"

cp .env.testnet.example .env                          # vul je 2 testnet-keys in
cp config/strategies.paper.example.yaml config/strategies.yaml
cd dashboard && npm install && npm run build && cd ..

.venv/bin/quantbot serve                              # bot + dashboard op poort 8000
```

Testnet-keys haal je op https://testnet.binance.vision (rechten: **Reading +
Spot Trading**, NOOIT withdrawals).

---

## 3. De gevalideerde config

**`config/strategies.yaml`** — RSI-only (EMA stond uit: was 72% van het verlies):

```yaml
strategies:
  - name: rsi_dip_buyer
    class: RSIStrategy
    enabled: true
    timeframes: [5m, 15m]
    params:
      period: 14
      oversold: 35          # backtest-best over 4 vensters
      overbought: 70
      trend_filter: false   # filter kostte meer dan hij beschermde
      trend_period: 50
```

**`.env`** — de belangrijke knoppen (volledige uitleg staat in
`.env.testnet.example`):

| Instelling | Waarde | Waarom |
|---|---|---|
| `BACKTEST__INITIAL_CAPITAL` | 100 | je test-kapitaal (nepgeld op testnet) |
| `RISK__RISK_PER_TRADE` | 0.003 | ~0,3% risico per trade |
| `RISK__DEFAULT_STOP_LOSS_PCT` | 0.03 | 3% stop |
| `RISK__MAX_OPEN_TRADES` | 8 | max gelijktijdige posities |
| `RISK__EXIT_ON_OPPOSITE_SIGNAL` | false | geen fee-churn op flips |
| `RISK__REENTRY_COOLDOWN_SECONDS` | 1800 | geen revenge-trade na verlies |
| `SYMBOLS` | 32 liquide coins | geen memes/dode coins |

De coin-lijst en alle risk-waardes staan kant-en-klaar in `.env.testnet.example`.

---

## 4. Backtesten (snel itereren)

Test je config op echte historie zonder dagen te wachten:

```bash
# één config testen over 30 dagen:
.venv/bin/quantbot replay --days 30

# config-varianten vergelijken (ranglijst op profit factor):
.venv/bin/quantbot sweep --days 30 --limit 10

# een ander marktregime testen:
.venv/bin/quantbot sweep --days 30 --limit 10 --start 2026-05-01
```

De replay draait je **echte** config door de **echte** engine met realistische
fills — wat je in de backtest ziet, is wat live gebeurt. Let altijd op de
**"Buy & hold BTC"**-regel onderaan om het marktregime te kennen: in een
zijwaartse/dalende markt presteert de dip-buyer goed; een dooie, richtingsloze
maand is het zwakst.

> ⚠️ Backtest ≠ toekomst. Het filtert slechte configs eruit; het garandeert geen
> winst. Test meerdere periodes en kies wat *consistent* werkt, niet wat op één
> venster piekt.

---

## 4b. Meerdere beurzen (Binance of Bitvavo)

De bot is multi-exchange: kies de beurs met één instelling in `.env`:

```bash
EXCHANGE=binance    # standaard — laagste fees (~0,1%), heeft een testnet
EXCHANGE=bitvavo    # EU/België — makkelijk storten (SEPA/Bancontact), EUR-paren
```

Voor Bitvavo: `cp .env.bitvavo.example .env` en vul je Bitvavo-keys in (rechten:
alleen View + Trade, nooit Withdraw). Let op de verschillen:

| | Binance | Bitvavo |
|---|---|---|
| Storten vanuit België | moeizaam | **makkelijk** (SEPA/Bancontact) |
| Fees | **~0,1%** | ~0,25% |
| Testnet (nepgeld) | **ja** | **nee** — valideren via `TRADING_MODE=paper` |
| Paren | USDT (BTCUSDT…) | EUR (BTCEUR…) |

⚠️ Omdat Bitvavo géén testnet heeft, is LIVE daar **altijd echt geld** — de bot
weigert dat zonder `ALLOW_LIVE_REAL_ORDERS=true`. Valideer er eerst weken in
paper-modus. En de hogere fees maken de strategie daar zwaarder: het
`.env.bitvavo.example` simuleert bewust 0,25% commissie zodat paper-resultaten
eerlijk blijven.

## 5. 24/7 draaien op een server

Volledige stap-voor-stap voor OVH: **`docs/OVH_SETUP.md`** (ook geldig voor
Hetzner/DigitalOcean/elke Debian-VPS). Kort:

```bash
sudo cp deploy/quantbot.service /etc/systemd/system/   # paden/User aanpassen!
sudo systemctl daemon-reload
sudo systemctl enable --now quantbot
journalctl -u quantbot -f                               # live logs
```

State (cash/posities/equity) wordt bewaard in `data/state.json`, dus een herstart
hervat naadloos. Test opnieuw beginnen? `rm data/state.json` + herstart.

---

## 6. Het dashboard

`quantbot serve` draait bot + dashboard op poort 8000. Bekijk veilig via een
SSH-tunnel: `ssh -L 8000:localhost:8000 user@server` → browser op
`http://localhost:8000`.

9 pagina's: **Overview · Market Scanner · Positions & Trades · Coin detail ·
Trade Analytics · Performance · Account · Controls & Config · Logs.**
Hoogtepunten:
- **Market Scanner** — live RSI/trend per coin: zie wáárom hij (niet) handelt.
- **Trade Analytics** — PnL per coin én per strategie, fees, houdtijd.
- **Performance → Profitability Report** — eerlijk go/no-go-oordeel vs buy & hold.
- **Account** — wallet vs bot-equity + storten/opnemen (telt niet als winst).
- **Belasting** — gerealiseerd resultaat per jaar + CSV-export voor je boekhouder
  (België: een frequent handelende bot valt vrijwel zeker onder speculatief/33%;
  Binance-rekening melden bij CAP + Vak XIII. Geen fiscaal advies.)
- **Controls** — pauzeren, posities sluiten, strategie/risk live tunen.

Beveiliging aanzetten (vóór echt geld of publieke toegang): zet
`API__DASHBOARD_PASSWORD` + `API__JWT_SECRET` in `.env`.

---

## 7. De weg naar echt geld (de trechter)

1. **Backtest groen** over meerdere regimes (sweep) ✅
2. **Grote sample** bevestigt het (alle coins, 60+ dagen).
3. **1-2 weken testnet paper-live** — vergelijk de live `Profitability Report`
   met de backtest. Komt de live profit factor in de buurt (>1)? Dan overleefde
   de edge de echte slippage.
4. **Pas dán** echt geld, en **klein** beginnen. Vereist:
   - `BINANCE__TESTNET=false` + echte mainnet-keys (Reading + Spot Trading,
     **nooit** withdrawals, met IP-whitelist),
   - `ALLOW_LIVE_REAL_ORDERS=true`,
   - dashboard-beveiliging aan,
   - een bedrag dat je 100% kunt missen.

Volledige veiligheidsgids: **`docs/LIVE_SAFETY.md`**.

---

## 8. Probleemoplossing (veelvoorkomend)

| Symptoom | Oorzaak / oplossing |
|---|---|
| `externally-managed-environment` bij pip | gebruik de venv: `.venv/bin/pip …` |
| `git pull: insufficient permission … .git/objects` | je draaide git met `sudo`. Fix: `sudo chown -R $USER ~/Bot`. Draai git **nooit** met sudo |
| Dashboard laadt niet / geen login-scherm | `cd dashboard && npm run build` + hard refresh (Ctrl+Shift+R) |
| Login lukt niet maar `curl /auth/login` geeft wel token | oude dashboard-build; rebuild (zie hierboven) |
| `reconcile_failed -1121` | opgelost; pull de laatste code |
| `warmup_skip_symbol` voor sommige coins | normaal — die coin staat niet op het testnet, wordt overgeslagen |
| `cache_write_failed … pyarrow` bij backtest | onschuldig; `pip install pyarrow` voor caching (optioneel) |
| `candles=0` bij backtest | tijdelijke Binance rate-limit; wacht ~30s en herhaal |
| Twee instances tegelijk | `pkill -f quantbot` en start er één |

---

## 9. Verdere documentatie

- **`docs/LANGE_TERMIJN_TEST.md`** — bevroren config + protocol voor de lange testnet-test.
- **`docs/OVH_SETUP.md`** — server opzetten, stap voor stap.
- **`docs/LIVE_SAFETY.md`** — alles vóór echt geld.
- **`docs/TESTNET_PAPER_TRADING.md`** — testnet paper-trading uitleg.
- **`docs/RUN_24_7.md`** — 24/7 draaien + state-persistence.
- **`docs/ARCHITECTURE.md`** / **`docs/STRUCTURE.md`** — hoe het systeem in elkaar zit.
- **`docs/REALISTIC_FILLS_REPORT.md`** — waarom we realistische fills gebruiken.
- **`README.md`** — projectoverzicht + CLI-commando's.

---

## 10. Samengevat

Je hebt een **compleet, getest, productieklaar systeem** met: een
backtest-gevalideerde strategie, een snelle iteratie-lus (replay/sweep), een rijk
dashboard, veilige 24/7-deployment en een eerlijk validatie-proces. Wat het systeem
**niet** doet — en wat geen enkel eerlijk systeem doet — is winst garanderen. De
volgende stap is geen code, maar **geduld**: laat de gevalideerde config op testnet
draaien, lees wekelijks het Profitability Report, en laat de cijfers beslissen.
