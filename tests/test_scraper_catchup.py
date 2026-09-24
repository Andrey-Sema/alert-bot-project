"""Recovery of Telegram history into the durable local outbox."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from alert_bot_project.scraper.catchup import catch_up_channel
from alert_bot_project.scraper.outbox import ScraperOutbox


class FakeHistory:
    def __init__(self, posts: list[SimpleNamespace]) -> None:
        self.posts = posts

    async def get_chat_history(self, _chat_id: int):
        for post in self.posts:
            yield post


@pytest.mark.asyncio
@settings(max_examples=20, deadline=None)
@given(gap=st.integers(min_value=1, max_value=30))
async def test_ten_minute_disconnect_recovers_each_source_id_once(gap: int) -> None:
    with TemporaryDirectory() as directory:
        outbox = ScraperOutbox(str(Path(directory) / "catchup.sqlite3"))
        await outbox.advance_checkpoint(-100, 100)
        now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
        posts = [
            SimpleNamespace(id=message_id, date=now - timedelta(minutes=10), text=f"threat {message_id}", caption=None)
            for message_id in range(101, 101 + gap)
        ]
        posts.append(SimpleNamespace(id=100, date=now - timedelta(minutes=11), text="old", caption=None))
        history = FakeHistory(list(reversed(posts[:-1])) + posts[-1:])
        assert await catch_up_channel(history, outbox, -100, now=now) == gap
        assert await outbox.checkpoint(-100) == 100 + gap
        assert await catch_up_channel(history, outbox, -100, now=now) == 0
        pending = await outbox.pending(limit=gap + 1)
        assert [message_id for _, message_id, _ in pending] == list(range(101, 101 + gap))
        assert all(json.loads(payload)["timestamp"] == "2026-09-24T11:50:00Z" for _, _, payload in pending)


@pytest.mark.asyncio
async def test_incomplete_history_scan_keeps_checkpoint_for_retry(tmp_path: Path) -> None:
    outbox = ScraperOutbox(str(tmp_path / "retry.sqlite3"))
    await outbox.advance_checkpoint(-100, 10)
    now = datetime.now(UTC)
    history = FakeHistory(
        [SimpleNamespace(id=number, date=now, text="threat", caption=None) for number in (13, 12, 11, 10)]
    )
    original_put = outbox.put

    async def failing_put(chat_id: int, message_id: int, payload: str) -> None:
        if message_id == 12:
            raise OSError("disk unavailable")
        await original_put(chat_id, message_id, payload)

    outbox.put = failing_put  # type: ignore[method-assign]
    with pytest.raises(OSError, match="disk unavailable"):
        await catch_up_channel(history, outbox, -100, now=now)
    assert await outbox.checkpoint(-100) == 10
    outbox.put = original_put  # type: ignore[method-assign]
    assert await catch_up_channel(history, outbox, -100, now=now) == 3
    assert [message_id for _, message_id, _ in await outbox.pending()] == [11, 12, 13]
