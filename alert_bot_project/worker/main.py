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
from typing import Any, Awaitable, Callable, Optional
from zoneinfo import ZoneInfo

from aiogram import Bot
from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError, ResponseError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

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
from alert_bot_project.services.ukrainealarm import AlarmStatePoller
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

REDIS_CUSTOM_TRIGGERS_KEY = "global_custom_triggers"
REDIS_NEW_TRIGGERS_KEY = "global_custom_triggers:new"
OFFICIAL_ALARM_KEY = "official_alarm_status:odesa"

shutdown_event = asyncio.Event()

RELEASE_LOCK_LUA = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
"""

# Тип скрипта звільнення розподіленого локу. Передається явно через параметри
# функцій замість мутабельного module-level глобального стану, який раніше
# ініціалізувався як None і перезаписувався лише всередині main() — статичний
# аналізатор (і потенційно виклик до старту main()) міг побачити None замість
# справжнього скрипта ("release_lock_script is not callable").
ReleaseLockScript = Callable[..., Awaitable[Any]]


class CustomTriggerMatcher:
    """
    Тримає ОДИН прекомпільований regex на весь глобальний пул кастомних фраз
    замість окремого re.compile на кожну фразу. Знижує вартість перевірки
    одного повідомлення з O(N окремих .search()) до одного проходу regex-двигуна —
    критично при рості пулу фраз (anti-DoS).
    """

    def __init__(self) -> None:
        self._pattern: Optional[re.Pattern[str]] = None
        self._phrases_by_group: dict[str, str] = {}
        self.last_hash = ""
        self._lock = asyncio.Lock()

    async def get_matches(self, normalized_text: str, global_custom: set[str]) -> list[str]:
        if not global_custom:
            return []

        async with self._lock:
            # noinspection PyTypeChecker
            current_hash = hashlib.md5(
                "".join(sorted(global_custom)).encode(), usedforsecurity=False
            ).hexdigest()
            if current_hash != self.last_hash:
                self._phrases_by_group = {f"g{i}": str(t) for i, t in enumerate(global_custom)}
                alternation = "|".join(
                    f"(?P<{group}>{re.escape(phrase)}\\w{{0,3}})"
                    for group, phrase in self._phrases_by_group.items()
                )
                self._pattern = re.compile(rf"{_WORD_BOUNDARY}(?:{alternation}){_WORD_BOUNDARY_END}")
                self.last_hash = current_hash

            if not self._pattern:
                return []

            matches: set[str] = set()
            for m in self._pattern.finditer(normalized_text):
                if m.lastgroup:
                    matches.add(self._phrases_by_group[m.lastgroup])
            return list(matches)


trigger_matcher = CustomTriggerMatcher()


def is_night_siren_interval_active() -> bool:
    now = datetime.now(LOCAL_TZ).time()
    if NIGHT_START > NIGHT_END:
        return now >= NIGHT_START or now <= NIGHT_END
    return NIGHT_START <= now <= NIGHT_END


async def check_official_air_alarm(redis_client: Redis) -> bool:
    """
    Читає стан офіційної тривоги, який пише фоновий AlarmStatePoller
    (services.ukrainealarm.AlarmStatePoller). Ключ має TTL: якщо поллер
    впав і ключ протух, використовуємо fail-open/fail-close режим за
    конфігом OFFICIAL_ALARM_FAILSAFE.
    """
    try:
        cached = await redis_client.get(OFFICIAL_ALARM_KEY)
        if cached is not None:
            return cached == "1"
        return config.OFFICIAL_ALARM_FAILSAFE
    except RedisError:
        logger.exception("Ошибка при чтении статуса официальной тревоги из Redis")
        return config.OFFICIAL_ALARM_FAILSAFE


async def _remove_dead_consumer(redis_client: Redis, consumer_name: str) -> None:
    try:
        await redis_client.xgroup_delconsumer(STREAM_NAME, GROUP_NAME, consumer_name)
        logger.info("Removed dead ghost consumer metadata from Redis: %s", consumer_name)
    except RedisError:
        logger.exception("Failed to delete specific consumer %s", consumer_name)


async def cleanup_dead_consumers(redis_client: Redis) -> None:
    try:
        if not await redis_client.exists(STREAM_NAME):
            return
        consumers = await redis_client.xinfo_consumers(STREAM_NAME, GROUP_NAME)
        for c in consumers:
            if c.get("pending") == 0 and c.get("idle", 0) > 86400000:
                await _remove_dead_consumer(redis_client, c["name"])
    except RedisError:
        logger.exception("General failure during dead consumers cleanup sweep")


async def sync_global_custom_triggers(redis_client: Redis) -> None:
    from alert_bot_project.core_shared.constants import ODESA_LOCS, OUTSIDE_LOCS

    all_static = list(ODESA_LOCS.keys()) + list(OUTSIDE_LOCS.keys())
    async with AsyncSessionLocal() as session:
        stmt = select(UserTrigger.trigger_word).where(UserTrigger.trigger_word.not_in(all_static)).distinct()
        res = await session.execute(stmt)
        triggers = res.scalars().all()

        if not triggers:
            await redis_client.delete(REDIS_CUSTOM_TRIGGERS_KEY)
            return

        # redis.asyncio Pipeline-команди — це корутини, їх ОБОВ'ЯЗКОВО треба await-ити
        # навіть у буферизованому режимі. Без await вони ніколи не потрапляють у
        # command_stack, і pipe.execute() виконує 0 команд — раніше delete/sadd/rename
        # викликались без await і мовчки нічого не робили (глобальний пул кастомних
        # фраз ніколи не перебудовувався при старті воркера).
        pipe = redis_client.pipeline()
        pipe.delete(REDIS_NEW_TRIGGERS_KEY)
        pipe.sadd(REDIS_NEW_TRIGGERS_KEY, *triggers)
        pipe.rename(REDIS_NEW_TRIGGERS_KEY, REDIS_CUSTOM_TRIGGERS_KEY)
        await pipe.execute()
        logger.info("Synchronized %d global custom triggers via Pipeline.", len(triggers))


async def init_redis_consumer_group(redis_client: Redis) -> None:
    try:
        if await redis_client.exists(STREAM_NAME):
            groups = await redis_client.xinfo_groups(STREAM_NAME)
            if any(g["name"] == GROUP_NAME for g in groups):
                return
        await redis_client.xgroup_create(name=STREAM_NAME, groupname=GROUP_NAME, id="$", mkstream=True)
    except ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise


async def monitor_dlq_backlog(redis_client: Redis) -> None:
    while not shutdown_event.is_set():
        try:
            if await redis_client.exists("dead_letter_queue"):
                dlq_depth = await redis_client.xlen("dead_letter_queue")
                DLQ_SIZE.set(dlq_depth)
        except asyncio.CancelledError:
            raise
        except RedisError:
            logger.exception("Error checking DLQ depth")

        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=60.0)
        except asyncio.TimeoutError:
            pass


# =========================================================================
#  РЕЗОЛВІНГ ОДЕРЖУВАЧІВ (декомпозовано з єдиної функції складністю 51 -> дрібні шматки)
# =========================================================================

async def _try_get_cached_targets(redis_client: Redis, cache_hash_key: str) -> Optional[list[int]]:
    cached = await redis_client.get(cache_hash_key)
    if cached:
        return json.loads(cached)
    return None


async def _acquire_cache_build_lock(redis_client: Redis, lock_key: str, lock_token: str) -> bool:
    return bool(await redis_client.set(lock_key, lock_token, ex=4, nx=True))


async def _fetch_targets_from_db(categories: set[str], trigger_words: set[str]) -> list[int]:
    async with AsyncSessionLocal() as session:
        target_users = await get_users_by_trigger_and_category(
            session=session, category_names=categories, trigger_words=trigger_words
        )
        return [u.user_id for u in target_users]


async def _handle_db_failure(
    redis_client: Redis, redis_msg_id: str, raw_json: str, db_err: Exception
) -> None:
    """Рахує ретраї конкретного повідомлення і зносить його в DLQ після 5 невдалих спроб."""
    retry_key = f"retry_count:{redis_msg_id}"
    current_retries = await redis_client.incr(retry_key)
    await redis_client.expire(retry_key, 3600)

    if current_retries > 5:
        logger.error("Task message ID %s dropped to DLQ.", redis_msg_id)
        await redis_client.xadd("dead_letter_queue", {"payload": raw_json, "error": str(db_err)}, maxlen=10000)
        await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
        await redis_client.delete(retry_key)


async def _build_and_cache_targets(
    redis_client: Redis,
    cache_hash_key: str,
    lock_key: str,
    lock_token: str,
    categories: set[str],
    trigger_words: set[str],
    redis_msg_id: str,
    raw_json: str,
    release_lock_script: ReleaseLockScript,
) -> list[int]:
    try:
        user_ids_list = await _fetch_targets_from_db(categories, trigger_words)
        await redis_client.setex(cache_hash_key, 5, json.dumps(user_ids_list))
        return user_ids_list
    except SQLAlchemyError as db_err:
        await _handle_db_failure(redis_client, redis_msg_id, raw_json, db_err)
        raise
    finally:
        await release_lock_script(keys=[lock_key], args=[lock_token])


async def _resolve_target_users(
    redis_client: Redis,
    checksum: str,
    categories: set[str],
    trigger_words: set[str],
    redis_msg_id: str,
    raw_json: str,
    release_lock_script: ReleaseLockScript,
) -> list[int]:
    """
    Резолвить список user_id-отримувачів для конкретної комбінації категорій/тригерів,
    з коротким Redis-кешем (5с) під розподіленим локом, щоб уникнути дублюючих
    важких SELECT-ів у БД при сплеску однакових повідомлень.
    """
    cache_hash_key = f"cache:alert_targets:{checksum}"
    lock_key = f"lock:cache_build:{checksum}"
    lock_token = str(uuid.uuid4())

    for _ in range(15):
        cached_targets = await _try_get_cached_targets(redis_client, cache_hash_key)
        if cached_targets is not None:
            return cached_targets

        if await _acquire_cache_build_lock(redis_client, lock_key, lock_token):
            return await _build_and_cache_targets(
                redis_client, cache_hash_key, lock_key, lock_token,
                categories, trigger_words, redis_msg_id, raw_json, release_lock_script,
            )

        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=0.1)
        except asyncio.TimeoutError:
            pass

    # Ліміт спроб вичерпано, ніхто так і не звільнив лок вчасно —
    # читаємо з БД напряму без кешування (як і в початковій реалізації).
    return await _fetch_targets_from_db(categories, trigger_words)


# =========================================================================
#  ОБРОБКА ОДНОГО ПОВІДОМЛЕННЯ (декомпозовано з складністю 51 -> дрібні шматки)
# =========================================================================

async def _validate_payload(
    redis_client: Redis, redis_msg_id: str, raw_json: str
) -> Optional[AlertMessage]:
    try:
        alert_data = AlertMessage.model_validate_json(raw_json)
    except (ValidationError, ValueError):
        logger.exception("Dropped corrupted payload")
        await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
        return None

    if (datetime.now(timezone.utc) - alert_data.timestamp).total_seconds() > 600:
        await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
        return None

    return alert_data


async def _acquire_dedup_lock(redis_client: Redis, alert_data: AlertMessage) -> Optional[str]:
    """Повертає ключ дедуплікації, якщо повідомлення ще не оброблялося, інакше None."""
    dedup_key = f"processed_msg:{alert_data.chat_id}:{alert_data.message_id}"
    acquired = await redis_client.set(dedup_key, "1", ex=600, nx=True)
    return dedup_key if acquired else None


def _resolve_trigger_words(
    analysis: dict[str, set[str]], matched_custom: list[str], official_alarm_active: bool
) -> Optional[set[str]]:
    """
    Вирішує, чи повідомлення варте розсилки, і повертає фінальний набір
    trigger_words для пошуку одержувачів, або None — якщо розсилку треба
    пропустити. Порядок перевірок ідентичний початковій реалізації воркера.

    Правила:
      * Без офіційної тривоги: потрібна і категорія загрози, І (локація або кастом-фраза).
      * З офіційною тривогою: локації/кастом-фрази достатньо самої по собі;
        якщо їх немає, але є розпізнана категорія загрози — ескалюємо на
        загальноміських підписників (ключ "city").
    """
    if not official_alarm_active and (
        not analysis["categories"] or (not analysis["locations"] and not matched_custom)
    ):
        return None

    if official_alarm_active and not analysis["locations"] and not matched_custom:
        if analysis["categories"]:
            return {"city"}
        return None

    trigger_words = set(analysis["locations"])
    if matched_custom:
        trigger_words.update(matched_custom)
    return trigger_words


async def _filter_muted_users(redis_client: Redis, user_ids: list[int]) -> list[int]:
    mute_keys = [f"user_mute:{u}" for u in user_ids]
    mutes = await redis_client.mget(mute_keys)
    return [u for u, m in zip(user_ids, mutes) if not m]


def _dispatch_alerts(broadcaster: Broadcaster, active_users: list[int]) -> None:
    alert_markup = build_acknowledge_keyboard()
    for u_id in active_users:
        broadcaster.fire_and_forget_message(u_id, ALERT_FIRST, reply_markup=alert_markup, disable_notification=False)
        broadcaster.schedule_delayed_alerts(u_id, disable_notification=False)


async def process_single_stream_payload(
    redis_msg_id: str,
    raw_json: str,
    redis_client: Redis,
    broadcaster: Broadcaster,
    release_lock_script: ReleaseLockScript,
) -> None:
    alert_data = await _validate_payload(redis_client, redis_msg_id, raw_json)
    if alert_data is None:
        return

    dedup_key = await _acquire_dedup_lock(redis_client, alert_data)
    if dedup_key is None:
        await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
        return

    with PROCESSING_TIME.time():
        analysis = TextProcessor.parse_message(alert_data.raw_text)
        normalized_text = TextProcessor.normalize(alert_data.raw_text)

        global_custom = await redis_client.smembers(REDIS_CUSTOM_TRIGGERS_KEY)
        matched_custom = await trigger_matcher.get_matches(normalized_text, global_custom)
        official_alarm_active = await check_official_air_alarm(redis_client)

        trigger_words = _resolve_trigger_words(analysis, matched_custom, official_alarm_active)
        if trigger_words is None:
            await redis_client.delete(dedup_key)
            await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
            return

        if not analysis["categories"]:
            analysis["categories"] = {"Мопеди", "Ракети"}

        sorted_cats = sorted(analysis["categories"])
        sorted_triggers = sorted(trigger_words)
        # noinspection PyTypeChecker
        checksum = hashlib.md5(
            f"cats:{sorted_cats}|triggers:{sorted_triggers}".encode("utf-8"), usedforsecurity=False
        ).hexdigest()

        try:
            user_ids_list = await _resolve_target_users(
                redis_client, checksum, analysis["categories"], trigger_words,
                redis_msg_id, raw_json, release_lock_script,
            )
        except SQLAlchemyError:
            await redis_client.delete(dedup_key)
            return

        if not user_ids_list:
            await redis_client.delete(dedup_key)
            await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
            return

        active_users = await _filter_muted_users(redis_client, user_ids_list)
        if not active_users or not is_night_siren_interval_active():
            await redis_client.delete(dedup_key)
            await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
            return

        _dispatch_alerts(broadcaster, active_users)

        await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
        await redis_client.delete(f"retry_count:{redis_msg_id}")

    ALERTS_PROCESSED.inc()


async def auto_claim_pending_tasks(
    redis_client: Redis, broadcaster: Broadcaster, release_lock_script: ReleaseLockScript
) -> None:
    next_start_id = "0-0"
    while not shutdown_event.is_set():
        try:
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=30 + random.uniform(0.0, 10.0))
            except asyncio.TimeoutError:
                pass

            res = await redis_client.xautoclaim(
                name=STREAM_NAME, groupname=GROUP_NAME, consumername=CONSUMER_NAME,
                min_idle_time=60000, start_id=next_start_id, count=10
            )
            if res:
                next_start_id = res[0]
                if res[1]:
                    for msg_id, payload in res[1]:
                        raw_json = payload.get("payload")
                        if raw_json:
                            await process_single_stream_payload(
                                msg_id, raw_json, redis_client, broadcaster, release_lock_script
                            )
                        else:
                            await redis_client.xack(STREAM_NAME, GROUP_NAME, msg_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Верхньорівневий демон-цикл навмисно ловить будь-яку помилку:
            # одиничний збій ітерації не повинен вбивати відновлення "завислих" повідомлень.
            logger.exception("XAUTOCLAIM tracking loop error")


# =========================================================================
#  ГОЛОВНИЙ ЦИКЛ (декомпозовано з складністю 22 -> дрібні шматки)
# =========================================================================

async def _drain_pending_backlog(
    redis_client: Redis, broadcaster: Broadcaster, release_lock_script: ReleaseLockScript
) -> None:
    """Одноразово вичитує весь PEL (Pending Entries List) цього консюмера при старті."""
    logger.info("Draining outstanding internal consumer PEL backlogs completely...")
    while True:
        try:
            backlog_data = await redis_client.xreadgroup(
                groupname=GROUP_NAME, consumername=CONSUMER_NAME,
                streams={STREAM_NAME: "0"}, count=100, block=10
            )
            if not backlog_data or not backlog_data[0][1]:
                break

            for _stream, messages in backlog_data:
                for redis_msg_id, payload in messages:
                    raw_json = payload.get("payload")
                    if raw_json:
                        await process_single_stream_payload(
                            redis_msg_id, raw_json, redis_client, broadcaster, release_lock_script
                        )
                    else:
                        await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
        except Exception:
            logger.exception("Error during initial PEL drainage sweep")
            break


async def _handle_stream_response_error(redis_client: Redis, error: ResponseError) -> None:
    if "NOGROUP" in str(error):
        logger.warning("Consumer group missing. Re-initializing...")
        await init_redis_consumer_group(redis_client)
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            pass
    else:
        WORKER_ERRORS.inc()
        logger.exception("Core engine execution loop ResponseError")
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pass


async def _consume_loop(
    redis_client: Redis, broadcaster: Broadcaster, release_lock_script: ReleaseLockScript
) -> None:
    """Основний нескінченний цикл читання нових повідомлень зі стріму (">")."""
    while not shutdown_event.is_set():
        try:
            streams_data = await redis_client.xreadgroup(
                groupname=GROUP_NAME, consumername=CONSUMER_NAME,
                streams={STREAM_NAME: ">"}, count=5, block=1000
            )
            if not streams_data:
                continue
            for _stream, messages in streams_data:
                for redis_msg_id, payload in messages:
                    raw_json = payload.get("payload")
                    if raw_json:
                        await process_single_stream_payload(
                            redis_msg_id, raw_json, redis_client, broadcaster, release_lock_script
                        )
                    else:
                        await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
        except ResponseError as e:
            await _handle_stream_response_error(redis_client, e)
        except Exception:
            # Верхньорівневий цикл споживання навмисно ловить будь-яку помилку:
            # одиничний збій ітерації не повинен вбивати весь воркер-процес.
            WORKER_ERRORS.inc()
            logger.exception("Core engine execution loop error")
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass


async def main() -> None:
    logger.info("Production background alert stream analysis subsystem initialization...")
    start_metrics_server(config.METRICS_PORT_WORKER)

    bot = Bot(token=config.BOT_TOKEN)
    redis_client = Redis.from_url(config.REDIS_URL, decode_responses=True)

    release_lock_script: ReleaseLockScript = redis_client.register_script(RELEASE_LOCK_LUA)

    await init_redis_consumer_group(redis_client)
    await cleanup_dead_consumers(redis_client)
    await sync_global_custom_triggers(redis_client)

    broadcaster = Broadcaster(bot, redis_client)
    broadcaster.start()

    delayed_daemon = asyncio.create_task(broadcaster.process_delayed_alerts())
    recovery_daemon = asyncio.create_task(
        auto_claim_pending_tasks(redis_client, broadcaster, release_lock_script)
    )
    dlq_daemon = asyncio.create_task(monitor_dlq_backlog(redis_client))

    alarm_poller = AlarmStatePoller(redis_client)
    alarm_daemon = asyncio.create_task(alarm_poller.run(shutdown_event))

    def _signal_handler(*_args: object) -> None:
        logger.info("Shutdown signal received.")
        shutdown_event.set()

    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _signal_handler)
    except NotImplementedError:
        pass

    await _drain_pending_backlog(redis_client, broadcaster, release_lock_script)
    await _consume_loop(redis_client, broadcaster, release_lock_script)

    logger.info("Draining background tasks...")
    delayed_daemon.cancel()
    recovery_daemon.cancel()
    dlq_daemon.cancel()
    alarm_daemon.cancel()

    await asyncio.gather(
        delayed_daemon, recovery_daemon, dlq_daemon, alarm_daemon, return_exceptions=True
    )
    await broadcaster.close()

    try:
        await redis_client.xgroup_delconsumer(STREAM_NAME, GROUP_NAME, CONSUMER_NAME)
    except RedisError:
        pass

    await redis_client.close()
    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())