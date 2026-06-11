"""A burst of live subscribes must be batched into ONE SUBSCRIBE message —
Binance drops connections sending >~5 messages/sec, so a 60-coin basket
subscribing stream-per-stream would kill the socket."""

from __future__ import annotations

import asyncio

import pytest

from quantbot.core.config import WebSocketSettings
from quantbot.exchanges.websocket import WebSocketManager

pytestmark = pytest.mark.unit


async def test_burst_subscribes_are_batched_into_one_message(monkeypatch) -> None:
    ws = WebSocketManager("wss://example", WebSocketSettings())
    ws._connected.set()  # simulate an open connection

    sent: list[dict] = []

    async def fake_send(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr(ws, "_send", fake_send)

    streams = [f"coin{i}usdt@kline_5m" for i in range(120)]
    for s in streams:
        ws.subscribe(s)

    await asyncio.sleep(0.4)  # let the debounce flush run

    assert len(sent) == 1, "all 120 subscribes must go out in ONE message"
    assert sent[0]["method"] == "SUBSCRIBE"
    assert sorted(sent[0]["params"]) == sorted(streams)


async def test_duplicate_subscribe_returns_same_queue_without_resending(monkeypatch) -> None:
    ws = WebSocketManager("wss://example", WebSocketSettings())
    ws._connected.set()

    sent: list[dict] = []

    async def fake_send(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr(ws, "_send", fake_send)

    q1 = ws.subscribe("btcusdt@kline_5m")
    q2 = ws.subscribe("btcusdt@kline_5m")
    await asyncio.sleep(0.4)

    assert q1 is q2
    assert len(sent) == 1 and sent[0]["params"] == ["btcusdt@kline_5m"]
