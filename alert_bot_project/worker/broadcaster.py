import asyncio
import logging
import json
import time
from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter, TelegramAPIError
from redis.asyncio import Redis
from alert_bot_project.core_shared.config import config
from alert_bot_project.core_shared.constants import (
    ALERT_FIRST, ALERT_SECOND, ALERT_THIRD,
    ALERT_DELAY_1, ALERT_DELAY_2
)

logger = logging.getLogger("worker.broadcaster")
BACKPRESSURE_TIMEOUT = 5.0


class Broadcaster:
    def __init__(self, bot: Bot, redis_client: Redis, max_tasks: int = 1000):
        self.bot = bot
        self.redis = redis_client
        self.rate_limiter = asyncio.Semaphore(25)
        self.delayed_queue_key = "delayed_alerts_queue"
        self.background_tasks: set[asyncio.Task] = set()
        self.max_bg_tasks = max_tasks

    async def send_single_message(self, chat_id: int, text: str, reply_markup=None,
                                  disable_notification: bool = False) -> bool:
        total_time_waited = 0
        max_wait_seconds = config.TELEGRAM_MAX_RETRY_SECONDS

        while total_time_waited < max_wait_seconds:
            try:
                async with self.rate_limiter:
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
                logger.warning("Telegram API 429 caught. Waiting %s s on destination %s", wait_duration, chat_id)
                await asyncio.sleep(wait_duration)
                total_time_waited += wait_duration
            except TelegramAPIError as e:
                logger.error("Telegram API exception encountered for peer %s: %s", chat_id, e)
                return False
            except Exception as e:
                logger.error("Transport error during message routing to %s: %s", chat_id, e)
                return False

        logger.error("Canceled transmission stack targeting %s after hitting timeout window limits.", chat_id)
        return False

    def fire_and_forget_message(self, chat_id: int, text: str, reply_markup=None, disable_notification: bool = False):
        if len(self.background_tasks) >= self.max_bg_tasks:
            logger.error("Local background task pool saturated (%d tasks). Shedding load for user %s",
                         len(self.background_tasks), chat_id)
            return

        task = asyncio.create_task(self.send_single_message(chat_id, text, reply_markup, disable_notification))
        task.set_name(f"msg_{chat_id}_{int(time.time())}")
        self.background_tasks.add(task)

        def cleanup_callback(completed_future: asyncio.Task):
            self.background_tasks.discard(completed_future)
            if completed_future.exception():
                logger.error("Background text notification failed for user peer %s: %s", chat_id,
                             completed_future.exception())

        task.add_done_callback(cleanup_callback)

    async def _execute_scheduling(self, chat_id: int, disable_notification: bool):
        try:
            now_unix = int(time.time())
            task_step_2 = {"chat_id": chat_id, "step": 2, "text": ALERT_SECOND, "silent": disable_notification}
            task_step_3 = {"chat_id": chat_id, "step": 3, "text": ALERT_THIRD, "silent": disable_notification}

            await self.redis.zadd(self.delayed_queue_key, {
                json.dumps(task_step_2): now_unix + ALERT_DELAY_1,
                json.dumps(task_step_3): now_unix + ALERT_DELAY_1 + ALERT_DELAY_2
            })
        except Exception as e:
            logger.error("Failed to write delayed alerts to Redis for user %s: %s", chat_id, e)

    def schedule_delayed_alerts(self, chat_id: int, disable_notification: bool):
        if len(self.background_tasks) >= self.max_bg_tasks:
            logger.error("Local background task pool saturated. Shedding load for delayed schedule %s", chat_id)
            return

        task = asyncio.create_task(self._execute_scheduling(chat_id, disable_notification))
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)

    async def process_delayed_alerts(self):
        while True:
            try:
                now_unix = int(time.time())
                tasks = await self.redis.zpopmin(self.delayed_queue_key, count=50)

                if not tasks:
                    await asyncio.sleep(1)
                    continue

                requeue_buffer = {}
                for task_raw, score in tasks:
                    try:
                        if score > now_unix:
                            requeue_buffer[task_raw] = score
                            continue

                        task_data = json.loads(task_raw)
                        user_id = task_data["chat_id"]

                        if await self.redis.exists(f"user_mute:{user_id}"):
                            continue

                        is_silent = task_data.get("silent", False)
                        self.fire_and_forget_message(
                            chat_id=user_id,
                            text=task_data["text"],
                            reply_markup=None,
                            disable_notification=is_silent
                        )
                    except Exception as inner_err:
                        logger.error("Error processing individual popped delayed alert item: %s", inner_err)

                if requeue_buffer:
                    await self.redis.zadd(self.delayed_queue_key, requeue_buffer)

            except Exception as exc:
                logger.error("Catastrophic error in scheduled alert daemon loop: %s", exc, exc_info=True)
                await asyncio.sleep(2)