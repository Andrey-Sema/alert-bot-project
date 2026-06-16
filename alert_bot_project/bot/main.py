import asyncio
import logging
from alert_bot_project.core_shared.logging_config import setup_logging
from alert_bot_project.bot.loader import bot, dp, redis_client
from alert_bot_project.bot.handlers import start, settings
from alert_bot_project.bot.middlewares.db import DatabaseMiddleware

setup_logging("tg_bot_ui")
logger = logging.getLogger("bot.main")


async def main():
    logger.info("Configuring routers and connecting middlewares...")

    # КРИТИЧЕСКИ ВАЖНО: Регистрируем мидлварь БД для всех апдейтов
    dp.update.middleware(DatabaseMiddleware())

    # Подключаем роутеры с бизнес-логикой
    dp.include_router(start.router)
    dp.include_router(settings.router)

    logger.info("Dropping webhooks configurations parameters to sync cleanly...")
    await bot.delete_webhook(drop_pending_updates=True)

    logger.info("Starting long polling interfaces updates tracking routines...")
    try:
        await dp.start_polling(bot)
    finally:
        # Корректно закрываем все открытые соединения при шатдауне
        await bot.session.close()
        await redis_client.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot application UI destroyed smoothly.")