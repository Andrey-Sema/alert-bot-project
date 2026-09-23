"""Dependency readiness probe used by the service container healthchecks."""

import asyncio
import sys

from redis.asyncio import Redis
from sqlalchemy import text

from alert_bot_project.core_shared.config import config
from alert_bot_project.database.engine import AsyncSessionLocal


async def check_ready(service: str) -> bool:
    redis_client = Redis.from_url(config.REDIS_URL, decode_responses=True)
    try:
        async with asyncio.timeout(4):
            await redis_client.ping()
            if service in ("worker", "bot_ui"):
                async with AsyncSessionLocal() as session:
                    await session.execute(text("SELECT 1"))
            if service == "worker":
                groups = await redis_client.xinfo_groups("delivery_stream")
                if not any(group["name"] == "delivery_workers" for group in groups):
                    return False
            return True
    except Exception:
        return False
    finally:
        await redis_client.aclose()


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("worker", "scraper", "bot_ui"):
        sys.exit(2)
    sys.exit(0 if asyncio.run(check_ready(sys.argv[1])) else 1)
