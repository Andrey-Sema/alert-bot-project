"""Profile isolation and fail-closed runtime privilege contracts."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from alert_bot_project.core_shared.config import Settings
from alert_bot_project.database.privileges import PRIVILEGES, TABLES, allowed_privileges, verify_runtime_privileges


def _identity(**changes: object) -> MagicMock:
    result = MagicMock()
    result.mappings.return_value.one.return_value = {
        "identity": "alert_bot_worker",
        "login": "alert_bot_worker",
        "unsafe": False,
        "memberships": False,
        "ddl": False,
        **changes,
    }
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"identity": "postgres"},
        {"login": "postgres"},
        {"unsafe": True},
        {"memberships": True},
        {"ddl": True},
    ],
)
async def test_unsafe_identity_is_rejected_before_table_queries(changes: dict[str, object]) -> None:
    session = AsyncMock()
    session.execute.return_value = _identity(**changes)
    with pytest.raises(RuntimeError, match="identity"):
        await verify_runtime_privileges(session, "worker")
    assert session.execute.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"owned": True},
        {"owned": None},
        {"rls": False},
        {"granted": [True] * 7},
        {"columns": [True, True, False, False]},
        {"grantable": [True, False, False, False]},
    ],
)
async def test_extra_or_missing_privileges_are_rejected(changes: dict[str, object]) -> None:
    tables = MagicMock()
    tables.mappings.return_value.all.return_value = [
        {
            "table_name": "user_settings",
            "owned": False,
            "rls": True,
            "granted": [True, False, False, False, False, False, False],
            "columns": [True, False, False, False],
            "grantable": [False] * 4,
            **changes,
        }
    ]
    session = AsyncMock()
    session.execute.side_effect = [_identity(), tables]
    with pytest.raises(RuntimeError, match="Unsafe|Unexpected|Runtime"):
        await verify_runtime_privileges(session, "worker")


@given(table=st.sampled_from(TABLES), privilege=st.sampled_from(PRIVILEGES))
def test_worker_never_has_subscription_write_or_ddl_permissions(table: str, privilege: str) -> None:
    allowed = allowed_privileges("worker", table)
    if table in ("user_settings", "user_triggers"):
        assert (privilege in allowed) == (privilege == "SELECT")
    assert not allowed & {"TRUNCATE", "REFERENCES", "TRIGGER"}


@pytest.mark.parametrize("service", ["worker", "bot_ui", "scraper"])
def test_runtime_profile_rejects_migration_secret_before_file_access(
    monkeypatch: pytest.MonkeyPatch, service: str
) -> None:
    monkeypatch.setenv("MIGRATION_DATABASE_URL_FILE", "/missing/privileged-secret")
    with pytest.raises(ValidationError, match="Migration credentials"):
        Settings(SERVICE_ROLE=service, _env_file=None)


@pytest.mark.parametrize("service", ["worker", "bot_ui"])
def test_runtime_profile_does_not_require_scraper_credentials(monkeypatch: pytest.MonkeyPatch, service: str) -> None:
    for name in ("API_HASH", "API_ID", "GROUP_ID", "MIGRATION_DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(SERVICE_ROLE=service, _env_file=None)
    assert not settings.API_HASH
    assert not settings.MIGRATION_DATABASE_URL


def test_migrator_cannot_use_runtime_url_as_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="credentials are missing"):
        Settings(SERVICE_ROLE="migrator", _env_file=None)


def test_scraper_does_not_need_bot_or_database_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("BOT_TOKEN", "DATABASE_URL", "MIGRATION_DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(SERVICE_ROLE="scraper", _env_file=None)
    assert not settings.BOT_TOKEN
    assert not settings.DATABASE_URL


@pytest.mark.parametrize(
    ("service", "secret"),
    [
        ("worker", "API_HASH"),
        ("bot_ui", "PYROGRAM_SESSION_STRING"),
        ("scraper", "DATABASE_URL"),
        ("migrator", "DATABASE_URL"),
    ],
)
def test_unrelated_file_is_rejected_before_reading(monkeypatch: pytest.MonkeyPatch, service: str, secret: str) -> None:
    monkeypatch.setenv(f"{secret}_FILE", "/missing/unrelated-secret")
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="Unrelated secret files"):
        Settings(SERVICE_ROLE=service, _env_file=None)
