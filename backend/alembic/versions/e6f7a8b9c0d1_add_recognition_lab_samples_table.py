"""add_recognition_lab_samples_table

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-11-26 12:30:00.000000

Creates recognition_lab_samples table so Recognition Lab metadata is stored in PostgreSQL
instead of local disk samples.json or base64 thumbnails in memory.
Idempotent using table inspection.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'e6f7a8b9c0d1'
down_revision: Union[str, Sequence[str], None] = 'd5e6f7a8b9c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "recognition_lab_samples" not in set(inspector.get_table_names()):
        op.create_table(
            "recognition_lab_samples",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("filename", sa.String(length=255), nullable=False),
            sa.Column("source", sa.String(length=50), nullable=False),
            sa.Column("expected_barcode", sa.String(length=50), nullable=False),
            sa.Column("expected_product_name", sa.String(length=255), nullable=False),
            sa.Column("expected_product_id", sa.String(length=36), nullable=True),
            sa.Column("angle_label", sa.String(length=50), nullable=False),
            sa.Column("image_path", sa.Text(), nullable=True),
            sa.Column("top1_product_name", sa.String(length=255), nullable=True),
            sa.Column("top1_barcode", sa.String(length=50), nullable=True),
            sa.Column("top1_score", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("top2_product_name", sa.String(length=255), nullable=True),
            sa.Column("top2_barcode", sa.String(length=50), nullable=True),
            sa.Column("top2_score", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("score_scanned", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("best_other", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("best_other_product_name", sa.String(length=255), nullable=True),
            sa.Column("best_other_barcode", sa.String(length=50), nullable=True),
            sa.Column("margin", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("is_correct_top1", sa.Boolean(), nullable=True, server_default=sa.text("false")),
            sa.Column("recorded_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_recognition_lab_samples_expected_barcode", "recognition_lab_samples", ["expected_barcode"])


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "recognition_lab_samples" in set(inspector.get_table_names()):
        op.drop_table("recognition_lab_samples")
