import logging
from typing import cast

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from alert_bot_project.bot.keyboards.builders import MENU_INFO, MENU_MAIN, build_back_to_main_keyboard, build_main_menu
from alert_bot_project.bot.keyboards.messages import INFO_TEXT, WELCOME_TEXT
from alert_bot_project.bot.loader import redis_client
from alert_bot_project.database.activity import record_activity
from alert_bot_project.database.crud import get_or_create_user
from alert_bot_project.services.privacy import delete_user_data

logger = logging.getLogger("bot.handlers.start")
router = Router(name="start_router")


@router.message(CommandStart())
async def process_start_command(message: Message, db_session: AsyncSession) -> None:
    assert message.from_user is not None
    user_id = message.from_user.id

    try:
        await get_or_create_user(db_session, user_id)
        await record_activity(db_session, user_id)
        await db_session.commit()
        await redis_client.delete(f"privacy:deleted:{user_id}")
        logger.info("User ID %d successfully initiated /start command session.", user_id)
    except (SQLAlchemyError, RedisError):
        # ✅ СЕНЬОР-ФИКС: Избыточный перехват OperationalError убран, так как он наследуется от SQLAlchemyError.
        # Заодно переведено на канонический .exception()
        logger.exception("Database transport failure during user session initialization")
        await message.answer("⚠️ Виникла помилка під час реєстрації. Будь ласка, спробуйте пізніше.")
        return
    except Exception:
        logger.exception("Unexpected framework thread exception inside start handler context")
        await message.answer("⚠️ Критична помилка системи. Спробуйте пізніше.")
        return

    await message.answer(WELCOME_TEXT, reply_markup=build_main_menu())


@router.message(Command("delete_me"))
async def request_data_deletion(message: Message) -> None:
    if message.from_user is None or message.chat.id != message.from_user.id:
        await message.answer("Видалення доступне лише в приватному чаті з ботом.")
        return
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="Так, видалити мої дані", callback_data="privacy:confirm_delete")
    await message.answer(
        "Видалити профіль, локації та поточні завдання сповіщень? Дія незворотна.",
        reply_markup=keyboard.as_markup(),
    )


@router.callback_query(F.data == "privacy:confirm_delete")
async def confirm_data_deletion(callback: CallbackQuery, db_session: AsyncSession) -> None:
    if callback.from_user is None or callback.message is None or callback.message.chat.id != callback.from_user.id:
        await callback.answer("Доступно лише у власному приватному чаті", show_alert=True)
        return
    try:
        await delete_user_data(db_session, redis_client, callback.from_user.id)
    except (SQLAlchemyError, RedisError):
        logger.exception("User data deletion did not finish")
        await callback.answer("Видалення не завершено. Повторіть запит.", show_alert=True)
        return
    await cast(Message, callback.message).edit_text("Ваші активні дані видалено. /start для нової реєстрації.")
    await callback.answer()


@router.callback_query(F.data == MENU_MAIN)
async def process_return_to_main_menu(callback: CallbackQuery) -> None:
    # Колбек завжди прив'язаний до повідомлення бота, яке ми щойно редагуємо;
    # cast() лише повідомляє про це mypy, не змінюючи поведінку під час виконання.
    await cast(Message, callback.message).edit_text(
        text="🛡️ <b>Головне меню налаштувань:</b>", reply_markup=build_main_menu()
    )
    await callback.answer()


@router.callback_query(F.data == MENU_INFO)
async def process_info_menu(callback: CallbackQuery) -> None:
    await cast(Message, callback.message).edit_text(text=INFO_TEXT, reply_markup=build_back_to_main_keyboard())
    await callback.answer()
