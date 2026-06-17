import logging
from typing import Any, Optional
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiohttp import ClientTimeout
from redis.asyncio import Redis
from alert_bot_project.core_shared.config import config

logger = logging.getLogger("bot.loader")

# Внутреннее приватное хранилище для ленивых синглтонов
_bot: Optional[Bot] = None
_dp: Optional[Dispatcher] = None
_redis_client: Optional[Redis] = None


def __getattr__(name: str) -> Any:
    """
    Реализация PEP 562 для ленивой инициализации синглтонов на уровне модуля.

    Объекты создаются только в момент первого фактического обращения к ним в коде,
    что исключает падения на этапе импорта и позволяет изолированно тестировать хендлеры.
    """
    global _bot, _dp, _redis_client

    if name == "bot":
        if _bot is None:
            logger.info("Lazy-initializing official Bot API client...")
            custom_timeout = ClientTimeout(total=10.0, connect=2.0, sock_read=5.0)
            session = AiohttpSession(timeout=custom_timeout)
            _bot = Bot(
                token=config.BOT_TOKEN,
                session=session,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML)
            )
        return _bot

    if name == "dp":
        if _dp is None:
            logger.info("Lazy-initializing central Dispatcher framework...")
            _dp = Dispatcher()
        return _dp

    if name == "redis_client":
        if _redis_client is None:
            logger.info("Lazy-initializing shared production Redis connection pool...")
            _redis_client = Redis.from_url(config.REDIS_URL, decode_responses=True)
        return _redis_client

    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")