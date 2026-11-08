"""baseline_schema

Revision ID: d54e41411396
Revises: 
Create Date: 2026-10-23 14:29:48.646372

Baseline migration matching the initial schema up to commit b816c12.
Designed to be completely idempotent: safely executes on both brand-new databases
and existing live production databases without failing if tables already exist.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

try:
    import pgvector
    import pgvector.sqlalchemy
    HAS_PGVECTOR = True
except ImportError:
    HAS_PGVECTOR = False

# revision identifiers, used by Alembic.
revision: str = 'd54e41411396'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # 1. PostgreSQL Extension: vector
    if is_postgres:
        op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector;"))

    # 2. Users Table
    if "users" not in existing_tables:
        op.create_table(
            "users",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("password_hash", sa.String(length=255), nullable=False),
            sa.Column("full_name", sa.String(length=100), nullable=False),
            sa.Column("role", sa.String(length=20), server_default="STAFF", nullable=False),
            sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_users_email", "users", ["email"], unique=True)

    # 3. Carts Table
    if "carts" not in existing_tables:
        op.create_table(
            "carts",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("cart_number", sa.String(length=20), nullable=False),
            sa.Column("qr_code_token", sa.String(length=100), nullable=False),
            sa.Column("device_token_hash", sa.String(length=128), nullable=True),
            sa.Column("is_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.Column("signed_connect_url", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=20), server_default="IDLE", nullable=False),
            sa.Column("battery_level", sa.Integer(), server_default="100", nullable=False),
            sa.Column("camera_status", sa.String(length=20), server_default="ONLINE", nullable=False),
            sa.Column("last_heartbeat", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_carts_cart_number", "carts", ["cart_number"], unique=True)
        op.create_index("ix_carts_qr_code_token", "carts", ["qr_code_token"], unique=True)
    else:
        # Existing carts table: ensure recently added device/enable columns exist
        cols = {c["name"] for c in inspector.get_columns("carts")}
        if "device_token_hash" not in cols:
            op.add_column("carts", sa.Column("device_token_hash", sa.String(length=128), nullable=True))
        if "is_enabled" not in cols:
            op.add_column("carts", sa.Column("is_enabled", sa.Boolean(), server_default=sa.true(), nullable=False))
        if "signed_connect_url" not in cols:
            op.add_column("carts", sa.Column("signed_connect_url", sa.Text(), nullable=True))

    # 4. Products Table
    if "products" not in existing_tables:
        op.create_table(
            "products",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("barcode", sa.String(length=50), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("brand", sa.String(length=100), nullable=False),
            sa.Column("category", sa.String(length=100), nullable=False),
            sa.Column("price", sa.Float(), nullable=False),
            sa.Column("discount_price", sa.Float(), nullable=True),
            sa.Column("weight_grams", sa.Integer(), server_default="100", nullable=False),
            sa.Column("tax_rate", sa.Float(), server_default="5.0", nullable=False),
            sa.Column("stock_quantity", sa.Integer(), server_default="100", nullable=False),
            sa.Column("primary_image_url", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.Column("is_deleted", sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_products_barcode", "products", ["barcode"], unique=True)
    else:
        prod_cols = {c["name"] for c in inspector.get_columns("products")}
        if "is_deleted" not in prod_cols:
            op.add_column("products", sa.Column("is_deleted", sa.Boolean(), server_default=sa.false(), nullable=False))

    # 5. Product Images Table
    if "product_images" not in existing_tables:
        op.create_table(
            "product_images",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("product_id", sa.String(length=36), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
            sa.Column("image_url", sa.Text(), nullable=False),
            sa.Column("angle_tag", sa.String(length=50), nullable=False),
            sa.Column("is_360_scan", sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )

    # 6. Product Embeddings Table
    if "product_embeddings" not in existing_tables:
        vec_type = pgvector.sqlalchemy.Vector(512) if (is_postgres and HAS_PGVECTOR) else sa.Text()
        op.create_table(
            "product_embeddings",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("product_id", sa.String(length=36), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
            sa.Column("barcode", sa.String(length=50), nullable=False),
            sa.Column("angle_tag", sa.String(length=50), nullable=False),
            sa.Column("embedding_json", sa.Text(), nullable=False),
            sa.Column("embedding_vector", vec_type, nullable=True),
            sa.Column("image_path", sa.Text(), nullable=True),
            sa.Column("model_name", sa.String(length=100), server_default="openai/clip-vit-base-patch32", nullable=False),
            sa.Column("model_version", sa.String(length=50), server_default="v1.0.0-clip", nullable=False),
            sa.Column("vector_dim", sa.Integer(), server_default="512", nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_product_embeddings_barcode", "product_embeddings", ["barcode"])

    # 7. Cart Sessions Table (Baseline Schema: WITHOUT session_token)
    if "cart_sessions" not in existing_tables:
        op.create_table(
            "cart_sessions",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("cart_id", sa.String(length=36), sa.ForeignKey("carts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("customer_phone", sa.String(length=20), nullable=True),
            sa.Column("status", sa.String(length=20), server_default="ACTIVE", nullable=False),
            sa.Column("started_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("ended_at", sa.DateTime(), nullable=True),
            sa.Column("subtotal_amount", sa.Float(), server_default="0.0", nullable=False),
            sa.Column("total_tax", sa.Float(), server_default="0.0", nullable=False),
            sa.Column("total_discount", sa.Float(), server_default="0.0", nullable=False),
            sa.Column("total_amount", sa.Float(), server_default="0.0", nullable=False),
            sa.Column("item_count", sa.Integer(), server_default="0", nullable=False),
        )

    # 8. Cart Items Table
    if "cart_items" not in existing_tables:
        op.create_table(
            "cart_items",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("session_id", sa.String(length=36), sa.ForeignKey("cart_sessions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("product_id", sa.String(length=36), sa.ForeignKey("products.id"), nullable=False),
            sa.Column("quantity", sa.Integer(), server_default="1", nullable=False),
            sa.Column("unit_price", sa.Float(), nullable=False),
            sa.Column("status", sa.String(length=30), server_default="PENDING", nullable=False),
            sa.Column("scanned_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("verified_at", sa.DateTime(), nullable=True),
            sa.Column("confidence_score", sa.Float(), nullable=True),
            sa.Column("verification_evidence_url", sa.Text(), nullable=True),
        )

    # 9. Alerts Table
    if "alerts" not in existing_tables:
        op.create_table(
            "alerts",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("cart_id", sa.String(length=36), sa.ForeignKey("carts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("session_id", sa.String(length=36), sa.ForeignKey("cart_sessions.id", ondelete="SET NULL"), nullable=True),
            sa.Column("alert_type", sa.String(length=50), nullable=False),
            sa.Column("severity", sa.String(length=20), server_default="MEDIUM", nullable=False),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("evidence_snapshot_url", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=20), server_default="OPEN", nullable=False),
            sa.Column("resolved_by", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("resolution_notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
        )

    # 10. Review Cases Table
    if "review_cases" not in existing_tables:
        op.create_table(
            "review_cases",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("alert_id", sa.String(length=36), sa.ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("cart_id", sa.String(length=36), nullable=False),
            sa.Column("scanned_barcode", sa.String(length=50), nullable=True),
            sa.Column("predicted_product_id", sa.String(length=36), sa.ForeignKey("products.id", ondelete="SET NULL"), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("evidence_image_url", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=20), server_default="PENDING", nullable=False),
            sa.Column("assigned_to", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("feedback_saved_for_training", sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )

    # 11. Transactions Table
    if "transactions" not in existing_tables:
        op.create_table(
            "transactions",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("session_id", sa.String(length=36), sa.ForeignKey("cart_sessions.id", ondelete="CASCADE"), unique=True, nullable=False),
            sa.Column("payment_method", sa.String(length=50), server_default="UPI", nullable=False),
            sa.Column("payment_gateway_ref", sa.String(length=100), nullable=True),
            sa.Column("amount", sa.Float(), nullable=False),
            sa.Column("status", sa.String(length=20), server_default="SUCCESS", nullable=False),
            sa.Column("receipt_number", sa.String(length=50), nullable=False),
            sa.Column("receipt_pdf_url", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_transactions_receipt_number", "transactions", ["receipt_number"], unique=True)

    # 12. Audit Logs Table
    if "audit_logs" not in existing_tables:
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("action", sa.String(length=100), nullable=False),
            sa.Column("entity_type", sa.String(length=50), nullable=False),
            sa.Column("entity_id", sa.String(length=36), nullable=True),
            sa.Column("details_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )

    # 13. Model Versions Table
    if "model_versions" not in existing_tables:
        op.create_table(
            "model_versions",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("version_tag", sa.String(length=50), nullable=False),
            sa.Column("accuracy", sa.Float(), server_default="0.984", nullable=False),
            sa.Column("false_positive_rate", sa.Float(), server_default="0.008", nullable=False),
            sa.Column("false_negative_rate", sa.Float(), server_default="0.008", nullable=False),
            sa.Column("confidence_threshold", sa.Float(), server_default="0.85", nullable=False),
            sa.Column("is_active", sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_model_versions_version_tag", "model_versions", ["version_tag"], unique=True)


def downgrade() -> None:
    # Drops all baseline tables
    for table_name in [
        "model_versions", "audit_logs", "transactions", "review_cases",
        "alerts", "cart_items", "cart_sessions", "product_embeddings",
        "product_images", "products", "carts", "users"
    ]:
        try:
            op.drop_table(table_name)
        except Exception:
            pass
