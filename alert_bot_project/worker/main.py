import asyncio
import logging
import signal
import time
import json
import hashlib
import random
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select

from aiogram import Bot
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from alert_bot_project.core_shared.config import config
from alert_bot_project.core_shared.logging_config import setup_logging
from alert_bot_project.core_shared.schemas import AlertMessage
from alert_bot_project.core_shared.text_processor import TextProcessor
from alert_bot_project.core_shared.constants import ALERT_FIRST, KYIV_TZ, ODESA_LOCS, OUTSIDE_LOCS
from alert_bot_project.core_shared.metrics import (
    start_metrics_server, ALERTS_PROCESSED, PROCESSING_TIME, DLQ_SIZE, WORKER_ERRORS
)
from alert_bot_project.database.engine import AsyncSessionLocal
from alert_bot_project.database.models import UserTrigger
from alert_bot_project.database.crud import get_users_by_trigger_and_category
from alert_bot_project.worker.broadcaster import Broadcaster
from alert_bot_project.bot.keyboards.builders import build_acknowledge_keyboard

setup_logging("worker")
logger = logging.getLogger("worker.main")

LOCAL_TZ = ZoneInfo(KYIV_TZ)
STREAM_NAME = "alerts_stream"
GROUP_NAME = "workers_group"
CONSUMER_NAME = "worker_node_primary"

# Strict boundaries for in-memory O(N) substring match
_WORD_BOUNDARY = r"(?<![\w])"
_WORD_BOUNDARY_END = r"(?![\w])"

is_running = True


def is_quiet_hours_active() -> bool:
    now = datetime.now(LOCAL_TZ).time()
    start = datetime.strptime(f"{config.NIGHT_START_HOUR}:00", "%H:%M").time()
    end = datetime.strptime(f"{config.NIGHT_END_HOUR}:00", "%H:%M").time()
    if start <= end:
        return start <= now <= end
    return now >= start or now <= end


async def sync_global_custom_triggers(redis_client: Redis):
    all_static = list(ODESA_LOCS.keys()) + list(OUTSIDE_LOCS.keys())
    async with AsyncSessionLocal() as session:
        stmt = select(UserTrigger.trigger_word).where(UserTrigger.trigger_word.not_in(all_static)).distinct()
        res = await session.execute(stmt)
        triggers = res.scalars().all()
        if triggers:
            await redis_client.delete("global_custom_triggers")
            await redis_client.sadd("global_custom_triggers", *triggers)
            logger.info("Synchronized %d global custom triggers to memory cache.", len(triggers))


async def init_redis_consumer_group(redis_client: Redis):
    try:
        if await redis_client.exists(STREAM_NAME):
            groups = await redis_client.xinfo_groups(STREAM_NAME)
            if any(g['name'] == GROUP_NAME for g in groups):
                return
        await redis_client.xgroup_create(name=STREAM_NAME, groupname=GROUP_NAME, id="$", mkstream=True)
    except ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise e


async def monitor_dlq_backlog(redis_client: Redis):
    while is_running:
        try:
            if await redis_client.exists("dead_letter_queue"):
                dlq_depth = await redis_client.xlen("dead_letter_queue")
                DLQ_SIZE.set(dlq_depth)  # Export metric to Prometheus

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
                    await process_single_stream_payload(msg_id, raw_json, redis_client, broadcaster)
        except Exception as e:
            logger.error("Exception occurred inside PEL XAUTOCLAIM tracking loop: %s", e)


async def process_single_stream_payload(redis_msg_id: str, raw_json: str, redis_client: Redis,
                                        broadcaster: Broadcaster):
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

    if await redis_client.exists(dedup_key):
        await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
        return

    analysis = TextProcessor.parse_message(alert_data.raw_text)
    normalized_text = TextProcessor.normalize(alert_data.raw_text)

    global_custom = await redis_client.smembers("global_custom_triggers")
    matched_custom = [
        t for t in global_custom
        if re.search(rf"{_WORD_BOUNDARY}{re.escape(t)}{_WORD_BOUNDARY_END}", normalized_text)
    ]

    # Если сообщение пустое, выходим ДО старта метрики производительности
    if not analysis["categories"] and not analysis["locations"] and not matched_custom:
        is_fresh_lock = await redis_client.set(dedup_key, "1", nx=True, ex=300)
        if is_fresh_lock:
            await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
        return

    # Измеряем только реальную нагрузку: Хэширование, Кэш и БД
    with PROCESSING_TIME.time():
        sorted_locs = sorted(list(analysis["locations"]))
        sorted_cats = sorted(list(analysis["categories"]))
        sorted_custom = sorted(matched_custom)

        hash_payload = f"locs:{sorted_locs}|cats:{sorted_cats}|custom:{sorted_custom}"
        checksum = hashlib.md5(hash_payload.encode("utf-8")).hexdigest()

        cache_hash_key = f"cache:alert_targets:{checksum}"
        cached_targets = await redis_client.get(cache_hash_key)

        if cached_targets:
            user_ids_list = json.loads(cached_targets)
        else:
            all_static_keys = list(ODESA_LOCS.keys()) + list(OUTSIDE_LOCS.keys())
            async with AsyncSessionLocal() as session:
                try:
                    target_users = await get_users_by_trigger_and_category(
                        session=session, location_keys=analysis["locations"],
                        category_names=analysis["categories"], matched_custom_phrases=matched_custom,
                        all_static_keys=all_static_keys
                    )
                    user_ids_list = [u.user_id for u in target_users]

                    if not user_ids_list:
                        await redis_client.setex(cache_hash_key, 5, json.dumps([]))
                    else:
                        await redis_client.setex(cache_hash_key, 5, json.dumps(user_ids_list))
                except Exception as db_err:
                    retry_key = f"retry_count:{redis_msg_id}"
                    current_retries = await redis_client.incr(retry_key)
                    await redis_client.expire(retry_key, 3600)

                    if current_retries > 5:
                        logger.error("Task message ID %s dropped after exceeding retry limit.", redis_msg_id)
                        await redis_client.xadd("dead_letter_queue", {"payload": raw_json, "error": str(db_err)},
                                                maxlen=10000)
                        await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
                        await redis_client.delete(retry_key)
                    else:
                        logger.warning("Database transient exception on iteration %s/5.", current_retries)
                    return

    if not user_ids_list:
        is_fresh_lock = await redis_client.set(dedup_key, "1", nx=True, ex=300)
        if is_fresh_lock:
            await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
        return

    logger.info("Fresh broadcast alert payload verified. Forwarding dispatch streams.")
    quiet_mode = is_quiet_hours_active()
    alert_markup = build_acknowledge_keyboard()
    display_text = f"{ALERT_FIRST}\n\n🌙 <i>[Сповіщення надіслано у тихому режимі нічного часу]</i>" if quiet_mode else ALERT_FIRST

    for u_id in user_ids_list:
        broadcaster.fire_and_forget_message(u_id, display_text, reply_markup=alert_markup,
                                            disable_notification=quiet_mode)
        broadcaster.schedule_delayed_alerts(u_id, disable_notification=quiet_mode)

    is_fresh_lock = await redis_client.set(dedup_key, "1", nx=True, ex=300)
    if is_fresh_lock:
        await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
        await redis_client.delete(f"retry_count:{redis_msg_id}")
        ALERTS_PROCESSED.inc()


async def main():
    global is_running
    logger.info("Production background alert stream analysis subsystem initialization...")

    start_metrics_server(8000)

    bot = Bot(token=config.BOT_TOKEN)
    redis_client = Redis.from_url(config.REDIS_URL, decode_responses=True)

    await init_redis_consumer_group(redis_client)
    await sync_global_custom_triggers(redis_client)

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
        pass

    logger.info("Clearing outstanding internal consumer PEL backlogs...")
    backlog_data = await redis_client.xreadgroup(groupname=GROUP_NAME, consumername=CONSUMER_NAME,
                                                 streams={STREAM_NAME: "0"}, count=100, block=10)
    if backlog_data:
        for stream, messages in backlog_data:
            for redis_msg_id, payload in messages:
                raw_json = payload.get("payload")
                if raw_json:
                    await process_single_stream_payload(redis_msg_id, raw_json, redis_client, broadcaster)

    logger.info("Worker processing loop listening for target stream pipelines...")
    while is_running:
        try:
            streams_data = await redis_client.xreadgroup(groupname=GROUP_NAME, consumername=CONSUMER_NAME,
                                                         streams={STREAM_NAME: ">"}, count=1, block=1000)
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
            WORKER_ERRORS.inc()
            logger.error("Core engine execution loop error: %s", e, exc_info=True)
            await asyncio.sleep(2)

    # Graceful Teardown
    delayed_daemon.cancel()
    recovery_daemon.cancel()
    dlq_daemon.cancel()

    # CRITICAL: Await all in-flight outbound Telegram broadcasts before killing connections
    if broadcaster.background_tasks:
        logger.info("Graceful drain: Waiting for %d in-flight broadcast tasks to complete...",
                    len(broadcaster.background_tasks))
        await asyncio.gather(*broadcaster.background_tasks, return_exceptions=True)

    await redis_client.close()
    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())