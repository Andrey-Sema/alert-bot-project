import logging
from typing import cast

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from alert_bot_project.bot.keyboards.builders import MENU_INFO, MENU_MAIN, build_back_to_main_keyboard, build_main_menu
from alert_bot_project.bot.keyboards.messages import INFO_TEXT, WELCOME_TEXT
from alert_bot_project.core_shared.privacy import hash_peer_id
from alert_bot_project.database.crud import get_or_create_user

logger = logging.getLogger("bot.handlers.start")
router = Router(name="start_router")


@router.message(CommandStart())
async def process_start_command(message: Message, db_session: AsyncSession) -> None:
    assert message.from_user is not None
    user_id = message.from_user.id

    try:
        await get_or_create_user(db_session, user_id)
        logger.info("User %s successfully initiated /start command session.", hash_peer_id(user_id))
    except SQLAlchemyError:
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
