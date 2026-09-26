"""Fail-closed secret loading and independent log-key regression checks."""

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from alert_bot_project.core_shared.config import Settings, config
from alert_bot_project.core_shared.logging_config import RedactingConsoleFormatter, StructuredJsonFormatter
from alert_bot_project.core_shared.secrets import load_secret
from alert_bot_project.worker.broadcaster import Broadcaster

KEY = "0123456789abcdef" * 4


@pytest.mark.parametrize("value", ["", "change_me", "0" * 64, "g" * 64, "a" * 63, "a" * 65])
def test_invalid_key_cannot_start_or_leak_input(value: str) -> None:
    with pytest.raises(ValidationError) as error:
        Settings(LOG_PSEUDONYM_KEY=value, _env_file=None)
    assert "input_value" not in str(error.value)


def test_missing_key_has_no_credential_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOG_PSEUDONYM_KEY", raising=False)
    monkeypatch.delenv("LOG_PSEUDONYM_KEY_FILE", raising=False)
    with pytest.raises(ValidationError, match="LOG_PSEUDONYM_KEY"):
        Settings(_env_file=None)


def test_log_key_cannot_reuse_telegram_credential() -> None:
    with pytest.raises(ValidationError, match="cannot reuse"):
        Settings(LOG_PSEUDONYM_KEY=KEY, API_HASH=KEY, _env_file=None)


def test_key_file_overrides_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "key"
    path.write_text(KEY + "\n", encoding="utf-8")
    monkeypatch.setenv("LOG_PSEUDONYM_KEY_FILE", str(path))
    settings = Settings(LOG_PSEUDONYM_KEY="bad", _env_file=None)
    assert settings.LOG_PSEUDONYM_KEY == KEY
    assert KEY not in repr(settings)


def test_pseudonym_is_stable_independent_and_changes_on_rotation() -> None:
    with patch.object(config, "LOG_PSEUDONYM_KEY", KEY):
        first = Broadcaster(AsyncMock(), MagicMock())._hash_id(777)
        with patch.object(config, "API_HASH", "changed-telegram-credential"):
            assert Broadcaster(AsyncMock(), MagicMock())._hash_id(777) == first
    with patch.object(config, "LOG_PSEUDONYM_KEY", "fedcba9876543210" * 4):
        assert Broadcaster(AsyncMock(), MagicMock())._hash_id(777) != first
    assert first != Broadcaster(AsyncMock(), MagicMock())._hash_id(888)


@given(value=st.text(alphabet="0123456789abcdef", min_size=64, max_size=64).filter(lambda s: len(set(s)) > 1))
def test_valid_key_decodes_to_exactly_256_bits(value: str) -> None:
    assert len(bytes.fromhex(Settings.validate_log_key(value))) == 32


@pytest.mark.parametrize("content", [b"", b"x" * 4097, b"\xffprivate"])
def test_invalid_file_never_falls_back_to_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, content: bytes
) -> None:
    path = tmp_path / "secret"
    path.write_bytes(content)
    monkeypatch.setenv("BOT_TOKEN_FILE", str(path))
    monkeypatch.setenv("BOT_TOKEN", "valid-fallback")
    with pytest.raises(ValueError, match="BOT_TOKEN_FILE") as error:
        load_secret("BOT_TOKEN")
    assert "private" not in str(error.value)


def test_empty_file_path_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN_FILE", "")
    with pytest.raises(ValueError, match="cannot be empty"):
        load_secret("BOT_TOKEN")


def test_file_read_is_bounded_even_when_stat_reports_small_size(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "secret"
    path.write_bytes(b"x" * 4097)
    monkeypatch.setenv("BOT_TOKEN_FILE", str(path))
    with (
        patch("alert_bot_project.core_shared.secrets.os.fstat", return_value=MagicMock(st_mode=0o100600, st_size=1)),
        pytest.raises(ValueError, match="exceeds"),
    ):
        load_secret("BOT_TOKEN")


@pytest.mark.skipif(os.name == "nt", reason="POSIX named pipes")
def test_named_pipe_is_rejected_without_waiting_for_writer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "pipe"
    os.mkfifo(path)
    monkeypatch.setenv("BOT_TOKEN_FILE", str(path))
    with pytest.raises(ValueError, match="regular file"):
        load_secret("BOT_TOKEN")


@pytest.mark.skipif(os.name == "nt", reason="POSIX atomic replacement of open files")
def test_concurrent_rotation_reads_one_complete_secret(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "secret"
    values = ("a" * 2048, "b" * 2048)
    path.write_text(values[0], encoding="utf-8")
    monkeypatch.setenv("BOT_TOKEN_FILE", str(path))

    def read_many() -> set[str]:
        return {load_secret("BOT_TOKEN") for _ in range(100)}

    with ThreadPoolExecutor(max_workers=4) as executor:
        readers = [executor.submit(read_many) for _ in range(4)]
        for i in range(40):
            replacement = tmp_path / f"replacement-{i}"
            replacement.write_text(values[i % 2], encoding="utf-8")
            os.replace(replacement, path)
        for reader in readers:
            assert reader.result() <= set(values)


def test_optional_session_file_cannot_be_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "session"
    path.write_text("", encoding="utf-8")
    monkeypatch.setenv("PYROGRAM_SESSION_STRING_FILE", str(path))
    with pytest.raises(ValidationError, match="cannot be empty"):
        Settings(_env_file=None)


def test_session_environment_is_bounded_by_utf8_bytes() -> None:
    with pytest.raises(ValidationError, match="16384 bytes"):
        Settings(PYROGRAM_SESSION_STRING="я" * 8193, _env_file=None)


@pytest.mark.parametrize("formatter", [RedactingConsoleFormatter(), StructuredJsonFormatter()])
def test_session_and_log_key_redacted_in_exception_and_message(formatter: logging.Formatter) -> None:
    session = "private-session-value"
    with patch.object(config, "PYROGRAM_SESSION_STRING", session), patch.object(config, "LOG_PSEUDONYM_KEY", KEY):
        try:
            raise ValueError(session + " " + KEY)
        except ValueError:
            import sys

            record = logging.LogRecord("test", logging.ERROR, "test.py", 1, session + " " + KEY, (), sys.exc_info())
        output = formatter.format(record)
    assert session not in output
    assert KEY not in output
    assert "[REDACTED]" in output
