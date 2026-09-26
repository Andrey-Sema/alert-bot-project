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


def read_secret_file(path: str, label: str, *, max_bytes: int = 4096) -> str:
    """Read one regular UTF-8 file using the same bounded descriptor."""
    if not path:
        raise ValueError(f"{label} cannot be empty")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError(f"{label} must be a regular file")
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError(f"{label} exceeds {max_bytes} bytes")
    try:
        value = raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        raise ValueError(f"{label} must contain UTF-8") from None
    if not value:
        raise ValueError(f"{label} cannot be empty")
    return value


def load_secret(name: str, fallback: str | None = None, *, required: bool = True, max_bytes: int = 4096) -> str:
    """Read an environment secret, preferring its bounded *_FILE variant."""
    path = os.getenv(f"{name}_FILE")
    if path is not None:
        value = read_secret_file(path, f"{name}_FILE", max_bytes=max_bytes)
    else:
        value = fallback if fallback is not None else os.getenv(name, "")
    if len(value.encode("utf-8")) > max_bytes:
        raise ValueError(f"{name} exceeds {max_bytes} bytes")
    if required and not value:
        raise ValueError(f"{name} is required and cannot be empty")
    return value
