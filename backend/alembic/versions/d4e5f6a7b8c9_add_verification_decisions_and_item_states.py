"""add_verification_decisions_and_item_states

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-11-10 16:30:00.000000

Adds verification_decisions audit table and extends cart_items:
- verification_decisions: immutable log of every AI verification event, scores, thresholds, and evidence
- cart_items: previous_status, warning_reason, top1_score, top2_score, matched_product_id
Idempotent creation using SQLAlchemy table and column inspection.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    is_postgres = conn.dialect.name == "postgresql"
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    # 1. Extend cart_items columns idempotently
    if "cart_items" in existing_tables:
        existing_cols = {col["name"] for col in inspector.get_columns("cart_items")}
        with op.batch_alter_table("cart_items") as batch_op:
            if "previous_status" not in existing_cols:
                batch_op.add_column(sa.Column("previous_status", sa.String(length=30), nullable=True, server_default="PENDING"))
            if "warning_reason" not in existing_cols:
                batch_op.add_column(sa.Column("warning_reason", sa.String(length=100), nullable=True))
            if "top1_score" not in existing_cols:
                batch_op.add_column(sa.Column("top1_score", sa.Float(), nullable=True))
            if "top2_score" not in existing_cols:
                batch_op.add_column(sa.Column("top2_score", sa.Float(), nullable=True))
            if "matched_product_id" not in existing_cols:
                batch_op.add_column(sa.Column("matched_product_id", sa.String(length=36), sa.ForeignKey("products.id", name="fk_cart_items_matched_product_id"), nullable=True))

    # 1b. Extend review_cases columns idempotently
    if "review_cases" in existing_tables:
        existing_rc_cols = {col["name"] for col in inspector.get_columns("review_cases")}
        with op.batch_alter_table("review_cases") as batch_op:
            if "top_candidates_json" not in existing_rc_cols:
                batch_op.add_column(sa.Column("top_candidates_json", sa.Text(), nullable=True))

    # 2. Create verification_decisions table idempotently
    if "verification_decisions" not in existing_tables:
        op.create_table(
            "verification_decisions",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("cart_id", sa.String(length=36), nullable=False),
            sa.Column("session_id", sa.String(length=36), nullable=True),
            sa.Column("item_id", sa.String(length=36), nullable=True),
            sa.Column("decision", sa.String(length=50), nullable=False),
            sa.Column("scanned_barcode", sa.String(length=50), nullable=True),
            sa.Column("scanned_product_name", sa.String(length=255), nullable=True),
            sa.Column("matched_product_id", sa.String(length=36), nullable=True),
            sa.Column("matched_product_name", sa.String(length=255), nullable=True),
            sa.Column("top1_score", sa.Float(), nullable=True),
            sa.Column("top2_score", sa.Float(), nullable=True),
            sa.Column("threshold_high", sa.Float(), nullable=False),
            sa.Column("threshold_low", sa.Float(), nullable=False),
            sa.Column("evidence_path", sa.Text(), nullable=True),
            sa.Column("details_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        if is_postgres:
            op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_verification_decisions_cart_id ON verification_decisions (cart_id);"))
            op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_verification_decisions_session_id ON verification_decisions (session_id);"))
            op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_verification_decisions_decision ON verification_decisions (decision);"))
            op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_verification_decisions_created_at ON verification_decisions (created_at);"))
        else:
            op.create_index("ix_verification_decisions_cart_id", "verification_decisions", ["cart_id"])
            op.create_index("ix_verification_decisions_session_id", "verification_decisions", ["session_id"])
            op.create_index("ix_verification_decisions_decision", "verification_decisions", ["decision"])
            op.create_index("ix_verification_decisions_created_at", "verification_decisions", ["created_at"])


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if "verification_decisions" in existing_tables:
        op.drop_table("verification_decisions")

    if "review_cases" in existing_tables:
        existing_rc_cols = {col["name"] for col in inspector.get_columns("review_cases")}
        with op.batch_alter_table("review_cases") as batch_op:
            if "top_candidates_json" in existing_rc_cols:
                batch_op.drop_column("top_candidates_json")

    if "cart_items" in existing_tables:
        existing_cols = {col["name"] for col in inspector.get_columns("cart_items")}
        with op.batch_alter_table("cart_items") as batch_op:
            for col_name in ["matched_product_id", "top2_score", "top1_score", "warning_reason", "previous_status"]:
                if col_name in existing_cols:
                    batch_op.drop_column(col_name)
