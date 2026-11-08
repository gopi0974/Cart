import logging
from pathlib import Path
from typing import Dict, Any
from alembic.config import Config
from alembic import command
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext
from app.config import settings

logger = logging.getLogger("smartcart.migrations")


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


def run_db_migrations(target: str = "head", connection=None) -> bool:
    """
    Run Alembic migrations automatically up to the specified target (default: 'head').
    Ensures the live database schema is upgraded before serving any requests.
    Returns True if migrations succeeded, False otherwise.
    """
    try:
        logger.info(f"Applying database migrations to target: '{target}'...")
        alembic_cfg = get_alembic_config(connection=connection)
        command.upgrade(alembic_cfg, target)
        logger.info(f"Database migrations successfully applied to '{target}'.")
        return True
    except Exception as e:
        logger.error(f"Failed to apply database migrations to '{target}': {e}", exc_info=True)
        return False


def get_schema_info(connection=None) -> Dict[str, Any]:
    """
    Inspect the database and Alembic scripts to determine current and head revisions.
    """
    from app.database import engine

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
        return {
            "current_revision": current_rev,
            "head_revision": head_rev,
            "is_up_to_date": is_up_to_date
        }
    except Exception as e:
        logger.error(f"Failed to retrieve schema info: {e}")
        return {
            "current_revision": None,
            "head_revision": None,
            "is_up_to_date": False,
            "error": str(e)
        }


def check_schema_health(connection=None) -> bool:
    """
    Returns True only when the database is at the latest Alembic migration (head).
    """
    info = get_schema_info(connection=connection)
    return info["is_up_to_date"]
