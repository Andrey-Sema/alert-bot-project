"""Bounded Redis sockets with certificate and hostname verification."""

from typing import Any

from redis.asyncio import Redis

from alert_bot_project.core_shared.config import config
from alert_bot_project.core_shared.redis_transport import validate_redis_transport_url


def create_service_redis(redis_url: str | None = None) -> Redis:
    url = validate_redis_transport_url(config.REDIS_URL if redis_url is None else redis_url)
    options: dict[str, Any] = {"decode_responses": True, "socket_connect_timeout": 3, "socket_timeout": 5}
    if url.startswith("rediss://"):
        options.update(ssl_cert_reqs="required", ssl_check_hostname=True)
        if config.REDIS_TLS_CA_FILE:
            options["ssl_ca_certs"] = config.REDIS_TLS_CA_FILE
    client: Redis = Redis.from_url(url, **options)
    return client
