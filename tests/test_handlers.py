# noinspection PyPackageRequirements,PyUnresolvedReferences,SpellCheckingInspection
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.fsm.context import FSMContext
from sqlalchemy.exc import SQLAlchemyError
from hypothesis import given, settings, strategies as st, HealthCheck

from alert_bot_project.bot.handlers.start import process_start_command, process_return_to_main_menu
from alert_bot_project.bot.handlers.settings import show_group_selection, store_custom_user_keyword
from alert_bot_project.database.models import UserSettings


@pytest.fixture
def mock_db_session() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_fsm_state() -> AsyncMock:
    return AsyncMock(spec=FSMContext)


class TestStartHandlers:

    @pytest.mark.asyncio
    @patch("alert_bot_project.bot.handlers.start.get_or_create_user")
    async def test_process_start_command_success(self, mock_get_user: MagicMock, mock_db_session: AsyncMock) -> None:
        mock_user_tg = MagicMock()
        mock_user_tg.id = 77777
        mock_message = AsyncMock(from_user=mock_user_tg)

        mock_get_user.return_value = UserSettings(user_id=77777)

        await process_start_command(mock_message, db_session=mock_db_session)

        mock_get_user.assert_called_once_with(mock_db_session, 77777)
        mock_message.answer.assert_called_once()

    @pytest.mark.asyncio
    @patch("alert_bot_project.bot.handlers.start.get_or_create_user")
    async def test_process_start_command_database_crash(self, mock_get_user: MagicMock,
                                                        mock_db_session: AsyncMock) -> None:
        mock_user_tg = MagicMock(id=999)
        mock_message = AsyncMock(from_user=mock_user_tg)
        mock_get_user.side_effect = SQLAlchemyError("Supabase connection timeout")

        await process_start_command(mock_message, db_session=mock_db_session)

        mock_message.answer.assert_called_once()
        assert "Виникла помилка" in mock_message.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_process_return_to_main_menu(self) -> None:
        mock_message = AsyncMock()
        mock_callback = AsyncMock(message=mock_message)

        await process_return_to_main_menu(mock_callback)

        mock_message.edit_text.assert_called_once()
        mock_callback.answer.assert_called_once()


class TestSettingsHandlers:

    @pytest.mark.asyncio
    async def test_show_group_selection(self) -> None:
        mock_message = AsyncMock()
        mock_callback = AsyncMock(message=mock_message)

        await show_group_selection(mock_callback)

        mock_message.edit_text.assert_called_once()
        mock_callback.answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_custom_user_keyword_invalid_length(self, mock_db_session: AsyncMock,
                                                            mock_fsm_state: AsyncMock) -> None:
        mock_message = AsyncMock(text="бп")

        await store_custom_user_keyword(mock_message, state=mock_fsm_state, db_session=mock_db_session)

        mock_message.reply.assert_called_once()
        assert "від 3 до 30 символів" in mock_message.reply.call_args[0][0]
        mock_fsm_state.clear.assert_not_called()

    @pytest.mark.asyncio
    async def test_store_custom_user_keyword_prebuilt_warning(self, mock_db_session: AsyncMock,
                                                              mock_fsm_state: AsyncMock) -> None:
        mock_message = AsyncMock(text="Черемушки")

        await store_custom_user_keyword(mock_message, state=mock_fsm_state, db_session=mock_db_session)

        mock_message.reply.assert_called_once()
        assert "вже є у вбудованому списку" in mock_message.reply.call_args[0][0]
        mock_fsm_state.clear.assert_called_once()

    @pytest.mark.asyncio
    @patch("alert_bot_project.bot.handlers.settings.UserService")
    @patch("alert_bot_project.bot.handlers.settings.get_or_create_user")
    async def test_store_custom_user_keyword_success(self, mock_get_user: MagicMock, mock_user_service_cls: MagicMock,
                                                     mock_db_session: AsyncMock, mock_fsm_state: AsyncMock) -> None:
        mock_user_tg = MagicMock()
        mock_user_tg.id = 555
        mock_message = AsyncMock(from_user=mock_user_tg, text="Люстдорф")

        mock_service_instance = AsyncMock()
        mock_service_instance.add_custom_trigger.return_value = (True, "Локацію додано")
        mock_user_service_cls.return_value = mock_service_instance

        await store_custom_user_keyword(mock_message, state=mock_fsm_state, db_session=mock_db_session)

        mock_service_instance.add_custom_trigger.assert_called_once_with(555, "люстдорф")
        mock_message.answer.assert_called_once()
        mock_fsm_state.clear.assert_called_once()


class TestSettingsHandlersFuzzing:

    @pytest.mark.asyncio
    # ✅ ФИКС: Подавляем хелсчек на использование function-scoped фикстур базы внутри Hypothesis
    @settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(user_text=st.text(min_size=1, max_size=100))
    async def test_store_custom_user_keyword_resilience_matrix(self, user_text: str, mock_db_session: AsyncMock,
                                                               mock_fsm_state: AsyncMock) -> None:
        mock_user_tg = MagicMock(id=555)
        mock_message = AsyncMock(from_user=mock_user_tg, text=user_text)

        with patch("alert_bot_project.bot.handlers.settings.UserService") as mock_user_service_cls:
            mock_service_instance = AsyncMock()
            mock_service_instance.add_custom_trigger.return_value = (True, "Локацію додано")
            mock_user_service_cls.return_value = mock_service_instance

            await store_custom_user_keyword(mock_message, state=mock_fsm_state, db_session=mock_db_session)

            assert mock_message.reply.call_count + mock_message.answer.call_count == 1