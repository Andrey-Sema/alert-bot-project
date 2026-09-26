"""Bounded secret-file loading shared by runtime and migrations."""

import os
import stat

SECRET_NAMES = (
    "BOT_TOKEN",
    "API_HASH",
    "DATABASE_URL",
    "MIGRATION_DATABASE_URL",
    "REDIS_URL",
    "UKRAINEALARM_API_KEY",
    "LOG_PSEUDONYM_KEY",
    "PYROGRAM_SESSION_STRING",
)


def load_secret(name: str, fallback: str | None = None, *, required: bool = True, max_bytes: int = 4096) -> str:
    """Read an environment secret, preferring its bounded *_FILE variant."""
    path = os.getenv(f"{name}_FILE")
    if path is not None:
        if not path:
            raise ValueError(f"{name}_FILE cannot be empty")
        # Nonblocking open prevents a FIFO from hanging startup. fstat/read use
        # the same descriptor, so replacement or growth cannot bypass the bound.
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError(f"{name}_FILE must be a regular file")
            raw = stream.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ValueError(f"{name}_FILE exceeds {max_bytes} bytes")
        try:
            value = raw.decode("utf-8").strip()
        except UnicodeDecodeError:
            raise ValueError(f"{name}_FILE must contain UTF-8") from None
        if not value:
            raise ValueError(f"{name}_FILE cannot be empty")
    else:
        value = fallback if fallback is not None else os.getenv(name, "")
    if len(value.encode("utf-8")) > max_bytes:
        raise ValueError(f"{name} exceeds {max_bytes} bytes")
    if required and not value:
        raise ValueError(f"{name} is required and cannot be empty")
    return value
