import logging
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from sqlalchemy.exc import SQLAlchemyError, OperationalError

from alert_bot_project.database.engine import AsyncSessionLocal
from alert_bot_project.database.crud import get_or_create_user
from alert_bot_project.bot.keyboards.builders import build_main_menu

logger = logging.getLogger("bot.handlers.start")
router = Router(name="start_router")


@router.message(CommandStart())
async def process_start_command(message: Message):
    """Registers user profiles natively with explicit database exception traps."""
    user_id = message.from_user.id

    async with AsyncSessionLocal() as session:
        # Fix: Replaced broad generic exception traps with precise SQLAlchemy constraint boundaries mapping
        try:
            async with session.begin():
                await get_or_create_user(session, user_id)
        except (SQLAlchemyError, OperationalError) as db_err:
            logger.error("Database transport failure during user session initialization: %s", db_err)
            await message.answer("⚠️ Виникла помилка під час реєстрації. Будь ласка, спробуйте пізніше.")
            return
        except Exception as unexpected_err:
            logger.critical("Unexpected framework thread exception inside start handler context: %s", unexpected_err, exc_info=True)
            await message.answer("⚠️ Критична помилка системи. Спробуйте пізніше.")
            return

    welcome_text = (
        "🛡️ <b>Вітаємо у системі персонального моніторингу загроз!</b>\n\n"
        "Цей бот призначений для миттєвого інформування про небезпеку у конкретно обраних вами зонах "
        "на основі оперативного аналізу інформаційних каналів.\n\n"
        "ℹ️ <b>Важливо:</b> Бот є допоміжним інструментом і не замінює державну повітряну тривогу. "
        "У разі отримання сигналу небезпеки завжди прямуйте до найближчого укриття.\n\n"
        "Скористайтеся меню нижче для налаштування моніторингу:"
    )
    await message.answer(welcome_text, reply_markup=build_main_menu())


@router.callback_query(F.data == "menu:main")
async def process_return_to_main_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        text="🛡️ <b>Головне меню налаштувань:</b>",
        reply_markup=build_main_menu()
    )
    await callback.answer()


@router.callback_query(F.data == "menu:info")
async def process_info_menu(callback: CallbackQuery):
    info_text = (
        "ℹ️ <b>Інформація про роботу системи:</b>\n\n"
        "• <b>Принцип дії:</b> Наш автономний модуль перехоплює повідомлення інформаційних пабліків "
        "та аналізує їх на наявність специфічних географічних і тактичних ключових слів.\n\n"
        "• <b>Двомовність:</b> Система автоматично розпізнає назви локацій як українською, "
        "та ко російською мовами, зводячи їх до єдиного внутрішнього ідентифікатора.\n\n"
        "• <b>Кастомні триггери:</b> Ви можете додати до 5 власних точних назв вулиць, орієнтирів "
        "або селищ. Якщо це слово з'явиться у звітах адмінів — ви миттєво отримаєте попередження."
    )
    # Fix: Replaced unexported transitive reference lookups with direct native class definition calls
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data="menu:main")

    await callback.message.edit_text(text=info_text, reply_markup=kb.as_markup())
    await callback.answer()