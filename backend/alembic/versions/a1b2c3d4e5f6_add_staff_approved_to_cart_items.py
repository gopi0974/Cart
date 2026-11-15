"""add_staff_approved_to_cart_items

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-11-14 14:45:00.000000

Adds staff_approved, staff_approved_at, staff_approved_by to cart_items table.
Idempotent creation using SQLAlchemy table and column inspection.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if "cart_items" in existing_tables:
        existing_cols = {c["name"] for c in inspector.get_columns("cart_items")}
        with op.batch_alter_table("cart_items", schema=None) as batch_op:
            if "staff_approved" not in existing_cols:
                batch_op.add_column(
                    sa.Column(
                        "staff_approved",
                        sa.Boolean(),
                        nullable=False,
                        server_default=sa.text("false" if conn.dialect.name == "postgresql" else "0")
                    )
                )
            if "staff_approved_at" not in existing_cols:
                batch_op.add_column(
                    sa.Column(
                        "staff_approved_at",
                        sa.DateTime(),
                        nullable=True
                    )
                )
            if "staff_approved_by" not in existing_cols:
                batch_op.add_column(
                    sa.Column(
                        "staff_approved_by",
                        sa.String(36),
                        nullable=True
                    )
                )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if "cart_items" in existing_tables:
        existing_cols = {c["name"] for c in inspector.get_columns("cart_items")}
        with op.batch_alter_table("cart_items", schema=None) as batch_op:
            if "staff_approved_by" in existing_cols:
                batch_op.drop_column("staff_approved_by")
            if "staff_approved_at" in existing_cols:
                batch_op.drop_column("staff_approved_at")
            if "staff_approved" in existing_cols:
                batch_op.drop_column("staff_approved")
