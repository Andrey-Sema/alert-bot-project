# noinspection PyPackageRequirements,PyUnresolvedReferences,SpellCheckingInspection
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from alert_bot_project.services.user_service import UserService
from alert_bot_project.core_shared.constants import MAX_CUSTOM_TRIGGERS


@pytest.fixture
def mock_redis() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_session() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def user_service(mock_session: AsyncMock, mock_redis: AsyncMock) -> UserService:
    return UserService(mock_session, mock_redis)


# ============================================================================
# ТЕСТЫ: toggle_location
# ============================================================================
class TestToggleLocation:

    @pytest.mark.asyncio
    async def test_toggle_adds_location(self, user_service: UserService) -> None:
        """Добавление статической локации возвращает обновленный хэш-сет триггеров"""
        mock_user = MagicMock()
        mock_user.triggers_set = {"peresyp"}

        with patch("alert_bot_project.services.user_service.get_or_create_user", return_value=mock_user), \
                patch("alert_bot_project.services.user_service.add_user_trigger") as mock_add:
            mock_add: MagicMock

            result = await user_service.toggle_location(12345, "peresyp")

            assert isinstance(result, set)
            assert "peresyp" in result
            mock_add.assert_called_once_with(user_service.session, 12345, "peresyp")

    @pytest.mark.asyncio
    async def test_toggle_removes_location(self, user_service: UserService) -> None:
        """Удаление статической локации если она уже была в хэш-сете"""
        mock_user = MagicMock()
        mock_user.triggers_set = set()

        with patch("alert_bot_project.services.user_service.get_or_create_user", return_value=mock_user), \
                patch("alert_bot_project.services.user_service.remove_user_trigger") as mock_remove:
            mock_remove: MagicMock

            result = await user_service.toggle_location(12345, "peresyp")

            assert "peresyp" not in result
            mock_remove.assert_called_once_with(user_service.session, 12345, "peresyp")


# ============================================================================
# ТЕСТЫ: add_custom_trigger
# ============================================================================
class TestAddCustomTrigger:

    @pytest.mark.asyncio
    async def test_success_adds_to_redis(self, user_service: UserService) -> None:
        """Успешное добавление: триггер попадает в кэш памяти Redis"""
        mock_user = MagicMock()
        mock_user.triggers_set = {"existing_custom"}

        with patch("alert_bot_project.services.user_service.get_or_create_user", return_value=mock_user), \
                patch("alert_bot_project.services.user_service.add_user_trigger",
                      return_value=True) as mock_add_trigger:
            mock_add_trigger: MagicMock

            success, msg = await user_service.add_custom_trigger(12345, "new_phrase")

            assert success is True
            assert "додано" in msg or "Локацію" in msg
            user_service.redis.sadd.assert_called_once_with("global_custom_triggers", "new_phrase")

    @pytest.mark.asyncio
    async def test_limit_reached_blocks_addition(self, user_service: UserService) -> None:
        """Жесткий лимит кастомных триггеров блокирует добавление"""
        mock_user = MagicMock()
        mock_user.triggers_set = {f"custom_{i}" for i in range(MAX_CUSTOM_TRIGGERS)}

        with patch("alert_bot_project.services.user_service.get_or_create_user", return_value=mock_user):
            success, msg = await user_service.add_custom_trigger(12345, "new_phrase")

            assert success is False
            assert "ліміту" in msg
            user_service.redis.sadd.assert_not_called()


# ============================================================================
# ТЕСТЫ: delete_custom_trigger
# ============================================================================
class TestDeleteCustomTrigger:

    @pytest.mark.asyncio
    async def test_delete_removes_from_redis_when_last_user(self, user_service: UserService) -> None:
        """Если фразу больше никто не отслеживает в БД — стираем ее из Redis глобально"""
        mock_user = MagicMock()
        mock_user.triggers_set = set()

        with patch("alert_bot_project.services.user_service.get_or_create_user", return_value=mock_user), \
                patch("alert_bot_project.services.user_service.remove_user_trigger"):
            mock_result = MagicMock()
            mock_result.scalar.return_value = False
            user_service.session.execute.return_value = mock_result

            success, msg = await user_service.delete_custom_trigger(12345, "my_phrase")

            assert success is True
            user_service.redis.srem.assert_called_once_with("global_custom_triggers", "my_phrase")


# ============================================================================
# ТЕСТЫ: apply_mute_preset
# ============================================================================
class TestApplyMutePreset:

    @pytest.mark.asyncio
    async def test_clear_mute_preset(self, user_service: UserService) -> None:
        """Пресет 'clear' сбрасывает заглушение в БД и чистит ключ Redis"""
        with patch("alert_bot_project.services.user_service.update_user_mute") as mock_update:
            mock_update: MagicMock

            msg = await user_service.apply_mute_preset(12345, "clear")

            assert "увімкнено" in msg
            mock_update.assert_called_once_with(user_service.session, 12345, None)
            user_service.redis.delete.assert_called_once_with("user_mute:12345")

    @pytest.mark.asyncio
    async def test_hours_mute_preset(self, user_service: UserService) -> None:
        """Пресет на определенное количество часов ставит TTL в Redis"""
        with patch("alert_bot_project.services.user_service.update_user_mute") as mock_update:
            mock_update: MagicMock

            msg = await user_service.apply_mute_preset(12345, "2")

            assert "вимкнено" in msg
            assert "2 год." in msg
            mock_update.assert_called_once()
            user_service.redis.set.assert_called_once()


# ============================================================================
# ТЕСТЫ: acknowledge_alert
# ============================================================================
class TestAcknowledgeAlert:

    @pytest.mark.asyncio
    async def test_acknowledge_mutes_for_10_minutes(self, user_service: UserService) -> None:
        """Подтверждение алерта глушит систему на 10 минут (600 секунд)"""
        with patch("alert_bot_project.services.user_service.update_user_mute") as mock_update:
            mock_update: MagicMock

            msg = await user_service.acknowledge_alert(12345)

            assert "прийнято" in msg
            mock_update.assert_called_once()
            user_service.redis.set.assert_called_once_with("user_mute:12345", "1", ex=600)