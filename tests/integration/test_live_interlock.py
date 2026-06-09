"""The live-trading safety interlock must block real-money mode by default."""

from __future__ import annotations

import pytest

from quantbot.core.config import Settings
from quantbot.core.constants import TradingMode
from quantbot.engine.runtime import build_runtime

pytestmark = pytest.mark.integration


def _live_settings(*, allow: bool) -> Settings:
    s = Settings(_env_file=None)
    s.trading_mode = TradingMode.LIVE
    s.allow_live_real_orders = allow
    s.binance.api_key = "k"
    from pydantic import SecretStr

    s.binance.api_secret = SecretStr("s")
    return s


def test_live_mode_refuses_to_start_without_explicit_opt_in() -> None:
    with pytest.raises(RuntimeError, match="LIVE trading is gated"):
        build_runtime(_live_settings(allow=False))


def test_paper_mode_is_unaffected_by_the_interlock() -> None:
    s = Settings(_env_file=None)
    s.trading_mode = TradingMode.PAPER  # default, but explicit for clarity
    runtime = build_runtime(s)
    assert runtime.engine is not None
