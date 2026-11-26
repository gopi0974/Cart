import os

# Provide non-default ephemeral test secrets before app.config is imported by tests
os.environ.setdefault("SECRET_KEY", "pytest-ephemeral-jwt-secret-key-for-local-tests")
os.environ.setdefault("QR_SIGNING_SECRET", "pytest-ephemeral-qr-hmac-secret-for-local-tests")


def require_test_database_url() -> str:
    """
    Live-DB tests must explicitly opt in via TEST_DATABASE_URL.
    Never fall back to DATABASE_URL so tests cannot accidentally touch production/dev DBs.
    """
    test_db_url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not test_db_url:
        import pytest
        pytest.skip("TEST_DATABASE_URL is not set; skipping live database test.")
    return test_db_url


def create_live_test_session():
    """Connects to explicit TEST_DATABASE_URL (never DATABASE_URL), skipping if unset or unreachable."""
    import pytest
    import psycopg2
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    test_db_url = require_test_database_url()
    try:
        conn = psycopg2.connect(test_db_url, connect_timeout=1)
        conn.close()
    except Exception as e:
        pytest.skip(f"TEST_DATABASE_URL is not reachable: {e}")

    engine = create_engine(test_db_url)
    LiveSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, LiveSessionLocal
