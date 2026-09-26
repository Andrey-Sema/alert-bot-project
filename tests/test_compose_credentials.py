"""The rendered Compose credential boundary cannot silently widen."""

import pytest

from alert_bot_project.scripts.validate_service_environment import ALLOWED, validate_service_environments


def _config() -> dict:
    config = {
        "services": {
            name: {
                "environment": {
                    "SERVICE_ROLE": name,
                    "LOG_PSEUDONYM_KEY": "test-key",
                    **dict.fromkeys(allowed, "ci-placeholder"),
                }
            }
            for name, allowed in ALLOWED.items()
        }
    }
    for name in ("worker", "bot_ui", "scraper"):
        config["services"][name]["environment"]["REDIS_URL"] = f"redis://alert_{name}:test-value@redis/0"
    config["services"]["redis"] = {
        "command": ["redis-server", "--aclfile", "/run/secrets/redis_users_acl"],
        "secrets": ["redis_users_acl", "redis_health_password"],
    }
    config["services"]["redis-exporter"] = {
        "environment": {
            "REDIS_ADDR": "redis://redis:6379",
            "REDIS_USER": "alert_monitor",
            "REDIS_PASSWORD_FILE": "/run/secrets/redis_exporter_credentials",
            "REDIS_EXPORTER_CONFIG_COMMAND": "-",
            "REDIS_EXPORTER_EXPORT_CLIENT_LIST": "false",
            "REDIS_EXPORTER_DISABLE_EXPORTING_KEY_VALUES": "true",
        },
        "secrets": ["redis_exporter_credentials"],
    }
    return config


def test_minimal_profiles_are_accepted() -> None:
    validate_service_environments(_config())


@pytest.mark.parametrize(
    ("service", "key"),
    [
        ("worker", "MIGRATION_DATABASE_URL"),
        ("bot_ui", "API_HASH"),
        ("scraper", "DATABASE_URL_FILE"),
        ("migrator", "PYROGRAM_SESSION_STRING"),
        ("worker", "REDIS_PASSWORD"),
    ],
)
def test_unrelated_credentials_are_rejected(service: str, key: str) -> None:
    data = _config()
    data["services"][service]["environment"][key] = "private-credential"
    with pytest.raises(ValueError, match="unrelated") as error:
        validate_service_environments(data)
    assert "private-credential" not in str(error.value)


def test_profile_and_required_secret_cannot_be_removed() -> None:
    data = _config()
    data["services"]["worker"]["environment"]["SERVICE_ROLE"] = "development"
    with pytest.raises(ValueError, match="profile"):
        validate_service_environments(data)
    data = _config()
    del data["services"]["worker"]["environment"]["DATABASE_URL"]
    with pytest.raises(ValueError, match="missing"):
        validate_service_environments(data)


@pytest.mark.parametrize("setting", ["REDIS_PASSWORD", "REDIS_EXPORTER_CHECK_KEYS", "REDIS_EXPORTER_SCRIPT"])
def test_monitor_cannot_receive_shared_password_or_payload_extractors(setting: str) -> None:
    data = _config()
    data["services"]["redis-exporter"]["environment"][setting] = "forbidden"
    with pytest.raises(ValueError, match="monitoring"):
        validate_service_environments(data)


def test_runtime_cannot_mount_all_redis_credentials() -> None:
    data = _config()
    data["services"]["worker"]["secrets"] = [{"source": "redis_users_acl"}]
    with pytest.raises(ValueError, match="infrastructure secrets"):
        validate_service_environments(data)
