"""The rendered Compose credential boundary cannot silently widen."""

import pytest

from alert_bot_project.scripts.validate_service_environment import ALLOWED, validate_service_environments


def _config() -> dict:
    return {
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
