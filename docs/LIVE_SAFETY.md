# Veiligheid: status van het live/paper handelspad

Dit document beschrijft eerlijk wat **wel en niet** veilig is om mee te draaien,
na een grondige audit van het uitvoeringspad. Doel: dat je tijdens echte tests
**geen bugs of verliezen door codefouten** oploopt.

## Korte versie

- ✅ **Paper-trading op het testnet is veilig** en de aanbevolen manier om nu te
  draaien (`TRADING_MODE=paper`). Geen echt geld, en het pad is getest.
- ⛔ **Live (echt geld) is geblokkeerd** met een interlock. De runtime weigert
  `TRADING_MODE=live` te starten tenzij je expliciet `ALLOW_LIVE_REAL_ORDERS=true`
  zet — en dat moet je **niet** doen vóór de live-only punten hieronder af zijn.

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

## Wat MOET af vóór live met echt geld (live-only, niet actief in paper)

Deze raken het **echte** beurspad. In paper-mode simuleert de broker fills lokaal,
dus ze vormen daar geen gevaar — maar live wél. De interlock blokkeert live tot
deze gedaan zijn:

| # | Live-only risico | Waarom kritiek | Nodig |
|---|------------------|----------------|-------|
| 3 | Engine luistert **niet** naar de user-data stream; beurs-fills (een getriggerde stop) worden niet teruggekoppeld | Bot denkt dat een positie nog open is terwijl de beurs hem al sloot → spookposities, dubbele trades | Een user-data-stream-consumer die fills in `OrderManager`/`PositionManager` verwerkt |
| 4 | `OrderSynchronizer.reconcile()` wordt nooit gedraaid bij (her)verbinden of na een gemiste candle | Na een websocket-gap blijft een positie onbeheerd / niet-gereconcilieerd | `reconcile()` op start en na elke reconnect/gap |
| 5 | Futures-gateway erft spot-ordertypes; stuurt `STOP_LOSS` (bestaat niet op USD-M futures) en nooit `reduceOnly` | Live futures: stop-plaatsing wordt geweigerd → positie zonder stop | Futures `create_order` overschrijven (`STOP_MARKET`/`TAKE_PROFIT_MARKET` + `reduceOnly`) |
| 8 | `reduce_only` wordt op **spot** stil genegeerd | Elke hoeveelheid-desync wordt een verkeerd-gedimensioneerde spot-verkoop | Sluit-/stop-hoeveelheid clampen op vrije basis-balans |
| 9 | Spot account-equity telt alleen de quote-balans (negeert basis-holdings) | Verkeerde drawdown/sizing-baseline bij start | Basis-holdings tegen laatste prijs meewaarderen |
| 11 | ATR-proxy is één candle high-low i.p.v. echte ATR | Te grote posities op rustige bars | ATR uit de serie berekenen |

> Tot #3, #4 en #5 af zijn: **draai uitsluitend paper op het testnet.** Dat is
> precies waarvoor de interlock zorgt.

## Hoe je nu veilig test

Zie `docs/TESTNET_PAPER_TRADING.md`. Kort: `TRADING_MODE=paper`,
`BINANCE__TESTNET=true`, preflight via `scripts/test_testnet.py`, dan `quantbot run`.
De interlock laat dit gewoon draaien; alleen echt-geld-live wordt geblokkeerd.
