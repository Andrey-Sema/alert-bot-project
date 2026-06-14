from datetime import datetime, timezone
from pydantic import BaseModel, Field


class AlertMessage(BaseModel):
    """Data contract for message serialization between scraper and worker."""
    message_id: int = Field(..., description="Telegram message ID")
    chat_id: int = Field(..., description="Source channel ID")
    # Fix: Added max_length to protect worker memory from massive spam posts
    raw_text: str = Field(..., max_length=4000, description="Raw text message content")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC time when the message was captured"
    )

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, json_str: str) -> "AlertMessage":
        return cls.model_validate_json(json_str)