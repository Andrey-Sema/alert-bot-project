"""Synthetic Redis fanout probe; no Telegram messages are sent."""

import argparse
import asyncio
import json
import time
import uuid
from datetime import UTC, datetime

from aiogram import Bot
from redis.asyncio import Redis

from alert_bot_project.core_shared.config import config
from alert_bot_project.core_shared.redis_connection import create_service_redis
from alert_bot_project.worker.broadcaster import Broadcaster


def _percentile(samples: list[float], percentile: float) -> float:
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * percentile))]


async def probe_fanout(redis_client: Redis, recipients: int, posts_per_minute: int) -> dict[str, float | int]:
    """Measure accepted first-stage jobs and Redis cost for a one-minute burst."""
    if recipients < 1 or posts_per_minute not in (1, 5, 20):
        raise ValueError("recipients must be positive and posts_per_minute must be 1, 5, or 20")
    suffix = uuid.uuid4().hex
    source_chat_id = -(int(suffix[:12], 16) + 1000)
    bot = Bot(token=config.BOT_TOKEN)
    broadcaster = Broadcaster(bot, redis_client)
    broadcaster.delivery_stream_name = f"probe:delivery:{suffix}"
    broadcaster.delayed_queue_key = f"probe:delayed:{suffix}"
    memory_before = int((await redis_client.info("memory"))["used_memory"])
    post_latencies: list[float] = []
    accepted = 0
    try:
        for post_id in range(1, posts_per_minute + 1):
            started = time.perf_counter()
            for recipient in range(1, recipients + 1):
                accepted += int(
                    await broadcaster.enqueue_alert(
                        source_chat_id, post_id, recipient, source_timestamp=datetime.now(UTC)
                    )
                )
            post_latencies.append(time.perf_counter() - started)
        first_jobs = await redis_client.xlen(broadcaster.delivery_stream_name)
        delayed_jobs = await redis_client.zcard(broadcaster.delayed_queue_key)
        memory_after = int((await redis_client.info("memory"))["used_memory"])
        expected = recipients * posts_per_minute
        return {
            "recipients": recipients,
            "posts_per_minute": posts_per_minute,
            "accepted_jobs": accepted,
            "accepted_loss": expected - accepted,
            "first_stage_jobs": first_jobs,
            "delayed_jobs": delayed_jobs,
            "fanout_p95_seconds": _percentile(post_latencies, 0.95),
            "fanout_p99_seconds": _percentile(post_latencies, 0.99),
            "redis_memory_delta_bytes": max(0, memory_after - memory_before),
        }
    finally:
        await bot.session.close()
        markers = [
            marker async for marker in redis_client.scan_iter(match=f"delivery:enqueued:{source_chat_id}:*", count=500)
        ]
        for offset in range(0, len(markers), 500):
            await redis_client.delete(*markers[offset : offset + 500])
        await redis_client.delete(broadcaster.delivery_stream_name, broadcaster.delayed_queue_key)


async def _run(redis_url: str, recipients: int, scenarios: list[int]) -> None:
    client = create_service_redis(redis_url)
    try:
        results = [await probe_fanout(client, recipients, scenario) for scenario in scenarios]
        print(json.dumps({"scope": "Redis fanout only; no SQL or Telegram delivery", "results": results}, indent=2))
    finally:
        await client.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure synthetic Redis recipient fanout without sending Telegram alerts"
    )
    parser.add_argument("--redis-url", default=config.REDIS_URL)
    parser.add_argument("--recipients", type=int, required=True)
    parser.add_argument("--posts-per-minute", type=int, nargs="+", choices=(1, 5, 20), default=[1, 5, 20])
    args = parser.parse_args()
    asyncio.run(_run(args.redis_url, args.recipients, args.posts_per_minute))


if __name__ == "__main__":
    main()
