from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import and_, delete, exists, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from alert_bot_project.database.models import UserSettings, UserTrigger


async def get_or_create_user(session: AsyncSession, user_id: int) -> UserSettings:
    """Получить пользователя или создать с настройками по умолчанию."""
    stmt = select(UserSettings).where(UserSettings.user_id == user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if user:
        return user

    # ✅ ОПТИМИЗАЦИЯ: Убран избыточный begin_nested().
    # on_conflict_do_nothing не генерирует исключений, транзакция не ломается.
    insert_stmt = (
        insert(UserSettings)
        .values(user_id=user_id, potvory=["Мопеди", "Ракети"])
        .on_conflict_do_nothing(index_elements=["user_id"])
    )
    await session.execute(insert_stmt)

    # ✅ СИНХРОНИЗАЦИЯ: flush() гарантирует, что SQLAlchemy зафиксирует изменения
    # в текущей транзакции перед тем, как выполнять повторный select.
    await session.flush()

    result = await session.execute(stmt)
    return result.scalar_one()


async def add_user_trigger(session: AsyncSession, user_id: int, trigger_word: str) -> bool:
    """Добавить триггер пользователю. Возвращает True если добавлен, False если уже был."""
    stmt = (
        insert(UserTrigger)
        .values(user_id=user_id, trigger_word=trigger_word)
        .on_conflict_do_nothing(index_elements=["user_id", "trigger_word"])
    )
    res = await session.execute(stmt)
    # CursorResult.rowcount не виден статически на базовом типе Result[Any], который
    # объявляет execute(); во время выполнения объект всегда является CursorResult.
    return bool(res.rowcount > 0)  # type: ignore[attr-defined]


async def remove_user_trigger(session: AsyncSession, user_id: int, trigger_word: str) -> None:
    """Удалить триггер пользователя."""
    stmt = delete(UserTrigger).where(UserTrigger.user_id == user_id, UserTrigger.trigger_word == trigger_word)
    await session.execute(stmt)


async def update_user_potvory(session: AsyncSession, user_id: int, potvory_list: list[str]) -> None:
    """Обновить список категорий угроз."""
    user = await get_or_create_user(session, user_id)
    user.potvory = potvory_list


async def update_user_mute(session: AsyncSession, user_id: int, muted_until: datetime | None) -> None:
    """Установить или снять mute."""
    user = await get_or_create_user(session, user_id)
    user.muted_until = muted_until


async def update_user_repeat_count(session: AsyncSession, user_id: int, repeat_count: int) -> None:
    """Обновить количество повторов сигнала тревоги."""
    user = await get_or_create_user(session, user_id)
    user.repeat_count = repeat_count


async def get_users_by_trigger_and_category(
    session: AsyncSession, category_names: set[str], trigger_words: set[str]
) -> Sequence[UserSettings]:
    """
    Найти пользователей для рассылки алерта.

    Если trigger_words пустой — это глобальный пост (выборка всех по категории).
    Если trigger_words содержит ключи — сужаем выборку до конкретных локаций.
    """
    if not category_names:
        return []

    now = datetime.now(UTC)

    # Базовые условия отбора (Режим тишины + Категории)
    conditions = [
        # `== None` тут навмисно: це SQLAlchemy DSL, який генерує `IS NULL` у SQL.
        # `is None` не спрацює — SQLAlchemy перевизначає __eq__ на колонках, а не `is`.
        or_(UserSettings.muted_until == None, UserSettings.muted_until < now),  # noqa: E711
        UserSettings.potvory.overlap(list(category_names)),
    ]

    # ✅ ОПТИМИЗАЦИЯ: Убрано лишнее приведение list(trigger_words).
    # SQLAlchemy в методе .in_() прекрасно переваривает native Python set нативно.
    if trigger_words:
        conditions.append(
            exists().where(
                and_(UserTrigger.user_id == UserSettings.user_id, UserTrigger.trigger_word.in_(trigger_words))
            )
        )

    stmt = select(UserSettings).where(and_(*conditions))
    result = await session.execute(stmt)
    return result.scalars().all()
