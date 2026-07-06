#!/usr/bin/env python3
"""Bitvavo preflight: verify the adapter against the REAL Bitvavo API, read-only.

Bitvavo has NO testnet, so this script NEVER places orders. It is staged:

    Stage 1  Connectivity   — ping, server time, clock drift
    Stage 2  Market data    — markets loaded, klines, ticker (public, no keys)
    Stage 3  Account (auth) — signed balance + open-orders request (verifies the
                              HMAC signature end-to-end; only if keys are set)

Setup:
    1. cp .env.bitvavo.example .env  (and fill in your Bitvavo API keys —
       permissions: View + Trade only, NEVER Withdraw; set an IP whitelist)
    2. python scripts/test_bitvavo.py

All green?  Then start paper trading:  quantbot serve
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from quantbot.core.config import get_settings  # noqa: E402
from quantbot.core.constants import Timeframe  # noqa: E402

GREEN, RED, YELLOW, RESET = "\033[92m", "\033[91m", "\033[93m", "\033[0m"


def ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET} {msg}")


def fail(msg: str) -> None:
    print(f"  {RED}✗ {msg}{RESET}")


async def main() -> int:
    settings = get_settings()
    if settings.exchange.lower() != "bitvavo":
        fail(f"EXCHANGE is {settings.exchange!r} — set EXCHANGE=bitvavo in .env "
             "(tip: cp .env.bitvavo.example .env)")
        return 1

    from quantbot.exchanges.bitvavo import BitvavoGateway

    gateway = BitvavoGateway(settings)
    failures = 0
    try:
        # Stage 1 — connectivity
        print("Stage 1: connectivity")
        latency = await gateway.ping()
        ok(f"ping {latency * 1000:.0f} ms")
        server = await gateway.server_time()
        drift = abs((server - datetime.now(UTC)).total_seconds())
        (ok if drift < 5 else fail)(f"server time {server.isoformat()} (drift {drift:.1f}s)")
        if drift >= 5:
            failures += 1

        # Stage 2 — public market data
        print("Stage 2: market data (public)")
        symbols = await gateway.load_symbols()
        ok(f"{len(symbols)} markets loaded")
        probe = settings.symbols[0] if settings.symbols else "BTCEUR"
        if probe not in symbols:
            fail(f"configured symbol {probe} not listed on Bitvavo")
            failures += 1
        else:
            info = await gateway.get_symbol_info(probe)
            ok(f"{probe}: min order {info.min_notional} {info.quote_asset}")
            candles = await gateway.get_klines(probe, Timeframe.M5, limit=5)
            if candles and candles[0].open_time < candles[-1].open_time:
                ok(f"klines: {len(candles)} candles, last close {candles[-1].close}")
            else:
                fail("klines empty or mis-ordered")
                failures += 1
            ticker = await gateway.get_ticker(probe)
            ok(f"ticker: last {ticker.last_price}")
        missing = [s for s in settings.symbols if s not in symbols]
        if missing:
            print(f"  {YELLOW}! not on Bitvavo (will be skipped): {', '.join(missing)}{RESET}")

        # Stage 3 — authenticated (optional)
        print("Stage 3: account (signed)")
        if not settings.bitvavo.api_key:
            print(f"  {YELLOW}! no BITVAVO__API_KEY set — skipped (fill .env to verify auth){RESET}")
        else:
            account = await gateway.get_account()
            ok(f"balance: {account.available_balance} {settings.quote_asset} free, "
               f"equity ≈ {account.total_equity}")
            open_orders = await gateway.get_open_orders()
            ok(f"open orders: {len(open_orders)}")
    except Exception as exc:  # noqa: BLE001 - report any failure plainly
        fail(f"{type(exc).__name__}: {exc}")
        failures += 1
    finally:
        await gateway.close()

    print()
    if failures == 0:
        print(f"{GREEN}All checks passed.{RESET} Start paper trading with: quantbot serve")
        return 0
    print(f"{RED}{failures} check(s) failed — paste the output to debug.{RESET}")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
