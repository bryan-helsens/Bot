"""Unit tests for the rate limiter."""

from __future__ import annotations

import asyncio
import time

import pytest

from quantbot.exchanges.rate_limiter import RateLimiter

pytestmark = pytest.mark.unit


async def test_burst_within_capacity_is_fast() -> None:
    rl = RateLimiter(max_weight_per_minute=600, max_orders_per_10s=100, max_orders_per_day=100000)
    start = time.monotonic()
    for _ in range(10):
        await rl.acquire(1)
    assert time.monotonic() - start < 0.5


async def test_order_budget_forces_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    rl = RateLimiter(max_weight_per_minute=100000, max_orders_per_10s=2, max_orders_per_day=100000)
    await rl.acquire(1, is_order=True)
    await rl.acquire(1, is_order=True)
    waited = {"s": 0.0}

    async def fake_sleep(seconds: float) -> None:
        waited["s"] += seconds

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    await rl.acquire(1, is_order=True)
    assert waited["s"] > 0


async def test_cooldown_pauses() -> None:
    rl = RateLimiter()
    rl.pause_until(0.05)
    assert rl.is_paused


def test_update_used_weight_drains() -> None:
    rl = RateLimiter(max_weight_per_minute=100)
    before = rl.available_weight
    rl.update_used_weight(95)
    assert rl.available_weight < 6 < before
