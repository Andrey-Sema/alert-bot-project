import logging
from datetime import datetime
from typing import Optional, List
from sqlalchemy import select, exists
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis
from alert_bot_project.core_shared.constants import MAX_CUSTOM_TRIGGERS, ODESA_LOCS, OUTSIDE_LOCS
from alert_bot_project.database.models import UserTrigger
from alert_bot_project.database.crud import (
    get_or_create_user, add_user_trigger, remove_user_trigger,
    update_user_potvory, update_user_mute
)

logger = logging.getLogger("services.user_service")


class UserService:
    def __init__(self, db_session: AsyncSession, redis_client: Redis):
        self.session = db_session
        self.redis = redis_client

    async def toggle_location(self, user_id: int, location_key: str) -> tuple[bool, str]:
        user = await get_or_create_user(self.session, user_id)

        if location_key in user.triggers_set:
            await remove_user_trigger(self.session, user_id, location_key)
            return False, "Локацію видалено з моніторингу"
        else:
            await add_user_trigger(self.session, user_id, location_key)
            return True, "Локацію додано до моніторингу"

    async def add_custom_trigger(self, user_id: int, trigger_word: str) -> tuple[bool, str]:
        user = await get_or_create_user(self.session, user_id)
        static_keys = set(ODESA_LOCS.keys()) | set(OUTSIDE_LOCS.keys())
        custom_count = len([t for t in user.triggers_set if t not in static_keys])

        if custom_count >= MAX_CUSTOM_TRIGGERS:
            return False, "🚫 Ви вже досягли ліміту у 5 кастомних локацій."

        success = await add_user_trigger(self.session, user_id, trigger_word)
        if success:
            await self.redis.sadd("global_custom_triggers", trigger_word)
            return True, "Локацію додано"

        return False, "⚠️ Не вдалося зберегти кастомну локацію."

    async def delete_custom_trigger(self, user_id: int, trigger_word: str) -> tuple[bool, str]:
        await remove_user_trigger(self.session, user_id, trigger_word)

        user = await get_or_create_user(self.session, user_id)
        await self.session.refresh(user, attribute_names=['triggers_rel'])

        stmt = select(exists().where(UserTrigger.trigger_word == trigger_word))
        res = await self.session.execute(stmt)
        if not res.scalar():
            await self.redis.srem("global_custom_triggers", trigger_word)

        return True, "Локацію видалено"

    async def set_threat_categories(self, user_id: int, categories: List[str]) -> str:
        await update_user_potvory(self.session, user_id, categories)
        return "Налаштування категорій повітряних загроз оновлено"

    async def apply_mute_timeout(self, user_id: int, expiration: Optional[datetime], message_text: str) -> str:
        await update_user_mute(self.session, user_id, expiration)
        return message_text