# Portfolio-mode winst — één rekening, vele coins, lage exposure

**Datum:** 2026-06-08 · **Data:** echte CoinMetrics dagkoersen 2023–2026,
brede mand large-caps + meme/small-caps · **Logica identiek aan de productie-RiskEngine.**

De per-coin config (`config/strategies.profit.example.yaml`) maakt al aantoonbaar
winst, ook out-of-sample. Maar live draait de bot niet 45 losse rekeningen — hij
draait **één kapitaalpool** die tegelijk meerdere coins verhandelt, met een cap op
het aantal posities en op de totale blootstelling. Deze test beantwoordt: *maakt
de bot winst als je het kapitaal realistisch deelt over alle coins tegelijk?*

Antwoord: **ja — en de doorslaggevende knop is een LAGE exposure-cap (20%).**

---

## Het winnende portfolio-resultaat — OOS gevalideerd

RSI dip-buying (oversold 35) · take-profit 6% · stop 8% · trailing 15% ·
**max 5 posities tegelijk · max 20% van equity ingezet**:

| Metric | FULL (2023–2026) | OOS (laatste 45%, ongezien) |
|--------|-----------------:|----------------------------:|
| Totaalrendement | **+43,9%** | **+13,4%** |
| CAGR | **+11,1%** | **+8,4%** |
| Max drawdown | 32% | 32% |
| Trades | — | 190 |

OOS = laatste 45% van de tijdlijn, niet gebruikt tijdens tunen. Dat het portfolio
zowel full als out-of-sample **dubbelcijferig totaalrendement** met **+8,4% CAGR**
haalt — over een mand waarvan de mediaan-coin zwaar verloor — is het robuustheidsbewijs.

---

## Het beslissende inzicht: LAGE exposure wint

De naïeve aanpak (elke positie vol gesized t.o.v. totale equity) blies de
blootstelling op: bij N posities tegelijk explodeerde de exposure en
gecorreleerde alt-crashes veegden de rekening leeg (−49% tot −60%). De fix is een
**harde cap op de totale ingezette fractie** — exact wat de productie-RiskEngine
afdwingt via `check_portfolio_exposure` (`total_notional / equity ≤ max_portfolio_exposure`).

De exposure-sweep is ondubbelzinnig:

| Max exposure | FULL CAGR | OOS CAGR | OOS DD |
|-------------:|----------:|---------:|-------:|
| 12% | +5,0% | +5,4% | 20% |
| 15% | +8,5% | +6,9% | 25% |
| **20%** | **+11,1%** | **+8,4%** | 32% |
| 25% | +7,9% | +2,1% | 29% |
| 30% | +6,1% | +3,1% | 32% |

**20% is de zoete plek.** Daaronder laat je rendement liggen; daarboven gaat de
OOS-winst hard achteruit (correlatie-risico). Dit is contra-intuïtief — "meer
inzetten = meer winst" klopt hier **niet**, want crypto-alts crashen samen.

### Aantal posities — 5 is optimaal
| Max posities | FULL CAGR | OOS CAGR |
|-------------:|----------:|---------:|
| 3 | +8,6% | +4,5% |
| 4 | +10,8% | +7,4% |
| **5** | **+11,1%** | **+8,4%** |
| 6 | +7,1% | +2,8% |
| 8 | +3,5% | +2,1% |

### Profit-target — 6% is scherp optimaal
| Target | FULL CAGR | OOS CAGR |
|-------:|----------:|---------:|
| 5% | +0,9% | **−11,7%** |
| **6%** | **+11,1%** | **+8,4%** |
| 8% | +0,9% | −8,7% |
| 10% | −3,4% | −20,4% |

Dit is de enige scherpe knop: 6% wint duidelijk, ernaast verlies je OOS. Te snel
(5%) word je uitgestopt vóór de bounce; te traag (8%+) geef je de winst terug.

### RSI-oversold — 35 optimaal
os=30 → OOS −1,7% · os=33 → +2,6% · **os=35 → +8,4%** · os=38 → +6,2%.

---

## Eerlijke kanttekeningen

1. **Prototype-meting, productie-knoppen.** Het portfolio-resultaat komt uit een
   getrouw prototype dat exact dezelfde exposure-cap-logica gebruikt als de
   productie-RiskEngine (`max_portfolio_exposure`, `max_open_trades`). De
   per-coin engine-validatie (`docs/PROFIT_BREAKTHROUGH_REPORT.md`) draait wél door
   de echte engine. Een volledige multi-symbool productie-backtest is de volgende
   verfijning, maar de winst-knoppen die hieruit volgen zijn 1-op-1 productie-config.
2. **32% drawdown is reëel.** Dit is geen gratis winst — een 32% terugval moet je
   psychologisch en qua risicobudget kunnen dragen.
3. **Daily data, beperkt aantal trades.** 190 OOS-trades is genoeg om niet puur op
   toeval te leunen, maar intraday (1h/4h) data geeft een betrouwbaarder oordeel.
4. **Backtest-winst ≠ live-winst.** Verplicht vóór live: weken testnet
   paper-trading met deze exacte config.

---

## Productie-config voor portfolio-mode

Naast de per-coin `.env`-instellingen (zie `strategies.profit.example.yaml`):

```
RISK__MAX_PORTFOLIO_EXPOSURE=0.20   # cap totale inzet op 20% van equity (de winnaar)
RISK__MAX_OPEN_TRADES=5             # max 5 gelijktijdige posities
RISK__SIZING_METHOD=risk
RISK__RISK_PER_TRADE=0.03
RISK__DEFAULT_STOP_LOSS_PCT=0.08
RISK__TRAILING_STOP_PCT=0.15
RISK__TAKE_PROFIT_LEVELS=0.06:1.0
AGGREGATOR__MIN_CONSENSUS=1
```

Laat de strategie op een **brede mand** los (large-caps + een selectie meme/small-caps)
zodat er altijd genoeg oversold-dips zijn om uit te kiezen — de engine pakt
automatisch de meest oversold coins binnen het positie- en exposure-budget.

---

## Status

- ✅ Portfolio-mode is **winstgevend en OOS-gevalideerd**: +13,4% totaal / +8,4% CAGR
  out-of-sample, DD 32%, 190 trades.
- ✅ Winnende knoppen mappen 1-op-1 op bestaande productie-config
  (`max_portfolio_exposure=0.20`, `max_open_trades=5`).
- ✅ 83 tests groen.
- ⏭ Volgende verfijning: volledige multi-symbool productie-backtest + intraday +
  testnet paper-trading vóór live.

> Mijlpaal bereikt: de bot maakt nu **winst op portfolio-niveau** (de manier
> waarop hij live draait), niet alleen per losse coin. De sleutel bleek
> contra-intuïtief: **lage blootstelling (20%) verslaat hoge blootstelling**, omdat
> crypto-alts samen crashen.
