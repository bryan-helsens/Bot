# Multi-coin backtest — echte data

**Datum:** 2026-05-30 · **Databron:** CoinMetrics (echte dagkoersen, GitHub) ·
**Periode:** feb 2023 – mei 2026 (~3,2 jaar, 1200 dagen/coin)

21 coins getest met **4-strategie confluence** (consensus ≥ 2: EMA-cross, MACD,
Breakout, Mean-Reversion), 3% risico/trade, 10% stop, trailing-stop + multi-TP.
Spot-modus (long-only, sell = exit). Commissie 0,1% + slippage + spread.

---

## Resultaten per coin

| Coin | Buy & Hold | Bot | vs B&H | Trades | Win% | Sharpe |
|------|-----------:|----:|-------:|-------:|-----:|-------:|
| AAVE | +10,5% | +1,9% | −8,7% | 39 | 54% | 0,11 |
| ADA | −37,3% | **+14,3%** | **+51,7%** | 31 | 52% | 0,44 |
| ALGO | −48,4% | −2,8% | +45,6% | 22 | 45% | −0,08 |
| BCH | +179,1% | +11,6% | −167,5% | 33 | 45% | 0,29 |
| BNB | +108,7% | +1,9% | −106,8% | 12 | 33% | 0,14 |
| BTC | +171,8% | +22,9% | −148,9% | 39 | 62% | 0,83 |
| COMP | −54,4% | −17,5% | +36,9% | 28 | 43% | −0,50 |
| DOGE | +10,5% | +3,0% | −7,6% | 38 | 47% | 0,14 |
| DOT | −79,8% | −5,7% | +74,2% | 41 | 46% | −0,12 |
| ETC | −57,5% | −2,5% | +55,0% | 27 | 48% | −0,04 |
| ETH | +10,7% | +4,2% | −6,5% | 45 | 60% | 0,17 |
| LINK | +30,4% | −18,5% | −48,9% | 56 | 43% | −0,41 |
| LTC | −42,3% | −8,6% | +33,6% | 8 | 25% | −0,63 |
| MKR | +130,8% | **+27,2%** | −103,7% | 60 | 55% | 0,59 |
| SNX | −88,6% | −9,3% | +79,4% | 16 | 31% | −0,38 |
| SUSHI | −81,7% | −15,1% | +66,6% | 8 | 12% | −0,97 |
| TRX | +448,0% | +21,8% | −426,2% | 33 | 55% | 0,45 |
| UNI | −44,5% | −8,1% | +36,4% | 8 | 12% | −0,63 |
| XLM | +37,7% | +0,7% | −37,0% | 17 | 47% | 0,07 |
| XRP | +168,3% | −4,9% | −173,1% | 16 | 38% | −0,26 |
| YFI | −70,9% | −5,2% | +65,7% | 18 | 44% | −0,12 |

---

## Samenvatting

| Metric | Buy & Hold | Bot |
|--------|-----------:|----:|
| Gemiddeld rendement | **+33,4%** | +0,5% |
| Mediaan rendement | — | −2,5% |
| Rendementsspreiding (std) | 127,0% | **12,6%** |
| Bereik | −88,6% … +448,0% | −18,5% … +27,2% |

- **Bot winstgevend op 10/21 coins.**
- **Bot versloeg buy & hold op 10/21 coins.**

### De kerninzicht: kapitaalbehoud

| Op de **10 coins die daalden** | Buy & Hold | Bot |
|--------------------------------|-----------:|----:|
| Gemiddeld rendement | **−60,6%** | **−6,0%** |
| Bot versloeg B&H | — | **10/10 coins** |

Dit is precies het ontwerpdoel: **kapitaalbehoud**. Waar buy & hold catastrofaal
verloor (DOT −80%, SNX −89%, SUSHI −82%), beperkte de bot het verlies tot enkele
procenten dankzij stops, trailing-stops en het niet-vasthouden in dalende trends.

---

## Eerlijke interpretatie

1. **In een bull-markt verliest de bot van buy & hold.** Logisch: een trend-volgende
   bot met stops zit niet 100% van de tijd long; hij mist een deel van de rally
   (BTC +172% B&H vs +23% bot). Dat is de prijs van risicobeheer.

2. **In bear-markten beschermt de bot dramatisch beter** (−6% vs −61%). De waarde
   zit in de **asymmetrie**: beperkt verlies bij dalingen, deelname (niet maximaal)
   bij stijgingen.

3. **Veel lagere volatiliteit:** bot-spreiding 12,6% vs 127% voor buy & hold. Veel
   voorspelbaarder, minder afhankelijk van welke coin je koos — een echte
   eigenschap van risicobeheer.

4. **Geen winstgarantie.** Het gemiddelde bot-rendement (+0,5%) is na 3,2 jaar
   marginaal; de standaardparameters hebben geen sterke edge. Net als eerder geldt:
   een betrouwbare edge vereist **walk-forward-gevalideerde** parameters
   (zie `docs/OPTIMIZATION.md`), niet de defaults.

5. **Accounting bleef exact kloppen** over alle 21 coins
   (`final_equity == initial + Σ net_pnl`, afwijking < 0,01).

---

## Conclusie

Over 21 coins en 3,2 jaar echte data gedraagt de bot zich **zoals een goed
risicobeheerd systeem hoort**: hij maakt je niet rijk in een bull-run, maar hij
**beschermt je kapitaal consistent in dalingen (10/10)** en levert veel stabielere,
coin-onafhankelijke resultaten dan kopen-en-vasthouden. Of hij netto winst maakt
hangt volledig af van het marktregime en — vooral — van gevalideerde parameters.
