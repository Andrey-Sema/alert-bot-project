"""Real TLS handshakes against a disposable loopback RESP fixture."""

import asyncio
import contextlib
import shutil
import ssl
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from hypothesis import given
from hypothesis import strategies as st
from redis.exceptions import ConnectionError as RedisConnectionError

from alert_bot_project.core_shared.config import Settings, config
from alert_bot_project.core_shared.redis_connection import create_service_redis
from alert_bot_project.core_shared.redis_transport import validate_redis_transport_url
from alert_bot_project.scripts import stress_test


@given(query=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_=%", min_size=1, max_size=100))
def test_url_parameters_cannot_override_verified_transport(query: str) -> None:
    with pytest.raises(ValueError, match="query overrides"):
        validate_redis_transport_url("rediss://cache.example/0?" + query)


@pytest.mark.parametrize(
    "suffix",
    ["?ssl_check_hostname=false", "?ssl_cert_reqs=none", "?socket_timeout=0", "?username=default", "#fragment"],
)
def test_settings_reject_security_overrides(suffix: str) -> None:
    with pytest.raises(ValueError, match="query overrides"):
        Settings.require_tls_for_external_redis("rediss://cache.example/0" + suffix)


def test_factory_checks_certificates_hostnames_and_socket_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "REDIS_URL", "rediss://cache.example:6380/0")
    monkeypatch.setattr(config, "REDIS_TLS_CA_FILE", "/operator/ca.pem")
    client = create_service_redis()
    options = client.connection_pool.connection_kwargs
    assert options["ssl_cert_reqs"] == "required"
    assert options["ssl_check_hostname"] is True
    assert options["ssl_ca_certs"] == "/operator/ca.pem"
    assert options["socket_connect_timeout"] == 3
    assert options["socket_timeout"] == 5


def test_factory_revalidates_mutated_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "REDIS_URL", "rediss://cache.example/0?ssl_check_hostname=false")
    with pytest.raises(ValueError, match="query overrides"):
        create_service_redis()


@pytest.mark.asyncio
async def test_failed_probe_closes_pool_without_printing_credentials(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    url = "rediss://account:private-value@cache.example/0"
    client = AsyncMock()
    client.ping.side_effect = RedisConnectionError(url)
    monkeypatch.setattr(stress_test, "create_service_redis", lambda _: client)
    with pytest.raises(SystemExit) as error:
        await stress_test.build_redis_client(url)
    assert error.value.code == 1
    assert "private-value" not in capsys.readouterr().out
    client.aclose.assert_awaited_once()


@pytest.fixture
async def tls_endpoint(tmp_path: Path) -> AsyncIterator[tuple[int, Path]]:
    executable = shutil.which("openssl")
    if not executable:
        git_openssl = Path("C:/Program Files/Git/usr/bin/openssl.exe")
        executable = str(git_openssl) if git_openssl.is_file() else None
    if not executable:
        pytest.fail("OpenSSL is required for the TLS acceptance tests")
    certificate, private_key = tmp_path / "server.crt", tmp_path / "server.key"
    # Trusted OpenSSL binary; every argument is fixed or a pytest temporary path.
    await asyncio.to_thread(
        subprocess.run,
        [
            executable,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-keyout",
            str(private_key),
            "-out",
            str(certificate),
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=15,
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, private_key)

    async def respond(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            async with asyncio.timeout(10):
                while header := await reader.readline():
                    arguments = []
                    for _ in range(int(header[1:])):
                        length = int((await reader.readline())[1:])
                        arguments.append(await reader.readexactly(length))
                        await reader.readexactly(2)
                    writer.write(b"+PONG\r\n" if arguments[0].upper() == b"PING" else b"+OK\r\n")
                    await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, TimeoutError):
            pass
        finally:
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()

    server = await asyncio.start_server(respond, "127.0.0.1", 0, ssl=context)
    try:
        yield server.sockets[0].getsockname()[1], certificate
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_trusted_certificate_and_matching_hostname_connect(
    monkeypatch: pytest.MonkeyPatch, tls_endpoint: tuple[int, Path]
) -> None:
    port, certificate = tls_endpoint
    monkeypatch.setattr(config, "REDIS_URL", f"rediss://localhost:{port}/0")
    monkeypatch.setattr(config, "REDIS_TLS_CA_FILE", str(certificate))
    client = create_service_redis()
    try:
        assert await client.ping() is True
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["wrong_hostname", "untrusted_certificate", "missing_ca"])
async def test_invalid_tls_identity_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tls_endpoint: tuple[int, Path], failure: str
) -> None:
    port, certificate = tls_endpoint
    hostname = "127.0.0.1" if failure == "wrong_hostname" else "localhost"
    monkeypatch.setattr(config, "REDIS_URL", f"rediss://{hostname}:{port}/0")
    trust_store = str(certificate) if failure == "wrong_hostname" else None
    if failure == "missing_ca":
        trust_store = str(certificate.parent / "missing.crt")
    monkeypatch.setattr(config, "REDIS_TLS_CA_FILE", trust_store)
    client = create_service_redis()
    try:
        with pytest.raises((RedisConnectionError, FileNotFoundError)):
            await client.ping()
    finally:
        await client.aclose()
