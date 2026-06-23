import asyncio
import logging
from sqlalchemy import update, select, delete
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from alert_bot_project.database.models import UserTrigger, Base
from alert_bot_project.database.engine import engine

logger = logging.getLogger("database.migration")

MIGRATION_MAP = {
    "город": "city", "центр": "center", "черемушки": "cheremushki", "port": "port",
    "молдованка": "moldovanka", "бугаевка": "bugaevka", "слободка": "slobodka",
    "таирово": "tairovo", "совиньон": "sovignon", "ланжерон": "lanzheron",
    "поселок": "kotovskogo", "поскот": "kotovskogo", "южный": "yuzhny_dist",
    "фонтанка": "fontanka", "пересыпь": "peresyp", "аркадия": "arkadia", "берег": "coast",
    "усатово": "usatovo", "южное": "yuzhne", "беляевк": "belyaevka", "овидиополь": "ovidiopol",
    "черноморск": "chernomorsk", "черноморка": "chernomorka", "новые беляр": "novi_belyari",
    "reni": "reni", "измаил": "izmail", "татарбунар": "tatarbunary", "березовк": "berezovka",
    "вилково": "vilkovo", "авангард": "avangard", "лиманк": "limanka", "заток": "zatoka",
    "белгород": "belgorod", "теплодар": "teplodar", "доброслав": "dobroslav", "тузлы": "tuzly"
}


class LegacyMigrationManager:
    """Вся миграционная логика инкапсулирована в класс для консистентности с проектом."""

    @classmethod
    async def init_database_schema(cls) -> None:
        """Проверяет и инициализирует схему таблиц в базе данных."""
        logger.info("Перевірка та ініціалізація схеми бази даних...")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

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
                        stmt_update = update(UserTrigger).where(
                            UserTrigger.user_id == entry.user_id,
                            UserTrigger.trigger_word == entry.trigger_word
                        ).values(trigger_word=new_key)
                        await session.execute(stmt_update)
                    except IntegrityError:
                        await session.execute(delete(UserTrigger).where(
                            UserTrigger.user_id == entry.user_id,
                            UserTrigger.trigger_word == entry.trigger_word
                        ))

        logger.info("Data keys migration finalized successfully.")


async def standalone_bootstrap() -> None:
    """Безопасный CLI-стартер для выполнения миграции в изолированном контейнере."""
    from alert_bot_project.database.engine import AsyncSessionLocal

    logger.info("Starting manual safe database schema keys conversion routine...")
    try:
        await LegacyMigrationManager.init_database_schema()

        async with AsyncSessionLocal() as session:
            await LegacyMigrationManager.run_legacy_keys_migration(session)

        logger.info("Data migration workflow finalized cleanly.")
    except (OperationalError, ConnectionRefusedError):
        logger.exception("Database connection failure during migration bootstrap")
        raise
    except Exception:
        logger.exception("Uncaught critical exception during standalone migration execution")
        raise


if __name__ == "__main__":
    from alert_bot_project.core_shared.logging_config import setup_logging

    setup_logging("database_migration")

    try:
        asyncio.run(standalone_bootstrap())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Migration process terminated by system or user interrupt.")
        raise  # ✅ ФИКС С СОНАРОМ (python:S5754): Обязательный re-raise для корректного выхода операционной системы