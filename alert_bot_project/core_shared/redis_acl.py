"""Redis 7.2 command/key selectors. No passwords or runtime configuration."""

import hashlib
import re
from urllib.parse import unquote, urlsplit

REDIS_USERS = {"scraper": "alert_scraper", "worker": "alert_worker", "bot_ui": "alert_bot_ui"}
USERS = {**REDIS_USERS, "monitor": "alert_monitor", "health": "alert_health", "operator": "alert_operator"}
CONNECTION = "+ping +hello +auth +quit +client|setname +client|setinfo +acl|whoami"
SCRIPTING = "+script|load"


def selector(commands: str, keys: tuple[str, ...], *, permission: str = "RW") -> str:
    return "(" + commands + " " + " ".join(f"%{permission}~{key}" for key in keys) + ")"


WORKER_KEYS = (
    "dead_letter_queue",
    "expired_alerts_queue",
    "expired:audited:*",
    "delayed_alerts_queue",
    "delivery_stream",
    "delivery_dead_letter_queue",
    "delivery:*",
    "threat:clear_id:*",
    "official_alarm_status:odesa",
    "global_custom_triggers",
    "global_custom_triggers:version",
    "cache:alert_targets:*",
    "lock:cache_build:*",
    "retry_count:*",
    "telegram:blocked:*",
    "telegram:rate:*",
    "privacy:inflight:*",
)
SOURCE_COMMANDS = (
    "+exists +xreadgroup +xack +xclaim +xautoclaim +xgroup|create +xgroup|delconsumer "
    "+xinfo|groups +xinfo|consumers +xpending +xrange +xlen +xtrim"
)
WORKER_COMMANDS = (
    "+get +mget +set +setex +exists +del +incr +decr +expire +smembers +sadd +srem "
    "+xadd +xack +xrange +xlen +xreadgroup +xautoclaim +xclaim +xpending +xtrim "
    "+xgroup|create +xinfo|groups +xinfo|consumers +zadd +zrem +zrangebyscore +zcard +time"
)
UI_SCRIPT_KEYS = (
    "privacy:operation:*",
    "privacy:deleted:*",
    "privacy:generation:*",
    "global_custom_triggers",
    "global_custom_triggers:version",
)

POLICIES = {
    "scraper": " ".join(
        (
            CONNECTION,
            SCRIPTING,
            "+scan",
            selector("+exists +set +expire", ("source:published:*",)),
            selector("+xadd", ("alerts_stream",), permission="W"),
            selector("+eval +evalsha", ("source:published:*", "alerts_stream")),
        )
    ),
    "worker": " ".join(
        (
            CONNECTION,
            SCRIPTING,
            "+multi +exec +discard",
            selector(WORKER_COMMANDS, WORKER_KEYS),
            selector(SOURCE_COMMANDS, ("alerts_stream",)),
            selector(
                "+get +mget +exists", ("privacy:deleted:*", "privacy:generation:*", "user_mute:*"), permission="R"
            ),
            selector("+eval +evalsha", (*WORKER_KEYS, "alerts_stream", "privacy:deleted:*", "privacy:generation:*")),
        )
    ),
    "bot_ui": " ".join(
        (
            CONNECTION,
            SCRIPTING,
            "+scan",
            selector(
                "+get +set +del +exists +expire",
                ("privacy:operation:*", "privacy:deleted:*", "privacy:generation:*", "user_mute:*"),
            ),
            selector("+get", ("privacy:inflight:*",), permission="R"),
            selector("+set", ("throttle:*",), permission="W"),
            selector(
                "+del",
                (
                    "privacy:operation:*",
                    "privacy:deleted:*",
                    "privacy:generation:*",
                    "user_mute:*",
                    "telegram:blocked:*",
                    "telegram:rate:chat:*",
                    "delivery:enqueued:*",
                    "delivery:stage:*",
                    "delivery:retry:*",
                ),
                permission="W",
            ),
            selector("+xrange +xack +xdel", ("delivery_stream", "delivery_dead_letter_queue")),
            selector("+zscan +zrem", ("delayed_alerts_queue",)),
            selector("+sadd +srem", ("global_custom_triggers",)),
            selector("+incr", ("global_custom_triggers:version",)),
            selector("+eval +evalsha", UI_SCRIPT_KEYS),
        )
    ),
    "monitor": CONNECTION + " +info +slowlog|len +latency|latest +latency|histogram",
    "health": "+ping +auth +quit",
    "operator": "+@all ~* &*",
}


def build_acl(passwords: dict[str, str]) -> str:
    if set(passwords) != set(USERS):
        raise ValueError("All named Redis account passwords are required")
    if len(set(passwords.values())) != len(USERS):
        raise ValueError("Redis accounts must not share passwords")
    lines = ["user default reset off"]
    for role, username in USERS.items():
        password = passwords[role]
        if not re.fullmatch(r"[0-9a-f]{64}", password) or len(set(password)) < 2:
            raise ValueError("Each Redis password must be independently generated as 64 hexadecimal characters")
        digest = hashlib.sha256(password.encode()).hexdigest()
        lines.append(f"user {username} reset on #{digest} {POLICIES[role]}")
    return "\n".join(lines) + "\n"


def validate_service_redis_url(value: str, service: str) -> None:
    from alert_bot_project.core_shared.redis_transport import validate_redis_transport_url

    validate_redis_transport_url(value)
    if service not in REDIS_USERS:
        raise ValueError("Unknown Redis application service")
    parsed = urlsplit(value)
    if parsed.scheme not in ("redis", "rediss") or not parsed.hostname:
        raise ValueError("Invalid Redis service URL")
    if unquote(parsed.username or "") != REDIS_USERS[service] or not parsed.password:
        raise ValueError("Redis service URL must use its named ACL account and password")
    if parsed.path not in ("", "/", "/0") or parsed.query or parsed.fragment:
        raise ValueError("Redis service URL must use database 0 without query overrides or fragments")
