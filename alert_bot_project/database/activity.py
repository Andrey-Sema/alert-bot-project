"""Privacy bounded daily activity aggregates."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from alert_bot_project.database.models import UserActivityDaily


async def record_activity(session: AsyncSession, user_id: int, *, delivered: bool = False) -> None:
    day = datetime.now(UTC).date()
    values = {"user_id": user_id, "activity_date": day, "interacted": not delivered, "delivered": delivered}
    stmt = insert(UserActivityDaily).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "activity_date"],
        set_={
            "interacted": UserActivityDaily.interacted | stmt.excluded.interacted,
            "delivered": UserActivityDaily.delivered | stmt.excluded.delivered,
        },
    )
    await session.execute(stmt)


async def count_active_users(session: AsyncSession, *, as_of: date | None = None) -> tuple[int, int]:
    end = as_of or datetime.now(UTC).date()
    start = end - timedelta(days=29)
    result = await session.execute(
        select(
            func.count(func.distinct(UserActivityDaily.user_id)).filter(UserActivityDaily.interacted),
            func.count(func.distinct(UserActivityDaily.user_id)).filter(UserActivityDaily.delivered),
        ).where(UserActivityDaily.activity_date.between(start, end))
    )
    active, delivered = result.one()
    return int(active), int(delivered)


async def prune_old_activity(session: AsyncSession) -> None:
    cutoff = datetime.now(UTC).date() - timedelta(days=30)
    await session.execute(delete(UserActivityDaily).where(UserActivityDaily.activity_date < cutoff))
    await session.commit()
