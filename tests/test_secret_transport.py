"""Transport and secret-loading boundaries."""

from pathlib import Path

import pytest

from alert_bot_project.core_shared.config import Settings
from alert_bot_project.core_shared.secrets import load_secret


def test_secret_file_overrides_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    token_file = tmp_path / "bot_token"
    token_file.write_text("123456:file_token\n", encoding="utf-8")
    monkeypatch.setenv("BOT_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("BOT_TOKEN", "123456:environment_token")
    settings = Settings(_env_file=None)
    assert settings.BOT_TOKEN == "123456:file_token"


def test_database_secret_file_is_shared_with_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    secret_file = tmp_path / "database_url"
    secret_file.write_text("postgresql+asyncpg://user:password@localhost/db\n", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL_FILE", str(secret_file))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert load_secret("DATABASE_URL") == "postgresql+asyncpg://user:password@localhost/db"
    assert load_secret("DATABASE_URL") == Settings(_env_file=None).DATABASE_URL


@pytest.mark.parametrize("content", ["", "x" * 4097])
def test_database_secret_file_rejects_empty_or_oversized_content(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, content: str
) -> None:
    secret_file = tmp_path / "database_url"
    secret_file.write_text(content, encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL_FILE", str(secret_file))
    with pytest.raises(ValueError, match="DATABASE_URL"):
        load_secret("DATABASE_URL")


def test_database_secret_file_rejects_missing_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL_FILE", str(tmp_path / "missing"))
    with pytest.raises(FileNotFoundError):
        load_secret("DATABASE_URL")


@pytest.mark.parametrize("url", ["redis://cache.example.com:6379/0", "http://cache.example.com/0"])
def test_external_redis_without_tls_is_rejected(url: str) -> None:
    with pytest.raises(ValueError, match=r"REDIS_URL|External Redis"):
        Settings.require_tls_for_external_redis(url)
