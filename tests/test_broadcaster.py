import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter

from alert_bot_project.worker.broadcaster import Broadcaster


@pytest.fixture
def mock_bot() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_redis() -> MagicMock:
    client = MagicMock()
    client.register_script.return_value = AsyncMock(return_value=1)
    client.xack = AsyncMock()
    client.delete = AsyncMock()
    client.exists = AsyncMock(return_value=False)
    client.incr = AsyncMock(return_value=1)
    client.expire = AsyncMock()
    client.get = AsyncMock(return_value=None)
    pipe = MagicMock()
    pipe.execute = AsyncMock()
    client.pipeline.return_value = pipe
    return client


@pytest.mark.asyncio
async def test_enqueue_all_stages_with_stable_recipient_identity(mock_bot: AsyncMock, mock_redis: MagicMock) -> None:
    broadcaster = Broadcaster(mock_bot, mock_redis)
    with patch("time.time", return_value=1700000000):
        assert await broadcaster.enqueue_alert(-100, 42, 777)
    keys = mock_redis.register_script.return_value.call_args.kwargs["keys"]
    args = mock_redis.register_script.return_value.call_args.kwargs["args"]
    assert keys == ["delivery:enqueued:-100:42:777", "delivery_stream", "delayed_alerts_queue"]
    assert json.loads(args[0])["step"] == 1
    assert json.loads(args[2])["step"] == 2
    assert json.loads(args[4])["step"] == 3
    assert args[1] < args[3]
    assert args[5] == 0


@pytest.mark.asyncio
@patch("asyncio.sleep")
async def test_send_single_message_handles_flood_control_retry(
    mock_sleep: MagicMock, mock_bot: AsyncMock, mock_redis: MagicMock
) -> None:
    broadcaster = Broadcaster(mock_bot, mock_redis)
    mock_bot.send_message.side_effect = [
        TelegramRetryAfter(retry_after=5, method=MagicMock(), message="Flood control"),
        AsyncMock(),
    ]
    assert await broadcaster.send_single_message(777, "Тест") is True
    assert mock_bot.send_message.call_count == 2
    mock_sleep.assert_any_call(5)


@pytest.mark.asyncio
async def test_failed_send_remains_pending(mock_bot: AsyncMock, mock_redis: MagicMock) -> None:
    broadcaster = Broadcaster(mock_bot, mock_redis)
    mock_bot.send_message.side_effect = TelegramAPIError(message="Chat not found", method=MagicMock())
    payload = json.dumps({"chat_id": 777, "step": 1, "text": "alert", "silent": False})
    await broadcaster._deliver_one("123-0", {"payload": payload})
    mock_redis.xack.assert_not_awaited()
    mock_redis.incr.assert_awaited_once_with("delivery:retry:123-0")


@pytest.mark.asyncio
async def test_success_acknowledges_only_after_send(mock_bot: AsyncMock, mock_redis: MagicMock) -> None:
    broadcaster = Broadcaster(mock_bot, mock_redis)
    with patch.object(broadcaster, "send_single_message", new_callable=AsyncMock, return_value=True) as send:
        await broadcaster._deliver_one("123-0", {"payload": json.dumps({"chat_id": 777, "step": 1, "text": "a"})})
    send.assert_awaited_once()
    mock_redis.pipeline.return_value.xack.assert_called_once_with("delivery_stream", "delivery_workers", "123-0")


@pytest.mark.asyncio
async def test_stale_alert_is_silent_and_has_no_repeats(mock_bot: AsyncMock, mock_redis: MagicMock) -> None:
    broadcaster = Broadcaster(mock_bot, mock_redis)
    await broadcaster.enqueue_alert(-100, 42, 777, stale=True)
    args = mock_redis.register_script.return_value.call_args.kwargs["args"]
    assert json.loads(args[0])["silent"] is True
    assert "неактуальним" in json.loads(args[0])["text"]
    assert args[5] == 1


@pytest.mark.asyncio
async def test_second_stage_waits_for_first(mock_bot: AsyncMock, mock_redis: MagicMock) -> None:
    broadcaster = Broadcaster(mock_bot, mock_redis)
    payload = json.dumps({"event_id": "event", "chat_id": 777, "step": 2, "text": "repeat"})
    await broadcaster._deliver_one("123-0", {"payload": payload})
    mock_bot.send_message.assert_not_awaited()
    pipe = mock_redis.pipeline.return_value
    pipe.zadd.assert_called_once()
    pipe.xack.assert_called_once_with("delivery_stream", "delivery_workers", "123-0")
