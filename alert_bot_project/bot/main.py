import asyncio
import logging
from alert_bot_project.core_shared.logging_config import setup_logging
from alert_bot_project.bot.loader import bot, dp, redis_client
from alert_bot_project.bot.handlers import start, settings
from alert_bot_project.bot.middlewares.db import DatabaseMiddleware
from alert_bot_project.core_shared.metrics import start_metrics_server
from alert_bot_project.core_shared.config import config

setup_logging("tg_bot_ui")
logger = logging.getLogger("bot.main")


async def main():
    # ✅ УЛУЧШЕНИЕ: Четкое логирование старта инициализации подсистемы
    logger.info("Starting Bot UI subsystem initialization sequence...")

    # Старт сервера метрик (если порт занят, внутри сработает Fail-Fast sys.exit(1))
    start_metrics_server(config.METRICS_PORT_BOT)

    logger.info("Configuring global update middlewares and registering routers...")
    dp.update.middleware(DatabaseMiddleware())

    dp.include_router(start.router)
    dp.include_router(settings.router)

    logger.info("Dropping outstanding webhook configurations to sync cleanly...")
    try:
        # ✅ ФИКС: Защита от зависания на старте. Задаем жесткий таймаут на запрос к серверам Telegram
        await bot.delete_webhook(drop_pending_updates=True, request_timeout=5)
    except Exception as e:
        # Ошибка сети до Telegram не должна намертво ронять контейнер при перезапуске
        logger.error("Non-fatal network failure during webhook deletion: %s. Continuing to polling...", e)

    # ✅ ФИКС: Устраняем слепую зону мониторинга. Явный сигнал о полной готовности системы к работе
    logger.info("Bot UI is fully initialized and operational. Launching long polling stream loop...")
    try:
        await dp.start_polling(bot)
    finally:
        # ✅ УЛУЧШЕНИЕ: Детальный лог процесса Graceful Shutdown ресурсов
        logger.info("Initiating graceful teardown for Bot UI active network sessions...")
        await bot.session.close()
        await redis_client.close()
        logger.info("Bot UI connection pools destroyed smoothly. Subsystem shutdown complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot application UI process destroyed via runtime execution interrupt.")