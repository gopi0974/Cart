"""add_cart_reference_image_path

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-11-26 11:25:00.000000

Adds reference_image_path column to carts table for explicit empty-cart reference storage.
Idempotent using column inspection.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, Sequence[str], None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "carts" in set(inspector.get_table_names()):
        cols = {c["name"] for c in inspector.get_columns("carts")}
        if "reference_image_path" not in cols:
            with op.batch_alter_table("carts", schema=None) as batch_op:
                batch_op.add_column(sa.Column("reference_image_path", sa.Text(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "carts" in set(inspector.get_table_names()):
        cols = {c["name"] for c in inspector.get_columns("carts")}
        if "reference_image_path" in cols:
            with op.batch_alter_table("carts", schema=None) as batch_op:
                batch_op.drop_column("reference_image_path")
