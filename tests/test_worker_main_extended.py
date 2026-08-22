# noinspection PyPackageRequirements,PyUnresolvedReferences,SpellCheckingInspection
from datetime import UTC, datetime, time, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from alert_bot_project.core_shared.metrics import WORKER_ERRORS
from alert_bot_project.core_shared.schemas import AlertMessage
from alert_bot_project.worker.main import (
    _resolve_target_users,
    check_official_air_alarm,
    is_night_siren_interval_active,
    process_single_stream_payload,
)


class TestWorkerMainInfrastructure:
    def test_is_night_siren_interval_active_logic(self) -> None:
        """Проверяем интервалы ночного будильника с реальными объектами времени."""
        with (
            patch("alert_bot_project.worker.main.NIGHT_START", time(22, 0, 0)),
            patch("alert_bot_project.worker.main.NIGHT_END", time(7, 0, 0)),
            patch("alert_bot_project.worker.main.datetime") as mock_dt,
        ):
            # Проверка 23:00 (Ночь - Активно)
            mock_dt.now.return_value.time.return_value = time(23, 0, 0)
            assert is_night_siren_interval_active() is True

            # Проверка 13:00 (День - Тихо)
            mock_dt.now.return_value.time.return_value = time(13, 0, 0)
            assert is_night_siren_interval_active() is False

    @pytest.mark.asyncio
    async def test_check_official_air_alarm_cache_hit(self) -> None:
        """Если статус тревоги уже закэширован в Redis, не дергаем конфигурацию."""
        mock_redis = AsyncMock()
        mock_redis.get.return_value = "1"

        status = await check_official_air_alarm(mock_redis)
        assert status is True
        mock_redis.get.assert_called_once_with("official_alarm_status:odesa")
        mock_redis.setex.assert_not_called()

    @pytest.mark.asyncio
    async def test_resolve_target_users_dlq_push_on_database_crash(self) -> None:
        """Если Supabase/Postgres лежит намертво, воркер после 5 попыток обязан сбросить задачу в DLQ."""
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        mock_redis.set.return_value = True
        mock_redis.incr.return_value = 6  # Имитируем превышение лимита ретраев (6 > 5)

        raw_payload = AlertMessage(message_id=1, chat_id=-100, raw_text="Тест уязвимости бд").model_dump_json()
        mock_release_script = AsyncMock()

        # AsyncSessionLocal должен падать реалистичным SQLAlchemyError — именно этот тип
        # ловит _build_and_cache_targets() для маршрутизации сбоя в DLQ.
        with patch(
            "alert_bot_project.worker.main.AsyncSessionLocal", side_effect=SQLAlchemyError("Supabase connection dead")
        ):
            with pytest.raises(SQLAlchemyError):
                await _resolve_target_users(
                    redis_client=mock_redis,
                    checksum="abc_hash",
                    categories={"Ракети"},
                    trigger_words={"center"},
                    redis_msg_id="111-0",
                    raw_json=raw_payload,
                    release_lock_script=mock_release_script,
                )

            # Проверяем, что бракованная задача реально ушла в DLQ, а из основного стрима сделан XACK
            mock_redis.xadd.assert_called_once_with(
                "dead_letter_queue", {"payload": raw_payload, "error": "Supabase connection dead"}, maxlen=10000
            )
            mock_redis.xack.assert_called_once_with("alerts_stream", "workers_group", "111-0")

    @pytest.mark.asyncio
    async def test_process_single_stream_payload_skips_outdated_messages(self) -> None:
        """Если сообщение протухло в очереди и ему больше 10 минут, просто подтверждаем (XACK) и выкидываем."""
        mock_redis = AsyncMock()
        mock_broadcaster = MagicMock()

        # Создаем древний пайлоад
        ancient_payload = AlertMessage(message_id=12, chat_id=-10, raw_text="Древняя тревога")
        ancient_payload.timestamp = datetime.now(UTC) - timedelta(minutes=10, seconds=1)

        await process_single_stream_payload(
            redis_msg_id="999-0",
            raw_json=ancient_payload.model_dump_json(),
            redis_client=mock_redis,
            broadcaster=mock_broadcaster,
            release_lock_script=AsyncMock(),
        )

        mock_redis.xack.assert_called_once_with("alerts_stream", "workers_group", "999-0")
        mock_redis.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_single_stream_payload_increments_worker_errors_on_db_failure(self) -> None:
        """Провал БД під час резолву отримувачів мусить бути видимим у worker_errors_total,
        інакше алертинг на цю деградацію просто не спрацює."""
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None  # немає кеша/офіційної тривоги -> failsafe=True за замовчуванням
        mock_redis.set.return_value = True  # дедуп-лок і лок білда кешу обидва "успішно" зайняті
        mock_redis.smembers.return_value = set()
        mock_redis.incr.return_value = 1  # перша спроба, ще не досягли ліміту ретраїв -> DLQ не чіпаємо
        mock_broadcaster = MagicMock()

        payload = AlertMessage(message_id=42, chat_id=-100, raw_text="Ракети на місто!").model_dump_json()

        before = WORKER_ERRORS._value.get()

        with patch(
            "alert_bot_project.worker.main.AsyncSessionLocal", side_effect=SQLAlchemyError("Supabase connection dead")
        ):
            await process_single_stream_payload(
                redis_msg_id="42-0",
                raw_json=payload,
                redis_client=mock_redis,
                broadcaster=mock_broadcaster,
                release_lock_script=AsyncMock(),
            )

        after = WORKER_ERRORS._value.get()
        assert after == before + 1
        mock_broadcaster.fire_and_forget_message.assert_not_called()
