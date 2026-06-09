# Veiligheid: status van het live/paper handelspad

Dit document beschrijft eerlijk wat **wel en niet** veilig is om mee te draaien,
na een grondige audit van het uitvoeringspad. Doel: dat je tijdens echte tests
**geen bugs of verliezen door codefouten** oploopt.

## Korte versie

- ✅ **Paper-trading op het testnet is veilig** en de aanbevolen manier om nu te
  draaien (`TRADING_MODE=paper`). Geen echt geld, en het pad is getest.
- ✅ **De kritieke live-bugs zijn nu gefixt** (fill-reconciliatie via de user-data
  stream, reconcile bij (her)verbinden, futures-ordertypes, spot over-sell-
  bescherming). Zie de tabellen hieronder.
- 🔒 **Live (echt geld) blijft achter een opt-in.** De runtime weigert
  `TRADING_MODE=live` tenzij je bewust `ALLOW_LIVE_REAL_ORDERS=true` zet. Doe dat
  pas **na** wekenlang schoon paper-traden op het testnet. De interlock voorkomt
  dat een config-slip per ongeluk echt geld inzet.

## Wat is gefixt in deze ronde (gold ook voor paper)

| # | Bug | Impact | Status |
|---|-----|--------|:------:|
| 1 | Gedeeltelijke take-profit paste de boeken aan **zonder** een verkooporder te plaatsen | Boek/positie liep uit de pas met de beurs | ✅ gefixt (`OrderExecutor.reduce_position` plaatst nu een echte reduce-only order) |
| 2 | Beschermende stop bleef op de **oude** (volledige) hoeveelheid na een partiële TP | Verkeerd-gedimensioneerde stop, dubbele-verkoop-risico | ✅ gefixt (stop wordt herplaatst op de resterende hoeveelheid) |
| 10 | Exposure-limieten rekenden met **entryprijs** i.p.v. actuele prijs | Portfolio kon de exposure-cap stilletjes overschrijden | ✅ gefixt (`notional()` gebruikt nu de mark price) |
| 14 | Noodstop/drawdown werd alleen op de 60s-timer geüpdatet | Snelle drawdown stopte nieuwe trades tot een minuut te laat | ✅ gefixt (per candle bijgewerkt) |
| 6 | Paper-broker gooide een ruwe `KeyError` bij ontbrekende prijs | Kon de candle-loop laten crashen | ✅ gefixt (typed `ExchangeError`) |
| 12 | Commissie werd overschreven i.p.v. opgeteld over deelvullingen | Onderschatte kosten | ✅ gefixt (opgeteld) |

Geborgd door tests: `tests/integration/test_live_execution.py` (partiële TP plaatst
een echte order; accounting-invariant houdt stand; exposure-cap verkleint de order;
noodstop blokkeert alle orders) en `tests/integration/test_realistic_fills.py`.

## Live-pad: nu gefixt (was eerder blokkerend voor echt geld)

Deze raakten het **echte** beurspad. In paper-mode simuleert de broker fills lokaal,
dus ze vormden daar geen gevaar — maar live wél. Nu gefixt en getest:

| # | Live-only risico | Status |
|---|------------------|:------:|
| 3 | Engine luisterde **niet** naar de user-data stream; een getriggerde beurs-stop werd niet teruggekoppeld → spookposities | ✅ user-data-stream-consumer verwerkt fills; een gevuurde stop sluit de positie in de boeken (`gateway.parse_user_event` + `TradingEngine._on_order_update` → `OrderExecutor.apply_external_close`) |
| 4 | `OrderSynchronizer.reconcile()` werd nooit gedraaid bij (her)verbinden | ✅ reconcile op start; positie die op de beurs al weg is wordt lokaal gesloten |
| 5 | Futures-gateway stuurde `STOP_LOSS` (bestaat niet op USD-M) en nooit `reduceOnly` → stop geweigerd | ✅ futures `create_order` gebruikt `STOP_MARKET`/`TAKE_PROFIT_MARKET` + `reduceOnly` |
| 8 | `reduce_only` werd op **spot** stil genegeerd → mogelijke over-sell | ✅ reduce-only spot-SELL wordt geclampt op de vrije basis-balans |

Geborgd door tests: `tests/integration/test_live_reconciliation.py` (gevuurde stop
sluit positie zonder nieuwe order; stale positie wordt gereconcilieerd),
`tests/unit/test_futures_orders.py`, `tests/unit/test_spot_reduce_clamp.py`.

## Kleinere resterende punten (niet blokkerend; paper dekt ze af)

| # | Punt | Impact | Aanpak |
|---|------|--------|--------|
| 9 | Spot account-equity telt alleen de quote-balans (negeert basis-holdings) | Alleen verkeerde **start**-baseline áls je met basis-assets begint; runtime-equity is PnL-based en klopt. Start je flat (alleen USDT), dan geen probleem | Optioneel: basis-holdings tegen laatste prijs meewaarderen |
| 11 | ATR-proxy is één candle high-low i.p.v. echte ATR | Sizing-kwaliteit op rustige bars | Optioneel: ATR uit de serie berekenen |

> Aanbevolen volgorde: weken **paper op testnet** → bevestig dat fills, stops en
> reconciliatie zich gedragen → pas dan `ALLOW_LIVE_REAL_ORDERS=true` met minimaal
> kapitaal.

## Hoe je nu veilig test

Zie `docs/TESTNET_PAPER_TRADING.md`. Kort: `TRADING_MODE=paper`,
`BINANCE__TESTNET=true`, preflight via `scripts/test_testnet.py`, dan `quantbot run`.
De interlock laat dit gewoon draaien; alleen echt-geld-live wordt geblokkeerd.
