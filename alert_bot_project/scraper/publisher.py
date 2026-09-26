import logging
from contextlib import suppress

from redis.asyncio import Redis
from redis.exceptions import ConnectionError, RedisError

from alert_bot_project.core_shared.config import config
from alert_bot_project.core_shared.constants import SOURCE_REPLAY_HORIZON_SECONDS

logger = logging.getLogger("scraper.publisher")

PUBLISH_ONCE_LUA = f"""
if redis.call('EXISTS', KEYS[1]) == 1 then return 0 end
local id = redis.call('XADD', KEYS[2], '*', 'payload', ARGV[1])
redis.call('SET', KEYS[1], id, 'EX', {SOURCE_REPLAY_HORIZON_SECONDS})
return id
"""


class RedisPublisher:
    def __init__(self) -> None:
        self.redis_url = config.REDIS_URL
        self.stream_name = "alerts_stream"
        self._redis: Redis | None = None

    async def connect(self) -> None:
        """Ініціалізує з'єднання з пулом Redis Streams."""
        if not self._redis:
            redis_client = Redis.from_url(
                self.redis_url, decode_responses=True, socket_connect_timeout=3, socket_timeout=5
            )
            try:
                await redis_client.ping()
            except Exception:
                await redis_client.aclose()
                raise
            self._redis = redis_client
            logger.info("🔌 Підключення до Redis Streams установлено та перевірено")

    async def publish_message(self, json_data: str, chat_id: int, message_id: int) -> str:
        """Publish a source post once, including after an uncertain network failure."""
        if not self._redis:
            await self.connect()
        assert self._redis is not None

        try:
            script = self._redis.register_script(PUBLISH_ONCE_LUA)
            msg_id: str = await script(
                keys=[f"source:published:{chat_id}:{message_id}", self.stream_name], args=[json_data]
            )
            logger.info("📨 Повідомлення записано в Stream (ID: %s)", msg_id)
            return msg_id

        except (ConnectionError, TimeoutError):
            # ✅ ФИКС С СОНАРОМ (python:S8572): Использование .exception() вместо ручной передачи net_err
            logger.exception("❌ Мережевий збій транспорту Redis. Скидання пулу підключень...")
            stale_client = self._redis
            self._redis = None
            if stale_client is not None:
                with suppress(Exception):
                    await stale_client.aclose()
            raise

        except RedisError:
            logger.exception("❌ Помилка виконання команди в Redis Streams")
            raise

    async def expire_legacy_markers(self) -> None:
        """Give markers created before the retention policy a bounded lifetime."""
        if self._redis is None:
            await self.connect()
        assert self._redis is not None
        keys: list[str] = []
        async for key in self._redis.scan_iter(match="source:published:*", count=500):
            keys.append(key)
            if len(keys) >= 500:
                await self._expire_marker_batch(keys)
                keys.clear()
        if keys:
            await self._expire_marker_batch(keys)

    async def _expire_marker_batch(self, keys: list[str]) -> None:
        assert self._redis is not None
        pipe = self._redis.pipeline(transaction=False)
        for key in keys:
            pipe.expire(key, SOURCE_REPLAY_HORIZON_SECONDS, nx=True)
        await pipe.execute()

    async def close(self) -> None:
        """Чисто закриває пул підключень до Redis."""
        if self._redis:
            await self._redis.close()
            self._redis = None
            logger.info("💾 Підключення до Redis Streams чисто закрито")
