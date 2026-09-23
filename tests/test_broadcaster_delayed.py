import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alert_bot_project.worker.broadcaster import POP_MATURE_TASKS_LUA, Broadcaster


@pytest.mark.asyncio
async def test_delayed_transfer_uses_both_stream_and_zset() -> None:
    redis_client = MagicMock()
    script = AsyncMock(side_effect=[50, asyncio.CancelledError()])
    redis_client.register_script.return_value = script
    broadcaster = Broadcaster(AsyncMock(), redis_client)
    with patch("asyncio.sleep", new_callable=AsyncMock), pytest.raises(asyncio.CancelledError):
        await broadcaster.process_delayed_alerts()
    assert script.call_args.kwargs["keys"] == ["delayed_alerts_queue", "delivery_stream"]
    assert script.call_args.kwargs["args"][1] == 50
    assert "ZREMRANGEBYSCORE" not in POP_MATURE_TASKS_LUA
    assert "ZREM" in POP_MATURE_TASKS_LUA


@pytest.mark.asyncio
async def test_db_muted_delayed_job_acknowledged_without_sending() -> None:
    redis_client = MagicMock()
    redis_client.exists = AsyncMock(return_value=True)
    redis_client.get = AsyncMock(return_value="sent")
    redis_client.xack = AsyncMock()
    broadcaster = Broadcaster(AsyncMock(), redis_client)
    with (
        patch.object(broadcaster, "_is_night", return_value=True),
        patch.object(broadcaster, "_db_mute_active", return_value=True),
    ):
        await broadcaster._deliver_one(
            "123-0",
            {"payload": json.dumps({"event_id": "test", "chat_id": 555, "step": 2, "text": "repeat", "silent": False})},
        )
    broadcaster.bot.send_message.assert_not_awaited()
    redis_client.xack.assert_awaited_once()
