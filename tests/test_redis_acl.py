"""ACL compilation, credential boundaries and fail-closed identity checks."""

import hashlib
import json
import os
import re
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from hypothesis import given
from hypothesis import strategies as st

from alert_bot_project.core_shared.redis_acl import USERS, build_acl, validate_service_redis_url
from alert_bot_project.core_shared.redis_connection import verify_redis_identity
from alert_bot_project.scripts.build_redis_acl import compile_credentials


def _passwords() -> dict[str, str]:
    return {role: hashlib.sha256(role.encode()).hexdigest() for role in USERS}


def _inputs(directory: Path) -> dict[str, str]:
    values = _passwords()
    for role, password in values.items():
        (directory / f"redis_{role}_password").write_text(password, encoding="utf-8")
    return values


def test_acl_disables_default_and_stores_hashes_only() -> None:
    values = _passwords()
    acl = build_acl(values)
    assert acl.startswith("user default reset off\n")
    assert acl.count(" reset on #") == 6
    assert all(password not in acl for password in values.values())
    for role, user in USERS.items():
        assert f"user {user} reset on #{hashlib.sha256(values[role].encode()).hexdigest()}" in acl


@given(
    role=st.sampled_from(tuple(USERS)),
    password=st.text(max_size=100).filter(lambda text: re.fullmatch(r"[0-9a-f]{64}", text) is None),
)
def test_invalid_password_cannot_inject_acl_directives(role: str, password: str) -> None:
    values = _passwords()
    values[role] = password
    with pytest.raises(ValueError, match="Redis"):
        build_acl(values)


@pytest.mark.parametrize("failure", ["duplicate", "missing", "low_entropy"])
def test_independent_passwords_are_required(failure: str) -> None:
    values = _passwords()
    if failure == "duplicate":
        values["worker"] = values["operator"]
    elif failure == "missing":
        del values["operator"]
    else:
        values["worker"] = "a" * 64
    with pytest.raises(ValueError, match="Redis"):
        build_acl(values)


def test_compiler_only_exports_monitor_password(tmp_path: Path) -> None:
    values = _inputs(tmp_path)
    acl, monitor = tmp_path / "users.acl", tmp_path / "exporter.json"
    compile_credentials(tmp_path, acl, monitor)
    assert json.loads(monitor.read_text()) == {"redis://alert_monitor@redis:6379": values["monitor"]}
    assert all(password not in acl.read_text() for password in values.values())
    assert all(password not in monitor.read_text() for role, password in values.items() if role != "monitor")
    if os.name == "posix":
        assert acl.stat().st_mode & 0o777 == 0o600
        assert monitor.stat().st_mode & 0o777 == 0o600


def test_compiler_never_overwrites_existing_credentials(tmp_path: Path) -> None:
    _inputs(tmp_path)
    acl, monitor = tmp_path / "users.acl", tmp_path / "exporter.json"
    monitor.write_text("existing", encoding="utf-8")
    with pytest.raises(FileExistsError):
        compile_credentials(tmp_path, acl, monitor)
    assert not acl.exists()
    assert monitor.read_text() == "existing"


@pytest.mark.parametrize("failure", ["missing", "oversized", "directory", "invalid_utf8"])
def test_compiler_rejects_invalid_input_before_writing(tmp_path: Path, failure: str) -> None:
    _inputs(tmp_path)
    target = tmp_path / "redis_worker_password"
    if failure == "missing":
        target.unlink()
    elif failure == "oversized":
        target.write_text("f" * 129, encoding="utf-8")
    elif failure == "directory":
        target.unlink()
        target.mkdir()
    else:
        target.write_bytes(b"\xff")
    with pytest.raises((ValueError, OSError)):
        compile_credentials(tmp_path, tmp_path / "users.acl", tmp_path / "exporter.json")
    assert not (tmp_path / "users.acl").exists()


@pytest.mark.parametrize(
    "url",
    [
        "redis://:private-credential@redis/0",
        "redis://alert_operator:private-credential@redis/0",
        "redis://alert_worker:private-credential@redis/15",
        "redis://alert_worker@redis/0",
        "rediss://alert_worker:private-credential@cache.example/0?ssl_check_hostname=false",
    ],
)
def test_profile_rejects_default_wrong_identity_and_query_overrides(url: str) -> None:
    with pytest.raises(ValueError, match="Redis|REDIS_URL") as error:
        validate_service_redis_url(url, "worker")
    assert "private-credential" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("identity", ["default", "alert_operator", "alert_bot_ui", None])
async def test_unexpected_server_identity_is_rejected(identity: str | None) -> None:
    client = AsyncMock()
    client.acl_whoami.return_value = identity
    with pytest.raises(RuntimeError, match="identity"):
        await verify_redis_identity(client, "worker")


@pytest.mark.asyncio
async def test_expected_server_identity_is_accepted() -> None:
    client = AsyncMock()
    client.acl_whoami.return_value = "alert_worker"
    await verify_redis_identity(client, "worker")
