import sys
from logging.config import fileConfig
from pathlib import Path
from alembic import context
from sqlalchemy import engine_from_config, pool, create_engine

# Ensure backend directory is in python module path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.config import settings
from app.database import Base, engine as db_engine
import app.models  # Register all models with Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url():
    return config.get_main_option("sqlalchemy.url") or settings.DATABASE_URL


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    # Check if a custom connection was injected into config attributes
    connection = config.attributes.get("connection", None)

    if connection is not None:
        context.configure(
            connection=connection,
            target_metadata=target_metadata
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    # If a specific url is set in the Alembic config (e.g. during tests), use it
    custom_url = config.get_main_option("sqlalchemy.url")
    if custom_url and (db_engine is None or str(db_engine.url) != custom_url):
        connect_args = {"check_same_thread": False} if custom_url.startswith("sqlite") else {}
        connectable = create_engine(custom_url, connect_args=connect_args)
    elif db_engine is not None:
        connectable = db_engine
    else:
        url = get_url()
        connect_args = {"check_same_thread": False} if (url and url.startswith("sqlite")) else {}
        connectable = create_engine(url, connect_args=connect_args)

    with connectable.connect() as conn:
        context.configure(
            connection=conn,
            target_metadata=target_metadata
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
