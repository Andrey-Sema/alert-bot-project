# noinspection PyPackageRequirements,PyUnresolvedReferences,SpellCheckingInspection
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import CallbackQuery

from alert_bot_project.bot.handlers.settings import (
    delete_custom_user_keyword,
    process_mute_action,
    process_repeat_action,
    show_repeat_options,
    toggle_location_trigger,
    toggle_threat_category,
)
from alert_bot_project.core_shared.callbacks import (
    CustomActionCallback,
    LocationToggleCallback,
    MutePresetCallback,
    RepeatCountCallback,
    ThreatCategoryCallback,
)
from alert_bot_project.database.models import UserSettings


@pytest.fixture
def mock_callback() -> AsyncMock:
    cb = AsyncMock(spec=CallbackQuery)
    cb.from_user = MagicMock(id=12345)
    # ✅ ФИКС: Явно переопределяем асинхронные методы aiogram, чтобы убрать TypeError 'MagicMock can't be used in await'
    cb.answer = AsyncMock()
    cb.message = AsyncMock()
    cb.message.edit_text = AsyncMock()
    cb.message.edit_reply_markup = AsyncMock()
    return cb


@pytest.fixture
def mock_db_session() -> AsyncMock:
    return AsyncMock()


class TestSettingsHandlersExtended:
    @pytest.mark.asyncio
    async def test_toggle_location_trigger_unknown_key(
        self, mock_callback: AsyncMock, mock_db_session: AsyncMock
    ) -> None:
        callback_data = LocationToggleCallback(group="odesa", location_key="invalid_sector_xyz", page=0)

        await toggle_location_trigger(mock_callback, callback_data, db_session=mock_db_session)

        mock_callback.answer.assert_called_once_with("Невідома локація", show_alert=True)
        mock_callback.message.edit_reply_markup.assert_not_called()

    @pytest.mark.asyncio
    @patch("alert_bot_project.bot.handlers.settings.get_or_create_user")
    async def test_toggle_threat_category_unknown_cat(
        self, mock_get_user: MagicMock, mock_callback: AsyncMock, mock_db_session: AsyncMock
    ) -> None:
        callback_data = ThreatCategoryCallback(category="НЛО")

        await toggle_threat_category(mock_callback, callback_data, db_session=mock_db_session)

        mock_callback.answer.assert_called_once_with("Помилка: невідома категорія", show_alert=True)

    @pytest.mark.asyncio
    @patch("alert_bot_project.bot.handlers.settings.get_or_create_user")
    async def test_toggle_threat_category_success_add_and_remove(
        self, mock_get_user: MagicMock, mock_callback: AsyncMock, mock_db_session: AsyncMock
    ) -> None:
        mock_user = UserSettings(user_id=12345, potvory=["Мопеди"])
        mock_get_user.return_value = mock_user

        callback_data_remove = ThreatCategoryCallback(category="Мопеди")
        await toggle_threat_category(mock_callback, callback_data_remove, db_session=mock_db_session)
        assert "Мопеди" not in mock_user.potvory

        callback_data_add = ThreatCategoryCallback(category="Ракети")
        await toggle_threat_category(mock_callback, callback_data_add, db_session=mock_db_session)
        assert "Ракети" in mock_user.potvory

    @pytest.mark.asyncio
    @patch("alert_bot_project.bot.handlers.settings.UserService")
    async def test_process_mute_action_handles_service_value_error(
        self, mock_service_cls: MagicMock, mock_callback: AsyncMock, mock_db_session: AsyncMock
    ) -> None:
        mock_service = AsyncMock()
        mock_service.apply_mute_preset.side_effect = ValueError("Кривой пресет")
        mock_service_cls.return_value = mock_service

        callback_data = MutePresetCallback(preset="broken_preset")
        await process_mute_action(mock_callback, callback_data, db_session=mock_db_session)

        mock_callback.answer.assert_called_once_with("Кривой пресет", show_alert=True)

    @pytest.mark.asyncio
    @patch("alert_bot_project.bot.handlers.settings.get_or_create_user")
    async def test_show_repeat_options_renders_current_selection(
        self, mock_get_user: MagicMock, mock_callback: AsyncMock, mock_db_session: AsyncMock
    ) -> None:
        mock_get_user.return_value = UserSettings(user_id=12345, repeat_count=5)

        await show_repeat_options(mock_callback, db_session=mock_db_session)

        mock_callback.message.edit_text.assert_called_once()
        _, kwargs = mock_callback.message.edit_text.call_args
        selected_button = next(
            btn for row in kwargs["reply_markup"].inline_keyboard for btn in row if "repeat_set:5" in btn.callback_data
        )
        assert "✅" in selected_button.text

    @pytest.mark.asyncio
    async def test_process_repeat_action_rejects_unknown_count(
        self, mock_callback: AsyncMock, mock_db_session: AsyncMock
    ) -> None:
        callback_data = RepeatCountCallback(count=999)
        await process_repeat_action(mock_callback, callback_data, db_session=mock_db_session)
        mock_callback.answer.assert_called_once_with("Помилка: невірна кількість повторів", show_alert=True)

    @pytest.mark.asyncio
    @patch("alert_bot_project.bot.handlers.settings.UserService")
    async def test_process_repeat_action_success(
        self, mock_service_cls: MagicMock, mock_callback: AsyncMock, mock_db_session: AsyncMock
    ) -> None:
        mock_service = AsyncMock()
        mock_service_cls.return_value = mock_service

        callback_data = RepeatCountCallback(count=10)
        await process_repeat_action(mock_callback, callback_data, db_session=mock_db_session)

        mock_service.set_repeat_count.assert_called_once_with(12345, 10)
        mock_callback.message.edit_reply_markup.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_custom_user_keyword_empty_phrase(
        self, mock_callback: AsyncMock, mock_db_session: AsyncMock
    ) -> None:
        callback_data = CustomActionCallback(action="delete", phrase="")
        await delete_custom_user_keyword(mock_callback, callback_data, db_session=mock_db_session)
        mock_callback.answer.assert_called_once_with("Помилка: фразу не знайдено", show_alert=True)

    @pytest.mark.asyncio
    @patch("alert_bot_project.bot.handlers.settings.get_or_create_user")
    @patch("alert_bot_project.bot.handlers.settings.UserService")
    async def test_delete_custom_user_keyword_success(
        self,
        mock_service_cls: MagicMock,
        mock_get_user: MagicMock,
        mock_callback: AsyncMock,
        mock_db_session: AsyncMock,
    ) -> None:
        mock_service = AsyncMock()
        mock_service_cls.return_value = mock_service

        mock_user = UserSettings(user_id=12345)
        mock_get_user.return_value = mock_user

        callback_data = CustomActionCallback(action="delete", phrase="люстдорф")
        await delete_custom_user_keyword(mock_callback, callback_data, db_session=mock_db_session)

        mock_service.delete_custom_trigger.assert_called_once_with(12345, "люстдорф")
        mock_callback.message.edit_text.assert_called_once()
        assert mock_callback.answer.call_args[1]["text"] == "Локацію видалено"
