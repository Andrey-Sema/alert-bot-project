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
    redis.register_script.return_value = AsyncMock(return_value=1)
    redis.set = AsyncMock(return_value=True)
    redis.get = AsyncMock(return_value=None)
    redis.delete = AsyncMock()
    redis.zrem = AsyncMock()
    redis.xack = AsyncMock()
    redis.xdel = AsyncMock()
    redis.scan_iter.side_effect = _keys
    redis.zscan_iter.side_effect = _scheduled

    async def stream_entries(stream: str, **_kwargs: object):
        if stream == "delivery_stream":
            return [
                ("1-0", {"payload": json.dumps({"chat_id": 123})}),
                ("2-0", {"payload": json.dumps({"chat_id": 456})}),
            ]
        return [
            ("3-0", {"payload": json.dumps({"chat_id": 123})}),
            ("4-0", {"payload": json.dumps({"chat_id": 456})}),
        ]

    redis.xrange = AsyncMock(side_effect=stream_entries)
    await delete_user_data(session, redis, 123)
    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()
    fence_call = redis.register_script.return_value.await_args_list[0]
    assert fence_call.kwargs["keys"] == ["privacy:deleted:123", "privacy:generation:123"]
    assert len(fence_call.kwargs["args"][0]) == 32
    redis.zrem.assert_awaited_once()
    redis.xack.assert_awaited_once_with("delivery_stream", "delivery_workers", "1-0")
    redis.xdel.assert_any_await("delivery_stream", "1-0")
    redis.xdel.assert_any_await("delivery_dead_letter_queue", "3-0")
    assert redis.xdel.await_count == 2
