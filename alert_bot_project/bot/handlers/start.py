import logging
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from alert_bot_project.database.crud import get_or_create_user
from alert_bot_project.bot.keyboards.builders import (
    build_main_menu, build_back_to_main_keyboard, MENU_MAIN, MENU_INFO
)
from alert_bot_project.bot.keyboards.messages import WELCOME_TEXT, INFO_TEXT

logger = logging.getLogger("bot.handlers.start")
router = Router(name="start_router")


@router.message(CommandStart())
async def process_start_command(message: Message, db_session: AsyncSession):
    user_id = message.from_user.id

    try:
        await get_or_create_user(db_session, user_id)
        logger.info("User ID %d successfully initiated /start command session.", user_id)
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
async def process_return_to_main_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        text="🛡️ <b>Головне меню налаштувань:</b>",
        reply_markup=build_main_menu()
    )
    await callback.answer()


@router.callback_query(F.data == MENU_INFO)
async def process_info_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        text=INFO_TEXT,
        reply_markup=build_back_to_main_keyboard()
    )
    await callback.answer()