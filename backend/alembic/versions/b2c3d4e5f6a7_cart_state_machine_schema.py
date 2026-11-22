"""cart_state_machine_schema

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-11-22 12:00:00.000000

Adds Cart State Machine fields:
- cart_items: crop_embedding, bounding_box, last_known_crop_path
- alerts: violation_type, evidence_path
- cart_sessions: cart_empty_verified, empty_override_by, empty_override_reason
Idempotent creation using SQLAlchemy table and column inspection.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    # 1. cart_items additions
    if "cart_items" in existing_tables:
        existing_cols = {c["name"] for c in inspector.get_columns("cart_items")}
        with op.batch_alter_table("cart_items", schema=None) as batch_op:
            if "crop_embedding" not in existing_cols:
                batch_op.add_column(sa.Column("crop_embedding", sa.Text(), nullable=True))
            if "bounding_box" not in existing_cols:
                batch_op.add_column(sa.Column("bounding_box", sa.Text(), nullable=True))
            if "last_known_crop_path" not in existing_cols:
                batch_op.add_column(sa.Column("last_known_crop_path", sa.Text(), nullable=True))

    # 2. alerts additions
    if "alerts" in existing_tables:
        existing_cols = {c["name"] for c in inspector.get_columns("alerts")}
        with op.batch_alter_table("alerts", schema=None) as batch_op:
            if "violation_type" not in existing_cols:
                batch_op.add_column(sa.Column("violation_type", sa.String(50), nullable=True))
            if "evidence_path" not in existing_cols:
                batch_op.add_column(sa.Column("evidence_path", sa.Text(), nullable=True))

    # 3. cart_sessions additions
    if "cart_sessions" in existing_tables:
        existing_cols = {c["name"] for c in inspector.get_columns("cart_sessions")}
        with op.batch_alter_table("cart_sessions", schema=None) as batch_op:
            if "cart_empty_verified" not in existing_cols:
                batch_op.add_column(
                    sa.Column(
                        "cart_empty_verified",
                        sa.Boolean(),
                        nullable=False,
                        server_default=sa.text("true" if conn.dialect.name == "postgresql" else "1")
                    )
                )
            if "empty_override_by" not in existing_cols:
                batch_op.add_column(sa.Column("empty_override_by", sa.String(36), nullable=True))
            if "empty_override_reason" not in existing_cols:
                batch_op.add_column(sa.Column("empty_override_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if "cart_sessions" in existing_tables:
        existing_cols = {c["name"] for c in inspector.get_columns("cart_sessions")}
        with op.batch_alter_table("cart_sessions", schema=None) as batch_op:
            if "empty_override_reason" in existing_cols:
                batch_op.drop_column("empty_override_reason")
            if "empty_override_by" in existing_cols:
                batch_op.drop_column("empty_override_by")
            if "cart_empty_verified" in existing_cols:
                batch_op.drop_column("cart_empty_verified")

    if "alerts" in existing_tables:
        existing_cols = {c["name"] for c in inspector.get_columns("alerts")}
        with op.batch_alter_table("alerts", schema=None) as batch_op:
            if "evidence_path" in existing_cols:
                batch_op.drop_column("evidence_path")
            if "violation_type" in existing_cols:
                batch_op.drop_column("violation_type")

    if "cart_items" in existing_tables:
        existing_cols = {c["name"] for c in inspector.get_columns("cart_items")}
        with op.batch_alter_table("cart_items", schema=None) as batch_op:
            if "last_known_crop_path" in existing_cols:
                batch_op.drop_column("last_known_crop_path")
            if "bounding_box" in existing_cols:
                batch_op.drop_column("bounding_box")
            if "crop_embedding" in existing_cols:
                batch_op.drop_column("crop_embedding")
