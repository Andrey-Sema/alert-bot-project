from datetime import datetime
from typing import Optional, List
from sqlalchemy import BigInteger, String, DateTime, ForeignKey, text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class UserTrigger(Base):
    """Stores verified invariant location keys and multi-word custom phrases."""
    __tablename__ = "user_triggers"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_settings.user_id", ondelete="CASCADE"),
        primary_key=True
    )
    trigger_word: Mapped[str] = mapped_column(String(50), primary_key=True)

    # ✅ ФИКС 1: Добавлено время создания триггера для аудита, логирования и устранения асимметрии моделей.
    # server_default гарантирует генерацию таймстемпа на стороне БД Постгреса.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    user_setting: Mapped["UserSettings"] = relationship(back_populates="triggers_rel")


class UserSettings(Base):
    """Core user settings schema mapping active categories and silencing rules."""
    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)

    potvory: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        server_default=text("ARRAY['Мопеди', 'Ракети']::VARCHAR[]")
    )

    # ✅ ФИКС 2: Добавлен B-Tree индекс (index=True). Теперь реалтайм-выборка get_users_by_trigger_and_category
    # при проверке режима тишины будет выполняться мгновенно через Index Scan, минуя перебор всей таблицы строк.
    muted_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True
    )

    # ✅ ОПТИМИЗАЦИЯ: Перевели дефолт времени на server_default=func.now(),
    # чтобы время создания профиля генерировалось на уровне движка БД, а не на стороне Python.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    triggers_rel: Mapped[List[UserTrigger]] = relationship(
        back_populates="user_setting",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    @property
    def triggers_set(self) -> set[str]:
        """Инкапсулирует связь один-ко-многим в удобный плоский хэш-сет строк триггеров."""
        return {t.trigger_word for t in self.triggers_rel}