"""Bounded secret-file loading shared by runtime and migrations."""

import os
from pathlib import Path


def load_secret(name: str, fallback: str | None = None) -> str:
    """Read an environment secret, preferring its bounded *_FILE variant."""
    path = os.getenv(f"{name}_FILE")
    if path:
        secret_path = Path(path)
        if secret_path.stat().st_size > 4096:
            raise ValueError(f"{name}_FILE exceeds 4096 bytes")
        value = secret_path.read_text(encoding="utf-8").strip()
    else:
        value = fallback if fallback is not None else os.getenv(name, "")
    if not value:
        raise ValueError(f"{name} is required and cannot be empty")
    return value
