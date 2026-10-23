"""
Standalone database initialization and seeding script for SmartCart AI.
Can be executed against local SQLite, Supabase, Neon, Railway, or Render PostgreSQL.
Usage:
    python seed.py
"""
import sys
import logging
from app.config import settings
from app.database import init_db, SessionLocal, engine
from app.utils.seed_data import seed_database

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed")

def main():
    logger.info("=" * 60)
    logger.info("SmartCart AI - Production Database Initialization & Seeding")
    logger.info("=" * 60)
    logger.info(f"Target Database Engine: {engine.name}")
    masked_url = settings.DATABASE_URL
    if "@" in masked_url:
        protocol_user, host_part = masked_url.split("@", 1)
        protocol = protocol_user.split("://")[0]
        masked_url = f"{protocol}://***:***@{host_part}"
    logger.info(f"Connecting to: {masked_url}")

    logger.info("Applying database schemas and pgvector extensions...")
    init_db()

    logger.info("Seeding initial data (1 Admin Account, 3 Test Carts, Catalog & Embeddings)...")
    db = SessionLocal()
    try:
        seed_database(db)
        logger.info("Database successfully seeded and ready for production operations!")
    except Exception as e:
        logger.error(f"Error during database seeding: {e}", exc_info=True)
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    main()
