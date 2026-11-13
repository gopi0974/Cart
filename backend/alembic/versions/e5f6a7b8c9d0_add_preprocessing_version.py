"""add_preprocessing_version

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-11-13 17:30:00.000000

Adds preprocessing_version column to:
- product_embeddings: tracks the exact preprocessing algorithm used during enrollment
- verification_decisions: tracks the preprocessing algorithm active at verification decision time
Idempotent creation using SQLAlchemy table and column inspection.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    # 1. Extend product_embeddings with preprocessing_version
    if "product_embeddings" in existing_tables:
        existing_cols = {c["name"] for c in inspector.get_columns("product_embeddings")}
        if "preprocessing_version" not in existing_cols:
            with op.batch_alter_table("product_embeddings", schema=None) as batch_op:
                batch_op.add_column(
                    sa.Column(
                        "preprocessing_version",
                        sa.String(50),
                        nullable=False,
                        server_default="v2_bilinear_224"
                    )
                )

    # 2. Extend verification_decisions with preprocessing_version
    if "verification_decisions" in existing_tables:
        existing_cols = {c["name"] for c in inspector.get_columns("verification_decisions")}
        if "preprocessing_version" not in existing_cols:
            with op.batch_alter_table("verification_decisions", schema=None) as batch_op:
                batch_op.add_column(
                    sa.Column(
                        "preprocessing_version",
                        sa.String(50),
                        nullable=False,
                        server_default="v2_bilinear_224"
                    )
                )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if "verification_decisions" in existing_tables:
        existing_cols = {c["name"] for c in inspector.get_columns("verification_decisions")}
        if "preprocessing_version" in existing_cols:
            with op.batch_alter_table("verification_decisions", schema=None) as batch_op:
                batch_op.drop_column("preprocessing_version")

    if "product_embeddings" in existing_tables:
        existing_cols = {c["name"] for c in inspector.get_columns("product_embeddings")}
        if "preprocessing_version" in existing_cols:
            with op.batch_alter_table("product_embeddings", schema=None) as batch_op:
                batch_op.drop_column("preprocessing_version")

