"""Add missing legacy columns, query indexes, and Data API isolation."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision: str = "f96e7f52bedf"
down_revision: str | Sequence[str] | None = "441675746143"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    settings_columns = {column["name"] for column in inspector.get_columns("user_settings")}
    if "potvory" not in settings_columns:
        op.add_column(
            "user_settings",
            sa.Column(
                "potvory",
                ARRAY(sa.String()),
                nullable=False,
                server_default=sa.text("ARRAY['Мопеди', 'Ракети']::VARCHAR[]"),
            ),
        )
    if "muted_until" not in settings_columns:
        op.add_column("user_settings", sa.Column("muted_until", sa.DateTime(timezone=True), nullable=True))
    if "created_at" not in settings_columns:
        op.add_column(
            "user_settings",
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    trigger_columns = {column["name"] for column in inspector.get_columns("user_triggers")}
    if "created_at" not in trigger_columns:
        op.add_column(
            "user_triggers",
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    op.execute("CREATE INDEX IF NOT EXISTS ix_user_settings_potvory_gin ON public.user_settings USING gin (potvory)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_settings_muted_until ON public.user_settings (muted_until)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_triggers_word_user ON public.user_triggers (trigger_word, user_id)")

    # Public is an exposed Supabase schema. The bot uses a direct server-side
    # database role, while Data API roles must have no access to these tables.
    for table in ("user_settings", "user_triggers", "alembic_version"):
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON TABLE public.{table} FROM PUBLIC")
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON TABLE public.user_settings, public.user_triggers FROM anon;
      END IF;
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON TABLE public.user_settings, public.user_triggers FROM authenticated;
      END IF;
    END $$
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.ix_user_triggers_word_user")
    op.execute("DROP INDEX IF EXISTS public.ix_user_settings_muted_until")
    op.execute("DROP INDEX IF EXISTS public.ix_user_settings_potvory_gin")
    # RLS and revoked public grants intentionally remain as a safety boundary.
