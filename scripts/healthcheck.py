#!/usr/bin/env python3
"""Container healthcheck: verify DB and Redis connectivity.

Exit code 0 = healthy, 1 = unhealthy. Used by Docker/K8s liveness probes for the
bot service (the API has its own /health HTTP endpoint).
"""

from __future__ import annotations

import asyncio
import sys


async def _check() -> bool:
    from quantbot.core.config import get_settings
    from quantbot.infrastructure.cache.redis_cache import RedisCache
    from quantbot.infrastructure.db.database import Database

    settings = get_settings()
    db = Database(settings)
    cache = RedisCache(settings)
    try:
        db_ok = await db.health_check()
        await cache.connect()
        redis_ok = await cache.health_check()
    except Exception:  # noqa: BLE001
        return False
    finally:
        await db.dispose()
        await cache.close()
    return db_ok and redis_ok


def main() -> int:
    healthy = asyncio.run(_check())
    print("healthy" if healthy else "unhealthy")
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
