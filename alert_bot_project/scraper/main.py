import asyncio
import logging
import os
import random
import signal
from datetime import UTC
from typing import cast

from pyrogram import Client, filters  # type: ignore[attr-defined]
from pyrogram.types import Message

from alert_bot_project.core_shared.config import config

# ✅ ФИКС 1: Импортируем наш централизованный логгер проекта
from alert_bot_project.core_shared.logging_config import setup_logging
from alert_bot_project.core_shared.metrics import (
    SCRAPER_ERRORS,
    SCRAPER_MESSAGES,
    SCRAPER_OUTBOX_DEPTH,
    SOURCE_PERSISTED,
    SOURCE_PUBLISHED,
    start_metrics_server,
)
from alert_bot_project.core_shared.schemas import AlertMessage
from alert_bot_project.scraper.catchup import HistoryClient, catch_up_channel
from alert_bot_project.scraper.outbox import ScraperOutbox
from alert_bot_project.scraper.publisher import RedisPublisher

# ✅ ФИКС 1: Заменяем дефолтный basicConfig на структурированный ротационный логгер.
# Теперь логи скрейпера будут чисто писаться в JSON-формате в файл /data/logs/scraper.json.log
setup_logging("scraper")
logger = logging.getLogger("scraper.main")

SESSION_DIR = "/data/session"

# Поддержка безопасных In-Memory сессий для деплоя
session_str = config.PYROGRAM_SESSION_STRING
if session_str:
    app = Client(name="twink_account", session_string=session_str, api_id=config.API_ID, api_hash=config.API_HASH)
else:
    app = Client(name="twink_account", api_id=config.API_ID, api_hash=config.API_HASH, workdir=SESSION_DIR)

publisher = RedisPublisher()
outbox = ScraperOutbox(os.getenv("SCRAPER_OUTBOX_PATH", "/data/outbox/scraper.sqlite3"))
shutdown_event = asyncio.Event()


@app.on_message(filters.chat(config.GROUP_ID) & (filters.text | filters.caption))  # type: ignore[misc]
async def handle_channel_post(client: Client, message: Message) -> None:
    raw_text = message.text or message.caption
    if not raw_text:
        return

    logger.info("Captured raw source payload feed ID: %s", message.id)
    SCRAPER_MESSAGES.inc()

    try:
        source_time = message.date.replace(tzinfo=UTC) if message.date.tzinfo is None else message.date.astimezone(UTC)
        alert_payload = AlertMessage(
            message_id=message.id, chat_id=message.chat.id, raw_text=raw_text, timestamp=source_time
        )
    except Exception:
        logger.warning("Payload validation failed for message ID: %s, skipping", message.id)
        return

    # ✅ ФИКС 2: Выносим нативную сериализацию Pydantic v2 за пределы цикла ретраев.
    # JSON генерируется ровно один раз, разгружая CPU при повторных попытках отправки.
    json_payload = alert_payload.model_dump_json()

    # A confirmed local SQLite commit precedes every Redis publish attempt.
    await outbox.put(message.chat.id, message.id, json_payload)
    SOURCE_PERSISTED.inc()
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Публикуем уже готовый спарсенный JSON-пайлоад
            await publisher.publish_message(json_payload, message.chat.id, message.id)
            SOURCE_PUBLISHED.inc()
            await outbox.delete(message.chat.id, message.id)
            break
        except Exception as exc:
            SCRAPER_ERRORS.inc()
            wait_time = 2**attempt + random.uniform(0, 0.5)  # noqa: S311  # nosec B311
            logger.error(
                "Failed downstream message transmission (attempt %d/%d): %s. Retrying in %.2fs...",
                attempt + 1,
                max_retries,
                exc,
                wait_time,
            )
            if attempt + 1 < max_retries:
                await asyncio.sleep(wait_time)
    else:
        logger.error("Post %s remains in durable outbox after %d attempts", message.id, max_retries)


async def replay_outbox() -> None:
    while not shutdown_event.is_set():
        try:
            pending = await outbox.pending()
            SCRAPER_OUTBOX_DEPTH.set(await outbox.count())
            for chat_id, message_id, payload in pending:
                await publisher.publish_message(payload, chat_id, message_id)
                SOURCE_PUBLISHED.inc()
                await outbox.delete(chat_id, message_id)
            await asyncio.sleep(0.1 if len(pending) == 100 else 5)
        except asyncio.CancelledError:
            raise
        except Exception:
            SCRAPER_ERRORS.inc()
            logger.exception("Outbox replay failed; posts remain on disk")
            await asyncio.sleep(5)


async def catchup_loop() -> None:
    while not shutdown_event.is_set():
        try:
            recovered = await catch_up_channel(cast(HistoryClient, app), outbox, config.GROUP_ID)
            if recovered:
                logger.info("Persisted %d source history posts for outbox replay", recovered)
            await asyncio.wait_for(shutdown_event.wait(), timeout=30)
        except TimeoutError:
            continue
        except asyncio.CancelledError:
            raise
        except Exception:
            SCRAPER_ERRORS.inc()
            logger.exception("Source history catch-up failed; checkpoint remains unchanged")
            await asyncio.sleep(5)


async def expire_legacy_source_markers() -> None:
    while not shutdown_event.is_set():
        try:
            await publisher.expire_legacy_markers()
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Source marker retention migration failed; retrying")
            await asyncio.sleep(60)


async def stop_services() -> None:
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


def setup_signal_handlers() -> None:
    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(stop_services()))
    except NotImplementedError:
        pass


async def main() -> None:
    start_metrics_server(config.METRICS_PORT_SCRAPER)

    setup_signal_handlers()
    logger.info("Starting Pyrogram client infrastructure tracking layer...")
    await app.start()
    replay_task = asyncio.create_task(replay_outbox())
    catchup_task = asyncio.create_task(catchup_loop())
    marker_cleanup_task = asyncio.create_task(expire_legacy_source_markers())
    logger.info("Scraper background subsystem engine online.")

    await shutdown_event.wait()
    replay_task.cancel()
    catchup_task.cancel()
    marker_cleanup_task.cancel()
    await asyncio.gather(replay_task, catchup_task, marker_cleanup_task, return_exceptions=True)
    logger.info("Subsystem execution terminated.")


if __name__ == "__main__":
    asyncio.run(main())
