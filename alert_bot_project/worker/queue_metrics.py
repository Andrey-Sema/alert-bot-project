"""Delivery queue metrics based on work still owed to consumer groups."""

import time

from redis.asyncio import Redis


def _stream_id(value: str) -> tuple[int, int]:
    milliseconds, sequence = value.split("-", 1)
    return int(milliseconds), int(sequence)


async def delivery_backlog(redis_client: Redis, stream: str, group_name: str) -> tuple[int, float]:
    """Return pending plus unseen jobs and the age of the oldest such job."""
    if not await redis_client.exists(stream):
        return 0, 0.0
    groups = await redis_client.xinfo_groups(stream)
    group = next((item for item in groups if item["name"] == group_name), None)
    if group is None:
        return 0, 0.0

    pending = int(group["pending"])
    unseen = int(group.get("lag") or 0)
    candidate_ids: list[str] = []
    if pending:
        summary = await redis_client.xpending(stream, group_name)
        if summary["min"]:
            candidate_ids.append(summary["min"])
    unseen_entries = await redis_client.xrange(stream, min=f"({group['last-delivered-id']}", count=1)
    if unseen_entries:
        candidate_ids.append(unseen_entries[0][0])
        unseen = max(1, unseen)
    if not candidate_ids:
        return pending + unseen, 0.0
    oldest_ms = min(_stream_id(message_id)[0] for message_id in candidate_ids)
    return pending + unseen, max(0.0, time.time() - oldest_ms / 1000)
