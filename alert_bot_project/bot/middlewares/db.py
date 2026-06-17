import logging
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.exc import SQLAlchemyError
from alert_bot_project.database.engine import AsyncSessionLocal

logger = logging.getLogger("bot.middlewares.db")


class DatabaseMiddleware(BaseMiddleware):
    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: TelegramObject,
            data: Dict[str, Any]
    ) -> Any:
        async with AsyncSessionLocal() as session:
            data["db_session"] = session
            try:
                result = await handler(event, data)

                # ✅ ФИКС: Защита краевого случая. Коммитим только если транзакция активна
                # и сессия не была принудительно закрыта или инвалидирована внутри хендлера
                if session.is_active:
                    await session.commit()

                return result

            except SQLAlchemyError as db_err:
                # ✅ ФИКС: Дифференциация ошибок. Выделяем сбои БД в отдельный критический контекст
                logger.error("Критична помилка бази даних SQLAlchemy під час обробки апдейту: %s", db_err,
                             exc_info=True)
                if session.is_active:
                    await session.rollback()
                raise

            except Exception as e:
                # ✅ ФИКС: Обработка неожиданных исключений логики/валидации приложения
                logger.error("Неочікувана помилка виконання хендлера під час обробки апдейту: %s", e, exc_info=True)
                if session.is_active:
                    await session.rollback()
                raise