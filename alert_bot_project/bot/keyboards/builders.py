from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup
from alert_bot_project.core_shared.constants import ODESA_LOCS, OUTSIDE_LOCS, KR_POTVORY, DISLOCS_PER_PAGE
from alert_bot_project.core_shared.callbacks import (
    GroupNavCallback, LocationToggleCallback, ThreatCategoryCallback,
    MutePresetCallback, CustomActionCallback
)

# Централизованные константы путей навигации (избавляемся от магических строк)
MENU_MAIN = "menu:main"
MENU_CHOOSE_GROUP = "menu:choose_group"
MENU_CUSTOM_MANAGE = "menu:custom_manage"
MENU_POTVORY = "menu:potvory"
MENU_MUTE = "menu:mute"
MENU_INFO = "menu:info"
CUSTOM_ADD = "custom:add"
ALERT_ACK = "alert:ack"

# ✅ ФИКС С СОНАРОМ (python:S1192): Избавляемся от дублирования строковых литералов
BACK_BUTTON_TEXT = "⬅️ Назад"


def build_back_to_main_keyboard() -> InlineKeyboardMarkup:
    """Генерує уніфіковану кнопку повернення до головного меню."""
    kb = InlineKeyboardBuilder()
    kb.button(text=BACK_BUTTON_TEXT, callback_data=MENU_MAIN)
    return kb.as_markup()


def build_main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🌍 Обрати дислокацію", callback_data=MENU_CHOOSE_GROUP)
    kb.button(text="✍️ Мої кастомні фрази", callback_data=MENU_CUSTOM_MANAGE)
    kb.button(text="🦅 Крилаті потвори", callback_data=MENU_POTVORY)
    kb.button(text="🔕 Режим тиші (MUTE)", callback_data=MENU_MUTE)
    kb.button(text="ℹ️ Інформація", callback_data=MENU_INFO)
    kb.adjust(1)
    return kb.as_markup()


def build_group_selection_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🏙️ Одеса (Райони)", callback_data=GroupNavCallback(group="odesa", page=0).pack())
    kb.button(text="🏞️ Передмістя / Область", callback_data=GroupNavCallback(group="outside", page=0).pack())
    kb.button(text=BACK_BUTTON_TEXT, callback_data=MENU_MAIN)
    kb.adjust(1)
    return kb.as_markup()


def build_locations_paginated_keyboard(group: str, active_user_triggers: set[str], page: int = 0) -> InlineKeyboardMarkup:
    source_map = ODESA_LOCS if group == "odesa" else OUTSIDE_LOCS
    items = list(source_map.items())
    total_items = len(items)

    max_page = max(0, (total_items - 1) // DISLOCS_PER_PAGE)
    if page < 0:
        page = 0
    elif page > max_page:
        page = max_page

    start_index = page * DISLOCS_PER_PAGE
    end_index = min(start_index + DISLOCS_PER_PAGE, total_items)

    kb = InlineKeyboardBuilder()

    for inv_key, meta in items[start_index:end_index]:
        is_active = inv_key in active_user_triggers
        status_marker = "✅" if is_active else "❌"
        button_label = f"{status_marker} {meta['emoji']} {meta['display']}"
        kb.button(text=button_label, callback_data=LocationToggleCallback(group=group, location_key=inv_key, page=page).pack())

    if page > 0:
        kb.button(text="⬅️ Попередні", callback_data=GroupNavCallback(group=group, page=page - 1).pack())
    if end_index < total_items:
        kb.button(text="Наступні ➡️", callback_data=GroupNavCallback(group=group, page=page + 1).pack())

    kb.button(text="➕ Додати власну локацію", callback_data=CUSTOM_ADD)
    kb.button(text="⬅️ Назад до груп", callback_data=MENU_CHOOSE_GROUP)
    kb.adjust(2)
    return kb.as_markup()


def build_custom_triggers_management_keyboard(custom_phrases: set[str]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for phrase in custom_phrases:
        kb.button(text=f"❌ {phrase}", callback_data=CustomActionCallback(action="delete", phrase=phrase).pack())
    kb.button(text="➕ Додати нову фразу", callback_data=CUSTOM_ADD)
    kb.button(text="⬅️ Головне меню", callback_data=MENU_MAIN)
    kb.adjust(1)
    return kb.as_markup()


def build_threat_categories_keyboard(active_categories: list[str]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for cat_name in KR_POTVORY.keys():
        is_enabled = cat_name in active_categories
        status_marker = "✅" if is_enabled else "❌"
        kb.button(text=f"{status_marker} {cat_name}", callback_data=ThreatCategoryCallback(category=cat_name).pack())
    kb.button(text=BACK_BUTTON_TEXT, callback_data=MENU_MAIN)
    kb.adjust(1)
    return kb.as_markup()


def build_mute_options_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔕 1 година", callback_data=MutePresetCallback(preset="1").pack())
    kb.button(text="🔕 2 години", callback_data=MutePresetCallback(preset="2").pack())
    kb.button(text="🔕 4 години", callback_data=MutePresetCallback(preset="4").pack())
    kb.button(text="😴 До ранку (07:00)", callback_data=MutePresetCallback(preset="morning").pack())
    kb.button(text="🔔 Увімкнути звук", callback_data=MutePresetCallback(preset="clear").pack())
    kb.button(text=BACK_BUTTON_TEXT, callback_data=MENU_MAIN)
    kb.adjust(2)
    return kb.as_markup()


def build_acknowledge_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Сповіщення прийнято", callback_data=ALERT_ACK)
    return kb.as_markup()