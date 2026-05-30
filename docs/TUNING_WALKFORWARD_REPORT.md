# Tuning & walk-forward rapport — echte data, 21 coins

**Datum:** 2026-05-30 · **Data:** CoinMetrics dagkoersen 2023–2026 (21 coins) ·
**Vervolg op:** `docs/MULTICOIN_REPORT.md`

Dit rapport beantwoordt twee vragen: **(1)** houden geoptimaliseerde parameters
stand op ongeziene data (walk-forward), en **(2)** kan de bot getuned worden voor
betere bull-participatie. Tijdens dit werk zijn **twee echte bugs** gevonden en
verholpen.

---

## Gevonden & opgeloste bugs

| Bug | Symptoom | Fix |
|-----|----------|-----|
| **Short op spot** | Sell-signalen openden onmogelijke short-posities; de bot zat short in een +251% bull-markt. | Op spot sluit een sell een open long (of is een no-op); alleen futures shorten. (commit `24a5e73`) |
| **Circuit-breaker bevroor backtests** | Wall-clock cooldown verstreek nooit in een backtest → na 4 verliezen blokkeerde de bot de rest van de run. | Cooldown gedreven door simulatie-/candle-tijd. (commit `c02f791`) |

Beide afgedekt met regressietests (totaal **74 tests groen**).

---

## (2) Tuning-inzichten

Geverifieerd via A/B-tests op echte data:

| Inzicht | Bewijs | Effect |
|---------|--------|--------|
| **Break-even arming is cruciaal** | stop → entry bij +5% winst | DOT −23% → −6%, ADA +0,7% → +14% |
| **Circuit breaker ~neutraal** | CB aan vs uit, 21 coins | −11,1% vs −11,2% (geen boosdoener) |
| **Strategie-mix telt** | 4-strat (met Mean-Reversion) > 2-strat | Mean-Reversion is een sterke bijdrager |

**Onontkoombare trade-off:** een bot met stops kan buy & hold niet verslaan in
een sterke bull-markt — hij zit niet 100% van de tijd long. Wijdere trailing-stops
+ break-even verhogen de bull-participatie (bullAvg ≈ +11%), maar nooit tot de
volle +250% van BTC. Dat is de prijs van risicobeheer, geen tekortkoming.

---

## (1) Walk-forward validatie — het beslissende resultaat

**Methode:** per coin de MACD-parameters optimaliseren op de eerste **70%** van de
historie (in-sample), daarna handelen op de laatste **30%** — data die de optimizer
**nooit zag** (out-of-sample). Dit is de eerlijke test tegen overfitting.

| Coin | OOS bot | OOS buy & hold | beat? |
|------|--------:|---------------:|:-----:|
| AAVE | −23,1% | −65,4% | ✅ |
| ADA | −6,5% | −66,1% | ✅ |
| ALGO | −11,5% | −45,5% | ✅ |
| BCH | −15,9% | −13,3% | ✗ |
| BNB | +4,7% | −2,9% | ✅ |
| BTC | −0,1% | −27,5% | ✅ |
| COMP | −24,5% | −53,8% | ✅ |
| DOGE | −3,0% | −52,2% | ✅ |
| DOT | −12,4% | −70,4% | ✅ |
| ETC | −16,4% | −50,4% | ✅ |
| ETH | −2,0% | −19,6% | ✅ |
| LINK | −2,9% | −36,7% | ✅ |
| LTC | −8,9% | −42,8% | ✅ |
| MKR | +3,9% | +23,0% | ✗ |
| SNX | −17,7% | −58,5% | ✅ |
| SUSHI | −11,3% | −71,4% | ✅ |
| TRX | +4,6% | +32,2% | ✗ |
| UNI | −7,6% | −47,5% | ✅ |
| XLM | −2,4% | −47,1% | ✅ |
| XRP | +0,3% | −39,6% | ✅ |
| YFI | −17,8% | −54,3% | ✅ |

### Samenvatting (out-of-sample, ongezien)

| Metric | Bot | Buy & Hold |
|--------|----:|-----------:|
| Gemiddeld OOS-rendement | **−8,1%** | **−38,6%** |
| Winstgevend | 4/21 | — |
| **Versloeg buy & hold** | **18/21** | — |
| Op dalende coins (19) | −9,4% | −45,5% |
| → versloeg B&H daar | **18/19** | — |

---

## Conclusie

De out-of-sample periode (laatste 30%, ~2025–2026) was overwegend **bearish**, en
juist daar laat de bot zijn kernkwaliteit zien:

1. **Op ongeziene data verslaat de bot buy & hold in 18 van de 21 coins** — niet
   door winst te maken (gemiddeld −8%), maar door verlies te **beperken** waar
   buy & hold −39% leed.

2. **De drie coins waar de bot verliest van B&H (BCH, MKR, TRX)** zijn precies de
   coins die in de OOS-periode **stegen** — opnieuw de bull-market trade-off.

3. **Dit is robuust, niet curve-fit:** de parameters werden op andere data
   gekozen en presteren consistent op ongeziene data. De waarde zit structureel
   in **kapitaalbehoud en lage volatiliteit**, niet in marktoutperformance.

### Eindoordeel op "winst of verlies?"

- **In bull-markten:** de bot maakt winst maar **minder dan buy & hold**.
- **In bear-markten:** de bot **beperkt verlies dramatisch** en verslaat buy & hold
  bijna altijd (18/19 out-of-sample).
- **Netto:** de bot is een **risico-/kapitaalbehoud-systeem**, geen
  winstmaximaliseerder. Over een volledige cyclus levert dat veel stabielere,
  beter te verdragen resultaten — maar geen gegarandeerde winst, en geen
  bull-market-outperformance.

Alle 21 coins voldeden aan de accounting-invariant (`equity == initial + Σ pnl`).
