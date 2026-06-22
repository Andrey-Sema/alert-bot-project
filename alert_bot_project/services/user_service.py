import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Optional, List, Set
from sqlalchemy import select, exists
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from alert_bot_project.core_shared.constants import MAX_CUSTOM_TRIGGERS, ODESA_LOCS, OUTSIDE_LOCS, KYIV_TZ
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

    async def toggle_location(self, user_id: int, location_key: str) -> Set[str]:
        user = await get_or_create_user(self.session, user_id)

        if location_key in user.triggers_set:
            await remove_user_trigger(self.session, user_id, location_key)
        else:
            await add_user_trigger(self.session, user_id, location_key)

        await self.session.refresh(user, attribute_names=['triggers_rel'])
        return user.triggers_set

    async def add_custom_trigger(self, user_id: int, trigger_word: str) -> tuple[bool, str]:
        user = await get_or_create_user(self.session, user_id)
        static_keys = set(ODESA_LOCS.keys()) | set(OUTSIDE_LOCS.keys())
        custom_count = len([t for t in user.triggers_set if t not in static_keys])

        # ✅ СЕНЬОР-ФИКС: Убран хардкод цифры 5. Теперь лимит подтягивается динамически из констант
        if custom_count >= MAX_CUSTOM_TRIGGERS:
            return False, f"🚫 Ви вже досягли ліміту у {MAX_CUSTOM_TRIGGERS} кастомних локацій."

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

    async def apply_mute_preset(self, user_id: int, preset: str) -> str:
        """Розраховує час глушіння, координує запис в БД та синхронізує кэш Redis."""
        now_utc = datetime.now(timezone.utc)
        until: Optional[datetime] = None
        ttl_seconds = 0
        text_reply = ""

        if preset == "clear":
            text_reply = "Звук увімкнено"
            await update_user_mute(self.session, user_id, None)
            await self.redis.delete(f"user_mute:{user_id}")
            return text_reply

        elif preset in ("1", "2", "4"):
            hours = int(preset)
            ttl_seconds = hours * 3600
            until = now_utc + timedelta(hours=hours)
            text_reply = f"Сповіщення вимкнено на {preset} год."

        elif preset == "morning":
            kyiv_now = datetime.now(ZoneInfo(KYIV_TZ))
            kyiv_target = kyiv_now.replace(hour=7, minute=0, second=0, microsecond=0)
            if kyiv_now >= kyiv_target:
                kyiv_target += timedelta(days=1)
            until = kyiv_target.astimezone(timezone.utc)
            ttl_seconds = int((until - now_utc).total_seconds())
            text_reply = "Сповіщення вимкнено до ранку"
        else:
            raise ValueError(f"Unknown mute preset: {preset}")

        await update_user_mute(self.session, user_id, until)
        await self.redis.set(f"user_mute:{user_id}", "1", ex=max(1, ttl_seconds))
        return text_reply

    async def acknowledge_alert(self, user_id: int) -> str:
        """Тимчасово глушить сповіщення на 10 хвилин при підтвердженні сигналу."""
        until = datetime.now(timezone.utc) + timedelta(minutes=10)

        await update_user_mute(self.session, user_id, until)
        await self.redis.set(f"user_mute:{user_id}", "1", ex=600)

        return "Сигнал прийнято"