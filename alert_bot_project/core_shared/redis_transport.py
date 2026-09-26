"""Fail-closed Redis URL validation without loading application settings."""

from urllib.parse import urlsplit


def validate_redis_transport_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in ("redis", "rediss") or not parsed.hostname:
        raise ValueError("REDIS_URL must be a redis:// or rediss:// URL")
    if parsed.query or parsed.fragment:
        raise ValueError("REDIS_URL query overrides and fragments are forbidden")
    if parsed.scheme == "redis" and parsed.hostname not in ("localhost", "127.0.0.1", "::1", "redis"):
        raise ValueError("External Redis requires rediss:// with TLS")
    return value
