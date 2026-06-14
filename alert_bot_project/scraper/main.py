import asyncio
import logging
import signal
import sys
from pyrogram import Client, filters
from pyrogram.types import Message

from alert_bot_project.core_shared.config import config
from alert_bot_project.core_shared.schemas import AlertMessage
from alert_bot_project.scraper.publisher import RedisPublisher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("scraper.main")

# Dedicated session storage directory configured for mounting host Docker Volumes
SESSION_DIR = "/data/session"

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
    """Intercepts broadcast events and safely structures them to transient stream pipelines."""
    raw_text = message.text or message.caption
    if not raw_text:
        return

    logger.info("Captured raw source payload feed ID: %s", message.id)

    alert_payload = AlertMessage(
        message_id=message.id,
        chat_id=message.chat.id,
        raw_text=raw_text
    )

    # Wrap the publication invocation inside defensive boundaries
    try:
        await publisher.publish_message(alert_payload.to_json())
    except Exception as exc:
        logger.error("Failed downstream message transmission pipeline: %s", exc)


async def stop_services():
    """Handles orchestration shutdown gracefully to protect session persistence mapping layers."""
    logger.info("Initiating graceful teardown protocol stack...")
    try:
        await app.stop()
        logger.info("Pyrogram listener runtime stopped safely.")
    except Exception as e:
        logger.error("Error destroying engine operational worker: %s", e)

    try:
        await publisher.close()
        logger.info("Redis link destroyed safely.")
    except Exception as e:
        logger.error("Error winding down stream publisher interface: %s", e)

    shutdown_event.set()


def setup_signal_handlers():
    """Configures system operational signals intercepts."""
    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(stop_services()))
    except NotImplementedError:
        # Graceful fallback handler support for edge platform execution constraints
        pass


async def main():
    setup_signal_handlers()
    await publisher.connect()

    logger.info("Starting Pyrogram client infrastructure tracking layer...")
    await app.start()
    logger.info("Scraper background subsystem engine online.")

    await shutdown_event.wait()
    logger.info("Subsystem execution terminated.")


if __name__ == "__main__":
    asyncio.run(main())