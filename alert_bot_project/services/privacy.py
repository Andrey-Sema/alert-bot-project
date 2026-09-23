"""Delete a user's live profile and queued delivery payloads."""

import json
import uuid

from redis.asyncio import Redis
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from alert_bot_project.database.models import UserSettings


async def delete_user_data(session: AsyncSession, redis_client: Redis, user_id: int) -> None:
    # Fence old jobs first; the random generation prevents them being delivered
    # after a user registers again. Redis must be available to accept deletion.
    generation = uuid.uuid4().hex
    await redis_client.set(f"privacy:deleted:{user_id}", "1", ex=691200)
    await redis_client.set(f"privacy:generation:{user_id}", generation, ex=691200)
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

    cursor = "-"
    while True:
        entries = await redis_client.xrange("delivery_stream", min=cursor, count=500)
        if not entries:
            break
        for message_id, fields in entries:
            try:
                job = json.loads(fields.get("payload", "{}"))
                matches = int(job.get("chat_id", 0)) == user_id and job.get("recipient_generation", "0") != generation
            except (ValueError, TypeError):
                matches = False
            if matches:
                await redis_client.xack("delivery_stream", "delivery_workers", message_id)
                await redis_client.xdel("delivery_stream", message_id)
                await redis_client.delete(f"delivery:retry:{message_id}")
        cursor = f"({entries[-1][0]}"
        if len(entries) < 500:
            break
