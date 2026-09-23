"""Real Redis checks run in CI; local runs skip when Redis is unavailable."""

import os
import time
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from alert_bot_project.worker.broadcaster import POP_MATURE_TASKS_LUA, Broadcaster
from alert_bot_project.worker.main import init_redis_consumer_group
from alert_bot_project.worker.stream_retention import trim_acknowledged_stream


async def _redis() -> Redis:
    client = Redis.from_url("redis://localhost:6379/15", decode_responses=True)
    try:
        await client.ping()
    except RedisConnectionError:
        await client.aclose()
        if os.getenv("GITHUB_ACTIONS") == "true":
            pytest.fail("CI Redis service is required for delivery integration tests")
        pytest.skip("local Redis is not running")
    return client


@pytest.mark.asyncio
@settings(max_examples=12, deadline=None)
@given(recipients=st.integers(min_value=1, max_value=125))
async def test_fanout_is_idempotent_and_delayed_pop_preserves_every_job(recipients: int) -> None:
    client = await _redis()
    suffix = uuid.uuid4().hex
    broadcaster = Broadcaster(AsyncMock(), client)
    broadcaster.delivery_stream_name = f"test:delivery:{suffix}"
    broadcaster.delayed_queue_key = f"test:delayed:{suffix}"
    try:
        with patch("time.time", return_value=1700000000):
            for user_id in range(1, recipients + 1):
                assert await broadcaster.enqueue_alert(-100, 42, user_id)
                assert not await broadcaster.enqueue_alert(-100, 42, user_id)

        assert await client.xlen(broadcaster.delivery_stream_name) == recipients
        assert await client.zcard(broadcaster.delayed_queue_key) == 2 * recipients

        moved = 0
        while True:
            count = await client.eval(
                POP_MATURE_TASKS_LUA,
                2,
                broadcaster.delayed_queue_key,
                broadcaster.delivery_stream_name,
                1700000000 + 10000,
                50,
            )
            if not count:
                break
            assert count <= 50
            moved += count
        assert moved == 2 * recipients
        assert await client.zcard(broadcaster.delayed_queue_key) == 0
        assert await client.xlen(broadcaster.delivery_stream_name) == 3 * recipients
    finally:
        keys = [f"delivery:enqueued:-100:42:{user_id}" for user_id in range(1, recipients + 1)]
        await client.delete(broadcaster.delivery_stream_name, broadcaster.delayed_queue_key, *keys)
        await client.aclose()


@pytest.mark.asyncio
async def test_new_group_reads_preexisting_entries_and_trim_preserves_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    client = await _redis()
    suffix = uuid.uuid4().hex
    source_stream = f"test:source:{suffix}"
    group = f"test:group:{suffix}"
    monkeypatch.setattr("alert_bot_project.worker.main.STREAM_NAME", source_stream)
    monkeypatch.setattr("alert_bot_project.worker.main.GROUP_NAME", group)
    try:
        ids = [await client.xadd(source_stream, {"payload": str(i)}) for i in range(6)]
        await init_redis_consumer_group(client)
        first = await client.xreadgroup(group, "consumer-a", {source_stream: ">"}, count=4)
        assert [message_id for message_id, _ in first[0][1]] == ids[:4]
        await client.xack(source_stream, group, *ids[:3])
        await trim_acknowledged_stream(client, source_stream)
        remaining = [message_id for message_id, _ in await client.xrange(source_stream)]
        assert ids[3] in remaining
        assert ids[4] in remaining
        assert ids[5] in remaining
        later = await client.xreadgroup(group, "consumer-b", {source_stream: ">"}, count=2)
        assert [message_id for message_id, _ in later[0][1]] == ids[4:]
    finally:
        await client.delete(source_stream)
        await client.aclose()


@pytest.mark.asyncio
async def test_future_delayed_job_not_popped() -> None:
    client = await _redis()
    suffix = uuid.uuid4().hex
    delayed = f"test:delayed:{suffix}"
    delivery = f"test:delivery:{suffix}"
    try:
        await client.zadd(delayed, {"future": int(time.time()) + 3600})
        moved = await client.eval(POP_MATURE_TASKS_LUA, 2, delayed, delivery, int(time.time()), 50)
        assert moved == 0
        assert await client.zcard(delayed) == 1
        assert await client.exists(delivery) == 0
    finally:
        await client.delete(delayed, delivery)
        await client.aclose()


@pytest.mark.asyncio
async def test_distinct_source_posts_keep_distinct_delayed_stages() -> None:
    client = await _redis()
    suffix = uuid.uuid4().hex
    broadcaster = Broadcaster(AsyncMock(), client)
    broadcaster.delivery_stream_name = f"test:delivery:{suffix}"
    broadcaster.delayed_queue_key = f"test:delayed:{suffix}"
    try:
        await broadcaster.enqueue_alert(-100, 41, 777)
        await broadcaster.enqueue_alert(-100, 42, 777)
        assert await client.xlen(broadcaster.delivery_stream_name) == 2
        assert await client.zcard(broadcaster.delayed_queue_key) == 4
    finally:
        await client.delete(
            broadcaster.delivery_stream_name,
            broadcaster.delayed_queue_key,
            "delivery:enqueued:-100:41:777",
            "delivery:enqueued:-100:42:777",
        )
        await client.aclose()
