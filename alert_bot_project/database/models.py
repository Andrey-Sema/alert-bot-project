from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import BigInteger, String, DateTime, ForeignKey, text
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

    user_setting: Mapped["UserSettings"] = relationship(back_populates="triggers_rel")


class UserSettings(Base):
    """Core user settings schema mapping active categories and silencing rules."""
    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)

    # Fix: Resolved array declaration syntax anomaly using explicit SQL expressions cast mapping
    potvory: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        server_default=text("ARRAY['Мопеди', 'Ракети']::VARCHAR[]")
    )

    muted_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    triggers_rel: Mapped[List[UserTrigger]] = relationship(
        back_populates="user_setting",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    @property
    def triggers_set(self) -> set[str]:
        return {t.trigger_word for t in self.triggers_rel}