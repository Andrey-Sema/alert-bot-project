"""Recover source posts missed while the Telegram client was disconnected."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Protocol

from pydantic import ValidationError

from alert_bot_project.core_shared.schemas import AlertMessage
from alert_bot_project.scraper.outbox import ScraperOutbox


class HistoryMessage(Protocol):
    id: int
    date: datetime | None
    text: str | None
    caption: str | None


class HistoryClient(Protocol):
    def get_chat_history(self, chat_id: int) -> AsyncIterator[HistoryMessage]: ...


async def catch_up_channel(
    client: HistoryClient,
    outbox: ScraperOutbox,
    chat_id: int,
    *,
    now: datetime | None = None,
) -> int:
    """Persist the gap before advancing a monotonic source checkpoint.

    On first deployment, bootstrap from the last 15 minutes of accessible
    history. Subsequent scans go back to the persisted checkpoint.
    """
    checkpoint = await outbox.checkpoint(chat_id)
    cutoff = (now or datetime.now(UTC)) - timedelta(minutes=15)
    highest_id: int | None = None
    recovered = 0
    async for message in client.get_chat_history(chat_id):
        if highest_id is None:
            highest_id = message.id
        if checkpoint is not None and message.id <= checkpoint:
            break
        if message.date is None:
            raise ValueError("Source history has a post without a timestamp")
        source_time = message.date.replace(tzinfo=UTC) if message.date.tzinfo is None else message.date.astimezone(UTC)
        if checkpoint is None and source_time < cutoff:
            break
        raw_text = message.text or message.caption
        if not raw_text:
            continue
        try:
            payload = AlertMessage(message_id=message.id, chat_id=chat_id, raw_text=raw_text, timestamp=source_time)
        except ValidationError:
            continue
        await outbox.put(chat_id, message.id, payload.model_dump_json())
        recovered += 1
    if highest_id is not None:
        await outbox.advance_checkpoint(chat_id, highest_id)
    return recovered
