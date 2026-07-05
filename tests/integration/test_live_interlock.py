"""The live-trading safety interlock must block real-money mode by default."""

from __future__ import annotations

import pytest

from quantbot.core.config import Settings
from quantbot.core.constants import TradingMode
from quantbot.engine.runtime import build_runtime

pytestmark = pytest.mark.integration


def _live_settings(*, allow: bool, testnet: bool) -> Settings:
    s = Settings(_env_file=None)
    s.trading_mode = TradingMode.LIVE
    s.allow_live_real_orders = allow
    s.binance.testnet = testnet
    s.binance.api_key = "k"
    from pydantic import SecretStr

    s.binance.api_secret = SecretStr("s")
    return s


def test_live_mainnet_refuses_to_start_without_explicit_opt_in() -> None:
    with pytest.raises(RuntimeError, match="LIVE trading with REAL money"):
        build_runtime(_live_settings(allow=False, testnet=False))


def test_live_on_testnet_runs_without_opt_in() -> None:
    # Testnet is fake money — live order placement there must NOT be gated.
    runtime = build_runtime(_live_settings(allow=False, testnet=True))
    assert runtime.engine is not None


def test_paper_mode_is_unaffected_by_the_interlock() -> None:
    s = Settings(_env_file=None)
    s.trading_mode = TradingMode.PAPER  # default, but explicit for clarity
    runtime = build_runtime(s)
    assert runtime.engine is not None
