"""add_scan_jobs_table

Revision ID: b1c2d3e4f5a6
Revises: f3a4b5c6d7e8
Create Date: 2026-11-09 09:40:00.000000

Adds scan_jobs table for asynchronous 360-degree vision enrollment background tasks:
- id (VARCHAR 36, PK)
- product_id (VARCHAR 36, FK products.id, indexed)
- status (VARCHAR 20, indexed: PENDING, PROCESSING, ENROLLED, FAILED)
- stage (VARCHAR 50)
- stage_message (VARCHAR 255)
- done (INTEGER DEFAULT 0)
- total (INTEGER DEFAULT 0)
- error (TEXT)
- frame_paths_json (TEXT)
- created_at (TIMESTAMP)
- updated_at (TIMESTAMP)
Idempotent creation using IF NOT EXISTS and SQLAlchemy table inspection.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = 'f3a4b5c6d7e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "scan_jobs" not in existing_tables:
        op.create_table(
            "scan_jobs",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("product_id", sa.String(length=36), sa.ForeignKey("products.id"), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
            sa.Column("stage", sa.String(length=50), nullable=False, server_default="QUEUED"),
            sa.Column("stage_message", sa.String(length=255), nullable=True),
            sa.Column("done", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("frame_paths_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        if is_postgres:
            op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_scan_jobs_product_id ON scan_jobs (product_id);"))
            op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_scan_jobs_status ON scan_jobs (status);"))
        else:
            op.create_index("ix_scan_jobs_product_id", "scan_jobs", ["product_id"])
            op.create_index("ix_scan_jobs_status", "scan_jobs", ["status"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if "scan_jobs" in existing_tables:
        op.drop_table("scan_jobs")
