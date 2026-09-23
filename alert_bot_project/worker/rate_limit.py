"""Shared Redis rate reservations for one Telegram bot token."""

import asyncio

from redis.asyncio import Redis

ACQUIRE_SLOT_LUA = """
local clock = redis.call('TIME')
local now = clock[1] * 1000 + math.floor(clock[2] / 1000)
local global_at = tonumber(redis.call('GET', KEYS[1]) or '0')
local chat_at = tonumber(redis.call('GET', KEYS[2]) or '0')
local repeat_at = 0
if ARGV[1] == '1' then repeat_at = tonumber(redis.call('GET', KEYS[3]) or '0') end
local wait = math.max(0, global_at - now, chat_at - now, repeat_at - now)
if wait > 0 then return wait end
redis.call('SET', KEYS[1], now + 50, 'PX', 2000)
redis.call('SET', KEYS[2], now + 1000, 'PX', 2000)
if ARGV[1] == '1' then redis.call('SET', KEYS[3], now + 200, 'PX', 2000) end
return 0
"""

PAUSE_GLOBAL_LUA = """
local clock = redis.call('TIME')
local now = clock[1] * 1000 + math.floor(clock[2] / 1000)
local until_ms = now + tonumber(ARGV[1])
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
if until_ms > current then redis.call('SET', KEYS[1], until_ms, 'PX', ARGV[1] + 2000) end
return 1
"""


class TelegramRateLimiter:
    def __init__(self, redis_client: Redis) -> None:
        self.redis = redis_client
        self.script = redis_client.register_script(ACQUIRE_SLOT_LUA)

    async def acquire(self, chat_id: int, *, repeat: bool) -> None:
        while True:
            wait_ms: int = await self.script(
                keys=["telegram:rate:global", f"telegram:rate:chat:{chat_id}", "telegram:rate:repeat"],
                args=[int(repeat)],
            )
            if wait_ms == 0:
                return
            await asyncio.sleep(min(max(wait_ms / 1000, 0.01), 1))

    async def pause(self, seconds: int) -> None:
        script = self.redis.register_script(PAUSE_GLOBAL_LUA)
        await script(keys=["telegram:rate:global"], args=[max(1000, seconds * 1000)])
