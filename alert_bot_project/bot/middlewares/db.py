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

                if session.is_active:
                    await session.commit()

                return result

            except SQLAlchemyError:
                # ✅ ФИКС С СОНАРОМ (python:S8572): Использование правильного логгера сеньор-уровня .exception()
                logger.exception("Критична помилка бази даних SQLAlchemy під час обробки апдейту")
                if session.is_active:
                    await session.rollback()
                raise

            except Exception:
                # ✅ ФИКС С СОНАРОМ (python:S8572): Перевод на .exception() без явной ручной передачи стейка трассировки
                logger.exception("Неочікувана помилка виконання хендлера під час обробки апдейту")
                if session.is_active:
                    await session.rollback()
                raise