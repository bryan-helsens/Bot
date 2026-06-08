# Adaptieve strategie-routing — testrapport

**Datum:** 2026-05-31 · **Data:** CoinMetrics dagkoersen 2023–2026

Het idee: één `AdaptiveStrategy` die **per bar** het marktregime detecteert
(`MarketRegimeDetector`) en automatisch routeert:
- `TRENDING_UP` → trend-following (ride de trend)
- `RANGING` / `HIGH/LOW_VOLATILITY` → mean-reversion (buy dips)
- `TRENDING_DOWN` / `UNKNOWN` → cash

Doel: één strategie die zowel large-caps (trends) als small-caps (choppy) goed
bedient, zodat de bot niet handmatig per coin gekozen hoeft te worden.

---

## Resultaat: routing verslaat de gespecialiseerde strategieën NIET

| Segment | AdaptiveStrategy | Gespecialiseerd | Verschil |
|---------|-----------------:|----------------:|----------|
| **Large-caps (21)** | −7,9% avg | TrendRider: **BTC +105%** | veel slechter |
| **Meme/small-caps (8)** | −12,6% avg | MeanReversion: **+2,6%** | veel slechter |

Op **beide** segmenten doet de adaptieve routing het slechter dan simpelweg de
juiste gespecialiseerde strategie kiezen.

---

## Waarom faalt de routing?

De regime-detector wisselt **te vaak** per bar tussen "trending" en "ranging".
Gevolg:
1. **In een bull-trend** classificeert hij regelmatig "ranging" → schakelt naar
   mean-reversion → **verkoopt winners te vroeg** in plaats van de trend uit te
   rijden. Daardoor mist hij het grootste deel van de stijging (large-caps −7,9%
   i.p.v. +100%+).
2. **De moduswisselingen zelf** genereren extra in/uit-trades → meer kosten,
   meer whipsaw.

Kortom: **per-bar regime-switching is te grillig**. Het regime van een markt is
pas achteraf duidelijk; real-time classificatie zit er vaak naast en de
strategie "twijfelt" zich kapot.

---

## De les: specialisatie > automatische routing

| Aanpak | Resultaat |
|--------|-----------|
| Gespecialiseerde strategie per segment (handmatig of via scanner) | ✅ Werkt (BTC +105%, meme MeanRev +2,6%) |
| Eén adaptieve strategie die per bar routeert | ❌ Slechter op beide |

**Betere routing-aanpak** (toekomstig werk, niet per-bar):
- Bepaal het segment **één keer** bij coin-selectie (via de scanners:
  `TrendScanner` / `VolatilityScanner`), niet elke bar opnieuw.
- Wijs dan een **vaste** strategie toe voor de hele looptijd: trend-coins →
  TrendRider, range-coins → MeanReversion.
- Dit vermijdt het mid-trend-omschakelen dat de winners afkapt.

---

## Status

- `AdaptiveStrategy` is gebouwd, getest (4 unit-tests) en behouden als
  **referentie/experimenteel** — hij werkt correct, maar presteert niet beter
  dan specialisatie. Niet aanbevolen als hoofd-default.
- **Aanbeveling blijft:** kies de strategie per segment. Gebruik de scanners om
  coins te classificeren, en wijs één gespecialiseerde strategie toe — met
  **RISK-gebaseerde sizing** (de dominante factor voor overleven, zie
  `docs/MEME_SMALLCAP_REPORT.md`).

> Eerlijke conclusie: "de bot kiest zelf de beste tactiek" klinkt mooi, maar
> per-bar regime-routing werkt in de praktijk slechter dan een mens (of scanner)
> die het segment één keer goed kiest. Specialisatie wint.
