"""Validate rendered Compose credential boundaries without printing credentials."""

import json
import sys
from typing import Any

from alert_bot_project.core_shared.redis_acl import validate_service_redis_url

SECRET_FIELDS = {
    "BOT_TOKEN",
    "API_HASH",
    "DATABASE_URL",
    "MIGRATION_DATABASE_URL",
    "PYROGRAM_SESSION_STRING",
    "UKRAINEALARM_API_KEY",
    "REDIS_PASSWORD",
    "REDIS_URL",
    "GRAFANA_PASSWORD",
}
ALLOWED = {
    "worker": {"BOT_TOKEN", "DATABASE_URL", "UKRAINEALARM_API_KEY", "REDIS_URL"},
    "bot_ui": {"BOT_TOKEN", "DATABASE_URL", "REDIS_URL"},
    "scraper": {"API_HASH", "PYROGRAM_SESSION_STRING", "REDIS_URL"},
    "migrator": {"MIGRATION_DATABASE_URL"},
}


def validate_service_environments(data: dict[str, Any]) -> None:
    for name, allowed in ALLOWED.items():
        environment = data["services"][name]["environment"]
        if environment.get("SERVICE_ROLE") != name:
            raise ValueError("Compose service profile mismatch")
        for key in environment:
            base = key.removesuffix("_FILE")
            if base in SECRET_FIELDS and base not in allowed:
                raise ValueError("Compose exposes credentials to an unrelated service")
        required = {
            "worker": ("BOT_TOKEN", "DATABASE_URL", "REDIS_URL"),
            "bot_ui": ("BOT_TOKEN", "DATABASE_URL", "REDIS_URL"),
            "scraper": ("API_HASH", "REDIS_URL"),
            "migrator": ("MIGRATION_DATABASE_URL",),
        }[name]
        for key in (*required, "LOG_PSEUDONYM_KEY"):
            if not environment.get(key) and not environment.get(f"{key}_FILE"):
                raise ValueError("Compose service credential missing")
        if name != "migrator" and environment.get("REDIS_URL"):
            validate_service_redis_url(environment["REDIS_URL"], name)
        if _secret_sources(data["services"][name]) & {
            "redis_users_acl",
            "redis_health_password",
            "redis_exporter_credentials",
        }:
            raise ValueError("Compose exposes infrastructure secrets to an application service")
    redis = data["services"]["redis"]
    command = redis.get("command", [])
    if isinstance(command, str):
        command = command.split()
    if "--requirepass" in command or "--aclfile" not in command:
        raise ValueError("Redis must use the named-account ACL file")
    index = command.index("--aclfile")
    if command[index + 1 : index + 2] != ["/run/secrets/redis_users_acl"]:
        raise ValueError("Unexpected Redis ACL file")
    if _secret_sources(redis) != {"redis_users_acl", "redis_health_password"}:
        raise ValueError("Unexpected Redis secret mounts")
    monitor = data["services"]["redis-exporter"]
    env = monitor["environment"]
    expected = {
        "REDIS_ADDR": "redis://redis:6379",
        "REDIS_USER": "alert_monitor",
        "REDIS_PASSWORD_FILE": "/run/secrets/redis_exporter_credentials",
        "REDIS_EXPORTER_CONFIG_COMMAND": "-",
        "REDIS_EXPORTER_EXPORT_CLIENT_LIST": "false",
        "REDIS_EXPORTER_DISABLE_EXPORTING_KEY_VALUES": "true",
    }
    if any(str(env.get(key)).lower() != value for key, value in expected.items()) or "REDIS_PASSWORD" in env:
        raise ValueError("Unexpected Redis monitoring identity or configuration")
    if any(
        env.get(key)
        for key in (
            "REDIS_EXPORTER_CHECK_KEYS",
            "REDIS_EXPORTER_CHECK_SINGLE_KEYS",
            "REDIS_EXPORTER_CHECK_STREAMS",
            "REDIS_EXPORTER_SCRIPT",
        )
    ) or _secret_sources(monitor) != {"redis_exporter_credentials"}:
        raise ValueError("Redis monitoring must not inspect application payloads")


def _secret_sources(service: dict[str, Any]) -> set[str]:
    return {item if isinstance(item, str) else item["source"] for item in service.get("secrets", [])}


if __name__ == "__main__":
    validate_service_environments(json.load(sys.stdin))
    print("Compose service credential boundaries validated")
