import asyncio
import hashlib
import json
import logging
import os
import random
import re
import signal
import socket
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import aiohttp
from aiogram import Bot
from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy import select

from alert_bot_project.bot.keyboards.builders import build_acknowledge_keyboard
from alert_bot_project.core_shared.config import config
from alert_bot_project.core_shared.constants import ALERT_FIRST, KYIV_TZ
from alert_bot_project.core_shared.logging_config import setup_logging
from alert_bot_project.core_shared.metrics import (
    start_metrics_server, ALERTS_PROCESSED, PROCESSING_TIME, DLQ_SIZE, WORKER_ERRORS
)
from alert_bot_project.core_shared.schemas import AlertMessage
from alert_bot_project.core_shared.text_processor import TextProcessor
from alert_bot_project.database.crud import get_users_by_trigger_and_category
from alert_bot_project.database.engine import AsyncSessionLocal
from alert_bot_project.database.models import UserTrigger
from alert_bot_project.worker.broadcaster import Broadcaster

setup_logging("worker")
logger = logging.getLogger("worker.main")

LOCAL_TZ = ZoneInfo(KYIV_TZ)
STREAM_NAME = "alerts_stream"
GROUP_NAME = "workers_group"
CONSUMER_NAME = f"worker_{socket.gethostname()}_{os.getpid()}"

_WORD_BOUNDARY = r"(?<![\w])"
_WORD_BOUNDARY_END = r"(?![\w])"

NIGHT_START = datetime.strptime(f"{config.NIGHT_START_HOUR}:00", "%H:%M").time()
NIGHT_END = datetime.strptime(f"{config.NIGHT_END_HOUR}:00", "%H:%M").time()

shutdown_event = asyncio.Event()

RELEASE_LOCK_LUA = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
"""

release_lock_script = None


class CustomTriggerMatcher:
    def __init__(self):
        self.cache = {}
        self.last_hash = ""
        self._lock = asyncio.Lock()

    async def get_matches(self, normalized_text: str, global_custom: set) -> list:
        if not global_custom:
            return []

        # ✅ ФИКС: Хэширование и сборка строго внутри одной критической секции
        async with self._lock:
            current_hash = hashlib.md5("".join(sorted(global_custom)).encode()).hexdigest()
            if current_hash != self.last_hash:
                self.cache = {
                    str(t): re.compile(rf"{_WORD_BOUNDARY}{re.escape(str(t))}\w{{0,3}}{_WORD_BOUNDARY_END}")
                    for t in global_custom
                }
                self.last_hash = current_hash

            return [t for t, pattern in self.cache.items() if pattern.search(normalized_text)]


trigger_matcher = CustomTriggerMatcher()


def is_night_siren_interval_active() -> bool:
    now = datetime.now(LOCAL_TZ).time()
    if NIGHT_START > NIGHT_END:
        return now >= NIGHT_START or now <= NIGHT_END
    return NIGHT_START <= now <= NIGHT_END


async def check_official_air_alarm(redis_client: Redis) -> bool:
    cache_key = "official_alarm_status:odesa"
    try:
        cached = await redis_client.get(cache_key)
        if cached is not None:
            return cached == "1"

        alarm_active = getattr(config, 'FORCE_ALARM_MODE', True)

        # TODO: Заменить на реальный HTTP-запрос к API alerts.in.ua

        await redis_client.setex(cache_key, 10, "1" if alarm_active else "0")
        return alarm_active
    except Exception as e:
        logger.error("Ошибка при запросе к официальному API: %s", e)
        return True


async def cleanup_dead_consumers(redis_client: Redis):
    try:
        if not await redis_client.exists(STREAM_NAME):
            return
        consumers = await redis_client.xinfo_consumers(STREAM_NAME, GROUP_NAME)
        for c in consumers:
            if c.get("pending") == 0 and c.get("idle", 0) > 86400000:
                try:
                    await redis_client.xgroup_delconsumer(STREAM_NAME, GROUP_NAME, c["name"])
                    logger.info("Removed dead ghost consumer metadata from Redis: %s", c["name"])
                except Exception as inner_exc:
                    logger.error("Failed to delete specific consumer %s: %s", c["name"], inner_exc)
    except Exception as e:
        logger.error("General failure during dead consumers cleanup sweep: %s", e)


async def sync_global_custom_triggers(redis_client: Redis):
    from alert_bot_project.core_shared.constants import ODESA_LOCS, OUTSIDE_LOCS

    all_static = list(ODESA_LOCS.keys()) + list(OUTSIDE_LOCS.keys())
    async with AsyncSessionLocal() as session:
        stmt = select(UserTrigger.trigger_word).where(UserTrigger.trigger_word.not_in(all_static)).distinct()
        res = await session.execute(stmt)
        triggers = res.scalars().all()

        pipe = redis_client.pipeline()
        if triggers:
            pipe.delete("global_custom_triggers:new")
            pipe.sadd("global_custom_triggers:new", *triggers)
            pipe.rename("global_custom_triggers:new", "global_custom_triggers")
            await pipe.execute()
            logger.info("Synchronized %d global custom triggers via Pipeline.", len(triggers))
        else:
            await redis_client.delete("global_custom_triggers")


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
    while True:
        try:
            if await redis_client.exists("dead_letter_queue"):
                dlq_depth = await redis_client.xlen("dead_letter_queue")
                DLQ_SIZE.set(dlq_depth)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Error checking DLQ depth: %s", e)

        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=60.0)
            break
        except asyncio.TimeoutError:
            pass


async def auto_claim_pending_tasks(redis_client: Redis, broadcaster: Broadcaster):
    next_start_id = "0-0"
    while not shutdown_event.is_set():
        try:
            await asyncio.sleep(30 + random.uniform(0.0, 10.0))
            res = await redis_client.xautoclaim(
                name=STREAM_NAME, groupname=GROUP_NAME, consumername=CONSUMER_NAME,
                min_idle_time=60000, start_id=next_start_id, count=10
            )
            if res:
                next_start_id = res[0]
                if res[1]:
                    for msg_id, payload in res[1]:
                        raw_json = payload.get("payload")
                        if not raw_json:
                            await redis_client.xack(STREAM_NAME, GROUP_NAME, msg_id)
                            continue
                        await process_single_stream_payload(msg_id, raw_json, redis_client, broadcaster)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("XAUTOCLAIM tracking loop error: %s", e)


async def process_single_stream_payload(redis_msg_id: str, raw_json: str, redis_client: Redis,
                                        broadcaster: Broadcaster):
    try:
        alert_data = AlertMessage.model_validate_json(raw_json)
    except Exception as err:
        logger.warning("Dropped corrupted payload: %s", err)
        await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
        return

    if (datetime.now(timezone.utc) - alert_data.timestamp).total_seconds() > 600:
        await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
        return

    dedup_key = f"processed_msg:{alert_data.chat_id}:{alert_data.message_id}"
    acquired = await redis_client.set(dedup_key, "1", ex=600, nx=True)

    if not acquired:
        await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
        return

    with PROCESSING_TIME.time():
        analysis = TextProcessor.parse_message(alert_data.raw_text)
        normalized_text = TextProcessor.normalize(alert_data.raw_text)

        global_custom = await redis_client.smembers("global_custom_triggers")
        matched_custom = await trigger_matcher.get_matches(normalized_text, global_custom)

        official_alarm_active = await check_official_air_alarm(redis_client)

        if not official_alarm_active:
            if not analysis["categories"] or (not analysis["locations"] and not matched_custom):
                await redis_client.delete(dedup_key)
                await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
                return
        else:
            if not analysis["locations"] and not matched_custom:
                await redis_client.delete(dedup_key)
                await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
                return

        if not analysis["categories"]:
            analysis["categories"] = {"Мопеди", "Ракети"}

        trigger_words = set(analysis["locations"])
        if matched_custom:
            trigger_words.update(matched_custom)

        sorted_cats = sorted(list(analysis["categories"]))
        sorted_triggers = sorted(list(trigger_words))

        hash_payload = f"cats:{sorted_cats}|triggers:{sorted_triggers}"
        checksum = hashlib.md5(hash_payload.encode("utf-8")).hexdigest()

        cache_hash_key = f"cache:alert_targets:{checksum}"
        lock_key = f"lock:cache_build:{checksum}"
        lock_token = str(uuid.uuid4())
        user_ids_list = None
        lock_acquired = False

        for _ in range(15):
            cached_targets = await redis_client.get(cache_hash_key)
            if cached_targets:
                user_ids_list = json.loads(cached_targets)
                break

            if await redis_client.set(lock_key, lock_token, ex=4, nx=True):
                lock_acquired = True
                break
            await asyncio.sleep(0.1)

        if lock_acquired:
            try:
                async with AsyncSessionLocal() as session:
                    target_users = await get_users_by_trigger_and_category(
                        session=session,
                        category_names=analysis["categories"],
                        trigger_words=trigger_words
                    )
                    user_ids_list = [u.user_id for u in target_users]
                    await redis_client.setex(cache_hash_key, 5, json.dumps(user_ids_list))
            except Exception as db_err:
                retry_key = f"retry_count:{redis_msg_id}"
                current_retries = await redis_client.incr(retry_key)
                await redis_client.expire(retry_key, 3600)

                if current_retries > 5:
                    logger.error("Task message ID %s dropped to DLQ.", redis_msg_id)
                    await redis_client.xadd("dead_letter_queue", {"payload": raw_json, "error": str(db_err)},
                                            maxlen=10000)
                    await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
                    await redis_client.delete(retry_key)
                else:
                    await redis_client.delete(dedup_key)
                return
            finally:
                await release_lock_script(keys=[lock_key], args=[lock_token])
        else:
            if user_ids_list is None:
                async with AsyncSessionLocal() as session:
                    try:
                        target_users = await get_users_by_trigger_and_category(
                            session=session,
                            category_names=analysis["categories"],
                            trigger_words=trigger_words
                        )
                        user_ids_list = [u.user_id for u in target_users]
                    except Exception as fallback_err:
                        logger.error("Critical failure during DB fallback: %s", fallback_err)
                        await redis_client.delete(dedup_key)
                        return

        if not user_ids_list:
            await redis_client.delete(dedup_key)
            await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
            return

        mute_keys = [f"user_mute:{u}" for u in user_ids_list]
        mutes = await redis_client.mget(mute_keys)
        active_users = [u for u, m in zip(user_ids_list, mutes) if not m]

        if not active_users:
            await redis_client.delete(dedup_key)
            await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
            return

        if not is_night_siren_interval_active():
            await redis_client.delete(dedup_key)
            await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
            return

        alert_markup = build_acknowledge_keyboard()
        display_text = ALERT_FIRST

        for u_id in active_users:
            broadcaster.fire_and_forget_message(u_id, display_text, reply_markup=alert_markup,
                                                disable_notification=False)
            broadcaster.schedule_delayed_alerts(u_id, disable_notification=False)

        await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
        await redis_client.delete(f"retry_count:{redis_msg_id}")

    ALERTS_PROCESSED.inc()


async def main():
    logger.info("Production background alert stream analysis subsystem initialization...")
    start_metrics_server(config.METRICS_PORT_WORKER)

    bot = Bot(token=config.BOT_TOKEN)
    redis_client = Redis.from_url(config.REDIS_URL, decode_responses=True)

    global release_lock_script
    release_lock_script = redis_client.register_script(RELEASE_LOCK_LUA)

    await init_redis_consumer_group(redis_client)
    await cleanup_dead_consumers(redis_client)
    await sync_global_custom_triggers(redis_client)

    broadcaster = Broadcaster(bot, redis_client)
    await broadcaster.start()

    delayed_daemon = asyncio.create_task(broadcaster.process_delayed_alerts())
    recovery_daemon = asyncio.create_task(auto_claim_pending_tasks(redis_client, broadcaster))
    dlq_daemon = asyncio.create_task(monitor_dlq_backlog(redis_client))

    def _signal_handler():
        logger.info("Shutdown signal received.")
        shutdown_event.set()

    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _signal_handler)
    except NotImplementedError:
        pass

    logger.info("Draining outstanding internal consumer PEL backlogs completely...")
    while True:
        try:
            backlog_data = await redis_client.xreadgroup(
                groupname=GROUP_NAME, consumername=CONSUMER_NAME,
                streams={STREAM_NAME: "0"}, count=100, block=10
            )
            if not backlog_data or not backlog_data[0][1]:
                break

            for stream, messages in backlog_data:
                for redis_msg_id, payload in messages:
                    raw_json = payload.get("payload")
                    if raw_json:
                        await process_single_stream_payload(redis_msg_id, raw_json, redis_client, broadcaster)
                    else:
                        await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
        except Exception as e:
            logger.error("Error during initial PEL drainage sweep: %s", e)
            break

    while not shutdown_event.is_set():
        try:
            streams_data = await redis_client.xreadgroup(groupname=GROUP_NAME, consumername=CONSUMER_NAME,
                                                         streams={STREAM_NAME: ">"}, count=5, block=1000)
            if not streams_data:
                continue
            for stream, messages in streams_data:
                for redis_msg_id, payload in messages:
                    raw_json = payload.get("payload")
                    if raw_json:
                        await process_single_stream_payload(redis_msg_id, raw_json, redis_client, broadcaster)
                    else:
                        await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
        except ResponseError as e:
            if "NOGROUP" in str(e):
                logger.warning("Consumer group missing. Re-initializing...")
                await init_redis_consumer_group(redis_client)
                await asyncio.sleep(1)
            else:
                WORKER_ERRORS.inc()
                logger.error("Core engine execution loop ResponseError: %s", str(e))
                await asyncio.sleep(2)
        except Exception as e:
            WORKER_ERRORS.inc()
            logger.error("Core engine execution loop error: %s", str(e))
            await asyncio.sleep(2)

    logger.info("Draining background tasks...")
    delayed_daemon.cancel()
    recovery_daemon.cancel()
    dlq_daemon.cancel()

    await asyncio.gather(delayed_daemon, recovery_daemon, dlq_daemon, return_exceptions=True)
    await broadcaster.close()

    try:
        await redis_client.xgroup_delconsumer(STREAM_NAME, GROUP_NAME, CONSUMER_NAME)
    except Exception:
        pass

    await redis_client.close()
    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())