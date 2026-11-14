"""add_item_id_to_alerts

Revision ID: f1a2b3c4d5e6
Revises: e5f6a7b8c9d0
Create Date: 2026-11-14 13:15:00.000000

Adds item_id column to alerts table for per-item alert de-duplication.
Idempotent creation using SQLAlchemy table and column inspection.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if "alerts" in existing_tables:
        existing_cols = {c["name"] for c in inspector.get_columns("alerts")}
        if "item_id" not in existing_cols:
            with op.batch_alter_table("alerts", schema=None) as batch_op:
                batch_op.add_column(
                    sa.Column(
                        "item_id",
                        sa.String(36),
                        nullable=True
                    )
                )
                batch_op.create_index("ix_alerts_item_id", ["item_id"])


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if "alerts" in existing_tables:
        existing_cols = {c["name"] for c in inspector.get_columns("alerts")}
        if "item_id" in existing_cols:
            with op.batch_alter_table("alerts", schema=None) as batch_op:
                batch_op.drop_index("ix_alerts_item_id")
                batch_op.drop_column("item_id")
