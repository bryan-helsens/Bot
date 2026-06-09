# Testnet paper-trading — opzet en draaiboek

Doel: de bot **wekenlang op het Binance testnet laten paper-traden** met echte
live-koersen, zodat je op échte uitvoering valideert vóór er ooit echt geld aan te
pas komt. Dit is de eerlijke vervolgstap na de backtest-correctie
(`docs/REALISTIC_FILLS_REPORT.md`): op korte candles vullen stops dicht bij hun
niveau, dus paper-trading meet wat de backtest niet kan weten.

> ⚠️ Dit moet op **jouw machine** draaien, niet in de cloud-sandbox van deze sessie:
> die blokkeert alle exchange-API's (alleen GitHub-raw is bereikbaar). Op je eigen
> machine met internettoegang werkt alles hieronder.

## Sneller starten (kant-en-klaar)

```bash
cp .env.testnet.example .env                          # echte koersen, nepgeld
cp config/strategies.paper.example.yaml config/strategies.yaml
# vul BINANCE__API_KEY en BINANCE__API_SECRET in .env in (zie stap 1)
python scripts/test_testnet.py --order --paper        # preflight, moet groen zijn
quantbot run                                          # start de bot
```

### Twee modi (beide nepgeld, beide echte koersen)
- **`TRADING_MODE=live`** (default in `.env.testnet.example`): orders gaan **echt**
  naar de testnet-beurs — het meest realistisch ("echte bedragen"). Op testnet is
  dit gratis nepgeld; de veiligheids-opt-in geldt alleen voor mainnet.
- **`TRADING_MODE=paper`**: fills lokaal gesimuleerd tegen een interne balans. Zet
  dit als je liever eerst zonder echte order-plaatsing begint. Eén regel omzetten.

---

## 0. Vereisten

- Python 3.12+, de repo geïnstalleerd (`pip install -e .` of `uv sync`).
- Uitgaande internettoegang naar `testnet.binance.vision`.
- **Geen** Postgres/Redis/dashboard nodig voor paper-trading (optioneel voor
  monitoring — zie §6). De engine draait standalone.

## 1. Maak SPOT-testnet-keys

1. Ga naar **https://testnet.binance.vision/** en log in met GitHub.
2. Genereer een **HMAC-SHA256** API-key.
3. Rechten: **Reading + Spot Trading** aanzetten. **Withdrawals NOOIT** (testnet
   heeft geen echt geld, maar maak er meteen een veilige gewoonte van).
4. Fund je testnet-account via de faucet-knop (gratis test-USDT).

## 2. Configureer `.env`

```bash
cp .env.example .env
cp config/strategies.paper.example.yaml config/strategies.yaml
```

Zet in `.env` minimaal:

```
TRADING_MODE=paper
BINANCE__MARKET=spot
BINANCE__TESTNET=true
BINANCE__API_KEY=<jouw testnet key>
BINANCE__API_SECRET=<jouw testnet secret>

SYMBOLS=BTCUSDT,ETHUSDT,BNBUSDT
TIMEFRAMES=5m,15m
STRATEGIES_CONFIG=config/strategies.yaml

# Confluence laag houden zodat de enkele strategie kan handelen
AGGREGATOR__MIN_CONSENSUS=1

# Conservatief risico — KLEIN beginnen
RISK__SIZING_METHOD=risk
RISK__RISK_PER_TRADE=0.005
RISK__DEFAULT_STOP_LOSS_PCT=0.03
RISK__TRAILING_STOP_PCT=0.05
RISK__BREAK_EVEN_TRIGGER_PCT=0.0
RISK__TAKE_PROFIT_LEVELS=0.02:1.0
RISK__MAX_OPEN_TRADES=3
RISK__MAX_PORTFOLIO_EXPOSURE=0.30
RISK__MAX_DAILY_LOSS=0.05
RISK__MAX_DRAWDOWN=0.20
RISK__EMERGENCY_STOP_ENABLED=true

# Paper-startkapitaal (in USDT)
BACKTEST__INITIAL_CAPITAL=10000
BACKTEST__COMMISSION=0.001
BACKTEST__SLIPPAGE=0.0005
```

`.env` staat in `.gitignore` — **committen verboden**.

## 3. Preflight — verifieer de hele stack tegen het testnet

Er is een kant-en-klaar end-to-end verificatiescript (6 fasen: connectiviteit →
market data → getekend account-request → websocket → order plaatsen/annuleren →
korte paper-loop op live koersen):

```bash
python scripts/test_testnet.py            # fasen 1-4 (connectiviteit, data, auth, WS)
python scripts/test_testnet.py --order    # + een test-order plaatsen en annuleren
python scripts/test_testnet.py --paper    # + een korte live paper-loop door de echte engine
python scripts/test_testnet.py --order --paper --duration 30   # alles, langer venster
```

Exitcode 0 = alles groen. Veelvoorkomend: bij "zero USDT balance" → gebruik de
faucet; bij "clock drift" → synchroniseer je systeemklok (NTP).

## 4. Start de continue paper-trading

```bash
quantbot run
```

De engine verbindt met het testnet, warmt de candle-historie op, abonneert op
gesloten candles en draait de **echte** beslis- en uitvoeringslus in paper-mode
(geen order bereikt ooit een echte beurs). Stop met Ctrl-C.

Tip: draai het in `tmux`/`screen` of als service zodat het wekenlang doorloopt.
Voor 24/7: zie `scripts/install_vps.sh` en `docs/DEPLOYMENT.md`.

## 5. Wat te monitoren

- **Equity-curve & drawdown** — daalt het gestaag of stabiel?
- **Trades**: entry/exit-prijzen, of stops dicht bij hun niveau vullen (op 5m/15m
  hoort dat zo te zijn — dát is de winst t.o.v. de daag-backtest).
- **Risk-events** in de log: afgewezen orders (exposure/cap/circuit-breaker).
- **Win-rate, gemiddelde winst/verlies, profit factor** over voldoende trades.

Logs zijn gestructureerd (`LOG_FORMAT=console` lokaal leesbaar; `json` voor
verzameling). Notificaties (Telegram/Discord/e-mail) kun je in `.env` aanzetten
onder `NOTIFICATIONS__*`.

## 6. Optioneel: monitoring-dashboard

```bash
quantbot api          # FastAPI-backend op :8000
# en in dashboard/: npm install && npm run dev   (React-UI op :5173)
```

## 7. Wanneer mag je naar live? (eerlijke graduatie-criteria)

Pas overwegen na **weken** paper-trading mét:

- [ ] Positieve of minstens **kapitaal-behoudende** equity over meerdere
      marktregimes (niet alleen één rally).
- [ ] Drawdown binnen je vooraf bepaalde grens (bv. < 20%).
- [ ] Voldoende trades (richtlijn 100+) zodat het geen toeval is.
- [ ] Stops die in de praktijk vullen zoals verwacht (controleer de fills).
- [ ] Geen onverklaarde risk-events of engine-fouten.

Zelfs dán: begin live met **minimaal** kapitaal en dezelfde conservatieve risico-
instellingen. Verhoog pas na bewezen gedrag.

> Eerlijk blijven: geen enkele config is tot nu toe bewezen winstgevend onder
> realistische aannames. Paper-trading is er om dat eerlijk te meten op échte
> uitvoering — niet om een backtestgetal te bevestigen.
