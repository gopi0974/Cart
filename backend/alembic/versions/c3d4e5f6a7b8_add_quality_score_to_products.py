"""add_quality_score_to_products

Revision ID: c3d4e5f6a7b8
Revises: b1c2d3e4f5a6
Create Date: 2026-11-09 10:45:00.000000

Adds quality_score column (Float, nullable=True) to products table:
Calculated from frame count, angle coverage, average sharpness, and intra-cluster cosine similarity.
Idempotent creation using SQLAlchemy column inspection.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if "products" in existing_tables:
        existing_cols = {col["name"] for col in inspector.get_columns("products")}
        if "quality_score" not in existing_cols:
            op.add_column(
                "products",
                sa.Column("quality_score", sa.Float(), nullable=True)
            )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if "products" in existing_tables:
        existing_cols = {col["name"] for col in inspector.get_columns("products")}
        if "quality_score" in existing_cols:
            op.drop_column("products", "quality_score")
