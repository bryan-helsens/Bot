"""Unit tests for configuration parsing."""

from __future__ import annotations

import os
from decimal import Decimal

import pytest

from quantbot.core.config import Settings
from quantbot.core.constants import MarketType, Timeframe

pytestmark = pytest.mark.unit


def test_csv_and_nested_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    env = {
        "SYMBOLS": "BTCUSDT, ETHUSDT ,SOLUSDT",
        "TIMEFRAMES": "15m,1h,4h",
        "RISK__MAX_OPEN_TRADES": "7",
        "BINANCE__MARKET": "futures",
        "BINANCE__TESTNET": "true",
        "DATABASE__HOST": "db",
        "DATABASE__PASSWORD": "secret",
        "API__CORS_ORIGINS": "http://a.com,http://b.com",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    s = Settings(_env_file=None)
    assert s.symbols == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    assert s.timeframes == [Timeframe.M15, Timeframe.H1, Timeframe.H4]
    assert s.risk.max_open_trades == 7
    assert s.binance.market is MarketType.FUTURES
    assert s.binance.resolved_rest_url == "https://testnet.binancefuture.com"
    assert s.database.url == "postgresql+asyncpg://quantbot:secret@db:5432/quantbot"
    assert s.api.cors_origins == ["http://a.com", "http://b.com"]


def test_take_profit_levels_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RISK__TAKE_PROFIT_LEVELS", "0.02:0.7,0.04:0.5")
    with pytest.raises(ValueError, match="sum"):
        Settings(_env_file=None)


def test_redis_and_db_urls() -> None:
    s = Settings(_env_file=None)
    assert s.redis.resolved_url.startswith("redis://")
    assert s.database.sync_url.startswith("postgresql+psycopg://")


def test_defaults() -> None:
    s = Settings(_env_file=None)
    assert s.risk.allow_martingale is False
    assert s.risk.allow_unlimited_averaging is False
    assert isinstance(s.risk.risk_per_trade, Decimal)
