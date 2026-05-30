#!/usr/bin/env python3
"""Standalone historical-data downloader.

Thin wrapper around the CLI ``download`` command for cron/batch use::

    python scripts/download_data.py BTCUSDT 1h 2023-01-01
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime


async def _download(symbol: str, timeframe: str, start: str) -> None:
    from quantbot.core.config import get_settings
    from quantbot.core.constants import Timeframe
    from quantbot.data.historical import HistoricalDataLoader
    from quantbot.exchanges.factory import create_gateway

    settings = get_settings()
    gateway = create_gateway(settings)
    await gateway.connect()
    try:
        loader = HistoricalDataLoader(gateway)
        candles = await loader.load(
            symbol, Timeframe.from_string(timeframe),
            datetime.fromisoformat(start).replace(tzinfo=UTC),
        )
        print(f"Downloaded {len(candles)} {timeframe} candles for {symbol}")
    finally:
        await gateway.close()


def main() -> int:
    if len(sys.argv) < 4:
        print("Usage: download_data.py SYMBOL TIMEFRAME START_DATE", file=sys.stderr)
        return 2
    asyncio.run(_download(sys.argv[1], sys.argv[2], sys.argv[3]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
