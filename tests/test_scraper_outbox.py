from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from alert_bot_project.scraper.outbox import ScraperOutbox


@pytest.mark.asyncio
@settings(max_examples=30, deadline=None)
@given(payload=st.text(max_size=500))
async def test_outbox_survives_reopen_and_treats_payload_as_data(payload: str) -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "outbox.sqlite3"
        outbox = ScraperOutbox(str(path))
        await outbox.put(-100, 7, payload)
        await outbox.put(-100, 7, "replacement")
        reopened = ScraperOutbox(str(path))
        assert await reopened.pending() == [(-100, 7, payload)]
        await reopened.delete(-100, 7)
        assert await outbox.pending() == []
