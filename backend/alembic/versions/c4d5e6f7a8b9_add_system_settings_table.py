"""add_system_settings_table

Revision ID: c4d5e6f7a8b9
Revises: b2c3d4e5f6a7
Create Date: 2026-11-26 11:00:00.000000

Creates system_settings table for DB-persisted AI thresholds (confidence_high, confidence_low, min_margin).
Idempotent using table inspection.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if "system_settings" not in existing_tables:
        op.create_table(
            "system_settings",
            sa.Column("key", sa.String(length=100), nullable=False),
            sa.Column("value", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("key"),
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "system_settings" in set(inspector.get_table_names()):
        op.drop_table("system_settings")
