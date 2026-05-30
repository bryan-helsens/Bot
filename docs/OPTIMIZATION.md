# Optimalisatiehandleiding

Parameter-optimalisatie verbetert strategieprestaties, maar **overfitting** is de
grootste valkuil: parameters die perfect op het verleden passen, falen live.
QuantBot biedt daarom niet alleen optimizers maar ook **walk-forward** en
**Monte-Carlo**-validatie om robuustheid te toetsen.

> Gouden regel: optimaliseer op in-sample data, **valideer altijd out-of-sample**.

---

## 1. Optimizers

| Optimizer | Wanneer | Kosten |
|-----------|---------|--------|
| **Grid Search** | Weinig parameters, exhaustief, deterministisch | Exponentieel in #params |
| **Random Search** | Veel parameters, slechts enkele relevant | Lineair in #trials |
| **Bayesian (Optuna)** | Dure evaluaties, slim zoeken | Efficiëntst; vereist `quantbot[optimize]` |

### Voorbeeld (code)

```python
from quantbot.core.config import get_settings
from quantbot.optimize.base import SearchSpace, IntRange, make_backtest_objective
from quantbot.optimize.bayesian import BayesianOptimizer
from quantbot.strategies.builtin.ema_crossover import EMACrossoverStrategy
# candles ophalen via HistoricalDataLoader ...

space = SearchSpace({
    "fast_period": IntRange(5, 20, 1),
    "slow_period": IntRange(20, 60, 2),
})
objective = make_backtest_objective(
    strategy_cls=EMACrossoverStrategy, candles=candles, settings=get_settings(),
    metric="sharpe_ratio", symbols=["BTCUSDT"], timeframes=[Timeframe.H1],
)
result = BayesianOptimizer(n_trials=100, seed=42).optimize(space=space, objective=objective)
print(result.best_params, result.best_score)
for trial in result.top(5):
    print(trial.score, trial.params)
```

Kies de **metric** bewust: `sharpe_ratio`/`calmar_ratio` belonen risico-gecorrigeerd
rendement; `net_profit` alleen kan overfitten op enkele grote trades.

---

## 2. Walk-Forward Analyse (anti-overfitting)

Splitst de historie in opeenvolgende vensters: optimaliseer op het
**in-sample** (IS) deel, evalueer op het aansluitende **out-of-sample** (OOS) deel,
schuif door en herhaal.

```python
from quantbot.optimize.walk_forward import WalkForwardAnalysis
from quantbot.optimize.grid_search import GridSearchOptimizer

wfa = WalkForwardAnalysis(
    strategy_cls=EMACrossoverStrategy, settings=get_settings(), space=space,
    optimizer=GridSearchOptimizer(), metric="sharpe_ratio",
    n_splits=4, is_ratio=0.7, symbols=["BTCUSDT"], timeframes=[Timeframe.H1],
)
report = wfa.run(candles)
print("Gem. OOS score:", report.avg_oos_score)
print("Efficiency (OOS/IS):", report.efficiency)   # ~1.0 = weinig overfitting
print("Robuust?", report.robust)
```

**Interpretatie:** een hoge IS-score met lage OOS-score (lage `efficiency`) =
overfit. Streef naar `efficiency >= 0.5` én positieve gemiddelde OOS-score.

---

## 3. Monte-Carlo Simulatie (tail-risk)

Toetst hoe afhankelijk het resultaat is van de *volgorde* van trades, en
kwantificeert staartrisico (kans op ruïne, drawdown-distributie).

```python
from quantbot.optimize.monte_carlo import MonteCarloSimulator

pnls = [float(t.net_pnl) for t in result_trades]      # uit een backtest
mc = MonteCarloSimulator(simulations=2000, method="bootstrap", seed=1)
stats = mc.run(pnls, starting_equity=10000)
print(stats.as_dict())
# p5_final_equity, p95_final_equity, worst_max_drawdown, probability_of_ruin, ...
```

Gebruik **bootstrap** (sampling met teruglegging) voor een verdeling van mogelijke
uitkomsten; **shuffle** behoudt de som maar toont sequentie-risico (drawdowns).
Een acceptabele strategie heeft een **lage `probability_of_ruin`** en een
`p5_final_equity` die je kunt verdragen.

---

## 4. Aanbevolen workflow

1. **Backtest** een baseline met standaardparameters.
2. **Optimaliseer** (random/bayesian) op een IS-periode met een risico-gecorrigeerde metric.
3. **Walk-forward** valideer; verwerp als OOS-efficiency laag is.
4. **Monte-Carlo** toets staartrisico op de OOS-trades.
5. **Paper-trade** de gekozen parameters wekenlang vóór live.
6. **Her-evalueer** periodiek; markten veranderen (regime-shift → `MarketRegimeDetector`).

## 5. Anti-overfitting checklist

- [ ] Houd het aantal parameters klein (≤ 3-4 per strategie).
- [ ] Optimaliseer op een metric die risico meeneemt, niet alleen winst.
- [ ] Eis out-of-sample-validatie (walk-forward) vóór acceptatie.
- [ ] Wantrouw "perfecte" equity-curves; controleer trade-aantallen.
- [ ] Combineer strategieën via confluence i.p.v. één over-getunede strategie.
- [ ] Herhaal Monte-Carlo; accepteer alleen lage ruïne-kans.
- [ ] Vermijd het optimaliseren van risk-limieten zelf — die zijn voor bescherming, niet voor rendement.
