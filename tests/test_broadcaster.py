# noinspection PyPackageRequirements,PyUnresolvedReferences,SpellCheckingInspection
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.exceptions import TelegramRetryAfter, TelegramAPIError
from alert_bot_project.worker.broadcaster import Broadcaster


@pytest.fixture
def mock_bot() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_redis() -> AsyncMock:
    return AsyncMock()


class TestBroadcasterQueueEngine:

    @pytest.mark.asyncio
    async def test_broadcaster_task_retention_and_gc_protection(self, mock_bot: AsyncMock,
                                                                mock_redis: AsyncMock) -> None:
        broadcaster = Broadcaster(bot=mock_bot, redis_client=mock_redis, workers_count=1)
        broadcaster.queue = asyncio.Queue(maxsize=1)

        broadcaster.fire_and_forget_message(chat_id=111, text="First alert lock")
        assert broadcaster.queue.qsize() == 1
        assert len(broadcaster._background_tasks) == 0

        broadcaster.fire_and_forget_message(chat_id=222, text="Second alert overflow push")
        assert len(broadcaster._background_tasks) == 1

        await broadcaster.queue.get()
        broadcaster.queue.task_done()

        await asyncio.sleep(0.001)
        assert len(broadcaster._background_tasks) == 0

    @pytest.mark.asyncio
    @patch("asyncio.sleep")
    async def test_send_single_message_handles_flood_control_retry(self, mock_sleep: MagicMock, mock_bot: AsyncMock,
                                                                   mock_redis: AsyncMock) -> None:
        """Проверка поимки TelegramRetryAfter (429): бродкастер должен виртуально засыпать и повторять попытку"""
        broadcaster = Broadcaster(bot=mock_bot, redis_client=mock_redis, workers_count=1)
        mock_sleep.return_value = None

        mock_bot.send_message.side_effect = [
            TelegramRetryAfter(retry_after=5, method=MagicMock(), message="Flood control"),
            AsyncMock()  # ✅ СЕНЬОР-ФИКС: Второй вызов делаем строго асинхронным под Python 3.13
        ]

        success = await broadcaster.send_single_message(chat_id=777, text="Тест флуд контроля")
        assert success is True
        assert mock_bot.send_message.call_count == 2

        # ✅ СЕНЬОР-ФИКС: Проверяем наличие вызова среди истории, игнорируя слип на 0.04 сек
        mock_sleep.assert_any_call(5)

    @pytest.mark.asyncio
    async def test_send_single_message_catches_api_error_smoothly(self, mock_bot: AsyncMock,
                                                                  mock_redis: AsyncMock) -> None:
        broadcaster = Broadcaster(bot=mock_bot, redis_client=mock_redis, workers_count=1)
        mock_bot.send_message.side_effect = TelegramAPIError(message="Chat not found", method=MagicMock())

        success = await broadcaster.send_single_message(chat_id=777, text="Тест краша АПИ")
        assert success is False

    @pytest.mark.asyncio
    async def test_broadcaster_lifecycle_and_graceful_shutdown(self, mock_bot: AsyncMock,
                                                               mock_redis: AsyncMock) -> None:
        broadcaster = Broadcaster(bot=mock_bot, redis_client=mock_redis, workers_count=2)

        broadcaster.start()
        try:
            assert len(broadcaster._workers) == 2
        finally:
            await broadcaster.close()
            for worker in broadcaster._workers:
                assert worker.done()