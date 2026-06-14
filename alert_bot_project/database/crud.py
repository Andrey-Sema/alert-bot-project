from datetime import datetime, timezone
from typing import Sequence, Optional, List, Set
from sqlalchemy import select, delete, or_, and_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from alert_bot_project.database.models import UserSettings, UserTrigger


async def get_or_create_user(session: AsyncSession, user_id: int) -> UserSettings:
    """Retrieves user settings or populates default layout entries via atomic Upsert."""
    stmt = select(UserSettings).where(UserSettings.user_id == user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if user:
        return user

    insert_stmt = (
        insert(UserSettings)
        .values(user_id=user_id, potvory=["Мопеди", "Ракети"])
        .on_conflict_do_nothing(index_elements=["user_id"])
    )
    await session.execute(insert_stmt)
    await session.flush()

    result = await session.execute(stmt)
    return result.scalar_one()


async def add_user_trigger(session: AsyncSession, user_id: int, trigger_word: str) -> bool:
    """Appends explicit keyword search parameter linked to target user identifier mapping."""
    stmt = (
        insert(UserTrigger)
        .values(user_id=user_id, trigger_word=trigger_word)
        .on_conflict_do_nothing(index_elements=["user_id", "trigger_word"])
    )
    res = await session.execute(stmt)
    return res.rowcount > 0


async def remove_user_trigger(session: AsyncSession, user_id: int, trigger_word: str) -> None:
    """Removes a specific granular custom tracking phrase from database tables."""
    stmt = delete(UserTrigger).where(
        UserTrigger.user_id == user_id,
        UserTrigger.trigger_word == trigger_word
    )
    await session.execute(stmt)


async def update_user_potvory(session: AsyncSession, user_id: int, potvory_list: List[str]) -> None:
    """Updates active categories lists mapping tracking parameters."""
    user = await get_or_create_user(session, user_id)
    user.potvory = potvory_list


async def update_user_mute(session: AsyncSession, user_id: int, muted_until: Optional[datetime]) -> None:
    """Updates user silence duration ceiling threshold limits parameters."""
    user = await get_or_create_user(session, user_id)
    user.muted_until = muted_until


async def get_users_by_trigger_and_category(
        session: AsyncSession,
        location_keys: Set[str],
        category_names: Set[str],
        phrase_candidates: List[str],
        all_static_keys: List[str]
) -> Sequence[UserSettings]:
    """Fetches targeted users using fully indexed queries with strict AND intersection filters."""
    now = datetime.now(timezone.utc)
    base_conditions = or_(UserSettings.muted_until == None, UserSettings.muted_until < now)

    match_conditions = []

    if phrase_candidates:
        match_conditions.append(
            and_(
                UserTrigger.trigger_word.in_(phrase_candidates),
                UserTrigger.trigger_word.not_in(all_static_keys)
            )
        )

    if location_keys and category_names:
        match_conditions.append(
            and_(
                UserTrigger.trigger_word.in_(list(location_keys)),
                UserSettings.potvory.overlap(list(category_names))
            )
        )

    if not match_conditions:
        return []

    stmt = (
        select(UserSettings)
        .join(UserTrigger, UserTrigger.user_id == UserSettings.user_id)
        .where(and_(base_conditions, or_(*match_conditions)))
    )

    result = await session.execute(stmt)
    return result.scalars().unique().all()