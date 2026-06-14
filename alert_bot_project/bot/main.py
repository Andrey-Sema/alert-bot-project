import asyncio
import logging
import sys
from alert_bot_project.core_shared.logging_config import setup_logging
from alert_bot_project.bot.loader import bot, dp
from alert_bot_project.bot.handlers import start, settings

# Setup logging architecture parameters directly for bot scope
setup_logging("tg_bot_ui")
logger = logging.getLogger("bot.main")


async def main():
    logger.info("Configuring routers mapping parameters arrays...")

    # Include functional feature logic modules blocks
    dp.include_router(start.router)
    dp.include_router(settings.router)

    logger.info("Dropping webhooks configurations parameters to sync cleanly...")
    await bot.delete_webhook(drop_pending_updates=True)

    logger.info("Starting long polling interfaces updates tracking routines...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot application UI destroyed smoothly.")