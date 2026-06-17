import logging
import html
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from alert_bot_project.database.crud import get_or_create_user
from alert_bot_project.services.user_service import UserService
from alert_bot_project.bot.loader import redis_client
from alert_bot_project.core_shared.constants import ODESA_LOCS, OUTSIDE_LOCS, KR_POTVORY
from alert_bot_project.core_shared.callbacks import (
    GroupNavCallback, LocationToggleCallback, ThreatCategoryCallback,
    MutePresetCallback, CustomActionCallback, CustomTriggerStates
)
from alert_bot_project.bot.keyboards.builders import (
    build_group_selection_menu, build_locations_paginated_keyboard,
    build_threat_categories_keyboard, build_mute_options_keyboard,
    build_custom_triggers_management_keyboard,
    MENU_CHOOSE_GROUP, MENU_CUSTOM_MANAGE, MENU_POTVORY, MENU_MUTE, CUSTOM_ADD, ALERT_ACK
)
from alert_bot_project.core_shared.text_processor import TextProcessor, COMPILED_LOCATIONS

logger = logging.getLogger("bot.handlers.settings")
router = Router(name="settings_router")


@router.callback_query(F.data == MENU_CHOOSE_GROUP)
async def show_group_selection(callback: CallbackQuery):
    await callback.message.edit_text("Оберіть регіональну групу дислокацій для налаштування:",
                                     reply_markup=build_group_selection_menu())
    await callback.answer()


@router.callback_query(F.data == MENU_CUSTOM_MANAGE)
async def show_custom_phrases_menu(callback: CallbackQuery, db_session: AsyncSession):
    user = await get_or_create_user(db_session, callback.from_user.id)
    static_keys = set(ODESA_LOCS.keys()) | set(OUTSIDE_LOCS.keys())
    custom_phrases = {t for t in user.triggers_set if t not in static_keys}

    await callback.message.edit_text(
        text="✍️ <b>Ваші кастомні фрази для відстеження:</b>\n\nНатисніть на фразу, щоб видалити її з бази.",
        reply_markup=build_custom_triggers_management_keyboard(custom_phrases)
    )
    await callback.answer()


@router.callback_query(GroupNavCallback.filter())
async def show_paginated_locations(callback: CallbackQuery, callback_data: GroupNavCallback, db_session: AsyncSession):
    user = await get_or_create_user(db_session, callback.from_user.id)
    await callback.message.edit_text(
        text="Оберіть точні локації для моніторингу:",
        reply_markup=build_locations_paginated_keyboard(callback_data.group, user.triggers_set, callback_data.page)
    )
    await callback.answer()


@router.callback_query(LocationToggleCallback.filter())
async def toggle_location_trigger(callback: CallbackQuery, callback_data: LocationToggleCallback,
                                  db_session: AsyncSession):
    if callback_data.location_key not in ODESA_LOCS and callback_data.location_key not in OUTSIDE_LOCS:
        await callback.answer("Невідома локація", show_alert=True)
        return

    service = UserService(db_session, redis_client)
    updated_triggers = await service.toggle_location(callback.from_user.id, callback_data.location_key)

    await callback.message.edit_reply_markup(
        reply_markup=build_locations_paginated_keyboard(callback_data.group, updated_triggers, callback_data.page)
    )
    await callback.answer()


@router.callback_query(F.data == MENU_POTVORY)
async def show_threat_categories(callback: CallbackQuery, db_session: AsyncSession):
    user = await get_or_create_user(db_session, callback.from_user.id)
    await callback.message.edit_text(
        text="🦅 <b>Налаштування категорій повітряних загроз:</b>",
        reply_markup=build_threat_categories_keyboard(user.potvory)
    )
    await callback.answer()


@router.callback_query(ThreatCategoryCallback.filter())
async def toggle_threat_category(callback: CallbackQuery, callback_data: ThreatCategoryCallback,
                                 db_session: AsyncSession):
    if callback_data.category not in KR_POTVORY:
        await callback.answer("Помилка: невідома категорія", show_alert=True)
        return

    user = await get_or_create_user(db_session, callback.from_user.id)
    categories = list(user.potvory)

    if callback_data.category in categories:
        categories.remove(callback_data.category)
    else:
        categories.append(callback_data.category)

    user.potvory = categories

    await callback.message.edit_reply_markup(reply_markup=build_threat_categories_keyboard(categories))
    await callback.answer(text="Налаштування категорій повітряних загроз оновлено")


@router.callback_query(F.data == MENU_MUTE)
async def show_mute_options(callback: CallbackQuery):
    await callback.message.edit_text(
        text="🔕 <b>Режим тиші (MUTE):</b>",
        reply_markup=build_mute_options_keyboard()
    )
    await callback.answer()


@router.callback_query(MutePresetCallback.filter())
async def process_mute_action(callback: CallbackQuery, callback_data: MutePresetCallback, db_session: AsyncSession):
    try:
        service = UserService(db_session, redis_client)
        msg = await service.apply_mute_preset(callback.from_user.id, callback_data.preset)
        await callback.answer(text=msg)
    except ValueError as e:
        await callback.answer(str(e), show_alert=True)


@router.callback_query(F.data == CUSTOM_ADD)
async def initiate_custom_trigger_prompt(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CustomTriggerStates.waiting_for_keyword)

    # ✅ УЛУЧШЕНИЕ UX: Добавлено жесткое предупреждение по поводу Одесского региона и мануал ввода основы слова
    await callback.message.answer(
        "✍ *Введіть назву вашої кастомної локації:*\n\n"
        "⚠ *Важливо:* Моніторинг працює виключно по Одесі та Одеській області. Вводити інші міста України немає сенсу.\n\n"
        "💡 *Порада щодо введення:* вводьте *основу слова* без закінчення.\n"
        "Наприклад, замість «Малиновського» введіть *малиновск*, замість «Олександрівка» введіть *олександрівк*.\n"
        "_"
        "Алгоритм автоматично прорахує до 3 символів закінчення (відмінки, роди, множину) у звітах пабліків!_"
    )
    await callback.answer()


@router.message(CustomTriggerStates.waiting_for_keyword)
async def store_custom_user_keyword(message: Message, state: FSMContext, db_session: AsyncSession):
    if not message.text:
        return

    cleaned_input = TextProcessor.normalize(message.text)
    safe_user_input = html.escape(message.text)

    if len(cleaned_input) < 3 or len(cleaned_input) > 30:
        await message.reply(
            "⚠️ Назва локації повинна містити від 3 до 30 символів (без спецсимволів). Спробуйте ще раз:")
        return

    for loc_key, pattern in COMPILED_LOCATIONS.items():
        if pattern.search(cleaned_input):
            await message.reply(
                f"ℹ️ Зверніть увагу: <b>«{safe_user_input}»</b> вже є у вбудованому списку як стандартна зона. "
                "Будь ласка, знайдіть її у головному меню та увімкніть, щоб не витрачати ліміт кастомних фраз."
            )
            await state.clear()
            return

    service = UserService(db_session, redis_client)
    success, message_text = await service.add_custom_trigger(message.from_user.id, cleaned_input)

    final_reply = message_text if not success else f"✅ Кастомну локацію <b>«{safe_user_input}»</b> успішно додано."
    await message.answer(final_reply)
    await state.clear()


@router.callback_query(CustomActionCallback.filter(F.action == "delete"))
async def delete_custom_user_keyword(callback: CallbackQuery, callback_data: CustomActionCallback,
                                     db_session: AsyncSession):
    if not callback_data.phrase:
        await callback.answer("Помилка: фразу не знайдено", show_alert=True)
        return

    service = UserService(db_session, redis_client)
    await service.delete_custom_trigger(callback.from_user.id, callback_data.phrase)

    user = await get_or_create_user(db_session, callback.from_user.id)
    static_keys = set(ODESA_LOCS.keys()) | set(OUTSIDE_LOCS.keys())
    custom_phrases = {t for t in user.triggers_set if t not in static_keys}

    await callback.message.edit_text(
        text="✍️ <b>Ваші кастомні фрази для відстеження:</b>",
        reply_markup=build_custom_triggers_management_keyboard(custom_phrases)
    )
    await callback.answer(text="Локацію видалено")


@router.callback_query(F.data == ALERT_ACK)
async def process_alert_acknowledgement(callback: CallbackQuery, db_session: AsyncSession):
    service = UserService(db_session, redis_client)
    await service.acknowledge_alert(callback.from_user.id)

    safe_text = callback.message.html_text or "<b>Загроза</b>"
    await callback.message.edit_text(text=f"{safe_text}\n\n✅ <i>Сигнал прийнято.</i>")
    await callback.answer(text="Сповіщення заглушено на 10 хвилин.")