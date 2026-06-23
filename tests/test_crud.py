# noinspection PyPackageRequirements,PyUnresolvedReferences,SpellCheckingInspection
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from hypothesis import given, settings, strategies as st
from datetime import datetime, timezone

from alert_bot_project.database.crud import (
    get_or_create_user, add_user_trigger, remove_user_trigger,
    update_user_potvory, update_user_mute, get_users_by_trigger_and_category
)
from alert_bot_project.database.models import UserSettings


@pytest.fixture
def mock_session() -> AsyncMock:
    return AsyncMock()


# ============================================================================
# 1. СТАНДАРТНЫЙ PYTEST (Тестирование логики и путей ветвления)
# ============================================================================

class TestCrudUserWorkflow:

    @pytest.mark.asyncio
    async def test_get_or_create_user_returns_existing(self, mock_session: AsyncMock) -> None:
        """Если юзер уже есть в базе, метод просто возвращает его без инсертов"""
        mock_user = UserSettings(user_id=111, potvory=["Ракети"])

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_session.execute.return_value = mock_result

        user = await get_or_create_user(mock_session, 111)

        assert user.user_id == 111
        assert user.potvory == ["Ракети"]
        assert mock_session.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_get_or_create_user_creates_new(self, mock_session: AsyncMock) -> None:
        """Если юзера нет, проверяем семантику контракта — создание и возврат дефолтных настроек"""
        mock_user = UserSettings(user_id=222, potvory=["Мопеди", "Ракети"])

        mock_result_none = MagicMock()
        mock_result_none.scalar_one_or_none.return_value = None

        mock_result_user = MagicMock()
        mock_result_user.scalar_one.return_value = mock_user

        mock_session.execute.side_effect = [mock_result_none, MagicMock(), mock_result_user]

        user = await get_or_create_user(mock_session, 222)

        assert user.user_id == 222
        assert user.potvory == ["Мопеди", "Ракети"]
        mock_session.flush.assert_awaited_once()
        assert mock_session.execute.call_count >= 2

    @pytest.mark.asyncio
    async def test_remove_user_trigger_execution(self, mock_session: AsyncMock) -> None:
        """Проверка изолированного удаления триггера пользователя через delete-выражение"""
        await remove_user_trigger(mock_session, user_id=123, trigger_word="center")
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_user_mute_execution(self, mock_session: AsyncMock) -> None:
        """Проверка мутации времени глушения пользователя"""
        mock_user = UserSettings(user_id=123, potvory=["Ракети"])
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = mock_user
        mock_session.execute.return_value = mock_res

        until_time = datetime.now(timezone.utc)
        await update_user_mute(mock_session, user_id=123, muted_until=until_time)
        assert mock_user.muted_until == until_time

    @pytest.mark.asyncio
    async def test_get_users_by_trigger_empty_categories_returns_empty_immediately(self,
                                                                                   mock_session: AsyncMock) -> None:
        """Если сет категорий пустой, метод обязан вернуть пустой список сразу, не дергая БД"""
        result = await get_users_by_trigger_and_category(mock_session, category_names=set(), trigger_words={"city"})

        assert result == []
        mock_session.execute.assert_not_called()


# ============================================================================
# 2. ИНТЕГРАЦИЯ С HYPOTHESIS (Fuzzing параметров и проверка генерации запросов)
# ============================================================================

class TestCrudPropertyBased:

    @pytest.mark.asyncio
    @settings(max_examples=30)
    @given(user_id=st.integers(min_value=-9223372036854775808, max_value=9223372036854775807))
    async def test_get_or_create_user_id_boundaries(self, user_id: int) -> None:
        """Проверяем, что генератор SQL-запросов хавает любые границы BigInteger без крашей приложения"""
        mock_session = AsyncMock()
        mock_user = UserSettings(user_id=user_id)

        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = mock_user
        mock_session.execute.return_value = mock_res

        user = await get_or_create_user(mock_session, user_id)
        assert user.user_id == user_id

    @pytest.mark.asyncio
    @settings(max_examples=30)
    @given(
        user_id=st.integers(min_value=1, max_value=999999999),
        trigger_word=st.text(min_size=1, max_size=50)
    )
    async def test_add_user_trigger_contracts(self, user_id: int, trigger_word: str) -> None:
        """Проверяем корректность булевого контракта при добавлении триггеров разной длины и кодировок"""
        mock_session = AsyncMock()

        mock_res_success = MagicMock()
        mock_res_success.rowcount = 1
        mock_session.execute.return_value = mock_res_success

        res_true = await add_user_trigger(mock_session, user_id, trigger_word)
        assert res_true is True

        mock_res_fail = MagicMock()
        mock_res_fail.rowcount = 0
        mock_session.execute.return_value = mock_res_fail

        res_false = await add_user_trigger(mock_session, user_id, trigger_word)
        assert res_false is False

    @pytest.mark.asyncio
    @settings(max_examples=30)
    @given(
        user_id=st.integers(min_value=1, max_value=999999999),
        potvory_list=st.lists(st.sampled_from(["Мопеди", "Ракети"]), min_size=0, max_size=2, unique=True)
    )
    async def test_update_user_potvory_mutation(self, user_id: int, potvory_list: list[str]) -> None:
        """Проверяем, что обновление списка потвор мутирует объект модели без падений"""
        mock_session = AsyncMock()
        mock_user = UserSettings(user_id=user_id, potvory=["Мопеди", "Ракети"])

        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = mock_user
        mock_session.execute.return_value = mock_res

        with patch("alert_bot_project.database.crud.get_or_create_user", return_value=mock_user):
            await update_user_potvory(mock_session, user_id, potvory_list)
            assert mock_user.potvory == potvory_list

    @pytest.mark.asyncio
    @settings(max_examples=30)
    @given(
        categories=st.sets(st.sampled_from(["Мопеди", "Ракети"]), min_size=1),
        triggers=st.sets(st.text(min_size=3, max_size=15), min_size=0, max_size=5)
    )
    async def test_get_users_by_trigger_query_building(self, categories: set[str], triggers: set[str]) -> None:
        """Гарантируем, что сложный блок условий (overlap + exists) собирается без синтаксических ошибок SQLAlchemy"""
        mock_session = AsyncMock()

        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_res

        result = await get_users_by_trigger_and_category(mock_session, categories, triggers)
        assert result == []
        assert mock_session.execute.call_count == 1