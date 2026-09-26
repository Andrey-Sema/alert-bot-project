"""Bounded, canonical contract for Redis delivery jobs (including legacy jobs)."""

import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

MAX_JOB_BYTES = 32768
FRESHNESS_SECONDS = 600
MAX_DELIVERY_AGE_SECONDS = 604800
HISTORICAL_NOTICE = (
    "⚠️ Затримане повідомлення про загрозу. Воно може бути неактуальним; перевірте поточний стан в офіційних джерелах."
)


class DeliveryJob(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chat_id: StrictInt = Field(ge=-(2**53 - 1), le=2**53 - 1)
    step: Literal[1, 2, 3]
    text: str = Field(min_length=1, max_length=4096, strict=True)
    silent: StrictBool = False
    event_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=r"^[\w:-]+$", strict=True)
    source_chat_id: StrictInt | None = Field(default=None, ge=-(2**53 - 1), le=2**53 - 1)
    source_message_id: StrictInt | None = Field(default=None, gt=0, le=2**31 - 1)
    source_timestamp: AwareDatetime | None = None
    source_locations: list[str] = Field(default_factory=list, max_length=64)
    recipient_generation: str = Field(default="0", min_length=1, max_length=64, strict=True)

    @field_validator("chat_id", mode="before")
    @classmethod
    def canonical_chat_id(cls, value: Any) -> int:
        # Lua producers store IDs as strings to avoid cjson floating-point loss.
        if isinstance(value, str) and value == str(int(value)):
            value = int(value)
        if type(value) is not int or value == 0:
            raise ValueError("Invalid recipient ID")
        return value

    @field_validator("step", mode="before")
    @classmethod
    def strict_step(cls, value: Any) -> int:
        if type(value) is not int:
            raise ValueError("Invalid step type")
        return value

    @field_validator("source_locations")
    @classmethod
    def location_keys(cls, values: list[str]) -> list[str]:
        if any(
            not value or len(value) > 64 or not value.replace("_", "").replace("-", "").isalnum() for value in values
        ):
            raise ValueError("Invalid location key")
        return values

    @field_validator("source_timestamp")
    @classmethod
    def source_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value - datetime.now(UTC)).total_seconds() > 300:
            raise ValueError("Invalid source time")
        return value.astimezone(UTC) if value is not None else None

    @field_validator("source_timestamp", mode="before")
    @classmethod
    def source_time_type(cls, value: Any) -> Any:
        if value is not None and not isinstance(value, str | datetime):
            raise ValueError("Invalid source timestamp type")
        return value

    @model_validator(mode="after")
    def consistent_identity(self) -> "DeliveryJob":
        if (self.source_chat_id is None) != (self.source_message_id is None):
            raise ValueError("Incomplete source identity")
        if self.source_chat_id is not None:
            expected = f"{self.source_chat_id}:{self.source_message_id}:{self.chat_id}"
            if self.event_id != expected:
                raise ValueError("Inconsistent event identity")
        if self.step > 1 and self.event_id is None:
            raise ValueError("Missing event identity")
        return self


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON member")
        result[key] = value
    return result


def parse_delivery_job(payload: str) -> DeliveryJob:
    if len(payload.encode("utf-8")) > MAX_JOB_BYTES:
        raise ValueError("Oversized delivery job")
    value = json.loads(payload, object_pairs_hook=_unique_object)
    if not isinstance(value, dict):
        raise ValueError("Delivery job must be an object")
    return DeliveryJob.model_validate(value)


def delivery_content(job: DeliveryJob, text: str, silent: bool) -> tuple[str, bool] | None:
    """Recheck freshness after queue and rate waits, immediately before send."""
    age = (datetime.now(UTC) - job.source_timestamp).total_seconds() if job.source_timestamp else None
    if age is not None and age > MAX_DELIVERY_AGE_SECONDS:
        return None
    if age is None or age > FRESHNESS_SECONDS:
        if job.step > 1:
            return None
        from alert_bot_project.core_shared.constants import ALERT_FIRST

        context = text.removeprefix(ALERT_FIRST)
        return (HISTORICAL_NOTICE + context)[:4096], True
    return text, silent
