import logging
import html
from datetime import datetime, timedelta, timezone
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from alert_bot_project.database.crud import get_or_create_user
from alert_bot_project.services.user_service import UserService
from alert_bot_project.bot.loader import redis_client
from alert_bot_project.core_shared.constants import ODESA_LOCS, OUTSIDE_LOCS, KYIV_TZ
from alert_bot_project.core_shared.callbacks import (
    GroupNavCallback, LocationToggleCallback, ThreatCategoryCallback,
    MutePresetCallback, CustomActionCallback, CustomTriggerStates
)
from alert_bot_project.bot.keyboards.builders import (
    build_group_selection_menu, build_locations_paginated_keyboard,
    build_threat_categories_keyboard, build_mute_options_keyboard,
    build_custom_triggers_management_keyboard
)

logger = logging.getLogger("bot.handlers.settings")
router = Router(name="settings_router")


@router.callback_query(F.data == "menu:choose_group")
async def show_group_selection(callback: CallbackQuery):
    await callback.message.edit_text("Оберіть регіональну групу дислокацій для налаштування:",
                                     reply_markup=build_group_selection_menu())
    await callback.answer()


@router.callback_query(F.data == "menu:custom_manage")
async def show_custom_phrases_menu(callback: CallbackQuery, db_session: AsyncSession):
    async with db_session.begin():
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
    async with db_session.begin():
        user = await get_or_create_user(db_session, callback.from_user.id)
        triggers = user.triggers_set

    await callback.message.edit_text(
        text="Оберіть точні локації для моніторингу:",
        reply_markup=build_locations_paginated_keyboard(callback_data.group, triggers, callback_data.page)
    )
    await callback.answer()


@router.callback_query(LocationToggleCallback.filter())
async def toggle_location_trigger(callback: CallbackQuery, callback_data: LocationToggleCallback,
                                  db_session: AsyncSession):
    async with db_session.begin():
        service = UserService(db_session, redis_client)
        await service.toggle_location(callback.from_user.id, callback_data.inv_key)
        user = await get_or_create_user(db_session, callback.from_user.id)
        updated_triggers = user.triggers_set

    await callback.message.edit_reply_markup(
        reply_markup=build_locations_paginated_keyboard(callback_data.group, updated_triggers, callback_data.page)
    )
    await callback.answer()


@router.callback_query(F.data == "menu:potvory")
async def show_threat_categories(callback: CallbackQuery, db_session: AsyncSession):
    async with db_session.begin():
        user = await get_or_create_user(db_session, callback.from_user.id)
        categories = user.potvory

    await callback.message.edit_text(
        text="🦅 <b>Налаштування категорій повітряних загроз:</b>",
        reply_markup=build_threat_categories_keyboard(categories)
    )
    await callback.answer()


@router.callback_query(ThreatCategoryCallback.filter())
async def toggle_threat_category(callback: CallbackQuery, callback_data: ThreatCategoryCallback,
                                 db_session: AsyncSession):
    async with db_session.begin():
        service = UserService(db_session, redis_client)
        user = await get_or_create_user(db_session, callback.from_user.id)
        categories = list(user.potvory)

        if callback_data.category in categories:
            categories.remove(callback_data.category)
        else:
            categories.append(callback_data.category)

        msg = await service.set_threat_categories(callback.from_user.id, categories)

    await callback.message.edit_reply_markup(reply_markup=build_threat_categories_keyboard(categories))
    await callback.answer(text=msg)


@router.callback_query(F.data == "menu:mute")
async def show_mute_options(callback: CallbackQuery):
    await callback.message.edit_text(text="🔕 <b>Режим тиші (MUTE):</b>", reply_markup=build_mute_options_keyboard())
    await callback.answer()


@router.callback_query(MutePresetCallback.filter())
async def process_mute_action(callback: CallbackQuery, callback_data: MutePresetCallback, db_session: AsyncSession):
    user_id = callback.from_user.id
    now_utc = datetime.now(timezone.utc)

    async with db_session.begin():
        service = UserService(db_session, redis_client)
        if callback_data.preset == "clear":
            msg = await service.apply_mute_timeout(user_id, None, "Звук увімкнено")
            await redis_client.delete(f"user_mute:{user_id}")
        else:
            mapping = {"1": 1, "2": 2, "4": 4}
            if callback_data.preset in mapping:
                ttl_seconds = mapping[callback_data.preset] * 3600
                until = now_utc + timedelta(hours=mapping[callback_data.preset])
                text_reply = f"Сповіщення вимкнено на {callback_data.preset} год."
            else:
                from zoneinfo import ZoneInfo
                kyiv_now = datetime.now(ZoneInfo(KYIV_TZ))
                kyiv_target = kyiv_now.replace(hour=7, minute=0, second=0, microsecond=0)
                if kyiv_now >= kyiv_target:
                    kyiv_target += timedelta(days=1)
                until = kyiv_target.astimezone(timezone.utc)
                ttl_seconds = int((until - now_utc).total_seconds())
                text_reply = "Сповіщення вимкнено до ранку"

            msg = await service.apply_mute_timeout(user_id, until, text_reply)
            await redis_client.set(f"user_mute:{user_id}", "1", ex=max(1, ttl_seconds))

    await callback.answer(text=msg)


@router.callback_query(F.data == "custom:add")
async def initiate_custom_trigger_prompt(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CustomTriggerStates.waiting_for_keyword)
    await callback.message.answer("✍️ <b>Введіть назву вашої кастомної локації:</b>")
    await callback.answer()


@router.message(CustomTriggerStates.waiting_for_keyword)
async def store_custom_user_keyword(message: Message, state: FSMContext, db_session: AsyncSession):
    cleaned_input = message.text.strip().lower()
    if len(cleaned_input) < 3 or len(cleaned_input) > 30:
        await message.reply("⚠️ Назва локації повинна містити від 3 до 30 символів. Спробуйте ще раз:")
        return

    async with db_session.begin():
        service = UserService(db_session, redis_client)
        success, message_text = await service.add_custom_trigger(message.from_user.id, cleaned_input)

    safe_output = html.escape(cleaned_input)
    final_reply = message_text if not success else f"✅ Кастомну локацію <b>«{safe_output}»</b> успішно додано."

    await message.answer(final_reply)
    await state.clear()


@router.callback_query(CustomActionCallback.filter(F.action == "delete"))
async def delete_custom_user_keyword(callback: CallbackQuery, callback_data: CustomActionCallback,
                                     db_session: AsyncSession):
    async with db_session.begin():
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


@router.callback_query(F.data == "alert:ack")
async def process_alert_acknowledgement(callback: CallbackQuery, db_session: AsyncSession):
    until = datetime.now(timezone.utc) + timedelta(minutes=10)
    async with db_session.begin():
        service = UserService(db_session, redis_client)
        await service.apply_mute_timeout(callback.from_user.id, until, "Сигнал прийнято")
        await redis_client.set(f"user_mute:{callback.from_user.id}", "1", ex=600)

    await callback.message.edit_text(text=f"{callback.message.text}\n\n✅ <i>Сигнал прийнято.</i>")
    await callback.answer(text="Сповіщення заглушено на 10 хвилин.")