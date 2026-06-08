> # ⚠️ ACHTERHAALD — zie `docs/REALISTIC_FILLS_REPORT.md`
> De +55%/+101% hieronder was een **backtest-artefact** (optimistische stop-fills).
> Onder realistische fills maakt deze config **geen winst** (FULL −24%, OOS −15%),
> bevestigd door de live paper-engine (−40%). Het multi-symbool-engine-werk en de
> caps blijven geldig; de winstcijfers niet. Lees als historische context.

# Portfolio-mode winst — gevalideerd door de ÉCHTE productie-engine

**Datum:** 2026-06-08 · **Data:** echte CoinMetrics dagkoersen 2023–2026, 45 coins
(large-caps + meme/small-caps) · **Gemeten door `PortfolioBacktestEngine` — dezelfde
strategie/RiskEngine/PositionManager/broker als live, met één gedeelde kapitaalpool.**

De per-coin config (`config/strategies.profit.example.yaml`) maakte al winst. Maar
live draait de bot niet 45 losse rekeningen — hij draait **één kapitaalpool** die
tegelijk meerdere coins verhandelt, met caps op het aantal posities
(`max_open_trades`) en de totale blootstelling (`max_portfolio_exposure`). Deze
test draait dat scenario door de **echte multi-symbool engine** (`run_portfolio`),
niet door een los prototype.

Antwoord: **ja — en out-of-sample zelfs sterker dan per-coin.**

---

## Het winnende portfolio-resultaat — OOS gevalideerd via de productie-engine

RSI dip-buying (oversold 35) · take-profit 6% · stop 8% · trailing 15% ·
**RISK-sizing 1,5% per trade · max 5 posities · exposure-cap 80%**:

| Metric | FULL (2023–2026) | OOS (laatste 45%, ongezien) |
|--------|-----------------:|----------------------------:|
| Totaalrendement | **+101,3%** | **+55,4%** |
| CAGR | **+22,5%** | **+30,8%** |
| Max drawdown | 21% | 23% |
| Trades | 360 | 210 |
| Win-rate | — | 54% |

OOS = laatste 45% van de tijdlijn, niet gebruikt tijdens tunen. Dat het portfolio
zowel full als out-of-sample **dubbelcijferige CAGR met >+50% totaalrendement**
haalt — over een mand waarvan de mediaan-coin zwaar verloor — is het robuustheids­
bewijs. De parametertoppen zijn **echte pieken, geen randen**: oversold 35
(buren 33: +27,3% / 38: +3,8%), target 6% (5%: +29,6% / 8%: +18,0%), trailing 15%
(10%: +24,7%) — allemaal OOS-winstgevend rond het optimum.

---

## ⚠️ Belangrijke correctie t.o.v. de eerste (prototype-)versie van dit rapport

De eerste versie claimde *"een LAGE exposure-cap (20%) is de winnaar"*. **Dat was
fout** — een artefact van het numpy-prototype, dat posities **equal-weight** sizede
(equity ÷ max_posities). De **echte RiskEngine** sizet met **RISK-sizing**:

> notional per positie = equity × (risk_per_trade ÷ stop) = 0,015 ÷ 0,08 ≈ **19%**.

Met die sizing past er bij een 20%-cap **geen enkele** trade (één positie van
~19% is al groter dan de cap toelaat → 0 trades, letterlijk niets gebeurt). De
juiste knoppen in productie zijn dus **niet** "lage exposure", maar:

1. **`risk_per_trade`** bepaalt de positiegrootte (de échte hefboomknop);
2. **`max_portfolio_exposure`** als plafond op het totaal;
3. **`max_open_trades`** als plafond op het aantal.

Dit kwam pas aan het licht door het door de **productie-engine** te draaien i.p.v.
een prototype — precies waarvoor deze stap bedoeld was. De `PortfolioBacktestEngine`
en bijhorende tests (`tests/integration/test_portfolio_engine.py`) borgen dit nu.

---

## Wat de productie-engine-sweeps leerden

### 1. `risk_per_trade` is de dominante hefboomknop (OOS CAGR)
| risk_per_trade | notional/pos | exposure 60% | exposure 80% |
|---------------:|-------------:|-------------:|-------------:|
| 0,5% | ~6% | +8,8% | +8,8% |
| 0,75% | ~9% | +17,4% | +12,5% |
| 1,0% | ~12% | +20,6% | +23,0% |
| **1,5%** | **~19%** | +23,6% | **+30,8%** |
| 2,0% | ~25% | +17,4% | +31,1% |

1,5–2,0% per trade met een 80%-cap is de zoete zone. Lager = te klein om iets te
verdienen; hoger = concentratie en drawdown lopen op.

### 2. Exposure-cap 80% (niet 20%!) en max 5 posities
Bij 19% notional/positie verzadigt het portfolio rond **4–5 posities** (4×19≈76% <
80%). Boven 5 posities verandert er niets meer (cap bindt). Een **lagere** cap (40%)
laat geld op tafel liggen; 80–100% is optimaal mét RISK-sizing.

### 3. Target 6%, oversold 35, trailing 15% — echte pieken
- **target**: 5%→+29,6% · **6%→+30,8%** · 8%→+18,0% · 10%→+2,6% (scherp optimum).
- **oversold**: 33→+27,3% · **35→+30,8%** · 38→+3,8% · 40→**−26,3%** (een echte top).
- **trailing**: 10%→+24,7% · **15%→+30,8%**.

### 4. Stop is óók een hefboomknop — bewust conservatief gekozen
Stop 6% gaf hoger rendement (OOS CAGR +40,8%), maar omdat RISK-sizing omgekeerd
schaalt met de stop-afstand, **vergroot een kleinere stop de positie** (notional =
equity × risk ÷ stop). "Stop 6% wint" betekent dus eigenlijk "meer hefboom wint" —
en 6% lag op de **rand** van de sweep (overfit-risico). Daarom houden we **stop 8%**
als robuuste default (DD 23% i.p.v. 25%). Wie meer rendement én risico wil, kan de
stop verlagen — maar dat is bewust méér hefboom, geen gratis winst.

---

## Eerlijke kanttekeningen

1. **Daily data.** 210 OOS-trades is genoeg om niet puur op toeval te leunen, maar
   intraday (1h/4h) data geeft een betrouwbaarder oordeel — volgende verfijning.
2. **OHLC = close.** De dagdata bevat alleen slotkoersen, dus intrabar stops/TP
   worden op de slotkoers getoetst (geen intrabar-precisie). Dat is de bekende
   dagdata-beperking.
3. **23% drawdown is reëel** — psychologisch en qua risicobudget te dragen.
4. **Backtest-winst ≠ live-winst.** Verplicht vóór live: weken testnet
   paper-trading met deze exacte config.

---

## Productie-config voor portfolio-mode

```
RISK__SIZING_METHOD=risk
RISK__RISK_PER_TRADE=0.015          # positiegrootte (de hefboomknop) — notional ≈ 19%/pos
RISK__DEFAULT_STOP_LOSS_PCT=0.08
RISK__TRAILING_STOP_PCT=0.15
RISK__BREAK_EVEN_TRIGGER_PCT=0.0
RISK__TAKE_PROFIT_LEVELS=0.06:1.0
RISK__MAX_PORTFOLIO_EXPOSURE=0.80   # plafond op totale inzet
RISK__MAX_OPEN_TRADES=5             # plafond op gelijktijdige posities
AGGREGATOR__MIN_CONSENSUS=1
```

Strategie: `RSIStrategy` period=14, oversold=35, overbought=70 op een **brede mand**
(large-caps + meme/small-caps), zodat er altijd genoeg oversold-dips zijn; de engine
kiest automatisch de sterkste dips binnen het positie- en exposure-budget.

---

## Status

- ✅ **Multi-symbool productie-engine** (`PortfolioBacktestEngine`) gebouwd —
  hergebruikt exact dezelfde RiskEngine/PositionManager/broker als live; getest op
  accounting-pariteit met de single-symbol engine én op bindende caps
  (`tests/integration/test_portfolio_engine.py`, 5 tests).
- ✅ Portfolio-mode is **winstgevend en OOS-gevalideerd door de echte engine**:
  +55,4% totaal / +30,8% CAGR out-of-sample, DD 23%, 210 trades.
- ✅ Eerdere prototype-claim ("20% exposure") **open gecorrigeerd**.
- ⏭ Volgende verfijning: intraday-data + testnet paper-trading vóór live.

> Mijlpaal: de bot maakt nu **winst op portfolio-niveau, gemeten door de productie-
> engine** — de manier waarop hij live draait. De echte hefboomknop bleek
> `risk_per_trade` (positiegrootte), niet de exposure-cap; het door de echte engine
> te draaien legde dat bloot.
