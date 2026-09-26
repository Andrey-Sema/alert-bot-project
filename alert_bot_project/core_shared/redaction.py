"""Redaction applied to both console and structured logging sinks."""

import json
import re
from collections.abc import Mapping
from typing import Any

from alert_bot_project.core_shared.config import config

CREDENTIAL_URL = re.compile(r"((?:postgresql(?:\+asyncpg)?|rediss?)://)[^\s/@]+(?::[^\s/@]*)?@", re.IGNORECASE)
BOT_TOKEN = re.compile(r"\b\d{5,16}:[A-Za-z0-9_-]{20,}\b")
SENSITIVE_KEY = re.compile(r"token|password|secret|authorization|api[_-]?(?:hash|key)|session_string", re.IGNORECASE)


def redact_text(value: str) -> str:
    for name in ("BOT_TOKEN", "API_HASH", "DATABASE_URL", "REDIS_URL", "UKRAINEALARM_API_KEY"):
        secret = str(getattr(config, name, ""))
        if len(secret) >= 4:
            value = value.replace(secret, "[REDACTED]")
            value = value.replace(json.dumps(secret, ensure_ascii=False)[1:-1], "[REDACTED]")
    value = BOT_TOKEN.sub("[REDACTED]", value)
    return CREDENTIAL_URL.sub(r"\1[REDACTED]@", value)


def redact_metadata(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if SENSITIVE_KEY.search(str(key)) else redact_metadata(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple | list):
        return [redact_metadata(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value
