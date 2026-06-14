import logging
from typing import Optional
from redis.asyncio import Redis
from alert_bot_project.core_shared.config import config

logger = logging.getLogger("scraper.publisher")


class RedisPublisher:
    def __init__(self):
        self.redis_url = config.REDIS_URL
        self.stream_name = "alerts_stream"
        self._redis: Optional[Redis] = None

    async def connect(self):
        if not self._redis:
            self._redis = Redis.from_url(self.redis_url, decode_responses=True)
            logger.info("🔌 Подключение к Redis Streams установлено")

    async def publish_message(self, json_data: str):
        """Отправка в персистентный Redis Stream с ограничением длины (чтобы не забить память)"""
        if not self._redis:
            await self.connect()

        try:
            # 🔥 Principal fix: XADD вместо PUBLISH. maxlen=10000 обрезает старые данные.
            msg_id = await self._redis.xadd(self.stream_name, {"payload": json_data}, maxlen=10000)
            logger.info(f"📨 Сообщение записано в Stream (ID: {msg_id})")
        except Exception as e:
            logger.error(f"❌ Ошибка записи в Redis: {e}", exc_info=True)

    async def close(self):
        if self._redis:
            await self._redis.close()