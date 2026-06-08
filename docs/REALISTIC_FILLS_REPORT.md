# ⚠️ Correctie: de eerdere "winst" was een backtest-artefact (stop-fill bug)

**Datum:** 2026-06-08 · **Hoe ontdekt:** door de bot in PAPER-mode door de échte
live-engine te draaien en het resultaat te vergelijken met de backtest.

Dit rapport corrigeert de eerdere winstclaims openhartig. **Kort:** de gerapporteerde
+55% tot +101% was een gevolg van een onrealistische aanname in de backtest over hoe
stop-loss orders gevuld worden. Onder realistische aannames maakt de strategie op
deze dagdata **geen winst**.

---

## Hoe het aan het licht kwam

Ik heb een paper-trading-replay gebouwd (`scripts/papertrade_replay.py`) die de
**echte live `TradingEngine`** (strategie → aggregator → RiskEngine → executor →
PaperTradingBroker → portfolio) bar voor bar over de historische candles draait — de
laatste check vóór een echte testnet. Zelfde config, zelfde data:

| Pad | Resultaat |
|-----|----------:|
| Backtest (zoals gerapporteerd) | **+101%** |
| Live paper-engine (zelfde config) | **−40%** |

Een kloof van ~140 procentpunten. Dat is geen ruis — het betekende dat de backtest
en het live-pad **fundamenteel iets anders deden**.

## De oorzaak: optimistische stop-fills

De backtest vulde een stop-loss **exact op de stopprijs**. Maar koersen *gappen*: een
munt kan ver onder zijn stop sluiten. Dan boekt de backtest een klein verlies (−8%),
terwijl je in werkelijkheid op de veel lagere koers wordt gevuld (−25%). Over honderden
trades op volatiele alts blies dat het resultaat kunstmatig op.

| Zelfde winnende config (45 munten) | FULL | OOS |
|------------------------------------|-----:|----:|
| **Optimistische fills** (oud, buggy) | +101,3% | +55,4% |
| **Realistische fills** (nu, gefixt) | **−23,8%** | **−15,1%** |
| Live paper-engine | **−40,3%** | — |

Realistisch en live liggen nu in dezelfde orde (beide fors negatief). De fix
verzoent backtest en live.

## De fix

`BacktestEngine` vult een stop nu standaard **realistisch**: als de bar voorbij de
stop opent, vul je op de open (gap-through), niet op de stop. Een vlag
`optimistic_stops=True` houdt het oude gedrag beschikbaar om beide grenzen te meten.
Geborgd door `tests/integration/test_realistic_fills.py`.

---

## De eerlijke bevinding onder realistische fills

Op dit mandje (45 munten, 2023–2026, met een diep-berenmarkt OOS-staart: buy & hold
OOS −32%) is de long-only RSI-mean-reversion-strategie **niet absoluut winstgevend**.
Uitputtend getest, niets draait het om:

| Knop getest | Beste OOS | Winstgevend? |
|-------------|----------:|:------------:|
| Stopbreedte 8%→90% | −19% (geen stop) | nee |
| Sizing / risk-per-trade | — | nee |
| Exposure-cap 40%→100% | −15% | nee |
| Profit-target 6%→25% | −17% | nee |
| **Regime-filter** (alleen dips kopen in uptrend) | −12% | nee |

De enige "edge" is **defensief**: in de berenmarkt verliest de strategie ~12–20%
terwijl buy & hold −32% verliest. Maar op de volledige cyclus (buy & hold +24%)
**onderpresteert** ze buy & hold fors. Dat is geen winstmachine.

**Waarom:** een long-only strategie kan geen absolute winst maken wanneer het hele
mandje daalt; en dagelijkse stops gappen door. De "winst" die ik eerder zag, was
volledig de fill-aanname.

---

## Een cruciale nuance (en waarom dagdata onvoldoende is)

Crypto handelt **24/7 — geen overnight gaps zoals aandelen**. Op *dag*-bars is
"vullen op de slotkoers" conservatief-pessimistisch; "vullen op de stop" is
optimistisch. Een live bot die continu meekijkt (op 1m/5m candles) zou een stop
dichter bij zijn niveau vullen. De **waarheid ligt tussen beide grenzen in en is
alleen met intraday-data te bepalen** — een dagelijkse backtest kent het intraday-pad
niet. Daarom is de `optimistic_stops`-vlag er: om beide grenzen expliciet te tonen,
niet om er stilletjes één aan te nemen.

Eerste intraday-check (echte BTC 1-min → 1h/4h, jan-2025–jun-2026): ook **verlies**
(−18% tot −23%), al verslaat het buy & hold (−38%). Maar dat is één munt in een
neergaande markt — niet de cross-sectionele meerdere-munten-strategie, waarvoor geen
intraday-data beschikbaar was via het toegestane netwerk.

---

## Wat dit waard is

- ✅ **Een catastrofale bug gevonden en gefixt** die live ~40% had gekost. De bot is
  nu *eerlijk*: backtest ≈ paper ≈ (verwacht) live.
- ✅ **Live-pad gevalideerd** end-to-end via paper-replay — dit is de winst van deze
  sessie, belangrijker dan een mooi-ogend backtestgetal.
- ❌ **Geen aangetoonde winstgevende dag-config** onder realistische aannames. Ik ga
  geen winst claimen die er niet is.

## Eerlijke aanbeveling — de weg naar échte winst

1. **Intraday-data voor veel munten** (1h/4h) om de cross-sectionele edge eerlijk te
   meten met fills dicht bij de stop. (Niet beschikbaar via het huidige sandbox-
   netwerk; alleen GitHub-raw is bereikbaar — BTC kreeg ik, een breed mandje niet.)
2. **Echte testnet paper-trading**: zet `TRADING_MODE=paper`, `BINANCE__TESTNET=true`
   + testnet-keys en draai `quantbot run` (op een machine mét exchange-toegang). Laat
   dat weken lopen vóór één euro echt geld.
3. **Heroverweeg de strategie-kern**: long-only mean-reversion is defensief, geen
   winstmotor in dalende markten. Overweeg regime-cash, of futures-short-mogelijkheid,
   of een andere edge — en valideer élke variant tegen het paper-pad, niet alleen de
   backtest.

> De belangrijkste verbetering van deze sessie is **eerlijkheid**: de bot rapporteert
> nu wat hij werkelijk zou doen, niet een opgeblazen backtest. Dat is meer waard dan
> een vals winstcijfer.
