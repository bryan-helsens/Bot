# 🧊 Lange-termijntest — bevroren config & protocol

Dit is je **bevroren test-config** voor de lange rit op testnet (nepgeld). Het doel:
ontdekken wat de strategie over **meerdere maanden en marktregimes** gemiddeld doet,
zonder risico en zonder te tweaken.

> **De gouden regel: niet aankomen.** Elke wijziging reset het experiment. Pas de
> config pas aan na de afgesproken periode hieronder — niet na een slechte dag/week.

---

## De bevroren config

**`config/strategies.yaml`** — RSI-only:
```yaml
strategies:
  - name: rsi_dip_buyer
    class: RSIStrategy
    enabled: true
    timeframes: [5m, 15m]
    params:
      period: 14
      oversold: 35
      overbought: 70
      trend_filter: false
      trend_period: 50
  - name: ema_trend
    enabled: false
```

**`.env`** — de kerninstellingen:
```bash
RISK__RISK_PER_TRADE=0.003
RISK__DEFAULT_STOP_LOSS_PCT=0.025     # 1:1 reward/risk
RISK__TAKE_PROFIT_LEVELS=0.025:1.0
RISK__TRAILING_STOP_PCT=0.05
RISK__MAX_OPEN_TRADES=8
RISK__EXIT_ON_OPPOSITE_SIGNAL=false
RISK__REENTRY_COOLDOWN_SECONDS=1800
BACKTEST__INITIAL_CAPITAL=100
BINANCE__TESTNET=true                 # nepgeld — niet wijzigen voor deze test
```

---

## Protocol

1. **Schone start (eenmalig):**
   ```bash
   cd ~/Bot
   rm data/state.json
   sudo systemctl restart quantbot
   ```
   Noteer de startdatum hieronder.
2. **Laat draaien — minimaal 3 maanden.** 24/7 (systemd). Niet stoppen bij een slechte week.
3. **NIET tweaken** tot de einddatum. Geen oversold, geen stops, geen coins aanpassen.
4. **Maandelijks** (niet vaker) één meting noteren in de tabel hieronder, via:
   ```bash
   curl -s -H "$H" "localhost:8000/portfolio/report?days=90"
   ```
   (zie de handleiding voor het ophalen van het token)

---

## Beslisregel (vooraf vastgelegd, zodat emotie niet beslist)

Na minimaal **3 maanden**:
- **Profit factor > 1,1 én verslaat buy & hold** over de hele periode → de moeite waard;
  pas dán praten over een eventuele kleine echt-geld-test (mét fiscalist, zie Belasting-pagina).
- **Rond break-even (PF 0,9–1,1)** → kapitaalbehoud-bot, geen edge; leuk als leerproject,
  geen echt geld.
- **Profit factor < 0,9** → geen edge; stoppen of een fundamenteel andere aanpak overwegen.

---

## Resultatenlog (zelf invullen)

| Datum | Dagen actief | Equity | Profit factor | Win rate | vs Buy&Hold | Notitie |
|---|---|---|---|---|---|---|
| (start) | 0 | 100,00 | — | — | — | schone start |
|  |  |  |  |  |  |  |
|  |  |  |  |  |  |  |
|  |  |  |  |  |  |  |

---

## Onthoud

- Dit is **nepgeld**. Er valt niets te verliezen — alleen te leren.
- De grootste fout zou zijn om **op basis van ruis te blijven sleutelen**. De waarde
  zit nu in geduldig meten.
- "Geen edge gevonden" is een **geldig en waardevol** eindresultaat — het bespaart je
  echt geld.
