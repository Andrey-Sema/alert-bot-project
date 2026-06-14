from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Telegram Bot Settings
    BOT_TOKEN: str = Field(..., description="Official UI bot token obtained from BotFather")
    GROUP_ID: int = Field(..., description="Target channel or group ID to parse threat monitoring data from")

    # Userbot (Pyrogram) Settings
    API_ID: int = Field(..., description="API ID from my.telegram.org")
    API_HASH: str = Field(..., description="API Hash from my.telegram.org")

    # Infrastructure Settings (Supabase & Redis)
    DATABASE_URL: str = Field(..., description="Connection string for PostgreSQL / Supabase")
    REDIS_URL: str = Field("redis://localhost:6379/0", description="Connection string for Redis instance")

    # Quiet Hours (Night Mode) Settings
    NIGHT_START_HOUR: int = Field(22, description="Start hour for quiet hours/night mode status")
    NIGHT_END_HOUR: int = Field(7, description="End hour for quiet hours/night mode status")

    # Production Logging Engine Configuration
    LOG_LEVEL: str = Field("INFO", description="Global application logging threshold level")
    LOG_DIR: str = Field("/data/logs", description="Directory where production rotational log files are persistent")
    LOG_MAX_BYTES: int = Field(20971520, description="Maximum individual file size boundary before rotation triggers")
    LOG_BACKUP_COUNT: int = Field(5, description="Ceiling buffer count of historical rotated log files to retain")

    # Fix: Removed magic numbers by adding configurable network threshold parameters
    TELEGRAM_MAX_RETRY_SECONDS: int = Field(180, description="Maximum total allowed cumulative sleep duration for Telegram 429 backoff")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


config = Settings()