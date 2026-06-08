# Meme coins & small-caps — testrapport

**Datum:** 2026-05-31 · **Data:** CoinMetrics dagkoersen 2023–2026 ·
**Set:** 26 small-cap/altcoins (1INCH, AAVE, BAL, BAT, COMP, CRV, DASH, DGB,
DOGE, EOS, FTT, KNC, LDO, MANA, MKR, NEO, OMG, REN, SNX, SUSHI, UNI, XMR, XTZ,
YFI, ZEC, ZRX)

Dit is een **stresstest**: dit mandje is brutaal — mediaan buy & hold **−64%**,
met totale wipeouts (BAL −97%, REN −96%, OMG −92%, EOS −90%) naast uitschieters
(ZEC +1930%, XMR +156%, MKR +136%).

---

## Belangrijke bug gevonden & gefixt

Tijdens deze test bleek de TrendRider **0 trades** te plaatsen — op álle coins,
inclusief BTC. Mijn eerder gerapporteerde "+24% TrendRider" was hierdoor
**onjuist** (het was 0% door nul trades).

**Oorzaak:** bij FIXED full-deployment-sizing duwde slippage de fill-notional net
boven het beschikbare cash, waarna de backtest de **hele trade stil liet vallen**
(`if fill.notional > cash: return cash`).

**Fix:** de positiegrootte wordt nu teruggeschaald zodat de kosten binnen het
kapitaal passen (zoals een exchange alleen vult wat je kunt betalen), i.p.v. de
trade te droppen. Na de fix: BTC TrendRider = **+105%** (9 trades). Commit
`6eac21c`. 79 tests groen.

---

## Resultaat 1 — TrendRider (trend-following) op meme/small-caps

| Config | Sizing | avg | mediaan | maxDD | verslaat B&H |
|--------|--------|----:|--------:|------:|:------------:|
| stop30%, trail25% | **FIXED** (full) | **−81,1%** | −83,3% | ~90% | 5/26 |
| stop15%, trail10% | RISK 2% | **−9,2%** | −8,9% | 20% | 20/26 |
| stop10%, trail8% | RISK 2% | −12,3% | −11,9% | 26% | 20/26 |

**Les:** trend-following faalt op meme-coins (scherpe pumps/dumps, geen gladde
trends). Maar — **positiegrootte domineert het resultaat**: FIXED full-deploy
(−81%, ruïne) vs RISK 2% (−9%, overleefbaar). Zelfde strategie, totaal ander lot.

## Resultaat 2 — Mean-Reversion (buy-the-dip) op meme/small-caps ✅

| Config | Sizing | avg | mediaan | maxDD | winstgevend | verslaat B&H |
|--------|--------|----:|--------:|------:|:-----------:|:------------:|
| z=2, stop10%, trail8% | RISK 2% | **+6,5%** | **+7,0%** | **12%** | **17/26** | **21/26** |

Op een mandje dat gemiddeld −64% kelderde, maakte mean-reversion **+6,5% winst**
met slechts 12% drawdown — winstgevend op 17 van 26 coins.

---

## De kernconclusie

**Verschillende marktsegmenten vragen verschillende strategieën:**

| Segment | Karakter | Beste aanpak | Resultaat |
|---------|----------|--------------|-----------|
| **Large-caps** (BTC/ETH) | gladde trends | Trend-following (ride the trend) | BTC +105% |
| **Meme/small-caps** | scherpe dips die terugveren | Mean-reversion (buy dips) | +6,5% op −64%-mandje |

En, belangrijker nog: **positiegrootte is belangrijker dan de strategie.** Op
volatiele coins is RISK-gebaseerde sizing (2% per trade, ATR/stop-genormaliseerd)
het verschil tussen −81% (geruïneerd) en −9% (overleefd). Dit is precies waarvoor
de RiskEngine bestaat.

---

## Eerlijke kanttekeningen

1. **Geen van deze configs maakt grote winst** op dit mandje — deze coins zijn
   grotendeels structureel waardeloos geworden. "Verslaat buy & hold" betekent
   hier vaak "verliest minder", niet "wordt rijk".
2. **In-sample parameters.** Walk-forward-validatie blijft verplicht vóór live.
3. **Mean-reversion +6,5% is bemoedigend** maar op een korte, specifieke periode.
   Het moet over meer perioden en met walk-forward bevestigd worden.

## Aanbeveling

Gebruik **segment-afhankelijke strategieën**: trend-following voor large-caps,
mean-reversion voor small-caps — beide met **RISK-gebaseerde sizing** (nooit
FIXED full-deploy op volatiele coins). De scanners (`quantbot scan`) kunnen
helpen coins naar het juiste segment te routeren.
