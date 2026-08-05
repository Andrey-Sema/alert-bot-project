from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    # Application core secret, used for HMAC/salting (e.g. hashing peer IDs before logging)
    APP_SECRET_KEY: str = Field(..., description="Unique application secret for cryptographic tasks (HMAC, salts)")

    # Telegram Bot Settings
    BOT_TOKEN: str = Field(..., description="Official UI bot token obtained from BotFather")
    GROUP_IDS: Annotated[list[int], NoDecode] = Field(
        ..., description="Comma-separated list of target channel/group IDs to parse threat monitoring data from"
    )

    @field_validator("GROUP_IDS", mode="before")
    @classmethod
    def parse_group_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(item.strip()) for item in value.split(",") if item.strip()]
        return value

    # Userbot (Pyrogram) Settings
    API_ID: int = Field(..., description="API ID from my.telegram.org")
    API_HASH: str = Field(..., description="API Hash from my.telegram.org")

    # Infrastructure Settings (Supabase & Redis)
    DATABASE_URL: str = Field(..., description="Connection string for PostgreSQL / Supabase")
    REDIS_URL: str = Field("redis://localhost:6379/0", description="Connection string for Redis instance")

    # ✅ ФИКС: Добавлены строгие диапазоны портов (ge=1024, le=65535) для предотвращения системных сбоев
    METRICS_PORT_WORKER: int = Field(8000, ge=1024, le=65535, description="Prometheus metrics port for worker service")
    METRICS_PORT_SCRAPER: int = Field(
        8001, ge=1024, le=65535, description="Prometheus metrics port for scraper service"
    )
    METRICS_PORT_BOT: int = Field(8002, ge=1024, le=65535, description="Prometheus metrics port for bot UI service")

    # Quiet Hours (Night Mode) Settings
    # ✅ ФИКС: Ограничение диапазона времени (от 0 до 23 часов) на уровне валидации схемы Pydantic
    NIGHT_START_HOUR: int = Field(22, ge=0, le=23, description="Start hour for quiet hours/night mode status")
    NIGHT_END_HOUR: int = Field(7, ge=0, le=23, description="End hour for quiet hours/night mode status")

    UKRAINEALARM_API_KEY: str = Field("", description="API-ключ від api.ukrainealarm.com")
    UKRAINEALARM_REGION_ID: str | None = Field(
        None, description="ID Одеської області; якщо None — резолвиться автоматично за назвою"
    )
    OFFICIAL_ALARM_FAILSAFE: bool = Field(
        True, description="Стан офіційної тривоги, коли API недоступне (True=fail-open, безпечніше)"
    )

    # Production Logging Engine Configuration
    LOG_LEVEL: str = Field("INFO", description="Global application logging threshold level")
    LOG_DIR: str = Field("/data/logs", description="Directory where production rotational log files are persistent")
    LOG_MAX_BYTES: int = Field(20971520, description="Maximum individual file size boundary before rotation triggers")
    LOG_BACKUP_COUNT: int = Field(5, description="Ceiling buffer count of historical rotated log files to retain")

    # Fix: Removed magic numbers by adding configurable network threshold parameters
    TELEGRAM_MAX_RETRY_SECONDS: int = Field(
        180, description="Maximum total allowed cumulative sleep duration for Telegram 429 backoff"
    )

    # ✅ ФИКС: Модель-валидатор для атомарной проверки уникальности портов на этапе инициализации контейнера
    @model_validator(mode="after")
    def validate_unique_ports(self) -> "Settings":
        ports = [self.METRICS_PORT_WORKER, self.METRICS_PORT_SCRAPER, self.METRICS_PORT_BOT]
        if len(ports) != len(set(ports)):
            raise ValueError(
                f"Metrics ports must be completely unique to prevent internal network conflicts. "
                f"Provided ports: {ports}"
            )
        return self

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


config = Settings()
