"""Delete a user's live profile and queued delivery payloads."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from alert_bot_project.database.models import UserSettings

FENCE_DELETION_LUA = """
redis.call('SET', KEYS[1], '1')
redis.call('SET', KEYS[2], ARGV[1])
return 1
"""

BEGIN_DELIVERY_LUA = """
if redis.call('EXISTS', KEYS[1]) == 1 then return 0 end
if (redis.call('GET', KEYS[2]) or '0') ~= ARGV[1] then return 0 end
redis.call('INCR', KEYS[3])
redis.call('EXPIRE', KEYS[3], 600)
return 1
"""

END_DELIVERY_LUA = """
local count = tonumber(redis.call('GET', KEYS[1]) or '0')
if count <= 1 then return redis.call('DEL', KEYS[1]) end
return redis.call('DECR', KEYS[1])
"""

RENEW_PRIVACY_LOCK_LUA = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
return redis.call('EXPIRE', KEYS[1], 90)
"""

RELEASE_PRIVACY_LOCK_LUA = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
return redis.call('DEL', KEYS[1])
"""


@asynccontextmanager
async def user_privacy_lock(redis_client: Redis, user_id: int) -> AsyncIterator[None]:
    """Serialize registration and deletion of one recipient."""
    key = f"privacy:operation:{user_id}"
    token = uuid.uuid4().hex
    if not await redis_client.set(key, token, nx=True, ex=90):
        raise RedisError("Another profile operation is in progress; retry later")
    stopped = asyncio.Event()

    async def renew() -> None:
        script = redis_client.register_script(RENEW_PRIVACY_LOCK_LUA)
        while not stopped.is_set():
            try:
                await asyncio.wait_for(stopped.wait(), timeout=30)
            except TimeoutError:
                if not await script(keys=[key], args=[token]):
                    return

    heartbeat = asyncio.create_task(renew())
    try:
        yield
    finally:
        stopped.set()
        await heartbeat
        release = redis_client.register_script(RELEASE_PRIVACY_LOCK_LUA)
        await release(keys=[key], args=[token])


async def _scrub_recipient_stream(redis_client: Redis, stream: str, user_id: int, group: str | None) -> None:
    cursor = "-"
    while True:
        entries = await redis_client.xrange(stream, min=cursor, count=500)
        if not entries:
            break
        for message_id, fields in entries:
            try:
                job = json.loads(fields.get("payload", "{}"))
                matches = int(job.get("chat_id", 0)) == user_id
            except (ValueError, TypeError, AttributeError):
                matches = False
            if matches:
                if group:
                    await redis_client.xack(stream, group, message_id)
                await redis_client.xdel(stream, message_id)
                if group:
                    await redis_client.delete(f"delivery:retry:{message_id}")
        cursor = f"({entries[-1][0]}"
        if len(entries) < 500:
            break


async def _delete_user_data_locked(session: AsyncSession, redis_client: Redis, user_id: int) -> None:
    # Fence old jobs first; the random generation prevents them being delivered
    # after a user registers again. Redis must be available to accept deletion.
    generation = uuid.uuid4().hex
    fence = redis_client.register_script(FENCE_DELETION_LUA)
    await fence(keys=[f"privacy:deleted:{user_id}", f"privacy:generation:{user_id}"], args=[generation])
    # A send that reserved its slot before the fence must finish before
    # deletion can report success. A timeout leaves the fence in place.
    for _ in range(350):
        if int(await redis_client.get(f"privacy:inflight:{user_id}") or 0) == 0:
            break
        await asyncio.sleep(0.1)
    else:
        raise RedisError("Delivery is still in flight; retry deletion later")
    await session.execute(delete(UserSettings).where(UserSettings.user_id == user_id))
    await session.commit()

    await redis_client.delete(f"user_mute:{user_id}", f"telegram:blocked:{user_id}", f"telegram:rate:chat:{user_id}")
    for pattern in (f"delivery:enqueued:*:*:{user_id}", f"delivery:stage:*:*:{user_id}:*"):
        async for key in redis_client.scan_iter(match=pattern, count=500):
            await redis_client.delete(key)

    async for member, _score in redis_client.zscan_iter("delayed_alerts_queue", count=500):
        try:
            job = json.loads(member)
            if int(job.get("chat_id", 0)) == user_id and job.get("recipient_generation", "0") != generation:
                await redis_client.zrem("delayed_alerts_queue", member)
        except (ValueError, TypeError):
            continue

    await _scrub_recipient_stream(redis_client, "delivery_stream", user_id, "delivery_workers")
    await _scrub_recipient_stream(redis_client, "delivery_dead_letter_queue", user_id, None)


async def delete_user_data(session: AsyncSession, redis_client: Redis, user_id: int) -> None:
    async with user_privacy_lock(redis_client, user_id):
        await _delete_user_data_locked(session, redis_client, user_id)
