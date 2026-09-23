"""Transport and secret-loading boundaries."""

from pathlib import Path

import pytest

from alert_bot_project.core_shared.config import Settings


def test_secret_file_overrides_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    token_file = tmp_path / "bot_token"
    token_file.write_text("123456:file_token\n", encoding="utf-8")
    monkeypatch.setenv("BOT_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("BOT_TOKEN", "123456:environment_token")
    settings = Settings(_env_file=None)
    assert settings.BOT_TOKEN == "123456:file_token"


@pytest.mark.parametrize("url", ["redis://cache.example.com:6379/0", "http://cache.example.com/0"])
def test_external_redis_without_tls_is_rejected(url: str) -> None:
    with pytest.raises(ValueError, match=r"REDIS_URL|External Redis"):
        Settings.require_tls_for_external_redis(url)
