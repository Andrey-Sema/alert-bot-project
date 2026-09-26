"""Validate rendered Compose credential boundaries without printing credentials."""

import json
import sys
from typing import Any

SECRET_FIELDS = {
    "BOT_TOKEN",
    "API_HASH",
    "DATABASE_URL",
    "MIGRATION_DATABASE_URL",
    "PYROGRAM_SESSION_STRING",
    "UKRAINEALARM_API_KEY",
    "REDIS_PASSWORD",
    "GRAFANA_PASSWORD",
}
ALLOWED = {
    "worker": {"BOT_TOKEN", "DATABASE_URL", "UKRAINEALARM_API_KEY"},
    "bot_ui": {"BOT_TOKEN", "DATABASE_URL"},
    "scraper": {"API_HASH", "PYROGRAM_SESSION_STRING"},
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
            "worker": ("BOT_TOKEN", "DATABASE_URL"),
            "bot_ui": ("BOT_TOKEN", "DATABASE_URL"),
            "scraper": ("API_HASH",),
            "migrator": ("MIGRATION_DATABASE_URL",),
        }[name]
        for key in (*required, "LOG_PSEUDONYM_KEY"):
            if not environment.get(key) and not environment.get(f"{key}_FILE"):
                raise ValueError("Compose service credential missing")


if __name__ == "__main__":
    validate_service_environments(json.load(sys.stdin))
    print("Compose service credential boundaries validated")
