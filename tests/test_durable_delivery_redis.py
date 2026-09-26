"""Real Redis checks run in CI; local runs skip when Redis is unavailable."""

import json
import os
import time
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError

from alert_bot_project.core_shared.trigger_cache import reconcile_custom_trigger_cache, update_custom_trigger_cache
from alert_bot_project.scraper.publisher import PUBLISH_ONCE_LUA, SOURCE_REPLAY_HORIZON_SECONDS, RedisPublisher
from alert_bot_project.services.privacy import (
    BEGIN_DELIVERY_LUA,
    END_DELIVERY_LUA,
    FENCE_DELETION_LUA,
    delete_user_data,
    user_privacy_lock,
)
from alert_bot_project.worker.broadcaster import POP_MATURE_TASKS_LUA, STORE_DLQ_LUA, Broadcaster
from alert_bot_project.worker.main import init_redis_consumer_group
from alert_bot_project.worker.queue_metrics import delivery_backlog
from alert_bot_project.worker.rate_limit import ACQUIRE_SLOT_LUA
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
        marker_ttl = await client.ttl("delivery:enqueued:-100:42:1")
        assert 0 < marker_ttl <= SOURCE_REPLAY_HORIZON_SECONDS

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


@pytest.mark.asyncio
async def test_source_publish_is_idempotent_after_uncertain_result() -> None:
    client = await _redis()
    suffix = uuid.uuid4().hex
    marker = f"test:published:{suffix}"
    stream = f"test:source:{suffix}"
    try:
        first = await client.eval(PUBLISH_ONCE_LUA, 2, marker, stream, '{"message_id":1}')
        second = await client.eval(PUBLISH_ONCE_LUA, 2, marker, stream, '{"message_id":1}')
        assert first != 0
        assert second == 0
        assert await client.xlen(stream) == 1
        assert 0 < await client.ttl(marker) <= SOURCE_REPLAY_HORIZON_SECONDS
    finally:
        await client.delete(marker, stream)
        await client.aclose()


@pytest.mark.asyncio
async def test_shared_rate_slot_limits_global_and_per_chat() -> None:
    client = await _redis()
    suffix = uuid.uuid4().hex
    keys = [f"test:rate:global:{suffix}", f"test:rate:chat:{suffix}", f"test:rate:repeat:{suffix}"]
    try:
        assert await client.eval(ACQUIRE_SLOT_LUA, 3, *keys, 0) == 0
        assert await client.eval(ACQUIRE_SLOT_LUA, 3, *keys, 0) > 0
        await client.delete(keys[0])
        assert await client.eval(ACQUIRE_SLOT_LUA, 3, *keys, 0) > 0
    finally:
        await client.delete(*keys)
        await client.aclose()


@pytest.mark.asyncio
async def test_privacy_fence_blocks_new_fanout_and_delayed_transfer() -> None:
    client = await _redis()
    suffix = uuid.uuid4().hex
    recipient = 1_000_000_000_000_000 + int(suffix[:8], 16)
    broadcaster = Broadcaster(AsyncMock(), client)
    broadcaster.delivery_stream_name = f"test:delivery:{suffix}"
    broadcaster.delayed_queue_key = f"test:delayed:{suffix}"
    deleted_key = f"privacy:deleted:{recipient}"
    generation_key = f"privacy:generation:{recipient}"
    marker = f"delivery:enqueued:-100:42:{recipient}"
    try:
        assert await broadcaster.enqueue_alert(-100, 42, recipient)
        await client.eval(FENCE_DELETION_LUA, 2, deleted_key, generation_key, "new-generation")
        assert await client.ttl(deleted_key) == -1
        assert await client.ttl(generation_key) == -1
        assert not await broadcaster.enqueue_alert(-100, 43, recipient)
        assert (
            await client.eval(
                POP_MATURE_TASKS_LUA,
                2,
                broadcaster.delayed_queue_key,
                broadcaster.delivery_stream_name,
                int(time.time()) + 10000,
                50,
            )
            == 2
        )
        assert await client.xlen(broadcaster.delivery_stream_name) == 1
        assert await client.zcard(broadcaster.delayed_queue_key) == 0
    finally:
        await client.delete(
            deleted_key, generation_key, marker, broadcaster.delivery_stream_name, broadcaster.delayed_queue_key
        )
        await client.aclose()


@pytest.mark.asyncio
async def test_deletion_scrubs_only_own_dlq_payload_and_rejects_late_failure() -> None:
    client = await _redis()
    user_id = 1_000_000_007_744_332
    other_id = user_id + 1
    try:
        await client.delete(
            "delivery_stream",
            "delivery_dead_letter_queue",
            f"privacy:deleted:{user_id}",
            f"privacy:generation:{user_id}",
        )
        await client.xgroup_create("delivery_stream", "delivery_workers", id="0-0", mkstream=True)
        await client.xadd(
            "delivery_dead_letter_queue", {"payload": json.dumps({"chat_id": user_id, "text": "private"})}
        )
        await client.xadd("delivery_dead_letter_queue", {"payload": json.dumps({"chat_id": other_id, "text": "keep"})})
        await delete_user_data(AsyncMock(), client, user_id)
        remaining = await client.xrange("delivery_dead_letter_queue")
        assert len(remaining) == 1
        assert json.loads(remaining[0][1]["payload"])["chat_id"] == other_id

        job = json.dumps({"chat_id": user_id, "recipient_generation": "0", "event_id": "event", "step": 1})
        message_id = await client.xadd("delivery_stream", {"payload": job})
        await client.xreadgroup("delivery_workers", "test-worker", {"delivery_stream": ">"}, count=1)
        await client.eval(
            STORE_DLQ_LUA,
            3,
            "delivery_dead_letter_queue",
            "delivery_stream",
            f"delivery:retry:{message_id}",
            job,
            "telegram_forbidden",
            message_id,
            "delivery_workers",
            "",
        )
        assert await client.xlen("delivery_dead_letter_queue") == 1
    finally:
        await client.delete(
            "delivery_stream",
            "delivery_dead_letter_queue",
            f"privacy:deleted:{user_id}",
            f"privacy:generation:{user_id}",
            f"privacy:inflight:{user_id}",
        )
        await client.aclose()


@pytest.mark.asyncio
async def test_deletion_fence_waits_for_reserved_delivery() -> None:
    client = await _redis()
    user_id = 7744332200
    deleted_key = f"privacy:deleted:{user_id}"
    generation_key = f"privacy:generation:{user_id}"
    inflight_key = f"privacy:inflight:{user_id}"
    try:
        await client.delete(deleted_key, generation_key, inflight_key)
        assert await client.eval(BEGIN_DELIVERY_LUA, 3, deleted_key, generation_key, inflight_key, "0") == 1
        await client.eval(FENCE_DELETION_LUA, 2, deleted_key, generation_key, "new-generation")
        assert await client.eval(BEGIN_DELIVERY_LUA, 3, deleted_key, generation_key, inflight_key, "0") == 0
        assert await client.get(inflight_key) == "1"
        await client.eval(END_DELIVERY_LUA, 1, inflight_key)
        assert await client.get(inflight_key) is None
    finally:
        await client.delete(deleted_key, generation_key, inflight_key)
        await client.aclose()


@pytest.mark.asyncio
async def test_registration_cannot_overlap_deletion_lock() -> None:
    client = await _redis()
    user_id = 1_000_000_007_744_333
    key = f"privacy:operation:{user_id}"
    try:
        async with user_privacy_lock(client, user_id):
            with pytest.raises(RedisError):
                async with user_privacy_lock(client, user_id):
                    pass
        assert await client.exists(key) == 0
    finally:
        await client.delete(key)
        await client.aclose()


@pytest.mark.asyncio
async def test_delivery_age_ignores_acknowledged_history_but_detects_stuck_job() -> None:
    client = await _redis()
    suffix = uuid.uuid4().hex
    stream = f"test:metrics:{suffix}"
    group = f"test:metrics-group:{suffix}"
    old_ms = int((time.time() - 900) * 1000)
    try:
        first = await client.xadd(stream, {"payload": "acknowledged"}, id=f"{old_ms}-0")
        await client.xgroup_create(stream, group, id="0-0")
        await client.xreadgroup(group, "consumer", {stream: ">"}, count=1)
        await client.xack(stream, group, first)
        assert await delivery_backlog(client, stream, group) == (0, 0.0)

        second = await client.xadd(stream, {"payload": "stuck"}, id=f"{old_ms + 1}-0")
        depth, age = await delivery_backlog(client, stream, group)
        assert depth == 1
        assert age > 600
        await client.xreadgroup(group, "consumer", {stream: ">"}, count=1)
        depth, age = await delivery_backlog(client, stream, group)
        assert depth == 1
        assert age > 600
        await client.xack(stream, group, second)
        assert await delivery_backlog(client, stream, group) == (0, 0.0)
    finally:
        await client.delete(stream)
        await client.aclose()


@pytest.mark.asyncio
async def test_legacy_source_markers_gain_ttl_without_shortening_existing_ttl() -> None:
    client = await _redis()
    suffix = uuid.uuid4().hex
    legacy = f"source:published:-100:{suffix}"
    recent = f"source:published:-101:{suffix}"
    publisher = RedisPublisher()
    publisher._redis = client
    try:
        await client.set(legacy, "1-0")
        await client.set(recent, "1-0", ex=60)
        await publisher.expire_legacy_markers()
        assert SOURCE_REPLAY_HORIZON_SECONDS - 60 < await client.ttl(legacy) <= SOURCE_REPLAY_HORIZON_SECONDS
        assert 0 < await client.ttl(recent) <= 60
    finally:
        await client.delete(legacy, recent)
        await client.aclose()


@pytest.mark.asyncio
@settings(max_examples=8, deadline=None)
@given(phrases=st.sets(st.text(alphabet="абвгде", min_size=3, max_size=8), max_size=10))
async def test_trigger_cache_version_changes_only_with_membership(phrases: set[str]) -> None:
    client = await _redis()
    keys = ("global_custom_triggers", "global_custom_triggers:version")
    try:
        await client.delete(*keys)
        assert await reconcile_custom_trigger_cache(client, phrases, None) == int(bool(phrases))
        version = await client.get(keys[1])
        assert await reconcile_custom_trigger_cache(client, phrases, version) == 0
        assert await client.get(keys[1]) == version
        assert await client.smembers(keys[0]) == phrases
        assert await update_custom_trigger_cache(client, "уникальная_фраза", add=True)
        assert not await update_custom_trigger_cache(client, "уникальная_фраза", add=True)
        assert await reconcile_custom_trigger_cache(client, phrases, version) == -1
    finally:
        await client.delete(*keys)
        await client.aclose()
