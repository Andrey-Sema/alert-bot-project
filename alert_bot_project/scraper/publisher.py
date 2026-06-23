import logging
from typing import Optional
from redis.asyncio import Redis
from redis.exceptions import RedisError, ConnectionError

from alert_bot_project.core_shared.config import config

logger = logging.getLogger("scraper.publisher")


class RedisPublisher:
    def __init__(self) -> None:
        self.redis_url = config.REDIS_URL
        self.stream_name = "alerts_stream"
        self._redis: Optional[Redis] = None

    async def connect(self) -> None:
        """Ініціалізує з'єднання з пулом Redis Streams."""
        if not self._redis:
            self._redis = Redis.from_url(self.redis_url, decode_responses=True)
            await self._redis.ping()
            logger.info("🔌 Підключення до Redis Streams установлено та перевірено")

    async def publish_message(self, json_data: str) -> str:
        """Відправляє повідомлення в персистентний Redis Stream з обмеженням довжини."""
        if not self._redis:
            await self.connect()

        try:
            msg_id: str = await self._redis.xadd(
                self.stream_name,
                {"payload": json_data},
                maxlen=10000
            )
            logger.info("📨 Повідомлення записано в Stream (ID: %s)", msg_id)
            return msg_id

        except (ConnectionError, TimeoutError):
            # ✅ ФИКС С СОНАРОМ (python:S8572): Использование .exception() вместо ручной передачи net_err
            logger.exception("❌ Мережевий збій транспорту Redis. Скидання пулу підключень...")
            self._redis = None
            raise

        except RedisError:
            logger.exception("❌ Помилка виконання команди в Redis Streams")
            raise

    async def close(self) -> None:
        """Чисто закриває пул підключень до Redis."""
        if self._redis:
            await self._redis.close()
            self._redis = None
            logger.info("💾 Підключення до Redis Streams чисто закрито")