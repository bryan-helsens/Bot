"""After a losing exit on a coin, the engine must ignore new entry signals for it
until the cooldown elapses — stops the bot re-buying a coin that just stopped out."""

from __future__ import annotations

from datetime import timedelta

import pytest

from quantbot.core.constants import EventType
from quantbot.core.events import Event
from quantbot.core.models import utcnow

from tests.integration.test_live_execution import _settings, _wire

pytestmark = pytest.mark.integration


def _engine(cooldown: int):
    settings = _settings(take_profit_levels=[])
    settings.risk.reentry_cooldown_seconds = cooldown
    engine, *_ = _wire(settings, _strategy())
    return engine


def _strategy():
    from quantbot.strategies.base import BaseStrategy

    class _Noop(BaseStrategy):
        name = "Noop"

        async def on_candle(self, ctx):
            return None

    return _Noop()


async def _close(engine, symbol: str, pnl: str) -> None:
    await engine._on_trade_event(
        Event(EventType.TRADE_CLOSED, payload={"symbol": symbol, "net_pnl": pnl}, source="t")
    )


async def test_losing_exit_triggers_cooldown() -> None:
    engine = _engine(cooldown=1800)
    await _close(engine, "BTCUSDT", "-1.5")
    assert engine._in_reentry_cooldown("BTCUSDT") is True
    assert engine._in_reentry_cooldown("ETHUSDT") is False  # untouched coin is free


async def test_winning_exit_does_not_trigger_cooldown() -> None:
    engine = _engine(cooldown=1800)
    await _close(engine, "BTCUSDT", "2.0")
    assert engine._in_reentry_cooldown("BTCUSDT") is False


async def test_cooldown_disabled_when_zero() -> None:
    engine = _engine(cooldown=0)
    await _close(engine, "BTCUSDT", "-1.5")
    assert engine._in_reentry_cooldown("BTCUSDT") is False


async def test_cooldown_expires() -> None:
    engine = _engine(cooldown=1800)
    await _close(engine, "BTCUSDT", "-1.5")
    # Backdate the loss beyond the window.
    engine._last_loss_at["BTCUSDT"] = utcnow() - timedelta(seconds=2000)
    assert engine._in_reentry_cooldown("BTCUSDT") is False
