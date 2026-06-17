import asyncio
import logging
import signal
import os
from pyrogram import Client, filters
from pyrogram.types import Message

from alert_bot_project.core_shared.config import config
from alert_bot_project.core_shared.schemas import AlertMessage
from alert_bot_project.scraper.publisher import RedisPublisher
from alert_bot_project.core_shared.metrics import start_metrics_server, SCRAPER_MESSAGES, SCRAPER_ERRORS
# ✅ ФИКС 1: Импортируем наш централизованный логгер проекта
from alert_bot_project.core_shared.logging_config import setup_logging

# ✅ ФИКС 1: Заменяем дефолтный basicConfig на структурированный ротационный логгер.
# Теперь логи скрейпера будут чисто писаться в JSON-формате в файл /data/logs/scraper.json.log
setup_logging("scraper")
logger = logging.getLogger("scraper.main")

SESSION_DIR = "/data/session"

# Поддержка безопасных In-Memory сессий для деплоя
session_str = os.getenv("PYROGRAM_SESSION_STRING")
if session_str:
    app = Client(
        name="twink_account",
        session_string=session_str,
        api_id=config.API_ID,
        api_hash=config.API_HASH
    )
else:
    app = Client(
        name="twink_account",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        workdir=SESSION_DIR
    )

publisher = RedisPublisher()
shutdown_event = asyncio.Event()


@app.on_message(filters.chat(config.GROUP_ID) & (filters.text | filters.caption))
async def handle_channel_post(client: Client, message: Message):
    raw_text = message.text or message.caption
    if not raw_text:
        return

    logger.info("Captured raw source payload feed ID: %s", message.id)
    SCRAPER_MESSAGES.inc()

    alert_payload = AlertMessage(
        message_id=message.id,
        chat_id=message.chat.id,
        raw_text=raw_text
    )

    # ✅ ФИКС 2: Выносим нативную сериализацию Pydantic v2 за пределы цикла ретраев.
    # JSON генерируется ровно один раз, разгружая CPU при повторных попытках отправки.
    json_payload = alert_payload.model_dump_json()

    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Публикуем уже готовый спарсенный JSON-пайлоад
            await publisher.publish_message(json_payload)
            break
        except Exception as exc:
            SCRAPER_ERRORS.inc()
            wait_time = 2 ** attempt
            logger.error("Failed downstream message transmission (attempt %d/%d): %s. Retrying in %ds...",
                         attempt + 1, max_retries, exc, wait_time)
            await asyncio.sleep(wait_time)
    else:
        logger.critical("🚨 MESSAGE PERMANENTLY LOST after %d retries! Message ID: %s", max_retries, message.id)


async def stop_services():
    logger.info("Initiating graceful teardown protocol stack...")
    try:
        await app.stop()
    except Exception as e:
        logger.error("Error destroying engine operational worker: %s", e)

    try:
        await publisher.close()
    except Exception as e:
        logger.error("Error winding down stream publisher interface: %s", e)

    shutdown_event.set()


def setup_signal_handlers():
    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(stop_services()))
    except NotImplementedError:
        pass


async def main():
    start_metrics_server(config.METRICS_PORT_SCRAPER)

    setup_signal_handlers()
    await publisher.connect()

    logger.info("Starting Pyrogram client infrastructure tracking layer...")
    await app.start()
    logger.info("Scraper background subsystem engine online.")

    await shutdown_event.wait()
    logger.info("Subsystem execution terminated.")


if __name__ == "__main__":
    asyncio.run(main())