"""Track daily interaction and delivery without storing event contents."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "eb2217aa309b"
down_revision: str | Sequence[str] | None = "f96e7f52bedf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_activity_daily",
        sa.Column(
            "user_id", sa.BigInteger(), sa.ForeignKey("user_settings.user_id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("activity_date", sa.Date(), primary_key=True),
        sa.Column("interacted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("delivered", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_user_activity_daily_date", "user_activity_daily", ["activity_date"])
    op.execute("ALTER TABLE public.user_activity_daily ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON TABLE public.user_activity_daily FROM PUBLIC")
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON TABLE public.user_activity_daily FROM anon;
      END IF;
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON TABLE public.user_activity_daily FROM authenticated;
      END IF;
    END $$
    """)


def downgrade() -> None:
    op.drop_index("ix_user_activity_daily_date", table_name="user_activity_daily")
    op.drop_table("user_activity_daily")
