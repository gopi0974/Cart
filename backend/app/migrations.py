import logging
from pathlib import Path
from typing import Dict, Any, Optional
import sqlalchemy as sa
from alembic.config import Config
from alembic import command
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext
from app.config import settings

logger = logging.getLogger("smartcart.migrations")

# Baseline revision corresponding to commit b816c12
BASELINE_REVISION: str = "d54e41411396"

# Track last migration error for /health diagnostics
_last_migration_error: Optional[str] = None


def get_alembic_config(connection=None) -> Config:
    """Build and configure Alembic Config object pointing to the backend alembic.ini."""
    backend_dir = Path(__file__).resolve().parent.parent
    alembic_ini_path = backend_dir / "alembic.ini"
    
    if not alembic_ini_path.exists():
        raise FileNotFoundError(f"Alembic configuration file not found at {alembic_ini_path}")

    alembic_cfg = Config(str(alembic_ini_path))
    alembic_cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    
    if settings.DATABASE_URL:
        alembic_cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
        
    if connection is not None:
        alembic_cfg.attributes["connection"] = connection

    return alembic_cfg


def _ensure_baseline_pieces_idempotent(bind_or_conn) -> None:
    """
    Ensure baseline table additions exist idempotently before stamping baseline.
    Checks carts and products for columns added between early commits and b816c12.
    Never executes destructive steps.
    """
    is_connection = isinstance(bind_or_conn, sa.engine.Connection)
    conn = bind_or_conn if is_connection else bind_or_conn.connect()
    
    try:
        is_postgres = conn.dialect.name == "postgresql"
        inspector = sa.inspect(conn)
        existing_tables = set(inspector.get_table_names())

        # Carts table columns
        if "carts" in existing_tables:
            cart_cols = {c["name"] for c in inspector.get_columns("carts")}
            if "device_token_hash" not in cart_cols:
                if is_postgres:
                    conn.execute(sa.text("ALTER TABLE carts ADD COLUMN IF NOT EXISTS device_token_hash VARCHAR(128);"))
                else:
                    conn.execute(sa.text("ALTER TABLE carts ADD COLUMN device_token_hash VARCHAR(128);"))
            if "is_enabled" not in cart_cols:
                if is_postgres:
                    conn.execute(sa.text("ALTER TABLE carts ADD COLUMN IF NOT EXISTS is_enabled BOOLEAN DEFAULT true;"))
                else:
                    conn.execute(sa.text("ALTER TABLE carts ADD COLUMN is_enabled BOOLEAN DEFAULT 1;"))
            if "signed_connect_url" not in cart_cols:
                if is_postgres:
                    conn.execute(sa.text("ALTER TABLE carts ADD COLUMN IF NOT EXISTS signed_connect_url TEXT;"))
                else:
                    conn.execute(sa.text("ALTER TABLE carts ADD COLUMN signed_connect_url TEXT;"))

        # Products table columns
        if "products" in existing_tables:
            prod_cols = {c["name"] for c in inspector.get_columns("products")}
            if "is_deleted" not in prod_cols:
                if is_postgres:
                    conn.execute(sa.text("ALTER TABLE products ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT false;"))
                else:
                    conn.execute(sa.text("ALTER TABLE products ADD COLUMN is_deleted BOOLEAN DEFAULT 0;"))
        
        if is_connection and not conn.in_transaction():
            conn.commit()
    finally:
        if not is_connection:
            conn.close()


def run_db_migrations(target: str = "head", connection=None) -> bool:
    """
    Run Alembic migrations automatically up to the specified target (default: 'head').
    If the database was previously initialized with create_all() and has no alembic_version table:
      1. Ensures any missing baseline pieces are added idempotently.
      2. Stamps the baseline revision (d54e41411396).
      3. Upgrades to head (applying incremental migrations e528b12f6891, f3a4b5c6d7e8).
    Never runs destructive steps. A migration failure sets migration_error and returns False
    without crashing the app.
    """
    global _last_migration_error
    from app.database import engine

    _last_migration_error = None
    try:
        alembic_cfg = get_alembic_config(connection=connection)

        # Helper to inspect table names and stamp if needed
        def check_and_stamp(conn):
            inspector = sa.inspect(conn)
            existing_tables = set(inspector.get_table_names())
            has_app_tables = bool(existing_tables.intersection({"cart_sessions", "products", "users", "carts"}))
            has_alembic_version = "alembic_version" in existing_tables

            if has_app_tables and not has_alembic_version:
                logger.info(
                    "Detected existing database created without Alembic. "
                    f"Applying idempotent baseline pieces and stamping revision '{BASELINE_REVISION}'..."
                )
                _ensure_baseline_pieces_idempotent(conn)
                command.stamp(alembic_cfg, BASELINE_REVISION)
                logger.info(f"Database successfully stamped with baseline revision '{BASELINE_REVISION}'.")

        if connection is not None:
            check_and_stamp(connection)
        elif engine is not None:
            with engine.connect() as conn:
                check_and_stamp(conn)

        logger.info(f"Applying database migrations to target: '{target}'...")
        command.upgrade(alembic_cfg, target)
        logger.info(f"Database migrations successfully applied to '{target}'.")
        _last_migration_error = None
        return True
    except Exception as e:
        _last_migration_error = str(e)
        logger.error(f"Failed to apply database migrations to '{target}': {e}", exc_info=True)
        return False


def get_schema_info(connection=None) -> Dict[str, Any]:
    """
    Inspect the database and Alembic scripts to determine current and head revisions,
    is_up_to_date flag, and short migration_error if any.
    """
    from app.database import engine
    global _last_migration_error

    try:
        alembic_cfg = get_alembic_config(connection=connection)
        script = ScriptDirectory.from_config(alembic_cfg)
        heads = script.get_heads()
        head_rev = heads[0] if heads else None

        current_rev = None
        if connection is not None:
            mig_context = MigrationContext.configure(connection)
            current_rev = mig_context.get_current_revision()
        elif engine is not None:
            with engine.connect() as conn:
                mig_context = MigrationContext.configure(conn)
                current_rev = mig_context.get_current_revision()

        is_up_to_date = bool(head_rev and current_rev == head_rev)
        
        # Determine informative error message if schema is not up to date
        err_msg = _last_migration_error
        if not is_up_to_date and not err_msg:
            if current_rev is None:
                err_msg = f"Database unversioned (alembic_version missing); expected head revision '{head_rev}'."
            else:
                err_msg = f"Database revision '{current_rev}' does not match head revision '{head_rev}'."

        return {
            "current_revision": current_rev,
            "head_revision": head_rev,
            "is_up_to_date": is_up_to_date,
            "migration_error": err_msg if not is_up_to_date else None,
        }
    except Exception as e:
        logger.error(f"Failed to retrieve schema info: {e}")
        return {
            "current_revision": None,
            "head_revision": None,
            "is_up_to_date": False,
            "migration_error": str(e),
        }


def check_schema_health(connection=None) -> bool:
    """
    Returns True only when the database is at the latest Alembic migration (head).
    """
    info = get_schema_info(connection=connection)
    return bool(info.get("is_up_to_date", False))
