"""add_session_token_and_maintenance_flags

Revision ID: e528b12f6891
Revises: d54e41411396
Create Date: 2026-11-08 22:30:00.000000

Adds cart_sessions.session_token (VARCHAR 64, indexed) and maintenance_flags table.
Entirely idempotent using IF NOT EXISTS and SQLAlchemy inspection so it safely runs
on databases where columns or tables were already added.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e528b12f6891'
down_revision: Union[str, Sequence[str], None] = 'd54e41411396'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    inspector = sa.inspect(bind)

    # 1. Idempotently add session_token to cart_sessions
    existing_tables = set(inspector.get_table_names())
    if "cart_sessions" in existing_tables:
        existing_cols = {c["name"] for c in inspector.get_columns("cart_sessions")}
        if "session_token" not in existing_cols:
            if is_postgres:
                op.execute(sa.text("ALTER TABLE cart_sessions ADD COLUMN IF NOT EXISTS session_token VARCHAR(64);"))
            else:
                op.add_column("cart_sessions", sa.Column("session_token", sa.String(length=64), nullable=True))

        # Ensure index on session_token
        existing_indexes = {ix["name"] for ix in inspector.get_indexes("cart_sessions")}
        if "ix_cart_sessions_session_token" not in existing_indexes:
            if is_postgres:
                op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_cart_sessions_session_token ON cart_sessions (session_token);"))
            else:
                try:
                    op.create_index("ix_cart_sessions_session_token", "cart_sessions", ["session_token"])
                except Exception:
                    pass

    # 2. Idempotently create maintenance_flags table
    if "maintenance_flags" not in existing_tables:
        if is_postgres:
            op.execute(sa.text("""
                CREATE TABLE IF NOT EXISTS maintenance_flags (
                    flag_name VARCHAR(100) PRIMARY KEY,
                    applied_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    details TEXT
                );
            """))
        else:
            op.create_table(
                "maintenance_flags",
                sa.Column("flag_name", sa.String(length=100), primary_key=True),
                sa.Column("applied_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
                sa.Column("details", sa.Text(), nullable=True)
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "maintenance_flags" in existing_tables:
        op.drop_table("maintenance_flags")

    if "cart_sessions" in existing_tables:
        existing_indexes = {ix["name"] for ix in inspector.get_indexes("cart_sessions")}
        if "ix_cart_sessions_session_token" in existing_indexes:
            op.drop_index("ix_cart_sessions_session_token", table_name="cart_sessions")

        existing_cols = {c["name"] for c in inspector.get_columns("cart_sessions")}
        if "session_token" in existing_cols:
            op.drop_column("cart_sessions", "session_token")

