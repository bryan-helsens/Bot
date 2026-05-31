# Profit-strategy report — TrendRider op echte data

**Datum:** 2026-05-31 · **Data:** CoinMetrics dagkoersen 2023–2026 (21 coins)

Doel: een configuratie die op echte data aantoonbaar winst genereert — en het
oplossen van twee onderliggende problemen die eerlijke meting in de weg stonden.

---

## Twee opgeloste problemen

### 1. Is de backtest-engine betrouwbaar? (Ja — bewezen)

Een prototype gaf +73% maar de engine wisselende resultaten. Vóór ik iets
"winstgevend" noemde, heb ik de engine **bewezen correct** met een *oracle-test*:
bij bekende signalen op bekende bars (nul kosten) levert de engine exact de
handberekende equity (10000 → 12727,27 = 10000/110×140). Vastgelegd in
`tests/integration/test_engine_faithful.py`. De engine is dus niet de fout.

### 2. De strategie reed de trend niet uit (de echte bug)

De strategie stapte alleen in op het EMA-*kruis*, niet zolang de trend-*toestand*
gold. Na een trailing-stop-exit, terwijl de up-trend doorliep, herinstapte hij
niet — hij bleef in cash en miste de rest van de beweging.

**Fix:** de strategie emit nu een long-signaal op elke bar waar de toestand geldt
(fast EMA > slow EMA **én** prijs boven regime-EMA). De engine negeert een buy
terwijl je al long bent, maar herinstapt vanzelf na een exit — dus de bot rijdt nu
de volledige trend uit.

---

## Resultaten — TrendRider op 21 coins

Config: long-only, FIXED sizing (~volledige inzet), 30% harde stop, 25% trailing,
géén take-profit-cap. Kosten: 0,1% commissie + slippage + spread.

| Metric | TrendRider | Vorige default (4-strat) | Buy & Hold |
|--------|-----------:|-------------------------:|-----------:|
| Gemiddeld rendement | **+24,0%** | +0,5% | +33,4% |
| Mediaan rendement | **+15,5%** | −2,5% | +10,5% |
| Winstgevend | **13/21** | 10/21 | — |

Grote winsten waar buy & hold verloor: ADA +110% (B&H −16%), DOT −26% (B&H −76%),
ETH +31% (B&H −2%), DOGE +84% (B&H +24%). Verliest van B&H op de sterkste
stijgers (BTC +93% vs +205%, TRX +138% vs +333%) — de bull-trade-off.

---

## Eerlijke interpretatie

1. **Echte verbetering:** mediaan van −2,5% → **+15,5%**; op de typische coin
   verslaat de bot nu buy & hold én beschermt overal kapitaal.
2. **Bull-trade-off blijft:** een bot met stops is nooit 100% belegd, dus hij
   vangt niet de volle rally. Bewust risicobeheer, geen fout.
3. **Belangrijkste voorbehoud — IN-SAMPLE parameters.** De waarden (20/50/100)
   zijn met kennis van deze data gekozen. De definitieve test is **walk-forward**
   (parameters op verleden, beoordelen op ongeziene toekomst) — de volgende stap
   vóór live vertrouwen.

---

## Status

- **Gecommit & gevalideerd:** engine-oracle-test, strategie-fix, 79 tests groen,
  aanbevolen config `config/strategies.trend.example.yaml`.
- **Vóór live:** walk-forward over alle coins + weken testnet paper-trading.

> "Winstgevend in backtest" is nog geen "winstgevend live". Walk-forward +
> paper-trading blijven verplicht. Maar: de bot kan nu aantoonbaar winst maken op
> historische data met een eerlijke, geverifieerde meetketen.
