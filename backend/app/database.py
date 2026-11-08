import logging
from typing import Generator
from fastapi import HTTPException, status
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.config import settings

logger = logging.getLogger("smartcart.database")

database_ok: bool = False
engine = None
SessionLocal = None
Base = declarative_base()

if settings.DATABASE_URL:
    is_sqlite = settings.DATABASE_URL.startswith("sqlite")
    connect_args = {"check_same_thread": False} if is_sqlite else {}

    engine_kwargs = {
        "connect_args": connect_args,
        "echo": False,
    }

    if not is_sqlite:
        # Optimized connection pool configuration for Supabase session pooler
        engine_kwargs.update({
            "pool_size": 5,
            "max_overflow": 5,
            "pool_recycle": 300,
            "pool_pre_ping": True,
            "pool_timeout": 20,
        })

    try:
        engine = create_engine(settings.DATABASE_URL, **engine_kwargs)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        logger.info(f"Database engine created for dialect: {engine.dialect.name}")
    except Exception as e:
        logger.error(f"Failed to create database engine with configured DATABASE_URL: {e}")
        engine = None
        SessionLocal = None
else:
    logger.warning("DATABASE_URL is not set. Database is offline.")

def check_db_health() -> bool:
    """Verify live database connectivity via active pre-ping."""
    global database_ok
    if engine is None:
        database_ok = False
        return False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        database_ok = True
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        database_ok = False
        return False

def get_db() -> Generator[Session, None, None]:
    """
    Dependency that yields a database session.
    If database connection is offline, immediately returns HTTP 503 Service Unavailable.
    Never silently falls back to SQLite in production.
    """
    if SessionLocal is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable: DATABASE_URL not configured. Writes and reads disabled."
        )

    # If currently flagged not OK, perform an active probe to check for recovery
    if not database_ok and not check_db_health():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable: Unable to establish connection to PostgreSQL. Writes and reads disabled."
        )

    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()

def init_db():
    """Run migrations and ensure database schema is up-to-date."""
    global database_ok
    import app.models as _models  # Register all models with Base.metadata
    _ = _models

    if engine is None or not check_db_health():
        logger.error("Cannot initialize database schema: Database engine is unreachable.")
        database_ok = False
        return

    # 1. Run Alembic migrations automatically up to latest revision (head)
    try:
        from app.migrations import run_db_migrations
        mig_ok = run_db_migrations("head")
        if not mig_ok:
            logger.warning("Alembic migrations did not complete cleanly; falling back to Base.metadata.create_all.")
    except Exception as e:
        logger.warning(f"Alembic auto-migration exception ({e}); falling back to Base.metadata.create_all.")

    # 2. Safety fallback for any newly registered models
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as ce:
        logger.warning(f"create_all safety check encountered: {ce}")
    database_ok = True
    logger.info(f"Database schema initialized on engine: {engine.name}")
