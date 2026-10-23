import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import settings

logger = logging.getLogger("smartcart.database")

# Database connection arguments and pool configuration
is_sqlite = settings.DATABASE_URL.startswith("sqlite")
connect_args = {"check_same_thread": False} if is_sqlite else {}

engine_kwargs = {
    "connect_args": connect_args,
    "echo": False
}

if not is_sqlite:
    # Production connection pool tuning for Supabase / Neon / Render
    engine_kwargs.update({
        "pool_size": 10,
        "max_overflow": 20,
        "pool_recycle": 300,
        "pool_pre_ping": True,
    })

try:
    engine = create_engine(
        settings.DATABASE_URL,
        **engine_kwargs
    )
except Exception as e:
    logger.error(f"Failed to create database engine with configured URL: {e}. Falling back to SQLite.")
    engine = create_engine(
        f"sqlite:///{settings.BASE_DIR}/smartcart.db",
        connect_args={"check_same_thread": False}
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    """Dependency that yields a database session and safely closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """Create all database tables defined in models and ensure pgvector extension if PostgreSQL."""
    import app.models  # Ensure all models are registered
    
    if not is_sqlite:
        try:
            with engine.connect() as conn:
                conn.execution_options(isolation_level="AUTOCOMMIT")
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                logger.info("PostgreSQL pgvector extension verified or created.")
        except Exception as e:
            logger.warning(f"Note: pgvector extension could not be auto-created ({e}). Fallback vector JSON matching active.")
    else:
        try:
            with engine.connect() as conn:
                conn.execute(text("PRAGMA journal_mode=WAL;"))
        except Exception:
            pass

    Base.metadata.create_all(bind=engine)
    logger.info(f"Database schema initialized on engine: {engine.name}")

