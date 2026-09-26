"""Actual Redis 7.2 ACLs on the separate disposable CI broker (port 6380)."""

import asyncio
import json
import os
import time
import urllib.request
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from prometheus_client.parser import text_string_to_metric_families
from redis.asyncio import Redis
from redis.exceptions import AuthenticationError, ResponseError

from alert_bot_project.core_shared.redis_acl import USERS
from alert_bot_project.core_shared.redis_connection import verify_redis_identity
from alert_bot_project.core_shared.trigger_cache import reconcile_custom_trigger_cache, update_custom_trigger_cache
from alert_bot_project.scraper.publisher import PUBLISH_ONCE_LUA
from alert_bot_project.services.privacy import BEGIN_DELIVERY_LUA, END_DELIVERY_LUA, delete_user_data
from alert_bot_project.worker.broadcaster import POP_MATURE_TASKS_LUA, Broadcaster
from alert_bot_project.worker.delivery_lease import RELEASE_DELIVERY_LUA, DeliveryLease
from alert_bot_project.worker.rate_limit import ACQUIRE_SLOT_LUA
from alert_bot_project.worker.stream_retention import trim_acknowledged_stream


@pytest.fixture
async def acl_clients() -> AsyncIterator[dict[str, Redis]]:
    if os.getenv("GITHUB_ACTIONS") != "true":
        pytest.skip("separate disposable ACL CI containers only")
    password_dir = Path(os.environ["ACL_TEST_SECRET_DIR"])
    clients = {
        role: Redis.from_url(
            f"redis://{user}:{(password_dir / f'redis_{role}_password').read_text().strip()}@127.0.0.1:6380/0",
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=3,
        )
        for role, user in USERS.items()
    }
    admin = clients["operator"]
    try:
        assert await admin.acl_whoami() == "alert_operator"
        assert (await admin.info("server"))["redis_version"].startswith("7.2.")
        assert (await admin.config_get("appendonly"))["appendonly"] == "no"
        assert (await admin.config_get("save"))["save"] == ""
        await admin.flushdb()
        yield clients
    finally:
        await asyncio.gather(*(client.aclose() for client in clients.values()))


@pytest.mark.asyncio
async def test_named_identities_and_disabled_anonymous_access(acl_clients: dict[str, Redis]) -> None:
    for service in ("scraper", "worker", "bot_ui"):
        await verify_redis_identity(acl_clients[service], service)
    assert await acl_clients["health"].ping()
    anonymous = Redis(host="127.0.0.1", port=6380, socket_timeout=2)
    wrong_password = Redis(host="127.0.0.1", port=6380, username="alert_worker", password="incorrect")
    try:
        with pytest.raises(AuthenticationError):
            await anonymous.ping()
        with pytest.raises(AuthenticationError):
            await wrong_password.ping()
    finally:
        await anonymous.aclose()
        await wrong_password.aclose()


@pytest.mark.asyncio
async def test_scraper_atomic_publish_is_deduplicated_under_concurrency(acl_clients: dict[str, Redis]) -> None:
    scraper, admin = acl_clients["scraper"], acl_clients["operator"]
    script = scraper.register_script(PUBLISH_ONCE_LUA)
    results = await asyncio.gather(
        *(script(keys=["source:published:-100:1", "alerts_stream"], args=["PRIVATE-ACL-FIXTURE"]) for _ in range(8))
    )
    assert len([result for result in results if result]) == 1
    assert await admin.xlen("alerts_stream") == 1
    assert await scraper.expire("source:published:-100:1", 100)
    assert "source:published:-100:1" in [key async for key in scraper.scan_iter(match="source:published:*")]
    with pytest.raises(ResponseError):
        await scraper.xrange("alerts_stream")
    with pytest.raises(ResponseError):
        await scraper.set("alerts_stream", "overwrite")


@pytest.mark.asyncio
async def test_worker_delivery_lua_leases_rates_and_transactions(acl_clients: dict[str, Redis]) -> None:
    worker, admin = acl_clients["worker"], acl_clients["operator"]
    await acl_clients["scraper"].xadd("alerts_stream", {"payload": "fixture"})
    await worker.xgroup_create("alerts_stream", "workers_group", id="0-0", mkstream=True)
    source = await worker.xreadgroup("workers_group", "worker-a", {"alerts_stream": ">"}, count=1)
    await worker.xack("alerts_stream", "workers_group", source[0][1][0][0])
    await worker.xgroup_delconsumer("alerts_stream", "workers_group", "worker-a")
    await worker.xtrim("alerts_stream", minid="0-0", approximate=False)
    assert await trim_acknowledged_stream(worker, "alerts_stream") >= 0

    broadcaster = Broadcaster(AsyncMock(), worker)
    await broadcaster.ensure_delivery_group()
    assert await broadcaster.enqueue_alert(-100, 42, 7, source_timestamp=datetime.now(UTC))
    assert not await broadcaster.enqueue_alert(-100, 42, 7, source_timestamp=datetime.now(UTC))
    assert await worker.zcard("delayed_alerts_queue") == 2
    response = await worker.xreadgroup("delivery_workers", "worker-a", {"delivery_stream": ">"}, count=1)
    message_id = response[0][1][0][0]
    lease = DeliveryLease(worker, "delivery_stream", "delivery_workers", "worker-a", message_id, "fixture")
    assert await lease.renew()
    assert await worker.eval(RELEASE_DELIVERY_LUA, 1, lease.key, lease.token) == 1
    assert (
        await worker.eval(BEGIN_DELIVERY_LUA, 3, "privacy:deleted:7", "privacy:generation:7", "privacy:inflight:7", "0")
        == 1
    )
    assert await worker.eval(END_DELIVERY_LUA, 1, "privacy:inflight:7") == 1
    assert (
        await worker.eval(
            ACQUIRE_SLOT_LUA, 3, "telegram:rate:global", "telegram:rate:chat:7", "telegram:rate:repeat", "0"
        )
        == 0
    )
    pipe = worker.pipeline(transaction=True)
    pipe.set("delivery:stage:fixture:1", "sent", ex=60)
    pipe.xack("delivery_stream", "delivery_workers", message_id)
    assert await pipe.execute() == [True, 1]
    assert (
        await worker.eval(
            POP_MATURE_TASKS_LUA, 2, "delayed_alerts_queue", "delivery_stream", int(time.time()) + 10000, 50
        )
        == 2
    )
    assert await admin.xlen("delivery_stream") == 3


@pytest.mark.asyncio
async def test_three_stage_send_and_dead_letter_under_worker_acl(
    acl_clients: dict[str, Redis], monkeypatch: pytest.MonkeyPatch
) -> None:
    worker, admin = acl_clients["worker"], acl_clients["operator"]
    bot = AsyncMock()
    broadcaster = Broadcaster(bot, worker)
    monkeypatch.setattr(broadcaster, "_is_night", lambda: True)
    monkeypatch.setattr(broadcaster, "_db_mute_active", AsyncMock(return_value=False))
    monkeypatch.setattr(broadcaster, "_record_delivered", AsyncMock())
    await broadcaster.ensure_delivery_group()
    assert await broadcaster.enqueue_alert(-100, 99, 7, source_timestamp=datetime.now(UTC))
    first = await worker.xreadgroup("delivery_workers", "worker-a", {"delivery_stream": ">"}, count=1)
    first_id, fields = first[0][1][0]
    await broadcaster._deliver_one(first_id, fields)
    assert await admin.get("delivery:stage:-100:99:7:1") == "sent"
    assert (
        await worker.eval(
            POP_MATURE_TASKS_LUA, 2, "delayed_alerts_queue", "delivery_stream", int(time.time()) + 10000, 50
        )
        == 2
    )
    later = await worker.xreadgroup("delivery_workers", "worker-a", {"delivery_stream": ">"}, count=2)
    for message_id, payload in later[0][1]:
        await broadcaster._deliver_one(message_id, payload)
    assert bot.send_message.await_count == 3
    assert await admin.get("delivery:stage:-100:99:7:3") == "sent"
    assert (await admin.xpending("delivery_stream", "delivery_workers"))["pending"] == 0
    failed_id = await admin.xadd("delivery_stream", fields)
    await worker.xreadgroup("delivery_workers", "worker-a", {"delivery_stream": ">"}, count=1)
    await broadcaster._move_to_dlq(failed_id, fields["payload"], "fixture", "delivery:stage:fixture")
    assert await admin.xlen("delivery_dead_letter_queue") == 1
    assert await admin.get("delivery:stage:fixture") == "failed"


@pytest.mark.asyncio
async def test_ui_deletes_user_payloads_without_breaking_other_recipients(acl_clients: dict[str, Redis]) -> None:
    ui, worker, admin = acl_clients["bot_ui"], acl_clients["worker"], acl_clients["operator"]
    broadcaster = Broadcaster(AsyncMock(), worker)
    await broadcaster.ensure_delivery_group()
    for user_id in (7, 8):
        assert await broadcaster.enqueue_alert(-100, 42, user_id, source_timestamp=datetime.now(UTC))
    await admin.xadd("delivery_dead_letter_queue", {"payload": json.dumps({"chat_id": "7"})})
    await admin.set("user_mute:7", "1")
    await admin.set("telegram:blocked:7", "1")
    await admin.set("telegram:rate:chat:7", "1")
    await delete_user_data(AsyncMock(), ui, 7)
    assert await admin.exists("user_mute:7", "telegram:blocked:7", "telegram:rate:chat:7") == 0
    assert await admin.xlen("delivery_stream") == 1
    assert await admin.xlen("delivery_dead_letter_queue") == 0
    assert await admin.zcard("delayed_alerts_queue") == 2
    assert await ui.get("privacy:deleted:7") == "1"
    assert not await broadcaster.enqueue_alert(-100, 43, 7, source_timestamp=datetime.now(UTC))
    with pytest.raises(ResponseError):
        await worker.set("privacy:deleted:7", "0")
    with pytest.raises(ResponseError):
        await worker.eval("return redis.call('SET', ARGV[1], ARGV[2])", 0, "privacy:deleted:7", "0")
    assert await admin.get("privacy:deleted:7") == "1"


@pytest.mark.asyncio
async def test_trigger_reconciliation_and_ui_throttle_work(acl_clients: dict[str, Redis]) -> None:
    ui, worker = acl_clients["bot_ui"], acl_clients["worker"]
    assert await ui.set("throttle:7", "1", nx=True, px=500)
    assert await update_custom_trigger_cache(ui, "sirena", add=True)
    version = await worker.get("global_custom_triggers:version")
    assert await reconcile_custom_trigger_cache(worker, {"sirena", "port"}, version) == 1
    version = await worker.get("global_custom_triggers:version")
    assert await reconcile_custom_trigger_cache(worker, {"sirena", "port"}, version) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["scraper", "worker", "bot_ui", "monitor", "health"])
async def test_role_boundaries_and_admin_commands_are_denied(acl_clients: dict[str, Redis], role: str) -> None:
    client, admin = acl_clients[role], acl_clients["operator"]
    with pytest.raises(ResponseError):
        await client.get("foreign:secret")
    with pytest.raises(ResponseError):
        await client.set("foreign:secret", "overwrite")
    assert await admin.execute_command("ACL", "DRYRUN", USERS[role], "PING") == "OK"
    for command in (
        ("FLUSHALL",),
        ("CONFIG", "SET", "maxmemory", "0"),
        ("ACL", "SETUSER", "backdoor", "on"),
        ("SHUTDOWN",),
        ("SLOWLOG", "GET"),
        ("SELECT", "1"),
        ("PUBLISH", "private", "fixture"),
    ):
        # DRYRUN returns a bulk string for a denial, rather than a RESP error.
        result = await admin.execute_command("ACL", "DRYRUN", USERS[role], *command)
        assert isinstance(result, str)
        assert "has no permissions" in result
    if role in ("worker", "bot_ui", "monitor", "health"):
        with pytest.raises(ResponseError):
            await client.xadd("alerts_stream", {"payload": "forged"})
    if role == "bot_ui":
        with pytest.raises(ResponseError):
            await client.xadd("delivery_stream", {"payload": "forged"})
    if role == "monitor":
        assert (await client.info())["redis_version"].startswith("7.2.")
        with pytest.raises(ResponseError):
            await client.scan()
    if role == "health":
        with pytest.raises(ResponseError):
            await client.info()


@pytest.mark.asyncio
async def test_pinned_exporter_scrapes_without_payload_access(acl_clients: dict[str, Redis]) -> None:
    await acl_clients["operator"].xadd("alerts_stream", {"payload": "PRIVATE-ACL-FIXTURE"})

    def read_metrics() -> str:
        # Fixed loopback endpoint of the disposable pinned CI exporter.
        with urllib.request.urlopen("http://127.0.0.1:9122/metrics", timeout=5) as response:
            return response.read().decode()

    for _ in range(25):
        try:
            metrics = await asyncio.to_thread(read_metrics)
        except OSError:
            await asyncio.sleep(0.2)
            continue
        samples = {
            sample.name: sample.value for family in text_string_to_metric_families(metrics) for sample in family.samples
        }
        if samples.get("redis_up") == 1:
            break
        await asyncio.sleep(0.2)
    else:
        pytest.fail("Pinned exporter could not scrape under its limited ACL")
    assert samples.get("redis_exporter_last_scrape_error") == 0
    assert "PRIVATE-ACL-FIXTURE" not in metrics
