"""User deletion fences and removes queued payloads."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from alert_bot_project.services.privacy import delete_user_data


async def _keys(match: str, count: int = 500):
    if "enqueued" in match:
        yield "delivery:enqueued:-100:8:123"


async def _scheduled(queue: str, count: int = 500):
    yield json.dumps({"chat_id": 123, "step": 2}), 100
    yield json.dumps({"chat_id": 456, "step": 2}), 100


@pytest.mark.asyncio
async def test_delete_cascades_and_scrubs_user_jobs() -> None:
    session = AsyncMock()
    redis = MagicMock()
    redis.set = AsyncMock()
    redis.delete = AsyncMock()
    redis.zrem = AsyncMock()
    redis.xack = AsyncMock()
    redis.xdel = AsyncMock()
    redis.scan_iter.side_effect = _keys
    redis.zscan_iter.side_effect = _scheduled
    redis.xrange = AsyncMock(
        return_value=[
            ("1-0", {"payload": json.dumps({"chat_id": 123})}),
            ("2-0", {"payload": json.dumps({"chat_id": 456})}),
        ]
    )
    await delete_user_data(session, redis, 123)
    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()
    redis.set.assert_any_await("privacy:deleted:123", "1", ex=691200)
    redis.zrem.assert_awaited_once()
    redis.xack.assert_awaited_once_with("delivery_stream", "delivery_workers", "1-0")
    redis.xdel.assert_awaited_once_with("delivery_stream", "1-0")
