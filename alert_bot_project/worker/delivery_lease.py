"""Renew pending ownership and fence a stage across worker processes."""

import asyncio
import contextlib
import secrets
from collections.abc import Awaitable, Callable

from redis.asyncio import Redis

RENEW_DELIVERY_LUA = """
local pending = redis.call('XPENDING', KEYS[1], ARGV[1], ARGV[2], ARGV[2], 1)
if #pending == 0 or pending[1][2] ~= ARGV[3] then return 0 end
local holder = redis.call('GET', KEYS[2])
if holder and holder ~= ARGV[4] then return 0 end
redis.call('SET', KEYS[2], ARGV[4], 'PX', ARGV[5])
redis.call('XCLAIM', KEYS[1], ARGV[1], ARGV[3], 0, ARGV[2], 'JUSTID')
return 1
"""
RELEASE_DELIVERY_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end
return 0
"""


class DeliveryLease:
    def __init__(self, redis: Redis, stream: str, group: str, consumer: str, message_id: str, stage: str) -> None:
        self.redis = redis
        self.stream = stream
        self.group = group
        self.consumer = consumer
        self.message_id = message_id
        self.key = f"delivery:lease:{stage}"
        self.token = secrets.token_hex(32)
        self.ttl_ms = 90000
        self.interval = 15.0

    async def renew(self) -> bool:
        script = self.redis.register_script(RENEW_DELIVERY_LUA)
        async with asyncio.timeout(5):
            return bool(
                await script(
                    keys=[self.stream, self.key],
                    args=[
                        self.group,
                        self.message_id,
                        self.consumer,
                        self.token,
                        self.ttl_ms,
                    ],
                )
            )

    async def run(self, operation: Callable[[], Awaitable[None]], budget_seconds: float) -> None:
        if not await self.renew():
            return
        task = asyncio.ensure_future(operation())

        async def heartbeat() -> None:
            try:
                while True:
                    await asyncio.sleep(self.interval)
                    if not await self.renew():
                        return
            finally:
                if not task.done():
                    task.cancel()

        heart = asyncio.create_task(heartbeat())
        try:
            async with asyncio.timeout(budget_seconds):
                done, _ = await asyncio.wait({task, heart}, return_when=asyncio.FIRST_COMPLETED)
                if heart in done:
                    await heart
                else:
                    await task
        finally:
            task.cancel()
            heart.cancel()
            await asyncio.gather(task, heart, return_exceptions=True)
            release = self.redis.register_script(RELEASE_DELIVERY_LUA)
            with contextlib.suppress(Exception):
                async with asyncio.timeout(5):
                    await release(keys=[self.key], args=[self.token])
