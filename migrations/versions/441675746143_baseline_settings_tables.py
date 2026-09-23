"""Baseline existing settings tables without replacing user data."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision: str = "441675746143"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("user_settings"):
        op.create_table(
            "user_settings",
            sa.Column("user_id", sa.BigInteger(), primary_key=True),
            sa.Column(
                "potvory",
                ARRAY(sa.String()),
                nullable=False,
                server_default=sa.text("ARRAY['Мопеди', 'Ракети']::VARCHAR[]"),
            ),
            sa.Column("muted_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    elif "user_id" not in {column["name"] for column in inspector.get_columns("user_settings")}:
        raise RuntimeError("Existing user_settings lacks user_id; manual migration required")

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("user_triggers"):
        op.create_table(
            "user_triggers",
            sa.Column(
                "user_id", sa.BigInteger(), sa.ForeignKey("user_settings.user_id", ondelete="CASCADE"), primary_key=True
            ),
            sa.Column("trigger_word", sa.String(50), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    elif not {"user_id", "trigger_word"}.issubset(
        {column["name"] for column in inspector.get_columns("user_triggers")}
    ):
        raise RuntimeError("Existing user_triggers has incompatible keys; manual migration required")


def downgrade() -> None:
    # This baseline can adopt pre-existing production tables. Never drop their
    # user data when the Alembic version is moved back to base.
    pass
