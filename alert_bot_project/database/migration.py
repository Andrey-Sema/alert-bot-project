import asyncio
import logging
import ssl
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import delete, pool, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alert_bot_project.core_shared.secrets import load_secret
from alert_bot_project.database.models import UserTrigger

logger = logging.getLogger("database.migration")

MIGRATION_MAP = {
    "город": "city",
    "центр": "center",
    "черемушки": "cheremushki",
    "port": "port",
    "молдованка": "moldovanka",
    "бугаевка": "bugaevka",
    "слободка": "slobodka",
    "таирово": "tairovo",
    "совиньон": "sovignon",
    "ланжерон": "lanzheron",
    "поселок": "kotovskogo",
    "поскот": "kotovskogo",
    "южный": "yuzhny_dist",
    "фонтанка": "fontanka",
    "пересыпь": "peresyp",
    "аркадия": "arkadia",
    "берег": "coast",
    "усатово": "usatovo",
    "южное": "yuzhne",
    "беляевк": "belyaevka",
    "овидиополь": "ovidiopol",
    "черноморск": "chernomorsk",
    "черноморка": "chernomorka",
    "новые беляр": "novi_belyari",
    "reni": "reni",
    "измаил": "izmail",
    "татарбунар": "tatarbunary",
    "березовк": "berezovka",
    "вилково": "vilkovo",
    "авангард": "avangard",
    "лиманк": "limanka",
    "заток": "zatoka",
    "белгород": "belgorod",
    "теплодар": "teplodar",
    "доброслав": "dobroslav",
    "тузлы": "tuzly",
}


def _upgrade_schema() -> None:
    alembic_ini = Path(__file__).resolve().parents[2] / "alembic.ini"
    configuration = Config(str(alembic_ini))
    command.upgrade(configuration, "head")


class LegacyMigrationManager:
    """Вся миграционная логика инкапсулирована в класс для консистентности с проектом."""

    @classmethod
    async def init_database_schema(cls) -> None:
        """Apply versioned, transactional Alembic revisions."""
        await asyncio.to_thread(_upgrade_schema)

    @classmethod
    async def run_legacy_keys_migration(cls, session: AsyncSession) -> None:
        """Мигрирует старые текстовые триггеры в новые инвариантные ключи."""
        async with session.begin():
            stmt_check = select(UserTrigger).where(UserTrigger.trigger_word.in_(list(MIGRATION_MAP.keys())))
            res = await session.execute(stmt_check)
            legacy_entries = res.scalars().all()

            if not legacy_entries:
                logger.info("No legacy keys found. Database is up to date.")
                return

            logger.info("Found %d legacy keys. Starting data conversion...", len(legacy_entries))
            for entry in legacy_entries:
                new_key = MIGRATION_MAP.get(entry.trigger_word)

                async with session.begin_nested():
                    try:
                        stmt_update = (
                            update(UserTrigger)
                            .where(UserTrigger.user_id == entry.user_id, UserTrigger.trigger_word == entry.trigger_word)
                            .values(trigger_word=new_key)
                        )
                        await session.execute(stmt_update)
                    except IntegrityError:
                        await session.execute(
                            delete(UserTrigger).where(
                                UserTrigger.user_id == entry.user_id, UserTrigger.trigger_word == entry.trigger_word
                            )
                        )

        logger.info("Data keys migration finalized successfully.")


async def standalone_bootstrap() -> None:
    """Безопасный CLI-стартер для выполнения миграции в изолированном контейнере."""
    from alert_bot_project.core_shared.config import config

    if config.SERVICE_ROLE != "migrator":
        raise RuntimeError("Migrator requires SERVICE_ROLE=migrator")
    migration_engine = create_async_engine(
        load_secret("MIGRATION_DATABASE_URL"),
        poolclass=pool.NullPool,
        connect_args={
            "ssl": ssl.create_default_context(),
            "timeout": 5,
            "command_timeout": 60,
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
        },
    )
    migration_sessions = async_sessionmaker(migration_engine, expire_on_commit=False)
    logger.info("Starting manual safe database schema keys conversion routine...")
    try:
        await LegacyMigrationManager.init_database_schema()

        async with migration_sessions() as session:
            await LegacyMigrationManager.run_legacy_keys_migration(session)

        logger.info("Data migration workflow finalized cleanly.")
    except (OperationalError, ConnectionRefusedError):
        logger.exception("Database connection failure during migration bootstrap")
        raise
    except Exception:
        logger.exception("Uncaught critical exception during standalone migration execution")
        raise
    finally:
        await migration_engine.dispose()


if __name__ == "__main__":
    from alert_bot_project.core_shared.logging_config import setup_logging

    setup_logging("database_migration")

    try:
        asyncio.run(standalone_bootstrap())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Migration process terminated by system or user interrupt.")
        raise  # ✅ ФИКС С СОНАРОМ (python:S5754): Обязательный re-raise для корректного выхода операционной системы
