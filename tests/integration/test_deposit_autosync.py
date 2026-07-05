"""Deposit auto-sync: an exchange deposit/withdrawal of the quote asset is folded
into the bot's capital automatically — sizing grows with it, but it is NEVER
counted as profit (total return stays honest)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from quantbot.core.config import AggregatorSettings, RiskSettings, Settings
from quantbot.core.constants import Side, SizingMethod, Timeframe
from quantbot.core.events import EventBus
from quantbot.core.models import Balance
from quantbot.data.market_data import MarketDataService
from quantbot.engine.trading_engine import TradingEngine
from quantbot.execution.executor import OrderExecutor
from quantbot.portfolio.manager import PortfolioManager
from quantbot.risk.engine import RiskEngine
from quantbot.strategies.aggregator import SignalAggregator

from tests.conftest import MockGateway

pytestmark = pytest.mark.integration


class _WalletGateway(MockGateway):
    """MockGateway with a controllable quote-wallet balance."""

    def __init__(self) -> None:
        super().__init__()
        self.wallet = Decimal("100")

    async def get_balance(self, asset: str) -> Balance:
        return Balance(asset=asset, free=self.wallet)


def _engine(*, auto_sync: bool = True):
    gateway = _WalletGateway()
    s = Settings(_env_file=None)
    s.symbols = ["BTCUSDT"]
    s.timeframes = [Timeframe.M5]
    s.auto_sync_deposits = auto_sync
    s.aggregator = AggregatorSettings(min_consensus=1, min_strength=0.5, window_seconds=999999)
    s.risk = RiskSettings(
        sizing_method=SizingMethod.RISK, risk_per_trade=Decimal("0.02"),
        max_open_trades=5, max_exposure_per_coin=Decimal("1.0"),
        max_portfolio_exposure=Decimal("1.0"), default_stop_loss_pct=Decimal("0.10"),
        trailing_stop_pct=Decimal("0.0"), break_even_trigger_pct=Decimal("0.0"),
        take_profit_levels=[], max_correlation=Decimal("1.0"), circuit_breaker_losses=99,
        emergency_stop_enabled=False,
    )
    bus = EventBus()
    portfolio = PortfolioManager(starting_balance=Decimal("100"))
    risk = RiskEngine(s.risk, event_bus=bus)
    risk.set_starting_equity(Decimal("100"))
    executor = OrderExecutor(gateway, risk, portfolio, event_bus=bus, commission_rate=Decimal("0"))
    engine = TradingEngine(
        settings=s, gateway=gateway, market_data=MarketDataService(gateway, event_bus=bus),
        strategies=[], aggregator=SignalAggregator(s.aggregator), risk_engine=risk,
        portfolio=portfolio, executor=executor, event_bus=bus,
    )
    return engine, portfolio, gateway


async def test_deposit_increases_capital_but_not_profit() -> None:
    engine, portfolio, gateway = _engine()
    await engine._capture_wallet_baseline()

    gateway.wallet += Decimal("50")  # user deposits 50 on the exchange
    await engine._check_external_transfers()

    assert portfolio.equity() == Decimal("150")
    assert portfolio.realized_pnl == Decimal("0")
    assert portfolio.total_return_pct() == Decimal("0")  # a deposit is NOT profit


async def test_withdrawal_decreases_capital_but_not_loss() -> None:
    engine, portfolio, gateway = _engine()
    await engine._capture_wallet_baseline()

    gateway.wallet -= Decimal("30")
    await engine._check_external_transfers()

    assert portfolio.equity() == Decimal("70")
    assert portfolio.total_return_pct() == Decimal("0")  # nor is a withdrawal a loss


async def test_small_drift_below_threshold_is_ignored() -> None:
    engine, portfolio, gateway = _engine()
    await engine._capture_wallet_baseline()

    gateway.wallet += Decimal("0.5")  # fee-noise scale, under max(1, 2% equity)
    await engine._check_external_transfers()

    assert portfolio.equity() == Decimal("100")


async def test_deposit_is_applied_exactly_once() -> None:
    engine, portfolio, gateway = _engine()
    await engine._capture_wallet_baseline()

    gateway.wallet += Decimal("50")
    await engine._check_external_transfers()
    await engine._check_external_transfers()  # re-anchored: must not double-count

    assert portfolio.equity() == Decimal("150")


async def test_open_position_spend_is_not_a_withdrawal() -> None:
    engine, portfolio, gateway = _engine()
    await engine._capture_wallet_baseline()

    # Buying moves quote into a held base asset: wallet drops, committed rises.
    portfolio.positions.open_position(
        symbol="BTCUSDT", side=Side.BUY, quantity=Decimal("0.001"),
        entry_price=Decimal("40000"), fee=Decimal("0"),
    )
    portfolio.update_price("BTCUSDT", Decimal("40000"))
    gateway.wallet -= Decimal("40")  # the 40 spent on the buy

    await engine._check_external_transfers()
    assert portfolio.total_return_pct() == Decimal("0")  # no phantom withdrawal booked
    # Capital untouched: cash still the original 100 (PnL-based accounting).
    assert portfolio.cash == Decimal("100")


async def test_disabled_setting_is_a_noop() -> None:
    engine, portfolio, gateway = _engine(auto_sync=False)
    await engine._capture_wallet_baseline()
    gateway.wallet += Decimal("50")
    await engine._check_external_transfers()
    assert portfolio.equity() == Decimal("100")
