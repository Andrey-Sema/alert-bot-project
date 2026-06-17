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
            logger.info("🔌 Підключення до Redis Streams установлено")

    async def publish_message(self, json_data: str) -> str:
        """
        Відправляє повідомлення в персистентний Redis Stream з обмеженням довжини (maxlen=10000).

        Рейзить виключення нагору, щоб викликаючий код (скрейпер) міг коректно
        відпрацювати політику повторних спроб (exponential backoff).
        """
        if not self._redis:
            await self.connect()

        try:
            # Атомарно пишемо в стрім із захистом оперативки Редіса від переповнення
            msg_id: str = await self._redis.xadd(
                self.stream_name,
                {"payload": json_data},
                maxlen=10000
            )
            logger.info("📨 Повідомлення записано в Stream (ID: %s)", msg_id)
            return msg_id

        except (ConnectionError, TimeoutError) as net_err:
            # ✅ ФИКС 2 (Восстановление): Если линк упал, обнуляем инстанс пула,
            # щоб наступний ретрай скрейпера примусово підняв чисте TCP-з'єднання
            logger.error("❌ Мережевий збій транспорту Redis: %s. Скидання пулу підключень...", net_err)
            self._redis = None
            raise

        except RedisError as redis_err:
            # ✅ ФИКС 1 (Контракт): Больше не жрём ошибки молча. Логируем и выкидываем наверх
            logger.error("❌ Помилка виконання команди в Redis Streams: %s", redis_err, exc_info=True)
            raise

    async def close(self) -> None:
        """Чисто закриває пул підключень до Redis."""
        if self._redis:
            await self._redis.close()
            self._redis = None
            logger.info("💾 Підключення до Redis Streams чисто закрито")