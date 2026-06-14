import logging
from sqlalchemy import update, select, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from alert_bot_project.database.models import UserTrigger

logger = logging.getLogger("database.migration")

MIGRATION_MAP = {
    "город": "city", "центр": "center", "черемушки": "cheremushki", "порт": "port",
    "молдованка": "moldovanka", "бугаевка": "bugaevka", "слободка": "slobodka",
    "таирово": "tairovo", "совиньон": "sovignon", "ланжерон": "lanzheron",
    "поселок": "kotovskogo", "поскот": "kotovskogo", "южный": "yuzhny_dist",
    "фонтанка": "fontanka", "пересыпь": "peresyp", "аркадия": "arkadia", "берег": "coast",
    "усатово": "usatovo", "южное": "yuzhne", "беляевк": "belyaevka", "овидиополь": "ovidiopol",
    "черноморск": "chernomorsk", "черноморка": "chernomorka", "новые беляр": "novi_belyari",
    "рени": "reni", "измаил": "izmail", "татарбунар": "tatarbunary", "березовк": "berezovka",
    "вилково": "vilkovo", "авангард": "avangard", "лиманк": "limanka", "заток": "zatoka",
    "белгород": "belgorod", "теплодар": "teplodar", "доброслав": "dobroslav", "тузлы": "tuzly"
}


async def run_legacy_keys_migration(session: AsyncSession):
    """Executes atomic batch migration for legacy location keys."""
    async with session.begin():
        stmt_check = select(UserTrigger).where(UserTrigger.trigger_word.in_(list(MIGRATION_MAP.keys())))
        res = await session.execute(stmt_check)
        legacy_entries = res.scalars().all()

        if not legacy_entries:
            logger.info("No legacy keys found.")
            return

        for entry in legacy_entries:
            new_key = MIGRATION_MAP.get(entry.trigger_word)
            try:
                # Attempt to update to the new invariant key
                stmt_update = update(UserTrigger).where(
                    UserTrigger.user_id == entry.user_id,
                    UserTrigger.trigger_word == entry.trigger_word
                ).values(trigger_word=new_key)
                await session.execute(stmt_update)
            except IntegrityError:
                # Key already exists: remove old one
                await session.execute(delete(UserTrigger).where(
                    UserTrigger.user_id == entry.user_id,
                    UserTrigger.trigger_word == entry.trigger_word
                ))
    logger.info("Migration finalized.")