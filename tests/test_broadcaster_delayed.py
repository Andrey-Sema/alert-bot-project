# noinspection PyPackageRequirements,PyUnresolvedReferences,SpellCheckingInspection
import pytest
import json
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import time
from alert_bot_project.worker.broadcaster import Broadcaster


@pytest.fixture
def mock_bot() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_redis() -> MagicMock:
    # ✅ СЕНЬОР-ФИКС: Разделяем синхронные и асинхронные методы Redis для защиты от вечных циклов
    r = MagicMock()
    r.register_script = MagicMock()  # Синхронный по контракту библиотеки
    r.exists = AsyncMock()           # Асинхронные
    r.zadd = AsyncMock()
    return r


class TestBroadcasterDelayedLogic:

    @pytest.mark.asyncio
    async def test_execute_scheduling_stores_correct_unix_intervals(self, mock_bot: AsyncMock, mock_redis: MagicMock) -> None:
        broadcaster = Broadcaster(bot=mock_bot, redis_client=mock_redis)

        with patch("time.time", return_value=1700000000):
            await broadcaster._execute_scheduling(chat_id=555, disable_notification=False)

            mock_redis.zadd.assert_called_once()
            called_args = mock_redis.zadd.call_args[1]
            mapping = called_args[0] if len(called_args) == 1 else mock_redis.zadd.call_args[0][1]

            steps = [json.loads(k)["step"] for k in mapping.keys()]
            assert 2 in steps
            assert 3 in steps

    @pytest.mark.asyncio
    async def test_process_single_delayed_task_corrupted_json(self, mock_bot: AsyncMock, mock_redis: MagicMock) -> None:
        broadcaster = Broadcaster(bot=mock_bot, redis_client=mock_redis)
        await broadcaster._process_single_delayed_task("This is totally not a json payload string")
        mock_redis.exists.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_single_delayed_task_skips_if_muted(self, mock_bot: AsyncMock, mock_redis: MagicMock) -> None:
        broadcaster = Broadcaster(bot=mock_bot, redis_client=mock_redis)
        mock_redis.exists.return_value = True

        task_raw = json.dumps({"chat_id": 555, "step": 2, "text": "Повторная тревога", "silent": False})

        with patch.object(broadcaster, "fire_and_forget_message") as mock_fire:
            await broadcaster._process_single_delayed_task(task_raw)
            mock_fire.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_delayed_alerts_drops_tasks_during_daytime(self, mock_bot: AsyncMock, mock_redis: MagicMock) -> None:
        broadcaster = Broadcaster(bot=mock_bot, redis_client=mock_redis)

        # Скрипт — корутина, которая будет вызвана внутри
        mock_script = AsyncMock()
        mock_script.side_effect = [["some_task_payload"], asyncio.CancelledError()]
        mock_redis.register_script.return_value = mock_script

        daytime_mock = time(12, 0, 0)

        with patch("alert_bot_project.worker.broadcaster.datetime") as mock_dt, \
                patch.object(broadcaster, "_process_single_delayed_task") as mock_process_task:
            mock_dt.now.return_value.time.return_value = daytime_mock

            with pytest.raises(asyncio.CancelledError):
                await broadcaster.process_delayed_alerts()

            mock_process_task.assert_not_called()