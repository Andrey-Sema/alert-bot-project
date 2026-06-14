import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from redis.asyncio import Redis
from alert_bot_project.core_shared.config import config

logger = logging.getLogger("bot.loader")

# Single instance definition for the official Bot API client
bot = Bot(
    token=config.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

# Central framework update router initialization
dp = Dispatcher()

# Shared production-grade Redis connection pool singleton
redis_client = Redis.from_url(config.REDIS_URL, decode_responses=True)