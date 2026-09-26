"""Regression checks for external payloads and bounded delivery ownership."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from alert_bot_project.core_shared.schemas import AlertMessage
from alert_bot_project.services.ukrainealarm import (
    OFFICIAL_ALARM_KEY,
    AlarmStatePoller,
    UkraineAlarmClient,
    UkraineAlarmError,
)
from alert_bot_project.worker.broadcaster import Broadcaster, DeliveryOutcome
from alert_bot_project.worker.main import _validate_payload


@given(timestamp=st.datetimes(timezones=st.none()))
def test_naive_source_time_is_rejected(timestamp: datetime) -> None:
    with pytest.raises(ValidationError):
        AlertMessage(message_id=1, chat_id=-100, raw_text="alert", timestamp=timestamp)


def test_future_source_time_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AlertMessage(message_id=1, chat_id=-100, raw_text="alert", timestamp=datetime.now(UTC) + timedelta(hours=1))


@pytest.mark.asyncio
async def test_invalid_source_time_does_not_poison_pending_queue() -> None:
    redis = AsyncMock()
    payload = json.dumps({"message_id": 1, "chat_id": -100, "raw_text": "a", "timestamp": "2026-01-01T00:00:00"})
    assert await _validate_payload(redis, "1-0", payload) is None
    redis.xack.assert_awaited_once_with("alerts_stream", "workers_group", "1-0")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"error": "unavailable"},
        None,
        [None],
        [{"activeAlerts": None}],
        [{"activeAlerts": [{}]}],
        [{"activeAlerts": [{"type": 1}]}],
    ],
)
async def test_malformed_official_state_is_not_clear(payload: object) -> None:
    client = UkraineAlarmClient("test_key")
    with patch.object(client, "_get", new=AsyncMock(return_value=payload)), pytest.raises(UkraineAlarmError):
        await client.get_region_alerts("123")


@pytest.mark.asyncio
async def test_empty_official_alerts_is_valid_clear() -> None:
    client = UkraineAlarmClient("test_key")
    with patch.object(client, "_get", new=AsyncMock(return_value=[])):
        assert not client.is_air_active(await client.get_region_alerts("123"))


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, [], {"lastActionIndex": True}, {"lastActionIndex": -1}])
async def test_malformed_status_index_cannot_extend_cached_state(payload: object) -> None:
    client = UkraineAlarmClient("test_key")
    with patch.object(client, "_get", new=AsyncMock(return_value=payload)), pytest.raises(UkraineAlarmError):
        await client.get_status_index()


@pytest.mark.asyncio
async def test_missing_redis_state_is_rebuilt_despite_unchanged_index() -> None:
    redis = AsyncMock()
    redis.expire.return_value = False
    poller = AlarmStatePoller(redis, api_key="test_key", region_id="123")
    poller._last_index = 1
    await poller._write_state(True)
    assert poller.client is not None
    with (
        patch.object(poller.client, "get_status_index", new=AsyncMock(return_value=1)),
        patch.object(poller.client, "get_region_alerts", new=AsyncMock(return_value=[])) as fetch,
    ):
        await poller._poll_once()
    fetch.assert_awaited_once()
    redis.set.assert_awaited_with(OFFICIAL_ALARM_KEY, "0", ex=90)


@pytest.mark.asyncio
async def test_official_http_does_not_follow_redirect_or_log_response_body() -> None:
    client = UkraineAlarmClient("test_key")
    response = MagicMock(status=302)
    response.text = AsyncMock(return_value="secret body")
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.get.return_value = context
    with (
        patch.object(client, "_ensure_session", new=AsyncMock(return_value=session)),
        pytest.raises(UkraineAlarmError, match="HTTP 302"),
    ):
        await client._get("/alerts/123")
    session.get.assert_called_once_with("/api/v3/alerts/123", allow_redirects=False)
    response.text.assert_not_awaited()


@pytest.mark.asyncio
async def test_rate_wait_timeout_leaves_job_retriable() -> None:
    bot = AsyncMock()
    broadcaster = Broadcaster(bot, MagicMock())

    async def blocked_slot(*_args: object, **_kwargs: object) -> None:
        await asyncio.Event().wait()

    with (
        patch.object(broadcaster.rate_limiter, "acquire", new=blocked_slot),
        patch("alert_bot_project.worker.broadcaster.config") as config,
    ):
        config.TELEGRAM_MAX_RETRY_SECONDS = 0.01
        assert await broadcaster.send_single_message(777, "a") == DeliveryOutcome("retry", "rate_limit_timeout")
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_skipped_second_stage_terminates_third_stage() -> None:
    redis = MagicMock()
    redis.get = AsyncMock(side_effect=lambda key: "skipped" if key == "delivery:stage:event:2" else None)
    redis.exists = AsyncMock(return_value=False)
    redis.pipeline.return_value.execute = AsyncMock()
    bot = AsyncMock()
    broadcaster = Broadcaster(bot, redis)
    await broadcaster._deliver_one(
        "3-0", {"payload": json.dumps({"event_id": "event", "step": 3, "chat_id": 777, "text": "a"})}
    )
    pipe = redis.pipeline.return_value
    pipe.set.assert_called_once_with("delivery:stage:event:3", "skipped", ex=604800)
    pipe.xack.assert_called_once_with("delivery_stream", "delivery_workers", "3-0")
    pipe.zadd.assert_not_called()
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_consumer_reserves_only_one_job_with_sufficient_lease() -> None:
    redis = MagicMock()
    redis.xautoclaim = AsyncMock(return_value=["0-0", []])
    redis.xreadgroup = AsyncMock(side_effect=asyncio.CancelledError)
    broadcaster = Broadcaster(AsyncMock(), redis)
    with pytest.raises(asyncio.CancelledError):
        await broadcaster.process_delivery_stream(0)
    assert redis.xautoclaim.call_args.kwargs["count"] == 1
    assert redis.xautoclaim.call_args.kwargs["min_idle_time"] >= 360000
    assert redis.xreadgroup.call_args.kwargs["count"] == 1
