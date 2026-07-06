
import time
import logging
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update
from redis.asyncio import Redis

logger = logging.getLogger("bot.middlewares.throttling")


class ThrottlingMiddleware(BaseMiddleware):
    """
    Обмежує частоту дій одного user_id через Redis SET NX EX.
    Не блокує назавжди — просто ігнорує апдейти частіше ніж rate_limit секунд,
    без відповіді юзеру (щоб не провокувати ще більше спаму скаргами бота).
    """

    def __init__(self, redis_client: Redis, rate_limit: float = 0.5):
        self.redis = redis_client
        self.rate_limit = rate_limit

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        key = f"throttle:{user.id}"
        allowed = await self.redis.set(key, "1", nx=True, px=int(self.rate_limit * 1000))
        if not allowed:
            logger.debug("Throttled update from user_id=%s", user.id)
            return None

        return await handler(event, data)