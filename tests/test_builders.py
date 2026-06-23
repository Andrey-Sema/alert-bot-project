# noinspection PyPackageRequirements,PyUnresolvedReferences,SpellCheckingInspection
import pytest
from aiogram.types import InlineKeyboardMarkup
from alert_bot_project.bot.keyboards.builders import (
    build_main_menu, build_group_selection_menu, build_locations_paginated_keyboard,
    build_threat_categories_keyboard, build_mute_options_keyboard, build_acknowledge_keyboard
)
from alert_bot_project.core_shared.constants import ODESA_LOCS


class TestKeyboardBuilders:

    def test_build_main_menu(self):
        kb = build_main_menu()
        assert isinstance(kb, InlineKeyboardMarkup)
        assert len(kb.inline_keyboard) == 5
        assert kb.inline_keyboard[0][0].callback_data == "menu:choose_group"

    def test_build_group_selection_menu(self):
        kb = build_group_selection_menu()
        assert len(kb.inline_keyboard) == 3
        assert "nav_group:odesa:0" in kb.inline_keyboard[0][0].callback_data

    @pytest.mark.parametrize("page, expected_page_in_buttons", [
        (0, 0),
        (-5, 0),
        (999, 3)
    ])
    def test_build_locations_paginated_keyboard_bounds(self, page, expected_page_in_buttons):
        kb = build_locations_paginated_keyboard(group="odesa", active_user_triggers=set(), page=page)
        first_loc_button = kb.inline_keyboard[0][0]
        assert first_loc_button.callback_data.endswith(f":{expected_page_in_buttons}")

    def test_build_locations_paginated_keyboard_markers(self):
        active_key = list(ODESA_LOCS.keys())[0]
        kb = build_locations_paginated_keyboard(group="odesa", active_user_triggers={active_key}, page=0)

        button_text = kb.inline_keyboard[0][0].text
        assert "✅" in button_text

        second_button_text = kb.inline_keyboard[1][0].text
        assert "❌" in second_button_text

    def test_build_threat_categories_keyboard(self):
        active_cats = ["Мопеди"]
        kb = build_threat_categories_keyboard(active_cats)

        moped_button = next(btn for row in kb.inline_keyboard for btn in row if "Мопеди" in btn.callback_data)
        assert "✅" in moped_button.text

    def test_build_mute_options_keyboard(self):
        kb = build_mute_options_keyboard()
        assert len(kb.inline_keyboard) > 0
        # ✅ ФИКС: Из-за kb.adjust(2) кнопка "morning" находится в ряду 1, позиция 1
        assert "mute_set:morning" in kb.inline_keyboard[1][1].callback_data

    def test_build_acknowledge_keyboard(self):
        kb = build_acknowledge_keyboard()
        assert kb.inline_keyboard[0][0].callback_data == "alert:ack"