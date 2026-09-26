"""Real asyncio failure/cancellation races and worker resource teardown."""

import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from alert_bot_project.core_shared.supervision import supervise


@pytest.mark.parametrize("mode", ["return", "raise", "cancel"])
async def test_unexpected_exit_stops_and_joins_siblings(mode: str) -> None:
    shutdown, started, cleaned = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def sibling() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    async def failed() -> None:
        await started.wait()
        if mode == "raise":
            raise ValueError("original failure")
        if mode == "cancel":
            raise asyncio.CancelledError

    with pytest.raises(RuntimeError, match="Critical loop") as caught:
        async with asyncio.timeout(1):
            await supervise({"sibling": sibling, "failed": failed}, shutdown)
    assert shutdown.is_set()
    assert cleaned.is_set()
    if mode == "raise":
        assert isinstance(caught.value.__cause__, ValueError)


async def test_requested_shutdown_is_normal_and_joins_all_tasks() -> None:
    shutdown = asyncio.Event()
    cleaned: list[int] = []

    async def stop() -> None:
        await asyncio.sleep(0)
        shutdown.set()

    async def sibling() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.append(1)

    await supervise({"stop": stop, "sibling": sibling}, shutdown)
    assert cleaned == [1]


async def test_parent_cancellation_propagates_after_child_cleanup() -> None:
    started, cleaned, shutdown = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def child() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    parent = asyncio.create_task(supervise({"child": child}, shutdown))
    await started.wait()
    parent.cancel()
    with pytest.raises(asyncio.CancelledError):
        await parent
    assert cleaned.is_set()
    assert shutdown.is_set()


async def test_factory_failure_still_joins_previously_started_tasks() -> None:
    shutdown = asyncio.Event()

    async def child() -> None:
        await asyncio.Event().wait()

    def broken_factory() -> None:
        raise ValueError("factory failed")

    with pytest.raises(ValueError, match="factory failed"):
        await supervise({"child": child, "broken": broken_factory}, shutdown)
    assert shutdown.is_set()
    assert not any(task.get_name() == "child" for task in asyncio.all_tasks())


async def test_already_stopped_does_not_start_factories() -> None:
    shutdown = asyncio.Event()
    shutdown.set()
    factory = MagicMock()
    await supervise({"child": factory}, shutdown)
    factory.assert_not_called()


@given(turns=st.integers(min_value=0, max_value=15))
@settings(deadline=None, max_examples=20)
async def test_failure_and_shutdown_race_does_not_hide_exception(turns: int) -> None:
    shutdown = asyncio.Event()

    async def failed() -> None:
        for _ in range(turns):
            await asyncio.sleep(0)
        shutdown.set()
        raise ValueError("failure at shutdown")

    with pytest.raises(RuntimeError, match="failed"):
        await supervise({"failed": failed}, shutdown)


@pytest.mark.parametrize("failure", ["startup", "delivery", "source", "alarm", "shutdown"])
async def test_worker_main_supervises_loops_and_closes_connections(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from alert_bot_project.worker import main as worker

    shutdown = asyncio.Event()
    monkeypatch.setattr(worker, "shutdown_event", shutdown)
    monkeypatch.setattr(worker.config, "SERVICE_ROLE", "worker")
    monkeypatch.setattr(worker, "start_metrics_server", MagicMock())
    monkeypatch.setattr(asyncio.get_running_loop(), "add_signal_handler", MagicMock())
    session = MagicMock()
    session.return_value.__aenter__ = AsyncMock()
    session.return_value.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(worker, "AsyncSessionLocal", session)
    monkeypatch.setattr(worker, "verify_runtime_privileges", AsyncMock())
    redis = MagicMock(aclose=AsyncMock())
    bot = SimpleNamespace(session=SimpleNamespace(close=AsyncMock()))
    monkeypatch.setattr(worker, "create_service_redis", lambda: redis)
    monkeypatch.setattr(worker, "Bot", lambda **_kwargs: bot)
    monkeypatch.setattr(worker, "verify_redis_identity", AsyncMock())
    for name in ("init_redis_consumer_group", "cleanup_dead_consumers", "sync_global_custom_triggers"):
        monkeypatch.setattr(worker, name, AsyncMock())
    if failure == "startup":
        monkeypatch.setattr(worker, "init_redis_consumer_group", AsyncMock(side_effect=ValueError("startup")))

    cleaned: set[str] = set()

    async def loop(name: str) -> None:
        try:
            await asyncio.sleep(0)
            if name == failure:
                raise ValueError(name)
            if failure == "shutdown":
                shutdown.set()
            await shutdown.wait()
        finally:
            cleaned.add(name)

    broadcaster = SimpleNamespace(
        workers_count=2,
        ensure_delivery_group=AsyncMock(),
        process_delivery_stream=lambda _index: loop("delivery"),
        process_delayed_alerts=lambda: loop("delayed"),
    )
    monkeypatch.setattr(worker, "Broadcaster", lambda *_args: broadcaster)
    monkeypatch.setattr(worker, "_drain_pending_backlog", AsyncMock())
    monkeypatch.setattr(worker, "_consume_loop", lambda *_args: loop("source"))
    for name in (
        "auto_claim_pending_tasks",
        "monitor_dlq_backlog",
        "reconcile_custom_triggers",
        "maintain_activity_retention",
    ):
        monkeypatch.setattr(worker, name, lambda *_args, name=name: loop(name))
    # Disabled official API must be allowed to finish normally; enabled API is critical.
    alarm = SimpleNamespace(client=object() if failure == "alarm" else None)
    alarm.run = (lambda _event: loop("alarm")) if failure == "alarm" else AsyncMock()
    monkeypatch.setattr(worker, "AlarmStatePoller", lambda *_args: alarm)
    async with asyncio.timeout(1):
        if failure == "shutdown":
            await worker.main()
        else:
            with pytest.raises((RuntimeError, ValueError)):
                await worker.main()
    redis.aclose.assert_awaited_once()
    bot.session.close.assert_awaited_once()
    assert shutdown.is_set()
    if failure != "startup":
        assert "delivery" in cleaned
        assert "source" in cleaned
        assert "delayed" in cleaned


@pytest.mark.parametrize("failure", ["startup", "replay", "catchup", "shutdown"])
async def test_scraper_main_joins_loops_before_closing_providers(monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    import pyrogram

    from alert_bot_project.core_shared.config import config

    monkeypatch.setattr(config, "SERVICE_ROLE", "scraper")
    app = SimpleNamespace(start=AsyncMock(), stop=AsyncMock(), on_message=lambda *_args: lambda function: function)
    monkeypatch.setattr(pyrogram, "Client", lambda **_kwargs: app)
    scraper = importlib.import_module("alert_bot_project.scraper.main")
    monkeypatch.setattr(scraper, "app", app)
    publisher = SimpleNamespace(close=AsyncMock())
    monkeypatch.setattr(scraper, "publisher", publisher)
    shutdown = asyncio.Event()
    monkeypatch.setattr(scraper, "shutdown_event", shutdown)
    monkeypatch.setattr(scraper, "start_metrics_server", MagicMock())
    monkeypatch.setattr(scraper, "setup_signal_handlers", MagicMock())
    cleaned: set[str] = set()

    async def loop(name: str) -> None:
        try:
            await asyncio.sleep(0)
            if failure == name:
                raise ValueError(name)
            if failure == "shutdown":
                shutdown.set()
            await shutdown.wait()
        finally:
            cleaned.add(name)

    monkeypatch.setattr(scraper, "replay_outbox", lambda: loop("replay"))
    monkeypatch.setattr(scraper, "catchup_loop", lambda: loop("catchup"))
    # Marker migration is intentionally allowed to finish normally.
    monkeypatch.setattr(scraper, "expire_legacy_source_markers", AsyncMock())
    if failure == "startup":
        app.start.side_effect = ValueError("startup")
    async with asyncio.timeout(1):
        if failure == "shutdown":
            await scraper.main()
        else:
            with pytest.raises((RuntimeError, ValueError)):
                await scraper.main()
    app.stop.assert_awaited_once()
    publisher.close.assert_awaited_once()
    assert shutdown.is_set()
    if failure != "startup":
        assert cleaned == {"replay", "catchup"}
