import asyncio
import logging
import json
import time
import hmac
import hashlib
from typing import Optional
from datetime import datetime
from zoneinfo import ZoneInfo
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup
from aiogram.exceptions import TelegramRetryAfter, TelegramAPIError
from redis.asyncio import Redis
from alert_bot_project.core_shared.config import config
from alert_bot_project.core_shared.constants import (
    ALERT_FIRST, ALERT_SECOND, ALERT_THIRD,
    ALERT_DELAY_1, ALERT_DELAY_2, KYIV_TZ
)

logger = logging.getLogger("worker.broadcaster")

POP_MATURE_TASKS_LUA = """
local key = KEYS[1]
local max_score = ARGV[1]
local count = ARGV[2]

local elements = redis.call('ZRANGEBYSCORE', key, '-inf', max_score, 'LIMIT', 0, count)
if #elements > 0 then
    redis.call('ZREMRANGEBYSCORE', key, '-inf', max_score)
end
return elements
"""


class Broadcaster:
    def __init__(self, bot: Bot, redis_client: Redis, workers_count: int = 15):
        self.bot = bot
        self.redis = redis_client
        self.workers_count = workers_count
        self.delayed_queue_key = "delayed_alerts_queue"
        self.queue = asyncio.Queue(maxsize=10000)
        self._workers = []
        self._salt = config.API_HASH.encode()
        self._background_tasks = set()

        self._night_start = datetime.strptime(f"{config.NIGHT_START_HOUR}:00", "%H:%M").time()
        self._night_end = datetime.strptime(f"{config.NIGHT_END_HOUR}:00", "%H:%M").time()
        self._tz = ZoneInfo(KYIV_TZ)

    def _hash_id(self, chat_id: int) -> str:
        return hmac.new(self._salt, str(chat_id).encode(), hashlib.sha256).hexdigest()[:16]

    def start(self):
        # ✅ ФИКС С СОНАРОМ (python:S7503): Убран избыточный async/await, так как создание тасков синхронно
        if not self._workers:
            self._workers = [asyncio.create_task(self._queue_worker()) for _ in range(self.workers_count)]

    async def close(self):
        logger.info("Очікування завершення розсилки повідомлень у черзі...")
        await self.queue.join()
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        logger.info("Воркери розсилки успешно остановлены.")

    async def _queue_worker(self):
        while True:
            try:
                chat_id, text, reply_markup, disable_notification = await self.queue.get()
                try:
                    await self.send_single_message(chat_id, text, reply_markup, disable_notification)
                finally:
                    self.queue.task_done()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Queue worker exception")

    async def send_single_message(self, chat_id: int, text: str, reply_markup: Optional[InlineKeyboardMarkup] = None,
                                  disable_notification: bool = False):
        total_time_waited = 0
        max_wait_seconds = config.TELEGRAM_MAX_RETRY_SECONDS
        peer_hash = self._hash_id(chat_id)

        while total_time_waited < max_wait_seconds:
            try:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                    disable_notification=disable_notification
                )
                await asyncio.sleep(0.04)
                return True
            except TelegramRetryAfter as e:
                wait_duration = min(e.retry_after, max_wait_seconds - total_time_waited)
                logger.warning("Telegram API 429. Ожидание %s сек для peer: %s", wait_duration, peer_hash)
                await asyncio.sleep(wait_duration)
                total_time_waited += wait_duration
            except TelegramAPIError:
                logger.exception("Telegram API ошибка для peer %s", peer_hash)
                return False
            except Exception:
                logger.exception("Транспортная ошибка для peer %s", peer_hash)
                return False

        logger.error("Таймаут доставки превышен для peer %s.", peer_hash)
        return False

    def fire_and_forget_message(self, chat_id: int, text: str, reply_markup: Optional[InlineKeyboardMarkup] = None,
                                disable_notification: bool = False):
        try:
            self.queue.put_nowait((chat_id, text, reply_markup, disable_notification))
        except asyncio.QueueFull:
            logger.warning("Внутренняя очередь переполнена. Запуск фоновой принудительной записи для peer %s",
                           self._hash_id(chat_id))
            task = asyncio.create_task(self.queue.put((chat_id, text, reply_markup, disable_notification)))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

    async def _execute_scheduling(self, chat_id: int, disable_notification: bool):
        try:
            now_unix = int(time.time())
            task_step_2 = {"chat_id": chat_id, "step": 2, "text": ALERT_SECOND, "silent": disable_notification}
            task_step_3 = {"chat_id": chat_id, "step": 3, "text": ALERT_THIRD, "silent": disable_notification}

            await self.redis.zadd(self.delayed_queue_key, {
                json.dumps(task_step_2): now_unix + ALERT_DELAY_1,
                json.dumps(task_step_3): now_unix + ALERT_DELAY_1 + ALERT_DELAY_2
            })
        except Exception:
            logger.exception("Сбой записи в отложенную очередь для peer %s", self._hash_id(chat_id))

    def schedule_delayed_alerts(self, chat_id: int, disable_notification: bool):
        task = asyncio.create_task(self._execute_scheduling(chat_id, disable_notification))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _process_single_delayed_task(self, task_raw: str):
        """✅ СЕНЬОР-ФИКС: Вынесено в отдельный метод для декомпозиции сложности (Cognitive Complexity)."""
        try:
            task_data = json.loads(task_raw)
        except json.JSONDecodeError:
            logger.exception("Сбой парсинга JSON отложенной задачи")
            return

        user_id = task_data["chat_id"]

        if await self.redis.exists(f"user_mute:{user_id}"):
            logger.debug("Отложенное уведомление пропущено: peer %s находится в режиме MUTE", self._hash_id(user_id))
            return

        self.fire_and_forget_message(
            chat_id=user_id,
            text=task_data["text"],
            disable_notification=task_data.get("silent", False)
        )

    async def process_delayed_alerts(self):
        script = self.redis.register_script(POP_MATURE_TASKS_LUA)
        while True:
            try:
                now_unix = int(time.time())
                tasks = await script(keys=[self.delayed_queue_key], args=[now_unix, 50])

                if not tasks:
                    await asyncio.sleep(2)
                    continue

                now_time = datetime.now(self._tz).time()
                if self._night_start > self._night_end:
                    is_night = now_time >= self._night_start or now_time <= self._night_end
                else:
                    is_night = self._night_start <= now_time <= self._night_end

                if not is_night:
                    logger.debug("Delayed alert matured during daytime. Strict cutoff active, dropping tasks.")
                    continue

                for task_raw in tasks:
                    await self._process_single_delayed_task(task_raw)

                await asyncio.sleep(0.05)

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Сбой демона отложенных сообщений")
                await asyncio.sleep(2)