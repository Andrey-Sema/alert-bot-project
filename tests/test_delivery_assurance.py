"""Negative, property and concurrency coverage for delivery security boundaries."""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from alert_bot_project.core_shared.logging_config import RedactingConsoleFormatter, StructuredJsonFormatter
from alert_bot_project.worker.broadcaster import Broadcaster, DeliveryOutcome, DeliveryReservation
from alert_bot_project.worker.delivery_contract import DeliveryJob, delivery_content, parse_delivery_job
from alert_bot_project.worker.delivery_lease import DeliveryLease
from alert_bot_project.worker.main import _validate_payload


def _job(**changes: object) -> DeliveryJob:
    return DeliveryJob.model_validate(
        {
            "chat_id": "777",
            "event_id": "event",
            "step": 1,
            "text": "alert",
            "source_timestamp": datetime.now(UTC).isoformat(),
            **changes,
        }
    )


@given(value=st.one_of(st.none(), st.booleans(), st.integers(), st.text(), st.lists(st.integers(), max_size=10)))
def test_non_object_delivery_payload_is_rejected(value: object) -> None:
    with pytest.raises(ValueError, match="must be an object"):
        parse_delivery_job(json.dumps(value))


@pytest.mark.parametrize(
    "changes",
    [
        {"chat_id": True},
        {"chat_id": 1.5},
        {"chat_id": "00777"},
        {"chat_id": 0},
        {"chat_id": 2**53},
        {"step": True},
        {"step": "1"},
        {"step": 4},
        {"silent": "false"},
        {"text": {"html": "a"}},
        {"text": "a" * 4097},
        {"unknown": "field"},
        {"source_timestamp": "2026-01-01T01:00:00"},
        {"source_chat_id": -100},
        {"source_chat_id": -100, "source_message_id": 42},
        {"source_locations": ["../../other"]},
        {"recipient_generation": 1},
    ],
)
def test_invalid_contract_fields_are_rejected(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _job(**changes)


def test_duplicate_json_fields_cannot_select_different_recipient() -> None:
    with pytest.raises(ValueError, match="Duplicate"):
        parse_delivery_job('{"chat_id":777,"chat_id":888,"step":1,"text":"a"}')


@given(age=st.integers(min_value=601, max_value=604700), step=st.integers(min_value=1, max_value=3))
def test_old_jobs_never_create_an_audible_current_threat(age: int, step: int) -> None:
    job = _job(step=step, source_timestamp=datetime.now(UTC) - timedelta(seconds=age))
    content = delivery_content(job, "alert", False)
    if step == 1:
        assert content is not None
        assert content[1] is True
    else:
        assert content is None


def test_missing_or_expired_time_cannot_schedule_a_current_alert() -> None:
    assert delivery_content(_job(source_timestamp=None), "alert", False)[1] is True
    assert delivery_content(_job(source_timestamp=datetime.now(UTC) - timedelta(days=8)), "alert", False) is None


@pytest.mark.asyncio
async def test_invalid_job_is_quarantined_without_personal_payload_or_retry_loop() -> None:
    broadcaster = Broadcaster(AsyncMock(), MagicMock())
    payload = '{"chat_id":777,"step":true,"text":"private_payload"}'
    with patch.object(broadcaster, "_move_to_dlq", new=AsyncMock()) as quarantine:
        await broadcaster._deliver_one("1-0", {"payload": payload})
    quarantine.assert_awaited_once_with("1-0", "", "invalid_delivery_contract")
    broadcaster.bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_source_validation_error_does_not_log_private_payload(caplog: pytest.LogCaptureFixture) -> None:
    payload = json.dumps({"chat_id": -100, "message_id": 42, "raw_text": {"private_marker": "private_source_text"}})
    assert await _validate_payload(AsyncMock(), "42-0", payload) is None
    assert "private_source_text" not in caplog.text
    assert "42-0" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("step", [1, 2, 3])
async def test_freshness_is_rechecked_after_rate_slot_wait(step: int) -> None:
    broadcaster = Broadcaster(AsyncMock(), MagicMock())
    job = _job(step=step, source_timestamp=datetime.now(UTC) - timedelta(seconds=590))
    reservation = DeliveryReservation("0", job=job)

    async def cross_freshness_boundary(*_args: object, **_kwargs: object) -> None:
        job.source_timestamp = datetime.now(UTC) - timedelta(seconds=610)

    broadcaster.rate_limiter.acquire = cross_freshness_boundary
    broadcaster.redis.register_script.return_value = AsyncMock(return_value=1)
    outcome = await broadcaster.send_single_message(777, "alert", reservation=reservation)
    if step == 1:
        assert outcome.status == "sent"
        assert broadcaster.bot.send_message.call_args.kwargs["disable_notification"] is True
        assert "неактуальним" in broadcaster.bot.send_message.call_args.kwargs["text"]
    else:
        assert outcome == DeliveryOutcome("cancelled", "stale_delivery")
        broadcaster.bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_lost_owner_cannot_send_after_rate_wait() -> None:
    broadcaster = Broadcaster(AsyncMock(), MagicMock())
    broadcaster.rate_limiter.acquire = AsyncMock()
    reservation = DeliveryReservation("0", job=_job(), guard=AsyncMock(return_value=False))
    assert await broadcaster.send_single_message(777, "a", reservation=reservation) == DeliveryOutcome(
        "retry", "ownership_lost"
    )
    broadcaster.bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_lease_loss_cancels_operation_and_does_not_kill_consumer() -> None:
    redis = MagicMock()
    redis.register_script.return_value = AsyncMock()
    lease = DeliveryLease(redis, "stream", "group", "owner", "1-0", "event:1")
    lease.interval = 0.001
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def operation() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    with patch.object(lease, "renew", new=AsyncMock(side_effect=[True, False])):
        await lease.run(operation, 1)
    assert started.is_set()
    assert cancelled.is_set()


@pytest.mark.parametrize("formatter", [RedactingConsoleFormatter(), StructuredJsonFormatter()])
def test_both_log_sinks_redact_credentials_and_escape_newlines(formatter: logging.Formatter) -> None:
    secret = "987654321:abcdefghijklmnopqrstuvwx"
    record = logging.LogRecord(
        "test",
        logging.ERROR,
        "test.py",
        1,
        f"failure {secret} postgresql://user:private@host/db\nforged record",
        (),
        None,
    )
    record.extra_metadata = {"authorization": "private", "nested": {"password": "also_private"}}
    with patch("alert_bot_project.core_shared.redaction.config") as config:
        config.BOT_TOKEN = secret
        config.API_HASH = ""
        config.DATABASE_URL = ""
        config.REDIS_URL = ""
        config.UKRAINEALARM_API_KEY = ""
        output = formatter.format(record)
    assert secret not in output
    assert "user:private" not in output
    assert "also_private" not in output
    assert "\n" not in output
    assert "[REDACTED]" in output
