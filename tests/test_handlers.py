# noinspection PyPackageRequirements,PyUnresolvedReferences,SpellCheckingInspection
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.fsm.context import FSMContext

from alert_bot_project.bot.handlers.start import process_start_command, process_return_to_main_menu
from alert_bot_project.bot.handlers.settings import show_group_selection, store_custom_user_keyword
from alert_bot_project.database.models import UserSettings
from alert_bot_project.core_shared.callbacks import CustomTriggerStates


@pytest.fixture
def mock_db_session() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_fsm_state() -> AsyncMock:
    return AsyncMock(spec=FSMContext)


# ============================================================================
# 1. ТЕСТЫ: Командный слой и базовая навигация (start.py)
# ============================================================================
class TestStartHandlers:

    @pytest.mark.asyncio
    @patch("alert_bot_project.bot.handlers.start.get_or_create_user")
    async def test_process_start_command_success(self, mock_get_user: MagicMock, mock_db_session: AsyncMock) -> None:
        """Проверяем, что /start команда регистрирует юзера и выдает приветственное сообщение"""
        mock_user_tg = MagicMock()
        mock_user_tg.id = 77777
        mock_message = AsyncMock(from_user=mock_user_tg)

        mock_get_user.return_value = UserSettings(user_id=77777)

        await process_start_command(mock_message, db_session=mock_db_session)

        mock_get_user.assert_called_once_with(mock_db_session, 77777)
        mock_message.answer.assert_called_once()
        assert "Вітаємо у системі" in mock_message.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_process_return_to_main_menu(self) -> None:
        """Проверяем изменение текста сообщения при возврате в меню"""
        mock_message = AsyncMock()
        mock_callback = AsyncMock(message=mock_message)

        await process_return_to_main_menu(mock_callback)

        mock_message.edit_text.assert_called_once()
        assert "Головне меню" in mock_message.edit_text.call_args[1]["text"]
        mock_callback.answer.assert_called_once()


# ============================================================================
# 2. ТЕСТЫ: Слой настроек и валидации ввода (settings.py)
# ============================================================================
class TestSettingsHandlers:

    @pytest.mark.asyncio
    async def test_show_group_selection(self) -> None:
        """Проверяем вызов меню выбора региональных групп"""
        mock_message = AsyncMock()
        mock_callback = AsyncMock(message=mock_message)

        await show_group_selection(mock_callback)

        mock_message.edit_text.assert_called_once()
        assert "Оберіть регіональну групу" in mock_message.edit_text.call_args[0][0]
        mock_callback.answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_custom_user_keyword_invalid_length(self, mock_db_session: AsyncMock,
                                                            mock_fsm_state: AsyncMock) -> None:
        """Валидация: Слишком короткая строка (меньше 3 символов) должна отсекаться"""
        mock_message = AsyncMock(text="бп")  # 2 символа

        await store_custom_user_keyword(mock_message, state=mock_fsm_state, db_session=mock_db_session)

        mock_message.reply.assert_called_once()
        assert "від 3 до 30 символів" in mock_message.reply.call_args[0][0]
        # Проверяем, что стейт не очистился, давая юзеру шанс исправиться
        mock_fsm_state.clear.assert_not_called()

    @pytest.mark.asyncio
    async def test_store_custom_user_keyword_prebuilt_warning(self, mock_db_session: AsyncMock,
                                                              mock_fsm_state: AsyncMock) -> None:
        """Валидация: Если юзер вводит то, что уже есть в статической базе — выдаем предупреждение"""
        # "Черемушки" зашиты в ODESA_LOCS, алгоритм должен это поймать
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
        """Успешный сценарий: Валидный кастомный триггер уходит в UserService"""
        mock_user_tg = MagicMock()
        mock_user_tg.id = 555
        mock_message = AsyncMock(from_user=mock_user_tg, text="Люстдорф")

        mock_service_instance = AsyncMock()
        mock_service_instance.add_custom_trigger.return_value = (True, "Локацію додано")
        mock_user_service_cls.return_value = mock_service_instance

        await store_custom_user_keyword(mock_message, state=mock_fsm_state, db_session=mock_db_session)

        mock_service_instance.add_custom_trigger.assert_called_once_with(555, "люстдорф")
        mock_message.answer.assert_called_once()
        assert "успішно додано" in mock_message.answer.call_args[0][0]
        mock_fsm_state.clear.assert_called_once()