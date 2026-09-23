# noinspection PyPackageRequirements,PyUnresolvedReferences,SpellCheckingInspection
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from redis.exceptions import RedisError

from alert_bot_project.core_shared.schemas import AlertMessage
from alert_bot_project.core_shared.text_processor import TextProcessor
from alert_bot_project.worker.main import _dispatch_alerts, process_single_stream_payload


@pytest.mark.asyncio
@pytest.mark.integration
class TestE2EAlertPipeline:
    async def test_full_pipeline_from_text_to_worker_routing(self) -> None:
        """
        Сквозной интеграционный тест конвейера:
        Перехват текста -> Схема Pydantic -> Выборка базы -> Логика Воркера -> Рассылка Бродкастера
        """
        mock_release_lock_script = AsyncMock(return_value=1)

        # 1. Имитируем боевой пост админов с новыми коварными суффиксами и сленгом
        raw_post = "🚨 ТУРБОДИЗЕЛЬНІ шлюхи заходять з моря на Пересип! Ракети Цыркон на центр!"

        # Проверяем, что регулярки ядра \w{0,3} чисто выгребают падежи и основы
        analysis = TextProcessor.parse_message(raw_post)
        assert "Мопеди" in analysis["categories"]
        assert "Ракети" in analysis["categories"]
        assert "peresyp" in analysis["locations"]
        assert "center" in analysis["locations"]

        # 2. Упаковываем данные в строгий контракт serialization
        payload = AlertMessage(message_id=999, chat_id=-100123456, raw_text=raw_post)
        json_data = payload.model_dump_json()

        # 3. Мокаем транспортную инфраструктуру
        mock_redis = AsyncMock()
        mock_broadcaster = MagicMock()
        mock_broadcaster.enqueue_alert = AsyncMock(return_value=True)

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

        with (
            patch("alert_bot_project.worker.main.get_users_by_trigger_and_category", return_value=[mock_user]),
            patch("alert_bot_project.worker.main.is_night_siren_interval_active", return_value=True),
        ):
            # 4. Прогоняем весь этот сквозной пайлоад через процессор воркера
            await process_single_stream_payload(
                redis_msg_id="1690000000-0",
                raw_json=json_data,
                redis_client=mock_redis,
                broadcaster=mock_broadcaster,
                release_lock_script=mock_release_lock_script,
            )

            # 5. Проверяем выполнение бизнес-контрактов системы
            mock_redis.xack.assert_called_once_with("alerts_stream", "workers_group", "1690000000-0")

            mock_broadcaster.enqueue_alert.assert_awaited_once_with(-100123456, 999, 4444, stale=False)


@pytest.mark.asyncio
@settings(max_examples=40, deadline=None)
@given(
    recipients=st.lists(st.integers(min_value=1, max_value=100000), min_size=2, max_size=20, unique=True),
    failed_index=st.integers(min_value=0, max_value=19),
)
async def test_partial_fanout_stops_without_forgetting_prior_recipients(
    recipients: list[int], failed_index: int
) -> None:
    failed_index %= len(recipients)
    broadcaster = MagicMock()
    seen: list[int] = []

    async def enqueue(_chat: int, _message: int, recipient: int, *, stale: bool = False) -> bool:
        seen.append(recipient)
        if len(seen) == failed_index + 1:
            raise RedisError("temporary outage")
        return True

    broadcaster.enqueue_alert = AsyncMock(side_effect=enqueue)
    alert = AlertMessage(message_id=8, chat_id=-100, raw_text="Ракети на центр")
    with pytest.raises(RedisError):
        await _dispatch_alerts(broadcaster, alert, recipients)
    assert seen == recipients[: failed_index + 1]


@pytest.mark.asyncio
async def test_source_is_not_acknowledged_when_durable_fanout_fails() -> None:
    redis_client = AsyncMock()
    redis_client.smembers.return_value = set()
    redis_client.mget.return_value = [None]
    payload = AlertMessage(message_id=8, chat_id=-100, raw_text="Ракети на центр").model_dump_json()
    with (
        patch("alert_bot_project.worker.main.check_official_air_alarm", return_value=True),
        patch("alert_bot_project.worker.main._resolve_target_users", return_value=[123]),
        patch("alert_bot_project.worker.main.is_night_siren_interval_active", return_value=True),
        patch("alert_bot_project.worker.main._dispatch_alerts", side_effect=RedisError("outage")),
        pytest.raises(RedisError),
    ):
        await process_single_stream_payload("1-0", payload, redis_client, MagicMock(), AsyncMock())
    redis_client.xack.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_pending_source_completes_fanout_with_historical_notice() -> None:
    redis_client = AsyncMock()
    redis_client.smembers.return_value = set()
    redis_client.mget.return_value = [None, None]
    broadcaster = MagicMock()
    broadcaster.enqueue_alert = AsyncMock(return_value=True)
    payload = AlertMessage(
        message_id=8,
        chat_id=-100,
        raw_text="Ракети на центр",
        timestamp=datetime.now(UTC) - timedelta(minutes=11),
    ).model_dump_json()
    with (
        patch("alert_bot_project.worker.main.check_official_air_alarm", return_value=True),
        patch("alert_bot_project.worker.main._resolve_target_users", return_value=[123, 456]),
        patch("alert_bot_project.worker.main.is_night_siren_interval_active", return_value=False),
    ):
        await process_single_stream_payload("1-0", payload, redis_client, broadcaster, AsyncMock())
    assert broadcaster.enqueue_alert.await_count == 2
    broadcaster.enqueue_alert.assert_any_await(-100, 8, 123, stale=True)
    broadcaster.enqueue_alert.assert_any_await(-100, 8, 456, stale=True)
    redis_client.xack.assert_awaited_once()
