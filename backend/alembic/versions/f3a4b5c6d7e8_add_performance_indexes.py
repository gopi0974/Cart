"""add_performance_indexes

Revision ID: f3a4b5c6d7e8
Revises: e528b12f6891
Create Date: 2026-11-08 23:15:00.000000

Adds database indexes on foreign keys and frequently queried filter columns:
- cart_sessions (cart_id, status)
- cart_items (session_id, product_id, status)
- alerts (cart_id, session_id, status)
- transactions (status)
Completely idempotent using IF NOT EXISTS and SQLAlchemy inspection.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3a4b5c6d7e8'
down_revision: Union[str, Sequence[str], None] = 'e528b12f6891'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEXES = [
    ("cart_sessions", "ix_cart_sessions_cart_id", ["cart_id"]),
    ("cart_sessions", "ix_cart_sessions_status", ["status"]),
    ("cart_items", "ix_cart_items_session_id", ["session_id"]),
    ("cart_items", "ix_cart_items_product_id", ["product_id"]),
    ("cart_items", "ix_cart_items_status", ["status"]),
    ("alerts", "ix_alerts_cart_id", ["cart_id"]),
    ("alerts", "ix_alerts_session_id", ["session_id"]),
    ("alerts", "ix_alerts_status", ["status"]),
    ("transactions", "ix_transactions_status", ["status"]),
]


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for table_name, index_name, columns in INDEXES:
        if table_name in existing_tables:
            existing_indexes = {ix["name"] for ix in inspector.get_indexes(table_name)}
            if index_name not in existing_indexes:
                if is_postgres:
                    cols_sql = ", ".join(columns)
                    op.execute(sa.text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({cols_sql});"))
                else:
                    try:
                        op.create_index(index_name, table_name, columns)
                    except Exception:
                        pass


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for table_name, index_name, _ in reversed(INDEXES):
        if table_name in existing_tables:
            existing_indexes = {ix["name"] for ix in inspector.get_indexes(table_name)}
            if index_name in existing_indexes:
                try:
                    op.drop_index(index_name, table_name=table_name)
                except Exception:
                    pass
