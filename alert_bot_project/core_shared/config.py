import os
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from alert_bot_project.core_shared.redis_transport import validate_redis_transport_url
from alert_bot_project.core_shared.secrets import SECRET_NAMES, load_secret


class Settings(BaseSettings):
    SERVICE_ROLE: Literal["development", "worker", "bot_ui", "scraper", "migrator"] = "development"

    @model_validator(mode="before")
    @classmethod
    def load_secret_files(cls, values: dict[str, object]) -> dict[str, object]:
        service = values.get("SERVICE_ROLE", os.getenv("SERVICE_ROLE", "development"))
        if service not in ("development", "migrator") and (
            values.get("MIGRATION_DATABASE_URL") or os.getenv("MIGRATION_DATABASE_URL_FILE") is not None
        ):
            raise ValueError("Migration credentials must not be supplied to runtime services")
        forbidden_files: tuple[str, ...] = ()
        if service in ("worker", "bot_ui", "migrator"):
            forbidden_files += ("API_HASH", "PYROGRAM_SESSION_STRING")
        if service in ("scraper", "migrator"):
            forbidden_files += ("DATABASE_URL",)
        if any(os.getenv(f"{name}_FILE") is not None for name in forbidden_files):
            raise ValueError("Unrelated secret files must not be supplied to this service")
        for name in SECRET_NAMES:
            if os.getenv(f"{name}_FILE") is not None:
                values[name] = load_secret(name, max_bytes=16384 if name == "PYROGRAM_SESSION_STRING" else 4096)
        return values

    # Telegram Bot Settings
    BOT_TOKEN: str = Field("", repr=False, description="Official UI bot token obtained from BotFather")
    GROUP_ID: int = Field(0, description="Target channel or group ID to parse threat monitoring data from")

    # Userbot (Pyrogram) Settings
    API_ID: int = Field(0, description="API ID from my.telegram.org")
    API_HASH: str = Field("", repr=False, description="API Hash from my.telegram.org")

    LOG_PSEUDONYM_KEY: str = Field(..., repr=False, description="Independent random 32-byte key as 64 hex characters")
    PYROGRAM_SESSION_STRING: str = Field("", repr=False, max_length=16384)

    @field_validator("PYROGRAM_SESSION_STRING")
    @classmethod
    def bound_session_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 16384:
            raise ValueError("PYROGRAM_SESSION_STRING exceeds 16384 bytes")
        return value

    @field_validator("LOG_PSEUDONYM_KEY")
    @classmethod
    def validate_log_key(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdefABCDEF" for char in value):
            raise ValueError("LOG_PSEUDONYM_KEY must contain exactly 64 hexadecimal characters")
        if len(set(value.lower())) == 1:
            raise ValueError("LOG_PSEUDONYM_KEY must be independently randomly generated")
        return value.lower()

    @model_validator(mode="after")
    def separate_log_key(self) -> "Settings":
        if self.LOG_PSEUDONYM_KEY in (self.API_HASH.lower(), self.BOT_TOKEN.lower()):
            raise ValueError("LOG_PSEUDONYM_KEY cannot reuse Telegram credentials")
        return self

    # Infrastructure Settings (Supabase & Redis)
    DATABASE_URL: str = Field("", repr=False, description="Runtime PostgreSQL connection string")
    MIGRATION_DATABASE_URL: str = Field("", repr=False, description="Migration-only PostgreSQL connection string")
    REDIS_URL: str = Field("redis://localhost:6379/0", repr=False, description="Connection string for Redis instance")
    REDIS_TLS_CA_FILE: str | None = Field(None, description="Optional Redis TLS trust store")

    @model_validator(mode="after")
    def require_service_credentials(self) -> "Settings":
        required = {
            "development": ("BOT_TOKEN", "GROUP_ID", "API_ID", "API_HASH", "DATABASE_URL"),
            "worker": ("BOT_TOKEN", "DATABASE_URL"),
            "bot_ui": ("BOT_TOKEN", "DATABASE_URL"),
            "scraper": ("GROUP_ID", "API_ID", "API_HASH"),
            "migrator": ("MIGRATION_DATABASE_URL",),
        }[self.SERVICE_ROLE]
        if any(not getattr(self, name) for name in required):
            raise ValueError("Required service credentials are missing")
        if self.SERVICE_ROLE in ("scraper", "migrator") and self.DATABASE_URL:
            raise ValueError("Runtime DATABASE_URL must not be supplied to scraper/migrator")
        if self.SERVICE_ROLE in ("worker", "bot_ui", "migrator") and (self.API_HASH or self.PYROGRAM_SESSION_STRING):
            raise ValueError("Scraper credentials must not be supplied to this service")
        return self

    @field_validator("REDIS_URL")
    @classmethod
    def require_tls_for_external_redis(cls, value: str) -> str:
        return validate_redis_transport_url(value)

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

    UKRAINEALARM_API_KEY: str = Field("", repr=False, description="API-ключ від api.ukrainealarm.com")
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
        180, ge=1, le=180, description="Maximum wait for a shared Telegram rate slot"
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

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True
    )


config = Settings()
