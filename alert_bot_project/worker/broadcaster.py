"""Durable per-recipient delivery of first and delayed Telegram alerts."""

import asyncio
import hashlib
import hmac
import html
import json
import logging
import os
import socket
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.types import InlineKeyboardMarkup
from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from alert_bot_project.bot.keyboards.builders import build_acknowledge_keyboard
from alert_bot_project.core_shared.config import config
from alert_bot_project.core_shared.constants import (
    ALERT_DELAY_1,
    ALERT_DELAY_2,
    ALERT_FIRST,
    ALERT_SECOND,
    ALERT_THIRD,
    KYIV_TZ,
)
from alert_bot_project.core_shared.metrics import (
    DELIVERY_LATENCY,
    DELIVERY_OUTCOMES,
    DELIVERY_PERMANENT_FAILURES,
    RECIPIENTS_SELECTED,
)
from alert_bot_project.database.activity import record_activity
from alert_bot_project.database.engine import AsyncSessionLocal
from alert_bot_project.database.models import UserSettings
from alert_bot_project.worker.rate_limit import TelegramRateLimiter

logger = logging.getLogger("worker.broadcaster")

# The marker, first delivery job and both delayed jobs are one Redis operation.
# Replaying a partially-fanned-out source post cannot duplicate recipients.
ENQUEUE_ALERT_LUA = """
if redis.call('EXISTS', KEYS[1]) == 0 then
    redis.call('XADD', KEYS[2], '*', 'payload', ARGV[1])
    if ARGV[6] == '0' then
        redis.call('ZADD', KEYS[3], ARGV[2], ARGV[3], ARGV[4], ARGV[5])
    end
    redis.call('SET', KEYS[1], '1', 'EX', 604800)
    return 1
end
return 0
"""

# Transfer exactly the returned due members to the durable stream, atomically.
# Moving directly avoids the crash window between pop and a Python XADD call.
POP_MATURE_TASKS_LUA = """
local elements = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1], 'LIMIT', 0, ARGV[2])
for _, element in ipairs(elements) do
    redis.call('XADD', KEYS[2], '*', 'payload', element)
    redis.call('ZREM', KEYS[1], element)
end
return #elements
"""


@dataclass(frozen=True)
class DeliveryOutcome:
    status: str
    reason: str = ""


class Broadcaster:
    delivery_stream_name = "delivery_stream"
    delivery_group_name = "delivery_workers"
    delivery_dlq_name = "delivery_dead_letter_queue"

    def __init__(self, bot: Bot, redis_client: Redis, workers_count: int = 15):
        self.bot = bot
        self.redis = redis_client
        self.workers_count = workers_count
        self.delayed_queue_key = "delayed_alerts_queue"
        self._salt = config.API_HASH.encode()
        self._night_start = datetime.strptime(f"{config.NIGHT_START_HOUR}:00", "%H:%M").time()
        self._night_end = datetime.strptime(f"{config.NIGHT_END_HOUR}:00", "%H:%M").time()
        self._tz = ZoneInfo(KYIV_TZ)
        self.rate_limiter = TelegramRateLimiter(redis_client)

    def _hash_id(self, chat_id: int) -> str:
        return hmac.new(self._salt, str(chat_id).encode(), hashlib.sha256).hexdigest()[:16]

    def _is_night(self) -> bool:
        now = datetime.now(self._tz).time()
        if self._night_start > self._night_end:
            return now >= self._night_start or now <= self._night_end
        return self._night_start <= now <= self._night_end

    async def _db_mute_active(self, chat_id: int) -> bool:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(UserSettings.muted_until).where(UserSettings.user_id == chat_id))
            muted_until = result.scalar_one_or_none()
            return bool(muted_until is not None and muted_until > datetime.now(UTC))

    async def _record_delivered(self, chat_id: int) -> None:
        try:
            async with AsyncSessionLocal() as session:
                await record_activity(session, chat_id, delivered=True)
                await session.commit()
        except SQLAlchemyError:
            logger.exception("Delivery activity aggregate failed after Telegram send")

    async def ensure_delivery_group(self) -> None:
        try:
            await self.redis.xgroup_create(self.delivery_stream_name, self.delivery_group_name, id="0-0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def enqueue_alert(
        self,
        source_chat_id: int,
        source_message_id: int,
        chat_id: int,
        *,
        stale: bool = False,
        source_timestamp: datetime | None = None,
        categories: set[str] | None = None,
        locations: set[str] | None = None,
    ) -> bool:
        """Persist all three stages once per source event and recipient."""
        identity = f"{source_chat_id}:{source_message_id}:{chat_id}"
        first_text = (
            "⚠️ Затримане повідомлення про загрозу. Воно може бути неактуальним; "
            "перевірте поточний стан в офіційних джерелах."
            if stale
            else ALERT_FIRST
        )
        context = [f"Джерело: канал {source_chat_id}, повідомлення {source_message_id}."]
        if source_timestamp is not None:
            context.append(f"Час отримання: {source_timestamp.astimezone(self._tz):%Y-%m-%d %H:%M} (Київ).")
        if categories:
            context.append("Категорія: " + html.escape(", ".join(sorted(categories))) + ".")
        if locations:
            context.append("Згадана локація: " + html.escape(", ".join(sorted(locations))) + ".")
        first_text += "\n" + "\n".join(context) + "\nПідтвердіть стан в офіційних джерелах."
        generation = await self.redis.get(f"privacy:generation:{chat_id}") or "0"
        common = {
            "event_id": identity,
            "chat_id": chat_id,
            "source_chat_id": source_chat_id,
            "source_message_id": source_message_id,
            "source_timestamp": source_timestamp.isoformat() if source_timestamp else None,
            "recipient_generation": generation,
        }
        first = json.dumps({**common, "step": 1, "text": first_text, "silent": stale})
        second = json.dumps({**common, "step": 2, "text": ALERT_SECOND, "silent": False})
        third = json.dumps({**common, "step": 3, "text": ALERT_THIRD, "silent": False})
        now = int(time.time())
        script = self.redis.register_script(ENQUEUE_ALERT_LUA)
        added = await script(
            keys=[f"delivery:enqueued:{identity}", self.delivery_stream_name, self.delayed_queue_key],
            args=[first, now + ALERT_DELAY_1, second, now + ALERT_DELAY_1 + ALERT_DELAY_2, third, int(stale)],
        )
        if added:
            RECIPIENTS_SELECTED.inc()
        return bool(added)

    async def send_single_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
        disable_notification: bool = False,
        repeat: bool = False,
    ) -> DeliveryOutcome:
        peer_hash = self._hash_id(chat_id)
        await self.rate_limiter.acquire(chat_id, repeat=repeat)
        try:
            await self.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                reply_markup=reply_markup,
                disable_notification=disable_notification,
            )
            return DeliveryOutcome("sent")
        except TelegramRetryAfter as exc:
            await self.rate_limiter.pause(exc.retry_after)
            logger.warning("Telegram 429 for peer %s; retry after %s", peer_hash, exc.retry_after)
            return DeliveryOutcome("retry", "telegram_429")
        except TelegramForbiddenError:
            logger.warning("Telegram recipient blocked bot for peer %s", peer_hash)
            return DeliveryOutcome("blocked", "telegram_forbidden")
        except TelegramBadRequest:
            logger.warning("Telegram rejected message format for peer %s", peer_hash)
            return DeliveryOutcome("permanent", "telegram_bad_request")
        except TelegramServerError:
            logger.warning("Telegram server failure for peer %s", peer_hash)
            return DeliveryOutcome("retry", "telegram_5xx")
        except TelegramAPIError:
            logger.exception("Telegram API error for peer %s", peer_hash)
            return DeliveryOutcome("retry", "telegram_api")
        except Exception:
            logger.exception("Telegram transport error for peer %s", peer_hash)
            return DeliveryOutcome("retry", "telegram_transport")

    async def _finish_failed_job(self, message_id: str, payload: str, reason: str, *, permanent: bool = False) -> None:
        retry_key = f"delivery:retry:{message_id}"
        if permanent:
            attempts = 5
        else:
            attempts = await self.redis.incr(retry_key)
            await self.redis.expire(retry_key, 86400)
        if attempts < 5:
            # Leave the job pending. XAUTOCLAIM retries after its idle lease.
            logger.warning("Delivery %s failed (%s), attempt %d/5", message_id, reason, attempts)
            return
        try:
            job = json.loads(payload)
            stage_key = f"delivery:stage:{job['event_id']}:{job['step']}"
        except (ValueError, KeyError, TypeError):
            stage_key = None
        pipe = self.redis.pipeline(transaction=True)
        pipe.xadd(self.delivery_dlq_name, {"payload": payload, "reason": reason, "source_id": message_id})
        if stage_key:
            pipe.set(stage_key, "failed", ex=604800)
        pipe.xack(self.delivery_stream_name, self.delivery_group_name, message_id)
        pipe.delete(retry_key)
        await pipe.execute()
        logger.error("Delivery %s moved to DLQ after five failures", message_id)

    async def _deliver_one(self, message_id: str, data: dict[str, str]) -> None:
        raw_payload = data.get("payload", "")
        try:
            job: dict[str, Any] = json.loads(raw_payload)
            chat_id = int(job["chat_id"])
            step = int(job["step"])
            text = str(job["text"])
            if step not in (1, 2, 3):
                raise ValueError("invalid delivery step")
        except (ValueError, KeyError, TypeError) as exc:
            await self._finish_failed_job(message_id, raw_payload, f"invalid job: {exc}")
            return

        event_id = job.get("event_id")
        current_generation = await self.redis.get(f"privacy:generation:{chat_id}") or "0"
        if job.get("recipient_generation", "0") != current_generation:
            await self.redis.xack(self.delivery_stream_name, self.delivery_group_name, message_id)
            return
        if await self.redis.exists(f"privacy:deleted:{chat_id}"):
            await self.redis.xack(self.delivery_stream_name, self.delivery_group_name, message_id)
            return
        source_timestamp = job.get("source_timestamp")
        if isinstance(source_timestamp, str):
            try:
                source_age = (datetime.now(UTC) - datetime.fromisoformat(source_timestamp)).total_seconds()
                if source_age > 604800:
                    await self.redis.xack(self.delivery_stream_name, self.delivery_group_name, message_id)
                    return
            except (TypeError, ValueError):
                await self._finish_failed_job(message_id, raw_payload, "invalid source timestamp", permanent=True)
                return
        if step > 1 and not isinstance(event_id, str):
            await self._finish_failed_job(message_id, raw_payload, "missing event identity")
            return
        if step > 1:
            source_chat_id = job.get("source_chat_id")
            source_message_id = job.get("source_message_id")
            if source_chat_id is not None and source_message_id is not None:
                clear_id = await self.redis.get(f"threat:clear_id:{int(source_chat_id)}")
                if clear_id is not None and int(clear_id) > int(source_message_id):
                    await self.redis.xack(self.delivery_stream_name, self.delivery_group_name, message_id)
                    DELIVERY_OUTCOMES.labels(stage=str(step), outcome="cancelled_clear").inc()
                    return
            prior_state = await self.redis.get(f"delivery:stage:{event_id}:{step - 1}")
            if prior_state == "failed":
                pipe = self.redis.pipeline(transaction=True)
                pipe.xadd(self.delivery_dlq_name, {"payload": raw_payload, "reason": "previous stage failed"})
                pipe.xack(self.delivery_stream_name, self.delivery_group_name, message_id)
                await pipe.execute()
                return
            if prior_state != "sent":
                # Requeue the delayed stage until the previous stage succeeds.
                pipe = self.redis.pipeline(transaction=True)
                pipe.zadd(self.delayed_queue_key, {raw_payload: int(time.time()) + 10})
                pipe.xack(self.delivery_stream_name, self.delivery_group_name, message_id)
                await pipe.execute()
                return

        # Acknowledgement or daytime cutoff intentionally suppresses a delayed
        # stage. The first stage was already selected during the night.
        if step > 1 and (not self._is_night() or await self._db_mute_active(chat_id)):
            await self.redis.xack(self.delivery_stream_name, self.delivery_group_name, message_id)
            return

        if await self.redis.exists(f"telegram:blocked:{chat_id}"):
            await self._finish_failed_job(message_id, raw_payload, "recipient_blocked", permanent=True)
            return

        outcome = await self.send_single_message(
            chat_id,
            text,
            reply_markup=build_acknowledge_keyboard() if step == 1 else None,
            disable_notification=bool(job.get("silent", False)),
            repeat=step > 1,
        )
        if outcome.status == "sent":
            DELIVERY_OUTCOMES.labels(stage=str(step), outcome="sent").inc()
            source_timestamp = job.get("source_timestamp")
            if isinstance(source_timestamp, str):
                try:
                    source_time = datetime.fromisoformat(source_timestamp)
                    if source_time.tzinfo is not None:
                        DELIVERY_LATENCY.labels(stage=str(step)).observe(
                            max(0.0, (datetime.now(UTC) - source_time).total_seconds())
                        )
                except ValueError:
                    logger.warning("Invalid source timestamp in delivery job %s", message_id)
            pipe = self.redis.pipeline(transaction=True)
            if isinstance(event_id, str):
                pipe.set(f"delivery:stage:{event_id}:{step}", "sent", ex=604800)
            pipe.xack(self.delivery_stream_name, self.delivery_group_name, message_id)
            await pipe.execute()
            await self.redis.delete(f"delivery:retry:{message_id}")
            await self._record_delivered(chat_id)
        else:
            DELIVERY_OUTCOMES.labels(stage=str(step), outcome=outcome.status).inc()
            if outcome.status == "blocked":
                await self.redis.set(f"telegram:blocked:{chat_id}", "re_onboarding_required")
            if outcome.status in ("blocked", "permanent"):
                DELIVERY_PERMANENT_FAILURES.inc()
            await self._finish_failed_job(
                message_id, raw_payload, outcome.reason, permanent=outcome.status in ("blocked", "permanent")
            )

    async def process_delivery_stream(self, worker_index: int) -> None:
        """Consume new jobs and reclaim jobs left pending by failed processes."""
        consumer = f"delivery_{socket.gethostname()}_{os.getpid()}_{worker_index}"
        next_start_id = "0-0"
        while True:
            try:
                claimed = await self.redis.xautoclaim(
                    self.delivery_stream_name,
                    self.delivery_group_name,
                    consumer,
                    # send_single_message can wait up to 180s on flood control.
                    # Do not let another process steal a job while it is sending.
                    min_idle_time=max(240000, (config.TELEGRAM_MAX_RETRY_SECONDS + 60) * 1000),
                    start_id=next_start_id,
                    count=20,
                )
                next_start_id = claimed[0]
                for message_id, data in claimed[1]:
                    await self._deliver_one(message_id, data)
                incoming = await self.redis.xreadgroup(
                    self.delivery_group_name,
                    consumer,
                    {self.delivery_stream_name: ">"},
                    count=20,
                    block=1000,
                )
                for _stream, messages in incoming:
                    for message_id, data in messages:
                        await self._deliver_one(message_id, data)
            except asyncio.CancelledError:
                raise
            except ResponseError as exc:
                if "NOGROUP" in str(exc):
                    await self.ensure_delivery_group()
                else:
                    logger.exception("Delivery stream response error")
                await asyncio.sleep(2)
            except Exception:
                logger.exception("Delivery stream worker failed; pending jobs will be reclaimed")
                await asyncio.sleep(2)

    async def process_delayed_alerts(self) -> None:
        script = self.redis.register_script(POP_MATURE_TASKS_LUA)
        while True:
            try:
                moved = await script(
                    keys=[self.delayed_queue_key, self.delivery_stream_name],
                    args=[int(time.time()), 50],
                )
                await asyncio.sleep(0.05 if moved else 2)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Delayed delivery transfer failed")
                await asyncio.sleep(2)
