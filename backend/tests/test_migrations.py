import os
import sys
from pathlib import Path
import pytest

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from alembic.config import Config
from alembic import command
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings
from app.database import get_db
from app.models.cart import Cart
from app.models.session import CartSession
from app.migrations import check_schema_health, get_schema_info
import hmac
import hashlib


@pytest.fixture
def temp_db_setup(tmp_path):
    """
    Creates an isolated SQLite test database and an Alembic Config pointing to it.
    """
    db_file = tmp_path / "migration_test.db"
    db_url = f"sqlite:///{db_file}"

    # Prepare Alembic Config pointing to the temporary test DB
    alembic_ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
    alembic_cfg = Config(str(alembic_ini_path))
    alembic_cfg.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    yield {
        "engine": engine,
        "TestingSessionLocal": TestingSessionLocal,
        "alembic_cfg": alembic_cfg,
        "db_url": db_url
    }

    engine.dispose()


def test_schema_migration_from_old_schema_to_head_and_shopper_pair(temp_db_setup):
    """
    Validates:
    1. Database builds from the OLD schema (baseline d54e41411396 matching b816c12).
    2. OLD schema has cart_sessions without session_token, and no maintenance_flags.
    3. Running alembic upgrade head migrates cleanly.
    4. NEW schema has cart_sessions.session_token and maintenance_flags.
    5. POST /shopper/pair succeeds on the migrated database with session_token.
    6. /health reports schema_ok=True and database_ok=True.
    """
    engine = temp_db_setup["engine"]
    alembic_cfg = temp_db_setup["alembic_cfg"]
    TestingSessionLocal = temp_db_setup["TestingSessionLocal"]

    # Step 1: Upgrade only to baseline revision d54e41411396 (OLD schema)
    command.upgrade(alembic_cfg, "d54e41411396")

    # Step 2: Inspect OLD schema
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert "cart_sessions" in tables, "cart_sessions table should exist in baseline"
    assert "maintenance_flags" not in tables, "maintenance_flags should NOT exist in baseline"

    old_cols = [c["name"] for c in inspector.get_columns("cart_sessions")]
    assert "session_token" not in old_cols, "session_token column must NOT exist in the OLD baseline schema"

    # Verify schema health reports NOT up to date when at baseline
    with engine.connect() as conn:
        assert not check_schema_health(connection=conn)
        info = get_schema_info(connection=conn)
        assert info["current_revision"] == "d54e41411396"
        assert info["head_revision"] is not None
        assert not info["is_up_to_date"]

    # Step 3: Run migrations up to head
    command.upgrade(alembic_cfg, "head")

    # Step 4: Inspect NEW schema
    inspector = inspect(engine)
    new_tables = set(inspector.get_table_names())
    assert "maintenance_flags" in new_tables, "maintenance_flags table must exist after migration"

    new_cols = [c["name"] for c in inspector.get_columns("cart_sessions")]
    assert "session_token" in new_cols, "session_token column must exist on cart_sessions after migration"

    # Step 5: Verify schema is now marked healthy / up to date
    with engine.connect() as conn:
        assert check_schema_health(connection=conn)
        info = get_schema_info(connection=conn)
        assert info["current_revision"] == info["head_revision"]
        assert info["is_up_to_date"]

    # Step 6: Seed a physical cart in this migrated database
    db = TestingSessionLocal()
    try:
        cart = Cart(
            id="test-cart-migration-uuid",
            cart_number="CART-MIG-01",
            qr_code_token="QR-TEST-MIG-01",
            is_enabled=True,
            status="IDLE"
        )
        db.add(cart)
        db.commit()
    finally:
        db.close()

    # Step 7: Override get_db dependency and test POST /shopper/pair
    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    try:
        # Compute valid HMAC signature
        msg = "CART-MIG-01:QR-TEST-MIG-01".encode("utf-8")
        sig = hmac.new(settings.QR_SIGNING_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()[:16]

        pair_payload = {
            "qr_token": "QR-TEST-MIG-01",
            "cart_number": "CART-MIG-01",
            "signature": sig
        }
        response = client.post("/api/v1/shopper/pair", json=pair_payload)
        assert response.status_code == 200, f"Pairing failed with status {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["cart_number"] == "CART-MIG-01"
        assert data["status"] == "ACTIVE"

        # Verify that session_token was saved to the cart_sessions row
        db_check = TestingSessionLocal()
        try:
            persisted_session = db_check.query(CartSession).filter(CartSession.id == data["id"]).first()
            assert persisted_session is not None
            assert persisted_session.session_token is not None
            assert len(persisted_session.session_token) > 20
        finally:
            db_check.close()

    finally:
        app.dependency_overrides.clear()
