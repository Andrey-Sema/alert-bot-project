# worker/mirror_pool.py
import asyncio, zlib, logging
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError, TelegramAPIError

logger = logging.getLogger("worker.mirror_pool")

class MirrorPool:
    def __init__(self, tokens: list[str], per_token_rps: float = 25.0, workers_per_token: int = 2):
        self.bots = [Bot(t, default=DefaultBotProperties(parse_mode=ParseMode.HTML)) for t in tokens]
        self.queues = [asyncio.Queue(maxsize=10000) for _ in tokens]
        self._delay = 1.0 / per_token_rps
        self._workers_per_token = workers_per_token
        self._tasks: list[asyncio.Task] = []

    def route(self, user_id: int, assigned_idx: int | None) -> int:
        # assigned_idx — тот бот, у которого юзер реально нажал /start (из БД).
        # Фоллбэк — детерминированный шард по user_id (для равномерности).
        if assigned_idx is not None and 0 <= assigned_idx < len(self.bots):
            return assigned_idx
        return zlib.crc32(str(user_id).encode()) % len(self.bots)

    def send(self, user_id: int, text: str, assigned_idx=None, **kw):
        idx = self.route(user_id, assigned_idx)
        try:
            self.queues[idx].put_nowait((user_id, text, kw))
        except asyncio.QueueFull:
            logger.warning("mirror %d queue full, dropping for %s", idx, user_id)

    def start(self):
        for i, bot in enumerate(self.bots):
            for _ in range(self._workers_per_token):
                self._tasks.append(asyncio.create_task(self._worker(i, bot)))

    async def _worker(self, idx: int, bot: Bot):
        q = self.queues[idx]
        while True:
            user_id, text, kw = await q.get()
            try:
                await self._send_one(bot, user_id, text, kw)
                await asyncio.sleep(self._delay)  # per-token throttle
            except Exception:
                logger.exception("send failed on mirror %d", idx)
            finally:
                q.task_done()

    async def _send_one(self, bot, user_id, text, kw):
        try:
            await bot.send_message(user_id, text, **kw)
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            await bot.send_message(user_id, text, **kw)
        except TelegramForbiddenError:
            # юзер заблокировал бота / не стартовал этого mirror — пометить в БД bot_id=NULL
            logger.info("forbidden: user %s must re-onboard", user_id)
        except TelegramAPIError:
            logger.exception("api error for %s", user_id)

    async def close(self):
        for q in self.queues: await q.join()
        for t in self._tasks: t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        for b in self.bots: await b.session.close()