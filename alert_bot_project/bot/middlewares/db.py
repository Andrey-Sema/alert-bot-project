import logging
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from alert_bot_project.database.engine import AsyncSessionLocal

logger = logging.getLogger("bot.middlewares.db")


class DatabaseMiddleware(BaseMiddleware):
    """
    Implements the clean Unit of Work pattern via aiogram middleware execution bounds.
    Ensures a single atomic transaction context per incoming update lifecycle.
    """
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        async with AsyncSessionLocal() as session:
            # Fix: Open an explicit atomic transaction context for the duration of the request
            async with session.begin():
                data["db_session"] = session
                return await handler(event, data)