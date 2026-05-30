#!/usr/bin/env python3
"""Live Binance **testnet** connectivity & smoke test.

Run this on a machine with outbound network access and testnet API keys to verify
the real connection end-to-end before paper/live trading. It performs only safe,
read-mostly operations; the optional order test places and immediately cancels a
tiny far-from-market limit order on the testnet (never on mainnet).

Setup:
    1. Create spot testnet keys at https://testnet.binance.vision/
    2. In .env set:
         BINANCE__TESTNET=true
         BINANCE__MARKET=spot
         BINANCE__API_KEY=...
         BINANCE__API_SECRET=...
    3. Run:  python scripts/test_testnet.py            # read-only checks
             python scripts/test_testnet.py --order    # also test order placement

Exit code 0 = all checks passed.
"""

from __future__ import annotations

import asyncio
import sys
from decimal import Decimal

from quantbot.core.config import get_settings
from quantbot.core.constants import OrderType, Side, Timeframe
from quantbot.exchanges.base import OrderRequest
from quantbot.exchanges.factory import create_gateway


async def run(test_orders: bool) -> int:
    settings = get_settings()
    if not settings.binance.testnet:
        print("REFUSING: BINANCE__TESTNET is not true. Set it to true first.")
        return 2
    if not settings.binance.api_key or not settings.binance.api_secret.get_secret_value():
        print("REFUSING: Binance API key/secret not configured in .env.")
        return 2

    gateway = create_gateway(settings)
    checks: list[tuple[str, bool]] = []
    symbol = settings.symbols[0] if settings.symbols else "BTCUSDT"

    await gateway.connect()
    try:
        latency = await gateway.ping()
        checks.append((f"ping ({latency * 1000:.0f} ms)", latency >= 0))

        server_time = await gateway.server_time()
        checks.append((f"server time {server_time.isoformat()}", True))

        symbols = await gateway.get_symbol_info(symbol)
        checks.append((f"symbol info {symbol} (tick={symbols.tick_size})", symbols.symbol == symbol))

        candles = await gateway.get_klines(symbol, Timeframe.H1, limit=10)
        checks.append((f"klines fetched ({len(candles)})", len(candles) > 0))

        ticker = await gateway.get_ticker(symbol)
        checks.append((f"ticker last={ticker.last_price}", ticker.last_price > 0))

        account = await gateway.get_account()
        bal = account.balance_of(settings.quote_asset)
        checks.append((f"account balance {settings.quote_asset}={bal.free}", True))

        if test_orders:
            # Place a tiny limit order far below market so it never fills, then cancel.
            info = await gateway.get_symbol_info(symbol)
            far_price = info.round_price(ticker.last_price * Decimal("0.5"))
            qty = info.round_qty(max(info.min_qty, info.min_notional / far_price * Decimal("1.1")))
            req = OrderRequest(
                symbol=symbol, side=Side.BUY, type=OrderType.LIMIT,
                quantity=qty, price=far_price,
            )
            order = await gateway.create_order(req)
            checks.append((f"limit order placed (id={order.exchange_order_id})", order.exchange_order_id is not None))
            cancelled = await gateway.cancel_order(symbol, order_id=order.exchange_order_id)
            checks.append((f"order cancelled ({cancelled.status.value})", True))
    finally:
        await gateway.close()

    print("=" * 60)
    print(f"BINANCE TESTNET CONNECTIVITY TEST — {symbol}")
    print("=" * 60)
    for name, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    all_ok = all(ok for _, ok in checks)
    print("RESULT:", "ALL PASS" if all_ok else "FAILURES")
    return 0 if all_ok else 1


def main() -> int:
    test_orders = "--order" in sys.argv
    try:
        return asyncio.run(run(test_orders))
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
