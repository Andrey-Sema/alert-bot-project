import asyncio
import logging
import signal
import time
import json
import hashlib
import random
import itertools
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from alert_bot_project.core_shared.config import config
from alert_bot_project.core_shared.logging_config import setup_logging
from alert_bot_project.core_shared.schemas import AlertMessage
from alert_bot_project.core_shared.text_processor import TextProcessor
from alert_bot_project.core_shared.constants import ALERT_FIRST, KYIV_TZ, ODESA_LOCS, OUTSIDE_LOCS
from alert_bot_project.database.engine import AsyncSessionLocal
from alert_bot_project.database.crud import get_users_by_trigger_and_category
from alert_bot_project.worker.broadcaster import Broadcaster
from alert_bot_project.bot.keyboards.builders import build_acknowledge_keyboard

setup_logging("worker")
logger = logging.getLogger("worker.main")

LOCAL_TZ = ZoneInfo(KYIV_TZ)
STREAM_NAME = "alerts_stream"
GROUP_NAME = "workers_group"
CONSUMER_NAME = "worker_node_primary"

is_running = True


def is_quiet_hours_active() -> bool:
    now = datetime.now(LOCAL_TZ).time()
    start = datetime.strptime(f"{config.NIGHT_START_HOUR}:00", "%H:%M").time()
    end = datetime.strptime(f"{config.NIGHT_END_HOUR}:00", "%H:%M").time()
    if start <= end:
        return start <= now <= end
    return now >= start or now <= end


def generate_phrase_candidates_generator(words_list: list[str], max_phrase_length: int = 4):
    for i in range(len(words_list)):
        for j in range(1, min(max_phrase_length + 1, len(words_list) - i + 1)):
            yield " ".join(words_list[i:i + j])


async def init_redis_consumer_group(redis_client: Redis):
    try:
        if await redis_client.exists(STREAM_NAME):
            groups = await redis_client.xinfo_groups(STREAM_NAME)
            if any(g['name'] == GROUP_NAME for g in groups):
                return
        await redis_client.xgroup_create(name=STREAM_NAME, groupname=GROUP_NAME, id="$", mkstream=True)
        logger.info(f"Persistent Redis Consumer Group established: {GROUP_NAME}")
    except ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise e


async def monitor_dlq_backlog(redis_client: Redis):
    try:
        if await redis_client.exists("dead_letter_queue"):
            startup_depth = await redis_client.xlen("dead_letter_queue")
            if startup_depth > 0:
                logger.error("Initial absolute state tracker check: dead_letter_queue holds %s entries.", startup_depth)
    except Exception as e:
        logger.error(f"Failed pulling absolute DLQ depth parameters: {e}")

    while is_running:
        try:
            if await redis_client.exists("dead_letter_queue"):
                dlq_depth = await redis_client.xlen("dead_letter_queue")
                prev_depth_raw = await redis_client.get("dlq:prev_depth")
                prev_depth = int(prev_depth_raw or 0)

                if dlq_depth != prev_depth:
                    logger.error("DLQ depth transformation detected: %s -> %s entries present.", prev_depth, dlq_depth)
                    await redis_client.set("dlq:prev_depth", str(dlq_depth))
        except Exception as e:
            logger.error(f"Error checking DLQ logs limits depth metrics: {e}")
        await asyncio.sleep(60)


async def auto_claim_pending_tasks(redis_client: Redis, broadcaster: Broadcaster):
    while is_running:
        try:
            await asyncio.sleep(30 + random.uniform(0.0, 10.0))
            res = await redis_client.xautoclaim(
                name=STREAM_NAME, groupname=GROUP_NAME, consumername=CONSUMER_NAME,
                min_idle_time=60000, start_id="0-0", count=10
            )
            if res and res[1]:
                for msg_id, payload in res[1]:
                    raw_json = payload.get("payload")
                    if not raw_json:
                        await redis_client.xack(STREAM_NAME, GROUP_NAME, msg_id)
                        continue

                    try:
                        alert_data = AlertMessage.from_json(raw_json)
                        dedup_key = f"processed_msg:{alert_data.message_id}"
                        if await redis_client.get(dedup_key):
                            await redis_client.xack(STREAM_NAME, GROUP_NAME, msg_id)
                            continue
                    except Exception:
                        pass

                    await process_single_stream_payload(msg_id, raw_json, redis_client, broadcaster)
        except Exception as e:
            logger.error("Exception occurred inside PEL XAUTOCLAIM tracking loop: %s", e)


async def process_single_stream_payload(redis_msg_id: str, raw_json: str, redis_client: Redis, broadcaster: Broadcaster):
    try:
        alert_data = AlertMessage.from_json(raw_json)
    except Exception as err:
        logger.warning("Dropped corrupted structural input stream item: %s", err)
        await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
        return

    if (datetime.now(timezone.utc) - alert_data.timestamp).total_seconds() > 600:
        await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
        return

    dedup_key = f"processed_msg:{alert_data.message_id}"
    analysis = TextProcessor.parse_message(alert_data.raw_text)
    normalized_text = TextProcessor.normalize(alert_data.raw_text)

    # Fix: Corrected conditional check to evaluate global custom trigger presence cleanly per-user scale context paths
    has_custom_triggers = await redis_client.exists("has_custom_triggers") > 0

    if not analysis["categories"] and not analysis["locations"] and not has_custom_triggers:
        await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
        return

    phrase_candidates = []
    if has_custom_triggers:
        words = normalized_text.split()
        phrase_candidates = list(itertools.islice(generate_phrase_candidates_generator(words, max_phrase_length=4), 100))

    sorted_locs = sorted(list(analysis["locations"]))
    sorted_cats = sorted(list(analysis["categories"]))

    hash_payload = f"locs:{sorted_locs}|cats:{sorted_cats}"
    checksum = hashlib.md5(hash_payload.encode("utf-8")).hexdigest()

    cache_version = await redis_client.get("cache:generation_version") or "0"
    cache_hash_key = f"cache:alert_targets_v{cache_version}:{checksum}"

    cached_targets = await redis_client.get(cache_hash_key)

    if cached_targets:
        user_ids_list = json.loads(cached_targets)
    else:
        all_static_keys = list(ODESA_LOCS.keys()) + list(OUTSIDE_LOCS.keys())
        async with AsyncSessionLocal() as session:
            try:
                target_users = await get_users_by_trigger_and_category(
                    session=session, location_keys=analysis["locations"],
                    category_names=analysis["categories"], phrase_candidates=phrase_candidates,
                    all_static_keys=all_static_keys
                )
                user_ids_list = [u.user_id for u in target_users]

                if not user_ids_list:
                    await redis_client.setex(cache_hash_key, 30, json.dumps([]))
                else:
                    await redis_client.setex(cache_hash_key, 30, json.dumps(user_ids_list))
            except Exception as db_err:
                retry_key = f"retry_count:{redis_msg_id}"
                current_retries = await redis_client.incr(retry_key)
                await redis_client.expire(retry_key, 3600)

                if current_retries > 5:
                    logger.error("Task message ID %s dropped after exceeding retry limit. Relocating to DLQ.", redis_msg_id)
                    await redis_client.xadd("dead_letter_queue", {"payload": raw_json, "error": str(db_err)}, maxlen=10000)
                    await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
                    await redis_client.delete(retry_key)
                else:
                    logger.warning("Database transient exception recorded on iteration %s/5. Leaving task inside PEL loop.", current_retries)
                return

    if not user_ids_list:
        await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
        return

    is_fresh_lock = await redis_client.set(dedup_key, "1", nx=True, ex=300)
    if not is_fresh_lock:
        await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
        return

    logger.info("Fresh broadcast alert payload verified. Forwarding dispatch streams downpipes safely.")
    quiet_mode = is_quiet_hours_active()
    alert_markup = build_acknowledge_keyboard()
    display_text = f"{ALERT_FIRST}\n\n🌙 <i>[Сповіщення надіслано у тихому режимі нічного часу]</i>" if quiet_mode else ALERT_FIRST

    # Fix: Resolved fatal coroutine leak by calling synchronous fire_and_forget_message cleanly without unawaited tokens
    for u_id in user_ids_list:
        broadcaster.fire_and_forget_message(u_id, display_text, reply_markup=alert_markup, disable_notification=quiet_mode)
        broadcaster.schedule_delayed_alerts(u_id, disable_notification=quiet_mode)

    await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
    await redis_client.delete(f"retry_count:{redis_msg_id}")


async def main():
    global is_running
    logger.info("Production background alert stream analysis subsystem initialization...")

    bot = Bot(token=config.BOT_TOKEN)
    redis_client = Redis.from_url(config.REDIS_URL, decode_responses=True)

    await init_redis_consumer_group(redis_client)
    broadcaster = Broadcaster(bot, redis_client)

    delayed_daemon = asyncio.create_task(broadcaster.process_delayed_alerts())
    recovery_daemon = asyncio.create_task(auto_claim_pending_tasks(redis_client, broadcaster))
    dlq_daemon = asyncio.create_task(monitor_dlq_backlog(redis_client))

    def shutdown_handler():
        global is_running
        is_running = False

    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, shutdown_handler)
    except NotImplementedError:
        logger.warning("System platform environment restricts native direct POSIX signal handlers assignments.")

    logger.info("Clearing outstanding internal consumer PEL backlogs...")
    backlog_data = await redis_client.xreadgroup(groupname=GROUP_NAME, consumername=CONSUMER_NAME, streams={STREAM_NAME: "0"}, count=100, block=10)
    if backlog_data:
        for stream, messages in backlog_data:
            for redis_msg_id, payload in messages:
                raw_json = payload.get("payload")
                if raw_json:
                    await process_single_stream_payload(redis_msg_id, raw_json, redis_client, broadcaster)

    logger.info("Worker processing loop listening for target stream pipelines...")
    while is_running:
        try:
            streams_data = await redis_client.xreadgroup(groupname=GROUP_NAME, consumername=CONSUMER_NAME, streams={STREAM_NAME: ">"}, count=1, block=1000)
            if not streams_data:
                continue
            for stream, messages in streams_data:
                for redis_msg_id, payload in messages:
                    raw_json = payload.get("payload")
                    if raw_json:
                        await process_single_stream_payload(redis_msg_id, raw_json, redis_client, broadcaster)
                    else:
                        await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
        except Exception as e:
            logger.error("Core engine execution loop error: %s", e, exc_info=True)
            await asyncio.sleep(2)

    delayed_daemon.cancel()
    recovery_daemon.cancel()
    dlq_daemon.cancel()
    await redis_client.close()
    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())