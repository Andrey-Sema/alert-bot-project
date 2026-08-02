from datetime import UTC, datetime

from pydantic import BaseModel, Field


class AlertMessage(BaseModel):
    """Data contract for message serialization between scraper and worker."""

    message_id: int = Field(..., description="Telegram message ID")
    chat_id: int = Field(..., description="Source channel ID")

    # Защита воркера от High-Load спама и переполнения буфера памяти
    raw_text: str = Field(..., max_length=4096, description="Raw text message content")

    # Гарантирует генерацию корректного UTC-времени строго в момент создания инстанса
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="UTC time when the message was captured"
    )
