# noinspection PyPackageRequirements,PyUnresolvedReferences,SpellCheckingInspection
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from alert_bot_project.core_shared.schemas import AlertMessage
from alert_bot_project.core_shared.text_processor import TextProcessor
from alert_bot_project.worker.main import process_single_stream_payload
from alert_bot_project.worker import main as worker_main


@pytest.mark.asyncio
class TestE2EAlertPipeline:

    async def test_full_pipeline_from_text_to_worker_routing(self) -> None:
        """
        Сквозной интеграционный тест конвейера:
        Перехват текста -> Схема Pydantic -> Выборка базы -> Логика Воркера -> Рассылка Бродкастера
        """
        worker_main.release_lock_script = AsyncMock(return_value=1)

        # 1. Имитируем боевой пост админов с новыми коварными суффиксами и сленгом
        raw_post = "🚨 ТУРБОДИЗЕЛЬНІ шлюхи заходять з моря на Пересип! Ракети Цыркон на центр!"

        # Проверяем, что регулярки ядра \w{0,3} чисто выгребают падежи и основы
        analysis = TextProcessor.parse_message(raw_post)
        assert "Мопеди" in analysis["categories"]
        assert "Ракети" in analysis["categories"]
        assert "peresyp" in analysis["locations"]
        assert "center" in analysis["locations"]

        # 2. Упаковываем данные в строгий контракт serialization
        payload = AlertMessage(
            message_id=999,
            chat_id=-100123456,
            raw_text=raw_post
        )
        json_data = payload.model_dump_json()

        # 3. Мокаем транспортную инфраструктуру
        mock_redis = AsyncMock()
        mock_broadcaster = MagicMock()

        # Настраиваем ответы кэша и дедупликатора Redis
        async def redis_set_side_effect(key, *args, **kwargs):
            if "processed_msg" in key:
                return True
            if "lock:cache_build" in key:
                return True
            return True

        mock_redis.set.side_effect = redis_set_side_effect
        mock_redis.smembers.return_value = set()
        mock_redis.get.return_value = None

        # Явно мокаем mget, возвращая [None] (пользователь не заглушен).
        mock_redis.mget.return_value = [None]

        # Мокаем выборку пользователей из Supabase (имитируем, что нашли одного юзера)
        mock_user = MagicMock()
        mock_user.user_id = 4444

        with patch("alert_bot_project.worker.main.get_users_by_trigger_and_category", return_value=[mock_user]), \
                patch("alert_bot_project.worker.main.is_night_siren_interval_active", return_value=True):

            # 4. Прогоняем весь этот сквозной пайлоад через процессор воркера
            await process_single_stream_payload(
                redis_msg_id="1690000000-0",
                raw_json=json_data,
                redis_client=mock_redis,
                broadcaster=mock_broadcaster
            )

            # 5. Проверяем выполнение бизнес-контрактов системы
            mock_redis.xack.assert_called_once_with("alerts_stream", "workers_group", "1690000000-0")

            mock_broadcaster.fire_and_forget_message.assert_called_once()
            call_args = mock_broadcaster.fire_and_forget_message.call_args
            assert call_args[0][0] == 4444
            assert call_args[1]["disable_notification"] is False

            mock_broadcaster.schedule_delayed_alerts.assert_called_once_with(4444, disable_notification=False)